import { expect } from "bun:test"
import { once } from "node:events"
import { createServer } from "node:http"
import { chmod, mkdir, readFile, stat, unlink, writeFile } from "node:fs/promises"
import path from "node:path"
import { Effect, Exit } from "effect"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { Global } from "@opencode-ai/core/global"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { ModelV2 } from "@opencode-ai/core/model"
import { Auth } from "../../src/auth"
import { Config } from "../../src/config/config"
import { Provider } from "../../src/provider/provider"
import { TestInstance, tmpdirScoped } from "../fixture/fixture"
import { testEffect } from "../lib/effect"

const it = testEffect(LayerNode.compile(LayerNode.group([Auth.node, Config.node, Provider.node, CrossSpawnSpawner.node])))

it.instance("URL changes require a matching key and cannot expose a staged key to the old model endpoint", () => Effect.gen(function* () {
  const instance = yield* TestInstance
  const control = yield* tmpdirScoped()
  const auth = yield* Auth.Service
  const config = yield* Config.Service
  const provider = yield* Provider.Service
  const configFile = Config.globalConfigFile()
  const authFile = path.join(Global.Path.data, "auth.json")
  // The package preload isolates XDG paths. Refuse to touch a real installation
  // if this regression is invoked without that mandatory test preload.
  for (const file of [configFile, authFile]) {
    if (!file.includes(`opencode-test-data-${process.pid}${path.sep}`)) {
      throw new Error("Model connection regression requires isolated test XDG paths")
    }
  }
  const files = yield* Effect.promise(() => Promise.all([configFile, authFile].map(async file => {
    const info = await stat(file).catch(error => {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined
      throw error
    })
    return { file, content: info ? await readFile(file) : undefined, mode: info ? info.mode & 0o777 : undefined }
  })))
  const environment = {
    OPENCODE_CHANNEL: process.env.OPENCODE_CHANNEL,
    QUANTCODE_UNIFIED_RUNTIME: process.env.QUANTCODE_UNIFIED_RUNTIME,
    QUANTCODE_IDENTITY_SESSION_FILE: process.env.QUANTCODE_IDENTITY_SESSION_FILE,
  }
  yield* Effect.addFinalizer(() => Effect.gen(function* () {
    yield* Effect.promise(async () => {
      try {
        for (const saved of files) {
          if (saved.content === undefined) {
            await unlink(saved.file).catch(error => { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error })
            continue
          }
          await writeFile(saved.file, saved.content)
          await chmod(saved.file, saved.mode!)
        }
      } finally {
        for (const [name, value] of Object.entries(environment)) {
          if (value === undefined) delete process.env[name]
          else process.env[name] = value
        }
      }
    })
    yield* config.invalidate()
  }))

  const identity = {
    session_id: "a".repeat(32), actor_id: "fixture-model-owner", group: "model", role: "analyst",
    workspace_id: "fixture-workspace", workspace_path: instance.directory,
    resource_scopes: ["workspace:read", "workspace:write"], authorized_groups: ["model"],
    issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 300_000).toISOString(),
    identity_source: "ssh_roster",
  }
  const paths: string[] = []
  const authority = createServer((request, response) => {
    paths.push(request.url ?? "")
    if (request.url !== "/session" || request.headers.authorization !== "Bearer fixture-authority-token") {
      response.writeHead(401)
      response.end()
      return
    }
    response.writeHead(200, { "content-type": "application/json" })
    response.end(JSON.stringify(identity))
  })
  yield* Effect.addFinalizer(() => Effect.promise(async () => {
    authority.closeAllConnections()
    if (authority.listening) await new Promise<void>((resolve, reject) => authority.close(error => error ? reject(error) : resolve()))
  }))
  authority.listen(0, "127.0.0.1")
  yield* Effect.promise(() => once(authority, "listening"))
  const address = authority.address()
  if (!address || typeof address === "string") throw new Error("Missing isolated authority address")
  const credential = path.join(control, "identity-session.json")
  yield* Effect.promise(() => writeFile(credential, JSON.stringify({
    gateway: `http://127.0.0.1:${address.port}`, token: "fixture-authority-token",
  }), { mode: 0o600 }))
  process.env.OPENCODE_CHANNEL = "quantcode"
  process.env.QUANTCODE_UNIFIED_RUNTIME = "1"
  process.env.QUANTCODE_IDENTITY_SESSION_FILE = credential

  const id = ProviderV2.ID.make("fixture-url-binding")
  const modelID = ModelV2.ID.make("fixture-model")
  const oldURL = "https://original-model.example/v1"
  const newURL = "https://replacement-model.example/v1"
  const connection = (baseURL: string) => ({ name: "Fixture model connection", npm: "@ai-sdk/openai-compatible",
    options: { baseURL }, models: { [modelID]: { name: "Fixture model", limit: { context: 32000, output: 1024 } } } })
  const initialConfig = JSON.stringify({ provider: { [id]: connection(oldURL) }, model: `${id}/${modelID}` })
  // Existing unbound keys remain usable at their original configured endpoint.
  // This seeds a historical disk record rather than bypassing Auth.set's new
  // requirement for all newly submitted credentials.
  yield* Effect.promise(async () => {
    await mkdir(path.dirname(configFile), { recursive: true })
    await mkdir(path.dirname(authFile), { recursive: true })
    await writeFile(configFile, initialConfig, { mode: 0o600 })
    await writeFile(authFile, JSON.stringify({ [id]: { type: "api", key: "fixture-old-key" } }), { mode: 0o600 })
    await chmod(authFile, 0o600)
  })
  yield* config.invalidate()
  const original = (yield* provider.list())[id]
  expect(original).toBeDefined()
  expect(original.key).toBe("fixture-old-key")
  expect(original.options.baseURL).toBe(oldURL)

  const missingBinding = yield* auth.set(id, { type: "api", key: "fixture-unbound-new-key" }).pipe(Effect.exit)
  expect(Exit.isFailure(missingBinding)).toBe(true)
  const rejected = yield* config.updateGlobal({ provider: { [id]: connection(newURL) } }).pipe(Effect.exit)
  expect(Exit.isFailure(rejected)).toBe(true)
  expect(yield* Effect.promise(() => readFile(configFile, "utf8"))).toBe(initialConfig)
  expect((yield* provider.list())[id].key).toBe("fixture-old-key")

  yield* auth.set(id, { type: "api", key: "fixture-new-key", metadata: { quantcode_base_url: newURL } })
  expect((yield* config.getGlobal()).provider?.[id]?.options?.baseURL).toBe(oldURL)
  // The same Provider service already cached the original connection. Changing
  // Auth first must invalidate that projection and hide the mismatched pair.
  expect((yield* provider.list())[id]).toBeUndefined()
  expect(Exit.isFailure(yield* provider.getModel(id, modelID).pipe(Effect.exit))).toBe(true)

  yield* config.updateGlobal({ provider: { [id]: connection(newURL) } })
  const updated = (yield* provider.list())[id]
  expect(updated.options.baseURL).toBe(newURL)
  expect(updated.key).toBe("fixture-new-key")
  expect((yield* provider.getModel(id, modelID)).providerID).toBe(id)
  // Discovery and configuration use no model request, generation or probe.
  expect(paths.length).toBeGreaterThan(0)
  expect(paths.every(value => value === "/session")).toBe(true)
}), { config: { plugin: [], formatter: false, lsp: false } })

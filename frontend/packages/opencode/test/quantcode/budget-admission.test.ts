import { expect } from "bun:test"
import { Effect, Exit, Stream } from "effect"
import { AppNodeBuilder } from "@opencode-ai/core/effect/app-node-builder"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { Global } from "@opencode-ai/core/global"
import { Database } from "@opencode-ai/core/database/database"
import { SessionProjector } from "@opencode-ai/core/session/projector"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { ModelV2 } from "@opencode-ai/core/model"
import { createServer } from "node:http"
import { once } from "node:events"
import { mkdir, readFile, writeFile, unlink, chmod } from "node:fs/promises"
import path from "node:path"
import { Config } from "../../src/config/config"
import { Provider } from "../../src/provider/provider"
import { Session } from "../../src/session/session"
import { LLM } from "../../src/session/llm"
import { Agent } from "../../src/agent/agent"
import { MessageID, PartID } from "../../src/session/schema"
import { QuantCodeBudget } from "../../src/quantcode/budget"
import { EventV2Bridge } from "../../src/event-v2-bridge"
import { TestInstance, tmpdirScoped } from "../fixture/fixture"
import { testEffect } from "../lib/effect"

const it = testEffect(AppNodeBuilder.build(LayerNode.group([Session.node, LLM.node, Provider.node, Agent.node,
  Config.node, Database.node, SessionProjector.node, EventV2Bridge.node, CrossSpawnSpawner.node])))

it.instance("429 receipts settle before retry; successful usage and unknown failures retain their distinct accounting", () => Effect.gen(function* () {
  const instance = yield* TestInstance
  const control = yield* tmpdirScoped()
  const config = yield* Config.Service
  const provider = yield* Provider.Service
  const sessions = yield* Session.Service
  const llm = yield* LLM.Service
  const agents = yield* Agent.Service
  const configFile = Config.globalConfigFile()
  const authFile = path.join(Global.Path.data, "auth.json")
  const files = yield* Effect.promise(() => Promise.all([configFile, authFile].map(async file => {
    if (!file.includes(`opencode-test-data-${process.pid}${path.sep}`)) throw Error("Test requires isolated XDG paths")
    return { file, content: await readFile(file).catch(error => { if (error.code !== "ENOENT") throw error; return undefined }) }
  })))
  const env = ["OPENCODE_CHANNEL", "QUANTCODE_UNIFIED_RUNTIME", "QUANTCODE_IDENTITY_SESSION_FILE", "QUANTCODE_MODEL_GATEWAY_URL"]
  const before = Object.fromEntries(env.map(key => [key, process.env[key]]))
  yield* Effect.addFinalizer(() => Effect.promise(async () => {
    for (const entry of files) {
      if (entry.content) await writeFile(entry.file, entry.content)
      else await unlink(entry.file).catch(error => { if (error.code !== "ENOENT") throw error })
    }
    for (const [key, value] of Object.entries(before)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }))
  const identity = { session_id: "b".repeat(32), actor_id: "fixture-budget", group: "agent", role: "analyst",
    workspace_id: "fixture-budget-workspace", workspace_path: instance.directory, github_subject: null,
    resource_scopes: [], authorized_groups: ["agent"], identity_source: "ssh_roster",
    issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 300000).toISOString() }
  let mode: "rejected" | "success" | "unknown" = "rejected"
  const requestIDs: string[] = []
  const gateway = createServer((request, response) => {
    if (request.url === "/session") return void response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(identity))
    if (request.url !== "/v1/chat/completions") return void response.writeHead(404).end()
    request.resume()
    const id = String(request.headers["x-quantcode-request-id"])
    requestIDs.push(id)
    if (mode !== "success") return void response.writeHead(429, { "content-type": "application/json", ...(mode === "rejected" ? {
      "x-quantcode-request-id": id, "x-quantcode-request-status": "not-started",
    } : {}) }).end(JSON.stringify({ error: { message: "Too Many Requests" } }))
    response.writeHead(200, { "content-type": "text/event-stream" })
    response.end('data: {"id":"fixture","object":"chat.completion.chunk","created":1,"model":"fixture","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":null}]}\n\ndata: {"id":"fixture","object":"chat.completion.chunk","created":1,"model":"fixture","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\ndata: [DONE]\n\n')
  })
  yield* Effect.addFinalizer(() => Effect.promise(async () => {
    gateway.closeAllConnections()
    if (gateway.listening) await new Promise<void>((resolve, reject) => gateway.close(error => error ? reject(error) : resolve()))
  }))
  gateway.listen(0, "127.0.0.1")
  yield* Effect.promise(() => once(gateway, "listening"))
  const address = gateway.address()
  if (!address || typeof address === "string") throw Error("No fixture gateway")
  const origin = `http://127.0.0.1:${address.port}`
  const credential = path.join(control, "identity.json")
  const id = ProviderV2.ID.make("fixture-budget"), modelID = ModelV2.ID.make("fixture")
  yield* Effect.promise(async () => {
    await writeFile(credential, JSON.stringify({ gateway: origin, token: "fixture-token" }), { mode: 0o600 })
    await mkdir(path.dirname(configFile), { recursive: true })
    await mkdir(path.dirname(authFile), { recursive: true })
    await writeFile(configFile, JSON.stringify({ provider: { [id]: { name: "Fixture budget gateway", npm: "@ai-sdk/openai-compatible", options: { baseURL: origin + "/v1" },
      models: { [modelID]: { name: "Fixture", limit: { context: 65536, output: 4096 } } } } }, model: `${id}/${modelID}` }), { mode: 0o600 })
    await writeFile(authFile, JSON.stringify({ [id]: { type: "api", key: "fixture-key", metadata: { quantcode_base_url: origin + "/v1" } } }), { mode: 0o600 })
    await chmod(authFile, 0o600)
  })
  Object.assign(process.env, { OPENCODE_CHANNEL: "quantcode", QUANTCODE_UNIFIED_RUNTIME: "1",
    QUANTCODE_IDENTITY_SESSION_FILE: credential, QUANTCODE_MODEL_GATEWAY_URL: origin + "/v1" })
  yield* config.invalidate()
  const model = yield* provider.getModel(id, modelID)
  const session = yield* sessions.create({ title: "Budget admission fixture" })
  const agent = yield* agents.get("build")
  if (!agent) throw Error("No fixture agent")
  const user = { id: MessageID.ascending(), sessionID: session.id, role: "user" as const, time: { created: Date.now() },
    agent: "build", model: { providerID: id, modelID } }
  yield* sessions.updateMessage(user)
  yield* sessions.updatePart({ id: PartID.ascending(), sessionID: session.id, messageID: user.id, type: "text", text: "hello" })
  const run = () => llm.stream({ sessionID: session.id, user, model, agent, tools: {}, system: [],
    messages: [{ role: "user", content: "hello" }] }).pipe(Stream.runDrain, Effect.exit)
  for (let i = 0; i < 3; i++) {
    expect(Exit.isFailure(yield* run())).toBe(true)
    expect(yield* QuantCodeBudget.status(session.id)).toMatchObject({ used: 0, reserved: 0, unconfirmed_requests: 0, requests: i + 1 })
  }
  expect(new Set(requestIDs).size).toBe(3)
  mode = "success"
  expect(Exit.isSuccess(yield* run())).toBe(true)
  expect(yield* QuantCodeBudget.status(session.id)).toMatchObject({ used: 12, reserved: 0, unconfirmed_requests: 0, requests: 4 })
  mode = "unknown"
  expect(Exit.isFailure(yield* run())).toBe(true)
  expect(yield* QuantCodeBudget.status(session.id)).toMatchObject({ used: 12, unconfirmed_requests: 1, requests: 5 })
  expect((yield* QuantCodeBudget.status(session.id)).reserved).toBeGreaterThan(0)
}), { config: { formatter: false, lsp: false, mcp: {}, plugin: [] } })

import { expect } from "bun:test"
import { Effect } from "effect"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { AppProcess } from "@opencode-ai/core/process"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { ChildProcess } from "effect/unstable/process"
import { once } from "node:events"
import { createServer } from "node:http"
import { writeFile } from "node:fs/promises"
import path from "node:path"
import { Provider } from "../../src/provider/provider"
import { QuantCodeIdentity } from "../../src/quantcode/identity"
import { QuantCodeLegacyProvider } from "../../src/quantcode/legacy-provider"
import { TestInstance, tmpdirScoped } from "../fixture/fixture"
import { testEffect } from "../lib/effect"

const it = testEffect(LayerNode.compile(LayerNode.group([AppProcess.node, Provider.node, CrossSpawnSpawner.node])))

it.instance("legacy transport decodes a result split across subprocess UTF-8 chunks", () => Effect.gen(function* () {
  const instance = yield* TestInstance
  const control = yield* tmpdirScoped()
  const identity: QuantCodeIdentity.Identity = {
    session_id: "a".repeat(32), actor_id: "fixture-legacy-owner", group: "factor", role: "analyst",
    workspace_id: "fixture-legacy-workspace", workspace_path: instance.directory,
    resource_scopes: [], authorized_groups: ["factor"], identity_source: "ssh_roster",
    issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60_000).toISOString(),
  }
  const authority = createServer((request, response) => {
    if (request.url !== "/session" || request.headers.authorization !== "Bearer fixture-only-token") {
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
  if (!address || typeof address === "string") throw new Error("Missing fixture authority address")
  const credential = path.join(control, "session.json")
  yield* Effect.promise(() => writeFile(credential, JSON.stringify({
    gateway: `http://127.0.0.1:${address.port}`, token: "fixture-only-token",
  }), { mode: 0o600 }))
  const environment = {
    OPENCODE_CHANNEL: "quantcode", QUANTCODE_UNIFIED_RUNTIME: "1",
    QUANTCODE_IDENTITY_SESSION_FILE: credential, QUANTCODE_WORKSPACES_FILE: path.join(control, "workspaces.json"),
  }
  const previous = Object.fromEntries(Object.keys(environment).map(key => [key, process.env[key]]))
  yield* Effect.addFinalizer(() => Effect.sync(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }))
  Object.assign(process.env, environment)
  const payload = { status: "recovered", message: "\u91cf\u5316" }
  // This subprocess only exercises the existing line protocol, without a
  // provider request or an archived task's side effects.
  const command = ChildProcess.make(process.execPath, ["-e", `
    const { createInterface } = require("node:readline")
    const input = createInterface({ input: process.stdin })
    input.once("line", line => {
      const bytes = Buffer.from(JSON.stringify({ type: "result", result: JSON.parse(line) }) + "\\n")
      const boundary = bytes.length - 5
      process.stdout.write(bytes.subarray(0, boundary))
      setTimeout(() => { process.stdout.write(bytes.subarray(boundary)); input.close(); process.stdin.destroy() }, 10)
    })
  `], { cwd: instance.directory })
  expect(yield* QuantCodeLegacyProvider.run(command, payload, identity)).toEqual(payload)
}), { config: { formatter: false, lsp: false, mcp: {}, plugin: [] } })

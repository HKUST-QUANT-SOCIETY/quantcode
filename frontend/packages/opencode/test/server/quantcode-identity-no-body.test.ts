import { expect } from "bun:test"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { Database } from "@opencode-ai/core/database/database"
import { Effect, Layer } from "effect"
import { Session } from "@/session/session"
import { TestInstance } from "../fixture/fixture"
import { testEffect } from "../lib/effect"
import { httpApiLayer, requestInDirectory } from "./httpapi-layer"

const it = testEffect(Layer.mergeAll(LayerNode.compile(LayerNode.group([Session.node, Database.node])), httpApiLayer))

it.instance("identity POSTs accept no body and cannot obtain a group from caller fields", () => Effect.gen(function* () {
  const { directory } = yield* TestInstance
  yield* Effect.acquireRelease(Effect.sync(() => {
    const previous = process.env.QUANTCODE_PUBLIC_KEY_FILE
    // Stop at the real identity configuration boundary; never touch a user's
    // key, credential file, SSH agent, gateway or MCP connection in this test.
    process.env.QUANTCODE_PUBLIC_KEY_FILE = ""
    return previous
  }), previous => Effect.sync(() => {
    if (previous === undefined) delete process.env.QUANTCODE_PUBLIC_KEY_FILE
    else process.env.QUANTCODE_PUBLIC_KEY_FILE = previous
  }))

  for (const operation of ["login", "logout", "challenge"] as const) {
    const endpoint = `/experimental/quantcode/identity/${operation}`
    // This is exactly the SDK's empty-parameters wire representation: POST
    // without a JSON object or Content-Type header.
    const response = yield* requestInDirectory(endpoint, directory, { method: "POST" })
    const body = yield* response.text
    expect(response.status).toBe(400)
    expect(body).not.toMatch(/"kind"\s*:\s*"payload"/i)
    if (operation === "challenge") expect(body).toContain("无法准备登录")

    const injected = yield* requestInDirectory(endpoint, directory, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ group: "risk", role: "admin", actor_id: "caller-controlled" }),
    })
    expect(injected.status).toBe(response.status)
    expect(yield* injected.text).toBe(body)
  }
}), { config: { formatter: false, lsp: false, mcp: {} } })

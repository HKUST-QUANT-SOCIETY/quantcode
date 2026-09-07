import { expect } from "bun:test"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { Database } from "@opencode-ai/core/database/database"
import { Effect, Layer } from "effect"
import { Session } from "@/session/session"
import { TestInstance } from "../fixture/fixture"
import { testEffect } from "../lib/effect"
import { httpApiLayer, requestInDirectory } from "./httpapi-layer"

// Pytest owns an isolated real gateway, roster, key and SSH agent. This suite
// drives the actual HTTP handlers, Python CLI and production MCP subprocess.
const it = testEffect(Layer.mergeAll(LayerNode.compile(LayerNode.group([Session.node, Database.node])), httpApiLayer))
const live = process.env.QUANTCODE_IDENTITY_INTEGRATION === "1" ? it.instance : it.instance.skip

live("real host selects one group, rejects concurrent login and revokes logout", () => Effect.gen(function* () {
  const { directory } = yield* TestInstance
  const call = (path: string, payload?: object) => requestInDirectory(`/experimental/quantcode/${path}`, directory,
    payload ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) } : {})
  const identities = yield* call("identities")
  const listed = yield* identities.json
  expect(listed).toMatchObject({ identities: [{ group: "model", groups: ["model", "factor"] }], session: null })
  const denied = yield* call("identity/login", { group: "risk" })
  expect(denied.status).toBe(400)
  const selected = yield* call("identity/login", { group: "factor" })
  expect(selected.status).toBe(200)
  expect(yield* selected.json).toMatchObject({ group: "factor" })
  expect((yield* call("identity/logout", {})).status).toBe(200)
  const concurrent = yield* Effect.all([call("identity/login", { group: "factor" }), call("identity/login", { group: "model" })], { concurrency: "unbounded" })
  expect(concurrent.map(response => response.status).sort()).toEqual([200, 400])
  const signed = yield* concurrent.find(response => response.status === 200)!.json
  const group = ["factor", "model"][concurrent.findIndex(response => response.status === 200)]
  expect(signed).toMatchObject({ status: "connected", group })
  const before = yield* call("tool?tool=session_context")
  expect(yield* before.json).toMatchObject({ group, authorized_groups: ["model", "factor"] })
  const logout = yield* call("identity/logout", {})
  expect(logout.status).toBe(200)
  expect(yield* logout.json).toEqual({ status: "disconnected" })
  const after = yield* call("tool?tool=session_context")
  expect(yield* after.json).toMatchObject({ error: "QuantCode MCP is not connected" })
  const restored = yield* call("identities")
  expect(yield* restored.json).toMatchObject({ session: null })
  const again = yield* call("identity/logout", {})
  expect(again.status).toBe(200)
}), { config: { formatter: false, lsp: false, mcp: { quantcode: {
  type: "local", enabled: false,
  command: [process.env.QUANTCODE_HOST_PYTHON ?? "python", "-m", "quantcode.mcp_host"],
  environment: { PYTHONPATH: process.env.QUANTCODE_BACKEND_ROOT ?? "", QUANTCODE_ENV: "production",
    QUANTCODE_IDENTITY_SESSION_FILE: process.env.QUANTCODE_IDENTITY_SESSION_FILE ?? "" },
} } } })

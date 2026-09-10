import { expect } from "bun:test"
import { NodeHttpServer, NodeServices } from "@effect/platform-node"
import { Config, Context, Effect, Layer } from "effect"
import { FetchHttpClient, HttpRouter, HttpServer } from "effect/unstable/http"
import { layerWebSocketConstructorGlobal } from "effect/unstable/socket/Socket"
import { Global } from "@opencode-ai/core/global"
import { pollWithTimeout, testEffect } from "../lib/effect"
import { requestInDirectory } from "./httpapi-layer"
import { HttpApiApp } from "../../src/server/routes/instance/httpapi/server"
import { createHash } from "node:crypto"
import { createServer } from "node:http"
import { readFile, stat, writeFile } from "node:fs/promises"
import { connect, disconnect, inspect } from "../../../desktop/src/main/quantcode-identity"
import { tmpdirScoped } from "../fixture/fixture"
import { registerDisposer } from "../../src/effect/instance-registry"
import { QuantCodeIdentity } from "../../src/quantcode/identity"
import { QuantCodeWorkspace } from "../../src/quantcode/workspace"

// Pytest owns an isolated real gateway, roster, key and SSH agent. This suite
// drives the actual HTTP handlers, Python gateway and Electron identity bridge.
class IdentityTestServer extends Context.Service<IdentityTestServer, ReturnType<typeof createServer>>()("@test/IdentityServer") {}
const serverLayer = Layer.unwrap(Effect.gen(function* () {
  const server = yield* IdentityTestServer
  return NodeHttpServer.layer(() => server, { port: 0 })
})).pipe(Layer.provideMerge(Layer.sync(IdentityTestServer, () => createServer())))
const servedRoutes: Layer.Layer<never, Config.ConfigError, HttpServer.HttpServer> = HttpRouter.serve(
  HttpApiApp.routes, { disableListenLog: true, disableLogger: true },
)
const httpApiLayer = servedRoutes.pipe(
  Layer.provide(layerWebSocketConstructorGlobal),
  Layer.provideMerge(HttpServer.layerTestClient.pipe(Layer.provide(FetchHttpClient.layer))),
  Layer.provideMerge(serverLayer),
  Layer.provideMerge(NodeServices.layer),
)
const it = testEffect(httpApiLayer)
const closeTestConnections = Effect.gen(function* () {
  const server = yield* IdentityTestServer
  // All response bodies are consumed before this test scope closes. Bun can
  // still retain idle fetch sockets past node:http's graceful shutdown.
  yield* Effect.addFinalizer(() => Effect.sync(() => server.closeAllConnections()))
})
// Identity routes are host controls and intentionally work before a workspace
// is selected. Running them through the instance fixture would force a
// pre-login workspace authorization and mask the route under test.
const live = process.env.QUANTCODE_IDENTITY_INTEGRATION === "1" ? it.live : it.live.skip

live("real host binds the roster group, rejects group overrides and revokes logout", () => Effect.gen(function* () {
  yield* closeTestConnections
  const directory = Global.Path.config
  const call = (path: string, payload?: object) => Effect.gen(function* () {
    const response = yield* requestInDirectory(`/experimental/quantcode/${path}`, directory,
      payload ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) } : {})
    return { status: response.status, body: yield* response.json }
  })
  const identities = yield* call("identities")
  const listed = identities.body
  expect(listed).toMatchObject({ identities: [{ group: "model", groups: ["model", "factor"] }], session: null })
  const denied = yield* call("identity/login", { group: "risk" })
  expect(denied.status).toBe(400)
  const selected = yield* call("identity/login", {})
  expect(selected.status).toBe(200)
  expect(selected.body).toMatchObject({ group: "model", execution_status: "disconnected" })
  expect((yield* call("identity/logout", {})).status).toBe(200)
  const concurrent = yield* Effect.all([call("identity/login", {}), call("identity/login", {})], { concurrency: "unbounded" })
  expect(concurrent.map(response => response.status).sort()).toEqual([200, 400])
  const signed = concurrent.find(response => response.status === 200)!.body
  const group = "model"
  expect(signed).toMatchObject({ status: "connected", group })
  const before = yield* call("tool?tool=session_context")
  expect(before.body).toMatchObject({ group, authorized_groups: ["model", "factor"] })
  const logout = yield* call("identity/logout", {})
  expect(logout.status).toBe(200)
  expect(logout.body).toEqual({ status: "disconnected", execution_status: "disconnected" })
  const after = yield* call("tool?tool=session_context")
  // After logout the host no longer exposes an execution identity. The route
  // rejects the unauthenticated session before it can produce an MCP payload.
  expect(after.status).toBe(400)
  const restored = yield* call("identities")
  expect(restored.body).toMatchObject({ session: null })
  const again = yield* call("identity/logout", {})
  expect(again.status).toBe(200)
  // The two-step desktop wizard selects a server AND an authorized group.
  // Exercise the real main-process signer and gateway, not a simulated UI grant.
  const host = yield* HttpServer.HttpServer
  const connection = { url: HttpServer.formatAddress(host.address).replace("0.0.0.0", "127.0.0.1").replace("[::]", "[::1]") }
  const secondary = yield* Effect.promise(() => connect(connection, {}, undefined, "factor"))
  expect(secondary).toMatchObject({ status: "connected", group: "factor" })
  expect((yield* call("tool?tool=session_context")).body).toMatchObject({ group: "factor", session_id: secondary.session_id })
  yield* Effect.promise(async () => { await expect(connect(connection, {}, undefined, "risk")).rejects.toThrow() })
  expect((yield* Effect.promise(() => inspect(connection))).session?.session_id).toBe(secondary.session_id)
  yield* Effect.promise(() => disconnect(connection))
}))

// Exercise the exact Electron main-process implementation against the real
// HttpApi and Python gateway. Pytest supplies a separate test SSH agent; this
// never signs with or reads credentials from the user's normal SSH agent.
live("desktop signs locally, rotates host tokens and keeps identity separate from execution", () => Effect.gen(function* () {
  yield* closeTestConnections
  const host = yield* HttpServer.HttpServer
  const connection = { url: HttpServer.formatAddress(host.address).replace("0.0.0.0", "127.0.0.1").replace("[::]", "[::1]"), username: null, password: null }
  const read = () => inspect(connection)
  const first = yield* Effect.promise(read)
  expect(first).toMatchObject({ identities: [{ group: "model" }], session: null })
  const signed = yield* Effect.promise(() => connect(connection))
  expect(signed).toMatchObject({ status: "connected", group: "model", execution_status: "disconnected" })
  expect(Date.parse(signed.expires_at)).toBeGreaterThan(Date.now())
  const filename = process.env.QUANTCODE_IDENTITY_SESSION_FILE!
  const credential = JSON.parse(yield* Effect.promise(() => readFile(filename, "utf8"))) as { gateway: string; token: string }
  expect((yield* Effect.promise(() => stat(filename))).mode & 0o077).toBe(0)
  expect(JSON.stringify(signed)).not.toContain(credential.token)
  expect(JSON.stringify(yield* Effect.promise(read))).not.toContain(credential.token)
  expect(JSON.stringify(signed)).not.toContain("signature")
  expect(JSON.stringify(signed)).not.toContain(process.env.QUANTCODE_PUBLIC_KEY_FILE!)

  const directories = yield* Effect.all([tmpdirScoped({ git: true }), tmpdirScoped({ git: true })])
  const controls = yield* tmpdirScoped()
  yield* Effect.acquireRelease(Effect.sync(() => {
    const previous = process.env.QUANTCODE_WORKSPACES_FILE
    process.env.QUANTCODE_WORKSPACES_FILE = `${controls}/workspaces.json`
    return previous
  }), previous => Effect.sync(() => {
    if (previous === undefined) delete process.env.QUANTCODE_WORKSPACES_FILE
    else process.env.QUANTCODE_WORKSPACES_FILE = previous
  }))
  // Only these temporary checkouts are enrolled for this real gateway member.
  const owner = yield* Effect.promise(QuantCodeIdentity.currentIdentity)
  yield* Effect.promise(() => writeFile(process.env.QUANTCODE_WORKSPACES_FILE!, JSON.stringify({
    version: 1, grants: directories.map(root => ({ actor_id: owner.actor_id, group: owner.group,
      workspace_id: owner.workspace_id, root, access: "write" })),
  }), { mode: 0o600 }))
  const disposed: string[] = []
  yield* Effect.acquireRelease(Effect.sync(() => registerDisposer(async directory => {
    if (directories.includes(directory)) disposed.push(directory)
  })), off => Effect.sync(off))
  const loadWorkspaces = Effect.gen(function* () {
    for (const directory of directories) {
      yield* Effect.promise(() => QuantCodeWorkspace.authorize(directory))
      const response = yield* requestInDirectory("/path", directory)
      const body = yield* response.json
      expect(response.status, JSON.stringify(body)).toBe(200)
      expect(body).toMatchObject({ directory })
    }
    disposed.length = 0
  })
  yield* loadWorkspaces

  const next = yield* Effect.promise(() => connect(connection))
  expect(next.session_id).not.toBe(signed.session_id)
  expect(disposed.toSorted()).toEqual(directories.toSorted())
  const revoked = yield* Effect.promise(() => fetch(new URL("/session", credential.gateway), {
    headers: { Authorization: `Bearer ${credential.token}` }, redirect: "error",
  }))
  expect(revoked.status).toBe(401)
  yield* Effect.promise(() => revoked.arrayBuffer())
  yield* loadWorkspaces
  const login = yield* requestInDirectory("/experimental/quantcode/identity/login", Global.Path.config, {
    method: "POST", headers: { "content-type": "application/json" }, body: "{}",
  })
  yield* login.json
  expect(login.status).toBe(200)
  expect(disposed.toSorted()).toEqual(directories.toSorted())
  yield* loadWorkspaces
  // Hold the actual Python gateway response while the HTTP client disconnects.
  // The credential transaction must retain its permit and still clean up.
  const barrier = process.env.QUANTCODE_IDENTITY_TEST_BARRIER!
  yield* Effect.addFinalizer(() => Effect.promise(() => writeFile(`${barrier}.released`, "1")))
  yield* Effect.promise(() => writeFile(`${barrier}.armed`, "1"))
  const controller = new AbortController()
  const aborted = connect(connection, { signal: controller.signal }).then(() => false, () => true)
  yield* pollWithTimeout(Effect.promise(async () =>
    await Bun.file(`${barrier}.entered`).exists() ? true : undefined), "Gateway never started verification", "5 seconds")
  controller.abort()
  expect(yield* Effect.promise(() => aborted)).toBe(true)
  const overlapping = yield* requestInDirectory("/experimental/quantcode/identity/login", Global.Path.config, {
    method: "POST", headers: { "content-type": "application/json" }, body: "{}",
  })
  yield* overlapping.text
  expect(overlapping.status).toBe(400)
  yield* Effect.promise(() => writeFile(`${barrier}.released`, "1"))
  yield* pollWithTimeout(Effect.sync(() => disposed.length === directories.length ? true : undefined),
    "Disconnected identity request skipped workspace cleanup", "5 seconds")
  expect(disposed.toSorted()).toEqual(directories.toSorted())
  yield* loadWorkspaces
  const invalid = yield* requestInDirectory("/experimental/quantcode/identity/verify", Global.Path.config, {
    method: "POST", headers: { "content-type": "application/json" }, body: "{}",
  })
  yield* invalid.text
  expect(invalid.status).toBe(400)
  expect(disposed).toEqual([])
  expect(yield* Effect.promise(() => disconnect(connection))).toEqual({ status: "disconnected", execution_status: "disconnected" })
  expect(disposed.toSorted()).toEqual(directories.toSorted())
  expect(yield* Effect.promise(read)).toMatchObject({ session: null })
}))

live("desktop cancellation before signing cannot replace the current login", () => Effect.gen(function* () {
  yield* closeTestConnections
  const host = yield* HttpServer.HttpServer
  const connection = { url: HttpServer.formatAddress(host.address).replace("0.0.0.0", "127.0.0.1").replace("[::]", "[::1]") }
  const signed = yield* Effect.promise(() => connect(connection))
  const filename = process.env.QUANTCODE_IDENTITY_SESSION_FILE!
  const before = createHash("sha256").update(yield* Effect.promise(() => readFile(filename))).digest("hex")
  let checks = 0
  const cancelled = yield* Effect.promise(() => connect(connection, { checkTarget: async () => {
    checks += 1
    // Request admission is first; the next checkpoint precedes ssh-add/sign.
    if (checks === 2) throw new Error("test target changed")
  } }).then(() => null, error => error))
  expect(cancelled).toBeInstanceOf(Error)
  expect(checks).toBe(2)
  const after = createHash("sha256").update(yield* Effect.promise(() => readFile(filename))).digest("hex")
  expect(after).toBe(before)
  expect(yield* Effect.promise(() => inspect(connection))).toMatchObject({ session: { session_id: signed.session_id } })
  const controller = new AbortController()
  controller.abort()
  const aborted = yield* Effect.promise(() => connect(connection, { signal: controller.signal }).then(() => null, error => error))
  expect(aborted).toBeInstanceOf(Error)
  yield* Effect.promise(() => disconnect(connection))
}))

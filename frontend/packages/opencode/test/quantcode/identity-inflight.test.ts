import { expect, test } from "bun:test"
import { mkdtemp, writeFile, rm } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { QuantCodeIdentity } from "../../src/quantcode/identity"

test("concurrent identity reads share transport, but later reads still observe revocation", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "qc-identity-inflight-"))
  const filename = path.join(dir, "identity.json"), before = process.env.QUANTCODE_IDENTITY_SESSION_FILE
  let calls = 0, revoked = false
  const entered = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
  const identity = { session_id: "fixture-login", actor_id: "fixture", group: "factor", role: "analyst",
    workspace_id: "fixture", workspace_path: dir, github_subject: null, resource_scopes: ["workspace:read"],
    authorized_groups: ["factor"], identity_source: "ssh_roster", issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60000).toISOString() }
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch() {
    calls++; entered.resolve(); await release.promise
    return Response.json(identity, { status: revoked ? 403 : 200 })
  } })
  try {
    await writeFile(filename, JSON.stringify({ gateway: server.url.origin, token: "fixture-token" }), { mode: 0o600 })
    process.env.QUANTCODE_IDENTITY_SESSION_FILE = filename
    const pending = Promise.all(Array.from({ length: 20 }, () => QuantCodeIdentity.currentIdentity()))
    await entered.promise
    await Bun.sleep(30)
    expect(calls).toBe(1)
    release.resolve()
    const results = await pending
    results[0].resource_scopes.push("must-not-leak")
    expect(results[1].resource_scopes).toEqual(["workspace:read"])
    revoked = true
    await expect(QuantCodeIdentity.currentIdentity()).rejects.toThrow("身份已失效")
    expect(calls).toBe(2)
  } finally {
    release.resolve()
    if (before === undefined) delete process.env.QUANTCODE_IDENTITY_SESSION_FILE
    else process.env.QUANTCODE_IDENTITY_SESSION_FILE = before
    await server.stop(true); await rm(dir, { recursive: true })
  }
})

test("a credential change invalidates every waiter on the old in-flight check", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "qc-identity-rotation-"))
  const filename = path.join(dir, "identity.json"), before = process.env.QUANTCODE_IDENTITY_SESSION_FILE
  const entered = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch() {
    entered.resolve(); await release.promise
    return Response.json({ session_id: "old", actor_id: "fixture", group: "factor", role: "analyst",
      workspace_id: "fixture", workspace_path: dir, resource_scopes: [], authorized_groups: ["factor"], identity_source: "ssh_roster",
      issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60000).toISOString() })
  } })
  try {
    await writeFile(filename, JSON.stringify({ gateway: server.url.origin, token: "old" }), { mode: 0o600 })
    process.env.QUANTCODE_IDENTITY_SESSION_FILE = filename
    const pending = QuantCodeIdentity.currentIdentity().then(() => undefined, error => error)
    await entered.promise
    await writeFile(filename, JSON.stringify({ gateway: server.url.origin, token: "new" }), { mode: 0o600 })
    release.resolve()
    expect((await pending)?.message).toContain("登录身份正在变化")
  } finally {
    release.resolve()
    if (before === undefined) delete process.env.QUANTCODE_IDENTITY_SESSION_FILE
    else process.env.QUANTCODE_IDENTITY_SESSION_FILE = before
    await server.stop(true); await rm(dir, { recursive: true })
  }
})

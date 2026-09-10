import { describe, expect, test } from "bun:test"
import { createHash } from "node:crypto"
import { connect, disconnect, inspect, requireAdminSession } from "./quantcode-identity"

// HTTP boundary regressions need no SSH agent or credentials. The end-to-end
// signature regression lives in opencode/test/server and uses pytest's isolated
// real gateway, roster and disposable SSH agent.
const summary = {
  status: "connected", actor_id: "fixture-member", session_id: "a".repeat(32),
  fingerprint: "SHA256:fixture", group: "model", groups: ["model", "factor"],
  expires_at: "2099-01-01T00:00:00+00:00", execution_status: "disconnected",
}
const identity = { id: "host-default", label: "Fixture SSH identity", fingerprint: summary.fingerprint,
  host: "fixture.example", user: "SSH agent", group: "model", groups: ["model", "factor"] }

describe("desktop identity HTTP bridge", () => {
  test("organization management requires the authority's admin role on the exact signed session", async () => {
    let role = "analyst"
    let sessionId = summary.session_id
    const host = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch(request) {
      const url = new URL(request.url)
      expect(url.pathname).toBe("/experimental/quantcode/tool")
      expect(url.searchParams.get("tool")).toBe("session_context")
      return Response.json({ actor_id: summary.actor_id, group: summary.group, session_id: sessionId, role })
    } })
    try {
      await expect(requireAdminSession({ url: host.url.origin }, summary as never)).rejects.toThrow("授权为管理员")
      role = "admin"
      await requireAdminSession({ url: host.url.origin }, summary as never)
      sessionId = "b".repeat(32)
      await expect(requireAdminSession({ url: host.url.origin }, summary as never)).rejects.toThrow("身份已变化")
    } finally { await host.stop(true) }
  })
  test("preserves the saved host base path, accepts null sidecar credentials and strips credential fields", async () => {
    const requests: string[] = []
    const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch(request) {
      requests.push(new URL(request.url).pathname)
      expect(request.headers.has("authorization")).toBe(false)
      return Response.json({ identities: [{ ...identity, token: "identity-secret" }],
        session: { ...summary, token: "session-secret", signature: "private-signature", public_key_file: "/secret/path" } })
    } })
    try {
      const result = await inspect({ url: `${server.url.origin}/member-fixture`, username: null, password: null })
      expect(requests).toEqual(["/member-fixture/experimental/quantcode/identities"])
      expect(result).toEqual({ identities: [identity], session: summary })
      expect(JSON.stringify(result)).not.toContain("secret")
      expect(JSON.stringify(result)).not.toContain("signature")
    } finally { await server.stop(true) }
  })

  test("rejects an expired or execution-ready claim instead of reporting identity success", async () => {
    let state = { ...summary, expires_at: "2000-01-01T00:00:00+00:00" }
    const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
      fetch: () => Response.json({ identities: [identity], session: state }) })
    try {
      await expect(inspect({ url: server.url.origin })).rejects.toThrow("已经过期")
      state = { ...summary, execution_status: "ready" }
      await expect(inspect({ url: server.url.origin })).rejects.toThrow("尚未认证")
    } finally { await server.stop(true) }
  })

  test("aborted or changed connections never issue a challenge or logout request", async () => {
    let calls = 0
    const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch() {
      calls += 1
      return Response.json({})
    } })
    try {
      const controller = new AbortController()
      controller.abort()
      await expect(connect({ url: server.url.origin }, { signal: controller.signal })).rejects.toThrow()
      await expect(disconnect({ url: server.url.origin }, { checkTarget: async () => { throw new Error("target changed") } })).rejects.toThrow("target changed")
      expect(calls).toBe(0)
    } finally { await server.stop(true) }
  })

  test("rejects untrusted transport and renderer-supplied group without contacting a host", async () => {
    await expect(connect({ url: "http://organization.example" })).rejects.toThrow("HTTPS")
    await expect(connect({ url: "https://user:pass@organization.example" })).rejects.toThrow("HTTPS")
    await expect(connect({ url: "https://organization.example", group: "admin" } as never)).rejects.toThrow("不接受业务组")
  })

  test("does not sign a nonce outside the fixed QuantCode login purpose", async () => {
    const algorithm = Buffer.from("ssh-ed25519")
    const size = Buffer.alloc(4)
    size.writeUInt32BE(algorithm.length)
    const bytes = Buffer.concat([size, algorithm, Buffer.from([0, 0, 0, 32]), Buffer.alloc(32)])
    const key = `ssh-ed25519 ${bytes.toString("base64")}`
    const fingerprint = `SHA256:${createHash("sha256").update(bytes).digest("base64").replace(/=+$/, "")}`
    const paths: string[] = []
    const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch(request) {
      paths.push(new URL(request.url).pathname)
      return Response.json({ challenge_id: "b".repeat(32), public_key: key, fingerprint,
        nonce: JSON.stringify({ purpose: "arbitrary-signature", group: "model", nonce: "x".repeat(43) }),
        ttl_seconds: 60, gateway_origin: "https://gateway.example" })
    } })
    try {
      await expect(connect({ url: server.url.origin })).rejects.toThrow("不属于 QuantCode")
      expect(paths).toEqual(["/experimental/quantcode/identity/challenge"])
    } finally { await server.stop(true) }
  })
})

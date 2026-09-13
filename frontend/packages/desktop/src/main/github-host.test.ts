import { afterEach, expect, test } from "bun:test"
import { prepare, connectCredential, hostRequest } from "./github-host"

const originalFetch = globalThis.fetch
const target = { url: "http://127.0.0.1:48199", username: "quantcode", password: "fixture" }
const signal = () => new AbortController().signal
const identity = () => ({ version: 1 as const, nonce: "nonce", session_id: "session", owner_digest: "a".repeat(64), github_subject: "admin-user", expires_at: Date.now() + 60000 })
afterEach(() => { globalThis.fetch = originalFetch })
function mockFetch(handler: (url: URL, init?: RequestInit) => Response | Promise<Response>) {
  globalThis.fetch = ((input: string | URL | Request, init?: RequestInit) => handler(new URL(String(input)), init)) as typeof fetch
}

test("missing roster binding is identified before attempting credential preparation", async () => {
  const requests: string[] = []
  mockFetch((url, init) => {
    requests.push(url.pathname + url.search)
    expect(new Headers(init?.headers).get("Authorization")).toBe("Basic " + Buffer.from("quantcode:fixture").toString("base64"))
    return Response.json({ actor_id: "quantadmin", role: "admin", github_subject: null })
  })
  await expect(prepare(target, signal())).rejects.toThrow("尚未绑定 GitHub 账号")
  expect(requests).toEqual(["/experimental/quantcode/tool?tool=session_context"])
})

test("distinguishes expired authentication from an absent host endpoint", async () => {
  for (const [status, message] of [[401, "登录已失效"], [403, "无权接入"], [404, "尚未提供"], [500, "请求失败（500）"]] as const) {
    mockFetch(() => Response.json({ _tag: "BadRequest" }, { status }))
    await expect(hostRequest(target, "/experimental/quantcode/github", signal())).rejects.toThrow(message)
  }
})

test("validates GitHub account and renewed host identity before sending the credential", async () => {
  const initial = identity()
  let imports = 0
  let checked = false
  mockFetch((url, init) => {
    if (url.hostname === "api.github.com") return Response.json({ login: "admin-user" })
    if (url.pathname.endsWith("/tool")) return Response.json({ github_subject: "admin-user" })
    if (url.pathname.endsWith("/prepare")) return Response.json(initial)
    expect(checked).toBe(true)
    imports++
    expect(JSON.parse(String(init?.body))).toMatchObject({ session_id: initial.session_id, owner_digest: initial.owner_digest, token: "test-token" })
    return Response.json({ status: "connected", subject: "admin-user" })
  })
  expect(await connectCredential(target, initial, "test-token", signal(), async () => { checked = true })).toMatchObject({ status: "connected" })
  expect(imports).toBe(1)
})

test("does not transmit a local credential when the roster session changes", async () => {
  let imports = 0
  mockFetch((url) => {
    if (url.hostname === "api.github.com") return Response.json({ login: "admin-user" })
    if (url.pathname.endsWith("/tool")) return Response.json({ github_subject: "admin-user" })
    if (url.pathname.endsWith("/prepare")) return Response.json({ ...identity(), session_id: "replacement" })
    imports++
    return Response.json({ status: "connected" })
  })
  await expect(connectCredential(target, identity(), "test-token", signal(), async () => {})).rejects.toThrow("组织身份已变化")
  expect(imports).toBe(0)
})

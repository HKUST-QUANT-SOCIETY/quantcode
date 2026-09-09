import { expect, test } from "bun:test"
import { createOpencodeClient } from "@opencode-ai/sdk/v2/client"
import { prepareResearchWorkspace } from "./workspaces"
import { NativeResponse } from "../../test-native-response"

const roots = [{ directory: "/srv/member/research", access: "write" as const }]
const clientFor = (baseUrl: string) => createOpencodeClient({ baseUrl, fetch: ((...args) => Bun.fetch(...args)) as typeof fetch })

test("rechecks a cached directory against the same live login before selecting it", async () => {
  const requests: URL[] = []
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch(request) {
    const url = new URL(request.url)
    requests.push(url)
    return NativeResponse.json({ login_session_id: "login-one", roots, preferred: "/srv/member/research/project" })
  } })
  try {
    const client = clientFor(server.url.origin)
    const workspace = await prepareResearchWorkspace(client, { preferred: "/srv/member/research/project", current: () => true })
    expect(workspace.defaultDirectory).toBe("/srv/member/research/project")
    expect(await workspace.validate(workspace.defaultDirectory!)).toBe("/srv/member/research/project")
    expect(requests.map(url => url.pathname)).toEqual(["/experimental/quantcode/workspaces", "/experimental/quantcode/workspaces"])
    expect(requests[1].searchParams.get("expected_session_id")).toBe("login-one")
    expect(requests[1].searchParams.get("preferred")).toBe("/srv/member/research/project")
  } finally { await server.stop(true) }
})

test("an invalid remembered directory never becomes an authorized preference", async () => {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
    fetch: () => NativeResponse.json({ login_session_id: "login-one", roots }) })
  try {
    const workspace = await prepareResearchWorkspace(clientFor(server.url.origin), {
      preferred: "/Users/previous-member/private", current: () => true,
    })
    expect(workspace.preferred).toBeUndefined()
    expect(workspace.defaultDirectory).toBe(roots[0].directory)
    await expect(workspace.validate("/Users/previous-member/private")).rejects.toThrow("不再属于")
  } finally { await server.stop(true) }
})

test("multiple authorized roots require a choice and empty roots give an actionable error", async () => {
  let available = [...roots, { directory: "/srv/shared/readonly", access: "read" as const }]
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
    fetch: () => NativeResponse.json({ login_session_id: "login-one", roots: available }) })
  try {
    const client = clientFor(server.url.origin)
    const workspace = await prepareResearchWorkspace(client, { current: () => true })
    expect(workspace.roots).toEqual(available)
    expect(workspace.defaultDirectory).toBeUndefined()
    available = []
    await expect(prepareResearchWorkspace(client, { current: () => true })).rejects.toThrow("连接个人研究宿主")
  } finally { await server.stop(true) }
})

test("old hosts without discovery cannot fall back to cached local directories", async () => {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
    fetch: () => NativeResponse.json({ message: "workspace discovery unavailable" }, { status: 404 }) })
  try {
    await expect(prepareResearchWorkspace(clientFor(server.url.origin), {
      preferred: "/Users/old-project", current: () => true,
    })).rejects.toBeDefined()
  } finally { await server.stop(true) }
})

test("cancelled or changed hosts discard an in-flight roots response", async () => {
  const started = Promise.withResolvers<void>()
  const release = Promise.withResolvers<void>()
  let current = true
  const fetch = async (_request: Request) => {
    started.resolve()
    await release.promise
    return new Response(JSON.stringify({ login_session_id: "login-one", roots }), {
      headers: { "content-type": "application/json" },
    })
  }
  try {
    const pending = prepareResearchWorkspace(createOpencodeClient({ baseUrl: "http://fixture", fetch: fetch as typeof globalThis.fetch }), { current: () => current })
    await started.promise
    current = false
    release.resolve()
    await expect(pending).rejects.toThrow("研究宿主已变化")
  } finally { release.resolve() }
})

test("cancelled final validation cannot select its late result", async () => {
  const started = Promise.withResolvers<void>()
  const release = Promise.withResolvers<void>()
  let current = true
  const fetch = async (request: Request) => {
    if (new URL(request.url).searchParams.has("expected_session_id")) {
      started.resolve()
      await release.promise
    }
    return new Response(JSON.stringify({ login_session_id: "login-one", roots, preferred: roots[0].directory }), {
      headers: { "content-type": "application/json" },
    })
  }
  try {
    const workspace = await prepareResearchWorkspace(createOpencodeClient({ baseUrl: "http://fixture", fetch: fetch as typeof globalThis.fetch }), { current: () => current })
    const pending = workspace.validate(roots[0].directory)
    await started.promise
    current = false
    release.resolve()
    await expect(pending).rejects.toThrow("研究宿主已变化")
  } finally { release.resolve() }
})

test("a login change during the chooser cannot authorize the previous login's draft", async () => {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch(request) {
    const validate = new URL(request.url).searchParams.has("expected_session_id")
    return NativeResponse.json({ login_session_id: validate ? "login-two" : "login-one", roots, preferred: roots[0].directory })
  } })
  try {
    const workspace = await prepareResearchWorkspace(clientFor(server.url.origin), { current: () => true })
    await expect(workspace.validate(roots[0].directory)).rejects.toThrow("不再属于")
  } finally { await server.stop(true) }
})

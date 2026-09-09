import { expect, test } from "bun:test"
import { createOpencodeClient } from "@opencode-ai/sdk/v2/client"
import { projectRuntime, saveProjectAppearance } from "./project-actions"
import { NativeResponse } from "../../test-native-response"

const appearance = { projectID: "fixture-project", directory: "/research/project", name: "Renamed project",
  icon: { color: "cyan", override: "" }, start: "old-startup-command" }
const clientFor = (baseUrl: string) => createOpencodeClient({ baseUrl, fetch: ((...args) => Bun.fetch(...args)) as typeof fetch })

test("native appearance updates never send the saved startup command", async () => {
  const payloads: unknown[] = []
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    payloads.push(await request.json())
    return NativeResponse.json({ id: appearance.projectID })
  } })
  try {
    await saveProjectAppearance(clientFor(server.url.origin), appearance, "native")
    expect(payloads).toEqual([{ name: appearance.name, icon: appearance.icon }])
    expect(JSON.stringify(payloads)).not.toContain("commands")
    expect(JSON.stringify(payloads)).not.toContain(appearance.start)
  } finally { await server.stop(true) }
})

test("legacy appearance updates retain the original startup-setting contract", async () => {
  const payloads: unknown[] = []
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    payloads.push(await request.json())
    return NativeResponse.json({ id: appearance.projectID })
  } })
  try {
    await saveProjectAppearance(clientFor(server.url.origin), appearance, "legacy")
    expect(payloads).toEqual([{ name: appearance.name, icon: appearance.icon, commands: { start: appearance.start } }])
  } finally { await server.stop(true) }
})

test("missing and failed capabilities do not authorize legacy workspace actions", async () => {
  let status = 200
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
    fetch: () => NativeResponse.json({}, { status }) })
  try {
    const client = clientFor(server.url.origin)
    await expect(projectRuntime(client)).rejects.toThrow("无法确认")
    status = 503
    await expect(projectRuntime(client)).rejects.toBeDefined()
  } finally { await server.stop(true) }
})

test("only the explicit false capability selects legacy worktree actions", async () => {
  let native = true
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
    fetch: () => NativeResponse.json({ quantcodeUnifiedRuntime: native }) })
  try {
    const client = clientFor(server.url.origin)
    expect(await projectRuntime(client)).toBe("native")
    native = false
    expect(await projectRuntime(client)).toBe("legacy")
  } finally { await server.stop(true) }
})

test("rejected appearance saves do not report a completed update", async () => {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
    fetch: () => NativeResponse.json({ message: "project access revoked" }, { status: 400 }) })
  try {
    await expect(saveProjectAppearance(clientFor(server.url.origin), appearance, "native")).rejects.toBeDefined()
  } finally { await server.stop(true) }
})

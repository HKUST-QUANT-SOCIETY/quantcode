import { expect, test } from "bun:test"
import { workspaceAccount } from "./account-status"
const now = Date.parse("2026-09-10T10:00:00Z")
const operations = { username: "quantadmin", serverId: "server-c", serverLabel: "Server C", fingerprint: "fixture", expires_at: "2026-09-10T11:00:00Z" }

test("SSH metadata alone cannot claim a completed administrator login", () => {
  const state = workspaceAccount({ view: "server-admin", organizationStatus: "error", actor: "quantadmin", role: "admin", operations }, now)
  expect(state.administrator).toBe(false)
  expect(state.operationsConnected).toBe(false)
  expect(state.showLoginNotice).toBe(true)
})
test("the same verified administrator identity covers every feature view", () => {
  for (const view of ["compose", "settings", "server-admin", "admin", "memory"]) {
    const state = workspaceAccount({ view, organizationStatus: "ready", actor: "quantadmin", role: "admin", operations }, now)
    expect(state.administrator).toBe(true)
    expect(state.label).toBe("quantadmin")
    expect(state.showLoginNotice).toBe(false)
  }
})
test("members cannot inherit administrator rights from cached SSH metadata", () => {
  const state = workspaceAccount({ view: "compose", organizationStatus: "ready", actor: "member", role: "analyst", operations }, now)
  expect(state.administrator).toBe(false)
  expect(state.operationsConnected).toBe(false)
})

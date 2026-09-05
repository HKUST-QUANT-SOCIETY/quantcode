import { describe, expect, test } from "bun:test"
import { createRoot, getOwner, onCleanup } from "solid-js"
import { createTabMemory } from "./tab-memory"
import type { Tab } from "./tabs"
import { draftHref } from "./draft-route"
import { reconcileTabServers } from "./tab-server-reconcile"
import { ServerConnection } from "./server"

describe("tab memory", () => {
  test("keeps state until its tab is removed", () => {
    createRoot((dispose) => {
      const memory = createTabMemory(getOwner())
      let disposed = 0
      const first = memory.ensure("tab", "prompt", () => {
        onCleanup(() => disposed++)
        return { value: "prompt" }
      })

      expect(memory.ensure("tab", "prompt", () => ({ value: "other" }))).toBe(first)
      expect(memory.ensure("other", "prompt", () => ({ value: "other" }))).not.toBe(first)

      memory.remove("tab")
      expect(disposed).toBe(1)
      expect(memory.ensure("tab", "prompt", () => ({ value: "new" }))).not.toBe(first)
      dispose()
    })
  })
})

describe("draft navigation", () => {
  test("carries a one-shot submit intent with an encoded research prompt", () => {
    expect(draftHref("draft/1", "PB & ROE", { submit: true })).toBe(
      "/new-session?draftId=draft%2F1&prompt=PB%20%26%20ROE&submit=true",
    )
  })

  test("keeps ordinary drafts manual", () => {
    expect(draftHref("draft-1", "review this")).toBe(
      "/new-session?draftId=draft-1&prompt=review%20this",
    )
  })
})

describe("tab server reconciliation", () => {
  test("rekeys loopback aliases instead of pruning persisted sessions and drafts", () => {
    const previous = ServerConnection.Key.make("http://localhost:4096")
    const current = ServerConnection.Key.make("http://127.0.0.1:4096")
    const stale = ServerConnection.Key.make("https://stale.example")
    const connections: ServerConnection.Any[] = [{ type: "http", http: { url: current } }]
    const tabs: Tab[] = [
      { type: "session", server: previous, sessionId: "session-1" },
      { type: "draft", server: previous, draftID: "draft-1", directory: "/tmp/project" },
      { type: "session", server: stale, sessionId: "session-stale" },
    ]

    const result = reconcileTabServers(tabs, connections, (tab) =>
      tab.type === "draft" ? `draft:${tab.draftID}` : `${tab.server}:${tab.sessionId}`,
    )

    expect(result.tabs).toEqual([
      { type: "session", server: current, sessionId: "session-1" },
      { type: "draft", server: current, draftID: "draft-1", directory: "/tmp/project" },
    ])
    expect(result.rekeyed.size).toBe(2)
    expect(result.removed.size).toBe(1)
  })
})

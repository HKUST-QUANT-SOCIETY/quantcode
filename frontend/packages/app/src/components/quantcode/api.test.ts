import { describe, expect, test } from "bun:test"
import {
  getQuantCodeSessionContext,
  listQuantCodeCapabilities,
  listQuantCodeSkills,
  listQuantCodeAlgorithms,
  searchQuantCodeMemory,
} from "./api"
import type { OpencodeClient } from "@opencode-ai/sdk/v2"

function clientFor(payload: unknown, calls: unknown[] = []) {
  return {
    quantcode: {
      tool: {
        readOnly: async (input: unknown) => {
          calls.push(input)
          return { data: payload }
        },
      },
    },
  } as unknown as OpencodeClient
}

describe("QuantCode read-only API adapters", () => {
  test("loads skills and forwards the authenticated group", async () => {
    const calls: unknown[] = []
    const skills = await listQuantCodeSkills(
      clientFor({ skills: [{ id: "factor-evaluation", name: "Factor Evaluation" }, { id: "" }] }, calls),
      "factor",
    )
    expect(skills).toEqual([{ id: "factor-evaluation", name: "Factor Evaluation" }])
    expect(calls).toEqual([{ tool: "list_skills", group: "factor" }])
  })

  test("maps memory hits and preserves empty results", async () => {
    const calls: unknown[] = []
    const result = await searchQuantCodeMemory(
      clientFor(
        {
          status: "CONNECTED",
          hits: [{ path: ".quantcode/memory/groups/factor/a.md", scope: "groups", scope_id: "factor", score: 2, snippet: "factor" }],
        },
        calls,
      ),
      "factor",
      5,
    )
    expect(result?.hits[0]).toMatchObject({ id: ".quantcode/memory/groups/factor/a.md", scope: "groups/factor" })
    expect(calls).toEqual([{ tool: "search_memory", query: "factor", limit: "5" }])
  })

  test("does not accept an unbound session context", async () => {
    await expect(getQuantCodeSessionContext(clientFor({ role: "analyst" }))).rejects.toThrow("no bound group")
  })

  test("does not accept an unrecognized server role", async () => {
    await expect(getQuantCodeSessionContext(clientFor({ group: "factor", role: "owner" }))).rejects.toThrow("invalid role")
  })

  test("uses the list capabilities response without fabricating cards", async () => {
    const cards = await listQuantCodeCapabilities(clientFor({ capabilities: [{ id: "contract", name: "Contract" }] }))
    expect(cards).toEqual([{ id: "contract", name: "Contract" }])
  })
})

for (const payload of [undefined, null, {}, { text: "not-json" }, { capabilities: "invalid" }]) {
  test(`rejects unavailable or malformed directory data: ${JSON.stringify(payload)}`, async () => {
    await expect(listQuantCodeCapabilities(clientFor(payload))).rejects.toThrow()
    await expect(listQuantCodeSkills(clientFor(payload), "factor")).rejects.toThrow()
    await expect(listQuantCodeAlgorithms(clientFor(payload))).rejects.toThrow()
    await expect(searchQuantCodeMemory(clientFor(payload), "factor")).rejects.toThrow()
  })
}

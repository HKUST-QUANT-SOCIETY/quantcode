import { describe, expect, test } from "bun:test"
import { QuantCodeSolution } from "../../src/quantcode/solution"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { SessionID } from "../../src/session/schema"

const state = {
  engine: "quantcode", session_id: SessionID.make("ses_new_task"),
  classification: { complexity: "L0", solution_required: false, business_mode: "research",
    execution_strategy: "direct", governance: "ordinary" },
} satisfies QuantCodeGovernance.SolutionState
const document = {
  id: "solution-fixture", goal: "Read the authorized input", status: "draft", version: 1, doc_hash: "fixture-hash",
  acceptance_criteria: ["Report source metadata"], file_impact: [], rounds: [], needs_human: true, trivial_exempt: false,
  created_at: "2026-09-09T00:00:00Z", updated_at: "2026-09-09T00:00:00Z",
} satisfies QuantCodeGovernance.SolutionDocument

describe("Python solution response", () => {
  test("new task with null solution decodes as an absent document", () => {
    const input = { ...state, solution: null }
    const result = QuantCodeSolution.decodeStatus(input, state.session_id)
    expect(result).toEqual(state)
    expect(Object.hasOwn(result, "solution")).toBe(false)
    expect(input.solution).toBeNull()
  })

  test("omitted document and valid draft retain their declared state", () => {
    expect(QuantCodeSolution.decodeStatus(state, state.session_id)).toEqual(state)
    expect(QuantCodeSolution.decodeStatus({ ...state, solution: document }, state.session_id).solution).toEqual(document)
  })

  test.each([undefined, {}, { ...document, version: 0 }, { ...document, status: "approved" }])(
    "malformed document is rejected: %j", solution => {
      expect(() => QuantCodeSolution.decodeStatus({ ...state, solution }, state.session_id)).toThrow()
    },
  )

  test("host errors and another task identity are rejected", () => {
    expect(() => QuantCodeSolution.decodeStatus({ error: "fixture denied" }, state.session_id)).toThrow("fixture denied")
    expect(() => QuantCodeSolution.decodeStatus(state, "ses_other_task")).toThrow("方案服务返回了不同任务。")
  })
})

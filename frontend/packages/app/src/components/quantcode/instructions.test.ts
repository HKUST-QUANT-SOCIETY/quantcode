import { describe, expect, test } from "bun:test"
import { buildComposePrefix, buildResearchInstruction, buildResumeInstruction, buildRecoveryInstruction } from "./instructions"

describe("QuantCode task entry and legacy instructions", () => {
  test("native task admission preserves user text without adding a second executor", () => {
    const task = '  compare "alpha"\nthen review\n'
    expect(buildResearchInstruction({ task, skillLabel: "Risk Review", unifiedRuntime: true })).toBe(task)
    expect(buildComposePrefix(true)).toBe("")
  })

  test("legacy recovery remains tied to the existing checkpoint", () => {
    const instruction = buildRecoveryInstruction("legacy-thread", "checkpoint-7")
    expect(instruction).toContain('"thread_id":"legacy-thread"')
    expect(instruction).toContain('"expected_checkpoint_id":"checkpoint-7"')
    expect(instruction).toContain("Do not start a new task")
  })
  test("quotes user task and forbids user-supplied group", () => {
    const instruction = buildResearchInstruction({
      task: 'compare "alpha"\nthen review',
      skillLabel: "Risk Review",
    })
    expect(instruction).toContain('task: "compare \\"alpha\\"\\nthen review"')
    expect(instruction).toContain("authenticated Session Context")
    expect(instruction).toContain("quantcode_run_agent")
  })

  test("resumes an existing HumanGate instead of starting a new task", () => {
    const instruction = buildResumeInstruction("thread-123", "approve")
    expect(instruction).toContain('thread_id: "thread-123"')
    expect(instruction).toContain('decision: "approve"')
    expect(instruction).toContain("Do not start a new research task")
  })

  test("builds the slash-command prefix from the authenticated session contract", () => {
    const prefix = buildComposePrefix()
    expect(prefix).toContain("group: use the authenticated Session Context")
    expect(prefix).not.toContain('group: "factor"')
    expect(prefix).toEndWith("=== USER TASK ===\n")
  })

  test("carries the P-07 reuse discipline and P-10 solution-first clause on every run instruction", () => {
    const instruction = buildResearchInstruction({ task: "demo", skillLabel: "Risk Review" })
    expect(instruction).toContain("capability catalog")
    expect(instruction).toContain("ask the human first")
    expect(instruction).toContain("draft_solution")
    expect(instruction).toContain("freeze_solution")
    expect(instruction).toContain("Trivial single-point fixes are exempt")
  })
})

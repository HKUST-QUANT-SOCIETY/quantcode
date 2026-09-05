import { describe, expect, test } from "bun:test"
import { SolutionPanelView, deriveSolutionState, type SolutionState } from "./solution-panel"
import type { RunAgentResult, TraceEvent } from "./result-contract"

/** 与 zh.ts 同文案的测试用 t（组件要求注入 i18n，见 quantcode.solution.* keys）。 */
const ZH: Record<string, string> = {
  "quantcode.solution.title": "方案面板",
  "quantcode.solution.empty": "本会话还没有方案。使用 /solution <目标> 发起方案先行流程。",
  "quantcode.solution.draft": "方案未冻结",
  "quantcode.solution.draftHint": "方案未冻结，代码工具不可用——请先讨论并冻结方案（trivial 单点修复可豁免）。",
  "quantcode.solution.frozen": "已冻结",
  "quantcode.solution.rounds": "讨论轮次",
  "quantcode.solution.revision": "修订",
  "quantcode.solution.docHash": "doc_hash 尾号",
  "quantcode.solution.solutionId": "方案 ID",
  "quantcode.solution.verdict.conformant": "实现符合方案",
  "quantcode.solution.verdict.deviation": "存在偏离",
  "quantcode.solution.verdict.needs_human": "需人工裁决",
  "quantcode.solution.deviatedFiles": "偏离文件清单",
}
const t = (key: string) => ZH[key] ?? key

let seq = 0
const toolCall = (tool: string, args: Record<string, unknown>): TraceEvent => ({
  type: "tool_call",
  seq: ++seq,
  data: { tool, args },
})
const toolResult = (tool: string, payload: unknown): TraceEvent => ({
  type: "tool_result",
  seq: ++seq,
  data: { tool, result: typeof payload === "string" ? payload : JSON.stringify(payload) },
})

const docPayload = (over: Record<string, unknown> = {}) => ({
  ok: true,
  solution_id: "sol-pbroe",
  solution_phase: "draft",
  rounds: 0,
  needs_human: false,
  ...over,
})

const mount = (trace: TraceEvent[]) => {
  const view = SolutionPanelView({ t, run: { execution_trace: trace } as RunAgentResult })
  document.body.append(view)
  return view
}

describe("deriveSolutionState", () => {
  test("empty trace → bare state", () => {
    expect(deriveSolutionState(undefined)).toEqual<SolutionState>({ rounds: [], deviations: [] })
  })

  test("draft → rounds → frozen lifecycle from tool events", () => {
    const state = deriveSolutionState([
      toolCall("draft_solution", { goal: "PB–ROE 中性化因子研究" }),
      toolResult("draft_solution", docPayload()),
      toolCall("revise_solution", { doc_id: "sol-pbroe", feedback: "对照组选股域要剔 ST", revision: "补 2.3 节" }),
      toolResult("revise_solution", docPayload({ rounds: 1 })),
      toolCall("freeze_solution", { doc_id: "sol-pbroe", confirm: true }),
      toolResult("freeze_solution", docPayload({ solution_phase: "frozen", rounds: 1, doc_hash: "a1b2c3d4e5f6" })),
    ])
    expect(state.solutionId).toBe("sol-pbroe")
    expect(state.phase).toBe("frozen")
    expect(state.rounds).toEqual([{ feedback: "对照组选股域要剔 ST", revision: "补 2.3 节" }])
    expect(state.docHash).toBe("a1b2c3d4e5f6")
  })

  test("consistency verdict + deviations list (shape-detected across payloads)", () => {
    const state = deriveSolutionState([
      toolResult("draft_solution", docPayload({ solution_phase: "frozen", doc_hash: "a1b2c3d4e5f6" })),
      toolResult("solution_status", {
        verdict: "deviation",
        deviations: ["factors/extra_alpha.py", "runner/patch.py"],
        missing: [],
      }),
    ])
    expect(state.verdict).toBe("deviation")
    expect(state.deviations).toEqual(["factors/extra_alpha.py", "runner/patch.py"])
  })

  test("needs_human flag follows the last doc payload (false after freeze clears it)", () => {
    const state = deriveSolutionState([
      toolResult("solution_status", docPayload({ needs_human: true })),
      toolResult("solution_status", docPayload({ solution_phase: "frozen", needs_human: false })),
    ])
    expect(state.needsHuman).toBe(false)
    expect(state.phase).toBe("frozen")
  })

  test("truncated (non-JSON) tool_result is skipped without poisoning state", () => {
    const state = deriveSolutionState([
      toolResult("draft_solution", '{"ok": true, "solution_id": "sol-trunc'),
      toolResult("draft_solution", docPayload()),
    ])
    expect(state.solutionId).toBe("sol-pbroe")
  })
})

describe("SolutionPanelView", () => {
  test("no solution → empty state pointing at /solution", () => {
    const view = mount([])
    expect(view.querySelector(".qc-solution-empty h3")?.textContent).toBe("方案面板")
    expect(view.querySelector(".qc-solution-empty p")?.textContent).toContain("/solution")
    view.remove()
  })

  test("draft state: yellow dot + 未冻结 hint banner", () => {
    const view = mount([toolResult("draft_solution", docPayload())])
    expect(view.querySelector(".qc-solution-dot")).toBeTruthy()
    const badge = view.querySelector(".qc-solution-draft .qc-status")?.textContent
    expect(badge).toBe("方案未冻结")
    const hint = view.querySelector(".qc-solution-draft-hint")?.textContent
    expect(hint).toContain("代码工具不可用")
    expect(hint).toContain("trivial 单点修复可豁免")
    view.remove()
  })

  test("rounds render as feedback timeline with revision notes", () => {
    const view = mount([
      toolResult("draft_solution", docPayload()),
      toolCall("revise_solution", { doc_id: "sol-pbroe", feedback: "对照组要剔 ST", revision: "补 2.3 节" }),
      toolResult("revise_solution", docPayload({ rounds: 1 })),
    ])
    const rows = view.querySelectorAll(".qc-solution-rounds .qc-event-row")
    expect(rows).toHaveLength(1)
    expect(rows[0].querySelector(".qc-event-index")?.textContent).toBe("01")
    expect(rows[0].querySelector("strong")?.textContent).toBe("对照组要剔 ST")
    expect(rows[0].textContent).toContain("修订：补 2.3 节")
    view.remove()
  })

  test("frozen: lock badge + doc_hash tail", () => {
    const view = mount([
      toolResult("draft_solution", docPayload()),
      toolResult("freeze_solution", docPayload({ solution_phase: "frozen", doc_hash: "a1b2c3d4e5f6" })),
    ])
    expect(view.querySelector(".qc-solution-phase .qc-status")?.textContent).toContain("已冻结")
    expect(view.querySelector(".qc-solution-doc-hash")?.textContent).toBe("…c3d4e5f6")
    expect(view.querySelector(".qc-solution-draft-hint")).toBeNull()
    view.remove()
  })

  test("verdict badges: conformant green, deviation yellow with deviated files, needs_human red", () => {
    const base = [toolResult("draft_solution", docPayload({ solution_phase: "frozen", doc_hash: "a1b2c3d4e5f6" }))]

    const ok = mount([...base, toolResult("solution_status", { verdict: "conformant", deviations: [] })])
    expect(ok.querySelector(".qc-solution-verdict-badge")?.classList.contains("qc-status-completed")).toBe(true)
    expect(ok.querySelector(".qc-solution-verdict-badge")?.textContent).toContain("实现符合方案")
    ok.remove()

    const dev = mount([
      ...base,
      toolResult("solution_status", { verdict: "deviation", deviations: ["factors/extra_alpha.py"] }),
    ])
    const devBadge = dev.querySelector(".qc-solution-verdict-badge")!
    expect(devBadge.classList.contains("qc-status-waiting_for_human")).toBe(true)
    expect(devBadge.textContent).toContain("存在偏离")
    const deviations = dev.querySelector(".qc-solution-deviations")!
    expect(deviations.querySelector("summary")?.textContent).toContain("偏离文件清单")
    expect(deviations.textContent).toContain("factors/extra_alpha.py")
    dev.remove()

    const human = mount([...base, toolResult("solution_status", { verdict: "needs_human", deviations: [] })])
    expect(human.querySelector(".qc-solution-verdict-badge")?.classList.contains("qc-status-error")).toBe(true)
    human.remove()
  })

  test("needs_human doc flag (max rounds, no verdict) surfaces red badge", () => {
    const view = mount([toolResult("solution_status", docPayload({ needs_human: true }))])
    expect(view.querySelector(".qc-solution-verdict-badge")?.classList.contains("qc-status-error")).toBe(true)
    view.remove()
  })
})

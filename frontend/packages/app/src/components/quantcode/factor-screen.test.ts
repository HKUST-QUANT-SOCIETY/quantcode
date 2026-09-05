import { describe, expect, test } from "bun:test"
import { FactorFlowView, flowNodeName } from "./factor-screen"
import type { RunAgentResult } from "./result-contract"

function runWith(overrides: Partial<RunAgentResult>): RunAgentResult {
  return { status: "completed", ...overrides }
}

function toolRun(): RunAgentResult {
  return runWith({
    execution_trace: ["match_gen", "gen_schema", "autoeval"].flatMap((tool, i) => [
      { type: "tool_call", iteration: 1, seq: i * 2, data: { tool_name: tool } },
      { type: "tool_result", iteration: 1, seq: i * 2 + 1, data: { tool_name: tool } },
    ]),
    output_data: { ic_mean: 0.05 },
    artifacts: ["artifact://factor/eval.json"],
  })
}

describe("FactorFlowView", () => {
  test("empty run renders two empty sections with text", () => {
    const el = FactorFlowView({ run: null })
    expect(el.className).toBe("qc-factor-flow")
    expect(el.querySelectorAll(".qc-metrics-empty").length).toBe(2)
    expect(el.textContent).toContain("暂无研究运行")
    expect(el.querySelectorAll(".qc-factor-node").length).toBe(0)
    el.remove()
  })

  test("run without output_data shows node rail but empty metrics", () => {
    const el = FactorFlowView({ run: runWith({ execution_trace: toolRun().execution_trace }) })
    expect(el.querySelectorAll(".qc-factor-node").length).toBe(3)
    expect(el.querySelectorAll(".qc-metrics-empty").length).toBe(1)
    el.remove()
  })

  test("three finished tool calls produce 3 nodes, 2 connectors, all done", () => {
    const el = FactorFlowView({ run: toolRun() })
    const nodes = [...el.querySelectorAll(".qc-factor-node")]
    expect(nodes.length).toBe(3)
    expect(nodes.filter((node) => node.classList.contains("is-done")).length).toBe(3)
    expect(el.querySelectorAll(".qc-factor-node:not(:last-child)").length).toBe(2)
    expect(nodes[0]!.textContent).toContain("match_main")
    expect(nodes[1]!.textContent).toContain("gen_schema")
    expect(nodes[2]!.textContent).toContain("autoeval")
    expect(nodes[0]!.textContent).toContain("完成 ✓")
    el.remove()
  })

  test("fake output_data ic_mean renders metric card value and 0.03 threshold progress", () => {
    const el = FactorFlowView({ run: toolRun() })
    const card = el.querySelector(".qc-metric")!
    expect(card.querySelector(".qc-metric-label")?.textContent).toBe("IC 均值")
    expect(card.querySelector(".qc-metric-value")?.textContent).toBe("0.05")
    expect(card.className).toBe("qc-metric qc-metric-ink")
    const progress = el.querySelector(".qc-progress")!
    expect(progress.querySelector("code")?.textContent).toBe("0.05 / 0.03")
    el.remove()
  })

  test("duplicate tools dedupe in order and names map to design-draft nodes", () => {
    expect(flowNodeName("cross_match_v2")).toBe("match_main")
    expect(flowNodeName("risk_gate_check")).toBe("risk_gate_check")
    expect(flowNodeName("custom_tool")).toBe("custom_tool")
    const run = runWith({
      execution_trace: [
        { type: "tool_call", seq: 0, data: { tool_name: "autoeval" } },
        { type: "tool_call", seq: 2, data: { tool_name: "match_gen" } },
        { type: "tool_result", seq: 3, data: { tool_name: "match_gen" } },
        { type: "tool_call", seq: 4, data: { tool_name: "autoeval" } },
      ],
    })
    const el = FactorFlowView({ run })
    const nodes = [...el.querySelectorAll(".qc-factor-node strong")].map((n) => n.textContent)
    expect(nodes).toEqual(["autoeval", "match_main"])
    const doneMarks = [...el.querySelectorAll(".qc-factor-node")]
    expect(doneMarks[0]!.classList.contains("is-done")).toBe(false)
    expect(doneMarks[1]!.classList.contains("is-done")).toBe(true)
    el.remove()
  })

  test("only merge/permission gates append HumanGate; risk verdicts stay domain output", () => {
    const gateRun = toolRun()
    gateRun.gate = { kind: "merge", reasons: ["merge_requires_approval"] }
    const gateEl = FactorFlowView({ run: gateRun })
    const names = [...gateEl.querySelectorAll(".qc-factor-node strong")].map((n) => n.textContent)
    expect(names).toEqual(["match_main", "gen_schema", "autoeval", "HumanGate"])
    gateEl.remove()
    const riskRun = toolRun()
    riskRun.gate = { kind: "risk", reasons: ["ic_below_threshold"] }
    const riskEl = FactorFlowView({ run: riskRun })
    expect([...riskEl.querySelectorAll(".qc-factor-node strong")].map((n) => n.textContent)).toEqual([
      "match_main",
      "gen_schema",
      "autoeval",
    ])
    riskEl.remove()
    const pendingRun = runWith({
      status: "waiting_for_human",
      gate: { message: "请确认风险" },
      execution_trace: [{ type: "tool_call", seq: 0, data: { tool_name: "match_gen" } }],
    })
    const pendingEl = FactorFlowView({ run: pendingRun })
    expect(pendingEl.querySelectorAll(".qc-factor-node").length).toBe(1)
    pendingEl.remove()
  })
})

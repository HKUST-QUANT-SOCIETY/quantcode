import { describe, expect, test } from "bun:test"
import { isRunAgentResult, parseRunAgentOutput } from "./result-contract"

const valid = {
  status: "waiting_for_human",
  thread_id: "thread-1",
  execution_trace: [
    {
      type: "tool_result",
      iteration: 2,
      seq: 3,
      data: { tool_name: "run_agent" },
    },
  ],
  artifacts: ["artifact://risk/report.json"],
  gate: {
    kind: "risk",
    reasons: ["drawdown"],
    risk_metrics: { max_drawdown: 0.2 },
    decision_schema: { allowed: ["approve", "reject"], default: "reject" },
  },
}

describe("QuantCode run_agent result contract", () => {
  test("accepts a bounded structured result and MCP text wrapper", () => {
    expect(isRunAgentResult(valid)).toBe(true)
    expect(parseRunAgentOutput(JSON.stringify(valid))).toEqual(valid)
    expect(parseRunAgentOutput(JSON.stringify({ content: [{ type: "text", text: JSON.stringify(valid) }] }))).toEqual(
      valid,
    )
  })

  test("rejects malformed nested tool output before it reaches the panel store", () => {
    expect(isRunAgentResult({ status: "completed", execution_trace: "not-an-array" })).toBe(false)
    expect(isRunAgentResult({ status: "completed", artifacts: ["ok", 42] })).toBe(false)
    expect(isRunAgentResult({ status: "completed", gate: { reasons: "not-an-array" } })).toBe(false)
    expect(parseRunAgentOutput("null")).toBeUndefined()
    expect(parseRunAgentOutput("not-json")).toBeUndefined()
  })
})

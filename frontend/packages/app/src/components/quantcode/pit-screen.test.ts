import { describe, expect, test } from "bun:test"
import { PitValuationView, pitDocuments } from "./pit-screen"
import type { RunAgentResult } from "./result-contract"

function pitRun(overrides: Partial<RunAgentResult> = {}): RunAgentResult {
  return {
    status: "completed",
    output_data: {
      as_of_date: "2026-06-30",
      documents: [
        { id: "d1", title: "年报点评 A", source: "中金公司", published_at: "2026-05-20", score: 0.8, url: "https://a" },
        { id: "d2", title: "行业观察 B", source: "广发证券", published_at: "2026-06-28", score: 0.6, url: "https://b" },
      ],
      fcf_ttm: 100,
      wacc: 0.12,
      growth_rate: 0.1,
      terminal_growth: 0.03,
      fair_value_per_share: 1.9,
    },
    ...overrides,
  }
}

describe("PitValuationView", () => {
  test("runs render date timeline in desc order; published_at > as_of_date flags 晚于估值时点", () => {
    const run = pitRun({
      output_data: {
        ...pitRun().output_data!,
        documents: [
          { id: "late", title: "迟到的 C", source: "卖方", published_at: "2026-07-05", score: 0.9, url: "" },
          { id: "ok", title: "合规的 D", source: "买方", published_at: "2026-06-01", score: 0.5, url: "" },
        ],
      },
    })
    const el = PitValuationView({ run })
    expect(el.className).toBe("qc-pit-view")
    expect(el.querySelectorAll(".qc-pit-doc").length).toBe(2)
    expect(el.querySelectorAll(".qc-pit-card").length).toBe(2)
    const late = el.querySelector(".qc-pit-card.is-late")!
    expect(late.textContent).toContain("迟到的 C")
    expect(late.textContent).toContain("晚于估值时点")
    expect([...el.querySelectorAll(".qc-pit-card")].every((d) => d.classList.contains("is-late"))).toBe(false)
    expect(pitDocuments(run)[0]!.late).toBe(true)
    el.remove()
  })

  test("fair value card renders output_data.fair_value_per_share big number", () => {
    const el = PitValuationView({ run: pitRun() })
    const card = el.querySelector(".qc-metric")!
    expect(card.querySelector(".qc-metric-label")?.textContent).toBe("每股公允价值")
    expect(card.querySelector(".qc-metric-value")?.textContent).toBe("1.90")
    expect(el.querySelector(".qc-pit-range")).toBeNull()
    expect(el.querySelectorAll('input[type="range"]')).toHaveLength(0)
    el.remove()
  })

  test("FCF alone cannot manufacture valuation or scenario bounds", () => {
    const el = PitValuationView({ run: pitRun({ output_data: { fcf_ttm: 100 } }) })
    expect(el.querySelector(".qc-metric-value")?.textContent).toBe("—")
    expect(el.querySelectorAll('input[type="range"]')).toHaveLength(0)
    expect(el.textContent).not.toContain("悲观")
    el.remove()
  })

  test("zero valuation and component provenance remain explicit", () => {
    const el = PitValuationView({ run: pitRun({ output_data: {
      fair_value_per_share: 0, source: "fixture", method: "gordon_dcf_stub", result_status: "STAGING",
    } }) })
    expect(el.querySelector(".qc-metric-value")?.textContent).toBe("0.00")
    expect(el.textContent).toContain("gordon_dcf_stub")
    expect(el.textContent).toContain("STAGING")
    expect(el.textContent).toContain("fixture")
    el.remove()
  })

  test("empty run shows both empty notes and no params", () => {
    const el = PitValuationView({ run: null })
    expect(el.querySelectorAll(".qc-empty-state").length).toBe(2)
    expect(el.querySelectorAll(".qc-pit-param").length).toBe(0)
    expect(el.querySelector(".qc-metric-value")?.textContent).toBe("—")
    el.remove()
  })

  test("artifact refs render as code rows and gate runs stay intact", () => {
    const run = pitRun({
      artifacts: ["artifact://pit/valuation.json"],
      status: "waiting_for_human",
      gate: { message: "确认估值假设", reasons: ["drawdown_breach", "var_99"] },
    })
    const el = PitValuationView({ run })
    expect(el.textContent).toContain("artifact://pit/valuation.json")
    // gate reason 不崩
    expect(el.querySelectorAll(".qc-pit-card").length).toBe(2)
    expect(el.querySelectorAll(".qc-pit-param").length).toBe(0)
    expect(el.textContent).not.toContain("undefined")
    el.remove()
  })
})
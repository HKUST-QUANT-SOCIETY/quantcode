import { describe, expect, test } from "bun:test"
import { QcBigNumber, QcChecklistItem, QcProgress, formatMetricValue } from "./metric-cards"

test("formatMetricValue preserves very small non-zero values", () => {
  expect(formatMetricValue("turnover_monthly", 0.000123)).toBe("1.23e-4")
  expect(formatMetricValue("turnover_monthly", 0)).toBe("0")
})

describe("QcBigNumber", () => {
  test("renders label above value with tone class", () => {
    const el = QcBigNumber({ label: "IC 均值", value: "0.05", tone: "positive" })
    expect(el.className).toBe("qc-metric qc-metric-positive")
    expect(el.querySelector(".qc-metric-label")?.textContent).toBe("IC 均值")
    expect(el.querySelector(".qc-metric-value")?.textContent).toBe("0.05")
    el.remove()
  })

  test("defaults to ink tone", () => {
    const el = QcBigNumber({ label: "Sharpe", value: "1.2" })
    expect(el.className).toBe("qc-metric qc-metric-ink")
  })
})

describe("QcProgress", () => {
  test("shows value readout and threshold mark", () => {
    const el = QcProgress({ label: "最大回撤", value: 0.12, threshold: 0.2 })
    expect(el.querySelector("code")?.textContent).toBe("0.12 / 0.2")
    const bar = el.querySelector(".qc-progress-bar")!
    expect(bar.classList.contains("is-breach")).toBe(false)
    expect(bar.querySelector("i:first-child")?.getAttribute("style")).toContain("12%")
    expect(bar.querySelector("i:last-child")?.getAttribute("style")).toContain("20%")
    el.remove()
  })

  test("marks breach when value exceeds threshold", () => {
    const el = QcProgress({ label: "最大回撤", value: 0.35, threshold: 0.2 })
    expect(el.querySelector(".qc-progress-bar")!.classList.contains("is-breach")).toBe(true)
    el.remove()
  })

  test("clamps ratio into 0..1 and hides mark without threshold", () => {
    const el = QcProgress({ label: "回撤", value: 1.4 })
    expect(el.querySelector("code")?.textContent).toBe("1.4")
    expect(el.querySelector(".qc-progress-bar i:last-child")?.getAttribute("style")).toBeNull()
    el.remove()
  })
})

describe("QcChecklistItem", () => {
  test("renders status word per state", () => {
    expect(QcChecklistItem({ label: "IC>0.03", status: "pass" }).querySelector("b")?.textContent).toBe("通过")
    expect(QcChecklistItem({ label: "IC>0.03", status: "fail" }).querySelector("b")?.textContent).toBe("不通过")
    expect(QcChecklistItem({ label: "IC>0.03", status: "marginal" }).querySelector("b")?.textContent).toBe("边缘")
  })

  test("applies status class", () => {
    const el = QcChecklistItem({ label: "x", status: "fail" })
    expect(el.querySelector("b")?.className).toBe("qc-checklist-status is-fail")
    el.remove()
  })
})

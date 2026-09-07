import { describe, expect, test } from "bun:test"
import { SupplierView } from "./settings-supplier"

describe("SupplierView", () => {
  test("does not invent provider/model/baseURL when runtime configuration is absent", () => {
    const el = SupplierView({})
    const values = [...el.querySelectorAll(".qc-supplier-row strong")].map((n) => n.textContent)
    expect(values).toEqual(["未读取", "未读取", "未读取"])
    el.remove()
  })

  test("renders custom values when props provided", () => {
    const el = SupplierView({ provider: "moonshot", model: "kimi-k2", baseUrl: "https://api.moonshot.cn/v1" })
    const values = [...el.querySelectorAll(".qc-supplier-row strong")].map((n) => n.textContent)
    expect(values).toEqual(["moonshot", "kimi-k2", "https://api.moonshot.cn/v1"])
    el.remove()
  })

  test("shows model availability without exposing implementation configuration", () => {
    const el = SupplierView({})
    const names = [...el.querySelectorAll(".qc-supplier-row code")].map((n) => n.textContent)
    expect(names).toEqual([])
    expect(el.querySelector(".qc-supplier-hint")?.textContent).toContain("尚未提供模型信息")
    el.remove()
  })

  test("shows algorithms empty state for empty list", () => {
    const el = SupplierView({})
    expect(el.querySelector(".qc-section-label")?.textContent).toBe("算法目录")
    expect(el.querySelector(".qc-supplier-empty")?.textContent).toBe("暂无可见算法。")
    el.remove()
  })

  test("renders algorithm entries when the directory has data", () => {
    const el = SupplierView({
      algorithms: [
        { id: "rank_top_n", description: "Rank assets by signal" },
        { id: "legacy_signal" },
      ],
    })
    expect(el.querySelector(".qc-supplier-empty")).toBeNull()
    expect([...el.querySelectorAll(".qc-supplier-algorithm-list li")].map((item) => item.textContent)).toEqual([
      "rank_top_n · Rank assets by signal",
      "legacy_signal",
    ])
    el.remove()
  })
})

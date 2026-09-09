import { describe, expect, test } from "bun:test"
import { AlgorithmCatalogView } from "./settings-supplier"
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))
describe("AlgorithmCatalogView", () => {
  test("keeps descriptions as text in collapsed details", async () => {
    const el = AlgorithmCatalogView({ fetcher: async () => [{ id: "demo_ranker", description: "Demo only <script>unsafe</script>" }] })
    await flush()
    expect(el.querySelector("code")?.textContent).toBe("demo_ranker")
    expect(el.querySelector("details")?.open).toBe(false)
    expect(el.querySelector("script")).toBeNull()
    expect(el.querySelector("details p")?.textContent).toContain("Demo only")
  })
  test("distinguishes unavailable service from empty catalog and retries", async () => {
    let calls = 0
    const el = AlgorithmCatalogView({ fetcher: async () => { if (++calls === 1) throw new Error("offline"); return [] } })
    await flush()
    expect(el.querySelector("[role=alert]")?.textContent).toContain("暂不可用")
    el.querySelector<HTMLButtonElement>("button")!.click()
    await flush()
    expect(el.textContent).toContain("暂无已发布算法")
    expect(el.querySelector("[role=alert]")).toBeNull()
  })
})

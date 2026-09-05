import { describe, expect, test } from "bun:test"
import { MemoryQueryView, highlightSegments, stubMemoryFetcher, type MemoryHit } from "./memory-query"

/** 与 zh.ts 同文案的测试用 t（组件要求注入 i18n，见 quantcode.memory.* keys）。 */
const ZH: Record<string, string> = {
  "quantcode.memory.title": "Memory 查询",
  "quantcode.memory.intro": "检索组内与共享 Memory（只读，fail-closed）。",
  "quantcode.memory.searchPlaceholder": "搜索研究记忆…",
  "quantcode.memory.search": "搜索",
  "quantcode.memory.empty": "输入关键词查询 Memory。",
  "quantcode.memory.noResults": "没有匹配的记忆条目。",
  "quantcode.memory.denied": "无权限：跨组 Memory 读取被拒绝（fail-closed）。",
  "quantcode.memory.unavailable": "Memory 检索通道尚未接通：等待后端 memory_search 工具（可注入 fetcher）。",
  "quantcode.memory.score": "相关度",
}
const t = (key: string) => ZH[key] ?? key

const HIT: MemoryHit = {
  id: "note-1",
  title: "PB–ROE 中性化结论",
  snippet: "目标收益必须取 Horizon 表（后复权 t+1→t+2），禁止自算。",
  score: 3.2,
  scope: "factor",
}

const mount = (fetcher?: Parameters<typeof MemoryQueryView>[0]["fetcher"]) => {
  const view = MemoryQueryView({ t, fetcher })
  document.body.append(view)
  return view
}

const search = async (view: HTMLElement, query: string) => {
  const input = view.querySelector<HTMLInputElement>(".qc-memory-search-input")!
  input.value = query
  input.dispatchEvent(new Event("input"))
  view.querySelector<HTMLButtonElement>(".qc-memory-search-submit")!.click()
  await new Promise<void>((resolve) => setTimeout(resolve, 0))
}

describe("highlightSegments", () => {
  test("marks query occurrences case-insensitively and keeps the rest plain", () => {
    expect(highlightSegments("abcABCx", "abc")).toEqual([
      { text: "abc", hit: true },
      { text: "ABC", hit: true },
      { text: "x", hit: false },
    ])
    expect(highlightSegments("no match", "zz")).toEqual([{ text: "no match", hit: false }])
    expect(highlightSegments("plain", "")).toEqual([{ text: "plain", hit: false }])
  })
})

describe("MemoryQueryView", () => {
  test("default (no channel): initial empty hint, search shows placeholder — no fake data", async () => {
    expect(stubMemoryFetcher).toBeTruthy()
    const view = mount()
    expect(view.querySelector(".qc-memory-empty h3")?.textContent).toBe("输入关键词查询 Memory。")
    await search(view, "目标收益")
    expect(view.querySelector(".qc-memory-empty h3")?.textContent).toBe(ZH["quantcode.memory.unavailable"])
    expect(view.querySelectorAll(".qc-memory-hit-row")).toHaveLength(0)
    view.remove()
  })

  test("injected fetcher: results with highlighted snippet, scope chip and relative score bar", async () => {
    const view = mount(async (query) => ({
      hits: [
        HIT,
        { id: "note-2", title: "低分条目", snippet: "回撤阈值记录", score: 0.8 },
      ],
    }))
    await search(view, "目标收益")
    const rows = view.querySelectorAll(".qc-memory-hit-row")
    expect(rows).toHaveLength(2)
    expect(rows[0].querySelector("strong")?.textContent).toBe(HIT.title)
    expect(rows[0].querySelector(".qc-memory-scope")?.textContent).toBe("factor")
    const marks = [...rows[0].querySelectorAll(".qc-memory-hit")].map((mark) => mark.textContent)
    expect(marks).toContain("目标收益")
    expect(rows[1].querySelectorAll(".qc-memory-hit")).toHaveLength(0)
    const bars = [...view.querySelectorAll<HTMLElement>(".qc-memory-score-bar")]
    expect(bars).toHaveLength(2)
    // 相对分数条：最高分条更宽
    expect(parseInt(bars[0].style.width)).toBeGreaterThan(parseInt(bars[1].style.width))
    view.remove()
  })

  test("injected fetcher returning empty hits → no-results state", async () => {
    const view = mount(async () => ({ hits: [] }))
    await search(view, "任何词")
    expect(view.querySelector(".qc-memory-empty h3")?.textContent).toBe("没有匹配的记忆条目。")
    view.remove()
  })

  test("cross-group denial → fail-closed 无权限 empty state", async () => {
    const view = mount(async () => ({ denied: true }))
    await search(view, "别的组的记忆")
    expect(view.querySelector(".qc-memory-empty h3")?.textContent).toBe(ZH["quantcode.memory.denied"])
    view.remove()
  })

  test("fetcher throwing → unavailable placeholder, never fake data", async () => {
    const view = mount(async () => {
      throw new Error("channel down")
    })
    await search(view, "目标收益")
    expect(view.querySelector(".qc-memory-empty h3")?.textContent).toBe(ZH["quantcode.memory.unavailable"])
    view.remove()
  })
})

test("search preserves focus and an edited draft while a request is pending", async () => {
  const pending = Promise.withResolvers<{ hits: MemoryHit[] }>()
  const view = mount(() => pending.promise)
  const input = view.querySelector<HTMLInputElement>("input")!
  input.focus()
  await search(view, "original")
  expect(view.querySelector("input")).toBe(input)
  expect(document.activeElement).toBe(input)
  input.value = "next query"
  input.dispatchEvent(new Event("input"))
  pending.resolve({ hits: [HIT] })
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(input.value).toBe("next query")
  expect(document.activeElement).toBe(input)
  expect(view.querySelector<HTMLButtonElement>("button")!.disabled).toBe(false)
  expect(view.querySelector(".qc-memory-pending")).toBeNull()
  view.remove()
})

test("out-of-order requests with the same query only display the latest result", async () => {
  const first = Promise.withResolvers<{ hits: MemoryHit[] }>()
  const second = Promise.withResolvers<{ hits: MemoryHit[] }>()
  let calls = 0
  const view = mount(() => (++calls === 1 ? first.promise : second.promise))
  await search(view, "same")
  view.querySelector("input")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }))
  second.resolve({ hits: [{ title: "latest" }] })
  await new Promise((resolve) => setTimeout(resolve, 0))
  first.resolve({ hits: [{ title: "stale" }] })
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(view.querySelector(".qc-memory-hit-row strong")?.textContent).toBe("latest")
  view.remove()
})

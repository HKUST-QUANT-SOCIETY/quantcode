/**
 * F-04 Memory 查询视图：搜索框 + 结果列表（snippet 高亮 + 相对分数条）。
 *
 * 数据源：MemoryService FTS 在后端 runner/memory；面板通过 OpenCode 的受限
 * QuantCode read-only surface 注入 fetcher。未连接/空库保持明确空态，绝不造假数据。
 * 跨组读取被拒（MemoryPermissionError fail-closed）→ "无权限" 空态。
 * 纯 DOM 构建（沿 ssh-login 模式，bun test 兼容）。
 */

export type MemoryHit = {
  id?: string
  title?: string
  snippet?: string
  /** BM25 分数；UI 只做同批结果间的相对分数条，不做绝对刻度 */
  score?: number
  scope?: string
}

/** null = 通道未接通；denied = 跨组无权限（fail-closed） */
export type MemoryQueryResult = { hits: MemoryHit[] } | { denied: true } | null

export type MemoryQueryFetcher = (query: string) => Promise<MemoryQueryResult>

export type MemoryQueryProps = {
  /** i18n：panels 传 language.t（key 见 quantcode.memory.*） */
  t: (key: string) => string
  /** 可注入检索实现；默认无通道（占位空态） */
  fetcher?: MemoryQueryFetcher
}

/**
 * Isolated consumers keep a deterministic unavailable fallback; the production
 * panel injects the server-backed search implementation.
 */
export const stubMemoryFetcher: MemoryQueryFetcher = async () => null

/** snippet 高亮分段：query（大小写不敏感）命中的片段标 hit。 */
export function highlightSegments(snippet: string, query: string): { text: string; hit: boolean }[] {
  const trimmed = query.trim()
  if (!trimmed) return [{ text: snippet, hit: false }]
  const lowerSnippet = snippet.toLowerCase()
  const lowerQuery = trimmed.toLowerCase()
  const segments: { text: string; hit: boolean }[] = []
  let cursor = 0
  while (cursor < snippet.length) {
    const index = lowerSnippet.indexOf(lowerQuery, cursor)
    if (index === -1) break
    if (index > cursor) segments.push({ text: snippet.slice(cursor, index), hit: false })
    segments.push({ text: snippet.slice(index, index + trimmed.length), hit: true })
    cursor = index + trimmed.length
  }
  if (cursor < snippet.length) segments.push({ text: snippet.slice(cursor), hit: false })
  return segments.length ? segments : [{ text: snippet, hit: false }]
}

export function MemoryQueryView(props: MemoryQueryProps): HTMLElement {
  const t = props.t
  const fetcher = props.fetcher ?? stubMemoryFetcher
  const root = document.createElement("div")
  root.className = "qc-memory-query"
  root.style.cssText = "display:grid;gap:12px;align-content:start;"

  let lastQuery = ""
  let searching = false
  let requestId = 0
  let resultQuery = ""
  const results = document.createElement("div")
  results.className = "qc-memory-results"
  results.setAttribute("aria-live", "polite")

  const sectionLabel = (text: string) => {
    const span = document.createElement("span")
    span.className = "qc-section-label"
    span.textContent = text
    return span
  }

  const emptyState = (titleKey: string, errorTone?: boolean) => {
    const empty = document.createElement("div")
    empty.className = "qc-empty-state qc-memory-empty"
    const index = document.createElement("span")
    index.className = "qc-empty-index"
    index.textContent = "—"
    const title = document.createElement("h3")
    title.textContent = t(titleKey)
    if (errorTone) title.style.color = "#aa2e23"
    empty.append(index, title)
    return empty
  }

  const renderSnippet = (hit: MemoryHit) => {
    const wrap = document.createElement("div")
    wrap.className = "qc-memory-snippet"
    for (const segment of highlightSegments(hit.snippet ?? "", resultQuery)) {
      if (!segment.text) continue
      const part = document.createElement(segment.hit ? "mark" : "span")
      if (segment.hit) {
        part.style.cssText = "background:rgba(154,91,18,0.18);color:inherit;"
        part.className = "qc-memory-hit"
      }
      part.textContent = segment.text
      wrap.append(part)
    }
    return wrap
  }

  const renderHits = (hits: MemoryHit[]) => {
    if (hits.length === 0) {
      results.append(emptyState("quantcode.memory.noResults"))
      return
    }
    const maxScore = Math.max(0, ...hits.map((hit) => (typeof hit.score === "number" && Number.isFinite(hit.score) ? hit.score : 0)))
    const list = document.createElement("div")
    list.className = "qc-memory-hits"
    for (const hit of hits) {
      const row = document.createElement("div")
      row.className = "qc-memory-hit-row"
      row.style.cssText = "display:grid;gap:4px;padding:10px 0;border-bottom:1px solid var(--qc-line);"

      const head = document.createElement("div")
      head.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;align-items:center;"
      const title = document.createElement("strong")
      title.textContent = hit.title || hit.id || "Memory"
      head.append(title)
      if (hit.scope) {
        const scope = document.createElement("span")
        scope.className = "qc-status qc-memory-scope"
        scope.textContent = hit.scope
        head.append(scope)
      }
      row.append(head)

      row.append(renderSnippet(hit))

      if (typeof hit.score === "number" && Number.isFinite(hit.score) && maxScore > 0) {
        const barWrap = document.createElement("div")
        barWrap.style.cssText = "display:flex;align-items:center;gap:8px;"
        const scoreLabel = document.createElement("span")
        scoreLabel.style.cssText = "font-size:9px;color:var(--qc-muted);"
        scoreLabel.textContent = `${t("quantcode.memory.score")} ${hit.score.toFixed(2)}`
        const bar = document.createElement("div")
        bar.className = "qc-memory-score-bar"
        bar.style.cssText = `height:4px;width:${Math.max(2, Math.round((hit.score / maxScore) * 100))}%;background:var(--qc-ink);border-radius:2px;`
        barWrap.append(scoreLabel, bar)
        row.append(barWrap)
      }
      list.append(row)
    }
    results.append(list)
  }

  const renderResult = (result: MemoryQueryResult) => {
    if (result === null) {
      results.append(emptyState("quantcode.memory.unavailable"))
      return
    }
    if ("denied" in result) {
      results.append(emptyState("quantcode.memory.denied", true))
      return
    }
    renderHits(result.hits)
  }

  const runSearch = async () => {
    const query = lastQuery.trim()
    const request = ++requestId
    if (!query) {
      searching = false
      submit.disabled = true
      results.replaceChildren(emptyState("quantcode.memory.empty"))
      results.setAttribute("aria-busy", "false")
      return
    }
    searching = true
    submit.disabled = true
    results.replaceChildren()
    results.setAttribute("aria-busy", "true")
    const pending = document.createElement("span")
    pending.className = "qc-connection-pill qc-memory-pending"
    pending.textContent = "…"
    results.append(pending)
    try {
      const result = await fetcher(query)
      if (request !== requestId) return
      resultQuery = query
      results.replaceChildren()
      renderResult(result)
    } catch {
      if (request !== requestId) return
      results.replaceChildren(emptyState("quantcode.memory.unavailable"))
    } finally {
      if (request === requestId) {
        searching = false
        submit.disabled = !lastQuery.trim()
        results.setAttribute("aria-busy", "false")
      }
    }
  }

  // Keep the form mounted while only the result region changes. Keyboard focus
  // and edits made during an in-flight request survive completion.
  const submit = document.createElement("button")
  const render = () => {
    root.replaceChildren()

    const intro = document.createElement("div")
    intro.className = "qc-memory-intro"
    intro.append(
      sectionLabel("RESEARCH MEMORY"),
      (() => {
        const title = document.createElement("h3")
        title.textContent = t("quantcode.memory.title")
        return title
      })(),
      (() => {
        const desc = document.createElement("p")
        desc.style.cssText = "margin:0;font-size:11px;color:var(--qc-muted);"
        desc.textContent = t("quantcode.memory.intro")
        return desc
      })(),
    )
    root.append(intro)

    const form = document.createElement("div")
    form.className = "qc-memory-search"
    form.style.cssText = "display:flex;gap:8px;"
    const input = document.createElement("input")
    input.className = "qc-select-wide qc-memory-search-input"
    input.type = "search"
    input.placeholder = t("quantcode.memory.searchPlaceholder")
    input.autocomplete = "off"
    input.setAttribute("aria-label", t("quantcode.memory.searchPlaceholder"))
    input.value = lastQuery
    input.addEventListener("input", () => {
      lastQuery = input.value
      submit.disabled = searching || !lastQuery.trim()
    })
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault()
        void runSearch()
      }
    })
    submit.type = "button"
    submit.className = "qc-button qc-button-primary qc-memory-search-submit"
    submit.textContent = t("quantcode.memory.search")
    submit.disabled = searching || !lastQuery.trim()
    submit.addEventListener("click", () => void runSearch())
    form.append(input, submit)
    root.append(form)

    root.append(results)
    results.replaceChildren(emptyState("quantcode.memory.empty"))
    return results
  }

  // 首屏：空查询 → 空态提示
  render()
  return root
}

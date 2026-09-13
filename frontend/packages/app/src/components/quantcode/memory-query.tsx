/**
 * F-04 Memory 查询视图：搜索框 + 结果列表（snippet 高亮 + 相对分数条）。
 *
 * 数据源：MemoryService FTS 在后端 runner/memory；面板通过执行服务的受限
 * QuantCode read-only surface 注入 fetcher。未连接/空库保持明确空态，绝不造假数据。
 * 跨组读取被拒（MemoryPermissionError fail-closed）→ "无权限" 空态。
 * 纯 DOM 构建（沿 ssh-login 模式，bun test 兼容）。
 */
import { viewEmpty, viewIcon } from "./workspace-ui"

export type MemoryHit = {
  content?: string
  contentTruncated?: boolean
  indexedAt?: number
  id?: string
  title?: string
  snippet?: string
  /** BM25 分数；UI 只做同批结果间的相对分数条，不做绝对刻度 */
  score?: number
  scope?: string
}

/** null = 通道未接通；denied = 跨组无权限（fail-closed） */
export type MemoryQueryResult = { hits: MemoryHit[]; total?: number; hasMore?: boolean } | { denied: true } | null

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

  let lastQuery = ""
  let searching = false
  let requestId = 0
  let resultQuery = ""
  let lastHits: MemoryHit[] = []
  let total = 0
  let hasMore = false
  const groupFilter = document.createElement("select")
  groupFilter.className = "qc-select-wide"
  groupFilter.setAttribute("aria-label", "知识范围")
  const option = (text: string, value: string) => Object.assign(document.createElement("option"), { textContent: text, value })
  groupFilter.append(option("全部授权范围", ""))
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
    const empty = viewEmpty(t(titleKey), errorTone ? "shield" : "brain")
    empty.classList.add("qc-memory-empty")
    if (errorTone) empty.classList.add("is-error")
    return empty
  }

  const renderSnippet = (hit: MemoryHit) => {
    const wrap = document.createElement("div")
    wrap.className = "qc-memory-snippet"
    for (const segment of highlightSegments((hit.snippet ?? "").replace(/<<|>>/g, ""), resultQuery)) {
      if (!segment.text) continue
      const part = document.createElement(segment.hit ? "mark" : "span")
      if (segment.hit) {
        part.className = "qc-memory-hit"
      }
      part.textContent = segment.text
      wrap.append(part)
    }
    return wrap
  }

  const renderHits = (all: MemoryHit[]) => {
    const hits = groupFilter.value ? all.filter(hit => hit.scope === groupFilter.value) : all
    if (hits.length === 0) {
      results.append(emptyState("quantcode.memory.noResults"))
      return
    }
    const maxScore = Math.max(0, ...hits.map((hit) => (typeof hit.score === "number" && Number.isFinite(hit.score) ? hit.score : 0)))
    const list = document.createElement("div")
    list.className = "qc-memory-hits"
    const count = document.createElement("p")
    count.className = "qc-results-count"
    count.textContent = `${hits.length} / ${total || all.length} 份知识${hasMore ? "（当前显示前 50 份，请搜索缩小范围）" : ""}`
    results.append(count)
    for (const hit of hits) {
      const row = document.createElement("div")
      row.className = "qc-memory-hit-row"

      const head = document.createElement("div")
      head.className = "qc-memory-hit-heading"
      head.append(viewIcon("file-tree"))
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
      if (hit.content !== undefined) {
        const detail = document.createElement("details")
        const summary = document.createElement("summary")
        summary.textContent = "查看正文与来源"
        const body = document.createElement("pre")
        body.className = "qc-code-block"
        body.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere;max-height:32rem;overflow:auto"
        body.textContent = hit.content
        detail.append(summary, body)
        if (hit.contentTruncated) {
          const note = document.createElement("p")
          note.textContent = "文档较长，此处展示前 64K 字符。"
          detail.append(note)
        }
        if (hit.indexedAt) {
          const date = document.createElement("p")
          date.className = "qc-muted"
          date.textContent = `索引更新：${new Date(hit.indexedAt).toLocaleString()}`
          detail.append(date)
        }
        row.append(detail)
      }
      if (hit.id) {
        const path = document.createElement("code")
        path.className = "qc-memory-path"
        path.textContent = hit.id
        row.append(path)
      }

      if (typeof hit.score === "number" && Number.isFinite(hit.score) && maxScore > 0) {
        const barWrap = document.createElement("div")
        barWrap.className = "qc-memory-score"
        const scoreLabel = document.createElement("span")
        scoreLabel.className = "qc-muted"
        scoreLabel.textContent = `${t("quantcode.memory.score")} ${hit.score.toFixed(2)}`
        const bar = document.createElement("div")
        bar.className = "qc-memory-score-bar"
        bar.style.width = `${Math.max(2, Math.round((hit.score / maxScore) * 100))}%`
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
    lastHits = result.hits
    total = result.total ?? result.hits.length
    hasMore = !!result.hasMore
    const selected = groupFilter.value
    groupFilter.replaceChildren(option("全部授权范围", ""))
    for (const scope of [...new Set(result.hits.map(hit => hit.scope).filter((value): value is string => !!value))]) {
      groupFilter.append(option(scope === "global" ? "全组织共享" : scope.replace("groups/", "业务组 · ").replace("projects/", "项目 · "), scope))
    }
    groupFilter.value = selected
    renderHits(result.hits)
  }

  const runSearch = async () => {
    const query = lastQuery.trim()
    const request = ++requestId
    searching = true
    submit.disabled = true
    results.replaceChildren()
    results.setAttribute("aria-busy", "true")
    const pending = document.createElement("span")
    pending.className = "qc-connection-pill qc-memory-pending"
    pending.textContent = "正在检索知识…"
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
        submit.disabled = false
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
      sectionLabel("GROUP MEMORY"),
      (() => {
        const title = document.createElement("h3")
        title.textContent = "长期知识库"
        return title
      })(),
      (() => {
        const desc = document.createElement("p")
        desc.textContent = "浏览已有知识、能力卡与公共契约，按关键词检索并查看正文和来源。"
        return desc
      })(),
    )
    root.append(intro)

    const form = document.createElement("div")
    form.className = "qc-memory-search"
    const input = document.createElement("input")
    input.className = "qc-select-wide qc-memory-search-input"
    input.type = "search"
    input.placeholder = t("quantcode.memory.searchPlaceholder")
    input.autocomplete = "off"
    input.setAttribute("aria-label", t("quantcode.memory.searchPlaceholder"))
    input.value = lastQuery
    input.addEventListener("input", () => {
      lastQuery = input.value
      submit.disabled = false
    })
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault()
        void runSearch()
      }
    })
    submit.type = "button"
    submit.className = "qc-button qc-button-primary qc-memory-search-submit"
    submit.append(viewIcon("magnifying-glass"), document.createTextNode(t("quantcode.memory.search")))
    submit.disabled = searching
    submit.addEventListener("click", () => void runSearch())
    const reset = document.createElement("button")
    reset.type = "button"
    reset.className = "qc-button qc-button-secondary"
    reset.textContent = "全部知识"
    reset.onclick = () => { lastQuery = ""; input.value = ""; groupFilter.value = ""; void runSearch() }
    groupFilter.onchange = () => { results.replaceChildren(); renderHits(lastHits) }
    form.append(input, submit, reset, groupFilter)
    root.append(form)

    root.append(results)
    results.replaceChildren(emptyState("quantcode.memory.empty"))
    return results
  }

  render()
  if (props.fetcher) void runSearch()
  return root
}

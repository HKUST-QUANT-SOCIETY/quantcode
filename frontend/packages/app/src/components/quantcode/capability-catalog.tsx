/**
 * F-04/P-07 能力目录视图：组织已登记能力卡片列表。
 *
 * 数据源：生产面板优先消费 OpenCode 受限 read-only surface 的 fetcher；
 * 当前 run 的 list_capabilities trace 作为回放/离线降级通道。
 *
 * 游客组被 Mask 的卡片后端已过滤，UI 无感知。
 * 纯 DOM 构建（沿 ssh-login / settings-supplier 模式，bun test 兼容）。
 */
import type { TraceEvent } from "./result-contract"

export type CapabilityCard = {
  id?: string
  name?: string
  type?: string
  api_surface?: string[]
  when_to_use?: string
  when_not_to_reinvent?: string
  owner_group?: string
  source_commit?: string
  canonical_repo?: string
  maturity_status?: string
  integration_status?: string
  domain_authority?: string
  depends_on?: string[]
  consumed_by?: string[]
  deprecated_aliases?: string[]
  observed_at?: string
  inputs?: string[]
  outputs?: string[]
}

export type CapabilityFetcher = () => Promise<CapabilityCard[] | null>

export type CapabilityCatalogProps = {
  /** i18n：panels 传 language.t（key 见 quantcode.capability.*） */
  t: (key: string) => string
  /** 服务端目录通道；返回 null 表示通道不可用，不回落到可能过期的 trace */
  fetcher?: CapabilityFetcher
  /** 当前 run（读取 list_capabilities 的 tool_result 事件） */
  run?: { execution_trace?: TraceEvent[] } | null
}

/** 从 execution_trace 提取 list_capabilities 的 tool_result 卡片（防御式：截断/非 JSON 跳过）。 */
export function capabilitiesFromTrace(run: { execution_trace?: TraceEvent[] } | null | undefined): CapabilityCard[] {
  const cards: CapabilityCard[] = []
  for (const event of run?.execution_trace ?? []) {
    if (event.type !== "tool_result") continue
    const tool = event.data?.tool ?? event.data?.tool_name
    if (tool !== "list_capabilities") continue
    const raw = event.data?.result
    if (typeof raw !== "string") continue
    try {
      const parsed: unknown = JSON.parse(raw)
      const list = Array.isArray(parsed) ? parsed : (parsed as { capabilities?: unknown })?.capabilities
      if (!Array.isArray(list)) continue
      for (const item of list) {
        if (item && typeof item === "object" && typeof (item as CapabilityCard).name === "string") {
          cards.push(item as CapabilityCard)
        }
      }
    } catch {
      // 结果被截断（后端 tool_result 限长）或非 JSON → 跳过，不造假数据
    }
  }
  return cards
}

function isCardText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0
}

export function CapabilityCatalogView(props: CapabilityCatalogProps): HTMLElement {
  const t = props.t
  const root = document.createElement("div")
  root.className = "qc-capability-catalog"
  root.style.cssText = "display:grid;gap:12px;align-content:start;"

  let fetched: CapabilityCard[] | undefined
  let fetchState: "idle" | "loading" | "ready" | "unavailable" = props.fetcher ? "loading" : "idle"
  let query = ""

  const cards = (): CapabilityCard[] => (props.fetcher ? fetched ?? [] : capabilitiesFromTrace(props.run))

  const matches = (card: CapabilityCard) => {
    if (!query) return true
    const haystack = [card.id, card.name, card.canonical_repo, card.type, card.owner_group, card.when_to_use, card.when_not_to_reinvent, ...(card.api_surface ?? []), ...(card.deprecated_aliases ?? []), ...(card.inputs ?? []), ...(card.outputs ?? []), ...(card.depends_on ?? []), ...(card.consumed_by ?? [])]
      .filter(isCardText)
      .join("\n")
      .toLowerCase()
    return haystack.includes(query)
  }

  const chip = (text: string, tone?: "green" | "yellow") => {
    const span = document.createElement("span")
    span.className = "qc-status"
    if (tone === "green") span.classList.add("qc-status-completed")
    if (tone === "yellow") span.classList.add("qc-status-waiting_for_human")
    span.textContent = text
    return span
  }

  const renderCard = (card: CapabilityCard) => {
    const cardEl = document.createElement("div")
    cardEl.className = "qc-capability-card"
    cardEl.style.cssText = "display:grid;gap:6px;padding:10px 0;border-bottom:1px solid var(--qc-line);"

    const head = document.createElement("div")
    head.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:8px;"
    const name = document.createElement("strong")
    name.textContent = card.name ?? ""
    head.append(name)
    if (isCardText(card.type)) head.append(chip(card.type))
    if (isCardText(card.maturity_status)) head.append(chip(`maturity: ${card.maturity_status}`))
    if (isCardText(card.integration_status)) {
      const tone = card.integration_status === "CONNECTED" ? "green" : "yellow"
      head.append(chip(`integration: ${card.integration_status}`, tone))
    }
    if (isCardText(card.owner_group)) {
      const owner = chip(`${t("quantcode.capability.ownerGroup")}: ${card.owner_group}`)
      owner.classList.add("qc-capability-owner")
      head.append(owner)
    }
    cardEl.append(head)

    if (isCardText(card.canonical_repo) || isCardText(card.domain_authority)) {
      const meta = document.createElement("p")
      meta.style.cssText = "margin:0;font-size:10px;color:var(--qc-muted);"
      meta.textContent = [card.canonical_repo, card.domain_authority].filter(isCardText).join(" · ")
      cardEl.append(meta)
    }

    if (isCardText(card.when_to_use)) {
      const use = document.createElement("p")
      use.style.cssText = "margin:0;font-size:11px;"
      use.textContent = `${t("quantcode.capability.whenToUse")}：${card.when_to_use}`
      cardEl.append(use)
    }

    // "何时别自造" 高亮（spec F-04 要求字段高亮呈现）
    if (isCardText(card.when_not_to_reinvent)) {
      const ban = document.createElement("p")
      ban.className = "qc-capability-ban"
      ban.style.cssText =
        "margin:0;padding:6px 8px;font-size:11px;color:#9a5b12;border:1px solid rgba(154,91,18,0.3);border-radius:6px;background:rgba(154,91,18,0.06);"
      ban.textContent = `⚠ ${t("quantcode.capability.whenNotToReinvent")}：${card.when_not_to_reinvent}`
      cardEl.append(ban)
    }

    if (card.api_surface?.length) {
      const surfaceLabel = document.createElement("span")
      surfaceLabel.className = "qc-section-label"
      surfaceLabel.textContent = t("quantcode.capability.apiSurface")
      cardEl.append(surfaceLabel)
      for (const line of card.api_surface) {
        if (!isCardText(line)) continue
        const code = document.createElement("code")
        code.className = "qc-artifact"
        code.textContent = line
        cardEl.append(code)
      }
    }

    const contracts = document.createElement("dl")
    contracts.className = "qc-result-provenance"
    for (const key of ["inputs", "outputs", "depends_on", "consumed_by", "deprecated_aliases"] as const) {
      const values = card[key]?.filter(isCardText)
      if (!values?.length) continue
      const label = document.createElement("dt")
      label.textContent = key
      const value = document.createElement("dd")
      value.textContent = values.join(" · ")
      contracts.append(label, value)
    }
    if (isCardText(card.observed_at)) {
      const label = document.createElement("dt")
      label.textContent = "observed_at"
      const value = document.createElement("dd")
      value.textContent = card.observed_at
      contracts.append(label, value)
    }
    if (contracts.childElementCount) cardEl.append(contracts)

    if (isCardText(card.source_commit)) {
      const commit = document.createElement("code")
      commit.className = "qc-artifact"
      commit.textContent = `${t("quantcode.capability.source")}:${card.source_commit}`
      cardEl.append(commit)
    }

    return cardEl
  }

  const renderEmpty = (titleKey: string) => {
    const empty = document.createElement("div")
    empty.className = "qc-empty-state qc-capability-empty"
    const index = document.createElement("span")
    index.className = "qc-empty-index"
    index.textContent = "—"
    const title = document.createElement("h3")
    title.textContent = t(titleKey)
    empty.append(index, title)
    return empty
  }

  const renderList = () => {
    // ponytail: 列表区可复用容器——搜索重渲只 replaceChildren 这里，搜索框不参与重渲，避免每敲一字失焦
    listHost.replaceChildren()
    const visible = cards().filter(matches)
    if (fetchState === "loading") {
      listHost.append(renderEmpty("quantcode.capability.loading"))
      return
    }
    if (fetchState === "unavailable") {
      listHost.append(renderEmpty("quantcode.capability.unavailable"))
      return
    }
    if (cards().length === 0) {
      listHost.append(renderEmpty("quantcode.capability.empty"))
      return
    }
    if (visible.length === 0) {
      listHost.append(renderEmpty("quantcode.capability.noMatch"))
      return
    }
    const list = document.createElement("div")
    list.className = "qc-capability-list"
    for (const card of visible) list.append(renderCard(card))
    listHost.append(list)
  }

  const intro = document.createElement("div")
  intro.className = "qc-memory-intro"
  const label = document.createElement("span")
  label.className = "qc-section-label"
  label.textContent = "ORG CAPABILITIES"
  const title = document.createElement("h3")
  title.textContent = t("quantcode.capability.title")
  const desc = document.createElement("p")
  desc.style.cssText = "margin:0;font-size:11px;color:var(--qc-muted);"
  desc.textContent = t("quantcode.capability.intro")
  intro.append(label, title, desc)

  // ponytail: 顶部搜索为纯客户端过滤；FTS 在后端，数据量大时由 fetcher 通道承担检索
  const search = document.createElement("input")
  search.className = "qc-select-wide qc-capability-search"
  search.type = "search"
  search.placeholder = t("quantcode.capability.searchPlaceholder")
  search.autocomplete = "off"
  search.addEventListener("input", () => {
    query = search.value.trim().toLowerCase()
    renderList()
  })
  const listHost = document.createElement("div")
  listHost.className = "qc-capability-results"

  const refresh = document.createElement("button")
  refresh.type = "button"
  refresh.textContent = "刷新能力目录"
  refresh.hidden = !props.fetcher
  const fetchCards = () => {
    if (!props.fetcher || refresh.disabled) return
    refresh.disabled = true
    fetchState = "loading"
    fetched = undefined
    renderList()
    void props
      .fetcher()
      .then((result) => {
        if (result === null) {
          fetchState = "unavailable"
          renderList()
          return
        }
        fetched = result
        fetchState = "ready"
        renderList()
      })
      .catch(() => {
        fetchState = "unavailable"
        renderList()
      })
      .finally(() => { refresh.disabled = false })
  }
  refresh.addEventListener("click", fetchCards)
  root.replaceChildren(intro, search, refresh, listHost)
  renderList()
  fetchCards()

  return root
}

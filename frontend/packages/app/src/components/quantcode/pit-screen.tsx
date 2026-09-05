/**
 * PIT 估值视图（v5 PPT slide20 屏3）：纯 DOM 构建，无 Solid 响应式，
 * 与 factor-screen 相同的 bun test 兼容策略；panels.tsx 中作为 JSX 子节点插入。
 *
 * 左侧：证据时间线（output_data.documents，published_at > as_of_date → 红色契约告警）。
 * 右侧：只读展示组件返回的估值、方法、来源和状态；不在前端计算领域结果。
 */
import { QcBigNumber } from "./metric-cards"
import type { RunAgentResult } from "./result-contract"

type PitDoc = {
  title: string
  publishedAt: string
  source: string
  score: number
  url: string
  /** published_at 晚于估值时点 → 契约告警（正常不应出现） */
  late: boolean
}

/** 防御式提取 PIT 文档：published_at > as_of_date 标记 late。导出给测试。 */
export function pitDocuments(run: RunAgentResult | null): PitDoc[] {
  const asOf = typeof run?.output_data?.as_of_date === "string" ? run.output_data.as_of_date : ""
  const raw = run?.output_data?.documents
  if (!Array.isArray(raw)) return []
  const docs: PitDoc[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const doc = item as Record<string, unknown>
    const publishedAt = typeof doc.published_at === "string" ? doc.published_at.slice(0, 10) : ""
    if (!publishedAt) continue
    docs.push({
      title: typeof doc.title === "string" ? doc.title : "未命名证据",
      publishedAt,
      source: typeof doc.source === "string" ? doc.source : "unknown",
      score: typeof doc.score === "number" && Number.isFinite(doc.score) ? doc.score : 0,
      url: typeof doc.url === "string" ? doc.url : "",
      late: !!asOf && publishedAt > asOf,
    })
  }
  return docs.sort((a, b) => (a.publishedAt < b.publishedAt ? 1 : a.publishedAt > b.publishedAt ? -1 : b.score - a.score))
}

function emptyNote(text: string) {
  const empty = document.createElement("div")
  empty.className = "qc-empty-state is-compact"
  const note = document.createElement("p")
  note.className = "qc-metrics-empty"
  note.textContent = text
  empty.append(note)
  return empty
}

export function PitValuationView(props: { run: RunAgentResult | null }): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-pit-view"

  // --- 左侧：证据时间线 ---
  const timeline = document.createElement("div")
  timeline.className = "qc-pit-timeline"
  const timelineLabel = document.createElement("span")
  timelineLabel.className = "qc-section-label"
  timelineLabel.textContent = "证据时间线"
  timeline.append(timelineLabel)
  const docs = pitDocuments(props.run)
  if (!docs.length) {
    timeline.append(emptyNote("暂无 PIT 证据，运行 pit_rag_search 后按发布日期排列于此。"))
  } else {
    for (const doc of docs) {
      const row = document.createElement("div")
      row.className = "qc-pit-doc"
      const date = document.createElement("time")
      date.textContent = doc.publishedAt
      const card = document.createElement("div")
      if (doc.late) card.className = "qc-pit-card is-late"
      else card.className = "qc-pit-card"
      const head = document.createElement("strong")
      head.textContent = doc.title
      const meta = document.createElement("small")
      meta.textContent = `${doc.source} · score ${doc.score.toFixed(2)}`
      card.append(head, meta)
      if (doc.late) {
        const warn = document.createElement("b")
        warn.className = "qc-pit-late"
        warn.textContent = "晚于估值时点"
        card.append(warn)
      }
      row.append(date, card)
      timeline.append(row)
    }
  }

  // --- 右侧：DCF 估值卡 ---
  const dcf = document.createElement("div")
  dcf.className = "qc-pit-valuation"
  const dcfLabel = document.createElement("span")
  dcfLabel.className = "qc-section-label"
  dcfLabel.textContent = "DCF 估值"
  dcf.append(dcfLabel)
  const output = props.run?.output_data ?? {}
  const base = typeof output.fair_value_per_share === "number" && Number.isFinite(output.fair_value_per_share)
    ? output.fair_value_per_share : undefined
  const cardGrid = document.createElement("div")
  cardGrid.className = "qc-metrics-body"
  cardGrid.append(QcBigNumber({ label: "每股公允价值", value: base === undefined ? "—" : base.toFixed(2), tone: "ink" }))
  dcf.append(cardGrid)
  if (base === undefined) dcf.append(emptyNote("尚无组件估值结果，请运行已授权的估值组件。"))

  const provenance = document.createElement("dl")
  provenance.className = "qc-pit-provenance"
  for (const [label, value] of [
    ["结果状态", output.result_status ?? output.status ?? props.run?.status],
    ["来源", output.source ?? output.backend],
    ["估值方法", output.method],
    ["数据时点", output.as_of_date],
    ["契约版本", output.contract_version ?? output.schema_version],
  ]) {
    const term = document.createElement("dt")
    const detail = document.createElement("dd")
    term.textContent = String(label)
    detail.textContent = typeof value === "string" && value ? value : "未提供"
    provenance.append(term, detail)
  }
  dcf.append(provenance)
  const note = document.createElement("p")
  note.className = "qc-metrics-empty"
  note.textContent = "估值与情景区间以领域组件返回值为准。调整假设需重新运行组件。"
  dcf.append(note)

  if (props.run?.artifacts?.length) {
    const artifact = document.createElement("code")
    artifact.className = "qc-artifact"
    artifact.textContent = props.run.artifacts.join("\n")
    dcf.append(artifact)
  }

  root.append(timeline, dcf)
  return root
}
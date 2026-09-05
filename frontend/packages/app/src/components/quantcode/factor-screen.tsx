/**
 * 因子评估视图（v5 PPT slide20 屏1）：纯 DOM 构建，无 Solid 响应式，
 * 与 metric-cards 相同的 bun test 兼容策略；panels.tsx 中作为 JSX 子节点插入。
 */
import { QcBigNumber, QcProgress, formatMetricValue, type MetricTone } from "./metric-cards"
import type { RunAgentResult } from "./result-contract"
import { METRIC_LABELS } from "./metrics"

const NODE_NAMES: Record<string, string> = {
  match_gen: "match_main",
  match: "match_main",
  gen_schema: "gen_schema",
  schema: "gen_schema",
  autoeval: "autoeval",
  eval: "autoeval",
}

const ACTIONABLE_GATE_KINDS = new Set(["merge", "permission"])

function nodeLabel(tool: string) {
  const key = tool.toLowerCase()
  for (const [needle, name] of Object.entries(NODE_NAMES)) {
    if (key.includes(needle)) return name
  }
  return tool
}

/** tool_name → 设计稿节点名（测试用）。 */
export function flowNodeName(tool: string) {
  return nodeLabel(tool)
}

/** tool_call 事件去重保序 → 流程节点；全部完成且有 gate → 末尾追加 HumanGate。 */
function flowNodes(run: RunAgentResult | null) {
  if (!run) return []
  const trace = run.execution_trace ?? []
  const names: string[] = []
  const done = new Set<string>()
  for (const event of trace) {
    const raw = event.data?.tool_name ?? event.data?.tool
    const tool = typeof raw === "string" ? raw : ""
    if (!tool) continue
    const name = nodeLabel(tool)
    if (event.type === "tool_call") {
      if (!names.includes(name)) names.push(name)
    } else if (event.type === "tool_result") {
      done.add(name)
    }
  }
  const nodes = names.map((name) => ({ name, done: done.has(name) }))
  const hasGate = ACTIONABLE_GATE_KINDS.has(run.gate?.kind ?? "") || trace.some((event) => {
    if (event.type !== "human_gate") return false
    const kind = event.data?.kind ?? (event.data?.gate as Record<string, unknown> | undefined)?.kind
    return typeof kind === "string" && ACTIONABLE_GATE_KINDS.has(kind)
  })
  if (nodes.length > 0 && nodes.every((node) => node.done) && hasGate && !nodes.some((node) => node.name === "HumanGate")) {
    nodes.push({ name: "HumanGate", done: run.human_decision !== undefined })
  }
  return nodes
}

/** 数值指标取前 4 个做 QcBigNumber；IC 类以 0.03 绝对值参考线画 QcProgress。 */
function numericMetrics(run: RunAgentResult) {
  const merged = { ...(run.output_data ?? {}), ...(run.risk_metrics ?? {}) }
  const cards: { label: string; value: string; tone: MetricTone }[] = []
  const rows: { label: string; value: number; threshold?: number }[] = []
  for (const [key, raw] of Object.entries(merged)) {
    if (typeof raw !== "number" || !Number.isFinite(raw) || !METRIC_LABELS[key]) continue
    if (cards.length < 4 && !cards.some((card) => card.label === METRIC_LABELS[key])) {
      const tone: MetricTone = /drawdown|var_|risk|vol/i.test(key) ? (raw > 0 ? "negative" : "positive") : "ink"
      cards.push({ label: METRIC_LABELS[key], value: formatMetricValue(key, raw), tone })
    }
    // ponytail: QcProgress 的 breach 色对 IC 方向相反（>参考线变红），等 metric-cards 支持方向语义再翻正
    if (rows.length < 4 && !rows.some((row) => row.label === METRIC_LABELS[key])) {
      rows.push({ label: METRIC_LABELS[key], value: raw, threshold: /ic/i.test(key) ? 0.03 : undefined })
    }
  }
  return { cards, rows }
}

function emptyNote() {
  const empty = document.createElement("div")
  empty.className = "qc-empty-state is-compact"
  const note = document.createElement("p")
  note.className = "qc-metrics-empty"
  note.textContent = "暂无研究运行"
  empty.append(note)
  return empty
}

export function FactorFlowView(props: { run: RunAgentResult | null }): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-factor-flow"

  // 上区：研究流程（节点 + css ::after 连线）
  const flow = document.createElement("div")
  flow.className = "qc-factor-flow-section"
  const flowLabel = document.createElement("span")
  flowLabel.className = "qc-section-label"
  flowLabel.textContent = "研究流程"
  flow.append(flowLabel)
  const nodes = flowNodes(props.run)
  if (!nodes.length) {
    flow.append(emptyNote())
  } else {
    const rail = document.createElement("div")
    rail.className = "qc-factor-rail"
    nodes.forEach((node, index) => {
      const card = document.createElement("div")
      card.className = "qc-factor-node"
      if (node.done) card.classList.add("is-done")
      const index0 = document.createElement("span")
      index0.className = "qc-factor-index"
      index0.textContent = String(index + 1).padStart(2, "0")
      const name = document.createElement("strong")
      name.textContent = node.name
      const state = document.createElement("b")
      state.textContent = node.done ? "完成 ✓" : "●"
      card.append(index0, name, state)
      rail.append(card)
    })
    flow.append(rail)
  }

  // 下区：评估指标（QcBigNumber + QcProgress + artifacts）
  const metrics = document.createElement("div")
  metrics.className = "qc-factor-metrics"
  const metricsLabel = document.createElement("span")
  metricsLabel.className = "qc-section-label"
  metricsLabel.textContent = "评估指标"
  metrics.append(metricsLabel)
  const { cards, rows } = props.run ? numericMetrics(props.run) : { cards: [], rows: [] }
  if (!cards.length) {
    metrics.append(emptyNote())
  } else {
    const grid = document.createElement("div")
    grid.className = "qc-metrics-body"
    for (const card of cards) grid.append(QcBigNumber(card))
    metrics.append(grid)
    for (const row of rows) metrics.append(QcProgress(row))
    if (props.run?.artifacts?.length) {
      const artifact = document.createElement("code")
      artifact.className = "qc-artifact"
      artifact.textContent = props.run.artifacts.join("\n")
      metrics.append(artifact)
    }
  }

  root.append(flow, metrics)
  return root
}

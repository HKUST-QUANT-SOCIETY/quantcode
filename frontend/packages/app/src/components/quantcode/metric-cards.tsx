/**
 * 极简指标卡组件：纯 DOM 构建，无 Solid 响应式。
 * bun test 不走 vite-plugin-solid 编译（JSX 会被编译成 React.createElement），
 * 因此这里直接用 DOM 调用返回 HTMLElement；panels.tsx 中作为 JSX 子节点直接插入。
 */

export type MetricTone = "ink" | "positive" | "negative"

/** 指标大数字统一格式化：IC/IR/Sharpe 两位小数，其余三位舍入（panels / factor-screen 同源）。 */
export function formatMetricValue(key: string, raw: number): string {
  if (!Number.isFinite(raw)) return String(raw)
  if (/ir|sharpe|ic/i.test(key)) return raw.toFixed(2)
  if (raw !== 0 && Math.abs(raw) < 0.0005) return raw.toExponential(2)
  return raw.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")
}

export function QcBigNumber(props: { label: string; value: string; tone?: MetricTone }): HTMLElement {
  const root = document.createElement("div")
  root.className = `qc-metric qc-metric-${props.tone ?? "ink"}`
  const label = document.createElement("span")
  label.className = "qc-metric-label"
  label.textContent = props.label
  const value = document.createElement("strong")
  value.className = "qc-metric-value"
  value.textContent = props.value
  root.append(label, value)
  return root
}

/** 比例条：value/threshold 两个 0..1 比例，value 超过 threshold 时条与阈值线转为红色。 */
export function QcProgress(props: { label: string; value: number; threshold?: number }): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-progress"
  const head = document.createElement("div")
  head.className = "qc-progress-head"
  const label = document.createElement("span")
  label.textContent = props.label
  const readout = document.createElement("code")
  readout.textContent = props.threshold === undefined ? `${props.value}` : `${props.value} / ${props.threshold}`
  head.append(label, readout)
  const bar = document.createElement("div")
  bar.className = "qc-progress-bar"
  const fill = document.createElement("i")
  const ratio = Math.max(0, Math.min(1, props.value))
  const breach = props.threshold !== undefined && props.value > props.threshold
  const shown = breach ? Math.min(1, props.threshold ?? 1) : ratio
  fill.style.width = `${Math.round(shown * 100)}%`
  if (breach) bar.classList.add("is-breach")
  const mark = document.createElement("i")
  if (props.threshold !== undefined) mark.style.left = `${Math.max(0, Math.min(1, props.threshold)) * 100}%`
  bar.append(fill, mark)
  root.append(head, bar)
  return root
}

export type ChecklistStatus = "pass" | "fail" | "marginal"

const STATUS_TEXT: Record<ChecklistStatus, string> = { pass: "通过", fail: "不通过", marginal: "边缘" }

export function QcChecklistItem(props: { label: string; status: ChecklistStatus }): HTMLElement {
  const row = document.createElement("div")
  row.className = "qc-checklist"
  const label = document.createElement("span")
  label.textContent = props.label
  const status = document.createElement("b")
  status.className = `qc-checklist-status is-${props.status}`
  status.textContent = STATUS_TEXT[props.status]
  row.append(label, status)
  return row
}

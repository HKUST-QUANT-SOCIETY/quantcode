/**
 * F-05 供应商设置只读视图：纯 DOM 构建（沿 metric-cards 模式，bun test 兼容）。
 * 未取得运行配置时不推断 Provider；只展示已返回的模型与目录信息。
 */

export type SupplierProps = {
  provider?: string
  model?: string
  baseUrl?: string
  algorithms?: (string | { id: string; description?: string })[]
}

const ROWS: { key: keyof Omit<SupplierProps, "algorithms">; label: string; fallback: string }[] = [
  { key: "provider", label: "模型服务商", fallback: "未读取" },
  { key: "model", label: "当前模型", fallback: "未读取" },
  { key: "baseUrl", label: "服务地址", fallback: "未读取" },
]

export function SupplierView(props: SupplierProps): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-supplier"
  for (const row of ROWS) {
    const line = document.createElement("div")
    line.className = "qc-supplier-row"
    const label = document.createElement("span")
    label.className = "qc-supplier-label"
    label.textContent = row.label
    const value = document.createElement("strong")
    value.textContent = props[row.key] ?? row.fallback
    line.append(label, value)
    root.append(line)
  }
  const hint = document.createElement("p")
  hint.className = "qc-supplier-hint"
  hint.textContent = props.model ? "模型信息由当前研究服务提供。" : "当前研究服务尚未提供模型信息。"
  root.append(hint)
  const algorithms = props.algorithms ?? []
  const section = document.createElement("div")
  section.className = "qc-supplier-algorithms"
  const title = document.createElement("span")
  title.className = "qc-section-label"
  title.textContent = "算法目录"
  section.append(title)
  if (algorithms.length === 0) {
    const empty = document.createElement("p")
    empty.className = "qc-supplier-empty"
    empty.textContent = "暂无可见算法。"
    section.append(empty)
  } else {
    const list = document.createElement("ul")
    list.className = "qc-supplier-algorithm-list"
    for (const algorithm of algorithms) {
      const item = document.createElement("li")
      const id = typeof algorithm === "string" ? algorithm : algorithm.id
      const description = typeof algorithm === "string" ? "" : algorithm.description
      item.textContent = description ? `${id} · ${description}` : id
      list.append(item)
    }
    section.append(list)
  }
  root.append(section)
  return root
}

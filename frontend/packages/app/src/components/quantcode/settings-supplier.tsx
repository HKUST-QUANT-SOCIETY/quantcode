/**
 * F-05 供应商设置只读视图：纯 DOM 构建（沿 metric-cards 模式，bun test 兼容）。
 * 浏览器无法读取进程 env，因此这里只展示配置名清单与默认值，
 * 实际取值经 MCP mcp.environment 注入（v0 静态展示，接 list_algorithms 数据另批）。
 */

export type SupplierProps = {
  provider?: string
  model?: string
  baseUrl?: string
  algorithms?: (string | { id: string; description?: string })[]
}

const ROWS: { key: keyof Omit<SupplierProps, "algorithms">; label: string; env: string; fallback: string }[] = [
  { key: "provider", label: "Provider", env: "QUANTCODE_MODEL_PROVIDER", fallback: "未读取" },
  { key: "model", label: "Model", env: "QUANTCODE_MODEL_NAME", fallback: "未读取" },
  { key: "baseUrl", label: "BaseURL", env: "QUANTCODE_MODEL_BASE_URL", fallback: "未读取" },
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
    const name = document.createElement("code")
    name.textContent = row.env
    const value = document.createElement("strong")
    value.textContent = props[row.key] ?? row.fallback
    line.append(label, name, value)
    root.append(line)
  }
  const hint = document.createElement("p")
  hint.className = "qc-supplier-hint"
  hint.textContent = "运行配置由 mcp.environment 管理；未读取时不推断 Provider 或模型。"
  root.append(hint)
  const algorithms = props.algorithms ?? []
  const section = document.createElement("div")
  section.className = "qc-supplier-algorithms"
  const title = document.createElement("span")
  title.className = "qc-section-label"
  title.textContent = "ALGORITHMS"
  section.append(title)
  if (algorithms.length === 0) {
    const empty = document.createElement("p")
    empty.className = "qc-supplier-empty"
    empty.textContent = "算法目录将随 list_algorithms 联动"
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

import { getOwner, onCleanup } from "solid-js"
import type { QuantCodeAlgorithm } from "./api"
import { viewEmpty } from "./workspace-ui"

/** Published algorithm metadata only; algorithm execution remains in research tasks. */
export function AlgorithmCatalogView(props: { fetcher: () => Promise<QuantCodeAlgorithm[]> }): HTMLElement {
  const root = document.createElement("section")
  root.className = "qc-algorithm-catalog"
  root.setAttribute("aria-label", "已发布算法")
  let revision = 0
  if (getOwner()) onCleanup(() => { revision++ })
  const load = async () => {
    const current = ++revision
    root.replaceChildren(viewEmpty("正在加载算法目录…", "brain"))
    try {
      const algorithms = await props.fetcher()
      if (current !== revision) return
      const intro = document.createElement("p")
      intro.className = "qc-catalog-intro"
      intro.textContent = "维护员发布的算法，可在研究任务中引用。演示与占位实现请以算法说明为准。"
      const refresh = document.createElement("button")
      refresh.type = "button"
      refresh.className = "qc-button qc-button-secondary"
      refresh.textContent = "刷新算法目录"
      refresh.onclick = () => void load()
      root.replaceChildren(intro, refresh)
      if (!algorithms.length) root.append(viewEmpty("暂无已发布算法", "brain"))
      for (const algorithm of algorithms) {
        const item = document.createElement("article")
        item.className = "qc-algorithm-entry"
        const title = document.createElement("h3")
        title.textContent = algorithm.id.replaceAll("_", " ")
        const id = document.createElement("code")
        id.textContent = algorithm.id
        const details = document.createElement("details")
        const summary = document.createElement("summary")
        summary.textContent = "查看算法说明"
        const description = document.createElement("p")
        description.textContent = algorithm.description || "维护员尚未提供说明。"
        details.append(summary, description)
        item.append(title, id, details)
        root.append(item)
      }
    } catch {
      if (current !== revision) return
      const error = viewEmpty("算法目录暂不可用", "brain")
      error.setAttribute("role", "alert")
      const retry = document.createElement("button")
      retry.type = "button"
      retry.className = "qc-button qc-button-secondary"
      retry.textContent = "重试"
      retry.onclick = () => void load()
      error.append(retry)
      root.replaceChildren(error)
    }
  }
  void load()
  return root
}

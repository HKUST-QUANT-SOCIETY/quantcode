import { Show, type JSX } from "solid-js"
import { Icon, type IconProps } from "@opencode-ai/ui/icon"

export function WorkspaceEmpty(props: { icon: IconProps["name"]; title: string; description?: string; children?: JSX.Element }) {
  return <div class="qc-workspace-empty">
    <span class="qc-empty-symbol"><Icon name={props.icon} size="large" /></span>
    <h3>{props.title}</h3>
    <Show when={props.description}><p>{props.description}</p></Show>
    {props.children}
  </div>
}

export function RefreshAction(props: { label: string; disabled?: boolean; onClick: () => void }) {
  return <button type="button" class="qc-icon-action" aria-label={props.label} title={props.label} disabled={props.disabled} onClick={props.onClick}>
    <Icon name="reset" size="normal" />
  </button>
}

export function navigateViewTabs(event: KeyboardEvent & { currentTarget: HTMLDivElement }) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
  const tabs = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  const current = tabs.indexOf(event.target as HTMLButtonElement)
  if (current < 0) return
  event.preventDefault()
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
    (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length
  tabs[next]?.focus()
  tabs[next]?.click()
}

export function userFacingServiceError(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : String(error ?? "")
  if (/management request rejected|production executor|deploy.*503/i.test(message)) {
    return "生产管理通道尚未配置，部署请求保持 STAGING。"
  }
  if (/github identity token|github.*token.*not connected/i.test(message)) {
    return "GitHub 身份尚未连接，GitGraph 暂不可用。"
  }
  if (/identity service unavailable|quantcode read-only service/i.test(message)) {
    return "数据通道暂不可用，请检查研究服务连接。"
  }
  if (/^Error:\s*/i.test(message)) return message.replace(/^Error:\s*/i, "")
  return message || fallback
}

export function runStatusLabel(status: string) {
  return ({ completed: "已完成", running: "运行中", waiting_for_human: "待审批", rejected: "已拒绝", error: "异常", failed: "失败", stopped_budget: "预算停止", stopped_loop: "循环停止" } as Record<string, string>)[status] ?? status
}

// Legacy DOM views share the same icon sprite and empty-state styling.
export function viewIcon(name: IconProps["name"]) {
  const element = document.createElement("span")
  element.className = "qc-view-icon"
  element.setAttribute("aria-hidden", "true")
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
  svg.setAttribute("viewBox", name === "magnifying-glass" ? "0 0 16 16" : "0 0 20 20")
  svg.setAttribute("width", "20")
  svg.setAttribute("height", "20")
  svg.setAttribute("fill", "none")
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use")
  use.setAttribute("href", `#opencode-icon-${name}`)
  svg.append(use)
  element.append(svg)
  return element
}

export function viewEmpty(title: string, icon: IconProps["name"]) {
  const element = document.createElement("div")
  element.className = "qc-workspace-empty"
  const symbol = viewIcon(icon)
  symbol.classList.add("qc-empty-symbol")
  const heading = document.createElement("h3")
  heading.textContent = title
  element.append(symbol, heading)
  return element
}

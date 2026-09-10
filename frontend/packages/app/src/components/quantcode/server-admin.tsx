import type { QuantCodeDesktopIdentity } from "../../identity"
import { loginError } from "./ssh-login"

/** SSH operations owns its own session. No research directory, organization
 * token or model instruction is created by this view. */
export function ServerAdminView(props: {
  status: QuantCodeDesktopIdentity["sshAdminStatus"]
  disconnect: QuantCodeDesktopIdentity["sshAdminDisconnect"]
  organization: (serverId: string) => Promise<void>
  onDisconnected: () => void
}): HTMLElement {
  const root = document.createElement("section")
  root.className = "qc-detail-body"
  const title = document.createElement("h3")
  title.textContent = "服务器运维"
  const account = document.createElement("p")
  const note = document.createElement("p")
  note.className = "qc-muted"
  note.textContent = "通过服务器 SSH 管理权限查看系统状态。组织审批、成员和发布使用独立的组织管理身份。"
  const output = document.createElement("pre")
  output.className = "qc-code-block"
  const error = document.createElement("p")
  error.setAttribute("role", "alert")
  const actions = document.createElement("div")
  actions.className = "qc-gate-actions"
  const refresh = document.createElement("button")
  const organization = document.createElement("button")
  const disconnect = document.createElement("button")
  for (const button of [refresh, organization, disconnect]) { button.type = "button"; button.className = "qc-button qc-button-secondary" }
  refresh.textContent = "刷新服务器状态"
  organization.textContent = "进入组织管理"
  disconnect.textContent = "退出服务器运维"
  actions.append(refresh, organization, disconnect)
  root.append(title, account, note, actions, error, output)
  let serverId = ""
  let busy = false
  const run = async (action: () => Promise<void>) => {
    if (busy) return
    busy = true
    error.textContent = ""
    for (const button of [refresh, organization, disconnect]) button.disabled = true
    try { await action() } catch (cause) { error.textContent = loginError(cause, "服务器状态读取失败。") }
    finally {
      busy = false
      refresh.disabled = false
      organization.disabled = !serverId
      disconnect.disabled = false
    }
  }
  const load = async () => {
    const current = await props.status()
    if (!current) { props.onDisconnected(); return }
    serverId = current.session.serverId
    account.textContent = `${current.session.username} · ${current.session.serverLabel}`
    output.textContent = current.report
  }
  refresh.addEventListener("click", () => void run(load))
  organization.addEventListener("click", () => void run(() => props.organization(serverId)))
  disconnect.addEventListener("click", () => void run(async () => { await props.disconnect(); props.onDisconnected() }))
  void run(load)
  return root
}

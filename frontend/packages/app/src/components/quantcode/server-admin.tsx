import type { QuantCodeDesktopIdentity } from "../../identity"
import { loginError } from "./ssh-login"

/** A feature of the unified administrator workspace, with no separate login. */
export function ServerAdminView(props: {
  status: QuantCodeDesktopIdentity["sshAdminStatus"]
  onDisconnected: () => void
}): HTMLElement {
  const root = document.createElement("section")
  root.className = "qc-detail-body"
  const title = document.createElement("h3")
  title.textContent = "服务器状态"
  const account = document.createElement("p")
  const output = document.createElement("pre")
  output.className = "qc-code-block"
  const error = document.createElement("p")
  error.setAttribute("role", "alert")
  error.hidden = true
  const actions = document.createElement("div")
  actions.className = "qc-gate-actions"
  const select = document.createElement("select")
  select.className = "qc-select-wide"
  select.setAttribute("aria-label", "服务器")
  for (const id of ["a", "b", "c"]) {
    const option = document.createElement("option")
    option.value = `server-${id}`
    option.textContent = `Server ${id.toUpperCase()}`
    select.append(option)
  }
  select.value = "server-c"
  const refresh = document.createElement("button")
  refresh.type = "button"
  refresh.className = "qc-button qc-button-secondary"
  refresh.textContent = "刷新状态"
  actions.append(select, refresh)
  root.append(title, account, actions, error, output)
  let busy = false
  const load = async () => {
    if (busy) return
    busy = true
    error.hidden = true
    refresh.disabled = true
    select.disabled = true
    try {
      const current = await props.status({ serverId: select.value })
      if (!current) { props.onDisconnected(); return }
      account.textContent = `${current.session.username} · 管理员 · ${current.session.serverLabel}`
      output.textContent = current.report
    } catch (cause) {
      error.textContent = loginError(cause, "服务器状态读取失败。")
      error.hidden = false
    } finally { busy = false; refresh.disabled = false; select.disabled = false }
  }
  refresh.addEventListener("click", () => void load())
  select.addEventListener("change", () => void load())
  void load()
  return root
}

import type { QuantCodeDesktopIdentity, QuantCodeSshLoginScan, QuantCodeSshLoginResult, QuantCodeSshLoginChoice } from "../../identity"
import { getOwner, onCleanup } from "solid-js"

/**
 * F-05 SSH 登录界面：完整登录流四态（表单 → 连接 → 已连接 / 失败）。
 * 纯 DOM 构建（沿 settings-supplier / notifications 模式，bun test 兼容），
 * 状态切换由内部 render() 重绘；panels.tsx settings 分支挂载。
 *
 * 安全约束：组件只接收本地 SSH Agent/Keychain identity id，不接收私钥文本；
 * identity id 不写入 localStorage / 任何 store。
 */

export type SshLoginStatus = "form" | "connecting" | "connected" | "disconnecting" | "error"

export type SshConnectInput = {
  host: string
  user: string
  /** Local SSH Agent/Keychain identity selected by the desktop bridge. */
  identityId: string
  group?: string
  /** 连接过程中逐行追加日志 */
  log: (line: string) => void
}

export type SshConnectResult =
  | { status: "connected"; fingerprint: string; group?: string; groups?: string[] }
  | { status: "error"; reason: string }

export type SshConnectFn = (input: SshConnectInput) => Promise<SshConnectResult>
export type SshSession = Extract<SshConnectResult, { status: "connected" }>
export type SshDisconnectFn = () => Promise<{ status: "disconnected" } | { status: "error"; reason: string }>

export type SshIdentity = {
  id: string
  label: string
  host: string
  user: string
  fingerprint?: string
  group?: string
  groups?: string[]
}

/**
 * Isolated consumers keep a deterministic unavailable fallback. The production
 * QuantCode panel injects the server-backed implementation from api.ts.
 */
export const stubSshConnect: SshConnectFn = async ({ log }) => {
  log("waiting for ssh_status (W3) …")
  return { status: "error", reason: "unavailable" }
}

/** 已知失败原因 → i18n key；未知原因原样展示（后端可下发更具体文案）。 */
const REASON_KEYS: Record<string, string> = {
  key_rejected: "quantcode.ssh.reason.key_rejected",
  host_unreachable: "quantcode.ssh.reason.host_unreachable",
  unavailable: "quantcode.ssh.reason.unavailable",
}

export type SshLoginProps = {
  /** i18n：panels 传 language.t（key 见 quantcode.ssh.*，18 locale 均已补齐） */
  t: (key: string) => string
  /** 可注入的连接实现；默认 stub（见上） */
  connect?: SshConnectFn
  /** Identities supplied by the local SSH Agent/Keychain bridge. */
  identities?: SshIdentity[]
  session?: SshSession
  disconnect?: SshDisconnectFn
  /** 通过系统文件选择器把私钥加入本机 SSH Agent；私钥正文不上传。 */
  importKey?: () => Promise<{ fingerprint: string } | null>
}

export function SshLoginView(props: SshLoginProps): HTMLElement {
  const t = props.t
  const connect = props.connect ?? stubSshConnect
  const identities = props.identities ?? []
  const root = document.createElement("div")
  root.className = "qc-ssh"

  let status: SshLoginStatus = props.session ? "connected" : "form"
  let identityId = identities[0]?.id ?? ""
  let host = identities[0]?.host ?? ""
  let user = identities[0]?.user ?? ""
  let group = props.session?.group ?? identities[0]?.group ?? ""
  let fingerprint = props.session?.fingerprint ?? ""
  let groups: string[] = props.session?.groups ?? []
  let reason = ""
  let logs: string[] = []
  let logEl: HTMLPreElement | undefined

  const appendLog = (line: string) => {
    logs.push(line)
    if (logEl) logEl.textContent = logs.join("\n")
  }

  const renderForm = () => {
    if (identities.length === 0) {
      const status = document.createElement("span")
      status.className = "qc-status qc-status-error"
      status.textContent = t("quantcode.ssh.reason.unavailable")
      const hint = document.createElement("p")
      hint.className = "qc-ssh-hint"
      hint.textContent = "未发现可用的本机 SSH 身份。"
      root.replaceChildren(status, hint)
      // 空身份时仍提供导入私钥入口：按钮走本机 ssh-add，成功后触发外层刷新。
      if (props.importKey) {
        const importButton = document.createElement("button")
        importButton.type = "button"
        importButton.className = "qc-button qc-button-secondary"
        importButton.textContent = "选择本地私钥文件登录"
        importButton.addEventListener("click", () => {
          importButton.disabled = true
          void props.importKey!()
            .then(fingerprint => {
              if (!fingerprint) {
                importButton.disabled = false
                return
              }
              hint.textContent = `私钥已加入本机 Agent（${fingerprint.fingerprint}）。正在刷新研究宿主身份…`
            })
            .catch(error => {
              hint.textContent = error instanceof Error ? error.message : "SSH 私钥导入失败，请重试。"
              importButton.disabled = false
            })
        })
        root.append(importButton)
      }
      return
    }

    const identityLabel = document.createElement("label")
    identityLabel.className = "qc-field-label"
    identityLabel.htmlFor = "qc-ssh-identity"
    identityLabel.textContent = "登录身份"
    const identitySelect = document.createElement("select")
    identitySelect.id = "qc-ssh-identity"
    identitySelect.className = "qc-select-wide"
    for (const identity of identities) {
      const option = document.createElement("option")
      option.value = identity.id
      option.textContent = identity.label
      identitySelect.append(option)
    }
    identitySelect.value = identityId
    identitySelect.addEventListener("change", () => {
      identityId = identitySelect.value
      const identity = identities.find((item) => item.id === identityId)
      host = identity?.host ?? ""
      user = identity?.user ?? ""
      group = identity?.group ?? ""
      render()
    })

    const target = document.createElement("code")
    target.className = "qc-artifact"
    target.textContent = host

    const submit = document.createElement("button")
    submit.type = "button"
    submit.className = "qc-button qc-button-primary"
    submit.textContent = t("quantcode.ssh.connect")
    const authorized = identities.find(identity => identity.id === identityId)?.groups ?? []
    submit.disabled = !identityId || (authorized.length > 0 && !authorized.includes(group))

    submit.addEventListener("click", () => {
      status = "connecting"
      reason = ""
      logs = [t("quantcode.ssh.logWaiting")]
      render()
      void attempt()
    })

    const actions = document.createElement("div")
    actions.className = "qc-gate-actions"
    actions.append(submit)
    root.replaceChildren(identityLabel, identitySelect, target)
    if (authorized.length) {
      const label = document.createElement("label")
      label.htmlFor = "qc-ssh-group"
      label.className = "qc-field-label"
      label.textContent = t("quantcode.group.label")
      const select = document.createElement("select")
      select.id = "qc-ssh-group"
      select.className = "qc-select-wide"
      for (const value of authorized) {
        const option = document.createElement("option")
        option.value = value
        option.textContent = value
        select.append(option)
      }
      select.value = group
      select.addEventListener("change", () => {
        group = select.value
        submit.disabled = !authorized.includes(group)
      })
      root.append(label, select)
    }
    if (props.importKey) {
      // 重新登录主路径：选择本地私钥文件 → 加入本机 Agent → 自动继续连接。
      const importButton = document.createElement("button")
      importButton.type = "button"
      importButton.className = "qc-button qc-button-secondary"
      importButton.textContent = "重新登录：选择本地私钥"
      importButton.addEventListener("click", () => {
        importButton.disabled = true
        void props.importKey!()
          .then(fingerprint => {
            if (!fingerprint) {
              importButton.disabled = false
              return
            }
            reason = ""
            status = "connecting"
            logs = [`私钥已加入本机 Agent（${fingerprint.fingerprint}），继续登录…`]
            render()
            void attempt()
          })
          .catch(error => {
            reason = error instanceof Error ? error.message : "SSH 私钥导入失败，请重试。"
            status = "error"
            render()
          })
      })
      actions.append(importButton)
    }
    root.append(actions)
  }

  const attempt = async () => {
    const result = await connect({ host, user, identityId, group: group || undefined, log: appendLog }).catch(
      (): SshConnectResult => {
        // 合同外异常（注入实现 throw）按网络不可达处理
        return { status: "error", reason: "host_unreachable" }
      },
    )
    if (result.status === "connected") {
      status = "connected"
      fingerprint = result.fingerprint
      group = result.group ?? group
      groups = result.groups ?? []
    } else {
      status = "error"
      reason = result.reason
    }
    render()
  }

  const renderConnecting = () => {
    const pill = document.createElement("span")
    pill.className = "qc-connection-pill"
    const dot = document.createElement("i")
    dot.className = "qc-ssh-spinner"
    // ponytail: 全局 pulse-opacity keyframes（@opencode-ai/ui animations.css）做单点 spinner，免动 panels.css
    dot.style.animation = "pulse-opacity 1.2s ease-in-out infinite"
    pill.append(dot, document.createTextNode(t("quantcode.ssh.connecting")))

    logEl = document.createElement("pre")
    logEl.className = "qc-code-block qc-ssh-log"
    logEl.textContent = logs.join("\n")
    root.replaceChildren(pill, logEl)
  }

  const renderConnected = () => {
    const pill = document.createElement("span")
    pill.className = "qc-connection-pill"
    pill.append(document.createElement("i"), document.createTextNode(t("quantcode.ssh.connected")))

    const fpLabel = document.createElement("span")
    fpLabel.className = "qc-section-label"
    fpLabel.textContent = t("quantcode.ssh.fingerprint")
    const fp = document.createElement("code")
    fp.className = "qc-artifact qc-ssh-fingerprint"
    fp.textContent = fingerprint

    root.replaceChildren(pill, fpLabel, fp)
    if (group) {
      const label = document.createElement("span")
      label.className = "qc-section-label"
      label.textContent = t("quantcode.group.label")
      const active = document.createElement("code")
      active.dataset.sessionGroup = group
      active.textContent = group
      root.append(label, active)
    }

    if (groups.length > 0) {
      const groupLabel = document.createElement("span")
      groupLabel.className = "qc-section-label"
      groupLabel.textContent = t("quantcode.ssh.groups")
      const badgeRow = document.createElement("div")
      badgeRow.className = "qc-ssh-badges"
      badgeRow.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;"
      for (const group of groups) {
        const badge = document.createElement("span")
        badge.className = "qc-connection-pill qc-ssh-badge"
        badge.textContent = `${group} ${t("quantcode.ssh.groupSuffix")}`
        badgeRow.append(badge)
      }
      root.append(groupLabel, badgeRow)
    }

    const disconnect = document.createElement("button")
    disconnect.type = "button"
    disconnect.className = "qc-button qc-button-secondary"
    disconnect.textContent = t("quantcode.ssh.disconnect")
    disconnect.disabled = status === "disconnecting" || !props.disconnect
    disconnect.setAttribute("aria-busy", String(status === "disconnecting"))
    disconnect.addEventListener("click", () => {
      if (!props.disconnect || status === "disconnecting") return
      status = "disconnecting"
      reason = ""
      render()
      void props.disconnect().catch(() => ({ status: "error" as const, reason: t("quantcode.ssh.reason.host_unreachable") })).then(result => {
        if (result.status === "disconnected") {
          status = "form"
          fingerprint = ""
          groups = []
        } else {
          status = "connected"
          reason = result.reason
        }
        render()
      })
    })
    const actions = document.createElement("div")
    actions.className = "qc-gate-actions"
    actions.append(disconnect)
    root.append(actions)
    if (reason) {
      const error = document.createElement("p")
      error.setAttribute("role", "alert")
      error.textContent = reason
      root.append(error)
    }
  }

  const renderFailed = () => {
    const chip = document.createElement("span")
    chip.className = "qc-status qc-status-error"
    chip.textContent = t("quantcode.ssh.failed")

    const detail = document.createElement("p")
    detail.className = "qc-ssh-reason"
    detail.setAttribute("role", "alert")
    detail.textContent = REASON_KEYS[reason] ? t(REASON_KEYS[reason]) : reason

    const retry = document.createElement("button")
    retry.type = "button"
    retry.className = "qc-button qc-button-primary"
    retry.textContent = t("quantcode.ssh.retry")
    retry.addEventListener("click", () => {
      status = "form"
      render()
    })
    const actions = document.createElement("div")
    actions.className = "qc-gate-actions"
    actions.append(retry)
    root.replaceChildren(chip, detail, actions)
  }

  const render = () => {
    logEl = undefined
    if (status === "form") renderForm()
    else if (status === "connecting") renderConnecting()
    else if (status === "connected" || status === "disconnecting") renderConnected()
    else renderFailed()
  }

  render()
  return root
}

/** 选私钥 → 探测 → 点组选宿主并认证；只有正式会话才能进入工作台。 */
export function SshOrgLoginWizard(props: {
  sshSelectKey?: QuantCodeDesktopIdentity["sshSelectKey"]
  sshCancel?: QuantCodeDesktopIdentity["sshCancel"]
  sshProgress?: QuantCodeDesktopIdentity["sshProgress"]
  sshScan: QuantCodeDesktopIdentity["sshScan"]
  sshConnect: QuantCodeDesktopIdentity["sshConnect"]
  onEnter: (result: QuantCodeSshLoginResult, signal?: AbortSignal) => Promise<void>
  autoStart?: boolean
  onStarted?: () => void
  timeoutMs?: number
}): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-ssh"
  let scan: QuantCodeSshLoginScan | undefined
  let username = ""
  let showUsername = false
  let busy = false
  let error = ""
  let progress = ""
  let phase: "selecting" | "scanning" | "connecting" | undefined
  let revision = 0
  let disposed = false
  let active: AbortController | undefined
  let cleanup: (() => void) | undefined
  const details = document.createElement("details")
  const detailTitle = document.createElement("summary")
  detailTitle.textContent = "SSH 连接详情"
  const log = document.createElement("pre")
  log.className = "qc-code-block qc-ssh-log"
  log.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere;max-height:18rem;overflow:auto"
  log.textContent = "选择私钥后，这里会显示服务器、身份验证和工作区连接进度。"
  details.append(detailTitle, log)
  let readingProgress = false
  const readProgress = async (request: number) => {
    if (!props.sshProgress || readingProgress || disposed || request !== revision) return
    readingProgress = true
    try { const lines = await props.sshProgress(); if (!disposed && request === revision && lines.length) log.textContent = lines.join("\n") }
    catch { /* Progress is informational; login errors stay in the form. */ }
    finally { readingProgress = false }
  }
  const watchProgress = (request: number) => {
    details.open = true
    void readProgress(request)
    const timer = setInterval(() => void readProgress(request), 500)
    return () => { clearInterval(timer); void readProgress(request) }
  }

  const cancelled = (promise: Promise<unknown>, signal: AbortSignal) => new Promise<unknown>((resolve, reject) => {
    const abort = () => reject(new Error("本次登录已取消。"))
    if (signal.aborted) { abort(); return }
    signal.addEventListener("abort", abort, { once: true })
    void promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort))
  })
  const cancel = (message = "") => {
    if (!active) return
    const previous = active
    active = undefined
    revision++
    cleanup?.()
    cleanup = undefined
    previous.abort()
    busy = false
    phase = undefined
    scan = undefined
    error = message
    void props.sshCancel?.().catch(() => {})
    if (!disposed) render()
  }
  const watch = (request: number) => {
    const stop = watchProgress(request)
    const timer = setTimeout(() => cancel("本次登录等待超时。可以重试或重新选择私钥。"), props.timeoutMs ?? 90000)
    const finish = () => { clearTimeout(timer); stop() }
    cleanup = finish
    return finish
  }
  if (getOwner()) onCleanup(() => { disposed = true; cancel() })

  const scanKey = async (chooseKey: boolean) => {
    if (busy) return
    const controller = new AbortController()
    active = controller
    const request = ++revision
    const current = () => !disposed && revision === request
    busy = true
    error = ""
    phase = chooseKey && props.sshSelectKey ? "selecting" : "scanning"
    progress = phase === "selecting" ? "请在文件选择窗口选择本地私钥，取消可返回登录。" : "正在探测组织服务器（Server A / B / C）…"
    log.textContent = "本次登录的连接进度将在选好私钥后显示。"
    details.open = false
    let stopProgress: (() => void) | undefined
    render()
    try {
      if (chooseKey && props.sshSelectKey) {
        const picked = await cancelled(props.sshSelectKey(), controller.signal)
        if (!current() || !picked) return
      }
      if (!current()) return
      phase = "scanning"
      progress = "正在探测组织服务器（Server A / B / C）…"
      stopProgress = watch(request)
      render()
      const result = await cancelled(props.sshScan({ chooseKey: chooseKey && !props.sshSelectKey, username: username || undefined }), controller.signal) as QuantCodeSshLoginScan | null
      if (!current()) return
      if (!result) return
      username = result.username
      showUsername = !!result.needsUsername
      scan = result.needsUsername ? undefined : result
    } catch (cause) {
      if (!current()) return
      error = loginError(cause, "登录探测失败，请重试。")
      showUsername = true
      scan = undefined
    } finally {
      stopProgress?.()
      if (current()) { cleanup = undefined; active = undefined; busy = false; phase = undefined; render() }
    }
  }

  const enter = async (choice: QuantCodeSshLoginChoice, label: string) => {
    if (busy) return
    const controller = new AbortController()
    active = controller
    const request = ++revision
    const current = () => !disposed && revision === request
    busy = true
    phase = "connecting"
    error = ""
    progress = `正在连接${label}…`
    const stopProgress = watch(request)
    render()
    try {
      const result = await cancelled(props.sshConnect(choice), controller.signal) as QuantCodeSshLoginResult
      if (current()) await props.onEnter(result, controller.signal)
    }
    catch (cause) { if (current()) error = loginError(cause, "登录失败，请重试。") }
    finally { stopProgress(); if (current()) { cleanup = undefined; active = undefined; busy = false; phase = undefined; render() } }
  }

  const render = () => {
    root.replaceChildren()
    if (busy) {
      const status = document.createElement("p")
      status.className = "qc-connection-pill"
      status.setAttribute("role", "status")
      status.textContent = progress
      const pick = document.createElement("button")
      pick.type = "button"
      pick.className = "qc-button qc-button-primary"
      pick.textContent = phase === "selecting" ? "正在选择私钥文件…" : "重新登录"
      pick.disabled = true
      root.append(status, pick)
      if (phase !== "selecting") {
        const stop = document.createElement("button")
        stop.type = "button"
        stop.className = "qc-button qc-button-secondary"
        stop.textContent = "取消本次登录"
        stop.addEventListener("click", () => cancel())
        root.append(stop)
      }
      root.append(details)
      return
    }
    if (error) {
      const alert = document.createElement("p")
      alert.setAttribute("role", "alert")
      alert.textContent = error
      root.append(alert)
    }
    if (scan) {
      const hint = document.createElement("p")
      hint.className = "qc-ssh-hint"
      hint.textContent = scan.administrators?.length ? "检测到管理员身份，登录后进入完整工作台。" : "选择工作组，直接进入对应服务器的工作区。"
      root.append(hint)
      for (const server of scan.servers) {
        for (const group of server.groups) {
          const row = document.createElement("button")
          row.type = "button"
          row.className = "qc-button qc-button-secondary qc-ssh-group-option"
          row.style.cssText = "display:flex;justify-content:space-between;width:100%;margin-bottom:6px"
          const labels: Record<string, string> = { factor: "因子组", model: "Model 组", fundamental: "基本面组", risk: "风控组", strategy: "策略组", options: "期权组", infra: "基建组", agent: "Agent 组" }
          row.textContent = `✓ ${labels[group] ?? group} · ${server.label}`
          row.addEventListener("click", () => void enter({ serverId: server.id, group }, `${server.label} 的${labels[group] ?? group}`))
          root.append(row)
        }
      }
      if (scan.administrators?.length) {
        const organization = document.createElement("button")
        organization.type = "button"
        organization.className = "qc-button qc-button-secondary qc-ssh-admin-option"
        organization.style.cssText = "display:block;width:100%;margin-bottom:6px;text-align:left"
        organization.textContent = "管理员登录 · 全部权限"
        organization.disabled = !scan.administrators.some(server => server.id === "server-c")
        organization.addEventListener("click", () => void enter({ serverId: "server-c", administrator: "organization" }, "管理员工作台"))
        root.append(organization)
      }
      for (const failed of scan.failed) {
        const note = document.createElement("p")
        note.className = "qc-ssh-hint"
        note.textContent = `✗ ${failed.id.replace("server-", "Server ").toUpperCase()}：${failed.reason}`
        root.append(note)
      }
    }
    if (showUsername) {
      const label = document.createElement("label")
      label.className = "qc-field-label"
      label.textContent = "SSH 用户名（确认后会记住）"
      const input = document.createElement("input")
      input.type = "text"
      input.className = "qc-select-wide"
      input.value = username
      input.placeholder = "例如 qc-chenzhenhong"
      const retry = document.createElement("button")
      retry.type = "button"
      retry.className = "qc-button qc-button-primary"
      retry.textContent = "确认并重新探测"
      retry.disabled = !username.trim()
      input.addEventListener("input", () => {
        username = input.value.trim()
        retry.disabled = !username
      })
      input.addEventListener("keydown", event => { if (event.key === "Enter" && username) void scanKey(false) })
      retry.addEventListener("click", () => void scanKey(false))
      label.append(input)
      root.append(label, retry)
    }
    const pick = document.createElement("button")
    pick.type = "button"
    pick.className = "qc-button qc-button-secondary"
    pick.textContent = scan ? "换一把私钥" : "重新登录"
    pick.addEventListener("click", () => { username = ""; void scanKey(true) })
    root.append(pick, details)
  }
  render()
  if (props.autoStart) queueMicrotask(() => { if (!disposed) { props.onStarted?.(); void scanKey(true) } })
  return root
}

export function loginError(error: unknown, fallback = "登录失败，请重试。") {
  return error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/, "") : fallback
}

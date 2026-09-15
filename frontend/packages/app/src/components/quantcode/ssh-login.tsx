import type { QuantCodeDesktopIdentity, QuantCodeSshLoginScan, QuantCodeSshLoginResult, QuantCodeSshLoginChoice, QuantCodeSshAgentStatus } from "../../identity"
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
  sshUnlockKey?: QuantCodeDesktopIdentity['sshUnlockKey']
  sshAgentStatus?: QuantCodeDesktopIdentity['sshAgentStatus']
  sshStartAgent?: QuantCodeDesktopIdentity['sshStartAgent']
  sshOpenAgentSettings?: QuantCodeDesktopIdentity['sshOpenAgentSettings']
  sshAgentKeys?: QuantCodeDesktopIdentity['sshAgentKeys']
  sshSelectAgent?: QuantCodeDesktopIdentity['sshSelectAgent']
  sshResolve?: QuantCodeDesktopIdentity['sshResolve']
  sshExitAttempt?: QuantCodeDesktopIdentity['sshExitAttempt']
  onExited?: () => void
  sshProgress?: QuantCodeDesktopIdentity["sshProgress"]
  sshScan: QuantCodeDesktopIdentity["sshScan"]
  sshConnect: QuantCodeDesktopIdentity["sshConnect"]
  onEnter: (result: QuantCodeSshLoginResult, signal?: AbortSignal, onCommit?: () => void) => Promise<void>
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
  let phase: "selecting" | "scanning" | "connecting" | 'checking' | 'agent' | undefined
  let pendingResult: QuantCodeSshLoginResult | undefined
  let uncertain = false
  let stopEntering = false
  let committingEntry = false
  let selectedKey = false
  let agentKeys: { fingerprint: string; label: string }[] = []
  let agentStatus: QuantCodeSshAgentStatus | undefined
  let resumeAgentKeys = false
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
    if (phase === 'connecting' || phase === 'checking') {
      stopEntering = true
      progress = '正在核对认证结果；已签发的会话需要明确退出。'
      phase = 'checking'
      if (message || pendingResult) active.abort()
      if (!disposed) render()
      return
    }
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
  if (getOwner()) onCleanup(() => {
    disposed = true
    if (phase === 'scanning' || phase === 'selecting') cancel()
    else { cleanup?.(); if (!committingEntry) active?.abort() }
    window.removeEventListener('quantcode-login-recovery', recover)
  })

  const inspectAgentFailure = async (request: number) => {
    if (!props.sshAgentStatus || !/SSH Agent|OpenSSH/i.test(error)) return
    const status = await props.sshAgentStatus().catch(() => undefined)
    if (disposed || request !== revision || !status) return
    agentStatus = status
    error = ''
    showUsername = false
  }

  const scanKey = async (chooseKey: boolean) => {
    if (busy || uncertain || pendingResult) return
    const controller = new AbortController()
    active = controller
    const request = ++revision
    const current = () => !disposed && revision === request
    busy = true
    error = ""
    agentStatus = undefined
    if (chooseKey) resumeAgentKeys = false
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
        selectedKey = true
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
      await inspectAgentFailure(request)
    } finally {
      stopProgress?.()
      if (current()) { cleanup = undefined; active = undefined; busy = false; phase = undefined; render() }
    }
  }

  const loadAgentKeys = async () => {
    if (busy || disposed || !props.sshAgentKeys) return
    const request = ++revision
    resumeAgentKeys = true
    scan = undefined
    busy = true; phase = 'agent'; error = ''; progress = '正在读取本机 SSH 身份…'; render()
    try {
      const keys = await props.sshAgentKeys()
      if (disposed || request !== revision) return
      agentKeys = keys; agentStatus = undefined
      if (!keys.length) error = '系统 SSH Agent 中没有已加载的身份，请选择私钥文件。'
    } catch (cause) {
      if (!disposed && request === revision) { error = loginError(cause); await inspectAgentFailure(request) }
    } finally {
      if (!disposed && request === revision) { busy = false; phase = undefined; render() }
    }
  }

  const prepareAgent = async (start: boolean) => {
    if (busy || disposed || uncertain || pendingResult || !props.sshAgentStatus) return
    const request = ++revision
    busy = true; phase = 'agent'; error = ''
    progress = start ? '请在 Windows 系统授权窗口确认，正在启用 SSH Agent…' : '正在检查本机 SSH Agent…'
    render()
    let ready = false
    try {
      const result = await (start && props.sshStartAgent ? props.sshStartAgent() : props.sshAgentStatus())
      if (disposed || request !== revision) return
      agentStatus = result
      ready = result.status === 'ready'
      if (ready) agentStatus = undefined
    } catch (cause) { if (!disposed && request === revision) error = loginError(cause, '无法启用 SSH Agent，请重新检查。') }
    finally { if (!disposed && request === revision) { busy = false; phase = undefined; render() } }
    if (!ready || disposed || request !== revision) return
    if (resumeAgentKeys) { await loadAgentKeys(); return }
    await scanKey(!selectedKey)
  }

  const enter = async (choice: QuantCodeSshLoginChoice, label: string) => {
    if (busy) return
    const controller = new AbortController()
    active = controller
    const request = ++revision
    const current = () => !disposed && revision === request
    busy = true
    stopEntering = false
    committingEntry = false
    pendingResult = undefined
    phase = "connecting"
    error = ""
    progress = `正在连接${label}…`
    const stopProgress = watch(request)
    render()
    try {
      const result = await cancelled(props.sshConnect(choice), controller.signal) as QuantCodeSshLoginResult
      if (!current()) return
      pendingResult = result
      if (!stopEntering) {
        await props.onEnter(result, controller.signal, () => { committingEntry = true })
        pendingResult = undefined
        scan = undefined
      }
    }
    catch (cause) { if (current()) { error = pendingResult && controller.signal.aborted ? '已停止进入工作区，组织会话仍有效。' : loginError(cause, "登录结果待核对。"); uncertain = !pendingResult && !!props.sshResolve } }
    finally {
      stopProgress()
      if (current()) {
        cleanup = undefined; active = undefined; busy = false; phase = undefined; render()
        if (uncertain) void checkOutcome()
      }
    }
  }

  const checkOutcome = async () => {
    if (busy || !props.sshResolve || disposed) return
    busy = true; phase = 'checking'; progress = '正在核对上次登录结果…'; render()
    try {
      const result = await props.sshResolve()
      if (disposed) return
      pendingResult = result ?? undefined; uncertain = false
      if (result) error = ''
      else { scan = undefined; error ||= '当前没有已认证的会话，可以重新登录。' }
    } catch (cause) { if (!disposed) { uncertain = true; error = loginError(cause, '认证结果仍未确认，请稍后核对。') } }
    finally { if (!disposed) { busy = false; phase = undefined; render() } }
  }
  const recover = () => { void checkOutcome() }
  window.addEventListener('quantcode-login-recovery', recover)

  const completeEntry = async () => {
    if (!pendingResult || busy) return
    const controller = new AbortController()
    committingEntry = false
    active = controller; busy = true; phase = 'connecting'; progress = '正在进入已认证工作区…'; error = ''
    const stop = watch(++revision)
    render()
    try { await props.onEnter(pendingResult, controller.signal, () => { committingEntry = true }); pendingResult = undefined; scan = undefined }
    catch (cause) { if (!disposed) error = controller.signal.aborted ? '已停止进入工作区，组织会话仍有效。' : loginError(cause) }
    finally { stop(); active = undefined; busy = false; phase = undefined; if (!disposed) render() }
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
      if (phase === 'scanning' || phase === 'connecting') {
        const stop = document.createElement("button")
        stop.type = "button"
        stop.className = "qc-button qc-button-secondary"
        stop.textContent = phase === 'connecting' ? '取消进入，核对登录结果' : "取消本次登录"
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
    if (pendingResult || uncertain) {
      const status = document.createElement('p')
      status.setAttribute('role', 'status')
      status.textContent = pendingResult ? `已认证为 ${pendingResult.session.actor_id}，尚未进入工作区。` : '认证结果待核对，请勿重复登录。'
      root.append(status)
      const resume = document.createElement('button')
      resume.type = 'button'; resume.className = 'qc-button qc-button-primary'
      resume.textContent = pendingResult ? '继续进入工作区' : '核对登录结果'
      resume.onclick = () => { if (pendingResult) void completeEntry(); else void checkOutcome() }
      const exit = document.createElement('button')
      exit.type = 'button'; exit.className = 'qc-button qc-button-secondary'; exit.textContent = '退出本次登录'; exit.disabled = !props.sshExitAttempt
      exit.onclick = async () => {
        if (busy || !props.sshExitAttempt) return
        busy = true; phase = 'checking'; progress = '正在确认退出组织会话…'; render()
        try {
          await props.sshExitAttempt()
          pendingResult = undefined; uncertain = false; scan = undefined; error = ''; props.onExited?.()
        } catch (cause) { error = loginError(cause, '退出尚未确认，请稍后重试。') }
        finally { busy = false; phase = undefined; if (!disposed) render() }
      }
      root.append(resume, exit, details)
      return
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
    if (agentStatus) {
      const message = document.createElement('p')
      message.setAttribute('role', agentStatus.status === 'ready' ? 'status' : 'alert')
      message.textContent = agentStatus.message
      root.append(message)
      if (agentStatus.platform === 'windows' && agentStatus.status === 'stopped' && props.sshStartAgent) {
        const start = document.createElement('button')
        start.type = 'button'; start.className = 'qc-button qc-button-primary'; start.textContent = '启用 SSH Agent 并继续登录'
        start.onclick = () => { void prepareAgent(true) }; root.append(start)
        const hint = document.createElement('p')
        hint.className = 'qc-ssh-hint'; hint.textContent = 'Windows 会请求一次管理员授权，用于启用服务并设置开机自动启动。'
        root.append(hint)
      }
      if (agentStatus.platform === 'windows' && ['missing-client', 'missing-service'].includes(agentStatus.status)) {
        const hint = document.createElement('p')
        hint.className = 'qc-ssh-hint'; hint.textContent = '在 Windows“可选功能”中添加 OpenSSH 客户端，安装完成后点击下方重新检查。'
        root.append(hint)
        if (props.sshOpenAgentSettings) {
          const settings = document.createElement('button')
          settings.type = 'button'; settings.className = 'qc-button qc-button-secondary'; settings.textContent = '打开 Windows 可选功能'
          settings.onclick = () => { void props.sshOpenAgentSettings!().catch(cause => { if (!disposed) { error = loginError(cause); render() } }) }
          root.append(settings)
        }
      }
      const retry = document.createElement('button')
      retry.type = 'button'; retry.className = 'qc-button qc-button-secondary'
      retry.textContent = agentStatus.status === 'ready' ? '继续登录' : '重新检查并继续登录'
      retry.onclick = () => { void prepareAgent(false) }; root.append(retry, details)
      return
    }
    if (showUsername) {
      const label = document.createElement("label")
      label.className = "qc-field-label"
      label.textContent = "SSH 用户名（沿用原账号，确认后记住）"
      const input = document.createElement("input")
      input.type = "text"
      input.className = "qc-select-wide"
      input.value = username
      input.placeholder = "填写平时 SSH 登录使用的用户名"
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
    root.append(pick)
    if (selectedKey && !scan) {
      const retry = document.createElement('button')
      retry.type = 'button'; retry.className = 'qc-button qc-button-secondary'; retry.textContent = '重新探测所选身份'
      retry.onclick = () => { void scanKey(false) }; root.append(retry)
    }
    if (props.sshUnlockKey && /私钥需要解锁/.test(error)) {
      const unlock = document.createElement('button')
      unlock.type = 'button'; unlock.className = 'qc-button qc-button-primary'; unlock.textContent = '在本机终端解锁私钥'
      unlock.onclick = () => { void props.sshUnlockKey!().catch(cause => { error = loginError(cause); render() }) }
      root.append(unlock)
    }
    if (props.sshAgentKeys && props.sshSelectAgent) {
      const useAgent = document.createElement('button')
      useAgent.type = 'button'; useAgent.className = 'qc-button qc-button-secondary'; useAgent.textContent = '使用已有 SSH 身份'
      useAgent.onclick = () => { void loadAgentKeys() }
      root.append(useAgent)
      for (const key of agentKeys) {
        const choose = document.createElement('button')
        choose.type = 'button'; choose.className = 'qc-button qc-button-secondary'; choose.textContent = key.label
        choose.onclick = async () => {
          if (busy) return
          busy = true
          try { await props.sshSelectAgent!({ fingerprint: key.fingerprint }); selectedKey = true; resumeAgentKeys = false; agentKeys = []; username = ''; busy = false; if (!disposed) await scanKey(false) }
          catch (cause) { busy = false; error = loginError(cause); if (!disposed) render() }
        }
        root.append(choose)
      }
    }
    if (props.sshResolve) {
      const check = document.createElement('button')
      check.type = 'button'; check.className = 'qc-button qc-button-secondary'; check.textContent = '核对上次登录状态'
      check.onclick = recover; root.append(check)
    }
    root.append(details)
  }
  render()
  if (props.autoStart) queueMicrotask(() => { if (!disposed) { props.onStarted?.(); void scanKey(true) } })
  else if (props.sshResolve) queueMicrotask(() => {
    if (disposed || busy) return
    const request = revision
    void props.sshResolve!().then(result => { if (!disposed && !busy && request === revision && result) { pendingResult = result; render() } }).catch(() => {})
  })
  return root
}

export function loginError(error: unknown, fallback = "登录失败，请重试。") {
  return error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/, "") : fallback
}

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
  /** 组织 SSH 登录向导：选择本地私钥 → 探测三台内置服务器 → 返回 (组 × 服务器)。 */
  sshScan?: (input: { keyFile: string; username?: string }) => Promise<
    { username: string; servers: { id: string; label: string; groups: string[] }[]; failed: { id: string; reason: string }[] }
  >
  /** 选定组后对该服务器做一次登录校验。 */
  sshProbe?: (input: { keyFile: string; username: string }) => Promise<{ ok: true } | { ok: false; reason: string }>
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

/**
 * 组织 SSH 重新登录向导：选本地私钥 → 自动探测三台内置服务器 → (组 × 服务器) 清单 → 选组进入。
 * 成员全程只碰两样东西：私钥文件、组清单。服务器地址内置，无 URL/端口/密码。
 * desktop 桥未注入（web/dev）时组件不渲染任何内容。
 */
export function SshOrgLoginWizard(props: {
  sshScan: (input: { keyFile: string; username?: string }) => Promise<
    { username: string; servers: { id: string; label: string; groups: string[] }[]; failed: { id: string; reason: string }[] }
  >
  sshProbe: (input: { keyFile: string; username: string }) => Promise<{ ok: true } | { ok: false; reason: string }>
  /** 选定 (组, 服务器) 后的进入动作。 */
  onEnter: (input: { group: string; serverId: string; serverLabel: string; username: string }) => void
  /** 记住的最近一次用户名（可选，向导里可改）。 */
  rememberedUsername?: string
}): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-ssh"

  type Stage = "pick" | "scanning" | "groups"
  let stage: Stage = "pick"
  let keyFile = ""
  let username = props.rememberedUsername ?? ""
  let askUsername = false
  let scanError = ""
  let scanResult: { username: string; servers: { id: string; label: string; groups: string[] }[]; failed: { id: string; reason: string }[] } | undefined
  let enterBusy = false

  const renderPick = () => {
    const title = document.createElement("p")
    title.className = "qc-ssh-hint"
    title.textContent = "选择你本地保存的 SSH 私钥文件（私钥不会离开这台电脑）。"
    const pick = document.createElement("button")
    pick.type = "button"
    pick.className = "qc-button qc-button-primary"
    pick.textContent = "重新登录：选择本地私钥"
    pick.addEventListener("click", () => {
      const input = document.createElement("input")
      input.type = "file"
      input.onchange = () => {
        const file = input.files?.[0]
        if (!file) return
        keyFile = (file as File & { path?: string }).path ?? file.name
        stage = "scanning"
        render()
        void props.sshScan({ keyFile, username: username || undefined }).then(result => {
          scanResult = result
          username = result.username
          askUsername = false
          stage = "groups"
          render()
        }).catch(error => {
          const message = error instanceof Error ? error.message : String(error)
          if (message.includes("无法从私钥文件名解析")) {
            stage = "pick"
            askUsername = true
            render()
            return
          }
          scanError = message
          stage = "pick"
          render()
        })
      }
      input.click()
    })
    const fileRow = document.createElement("label")
    fileRow.className = "qc-field-label"
    fileRow.textContent = "SSH 用户名（私钥文件名不代表登录用户名时，在这里填写并重试）"
    const userField = document.createElement("input")
    userField.type = "text"
    userField.className = "qc-select-wide"
    userField.value = username
    userField.placeholder = "你的 Linux 用户名"
    userField.addEventListener("input", () => { username = userField.value.trim() })
    const retry = document.createElement("button")
    retry.type = "button"
    retry.className = "qc-button qc-button-secondary"
    retry.textContent = username ? `用用户名 ${username} 重新探测` : "重新探测"
    retry.disabled = !username
    retry.addEventListener("click", () => {
      if (!username) return
      scanError = ""
      stage = "scanning"
      render()
      void props.sshScan({ keyFile, username }).then(result => {
        scanResult = result
        askUsername = false
        stage = "groups"
        render()
      }).catch(error => {
        scanError = error instanceof Error ? error.message : String(error)
        stage = "pick"
        render()
      })
    })
    root.replaceChildren(title, pick, fileRow, userField, retry)
    if (scanError) {
      const err = document.createElement("p")
      err.setAttribute("role", "alert")
      err.className = "qc-status qc-status-error"
      err.textContent = scanError
      root.append(err)
    }
  }

  const renderScanning = () => {
    const pill = document.createElement("span")
    pill.className = "qc-connection-pill"
    const dot = document.createElement("i")
    dot.className = "qc-ssh-spinner"
    dot.style.animation = "pulse-opacity 1.2s ease-in-out infinite"
    pill.append(dot, document.createTextNode("正在探测组织服务器（Server A / B / C）…"))
    root.replaceChildren(pill)
  }

  const renderGroups = () => {
    const result = scanResult
    if (!result) {
      stage = "pick"
      render()
      return
    }
    const title = document.createElement("p")
    title.className = "qc-ssh-hint"
    title.textContent = `登录成功（用户名 ${result.username}）。选择要进入的工作组：`
    root.replaceChildren(title)
    for (const server of result.servers) {
      for (const group of server.groups) {
        const row = document.createElement("button")
        row.type = "button"
        row.className = "qc-button qc-button-secondary qc-ssh-group-option"
        row.style.cssText = "display:flex;justify-content:space-between;width:100%;margin-bottom:6px;"
        const name = document.createElement("span")
        name.textContent = group
        const srv = document.createElement("span")
        srv.textContent = server.label
        row.append(name, srv)
        row.addEventListener("click", () => {
          if (enterBusy) return
          enterBusy = true
          row.disabled = true
          stage = "scanning"
          render()
          void props.sshProbe({ keyFile, username: result.username }).then(probe => {
            if (!probe.ok) {
              scanError = probe.reason
              stage = "groups"
              enterBusy = false
              render()
              return
            }
            props.onEnter({ group, serverId: server.id, serverLabel: server.label, username: result.username })
          })
        })
        root.append(row)
      }
    }
    for (const item of result.failed) {
      const note = document.createElement("p")
      note.className = "qc-ssh-hint"
      note.textContent = item.reason === "unreachable"
        ? "一台组织服务器暂时无法连接，已跳过。"
        : "有一台服务器未登记这把密钥，已跳过。"
      root.append(note)
      break
    }
    const back = document.createElement("button")
    back.type = "button"
    back.className = "qc-button qc-button-secondary"
    back.textContent = "换一把私钥"
    back.addEventListener("click", () => {
      stage = "pick"
      scanError = ""
      render()
    })
    root.append(back)
  }

  const render = () => {
    if (stage === "pick") renderPick()
    else if (stage === "scanning") renderScanning()
    else renderGroups()
  }

  render()
  return root
}

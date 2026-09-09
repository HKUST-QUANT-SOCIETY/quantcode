import { createEffect, getOwner } from "solid-js"
/**
 * F-09 / P-08 Admin 中枢：语义查询台 + 错误沉淀视图（仅 admin 角色可见导航，panels 负责门禁）。
 *
 * 数据通道（AG-G 实测结论，沿 capability-catalog 模式）：
 * - ① execution_trace 里 admin_list_runs / admin_errors 的 tool_result 事件（agent 调用后回流）；
 * - ③ 点击触发：语义查询经会话发送指令（buildAdminQueryInstruction），指示 agent 调
 *   admin_* 元工具，结果回流 trace 后在此渲染——无同步 tool.invoke，不伪造数据。
 * 纯 DOM 构建（沿 memory-query 模式，bun test 兼容）。
 */
import { viewIcon } from "./workspace-ui"
import "./admin-workspace.css"
import type { TraceEvent } from "./result-contract"

// ---------------------------------------------------------------------------
// 共享小工具（gitgraph-panel / notifications 复用，避免三处各抄一份）
// ---------------------------------------------------------------------------

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/** tool_result 载荷：字符串 JSON / 直接对象 → 记录（裸数组也接受）；截断或非 JSON → undefined（不造假数据）。 */
export function parseAdminToolResultJson(raw: unknown): Record<string, unknown> | unknown[] | undefined {
  if (typeof raw === "string") {
    try {
      const parsed: unknown = JSON.parse(raw)
      if (isRecord(parsed) || Array.isArray(parsed)) return parsed
      return undefined
    } catch {
      return undefined
    }
  }
  return isRecord(raw) || Array.isArray(raw) ? raw : undefined
}

/** 收集某 admin 元工具在 trace 中回流的全部结果载荷（按 trace 顺序，数组或对象）。 */
export function adminToolResultEvents(events: TraceEvent[] | undefined, tool: string): unknown[] {
  const payloads: unknown[] = []
  for (const event of events ?? []) {
    if (event.type !== "tool_result") continue
    const name = event.data?.tool ?? event.data?.tool_name
    if (name !== tool) continue
    const parsed = parseAdminToolResultJson(event.data?.result)
    payloads.push(parsed ?? { status: "UNAVAILABLE", error: "Malformed or truncated tool response" })
  }
  return payloads
}

/** Preserve service failures and provenance instead of rendering them as empty success. */
export function adminToolStatusView(events: TraceEvent[] | undefined, tools: string[]): HTMLElement {
  const root = document.createElement("div")
  root.className = "qc-service-status"
  root.setAttribute("role", "status")
  for (const tool of tools) {
    const payload = adminToolResultEvents(events, tool).at(-1)
    if (!isRecord(payload)) continue
    const status = payload.sync_status ?? payload.status
    const errors = [payload.error, ...(Array.isArray(payload.errors) ? payload.errors : [])]
      .filter((value): value is string => typeof value === "string" && !!value)
    const meta = [status, payload.visibility_source, payload.observed_at]
      .filter((value): value is string => typeof value === "string" && !!value)
    if (!meta.length && !errors.length && payload.ok !== false) continue
    const row = document.createElement("p")
    row.className = errors.length || payload.ok === false ? "qc-status-error" : "qc-muted"
    row.textContent = [tool, ...meta, ...errors].join(" · ")
    root.append(row)
  }
  return root
}

/** 载荷 → 记录列表：裸数组 / {runs|repos|errors|updates|packages:[…]} 二者皆收，防御截断与畸形项。 */
export function listFromPayload(payload: unknown, keys: string[]): Record<string, unknown>[] {
  if (Array.isArray(payload)) return payload.filter(isRecord)
  if (!isRecord(payload)) return []
  for (const key of keys) {
    if (Array.isArray(payload[key])) return (payload[key] as unknown[]).filter(isRecord)
  }
  return []
}

/** epoch 秒 / 毫秒 / ISO 字符串 → 毫秒；非法值 → undefined。 */
export function toEpochMs(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value < 10_000_000_000 ? value * 1000 : value
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

/** 相对时间（中文排版）：刚刚 / N 分钟前 / N 小时前 / N 天前 / M月D日。 */
export function relativeTimeLabel(timestampMs: number | undefined, now = Date.now()): string {
  if (timestampMs === undefined) return "—"
  const diff = now - timestampMs
  if (diff < 60_000) return "刚刚"
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  const date = new Date(timestampMs)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

// ---------------------------------------------------------------------------
// admin_list_runs：组 → 人 → 状态
// ---------------------------------------------------------------------------

export type AdminRunRecord = {
  thread_id?: string
  group?: string
  user?: string
  status?: string
  task?: string
  timestamp?: number
}

function pickString(source: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === "string" && value.trim()) return value
  }
  return undefined
}

/** admin_list_runs 载荷 → 运行记录（{runs:[…]} 或裸数组；字段取别名防御）。 */
export function runsFromPayload(payload: unknown): AdminRunRecord[] {
  const list = listFromPayload(payload, ["runs"])
  const records: AdminRunRecord[] = []
  for (const item of list) {
    if (!isRecord(item)) continue
    records.push({
      thread_id: pickString(item, ["thread_id", "threadId"]),
      group: pickString(item, ["group", "group_name", "owner_group"]),
      user: pickString(item, ["actor_id", "user", "owner", "identity", "member"]),
      status: pickString(item, ["status", "state"]),
      task: pickString(item, ["task", "title"]),
      timestamp: toEpochMs(item.ts ?? item.timestamp ?? item.pushed_at ?? item.updated_at),
    })
  }
  return records
}

export function runsFromTrace(events: TraceEvent[] | undefined): AdminRunRecord[] {
  return runsFromPayload(adminToolResultEvents(events, "admin_list_runs").at(-1))
    .sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0))
}

export type AdminGroupSummary = {
  group: string
  users: { user: string; runs: AdminRunRecord[] }[]
  total: number
  completed: number
  failed: number
}

const FAILED_STATUSES = new Set(["error", "failed", "rejected"])

/** 组 → 人 → 状态 聚合（纯函数）。user 缺省归 "—"；组缺省归 "未分组"。 */
export function groupRuns(runs: AdminRunRecord[]): AdminGroupSummary[] {
  const byGroup = new Map<string, Map<string, AdminRunRecord[]>>()
  for (const run of runs) {
    const group = run.group ?? "未分组"
    const user = run.user ?? "—"
    const users = byGroup.get(group) ?? new Map<string, AdminRunRecord[]>()
    const list = users.get(user) ?? []
    list.push(run)
    users.set(user, list)
    byGroup.set(group, users)
  }
  return [...byGroup.entries()].map(([group, users]) => {
    const all = [...users.values()].flat()
    return {
      group,
      users: [...users.entries()].map(([user, userRuns]) => ({ user, runs: userRuns })),
      total: all.length,
      completed: all.filter((run) => run.status === "completed").length,
      failed: all.filter((run) => FAILED_STATUSES.has(run.status ?? "")).length,
    }
  })
}

// ---------------------------------------------------------------------------
// admin_errors：错误沉淀（时间线 + 按组过滤 + 类型标签）
// ---------------------------------------------------------------------------

export type AdminErrorRecord = {
  thread_id?: string
  group?: string
  user?: string
  type?: string
  message?: string
  timestamp?: number
}

export function errorsFromPayload(payload: unknown): AdminErrorRecord[] {
  const list = listFromPayload(payload, ["errors"])
  const records: AdminErrorRecord[] = []
  for (const item of list) {
    if (!isRecord(item)) continue
    records.push({
      thread_id: pickString(item, ["thread_id", "threadId", "run_id"]),
      group: pickString(item, ["group", "group_name", "owner_group"]),
      user: pickString(item, ["actor_id", "user", "owner", "identity", "member"]),
      type: pickString(item, ["type", "kind", "error_type", "category"]),
      message: pickString(item, ["message", "error", "detail", "summary"]),
      timestamp: toEpochMs(item.ts ?? item.timestamp ?? item.time ?? item.created_at),
    })
  }
  return records
}

export function errorsFromTrace(events: TraceEvent[] | undefined): AdminErrorRecord[] {
  return errorsFromPayload(adminToolResultEvents(events, "admin_errors").at(-1))
    .sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0))
}

// ---------------------------------------------------------------------------
// 通道③指令：经会话发送，指示 agent 调 admin_list_runs / admin_errors
// ---------------------------------------------------------------------------

export function buildAdminQueryInstruction(query: string) {
  return (
    "You MUST call the admin_list_runs and admin_errors MCP tools NOW. Do NOT chat. Do NOT acknowledge. " +
    `Admin query (natural language): ${JSON.stringify(query)}. ` +
    "Return the raw tool results so the admin console can aggregate them. Do not start a new research task."
  )
}

// ---------------------------------------------------------------------------
// 视图
// ---------------------------------------------------------------------------

export type AdminConsoleProps = {
  /** i18n：panels 传 language.t（key 见 quantcode.admin.* 与 quantcode.gitgraph.open） */
  t: (key: string) => string
  /** 当前 run（读取 admin_* 的 tool_result 事件） */
  run?: { execution_trace?: TraceEvent[] } | null
  /** 通道③：经会话发送语义查询指令 */
  sendInstruction?: (content: string) => void
  /** GitGraph 面板入口按钮（panels 接视图切换） */
  onOpenGitgraph?: () => void
  onOpenDeployments?: () => void
  onOpenHistory?: (mode: "tasks" | "reports") => void
}

/** run 状态 → chip 类（与 panels.statusLabel 同源口径，ponytail: 等 admin 面板与 history 共源后抽公共 util） */
export function adminStatusChipClass(status: string | undefined): string {
  if (status === "completed") return "qc-status-completed"
  if (status === "waiting_for_human") return "qc-status-waiting_for_human"
  if (status === "error" || status === "failed" || status === "rejected") return "qc-status-error"
  return ""
}

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  waiting_for_human: "待审批",
  error: "异常",
  failed: "异常",
  rejected: "已拒绝",
}

export function adminStatusLabel(status: string | undefined): string {
  return STATUS_LABELS[status ?? ""] ?? "运行中"
}

const PRESETS = ["quantcode.admin.presetRuns", "quantcode.admin.presetModules", "quantcode.admin.presetErrors"] as const

export function AdminConsoleView(props: AdminConsoleProps): HTMLElement {
  const t = props.t
  const root = document.createElement("div")
  root.className = "qc-admin-console"

  const sectionLabel = (text: string) => {
    const span = document.createElement("span")
    span.className = "qc-section-label"
    span.textContent = text
    return span
  }
  const chip = (text: string, cls?: string) => {
    const span = document.createElement("span")
    span.className = cls ? `qc-status ${cls}` : "qc-status"
    span.textContent = text
    return span
  }

  let query = ""
  let sent = false
  let groupFilter = "all"

  const intro = document.createElement("div")
  intro.className = "qc-memory-intro"
  const title = document.createElement("h3")
  title.textContent = t("quantcode.admin.title")
  const desc = document.createElement("p")
  desc.textContent = t("quantcode.admin.intro")
  intro.append(sectionLabel("ADMIN CONSOLE"), title, desc)
  root.append(intro)

  const runs = (): AdminRunRecord[] => runsFromTrace(props.run?.execution_trace)
  const errors = (): AdminErrorRecord[] => errorsFromTrace(props.run?.execution_trace)

  const renderEntryRow = () => {
    const row = document.createElement("div")
    row.className = "qc-admin-entries"
    const entries = [
      { label: t("quantcode.gitgraph.open"), description: "浏览项目分支、提交与代码变更", icon: "branch" as const, action: props.onOpenGitgraph, cls: "qc-admin-open-gitgraph" },
      { label: "报告与产物", description: "查看组织研究报告与任务产物", icon: "open-file" as const, action: props.onOpenHistory ? () => props.onOpenHistory?.("reports") : undefined },
      { label: "任务管理", description: "查看任务状态、历史与执行记录", icon: "checklist" as const, action: props.onOpenHistory ? () => props.onOpenHistory?.("tasks") : undefined },
      { label: "部署管理", description: "暂存产物、核对版本与部署记录", icon: "server" as const, action: props.onOpenDeployments },
    ]
    for (const entry of entries) {
      const button = document.createElement("button")
      button.type = "button"
      button.className = `qc-admin-entry ${entry.cls ?? ""}`
      button.setAttribute("aria-label", entry.label)
      const title = document.createElement("strong")
      title.textContent = entry.label
      const description = document.createElement("small")
      description.textContent = entry.description
      button.append(viewIcon(entry.icon), title, description, viewIcon("arrow-right"))
      button.disabled = !entry.action
      button.addEventListener("click", () => entry.action?.())
      row.append(button)
    }
    return row
  }

  const renderComposer = () => {
    const wrap = document.createElement("div")
    wrap.className = "qc-admin-query"

    const presets = document.createElement("div")
    presets.className = "qc-admin-presets"
    for (const key of PRESETS) {
      const preset = document.createElement("button")
      preset.type = "button"
      preset.className = "qc-admin-preset"
      preset.textContent = t(key)
      preset.addEventListener("click", () => {
        query = t(key)
        render()
        root.querySelector<HTMLInputElement>(".qc-admin-query-input")?.focus()
      })
      presets.append(preset)
    }
    wrap.append(presets)

    const formRow = document.createElement("div")
    formRow.className = "qc-admin-form-row"
    const sendButton = document.createElement("button")
    sendButton.type = "button"
    sendButton.className = "qc-button qc-button-primary qc-admin-send"
    sendButton.disabled = !query.trim() || typeof props.sendInstruction !== "function"
    sendButton.textContent = t("quantcode.admin.send")
    sendButton.addEventListener("click", () => {
      if (query.trim()) send()
    })
    const input = document.createElement("input")
    input.className = "qc-select-wide qc-admin-query-input"
    input.type = "text"
    input.value = query
    input.setAttribute("aria-label", "查询组织运行情况")
    input.placeholder = t("quantcode.admin.inputPlaceholder")
    input.autocomplete = "off"
    input.style.height = "38px"
    input.addEventListener("input", () => {
      query = input.value
      sendButton.disabled = !query.trim()
    })
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && query.trim()) {
        send()
      }
    })
    formRow.append(input, sendButton)
    wrap.append(formRow)
    return wrap
  }

  const send = () => {
    if (!query.trim() || typeof props.sendInstruction !== "function") return
    props.sendInstruction(buildAdminQueryInstruction(query.trim()))
    sent = true
    render()
  }

  const renderSentNote = () => {
    if (!sent) return null
    const note = document.createElement("p")
    note.className = "qc-admin-sent-note"
    note.setAttribute("aria-live", "polite")
    note.textContent = t("quantcode.admin.sent")
    return note
  }

  /** 组 → 人 → 状态 卡片（spec：每组一行摘要 + 展开明细） */
  const renderRuns = () => {
    const wrap = document.createElement("div")
    wrap.className = "qc-admin-runs"
    wrap.append(sectionLabel("分组运行记录"))

    const grouped = groupRuns(runs())
    if (grouped.length === 0) {
      const hint = document.createElement("p")
      hint.textContent = sent ? t("quantcode.admin.waiting") : t("quantcode.admin.empty")
      wrap.append(hint)
      return wrap
    }
    for (const summary of grouped) {
      const details = document.createElement("details")
      details.className = "qc-admin-group"
      if (grouped.length === 1) details.open = true

      const line = document.createElement("summary")
      const name = document.createElement("strong")
      name.textContent = summary.group
      line.append(name, chip(`${summary.total} 条任务`))
      line.append(chip(`${adminStatusLabel("completed")} ${summary.completed}`, "qc-status-completed"))
      if (summary.failed > 0) line.append(chip(`${adminStatusLabel("error")} ${summary.failed}`, "qc-status-error"))
      details.append(line)

      for (const entry of summary.users) {
        for (const latest of entry.runs) {
        const row = document.createElement("div")
        row.className = "qc-admin-user-row"
        const who = document.createElement("div")
        const userName = document.createElement("strong")
        userName.textContent = entry.user
        const task = document.createElement("small")
        task.textContent = latest?.task ?? latest?.thread_id?.slice(0, 8) ?? ""
        task.title = task.textContent
        who.append(userName, task)
        row.append(who, chip(adminStatusLabel(latest?.status), adminStatusChipClass(latest?.status)))
        const time = document.createElement("span")
        time.textContent = relativeTimeLabel(latest?.timestamp)
        row.append(time)
        details.append(row)
        }
      }
      wrap.append(details)
    }
    return wrap
  }

  /** 错误沉淀：时间线 + 按组过滤 + 类型标签 */
  const renderErrors = () => {
    const wrap = document.createElement("div")
    wrap.className = "qc-admin-errors"
    wrap.append(sectionLabel("异常记录"))

    const records = errors()
    if (records.length === 0) {
      const hint = document.createElement("p")
      const latest = adminToolResultEvents(props.run?.execution_trace, "admin_errors").at(-1)
      const verifiedEmpty = isRecord(latest) && !latest.error && latest.ok !== false && Array.isArray(latest.errors)
      hint.textContent = verifiedEmpty ? t("quantcode.admin.errorsEmpty") : t("quantcode.admin.empty")
      wrap.append(hint)
      return wrap
    }

    const groups = [...new Set(records.map((record) => record.group).filter((group): group is string => !!group))]
    const filters = document.createElement("div")
    filters.className = "qc-admin-filters"
    for (const key of ["all", ...groups]) {
      const selected = groupFilter === key
      const button = document.createElement("button")
      button.type = "button"
      button.className = "qc-admin-filter"
      button.textContent = key === "all" ? t("quantcode.admin.filterAll") : key
      button.setAttribute("aria-pressed", String(selected))
      button.addEventListener("click", () => {
        groupFilter = key
        render()
      })
      filters.append(button)
    }
    wrap.append(filters)

    const timeline = document.createElement("div")
    timeline.className = "qc-admin-error-timeline"
    const visible = records.filter((record) => groupFilter === "all" || record.group === groupFilter)
    visible.forEach((record, index) => {
      const row = document.createElement("div")
      row.className = "qc-admin-error-row"
      const indexSpan = document.createElement("span")
      indexSpan.textContent = String(index + 1).padStart(2, "0")
      row.append(indexSpan)

      const body = document.createElement("div")
      const head = document.createElement("div")
      if (record.type) head.append(chip(record.type, "qc-status-error"))
      if (record.group) head.append(chip(record.group))
      const message = document.createElement("p")
      message.textContent = record.message ?? record.thread_id ?? "—"
      const meta = document.createElement("small")
      const parts = [record.user, record.group, record.thread_id?.slice(0, 8), relativeTimeLabel(record.timestamp)].filter(Boolean)
      meta.textContent = parts.join(" · ")
      body.append(head, message, meta)
      row.append(body)
      timeline.append(row)
    })
    wrap.append(timeline)
    return wrap
  }

  const render = () => {
    root.replaceChildren()
    root.append(intro, renderEntryRow(), renderComposer(), adminToolStatusView(props.run?.execution_trace, ["admin_list_runs", "admin_errors"]))
    const note = renderSentNote()
    if (note) root.append(note)
    const hasData = runs().length > 0 || errors().length > 0
    if (!hasData && !sent) {
      const empty = document.createElement("div")
      empty.className = "qc-empty-state qc-admin-empty"
      const index = document.createElement("span")
      index.className = "qc-empty-index"
      index.append(viewIcon("checklist"))
      const title = document.createElement("h3")
      title.textContent = t("quantcode.admin.emptyTitle")
      const desc = document.createElement("p")
      desc.textContent = t("quantcode.admin.empty")
      empty.append(index, title, desc)
      root.append(empty)
      return
    }
    const columns = document.createElement("div")
    columns.className = "qc-admin-results"
    columns.append(renderRuns(), renderErrors())
    root.append(columns)
  }

  if (getOwner()) createEffect(() => { props.run?.execution_trace; render() })
  else render()
  return root
}

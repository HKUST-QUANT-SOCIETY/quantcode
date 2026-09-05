/**
 * 会话内通知中心 v1：铃铛 + 三类通知（待审批 gate / repo 新提交 pop / 依赖版本更新 pop）。
 * 与 metric-cards 相同的 bun test 兼容策略：纯 DOM 构建、无 Solid 响应式、无 JSX；
 * 数据源由 panels.tsx 在响应式 JSX 子表达式中传入（_threadHistory / _trace 既有 signal）。
 * pop 数据来自通道①③：trace 里 admin_repo_status / admin_package_updates 的 tool_result。
 */
import type { RunAgentResult } from "./result-contract"
import { adminToolResultEvents, isRecord, listFromPayload, relativeTimeLabel, toEpochMs } from "./admin-console"
import { isRecentlyPushed } from "./gitgraph-panel"

export type QcNotificationKind = "gate" | "repo" | "package"

export type QcNotification = {
  kind: QcNotificationKind
  /** gate = run 线程；repo/package = 合成 id（repo:<名> / package:<名>），仅用于键合 */
  thread_id: string
  /** gate = 任务摘要；repo/package = 来源 repo / 库名 */
  task: string
  time: string
  status: string
  /** repo = 提交摘要；package = current → latest */
  detail?: string
}

const ACTIONABLE_GATE_KINDS = new Set(["merge", "permission"])

function isActionableGate(run: RunAgentResult) {
  return ACTIONABLE_GATE_KINDS.has(run.gate?.kind ?? "")
}

const BELL_PATH =
  '<path d="M10 3.1a4.9 4.9 0 0 0-4.9 4.9v2.9L3.5 13.9h13l-1.6-3V8A4.9 4.9 0 0 0 10 3.1Z" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linejoin="round"/>' +
  '<path d="M8.3 16.2a1.8 1.8 0 0 0 3.4 0" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linecap="round"/>'

// ponytail: 与 panels.tsx 的 taskFromRun/formatTime 小段重复；等通知与 history 面板共源后再抽公共 util
function taskLabel(run: RunAgentResult) {
  const event = run.execution_trace?.find((item) => item.type === "agent_start")
  const task = event?.data?.task
  return typeof task === "string" && task.trim() ? task : `研究任务 ${run.thread_id?.slice(0, 8) ?? "untitled"}`
}

function relativeTime(timestamp?: number) {
  if (!timestamp) return "刚刚"
  const date = new Date(timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" })
}

/** 未读集合 = 历史中 waiting_for_human（排除当前 trace 线程）+ 当前 trace 的 gate 等待。 */
export function pendingNotifications(history: RunAgentResult[], trace: RunAgentResult | null): QcNotification[] {
  const current = trace?.thread_id
  const pending = history.filter(
    (run) => run.status === "waiting_for_human" && isActionableGate(run) && run.thread_id && run.thread_id !== current,
  )
  if (trace?.status === "waiting_for_human" && isActionableGate(trace) && trace.thread_id) pending.push(trace)
  return pending.map((run) => ({
    kind: "gate" as const,
    thread_id: run.thread_id!,
    task: taskLabel(run),
    time: relativeTime(run.timestamp),
    status: "待审批",
  }))
}

// ---------------------------------------------------------------------------
// 双类 pop（F-09）：repo 新提交 + 依赖版本更新（全组可见，"不可能一直盯着 repo"）
// ---------------------------------------------------------------------------

const POP_DEFAULTS: Record<string, string> = {
  "quantcode.pop.repoTitle": "仓库有新提交",
  "quantcode.pop.packageTitle": "依赖有新版本",
  "quantcode.pop.viewGitgraph": "查看 GitGraph",
}

/** trace 事件里 admin_repo_status / admin_package_updates 的原始结果收集（与 admin-console 同解析口径）。 */
function popPayloads(runs: RunAgentResult[], tool: string): unknown[] {
  const payloads: unknown[] = []
  for (const run of runs) {
    // 只取每个 run 中该工具最后一次回流，避免历史 run 重复累积
    const payloadsOfRun = adminToolResultEvents(run.execution_trace, tool)
    if (payloadsOfRun.length) payloads.push(payloadsOfRun[payloadsOfRun.length - 1])
  }
  return payloads
}

/**
 * 双类 pop 数据（纯函数，测试友好）：repo 有新提交（pushed_at ≤ 7 天阈值）+ 依赖版本更新。
 * 同源去重（kind+id 取最新）；数据缺失时诚实返回空数组，不造假提醒。
 */
export function updateNotifications(
  runs: RunAgentResult[],
  opts: { now?: number; t?: (key: string) => string; thresholdMs?: number } = {},
): QcNotification[] {
  const now = opts.now ?? Date.now()
  const t = (key: string) => opts.t?.(key) ?? POP_DEFAULTS[key] ?? key
  const items = new Map<string, QcNotification>()

  for (const payload of popPayloads(runs, "admin_repo_status")) {
    for (const item of listFromPayload(payload, ["repos"])) {
      if (!isRecord(item)) continue
      const name = typeof item.name === "string" ? item.name : typeof item.repo === "string" ? item.repo : ""
      if (!name) continue
      const pushedAt = toEpochMs(item.pushed_at ?? item.last_push ?? item.updated_at)
      if (!isRecentlyPushed(pushedAt, now, opts.thresholdMs)) continue
      const commit =
        [item.last_commit_message, item.commit_message, item.commit].find(
          (value): value is string => typeof value === "string" && value.trim().length > 0,
        ) ?? ""
      items.set(`repo:${name}`, {
        kind: "repo",
        thread_id: `repo:${name}`,
        task: name,
        detail: commit,
        time: relativeTimeLabel(pushedAt, now),
        status: t("quantcode.pop.repoTitle"),
      })
    }
  }

  for (const payload of popPayloads(runs, "admin_package_updates")) {
    const payloadTime = isRecord(payload) ? toEpochMs(payload.timestamp ?? payload.checked_at) : undefined
    for (const item of listFromPayload(payload, ["updates", "packages"])) {
      if (!isRecord(item)) continue
      const name =
        [item.name, item.package, item.package_name, item.dependency].find(
          (value): value is string => typeof value === "string" && value.trim().length > 0,
        ) ?? ""
      if (!name) continue
      const current = typeof item.current === "string" ? item.current : ""
      const latest = typeof item.latest === "string" ? item.latest : ""
      items.set(`package:${name}`, {
        kind: "package",
        thread_id: `package:${name}`,
        task: name,
        detail: current || latest ? `${current || "?"} → ${latest || "?"}` : undefined,
        time: relativeTimeLabel(payloadTime, now),
        status: t("quantcode.pop.packageTitle"),
      })
    }
  }

  return [...items.values()]
}

export function NotificationsBell(props: { count: number; onClick: () => void }): HTMLElement {
  const button = document.createElement("button")
  button.type = "button"
  button.className = "qc-rail-button"
  button.title = "研究通知"
  button.setAttribute("aria-haspopup", "dialog")
  button.setAttribute("aria-label", props.count > 0 ? `研究通知（${props.count} 条）` : "研究通知")
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
  svg.setAttribute("viewBox", "0 0 20 20")
  svg.setAttribute("width", "18")
  svg.setAttribute("height", "18")
  svg.setAttribute("aria-hidden", "true")
  svg.innerHTML = BELL_PATH
  button.append(svg)
  if (props.count > 0) {
    const badge = document.createElement("span")
    badge.className = "qc-rail-notif-badge"
    badge.textContent = String(props.count)
    button.append(badge)
  }
  button.addEventListener("click", props.onClick)
  return button
}

export function NotificationsPanel(props: {
  items: QcNotification[]
  onClose: () => void
  onApprove: (threadId: string) => void
  /** pop 卡片点击跳转 GitGraph（repo/package 类）；缺省时 pop 行不渲染跳转动作 */
  onOpenGitgraph?: () => void
  /** i18n（quantcode.pop.*）；缺省回落中文默认文案（与面板既有硬编码中文一致） */
  t?: (key: string) => string
}): HTMLElement {
  const t = (key: string) => props.t?.(key) ?? POP_DEFAULTS[key] ?? key
  const panel = document.createElement("div")
  panel.className = "qc-notif-panel"
  panel.setAttribute("role", "dialog")
  panel.setAttribute("aria-label", "研究通知中心")
  const head = document.createElement("div")
  head.className = "qc-notif-head"
  const label = document.createElement("span")
  label.className = "qc-section-label"
  label.textContent = props.items.length ? `通知 · ${props.items.length} 条` : "通知"
  const close = document.createElement("button")
  close.type = "button"
  close.className = "qc-text-button"
  close.setAttribute("aria-label", "关闭通知")
  close.textContent = "关闭"
  close.addEventListener("click", props.onClose)
  head.append(label, close)
  panel.append(head)
  if (!props.items.length) {
    const empty = document.createElement("p")
    empty.className = "qc-notif-empty"
    empty.textContent = "没有待处理的审批，研究推进正常。"
    panel.append(empty)
    return panel
  }
  const goLabel = (kind: QcNotificationKind) => (kind === "gate" ? "去审批" : t("quantcode.pop.viewGitgraph"))
  for (const item of props.items) {
    const row = document.createElement("button")
    row.type = "button"
    row.className = "qc-notif-item"
    row.setAttribute("data-notif-kind", item.kind)
    const task = document.createElement("strong")
    task.textContent = item.task
    const status = document.createElement("span")
    status.className = `qc-status ${item.kind === "gate" ? "qc-status-waiting_for_human" : "qc-status-error"}`
    status.textContent = item.status
    const meta = document.createElement("small")
    const detail = item.detail ? ` · ${item.detail}` : ""
    meta.textContent = `${item.thread_id.startsWith("repo:") || item.thread_id.startsWith("package:") ? item.task : item.thread_id.slice(0, 8)} · ${item.time}${detail}`
    const go = document.createElement("span")
    go.className = "qc-text-button"
    go.textContent = goLabel(item.kind)
    row.append(task, status, meta, go)
    row.addEventListener("click", () => {
      if (item.kind === "gate") props.onApprove(item.thread_id)
      else props.onOpenGitgraph?.()
    })
    panel.append(row)
  }
  return panel
}

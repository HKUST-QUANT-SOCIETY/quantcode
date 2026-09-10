/**
 * QuantCode research workspace.
 *
 * The module-level trace store is intentionally preserved so MCP tool results,
 * HumanGate resumes, and the full-screen workspace share one source of truth.
 * Trace payloads pushed by the legacy task renderer arrive through the
 * quantcode-trace-bridge and join the same store, keeping one source of truth.
 */
import {
  For,
  Match,
  Show,
  Switch,
  batch,
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
  lazy,
  type JSX,
} from "solid-js"
import { createStore } from "solid-js/store"
import { Icon, type IconProps } from "@opencode-ai/ui/icon"
import { useDialog } from "@opencode-ai/ui/context/dialog"
import { setQuantCodeTraceListener, type QuantCodeTracePayload } from "@opencode-ai/session-ui/message-part"
import { usePrompt } from "@/context/prompt"
import { useServer } from "@/context/server"
import { useServerSDK } from "@/context/server-sdk"
import { useSDK } from "@/context/sdk"
import { useLocal } from "@/context/local"
import { useTabs } from "@/context/tabs"
import { useLanguage } from "@/context/language"
import { usePlatform } from "@/context/platform"
import { useCommand } from "@/context/command"
import { useFilteredList } from "@opencode-ai/ui/hooks"
import { PromptPopover, type SlashCommand } from "@/components/prompt-input/slash-popover"
import { showToast } from "@/utils/toast"
import { QcBigNumber, QcProgress, formatMetricValue, type MetricTone } from "./metric-cards"
import { buildResearchInstruction, buildResumeInstruction, buildRecoveryInstruction, QUANTCODE_GROUPS, type QuantCodeGroup } from "./instructions"
import { isRunAgentResult, type RunAgentResult, type TraceEvent } from "./result-contract"
import { submitQuantCodeInstruction, type QuantCodeSubmissionHandler } from "./submission"
import { NotificationsBell, NotificationsPanel, pendingNotifications } from "./notifications"
import { AlgorithmCatalogView } from "./settings-supplier"
import { useSearchParams, useNavigate } from "@solidjs/router"
import { createSdkForServer } from "@/utils/server"
import type { QuantCodeDesktopIdentity, QuantCodeSshLoginResult, QuantCodeServerAdminSession } from "@/identity"
import { useSettingsCommand } from "../settings-dialog"

const SettingsProvidersV2 = lazy(() => import("../settings-v2/providers").then(m => ({ default: m.SettingsProvidersV2 })))
const DialogSelectServer = lazy(() => import("../dialog-select-server").then(m => ({ default: m.DialogSelectServer })))
const QuantCodePreferences = lazy(() => import("./settings-preferences").then(m => ({ default: m.QuantCodePreferences })))
const QuantCodeTaskReview = lazy(() => import("./task-review").then(m => ({ default: m.QuantCodeTaskReview })))
import { SshLoginView, SshOrgLoginWizard, type SshConnectFn, type SshIdentity, type SshSession, type SshDisconnectFn } from "./ssh-login"
import { CapabilityCatalogView } from "./capability-catalog"
import { ApprovalQueue } from "./approval-queue"
import { NativeApprovalQueue } from "./native-approval-queue"
import { DeploymentPanel } from "./deployment-panel"
import { KnowledgeReview } from "./knowledge-review"
import { RunHistoryView } from "./run-history"
import { NativeTaskHistory, type NativeTaskSource } from "./native-task-history"
import { MemoryQueryView } from "./memory-query"
import { SolutionPanelView } from "./solution-panel"
import { AdminConsoleView } from "./admin-console"
import { ServerAdminView } from "./server-admin"
import { GitHubWorkspace } from "./github-workspace"
import { WorkspaceEmpty, navigateViewTabs } from "./workspace-ui"
import {
  readQuantCodeTool,
  reconcileQuantCodeReceipt,
  updateQuantCodePop,
  reviewQuantCodeCandidate,
  listQuantCodeAlgorithms,
  listQuantCodeSkills,
  listQuantCodeCapabilities,
  searchQuantCodeMemory,
  getQuantCodeSessionContext,
  createLocalIdentityConnect,
  createLocalIdentityDisconnect,
  type QuantCodeSkill,
} from "./api"
import { METRIC_LABELS } from "./metrics"
import "./panels.css"
import "./workspace.css"

const [_trace, setTrace] = createSignal<RunAgentResult | null>(null)
const [_group, setGroup] = createSignal("")
const [_threadHistory, setThreadHistory] = createSignal<RunAgentResult[]>([])
/** Legacy task result's session; HumanGate recovery sends its prompt there. */
const [_sessionId, setSessionId] = createSignal<string | undefined>(undefined)

let activeThreadCacheKey: string | undefined

function scopedThreadCacheKey(context: { actor_id?: string; group: string; workspace_id?: string }, serverKey: string) {
  if (!context.actor_id) return
  const scope = [serverKey, context.actor_id, context.group, context.workspace_id ?? ""].join(":")
  return `quantcode:thread_cache:${encodeURIComponent(scope)}`
}

function loadScopedThreadCache(key: string) {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "null")
    const items = Array.isArray(parsed) ? parsed.filter(isRunAgentResult) : []
    if (items[0]) {
      setTrace(items[0])
      setThreadHistory(items)
    }
  } catch {
    // Local storage is unavailable in SSR and hardened browser contexts.
  }
}

function mergeTraceEvents(existing: TraceEvent[], incoming: TraceEvent[]) {
  const events = new Map<string, TraceEvent>()
  for (const event of [...existing, ...incoming]) {
    const key = event.event_id ?? JSON.stringify([event.thread_id, event.type, event.node, event.iteration, event.seq, event.data])
    events.set(key, event)
  }
  return [...events.values()]
}

function mergeGate(
  current: RunAgentResult["gate"],
  incoming: RunAgentResult["gate"],
  decision?: string,
  history?: { decision: string; timestamp: number }[],
) {
  const entries = [...(current?.review_history ?? [])]
  for (const entry of history ?? []) {
    if (!entries.some((item) => item.decision === entry.decision && item.timestamp === entry.timestamp)) {
      entries.push(entry)
    }
  }
  if (decision && decision !== "auto" && !entries.some((item) => item.decision === decision)) {
    entries.push({ decision, timestamp: Date.now() })
  }
  const base = incoming ?? current
  return entries.length ? { ...base, review_history: entries } : base
}

export function updateQuantCodeTrace(result: RunAgentResult) {
  const enriched = { ...result, timestamp: result.timestamp ?? Date.now() }

  setThreadHistory((current) => {
    const index = current.findIndex((item) => enriched.thread_id && item.thread_id === enriched.thread_id)
    if (index === -1) {
      setTrace(enriched)
      return [enriched, ...current].slice(0, 50)
    }

    const previous = current[index]
    const merged = {
      ...previous,
      ...enriched,
      execution_trace: mergeTraceEvents(previous.execution_trace ?? [], enriched.execution_trace ?? []),
      gate: mergeGate(previous.gate, enriched.gate, enriched.human_decision, enriched.human_review_history),
    }
    const next = [...current]
    next[index] = merged
    setTrace(merged)
    return next
  })

  queueMicrotask(() => {
    if (!activeThreadCacheKey) return
    try {
      localStorage.setItem(activeThreadCacheKey, JSON.stringify(_threadHistory().slice(0, 50)))
    } catch {
      // The workspace remains usable without persistence.
    }
  })
}

export function setQuantCodeSessionGroup(group: string) {
  if (!QUANTCODE_GROUPS.includes(group as QuantCodeGroup)) return
  setGroup(group)
}

// ---------------------------------------------------------------------------
// 桥接：接收归档任务渲染推送的 trace，处理跨会话重置（B19-03）
// ---------------------------------------------------------------------------

let lastSessionId: string | undefined
let lastResultJson: string | undefined

function resetQuantCodeState() {
  setTrace(null)
  setThreadHistory([])
}

function handleQuantCodeTracePayload(payload: QuantCodeTracePayload) {
  // 新会话信号：先清空上一会话的 trace/history，避免跨会话泄漏
  if (typeof payload.sessionId === "string" && payload.sessionId && payload.sessionId !== lastSessionId) {
    lastSessionId = payload.sessionId
    resetQuantCodeState()
  }
  // resume 指令需要的 sessionId：在去重 return 之前记录，保证 gate 面板随时可取
  if (typeof payload.sessionId === "string" && payload.sessionId) setSessionId(payload.sessionId)
  // 工具 part 重挂载会重复推送同一结果，去重避免 history 出现重复条目
  const json = JSON.stringify(payload.result)
  if (json === lastResultJson) return
  lastResultJson = json
  if (payload.result === null || typeof payload.result !== "object") return
  updateQuantCodeTrace(payload.result as RunAgentResult)
}

export function quantCodeGroup() {
  return _group() as QuantCodeGroup
}

type DetailView =
  | "compose"
  | "activity"
  | "gate"
  | "memory"
  | "capabilities"
  | "solution"
  | "settings"
  | "admin"
  | "server-admin"
  | "gitgraph"
type SubmitState = "idle" | "starting" | "submitted" | "error"
type GateDecision = "approve" | "reject"

function taskFromRun(run: RunAgentResult) {
  const event = run.execution_trace?.find((item) => item.type === "agent_start")
  const task = event?.data?.task
  return typeof task === "string" && task.trim() ? task : `研究任务 ${run.thread_id?.slice(0, 8) ?? "untitled"}`
}

function formatTime(timestamp?: number) {
  if (!timestamp) return "刚刚"
  const date = new Date(timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" })
}

function statusLabel(status: string) {
  if (status === "completed") return "已完成"
  if (status === "waiting_for_human") return "待审批"
  if (status === "error") return "异常"
  if (status === "rejected") return "已拒绝"
  if (status === "stopped_budget") return "预算停止"
  if (status === "stopped_loop") return "循环停止"
  if (status === "failed") return "失败"
  return "运行中"
}

function eventTitle(type: string) {
  const titles: Record<string, string> = {
    agent_start: "研究已启动",
    skill_loaded: "Skill 已载入",
    node_update: "节点状态更新",
    llm_thought: "Agent 推理",
    tool_call: "工具调用",
    tool_result: "工具返回",
    risk_metrics: "风险指标",
    human_gate: "HumanGate",
    output_data: "结构化结果",
    artifact: "研究产物",
    checkpoint_snapshot: "上下文快照",
    budget_warning: "预算告警",
    agent_end: "研究完成",
    error: "执行异常",
  }
  return titles[type] ?? type
}

function eventSummary(event: TraceEvent) {
  const data = event.data ?? {}
  if (event.type === "agent_start" && typeof data.task === "string") return data.task
  if (event.type === "tool_call") return displayValue(data.tool_name ?? data.tool, "QuantCode tool")
  if (event.type === "artifact") return displayValue(data.artifact_ref ?? data.path, "Artifact")
  if (event.type === "error") return displayValue(data.error, "Unknown error")
  if (event.node) return event.node
  return event.flow_name ?? "QuantCode"
}

function displayValue(value: unknown, fallback: string) {
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return `${value}`
  return fallback
}

function eventIcon(type: string): IconProps["name"] {
  if (type === "agent_start") return "plus"
  if (type === "llm_thought") return "brain"
  if (type === "tool_call" || type === "tool_result") return "mcp"
  if (type === "risk_metrics" || type === "human_gate") return "review"
  if (type === "artifact") return "file-tree"
  if (type === "error") return "warning"
  if (type === "agent_end") return "check-small"
  return "code-lines"
}

// ---------------------------------------------------------------------------
// 指标摘要：从 output_data 与 risk_metrics 中防御式提取数值指标
// ---------------------------------------------------------------------------

/** output_data 里的数值键 → 卡片数据（最多 4 个），数值型才渲染。 */
function bigNumbersFromOutput(output?: Record<string, unknown>) {
  if (!output) return []
  const items: { label: string; value: string; tone: MetricTone }[] = []
  for (const [key, raw] of Object.entries(output)) {
    if (typeof raw !== "number" || !Number.isFinite(raw)) continue
    const label = METRIC_LABELS[key] ?? key
    const lower = key.toLowerCase()
    const tone: MetricTone = /drawdown|var_|risk|vol/i.test(lower) ? (raw > 0 ? "negative" : "positive") : "ink"
    const value = formatMetricValue(key, raw)
    items.push({ label, value, tone })
    if (items.length >= 4) return items
  }
  return items
}

/** 执行记录里的风险指标（gate/trace），数值型才画阈值对比条。
 * 越界判定由 payload 驱动：后端 gate.reasons（breached_thresholds 权威）含该指标键 → is-breach；
 * 前端不硬编码阈值数字。 */
function riskProgressRows(run: RunAgentResult | null) {
  if (!run) return []
  const reasons = run.gate?.reasons ?? []
  const breached = new Set(
    reasons.filter((r): r is string => typeof r === "string" && r.length > 0),
  )
  const rows: { label: string; value: number; breached: boolean }[] = []
  for (const source of [run.risk_metrics, run.gate?.risk_metrics]) {
    if (!source) continue
    for (const [key, raw] of Object.entries(source)) {
      if (typeof raw !== "number" || !Number.isFinite(raw)) continue
      if (!/max_drawdown|tail_risk_var_99/i.test(key)) continue
      if (rows.some((row) => row.label === (METRIC_LABELS[key] ?? key))) continue
      rows.push({
        label: METRIC_LABELS[key] ?? key,
        value: raw,
        breached: breached.has(key),
      })
    }
  }
  return rows
}

function traceEventCount(run: RunAgentResult | null) {
  return run?.execution_trace?.length ?? 0
}

function ActivityPanel(props: { onUseTask: (task: string) => void }): JSX.Element {
  const run = createMemo(() => _trace())
  const events = createMemo(() => run()?.execution_trace ?? [])
  const riskRows = createMemo(() => riskProgressRows(run()))

  return (
    <div class="qc-detail-body">
      <Show
        when={run()}
        fallback={
          <WorkspaceEmpty icon="task" title="当前没有运行中的任务"><button type="button" class="qc-button qc-button-primary" onClick={() => props.onUseTask("")}><Icon name="plus" size="small" />新建研究</button></WorkspaceEmpty>
        }
      >
        {(item) => (
          <>
            <div class="qc-run-overview">
              <div>
                <span class={`qc-status qc-status-${item().status}`}>{statusLabel(item().status)}</span>
                <h3>{taskFromRun(item())}</h3>
              </div>
              <button type="button" class="qc-text-button" onClick={() => props.onUseTask(taskFromRun(item()))}>
                再次运行
                <Icon name="arrow-right" size="small" />
              </button>
            </div>
            <div class="qc-run-meta">
              <span>THREAD</span>
              <code>{item().thread_id ?? "pending"}</code>
              <span>{formatTime(item().timestamp)}</span>
            </div>
            <Show when={riskRows().length > 0}>
              <div class="qc-detail-section">
                <span class="qc-section-label">RISK THRESHOLD</span>
                <For each={riskRows()}>
                  {(row) =>
                    QcProgress({
                      label: row.breached ? `${row.label}（越界）` : row.label,
                      value: row.value,
                    })
                  }
                </For>
              </div>
            </Show>
            <div class="qc-timeline">
              <For each={events()}>
                {(event, index) => (
                  <div class="qc-event-row">
                    <span class="qc-event-index">{String(index() + 1).padStart(2, "0")}</span>
                    <span class="qc-event-icon">
                      <Icon name={eventIcon(event.type)} size="small" />
                    </span>
                    <div>
                      <strong>{eventTitle(event.type)}</strong>
                      <p>{eventSummary(event)}</p>
                    </div>
                    <span class="qc-event-iteration">I{event.iteration ?? 0}</span>
                  </div>
                )}
              </For>
            </div>
            <Show when={(item().artifacts?.length ?? 0) > 0}>
              <div class="qc-detail-section">
                <span class="qc-section-label">ARTIFACTS</span>
                <For each={item().artifacts}>{(artifact) => <code class="qc-artifact">{artifact}</code>}</For>
              </div>
            </Show>
          </>
        )}
      </Show>
    </div>
  )
}

function GatePanel(props: {
  onResume: (threadId: string, decision: "approve" | "reject") => void
  role: string
}): JSX.Element {
  const run = createMemo(() => _trace())
  const gate = createMemo(() => {
    const value = run()?.gate
    return value?.kind && value.kind in GATE_KIND_LABELS ? value : undefined
  })
  const waiting = createMemo(() => run()?.status === "waiting_for_human" && !!gate())

  return (
    <div class="qc-detail-body">
      <Show
        when={gate()}
        fallback={
          <div class="qc-empty-state">
            <span class="qc-empty-index">OK</span>
            <h3>当前没有待处理的 Gate</h3>
            <p>共享写入或跨组授权需要处理时，审批请求会固定在这里；风险和评估结果不会生成 Gate。</p>
          </div>
        }
      >
        {(item) => (
          <>
            <span class={`qc-status ${waiting() ? "qc-status-waiting_for_human" : "qc-status-completed"}`}>
              {waiting() ? "等待人工判断" : "审批已记录"}
            </span>
            {/* v5: only merge/permission gates can reach this panel. */}
            <Show when={item().kind}>
              <span class="qc-status qc-gate-kind">{GATE_KIND_LABELS[item().kind!] ?? item().kind}</span>
            </Show>
            <h3 class="qc-gate-title">{item().message ?? "HumanGate review"}</h3>
            <div class="qc-detail-section">
              <span class="qc-section-label">REASONS</span>
              <For each={item().reasons ?? []}>
                {(reason, index) => (
                  <div class="qc-reason-row">
                    <span>{String(index() + 1).padStart(2, "0")}</span>
                    <p>{reason}</p>
                  </div>
                )}
              </For>
            </div>
            <div class="qc-detail-section">
              <span class="qc-section-label">EVIDENCE</span>
              <For each={Object.entries(item().risk_metrics ?? {}).filter(([, raw]) => typeof raw === "number" && Number.isFinite(raw))}>
                {([key, raw]) => QcProgress({ label: METRIC_LABELS[key] ?? key, value: raw as number })}
              </For>
            </div>
            <Show when={waiting() && run()?.thread_id && (props.role === "approver" || props.role === "admin")}>
              <div class="qc-gate-actions">
                <button
                  type="button"
                  class="qc-button qc-button-primary"
                  onClick={() => props.onResume(run()!.thread_id!, "approve")}
                >
                  批准继续
                </button>
                <button
                  type="button"
                  class="qc-button qc-button-secondary"
                  onClick={() => props.onResume(run()!.thread_id!, "reject")}
                >
                  拒绝并停止
                </button>
              </div>
            </Show>
            <Show when={waiting() && props.role === "analyst"}>
              <div class="qc-gate-actions qc-gate-readonly">
                <p>由有权限的审批人处理（当前身份：{props.role}）</p>
                <p>可通过 PR 评论提出意见</p>
              </div>
            </Show>
          </>
        )}
      </Show>
    </div>
  )
}

/** v2 收窄后进 GatePanel 的四类写操作 kind → 徽章文案（U1-A6；未知 kind 原样显示）。 */
const GATE_KIND_LABELS: Record<string, string> = {
  merge: "主线入库",
  permission: "跨组权限",
}

function skillLabel(skill: QuantCodeSkill) {
  return skill.name?.trim() || skill.id
}

function SettingsPanel(props: {
  skill: string
  onSkillChange: (skill: string) => void
  skills: QuantCodeSkill[]
  skillsStatus: "loading" | "ready" | "error"
  sessionStatus: "loading" | "ready" | "error"
  sessionRole: string
  sessionActor: string
  workspacePath: string
  serverName: string
  serverReady: boolean
  serverTransport: string
  unifiedRuntime: boolean
  /** F-05 SSH 登录视图的 i18n（quantcode.ssh.*），来自 useLanguage().t */
  sshT: (key: string) => string
  sshConnect: SshConnectFn
  sshDisconnect: SshDisconnectFn
  sshSession?: SshSession
  sshIdentities: SshIdentity[]
  sshIdentityError: string
  servers: { key: string; name: string }[]
  selectedServer: string
  onServerChange: (key: string) => void
  githubSubject?: string
  onOpenGitgraph: () => void
  importKey?: () => Promise<{ fingerprint: string } | null>
  /** 组织 SSH 登录向导桥（desktop 提供）；未注入时回退到服务器驱动的 SshLoginView。 */
  orgSshLogin?: Pick<QuantCodeDesktopIdentity, "sshScan" | "sshConnect">
  orgSshOnEnter?: (result: QuantCodeSshLoginResult) => Promise<void>
  orgSshStart?: boolean
  orgSshOnStarted?: () => void
}): JSX.Element {
  const dialog = useDialog()
  const [tab, setTab] = createSignal("account")
  const tabs = [{ id: "account", label: "账号与连接" }, { id: "providers", label: "模型供应商" }, { id: "preferences", label: "桌面偏好" }]
  return (
    <>
    <div class="qc-view-tabs" role="tablist" aria-label="QuantCode 设置分类" onKeyDown={navigateViewTabs}>
      <For each={tabs}>{item => <button type="button" role="tab" aria-selected={tab() === item.id} tabIndex={tab() === item.id ? 0 : -1} onClick={() => setTab(item.id)}>{item.label}</button>}</For>
    </div>
    <Show when={tab() === "providers"}><div class="qc-settings-models"><SettingsProvidersV2 /></div></Show>
    <Show when={tab() === "preferences"}><QuantCodePreferences /></Show>
    <Show when={tab() === "account"}>
    <div class="qc-detail-body qc-settings-content">
      <section class="qc-account-section" aria-label="SSH 账号登录">
      <div class="qc-section-heading"><Icon name="shield" /><h3>账号与身份</h3></div>
      <div class="qc-setting-row">
        <div>
          <span class="qc-section-label">当前账号</span>
          <strong>{props.sessionStatus === "ready" ? props.sessionActor : "尚未登录"}</strong>
          <Show when={props.sessionStatus === "ready"}><span class="qc-status">{props.sessionRole === "admin" ? "管理员" : props.sessionRole === "approver" ? "审批人" : "研究员"}</span></Show>
        </div>
        <span class="qc-connection-pill" classList={{ "is-disconnected": props.sessionStatus !== "ready" }}>
          <i /> {props.sessionStatus === "ready" ? "会话已认证" : "未认证"}
        </span>
      </div>
      <div class="qc-setting-row">
        <div>
          <span class="qc-section-label">业务组</span>
          <strong>{props.sessionStatus === "ready" ? _group() : "尚未绑定"}</strong>
        </div>
        <span class="qc-status">{props.sessionStatus === "ready" ? "服务端绑定" : "等待登录"}</span>
      </div>
      <Show when={props.sessionStatus === "ready" && props.workspacePath}>
        <div class="qc-setting-row"><div><span class="qc-section-label">个人工作目录</span><code>{props.workspacePath}</code></div></div>
      </Show>
      <div class="qc-detail-section">
        <span class="qc-section-label">本机 SSH 身份</span>
        <Show when={props.sshIdentityError && !props.orgSshLogin}><p role="alert">{props.sshIdentityError}</p></Show>
        <Show when={props.orgSshLogin}>
          <SshOrgLoginWizard sshScan={input => props.orgSshLogin!.sshScan(input)}
            sshConnect={input => props.orgSshLogin!.sshConnect(input)}
            autoStart={props.orgSshStart} onStarted={props.orgSshOnStarted}
            onEnter={async result => { await props.orgSshOnEnter?.(result) }} />
        </Show>
        <Show when={props.sshSession || !props.orgSshLogin}>
          <Show keyed when={{ identities: props.sshIdentities, session: props.sshSession }}>
            {identity => <SshLoginView t={props.sshT} connect={props.sshConnect} disconnect={props.sshDisconnect}
              identities={identity.identities} session={identity.session} importKey={props.importKey} />}
          </Show>
        </Show>
      </div>
      </section>
      <section class="qc-preferences-section">
      <div class="qc-section-heading"><Icon name="settings-gear" /><h3>工作区配置</h3></div>
      <Show when={!props.orgSshLogin}>
      <div class="qc-server-line">
        <label class="qc-field-label" for="qc-settings-server">研究服务器</label>
        <button type="button" class="qc-button qc-button-secondary" onClick={() => dialog.show(() => <DialogSelectServer />)}>
          <Icon name="settings-gear" size="small" />管理服务器
        </button>
      </div>
      <select id="qc-settings-server" class="qc-select-wide" value={props.selectedServer} onChange={(event) => props.onServerChange(event.currentTarget.value)}>
        <For each={props.servers}>{item => <option value={item.key}>{item.name}</option>}</For>
      </select>
      <p class="qc-muted">切换服务器会清除当前身份并重新读取该服务器允许的 SSH 公钥。</p>
      </Show>
      <Show when={props.unifiedRuntime} fallback={<>
      <label class="qc-field-label" for="qc-settings-skill">
        默认 Skill
      </label>
      <select
        id="qc-settings-skill"
        class="qc-select-wide"
        value={props.skill}
        disabled={props.skillsStatus !== "ready"}
        onChange={(event) => props.onSkillChange(event.currentTarget.value)}
      >
        <Show when={props.skillsStatus === "loading"}>
          <option value="">正在加载 Skill 目录…</option>
        </Show>
        <Show when={props.skillsStatus === "error"}>
          <option value="">Skill 目录未连接</option>
        </Show>
        <For each={props.skills}>{(skill) => <option value={skill.id}>{skillLabel(skill)}</option>}</For>
      </select>
      </>}>
        <div class="qc-setting-row"><div><span class="qc-section-label">组 Skill</span><strong>按组织身份自动加载</strong><p class="qc-muted">开始任务时读取当前业务组的已安装 Skill；无法读取时会在任务中说明。</p></div></div>
      </Show>
      <div class="qc-detail-section">
        <span class="qc-section-label">研究服务</span>
        <div class="qc-server-line">
          <span>{props.serverName}</span>
          <code>{props.serverTransport}</code>
        </div>
      </div>
      <div class="qc-detail-section qc-connection-section">
        <div class="qc-section-heading"><Icon name="providers" /><h3>GitHub 连接</h3></div>
        <div class="qc-setting-row">
          <div><span class="qc-section-label">GitHub 身份</span><strong>{props.githubSubject || "尚未绑定"}</strong><p class="qc-muted">仓库可见范围由当前 GitHub 身份与业务组权限共同决定。</p></div>
          <button type="button" class="qc-button qc-button-secondary" onClick={props.onOpenGitgraph}>查看绑定状态</button>
        </div>
      </div>
      </section>
    </div>
    </Show>
    </>
  )
}

export type QuantCodePanelProps = {
  onClose?: () => void
  nativeSessionID?: string
  /**
   * Root-home entry point. Session panels keep the default prompt bridge;
   * the standalone home delegates submission to the draft/session router.
   */
  onSubmitInstruction?: QuantCodeSubmissionHandler
}

export function QuantCodePanel(props: QuantCodePanelProps = {}): JSX.Element {
  const prompt = props.onSubmitInstruction ? undefined : usePrompt()
  const directorySDK = props.onSubmitInstruction ? undefined : useSDK()
  const local = props.onSubmitInstruction ? undefined : useLocal()
  const server = useServer()
  const navigate = useNavigate()
  const serverSDK = useServerSDK()
  const language = useLanguage()
  const platform = usePlatform()
  const tabs = useTabs()
  const [searchParams] = useSearchParams()
  let disposed = false
  onCleanup(() => { disposed = true })
  useSettingsCommand()
  const [state, setState] = createStore({
    view: "compose" as DetailView,
    task: "",
    skill: "",
    skills: [] as QuantCodeSkill[],
    skillsStatus: "loading" as "loading" | "ready" | "error",
    sessionStatus: "loading" as "loading" | "ready" | "error",
    sessionRole: "未连接",
    sessionActor: "未连接",
    sessionId: "",
    githubSubject: "",
    workspacePath: "",
    catalogTab: "components",
    memoryTab: "knowledge" as "knowledge" | "review",
    activityTab: "history" as "history" | "current" | "legacy",
    historyScope: "",
    githubUnread: 0,
    identityRevision: 0,
    unifiedRuntime: false,
    runtimeStatus: "loading" as "loading" | "ready" | "error",
    sshIdentities: [] as SshIdentity[],
    sshSession: undefined as SshSession | undefined,
    sshIdentityError: "",
    orgSshStart: false,
    adminSession: undefined as QuantCodeServerAdminSession | undefined,
    adminHistory: "overview" as "overview" | "tasks" | "reports" | "deployments",
    submit: "idle" as SubmitState,
    error: "",
  })
  createEffect(() => { if (searchParams.settings) setState("view", "settings") })
  let taskInput: HTMLTextAreaElement | undefined
  let slashPopoverRef: HTMLDivElement | undefined
  let shell: HTMLDivElement | undefined
  let stage: HTMLElement | undefined
  let fieldCanvas: HTMLCanvasElement | undefined
  let focusLens: HTMLDivElement | undefined
  let sharpBrand: HTMLDivElement | undefined
  const [notifOpen, setNotifOpen] = createSignal(false)
  const command = useCommand()
  const [slashPopover, setSlashPopover] = createSignal<"slash" | null>(null)

// Reuse the existing command catalog and popover on the standalone QuantCode home.
  // Session-only commands stay registered by the session composer.
  command.register("quantcode-home", () => props.onSubmitInstruction && state.runtimeStatus === "ready" ? [
    { id: "quantcode.home.goal", title: language.t(state.unifiedRuntime ? "quantcode.native.goal.title" : "quantcode.goal.title"), description: language.t(state.unifiedRuntime ? "quantcode.native.goal.description" : "quantcode.goal.description"), slash: "goal", onSelect: () => {} },
    { id: "quantcode.home.compose", title: "研究任务（Compose）", description: language.t("quantcode.native.compose.description"), slash: "compose", onSelect: () => {} },
    { id: "quantcode.home.solution", title: language.t(state.unifiedRuntime ? "quantcode.native.solution.title" : "quantcode.cmd.solution.title"), description: language.t(state.unifiedRuntime ? "quantcode.native.solution.description" : "quantcode.cmd.solution.description"), slash: "solution", onSelect: () => {} },
    { id: "quantcode.home.compact", title: "Compact", description: "进入研究会话后压缩上下文", slash: "compact", onSelect: () => showToast({ title: "Compact 需要在研究会话中使用" }) },
  ] : [])

  const slashCommands = createMemo<SlashCommand[]>(() =>
    command.options
      .filter((opt) => !opt.disabled && opt.slash && opt.id.startsWith("quantcode.home."))
      .map((opt) => ({ id: opt.id, trigger: opt.slash!, title: opt.title, description: opt.description, type: "builtin" as const })),
  )
  const selectSlashCommand = (item: SlashCommand | undefined) => {
    if (!item) return
    setSlashPopover(null)
    if (item.trigger === "goal") setState("task", language.t(state.unifiedRuntime ? "quantcode.native.goal.template" : "quantcode.goal.template"))
    else if (item.trigger === "solution") setState("task", language.t(state.unifiedRuntime ? "quantcode.native.solution.template" : "quantcode.cmd.solution.template"))
    else if (item.trigger === "compact") {
      showToast({ title: "Compact 需要在研究会话中使用" })
      return
    } else setState("task", state.unifiedRuntime && item.trigger === "compose" ? "" : `/${item.trigger} `)
    requestAnimationFrame(() => taskInput?.focus())
  }
  const slashList = useFilteredList<SlashCommand>({
    items: slashCommands,
    key: (item) => item.id,
    filterKeys: ["trigger", "title"],
    onSelect: selectSlashCommand,
  })
  const notifItems = createMemo(() => pendingNotifications(_threadHistory(), _trace()))
  /** F-09: admin 中枢仅服务端签发的 admin 角色可见。 */
  const adminViewable = createMemo(() => state.sessionStatus === "ready" && state.sessionRole === "admin")
  const nativeTasks = createMemo<NativeTaskSource>(() => {
    const client = serverSDK().client
    return {
      artifacts: {
        list: async (task, cursor, signal) => {
          const response = await client.quantcode.artifacts.list({ sessionID: task.session_id, source_revision: String(task.source_revision), cursor }, { signal })
          if (response.error || !response.data) throw new Error("产物清单读取失败，请刷新任务版本。")
          return response.data
        },
        read: async (task, artifact, offset, signal) => {
          const response = await client.quantcode.artifacts.read({ sessionID: task.session_id, source_revision: String(task.source_revision), artifact_id: artifact.id, offset: String(offset) }, { signal })
          if (response.error || !response.data) throw new Error("产物内容读取失败，请刷新任务版本。")
          return response.data
        },
      },
      publication: async (signal) => {
        const response = await client.quantcode.publication.status({}, { signal })
        if (response.error || !response.data) throw new Error("无法核验组织同步状态。")
        return response.data
      },
      list: async ({ cursor, signal }) => {
        const response = await client.quantcode.taskIndex.list({ limit: "100", cursor }, { signal })
        if (response.error || !response.data) throw new Error("任务索引暂不可用，请重新连接后刷新。")
        return response.data
      },
      read: async (task, signal) => {
        const response = await client.quantcode.taskIndex.read({ sessionID: task.session_id }, { signal })
        if (response.error || !response.data) throw new Error("当前身份无法读取该任务。")
        return response.data
      },
    }
  })
  const organizationTasks = createMemo<NativeTaskSource>(() => {
    const client = serverSDK().client
    return {
      publication: async (signal) => {
        const response = await client.quantcode.publication.status({}, { signal })
        if (response.error || !response.data) throw new Error("无法核验本机任务同步状态。")
        return response.data
      },
      artifacts: {
        list: async (task, cursor, signal) => {
          const response = await client.quantcode.organizationArtifacts.list({ source_id: task.source_id, sessionID: task.session_id, source_revision: String(task.source_revision), cursor }, { signal })
          if (response.error || !response.data) throw new Error("组织产物清单尚未同步或任务版本已变化。")
          return response.data
        },
        read: async (task, artifact, offset, signal) => {
          const response = await client.quantcode.organizationArtifacts.read({ source_id: task.source_id, sessionID: task.session_id, source_revision: String(task.source_revision), artifact_id: artifact.id, offset: String(offset) }, { signal })
          if (response.error || !response.data) throw new Error("组织产物尚未同步或当前身份无权读取。")
          return response.data
        },
      },
      relatives: async (task, cursor, signal) => {
        const response = await client.quantcode.organizationTasks.list({ limit: "100", cursor,
          source_id: task.source_id, root_session_id: task.root_session_id }, { signal })
        if (response.error || !response.data) throw new Error("组织任务树读取失败。")
        return response.data
      },
      list: async ({ cursor, signal }) => {
        const response = await client.quantcode.organizationTasks.list({ limit: "100", cursor }, { signal })
        if (response.error || !response.data) throw new Error("组织任务索引尚不可用。")
        return response.data
      },
      read: async (task, signal) => {
        if (!task.source_id) throw new Error("组织任务缺少执行宿主标识。")
        const response = await client.quantcode.organizationTasks.read({ sessionID: task.session_id, source_id: task.source_id }, { signal })
        if (response.error || !response.data) throw new Error("组织任务摘要读取失败。")
        return response.data
      },
    }
  })
  const openNativeTask = (sessionID: string) => {
    if (sessionID === props.nativeSessionID) { props.onClose?.(); return }
    const tab = tabs.addSessionTab({ server: server.key, sessionId: sessionID })
    tabs.select(tab)
    props.onClose?.()
  }

  /** 通知"去审批"：把目标 run 设为当前 trace 并切到 HumanGate 视图。 */
  const focusGateThread = (threadId: string) => {
    setNotifOpen(false)
    const run = _threadHistory().find((item) => item.thread_id === threadId)
    if (!run) return
    updateQuantCodeTrace(run)
    setState("view", "gate")
  }

  /** F-09：通知 = 待审批 gate + 双类 pop（repo 新提交 / 依赖更新），badge 计数合并 */
  const allNotifItems = createMemo(() => notifItems())

  // 通知面板打开期间监听 Escape 关闭（effect 重跑时自动解除旧监听）
  createEffect(() => {
    if (!notifOpen()) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNotifOpen(false)
    }
    window.addEventListener("keydown", onKey)
    onCleanup(() => window.removeEventListener("keydown", onKey))
  })

  // Trace bridge: the legacy task renderer pushes results here while
  // the panel is mounted; deregister on teardown so no stale writes land.
  onMount(() => setQuantCodeTraceListener(handleQuantCodeTracePayload))
  onCleanup(() => setQuantCodeTraceListener(null))

  onMount(() => {
    let disposed = false
    onCleanup(() => { disposed = true })
    void platform.identity?.sshAdminStatus?.().then(current => {
      if (disposed || !current) return
      setState("adminSession", current.session)
      if (!server.current?.organizationAdmin) setState("view", "server-admin")
    }).catch(() => undefined)
  })

  let skillsRequest = 0
  createEffect(() => {
    state.identityRevision
    const client = serverSDK().client
    const serverKey = String(server.key)
    let cancelled = false
    setState({ sshIdentities: [], sshSession: undefined, sshIdentityError: "" })
    setState({ unifiedRuntime: false, runtimeStatus: "loading" })
    const identityRequest = platform.identity
      ? platform.identity.inspect({ server: serverKey }).then(data => ({ data, error: undefined }))
      : client.quantcode.identity.list()
    void identityRequest.then(response => {
      if (cancelled) return
      const data = response.data
      if (response.error || !data || typeof data !== "object") {
        setState("sshIdentityError", "本机身份服务不可用，请检查研究服务器连接。")
        return
      }
      if ("error" in data && typeof data.error === "string") {
        // 本机研究宿主（sidecar）没有组织身份配置：组织登录必须走个人研究宿主，
        // 把宿主侧的配置错误翻译成下一步操作指引，而不是裸报错。
        if (serverKey === "sidecar" && data.error.includes("尚未配置组织身份连接")) {
          setState("sshIdentityError",
            "当前选中的是本机研究宿主（开发用），不支持组织登录。请点右侧「管理服务器」，添加组织分配给你的个人研究宿主地址并切换过去。")
          return
        }
        setState("sshIdentityError", data.error)
        return
      }
      if (!("identities" in data) || !Array.isArray(data.identities)
        || !data.identities.every(identity => identity && typeof identity.id === "string" && typeof identity.fingerprint === "string")) {
        setState("sshIdentityError", "本机身份服务返回格式错误。")
        return
      }
      setState("sshIdentities", data.identities as SshIdentity[])
      if ("session" in data && data.session && typeof data.session === "object"
        && "status" in data.session && data.session.status === "connected"
        && "fingerprint" in data.session && typeof data.session.fingerprint === "string"
        && "group" in data.session && typeof data.session.group === "string") {
        setState("sshSession", data.session as SshSession)
      }
      if (!data.identities.length) setState("sshIdentityError", "宿主尚未提供可用公钥身份，请完成本机身份桥配置。")
    }).catch(error => {
      if (cancelled) return
      // Electron IPC 拒绝会带上远端方法前缀；剥掉后按服务器给出可操作的指引
      const raw = error instanceof Error ? error.message : "读取身份失败，请检查研究宿主连接。"
      const message = raw.replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/, "")
      if (serverKey === "sidecar" && message.includes("尚未配置组织身份连接")) {
        setState("sshIdentityError",
          "当前选中的是本机研究宿主（开发用），不支持组织登录。请点右侧「管理服务器」，添加组织分配给你的个人研究宿主地址并切换过去。")
        return
      }
      setState("sshIdentityError", message)
    })
    onCleanup(() => { cancelled = true })
    activeThreadCacheKey = undefined
    setSessionId(undefined)
    lastResultJson = undefined
    resetQuantCodeState()
    setGroup("")
    setState({ historyScope: "", sessionStatus: "loading", sessionRole: "未连接", sessionActor: "未连接", workspacePath: "", sessionId: "", githubSubject: "", skills: [], skill: "", memoryTab: "knowledge" })
    void getQuantCodeSessionContext(client).then(
      (context) => {
        if (cancelled) return
        const group = context.group
        if (!group || !QUANTCODE_GROUPS.includes(group as QuantCodeGroup)) {
          activeThreadCacheKey = undefined
          resetQuantCodeState()
          setState({ sessionStatus: "error", sessionRole: "身份组无效", sessionActor: "未连接", skillsStatus: "error", skill: "" })
          return
        }
        activeThreadCacheKey = scopedThreadCacheKey({ ...context, group }, serverKey)
        resetQuantCodeState()
        if (activeThreadCacheKey) loadScopedThreadCache(activeThreadCacheKey)
        setQuantCodeSessionGroup(group)
        if (server.current?.organizationAdmin && context.role === "admin") setState("view", "admin")
        setState({ historyScope: activeThreadCacheKey ?? "", sessionStatus: "ready", sessionRole: context.role ?? "analyst", sessionActor: context.actor_id ?? "已认证身份", workspacePath: context.workspace_path ?? "", sessionId: context.session_id ?? "", githubSubject: context.github_subject ?? "" })
      },
      () => {
        if (cancelled) return
        activeThreadCacheKey = undefined
        resetQuantCodeState()
        setState({ sessionStatus: "error", sessionRole: "身份接线未完成", sessionActor: "未连接", skillsStatus: "error", skill: "" })
      },
    )
    void client.experimental.capabilities.get().then(response => {
      if (cancelled) return
      if (response.error || typeof response.data?.quantcodeUnifiedRuntime !== "boolean") {
        setState("runtimeStatus", "error")
        return
      }
      setState({ unifiedRuntime: response.data.quantcodeUnifiedRuntime, runtimeStatus: "ready" })
    }).catch(() => { if (!cancelled) setState("runtimeStatus", "error") })
  })

  // Keep the visible account in step with revoked/expired host sessions.
  createEffect(() => {
    if (state.sessionStatus !== "ready") return
    const expected = state.sessionId
    const scope = state.historyScope
    const role = state.sessionRole
    const client = serverSDK().client
    const serverKey = String(server.key)
    let cancelled = false
    let pending = false
    const verify = async () => {
      if (pending) return
      pending = true
      try {
        const context = await getQuantCodeSessionContext(client)
        if (!cancelled && ((context.session_id ?? "") !== expected || context.role !== role ||
          scopedThreadCacheKey({ ...context, group: context.group! }, serverKey) !== scope)) {
          setState("identityRevision", value => value + 1)
        }
      } catch {
        if (!cancelled) {
          activeThreadCacheKey = undefined
          resetQuantCodeState()
          setGroup("")
          setState({ sessionStatus: "error", sessionActor: "未连接", sessionRole: "未连接", sessionId: "", workspacePath: "", historyScope: "", githubSubject: "", sshSession: undefined, skills: [], skill: "", skillsStatus: "error", memoryTab: "knowledge" })
        }
      } finally { pending = false }
    }
    const interval = setInterval(() => void verify(), 60_000)
    window.addEventListener("focus", verify)
    onCleanup(() => { cancelled = true; clearInterval(interval); window.removeEventListener("focus", verify) })
  })

  createEffect(() => {
    const group = _group()
    if (state.sessionStatus !== "ready") return
    if (state.runtimeStatus !== "ready") return
    if (state.unifiedRuntime) { setState({ skills: [], skill: "", skillsStatus: "ready" }); return }
    const request = ++skillsRequest
    onCleanup(() => { skillsRequest++ })
    setState({ skillsStatus: "loading", skills: [], skill: "" })
    void listQuantCodeSkills(serverSDK().client, group).then(
      (skills) => {
        if (request !== skillsRequest) return
        setState({ skills, skillsStatus: skills.length ? "ready" : "error", skill: skills[0]?.id ?? "" })
      },
      () => {
        if (request !== skillsRequest) return
        setState({ skills: [], skillsStatus: "error", skill: "" })
      },
    )
  })



  const selectedSkill = createMemo(() => state.skills.find((skill) => skill.id === state.skill))
  const selectedSkillLabel = createMemo(() => {
    const skill = selectedSkill()
    if (skill) return skillLabel(skill)
    if (state.sessionStatus !== "ready") return "身份未连接"
    if (state.unifiedRuntime) return "按业务组加载 Skill"
    return state.skillsStatus === "loading" ? "正在加载 Skill 目录…" : "Skill 目录未连接"
  })
  const gateWaiting = createMemo(() => _trace()?.status === "waiting_for_human")
  const serverName = createMemo(() => server.name || "当前服务器")
  const serverReady = createMemo(() => server.ready())
  const serverTransport = createMemo(() => (server.isLocal() ? "本机研究宿主" : "远程研究宿主"))
  const sshConnect = createMemo<SshConnectFn>(() => {
    const bridge = platform.identity
    const selected = String(server.key)
    if (!bridge) return createLocalIdentityConnect(serverSDK().client, () => setState("identityRevision", value => value + 1))
    return async ({ identityId, log }) => {
      log("正在使用本机 SSH agent 验证组织身份…")
      try {
        const result = await bridge.connect({ server: selected, identityId })
        if (selected !== String(server.key)) return { status: "error", reason: "研究宿主已切换，请查看所选宿主的登录状态。" }
        setState("identityRevision", value => value + 1)
        return result
      } catch (error) { return { status: "error", reason: error instanceof Error ? error.message : "身份认证未完成，请重试。" } }
    }
  })
  const sshDisconnect = createMemo<SshDisconnectFn>(() => {
    const bridge = platform.identity
    const selected = String(server.key)
    if (!bridge) return createLocalIdentityDisconnect(serverSDK().client, () => setState("identityRevision", value => value + 1))
    return async () => {
      try {
        const result = await bridge.disconnect({ server: selected })
        if (selected === String(server.key)) setState("identityRevision", value => value + 1)
        return result
      } catch (error) { return { status: "error", reason: error instanceof Error ? error.message : "退出未完成，请重试。" } }
    }
  })
  const enterSshWorkspace = async (result: QuantCodeSshLoginResult) => {
    if (result.mode === "server-admin") {
      setState({ adminSession: result.admin, view: "server-admin" })
      navigate("/")
      return
    }
    if (!result.connection || !result.session) throw new Error("登录结果缺少连接信息，请重试。")
    const organizationAdmin = result.mode === "organization-admin"
    const context = await getQuantCodeSessionContext(createSdkForServer({ server: result.connection, fetch: platform.fetch }))
    if (context.session_id !== result.session.session_id || context.actor_id !== result.session.actor_id || context.group !== result.session.group) {
      throw new Error("登录身份正在变化，请重试。")
    }
    if (organizationAdmin && context.role !== "admin") throw new Error("当前身份没有组织管理员权限。")
    if (!organizationAdmin && !context.workspace_path) throw new Error("组织尚未分配个人工作区，请联系管理员。")
    batch(() => {
      const connection = server.add({ type: "http", displayName: result.connection.displayName, organizationAdmin,
        http: { url: result.connection.url, username: result.connection.username, password: result.connection.password } })
      if (!connection) throw new Error("无法保存个人研究宿主连接，请重试。")
      if (!organizationAdmin && context.workspace_path) {
        server.projects.open(context.workspace_path)
        server.projects.touch(context.workspace_path)
      }
      setState("identityRevision", value => value + 1)
    })
    await platform.setDefaultServer?.(server.key)
    setState("view", organizationAdmin ? "admin" : "compose")
    setState("adminSession", organizationAdmin ? result.admin : undefined)
    navigate("/")
  }

  const recent = createMemo(() => {
    const history = _threadHistory().slice(0, 3)
    if (history.length) {
      return history.map((run) => ({
        id: run.thread_id ?? `${run.timestamp}`,
        title: taskFromRun(run),
        meta: `${run.execution_trace?.length ?? 0} steps · ${run.artifacts?.length ?? 0} artifacts`,
        status: statusLabel(run.status),
        time: formatTime(run.timestamp),
        template: false,
      }))
    }
    return [
      {
        id: "pb-roe",
        title: "PB–ROE 中性化因子扫描",
        meta: "Factor · Auto Factor Evaluation",
        status: "模板",
        time: "01",
        template: true,
      },
      {
        id: "liquidity",
        title: "短周期流动性因子复核",
        meta: "Risk · Cross-section Research",
        status: "模板",
        time: "02",
        template: true,
      },
      {
        id: "vol-surface",
        title: "期权波动率曲面异常",
        meta: "Options · Risk Review",
        status: "模板",
        time: "03",
        template: true,
      },
    ]
  })

  const instruction = () => {
    return buildResearchInstruction({
      task: state.task,
      skillLabel: selectedSkillLabel(),
      unifiedRuntime: state.unifiedRuntime,
    })
  }

  const submitInstruction = async (content: string, nextView: DetailView = "compose"): Promise<boolean> => {
    // Guard the shared submission path as well as the form button.  A second
    // click can otherwise arrive before Solid flushes the signal update or
    // while the requestAnimationFrame callback is still queued.
    if (state.submit === "starting") return false
    if (state.runtimeStatus !== "ready") {
      setState({ submit: "error", error: language.t("quantcode.native.unavailable") })
      return false
    }
    setState({ submit: "starting", error: "" })

    if (state.unifiedRuntime && props.nativeSessionID && directorySDK) {
      const context = directorySDK()
      const sessionID = props.nativeSessionID
      const login = state.sessionId
      const serverContext = serverSDK()
      const client = context.client
      const active = () => !disposed && props.nativeSessionID === sessionID && directorySDK() === context && serverSDK() === serverContext && state.sessionId === login
      try {
        // Use exactly the same selection as the native session composer,
        // including an unsent model/agent/variant change made by the user.
        const selectedModel = local?.model.current()
        const selectedAgent = local?.agent.current()
        const variant = local?.model.variant.current()
        if (!selectedModel || !selectedAgent) throw new Error("模型或 Agent 尚未就绪，请返回任务界面完成选择。")
        const model = { modelID: selectedModel.id, providerID: selectedModel.provider.id }
        const agent = selectedAgent.name
        const response = await client.session.get({ sessionID })
        if (response.error || !response.data || response.data.id !== sessionID || !active()) {
          throw new Error("任务或工作区已变化，请回到原任务后再提交。")
        }
        const target = serverContext.ensureDirSdkContext(response.data.directory).client
        const submitted = await target.session.promptAsync({ sessionID, model, agent, variant, parts: [{ type: "text", text: content }] })
        if (submitted.error) throw new Error("任务提交失败，请在任务界面核对连接状态。")
        if (!active()) return false
        setState({ submit: "submitted", error: "" })
        props.onClose?.()
        return true
      } catch (error) {
        if (active()) setState({ submit: "error", error: error instanceof Error ? error.message : "任务提交失败，请重试。" })
        return false
      }
    }

    if (state.unifiedRuntime && !props.onSubmitInstruction) {
      setState({ submit: "error", error: "请返回任务界面新建任务；历史会话不能作为新执行器继续。" })
      return false
    }

    if (props.onSubmitInstruction) {
      const result = await submitQuantCodeInstruction(props.onSubmitInstruction, content)
      if (result === "unavailable") {
        setState({ submit: "error", error: "请先连接研究服务器并选择一个项目。" })
        return false
      }
      if (result === "failed") {
        setState({ submit: "error", error: "研究启动失败，请重试。" })
        return false
      }
      setState({ view: nextView, submit: "submitted" })
      return true
    }

    if (!prompt) {
      setState({ submit: "error", error: "研究输入尚未就绪，请稍后重试。" })
      return false
    }

    prompt.set([{ type: "text", content, start: 0, end: content.length }], content.length)

    return new Promise<boolean>(resolve => requestAnimationFrame(() => {
      const form = document.querySelector<HTMLFormElement>(
        '[data-component="session-composer"], [data-component="session-new-composer"]',
      )
      if (!form) {
        setState({ view: "compose", submit: "error", error: "当前会话输入框尚未就绪，请稍后重试。" })
        resolve(false)
        return
      }
      try { form.requestSubmit() }
      catch {
        setState({ submit: "error", error: "当前会话提交失败，请稍后重试。" })
        resolve(false)
        return
      }
      setState({ view: nextView, submit: "submitted" })
      resolve(true)
    }))
  }

  const submitResearch = () => {
    if (!state.task.trim() || (!state.unifiedRuntime && !state.skill) || state.runtimeStatus !== "ready" || state.sessionStatus !== "ready" || state.submit === "starting") return
    submitInstruction(instruction())
  }

  const recoverLegacy = (content: string) => {
    if (!state.unifiedRuntime) return submitInstruction(content, "activity")
    const error = language.t("quantcode.native.legacyRecovery")
    setState({ submit: "error", error })
    showToast({ title: error, variant: "error" })
    return Promise.resolve(false)
  }

  /**
   * HumanGate 审批 → resume：向归档任务所属的 session 通过 server SDK
   * promptAsync 发结构化短指令（立即返回，不阻塞整轮 agent 回合），由 Agent 调
   * 兼容恢复工具只处理已存在的归档任务。day5 P0-4 的实现，接到 QuantCode GatePanel 按钮。
   */
  const sendGateDecision = (threadId: string, decision: GateDecision) => {
    if (state.unifiedRuntime) { void recoverLegacy(""); return }
    const sessionId = _sessionId()
    if (!sessionId || !threadId || state.submit === "starting") return
    setState({ submit: "starting", error: "" })
    try {
      void serverSDK().client.session
        .promptAsync({
          sessionID: sessionId,
          parts: [
            {
              type: "text",
              text: buildResumeInstruction(threadId, decision, _trace()?.gate?.gate_id),
            },
          ],
        })
        .then((response) => {
          if (response.error) throw new Error("Gate resume request failed")
          showToast({ title: language.t("quantcode.gate.resumeSent"), variant: "success" })
          setState({ view: "activity", submit: "submitted" })
        })
        .catch(() => {
          setState({ submit: "error", error: language.t("quantcode.gate.resumeFailed") })
          showToast({ title: language.t("quantcode.gate.resumeFailed"), variant: "error" })
        })
    } catch {
      setState({ submit: "error", error: language.t("quantcode.gate.resumeFailed") })
      showToast({ title: language.t("quantcode.gate.resumeFailed"), variant: "error" })
    }
  }

  const focusComposer = (task?: string) => {
    if (task) setState("task", task)
    setState("view", "compose")
    requestAnimationFrame(() => taskInput?.focus())
  }

  onMount(() => {
    if (!shell || !stage || !fieldCanvas || !focusLens || !sharpBrand) return
    const elements = { shell, stage, fieldCanvas, focusLens, sharpBrand }
    const field = { disposed: false, dispose: () => {} }
    void import("./lens-field")
      .then(async (module) => {
        const dispose = await module.createQuantCodeLensField({
          canvas: elements.fieldCanvas,
          stage: elements.stage,
          shell: elements.shell,
          lens: elements.focusLens,
          sharpBrand: elements.sharpBrand,
        })
        if (!field.disposed) {
          field.dispose = dispose
          return
        }
        dispose()
      })
      .catch((error: unknown) => {
        if (field.disposed) return
        console.error("[quantcode] lens field failed to load", error)
        const note = document.createElement("p")
        note.className = "qc-lens-field-error"
        note.textContent = "视觉效果暂不可用，研究工作区仍可继续使用。"
        stage?.append(note)
      })
    onCleanup(() => {
      field.disposed = true
      field.dispose()
    })
  })

  const navItems: { id: DetailView; label: string; icon: IconProps["name"] }[] = [
    { id: "compose", label: "新建研究", icon: "plus" },
    { id: "activity", label: "执行记录", icon: "checklist" },
    { id: "gate", label: "HumanGate", icon: "review" },
    { id: "memory", label: "Memory", icon: "brain" },
    { id: "capabilities", label: "能力目录", icon: "mcp" },
    { id: "solution", label: "方案", icon: "prompt" },
  ]
  /** F-09：admin 专属视图（Admin 中枢 / GitGraph），仅 admin 角色可见导航项 */
  const adminNavItems: { id: DetailView; label: string; icon: IconProps["name"] }[] = [
    { id: "admin", label: "组织管理", icon: "shield" },
    { id: "gitgraph", label: "GitGraph", icon: "branch" },
  ]

  return (
    <div ref={shell} class="qc-shell" data-quantcode-workspace="true" data-view={state.view}>
      <a class="qc-skip-link" href="#qc-research-prompt">
        跳到研究输入
      </a>
      <aside class="qc-rail" aria-label="QuantCode 导航">
        <button type="button" class="qc-mark" aria-label="QuantCode 首页" onClick={() => setState("view", "compose")}>
          QC
        </button>
        <nav>
          <Show when={allNotifItems().length > 0 || state.githubUnread > 0 || notifOpen()} fallback={null}>
            {(() => {
              const bell = NotificationsBell({
                count: allNotifItems().length + state.githubUnread,
                onClick: () => setNotifOpen(!notifOpen()),
              })
              bell.classList.toggle("is-active", notifOpen())
              return bell
            })()}
          </Show>
          <Show when={state.adminSession}>
            <button type="button" class="qc-rail-button" classList={{ "is-active": state.view === "server-admin" }}
              aria-label="服务器运维" title="服务器运维" onClick={() => setState("view", "server-admin")}><Icon name="settings-gear" /></button>
          </Show>
          <For each={[...navItems, ...adminNavItems.filter((item) => item.id === "gitgraph" ? state.sessionStatus === "ready" : adminViewable())]}>
            {(item) => (
              <button
                type="button"
                class="qc-rail-button"
                classList={{ "is-active": state.view === item.id }}
                aria-label={item.label}
                aria-pressed={state.view === item.id}
                title={item.label}
                onClick={() => setState("view", item.id)}
              >
                <Icon name={item.icon} size="normal" />
                <span class="qc-nav-label">{item.label}</span>
                <Show when={item.id === "gate" && gateWaiting()}>
                  <span class="qc-rail-alert" />
                </Show>
              </button>
            )}
          </For>
        </nav>
        <Show when={notifOpen()}>
          <button type="button" class="qc-button" onClick={() => { setNotifOpen(false); setState("view", "gitgraph") }}>持久更新通知（{state.githubUnread}）</button>
          {NotificationsPanel({
            items: allNotifItems(),
            onClose: () => setNotifOpen(false),
            onApprove: focusGateThread,
            onOpenGitgraph: () => {
              setNotifOpen(false)
              setState("view", "gitgraph")
            },
            t: language.t as (key: string) => string,
          })}
        </Show>
        <div class="qc-rail-footer">
          <button
            type="button"
            class="qc-rail-button"
            classList={{ "is-active": state.view === "settings" }}
            aria-label="QuantCode 设置"
            title="设置"
            onClick={() => setState("view", "settings")}
          >
            <Icon name="settings-gear" size="normal" />
            <span class="qc-nav-label">设置与登录</span>
          </button>
          <Show when={props.onClose}>
            <button
              type="button"
              class="qc-rail-button"
              aria-label={props.nativeSessionID ? language.t("quantcode.native.return") : "关闭 QuantCode 工作区"}
              title={props.nativeSessionID ? language.t("quantcode.native.return") : "关闭 QuantCode 工作区"}
              onClick={() => props.onClose?.()}
            >
              <Icon name={props.nativeSessionID ? "arrow-left" : "close"} size="normal" />
              <Show when={props.nativeSessionID}><span class="qc-nav-label">{language.t("quantcode.native.return")}</span></Show>
            </button>
          </Show>
        </div>
      </aside>

      <main class="qc-main">
        <header class="qc-identity-bar">
          <button type="button" class="qc-identity" aria-label="账号与登录" title="账号与登录" onClick={() => setState({ view: "settings", orgSshStart: !state.adminSession && state.sessionStatus !== "ready" && !!platform.identity?.sshConnect })}>
            <Icon name="shield" size="small" />
            <span>{state.view === "server-admin" && state.adminSession ? `${state.adminSession.username} · 服务器运维` : state.sessionStatus === "ready" ? state.sessionActor : "重新登录"}</span>
            <Show when={state.sessionStatus === "ready" && state.view !== "server-admin"}><strong>{_group()} 组</strong><span class="qc-role">{state.sessionRole === "admin" ? "管理员" : state.sessionRole === "approver" ? "审批人" : "研究员"}</span></Show>
            <Icon name="chevron-down" size="small" />
          </button>
          <div class="qc-environment">
            <span>{serverName()}</span>
            <i />
            <span class="qc-connected" classList={{ "is-disconnected": !serverReady() }}>
              <b /> {serverReady() ? "服务在线" : "服务离线"}
            </span>
          </div>
        </header>

        <div class="qc-canvas">
          <section
            ref={stage}
            class="qc-stage"
            aria-labelledby="qc-lens-title"
            onPointerDown={(event) => {
              if (event.target === event.currentTarget) taskInput?.blur()
            }}
          >
            <div class="qc-brand qc-brand-blurred" aria-hidden="true">
              QUANTCODE
            </div>
            <div class="qc-brand qc-brand-dotted" aria-hidden="true">
              QUANTCODE
            </div>
            <div ref={sharpBrand} class="qc-brand qc-brand-sharp" aria-hidden="true">
              QUANTCODE
            </div>
            <canvas ref={fieldCanvas} class="qc-particle-field" aria-hidden="true" />
            <div ref={focusLens} class="qc-focus-lens" aria-hidden="true" />
            <div class="qc-lens-action">
              <button type="button" class="qc-lens-title-button" onClick={() => focusComposer()}>
                <h1 id="qc-lens-title">新建多智能体研究</h1>
              </button>
              <button type="button" class="qc-lens-meta-row" onClick={() => setState("view", "settings")}>
                <span>组:</span>
                <strong>{state.sessionStatus === "ready" ? _group() : "未认证"}</strong>
                <small>· {selectedSkillLabel()}</small>
                <Icon name="chevron-down" size="small" />
              </button>
              <button type="button" class="qc-lens-meta-row" onClick={() => setState("view", "settings")}>
                <span>服务:</span>
                <strong>{serverName()}</strong>
                <small>{serverReady() ? "已连接" : "未连接"}</small>
                <Icon name="chevron-down" size="small" />
              </button>
            </div>
          </section>

          <section class="qc-compose-zone" id="qc-research-prompt" aria-label="研究任务">
            <Show when={state.sessionStatus !== "ready"}>
              <div class="qc-login-notice"><Icon name="shield" /><span>{state.sessionStatus === "loading" ? "正在核验身份" : "当前未登录"}</span><button type="button" class="qc-button qc-button-primary" onClick={() => setState({ view: "settings", orgSshStart: !!platform.identity?.sshConnect })}>重新登录<Icon name="arrow-right" size="small" /></button></div>
            </Show>
            <div class="qc-compose-grid">
              <div class="qc-compose-left">
                <div class="qc-composer" classList={{ "has-error": state.submit === "error" }}>
                  <PromptPopover
                    popover={slashPopover()}
                    setSlashPopoverRef={(el) => (slashPopoverRef = el)}
                    atFlat={[]}
                    atKey={() => ""}
                    setAtActive={() => {}}
                    onAtSelect={() => {}}
                    slashFlat={slashList.flat()}
                    slashActive={slashList.active() || undefined}
                    setSlashActive={slashList.setActive}
                    onSlashSelect={selectSlashCommand}
                    commandKeybind={command.keybind}
                    commandKeybindParts={command.keybindParts}
                    newLayoutDesigns={false}
                    t={(key) => language.t(key as Parameters<typeof language.t>[0])}
                  />
                  <label for="qc-task">今天研究什么？</label>
                  <textarea
                    id="qc-task"
                    ref={taskInput}
                    value={state.task}
                    rows={2}
                    placeholder="描述任务，或输入 / 调用 Skill."
                    onInput={(event) => {
                      const value = event.currentTarget.value
                      setState({ task: value, submit: "idle", error: "" })
                      const match = value.match(/^\/(\S*)$/)
                      if (match) {
                        slashList.onInput(match[1])
                        setSlashPopover("slash")
                      } else {
                        setSlashPopover(null)
                      }
                    }}
                    onKeyDown={(event) => {
                      if (slashPopover()) {
                        if (event.key === "Escape") {
                          event.preventDefault()
                          setSlashPopover(null)
                          return
                        }
                        if (["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) {
                          slashList.onKeyDown(event)
                          return
                        }
                      }
                      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submitResearch()
                    }}
                    onBlur={() => setSlashPopover(null)}
                  />
                  <div class="qc-composer-actions">
                    <Show when={!state.unifiedRuntime} fallback={<span class="qc-skill-select"><Icon name="brain" size="small" />{language.t("quantcode.native.skill")}</span>}>
                    <label class="qc-skill-select">
                      <Icon name="brain" size="small" />
                      <span class="sr-only">选择 Skill</span>
                      <select
                        value={state.skill}
                        disabled={state.skillsStatus !== "ready"}
                        onChange={(event) => setState("skill", event.currentTarget.value)}
                      >
                        <Show when={state.skillsStatus === "loading"}>
                          <option value="">正在加载 Skill 目录…</option>
                        </Show>
                        <Show when={state.skillsStatus === "error"}>
                          <option value="">Skill 目录未连接</option>
                        </Show>
                        <For each={state.skills}>{(skill) => <option value={skill.id}>{skillLabel(skill)}</option>}</For>
                      </select>
                    </label>
                    </Show>
                    <div class="qc-submit-cluster">
                      <span>⌘ ENTER</span>
                      <button
                        type="button"
                        disabled={
                          !state.task.trim() || (!state.unifiedRuntime && !state.skill) || state.runtimeStatus !== "ready" || state.sessionStatus !== "ready" || state.submit === "starting"
                        }
                        onClick={submitResearch}
                      >
                        <Show
                          when={state.submit === "starting"}
                          fallback={
                            <>
                              开始研究 <Icon name="arrow-right" size="small" />
                            </>
                          }
                        >
                          正在启动
                        </Show>
                      </button>
                    </div>
                  </div>
                </div>
                <div class="qc-submit-state" aria-live="polite">
                  <Switch>
                    <Match when={state.runtimeStatus === "loading"}><span>{language.t("quantcode.native.checking")}</span></Match>
                    <Match when={state.runtimeStatus === "error"}><span class="is-error">{language.t("quantcode.native.unavailable")}</span></Match>
                    <Match when={state.submit === "submitted"}>
                      <span class="is-success">{state.unifiedRuntime ? language.t("quantcode.native.submitted") : `研究已提交到 ${_group()} Multi-Agent 流。`}</span>
                    </Match>
                    <Match when={state.submit === "error"}>
                      <span class="is-error">{state.error}</span>
                    </Match>
                    <Match when={state.submit === "starting"}>
                      <span>正在建立任务上下文…</span>
                    </Match>
                  </Switch>
                </div>
              </div>
              <aside class="qc-compose-metrics" aria-label="指标摘要">
                <span class="qc-section-label">指标摘要</span>
                <Show when={_trace()} fallback={<p class="qc-metrics-empty">启动一次研究后，指标将实时汇总于此。</p>}>
                  {(run) => (
                    <div class="qc-metrics-body">
                      <For each={bigNumbersFromOutput(run().output_data)}>
                        {(card) => QcBigNumber({ label: card.label, value: card.value, tone: card.tone })}
                      </For>
                      <Show when={run().gate || traceEventCount(run()) > 0}>
                        <div class="qc-metrics-strip">
                          <Show when={run().gate}>
                            <span>
                              Gate {run()!.gate?.reasons?.length ?? 0} 项原因 · {statusLabel(run().status)}
                            </span>
                          </Show>
                          <span>{traceEventCount(run())} 条 trace</span>
                        </div>
                      </Show>
                    </div>
                  )}
                </Show>
              </aside>
            </div>
          </section>

          <section class="qc-recents" aria-labelledby="qc-recents-title">
            <div class="qc-recents-heading">
              <h2 id="qc-recents-title">{_threadHistory().length ? "最近研究" : "研究模板"}</h2>
              <button type="button" onClick={() => setState("view", "activity")}>
                查看全部 <Icon name="arrow-right" size="small" />
              </button>
            </div>
            <div class="qc-recent-list">
              <For each={recent()}>
                {(item, index) => (
                  <button
                    type="button"
                    class="qc-recent-row"
                    onClick={() => (item.template ? focusComposer(item.title) : setState("view", "activity"))}
                  >
                    <span class="qc-recent-index">{String(index() + 1).padStart(2, "0")}</span>
                    <span class="qc-recent-copy">
                      <strong>{item.title}</strong>
                      <small>{item.meta}</small>
                    </span>
                    <span class="qc-recent-status">{item.status}</span>
                    <time>{item.time}</time>
                    <Icon name="arrow-right" size="small" />
                  </button>
                )}
              </For>
            </div>
          </section>

            <section class="qc-detail-panel" aria-label="QuantCode 详情" hidden={state.view === "compose"}>
              <div class="qc-detail-header">
                <div>
                  <span>QUANTCODE / {state.view.toUpperCase()}</span>
                  <h2>
                    {state.view === "activity"
                      ? "执行记录"
                      : state.view === "gate"
                          ? "HumanGate"
                          : state.view === "memory"
                            ? "Memory"
                            : state.view === "capabilities"
                              ? "能力目录"
                              : state.view === "solution"
                                ? "方案"
                                : state.view === "admin"
                                  ? "Admin 中枢"
                                  : state.view === "gitgraph"
                                    ? "GitGraph"
                                    : "工作区设置"}
                  </h2>
                </div>
                <button type="button" aria-label="关闭详情" onClick={() => setState("view", "compose")}>
                  <Icon name="close" size="normal" />
                </button>
              </div>
              <div class="qc-view-content">
          <GitHubWorkspace
            scope={state.historyScope}
            ready={state.sessionStatus === "ready"}
            visible={state.view === "gitgraph"}
            fetcher={(tool, cursor) => readQuantCodeTool(serverSDK().client, tool, undefined, { cursor })}
            update={(id, changes) => updateQuantCodePop(serverSDK().client, id, changes)}
            onUnread={(count) => setState("githubUnread", count)}
            notificationPermission={async () => {
              if (platform.platform === "desktop") return true
              if (!("Notification" in window)) return false
              if (Notification.permission === "granted") return true
              if (Notification.permission === "denied") return false
              return await Notification.requestPermission() === "granted"
            }}
            notify={(count) => platform.notify("QuantCode · GitHub 更新", `发现 ${count} 条新更新，请在 GitGraph 中查看。`)}
          />
              <Switch>
                <Match when={state.view === "activity"}>
                  <div class="qc-view-tabs" role="tablist" aria-label="执行记录视图" onKeyDown={navigateViewTabs}>
                    <button type="button" role="tab" tabIndex={state.activityTab === "history" ? 0 : -1} aria-selected={state.activityTab === "history"} onClick={() => setState("activityTab", "history")}>已保存的任务</button>
                    <button type="button" role="tab" tabIndex={state.activityTab === "current" ? 0 : -1} aria-selected={state.activityTab === "current"} onClick={() => setState("activityTab", "current")}>当前执行</button>
                    <Show when={state.unifiedRuntime}><button type="button" role="tab" tabIndex={state.activityTab === "legacy" ? 0 : -1} aria-selected={state.activityTab === "legacy"} onClick={() => setState("activityTab", "legacy")}>归档任务</button></Show>
                  </div>
                  <Show when={state.unifiedRuntime && state.activityTab === "current"}>
                    <Show when={props.nativeSessionID} fallback={<WorkspaceEmpty icon="task" title="选择一个任务查看当前执行" />}>
                      <NativeTaskHistory scope={state.historyScope} ready={state.sessionStatus === "ready"} currentSessionID={props.nativeSessionID}
                        source={nativeTasks()} onOpen={openNativeTask} />
                    </Show>
                  </Show>
                  <Show when={!state.unifiedRuntime && state.activityTab === "current"}><ActivityPanel onUseTask={focusComposer} /></Show>
                  <Show when={state.unifiedRuntime && state.activityTab === "history"}>
                    <NativeTaskHistory scope={state.historyScope} ready={state.sessionStatus === "ready"} source={nativeTasks()}
                      onOpen={openNativeTask} onNew={() => focusComposer()} />
                  </Show>
                  <Show when={state.unifiedRuntime ? state.activityTab === "legacy" : state.activityTab === "history"}>
                  <RunHistoryView
                    scope={state.historyScope}
                    ready={state.sessionStatus === "ready"}
                    legacy={state.unifiedRuntime}
                    requestLegacyApproval={state.unifiedRuntime ? async (input, signal) => {
                      const response = await serverSDK().client.quantcode.legacy.requestApproval({ quantCodeLegacyApprovalInput: input }, { signal })
                      if (response.error || !response.data) throw new Error("旧任务审批申请未完成，请刷新检查点后重试。")
                      return response.data
                    } : undefined}
                    recoverLegacy={state.unifiedRuntime ? async (input, signal) => {
                      const response = await serverSDK().client.quantcode.legacy.resume({ quantCodeLegacyResumeInput: input }, { signal })
                      if (response.error || !response.data) throw new Error("旧任务恢复未完成，请检查当前检查点、来源登记与模型设置。")
                      return response.data
                    } : undefined}
                    onNew={() => focusComposer()}
                    onRecover={state.unifiedRuntime ? undefined : (threadId, checkpointId) => recoverLegacy(buildRecoveryInstruction(threadId, checkpointId))}
                    reconcileGroup={_group()}
                    reconcile={!state.unifiedRuntime && state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)
                      ? payload => reconcileQuantCodeReceipt(serverSDK().client, payload) : undefined}
                    fetcher={async (tool, params) => {
                      const client = serverSDK().client
                      if (!state.unifiedRuntime) return readQuantCodeTool(client, tool, undefined, params)
                      const response = tool === "get_run_history" && params.thread_id
                        ? await client.quantcode.legacy.detail({ thread_id: params.thread_id, checkpoint_id: params.checkpoint_id,
                            trace_cursor: params.trace_cursor === undefined ? undefined : String(params.trace_cursor) })
                        : await client.quantcode.legacy.list({ limit: "20", cursor: params.cursor })
                      if (response.error || !response.data) throw new Error("归档任务读取失败，请核对归档宿主配置。")
                      return response.data
                    }}
                  />
                  </Show>
                </Match>
                <Match when={state.view === "gate"}>
                  <Show when={state.unifiedRuntime && state.sessionStatus !== "ready"}>
                    <WorkspaceEmpty icon="shield" title="登录后查看审批" description="使用组织身份登录后，查看当前账号有权访问的审批请求。" />
                  </Show>
                  <Show when={state.unifiedRuntime && state.sessionStatus === "ready"}>
                    <NativeApprovalQueue scope={state.historyScope} client={serverSDK().client} canApprove={["approver", "admin"].includes(state.sessionRole)} />
                  </Show>
                  <Show when={!state.unifiedRuntime}>
                  <Show when={_trace()?.gate}><GatePanel role={state.sessionRole} onResume={sendGateDecision} /></Show>
                  <Show when={state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)}>
                    <ApprovalQueue scope={state.historyScope}
                      fetcher={(cursor) => readQuantCodeTool(serverSDK().client, "list_pending_gates", undefined, { cursor, limit: 20 })}
                      decide={(threadId, checkpointId, gateId, decision) => recoverLegacy(buildResumeInstruction(threadId, decision, gateId, checkpointId))} />
                  </Show>
                  <Show when={state.sessionStatus !== "ready" || (state.sessionRole === "analyst" && !_trace()?.gate)}>
                    <WorkspaceEmpty icon="shield" title={state.sessionStatus !== "ready" ? "登录后查看审批" : "当前没有待处理请求"} description={state.sessionStatus !== "ready" ? "尚未取得审批身份。" : "当前身份为研究员，审批操作由审批人或管理员处理。"} />
                  </Show>
                  </Show>
                </Match>
                <Match when={state.view === "memory"}>
                  <div class="qc-view-tabs" role="tablist" aria-label="Memory 视图" onKeyDown={navigateViewTabs}>
                    <button type="button" role="tab" tabIndex={state.memoryTab === "knowledge" ? 0 : -1} aria-selected={state.memoryTab === "knowledge"} onClick={() => setState("memoryTab", "knowledge")}>长期知识</button>
                    <Show when={state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)}><button type="button" role="tab" tabIndex={state.memoryTab === "review" ? 0 : -1} aria-selected={state.memoryTab === "review"} onClick={() => setState("memoryTab", "review")}>知识候选审核</button></Show>
                  </div>
                  <Show when={state.memoryTab === "knowledge"}>
                  <Show keyed when={state.sessionStatus === "ready" ? state.historyScope : undefined} fallback={<WorkspaceEmpty icon="shield" title="登录后检索知识" />}>
                  <MemoryQueryView
                    t={language.t as (key: string) => string}
                    fetcher={(query) => searchQuantCodeMemory(serverSDK().client, query)}
                  />
                  </Show>
                  </Show>
                  <Show when={state.memoryTab === "review" && state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)}>
                    <KnowledgeReview scope={state.historyScope}
                      fetcher={() => readQuantCodeTool(serverSDK().client, "list_distill_candidates")}
                      review={(name, action, digest, replacement) => reviewQuantCodeCandidate(serverSDK().client, name, action, digest, replacement)} />
                  </Show>
                </Match>
                <Match when={state.view === "capabilities"}>
                  <div class="qc-view-tabs" role="tablist" aria-label="能力目录分类" onKeyDown={navigateViewTabs}>
                    <For each={[{ id: "components", label: "组织组件" }, { id: "algorithms", label: "算法目录" }]}>{item => <button type="button" role="tab" aria-selected={state.catalogTab === item.id} tabIndex={state.catalogTab === item.id ? 0 : -1} onClick={() => setState("catalogTab", item.id)}>{item.label}</button>}</For>
                  </div>
                  <Show keyed when={state.sessionStatus === "ready" ? state.historyScope : undefined} fallback={<WorkspaceEmpty icon="shield" title="登录后查看授权能力" />}>
                  <Show when={state.catalogTab === "components"}><CapabilityCatalogView
                    t={language.t as (key: string) => string}
                    run={_trace()}
                    fetcher={() => listQuantCodeCapabilities(serverSDK().client)}
                  /></Show>
                  <Show when={state.catalogTab === "algorithms"}><AlgorithmCatalogView fetcher={() => listQuantCodeAlgorithms(serverSDK().client)} /></Show>
                  </Show>
                </Match>
                <Match when={state.view === "solution"}>
                  <Show when={props.nativeSessionID} fallback={<SolutionPanelView t={language.t as (key: string) => string} run={_trace()} />}>
                    {sessionID => <QuantCodeTaskReview sessionID={sessionID()} expanded />}
                  </Show>
                </Match>
                <Match when={state.view === "server-admin" && state.adminSession && platform.identity?.sshAdminStatus}>
                  <ServerAdminView status={() => platform.identity!.sshAdminStatus()}
                    disconnect={() => platform.identity!.sshAdminDisconnect()}
                    organization={async () => { await enterSshWorkspace(await platform.identity!.sshConnect({ serverId: "server-c", administrator: "organization" })) }}
                    onDisconnected={() => setState({ adminSession: undefined, view: "settings" })} />
                </Match>
                <Match when={state.view === "admin" && adminViewable()}>
                  <div class="qc-view-tabs qc-admin-tabs" role="tablist" aria-label="Admin 管理视图" onKeyDown={navigateViewTabs}>
                    <For each={[{ id: "overview" as const, label: "概览" }, { id: "tasks" as const, label: "任务" }, { id: "reports" as const, label: "报告与产物" }, { id: "deployments" as const, label: "部署" }]}>{tab => <button type="button" role="tab" aria-selected={state.adminHistory === tab.id} tabIndex={state.adminHistory === tab.id ? 0 : -1} onClick={() => setState("adminHistory", tab.id)}>{tab.label}</button>}</For>
                  </div>
                  <div class="qc-admin-workspace">
                  <Show when={state.adminHistory === "deployments"}><DeploymentPanel scope={state.historyScope} client={serverSDK().client} /></Show>
                  <Show when={state.adminHistory === "overview" && state.unifiedRuntime}>
                    <NativeTaskHistory scope={state.historyScope} ready={adminViewable()} source={organizationTasks()} organization mode="overview" />
                  </Show>
                  <Show when={state.adminHistory === "overview" && !state.unifiedRuntime}><AdminConsoleView
                    t={language.t as (key: string) => string}
                    run={_trace()}
                    sendInstruction={(content) => submitInstruction(content, "admin")}
                    onOpenGitgraph={() => setState("view", "gitgraph")}
                    onOpenHistory={(mode) => setState("adminHistory", mode)}
                    onOpenDeployments={() => setState("adminHistory", "deployments")}
                  /></Show>
                  <Show when={state.unifiedRuntime && (state.adminHistory === "tasks" || state.adminHistory === "reports")}>
                    <NativeTaskHistory scope={state.historyScope} ready={adminViewable()} source={organizationTasks()} organization
                      mode={state.adminHistory === "reports" ? "reports" : "tasks"} />
                  </Show>
                  <Show when={!state.unifiedRuntime && (state.adminHistory === "tasks" || state.adminHistory === "reports")}><RunHistoryView
                    scope={state.historyScope}
                    ready={adminViewable()}
                    mode={state.adminHistory === "reports" ? "reports" : "tasks"}
                    reconcileGroup={_group()}
                    reconcile={adminViewable() ? payload => reconcileQuantCodeReceipt(serverSDK().client, payload) : undefined}
                    fetcher={(tool, params) => readQuantCodeTool(serverSDK().client,
                      tool === "get_run_history" ? "admin_get_task_history" : state.adminHistory === "reports" ? "admin_report_history" : "admin_task_history",
                      undefined, params)}
                  /></Show>
                  </div>
                </Match>
                <Match when={state.view === "settings"}>
                  <SettingsPanel
                    skill={state.skill}
                    onSkillChange={(skill) => setState("skill", skill)}
                    skills={state.skills}
                    skillsStatus={state.skillsStatus}
                    sessionStatus={state.sessionStatus}
                    sessionRole={state.sessionRole}
                    sessionActor={state.sessionActor}
                    workspacePath={state.workspacePath}
                    serverName={serverName()}
                    serverReady={serverReady()}
                    serverTransport={serverTransport()}
                    sshT={language.t as (key: string) => string}
                    sshConnect={sshConnect()}
                    unifiedRuntime={state.unifiedRuntime}
                    sshDisconnect={sshDisconnect()}
                    sshSession={state.sshSession}
                    sshIdentities={state.sshIdentities}
                    sshIdentityError={state.sshIdentityError}
                    servers={server.list.map(item => ({ key: String(item.type === "ssh" ? `ssh:${item.host}` : item.type === "sidecar" ? item.variant === "wsl" ? `wsl:${item.distro}` : "sidecar" : item.http.url), name: item.displayName || item.http.url }))}
                    selectedServer={String(server.key)}
                    onServerChange={(key) => { server.setActive(key as never); setState("identityRevision", value => value + 1) }}
                    githubSubject={state.githubSubject}
                    onOpenGitgraph={() => setState("view", "gitgraph")}
                    importKey={platform.identity ? async () => {
                      const result = await platform.identity!.importKey({ server: String(server.key) })
                      if (result) setState("identityRevision", value => value + 1)
                      return result
                    } : undefined}
                    orgSshLogin={platform.identity?.sshConnect ? platform.identity : undefined}
                    orgSshStart={state.orgSshStart}
                    orgSshOnStarted={() => setState("orgSshStart", false)}
                    orgSshOnEnter={enterSshWorkspace}
                  />
                </Match>
              </Switch>
              </div>
            </section>
        </div>
      </main>
    </div>
  )
}

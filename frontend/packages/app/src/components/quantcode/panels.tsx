/**
 * QuantCode research workspace.
 *
 * The module-level trace store is intentionally preserved so MCP tool results,
 * HumanGate resumes, and the full-screen workspace share one source of truth.
 * Trace payloads pushed by the session-ui run_agent renderer arrive through the
 * quantcode-trace-bridge and join the same store, keeping one source of truth.
 */
import {
  For,
  Match,
  Show,
  Switch,
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  onMount,
  type JSX,
} from "solid-js"
import { createStore } from "solid-js/store"
import { Icon, type IconProps } from "@opencode-ai/ui/icon"
import { setQuantCodeTraceListener, type QuantCodeTracePayload } from "@opencode-ai/session-ui/message-part"
import { usePrompt } from "@/context/prompt"
import { useServer } from "@/context/server"
import { useServerSDK } from "@/context/server-sdk"
import { useLanguage } from "@/context/language"
import { usePlatform } from "@/context/platform"
import { showToast } from "@/utils/toast"
import { QcBigNumber, QcProgress, formatMetricValue, type MetricTone } from "./metric-cards"
import { buildResearchInstruction, buildResumeInstruction, buildRecoveryInstruction, QUANTCODE_GROUPS, type QuantCodeGroup } from "./instructions"
import { isRunAgentResult, type RunAgentResult, type TraceEvent } from "./result-contract"
import { submitQuantCodeInstruction, type QuantCodeSubmissionHandler } from "./submission"
import { FactorFlowView } from "./factor-screen"
import { NotificationsBell, NotificationsPanel, pendingNotifications } from "./notifications"
import { PitValuationView } from "./pit-screen"
import { SupplierView } from "./settings-supplier"
import { SshLoginView, type SshConnectFn, type SshIdentity } from "./ssh-login"
import { CapabilityCatalogView } from "./capability-catalog"
import { ApprovalQueue } from "./approval-queue"
import { DeploymentPanel } from "./deployment-panel"
import { KnowledgeReview } from "./knowledge-review"
import { RunHistoryView } from "./run-history"
import { MemoryQueryView } from "./memory-query"
import { SolutionPanelView } from "./solution-panel"
import { AdminConsoleView } from "./admin-console"
import { GitHubWorkspace } from "./github-workspace"
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
  type QuantCodeAlgorithm,
  type QuantCodeSkill,
} from "./api"
import { METRIC_LABELS } from "./metrics"
import "./panels.css"

const [_trace, setTrace] = createSignal<RunAgentResult | null>(null)
const [_group, setGroup] = createSignal("factor")
const [_threadHistory, setThreadHistory] = createSignal<RunAgentResult[]>([])
/** run_agent 结果所属的 opencode session；HumanGate resume 需要向它发 prompt */
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
// 桥接：接收 run_agent 工具渲染推送的 trace，处理跨会话重置（B19-03）
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
  | "factor"
  | "pit"
  | "admin"
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
          <div class="qc-empty-state">
            <span class="qc-empty-index">00</span>
            <h3>还没有执行记录</h3>
            <p>发起一次研究后，Agent、工具调用和产物会按时间顺序出现在这里。</p>
          </div>
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
  algorithms: QuantCodeAlgorithm[]
  serverName: string
  serverReady: boolean
  serverTransport: string
  /** F-05 SSH 登录视图的 i18n（quantcode.ssh.*），来自 useLanguage().t */
  sshT: (key: string) => string
  sshConnect: SshConnectFn
  sshIdentities: SshIdentity[]
  sshIdentityError: string
}): JSX.Element {
  return (
    <div class="qc-detail-body">
      <div class="qc-setting-row">
        <div>
          <span class="qc-section-label">SSH IDENTITY</span>
          <strong>{props.sessionActor}</strong> <span class="qc-status">{props.sessionRole}</span>
          <p>身份和组由服务端认证会话绑定；服务可达不代表 SSH 已认证。</p>
        </div>
        <span class="qc-connection-pill" classList={{ "is-disconnected": props.sessionStatus !== "ready" }}>
          <i /> {props.sessionStatus === "ready" ? "会话已认证" : "未认证"}
        </span>
      </div>
      <div class="qc-setting-row">
        <div>
          <span class="qc-section-label">SESSION GROUP</span>
          <strong>{props.sessionStatus === "ready" ? _group() : "未连接"}</strong>
          <span class="qc-status">{props.sessionRole}</span>
        </div>
        <span class="qc-status">{props.sessionStatus === "ready" ? "服务端绑定" : "身份接线未完成"}</span>
      </div>
      <label class="qc-field-label" for="qc-settings-skill">
        默认 Skill
      </label>
      <select
        id="qc-settings-skill"
        class="qc-select-wide"
        value={props.skill}
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
      <div class="qc-detail-section">
        <span class="qc-section-label">EXECUTION TARGET</span>
        <div class="qc-server-line">
          <span>{props.serverName}</span>
          <code>{props.serverTransport}</code>
        </div>
      </div>
      <div class="qc-detail-section">
        <span class="qc-section-label">SSH LOGIN</span>
        <Show when={props.sshIdentityError}><p role="alert">{props.sshIdentityError}</p></Show>
        <SshLoginView t={props.sshT} connect={props.sshConnect} identities={props.sshIdentities} />
      </div>
      <SupplierView algorithms={props.algorithms} />
    </div>
  )
}

export type QuantCodePanelProps = {
  onClose?: () => void
  /**
   * Root-home entry point. Session panels keep the default prompt bridge;
   * the standalone home delegates submission to the draft/session router.
   */
  onSubmitInstruction?: QuantCodeSubmissionHandler
}

export function QuantCodePanel(props: QuantCodePanelProps = {}): JSX.Element {
  const prompt = props.onSubmitInstruction ? undefined : usePrompt()
  const server = useServer()
  const serverSDK = useServerSDK()
  const language = useLanguage()
  const platform = usePlatform()
  const [state, setState] = createStore({
    view: "compose" as DetailView,
    task: "",
    skill: "",
    skills: [] as QuantCodeSkill[],
    skillsStatus: "loading" as "loading" | "ready" | "error",
    sessionStatus: "loading" as "loading" | "ready" | "error",
    sessionRole: "未连接",
    sessionActor: "未连接",
    historyScope: "",
    githubUnread: 0,
    identityRevision: 0,
    sshIdentities: [] as SshIdentity[],
    sshIdentityError: "",
    adminHistory: "tasks" as "tasks" | "reports",
    algorithms: [] as QuantCodeAlgorithm[],
    submit: "idle" as SubmitState,
    error: "",
  })
  let taskInput: HTMLTextAreaElement | undefined
  let shell: HTMLDivElement | undefined
  let stage: HTMLElement | undefined
  let fieldCanvas: HTMLCanvasElement | undefined
  let focusLens: HTMLDivElement | undefined
  let sharpBrand: HTMLDivElement | undefined
  const [notifOpen, setNotifOpen] = createSignal(false)
  const notifItems = createMemo(() => pendingNotifications(_threadHistory(), _trace()))
  /** F-09: admin 中枢仅服务端签发的 admin 角色可见。 */
  const adminViewable = createMemo(() => state.sessionStatus === "ready" && state.sessionRole === "admin")

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

  // Trace bridge: the session-ui run_agent renderer pushes results here while
  // the panel is mounted; deregister on teardown so no stale writes land.
  onMount(() => setQuantCodeTraceListener(handleQuantCodeTracePayload))
  onCleanup(() => setQuantCodeTraceListener(null))

  let skillsRequest = 0
  createEffect(() => {
    state.identityRevision
    const client = serverSDK().client
    const serverKey = String(server.key)
    let cancelled = false
    setState({ sshIdentities: [], sshIdentityError: "" })
    void client.quantcode.identity.list().then(response => {
      if (cancelled) return
      const data = response.data
      if (response.error || !data || typeof data !== "object") {
        setState("sshIdentityError", "本机身份服务不可用，请检查研究服务器连接。")
        return
      }
      if ("error" in data && typeof data.error === "string") {
        setState("sshIdentityError", data.error)
        return
      }
      if (!("identities" in data) || !Array.isArray(data.identities)
        || !data.identities.every(identity => identity && typeof identity.id === "string" && typeof identity.fingerprint === "string")) {
        setState("sshIdentityError", "本机身份服务返回格式错误。")
        return
      }
      setState("sshIdentities", data.identities as SshIdentity[])
      if (!data.identities.length) setState("sshIdentityError", "宿主尚未提供可用公钥身份，请完成本机身份桥配置。")
    }).catch(() => { if (!cancelled) setState("sshIdentityError", "读取本机身份失败，请检查研究服务器连接。") })
    onCleanup(() => { cancelled = true })
    activeThreadCacheKey = undefined
    setSessionId(undefined)
    lastResultJson = undefined
    resetQuantCodeState()
    setState({ historyScope: "", sessionStatus: "loading", sessionRole: "未连接", sessionActor: "未连接", skills: [], skill: "" })
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
        setState({ historyScope: activeThreadCacheKey ?? "", sessionStatus: "ready", sessionRole: context.role ?? "analyst", sessionActor: context.actor_id ?? "已认证身份" })
      },
      () => {
        if (cancelled) return
        activeThreadCacheKey = undefined
        resetQuantCodeState()
        setState({ sessionStatus: "error", sessionRole: "身份接线未完成", sessionActor: "未连接", skillsStatus: "error", skill: "" })
      },
    )
  })

  createEffect(() => {
    const group = _group()
    if (state.sessionStatus !== "ready") return
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

  onMount(() => {
    void listQuantCodeAlgorithms(serverSDK().client).then(
      (algorithms) => setState("algorithms", algorithms),
      () => setState("algorithms", []),
    )
  })

  const selectedSkill = createMemo(() => state.skills.find((skill) => skill.id === state.skill))
  const selectedSkillLabel = createMemo(() => {
    const skill = selectedSkill()
    if (skill) return skillLabel(skill)
    if (state.sessionStatus !== "ready") return "身份未连接"
    return state.skillsStatus === "loading" ? "正在加载 Skill 目录…" : "Skill 目录未连接"
  })
  const gateWaiting = createMemo(() => _trace()?.status === "waiting_for_human")
  const serverName = createMemo(() => server.name || "当前服务器")
  const serverReady = createMemo(() => server.ready())
  const serverTransport = createMemo(() => (server.isLocal() ? "本地 sidecar" : server.key))
  const sshConnect = createMemo(() => createLocalIdentityConnect(serverSDK().client, () => setState("identityRevision", value => value + 1)))
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
      task: state.task.trim(),
      skillLabel: selectedSkillLabel(),
    })
  }

  const submitInstruction = async (content: string, nextView: DetailView = "compose"): Promise<boolean> => {
    // Guard the shared submission path as well as the form button.  A second
    // click can otherwise arrive before Solid flushes the signal update or
    // while the requestAnimationFrame callback is still queued.
    if (state.submit === "starting") return false
    setState({ submit: "starting", error: "" })

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
    if (!state.task.trim() || !state.skill || state.sessionStatus !== "ready" || state.submit === "starting") return
    submitInstruction(instruction())
  }

  /**
   * HumanGate 审批 → resume：向 run_agent 结果所属的 session 通过 server SDK
   * promptAsync 发结构化短指令（立即返回，不阻塞整轮 agent 回合），由 Agent 调
   * run_agent(resume) 工具恢复执行。day5 P0-4 的实现，接到 lens 侧 GatePanel 按钮。
   */
  const sendGateDecision = (threadId: string, decision: GateDecision) => {
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
    { id: "factor", label: "因子评估", icon: "sliders" },
    { id: "pit", label: "PIT 估值", icon: "file-tree" },
    { id: "gate", label: "HumanGate", icon: "review" },
    { id: "memory", label: "Memory", icon: "brain" },
    { id: "capabilities", label: "能力目录", icon: "mcp" },
    { id: "solution", label: "方案", icon: "prompt" },
  ]
  /** F-09：admin 专属视图（Admin 中枢 / GitGraph），仅 admin 角色可见导航项 */
  const adminNavItems: { id: DetailView; label: string; icon: IconProps["name"] }[] = [
    { id: "admin", label: "Admin 中枢", icon: "shield" },
    { id: "gitgraph", label: "GitGraph", icon: "branch" },
  ]

  return (
    <div ref={shell} class="qc-shell" data-quantcode-workspace="true">
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
          </button>
          <Show when={props.onClose}>
            <button
              type="button"
              class="qc-rail-button"
              aria-label="关闭 QuantCode 工作区"
              title="关闭 QuantCode 工作区"
              onClick={() => props.onClose?.()}
            >
              <Icon name="close" size="normal" />
            </button>
          </Show>
        </div>
      </aside>

      <main class="qc-main">
        <header class="qc-identity-bar">
          <div class="qc-identity">
            <span>{state.sessionActor}</span>
            <i />
            <strong>{state.sessionStatus === "ready" ? _group() : "未连接"}</strong>
          </div>
          <div class="qc-environment">
            <span>{serverName()}</span>
            <i />
            <span class="qc-connected" classList={{ "is-disconnected": !serverReady() }}>
              <b /> {serverReady() ? "已连接" : "未连接"}
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
            <div class="qc-compose-grid">
              <div class="qc-compose-left">
                <div class="qc-composer" classList={{ "has-error": state.submit === "error" }}>
                  <label for="qc-task">今天研究什么？</label>
                  <textarea
                    id="qc-task"
                    ref={taskInput}
                    value={state.task}
                    rows={2}
                    placeholder="描述任务，或输入 / 调用 Skill."
                    onInput={(event) => {
                      setState({ task: event.currentTarget.value, submit: "idle", error: "" })
                    }}
                    onKeyDown={(event) => {
                      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submitResearch()
                    }}
                  />
                  <div class="qc-composer-actions">
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
                    <div class="qc-submit-cluster">
                      <span>⌘ ENTER</span>
                      <button
                        type="button"
                        disabled={
                          !state.task.trim() || !state.skill || state.sessionStatus !== "ready" || state.submit === "starting"
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
                    <Match when={state.submit === "submitted"}>
                      <span class="is-success">研究已提交到 {_group()} Multi-Agent 流。</span>
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
          <Show when={state.view !== "compose"}>
            <section class="qc-detail-panel" aria-label="QuantCode 详情">
              <div class="qc-detail-header">
                <div>
                  <span>QUANTCODE / {state.view.toUpperCase()}</span>
                  <h2>
                    {state.view === "activity"
                      ? "执行记录"
                      : state.view === "factor"
                        ? "因子评估"
                        : state.view === "pit"
                          ? "PIT 估值"
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
              <Switch>
                <Match when={state.view === "activity"}>
                  <ActivityPanel onUseTask={focusComposer} />
                  <RunHistoryView
                    scope={state.historyScope}
                    ready={state.sessionStatus === "ready"}
                    onRecover={(threadId, checkpointId) => submitInstruction(buildRecoveryInstruction(threadId, checkpointId), "activity")}
                    reconcileGroup={_group()}
                    reconcile={state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)
                      ? payload => reconcileQuantCodeReceipt(serverSDK().client, payload) : undefined}
                    fetcher={(tool, params) => readQuantCodeTool(serverSDK().client, tool, undefined, params)}
                  />
                </Match>
                <Match when={state.view === "factor"}>
                  <FactorFlowView run={_trace()} />
                </Match>
                <Match when={state.view === "pit"}>
                  <PitValuationView run={_trace()} />
                </Match>
                <Match when={state.view === "gate"}>
                  <GatePanel role={state.sessionRole} onResume={sendGateDecision} />
                  <Show when={state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)}>
                    <ApprovalQueue scope={state.historyScope}
                      fetcher={(cursor) => readQuantCodeTool(serverSDK().client, "list_pending_gates", undefined, { cursor, limit: 20 })}
                      decide={(threadId, checkpointId, gateId, decision) => submitInstruction(buildResumeInstruction(threadId, decision, gateId, checkpointId), "activity")} />
                  </Show>
                </Match>
                <Match when={state.view === "memory"}>
                  <MemoryQueryView
                    t={language.t as (key: string) => string}
                    fetcher={(query) => searchQuantCodeMemory(serverSDK().client, query)}
                  />
                  <Show when={state.sessionStatus === "ready" && ["approver", "admin"].includes(state.sessionRole)}>
                    <KnowledgeReview scope={state.historyScope}
                      fetcher={() => readQuantCodeTool(serverSDK().client, "list_distill_candidates")}
                      review={(name, action, digest, replacement) => reviewQuantCodeCandidate(serverSDK().client, name, action, digest, replacement)} />
                  </Show>
                </Match>
                <Match when={state.view === "capabilities"}>
                  <CapabilityCatalogView
                    t={language.t as (key: string) => string}
                    run={_trace()}
                    fetcher={() => listQuantCodeCapabilities(serverSDK().client)}
                  />
                </Match>
                <Match when={state.view === "solution"}>
                  <SolutionPanelView t={language.t as (key: string) => string} run={_trace()} />
                </Match>
                <Match when={state.view === "admin" && adminViewable()}>
                  <DeploymentPanel scope={state.historyScope} client={serverSDK().client} />
                  <AdminConsoleView
                    t={language.t as (key: string) => string}
                    run={_trace()}
                    sendInstruction={(content) => submitInstruction(content, "admin")}
                    onOpenGitgraph={() => setState("view", "gitgraph")}
                    onOpenHistory={(mode) => setState("adminHistory", mode)}
                  />
                  <RunHistoryView
                    scope={state.historyScope}
                    ready={adminViewable()}
                    mode={state.adminHistory}
                    reconcileGroup={_group()}
                    reconcile={adminViewable() ? payload => reconcileQuantCodeReceipt(serverSDK().client, payload) : undefined}
                    fetcher={(tool, params) => readQuantCodeTool(serverSDK().client,
                      tool === "get_run_history" ? "admin_get_task_history" : state.adminHistory === "reports" ? "admin_report_history" : "admin_task_history",
                      undefined, params)}
                  />
                </Match>
                <Match when={state.view === "gitgraph" && state.sessionStatus === "ready"}>
                  <p class="qc-detail-body">仓库、分支和持久更新通知显示于工作台。</p>
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
                    algorithms={state.algorithms}
                    serverName={serverName()}
                    serverReady={serverReady()}
                    serverTransport={serverTransport()}
                    sshT={language.t as (key: string) => string}
                    sshConnect={sshConnect()}
                    sshIdentities={state.sshIdentities}
                    sshIdentityError={state.sshIdentityError}
                  />
                </Match>
              </Switch>
            </section>
          </Show>
        </div>
      </main>
    </div>
  )
}

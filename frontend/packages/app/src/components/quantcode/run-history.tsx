import { For, Show, createEffect, createMemo, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { Icon } from "@opencode-ai/ui/icon"
import { RefreshAction, WorkspaceEmpty, runStatusLabel } from "./workspace-ui"
import { ReceiptReview } from "./receipt-review"
import type { ReceiptReconciliation } from "./api"
import type { QuantCodeLegacyDetail } from "@opencode-ai/sdk/v2"
import { LegacyRecovery, type LegacyRecoveryRequest, type LegacyApprovalRequest } from "./legacy-recovery"

type Run = {
  thread_id: string
  checkpoint_id: string
  timestamp?: string | null
  task: string
  status: string
  group?: string | null
  actor_id?: string | null
  engine?: "legacy-python"
}
type Detail = Run & {
  read_only: true
  can_resume?: boolean
  pending_approval?: boolean
  recovery_block_reason?: string
  recovery?: QuantCodeLegacyDetail["recovery"]
  gate?: unknown
  unresolved_operations?: { call_id: string; digest: string; receipt_status: string; tool?: string }[]
  receipt_reviews?: { review_id: string; call_id: string; reviewer: string; reviewed_at: string; decision: string; evidence_ref: string; note: string; result_digest?: string }[]
  receipt_review_error?: string
  checkpoints: string[]
  messages: { type: string; content: unknown }[]
  artifacts?: unknown[]
  output_data?: unknown
  timeline_error?: string
  timeline?: {
    events: { event_id?: string; type: string; timestamp?: number; node?: string; data?: unknown }[]
    next_cursor: number
    exists: boolean
    has_more: boolean
    damaged_lines: number
  }
}

export function RunHistoryView(props: {
  scope: string
  ready: boolean
  onNew?: () => void
  mode?: "tasks" | "reports"
  legacy?: boolean
  recoverLegacy?: LegacyRecoveryRequest
  requestLegacyApproval?: LegacyApprovalRequest
  onRecover?: (threadId: string, checkpointId: string) => Promise<boolean>
  reconcile?: (payload: ReceiptReconciliation) => Promise<unknown>
  reconcileGroup?: string
  fetcher: (tool: "list_run_history" | "get_run_history", params: {
    cursor?: string; thread_id?: string; checkpoint_id?: string; trace_cursor?: number
  }) => Promise<unknown>
}) {
  const [state, setState] = createStore({
    runs: [] as Run[], cursor: undefined as string | undefined,
    detail: undefined as Detail | undefined, loading: false, error: "", recovering: false, query: "", filter: "all",
  })
  let revision = 0
  const visible = createMemo(() => state.runs.filter(run =>
    (state.filter === "all" || run.status === state.filter) &&
    `${run.task} ${run.thread_id}`.toLowerCase().includes(state.query.trim().toLowerCase())))
  onCleanup(() => revision++)

  async function load(params: { cursor?: string; thread_id?: string; checkpoint_id?: string; trace_cursor?: number } = {}) {
    const current = ++revision
    setState({ loading: true, error: "", recovering: false })
    try {
      const data = await props.fetcher(params.thread_id ? "get_run_history" : "list_run_history", params)
      if (revision !== current) return
      if (!data || typeof data !== "object") throw new Error("历史服务返回格式错误")
      if ("error" in data) throw new Error(String(data.error))
      if (props.legacy && (!("engine" in data) || data.engine !== "legacy-python")) throw new Error("归档任务来源校验失败。")
      if (params.thread_id) {
        if (!("read_only" in data) || data.read_only !== true || !("messages" in data) || !Array.isArray(data.messages)
          || !("checkpoints" in data) || !Array.isArray(data.checkpoints)) {
          throw new Error("历史详情返回格式错误")
        }
        const detail = data as Detail
        if (props.legacy && (typeof detail.can_resume !== "boolean" || !detail.recovery || typeof detail.recovery.available !== "boolean"
          || !Array.isArray(detail.recovery.blockers))) throw new Error("归档任务恢复状态返回格式错误。")
        if (detail.timeline && (!Array.isArray(detail.timeline.events) || !detail.timeline.events.every(event => event && typeof event.type === "string")
          || !Number.isSafeInteger(detail.timeline.next_cursor) || detail.timeline.next_cursor < 0)) throw new Error("执行时间线返回格式错误")
        if (params.trace_cursor !== undefined && state.detail?.timeline && detail.timeline) {
          detail.timeline = { ...detail.timeline,
            events: [...state.detail.timeline.events, ...detail.timeline.events],
            damaged_lines: state.detail.timeline.damaged_lines + detail.timeline.damaged_lines,
          }
        }
        setState("detail", detail)
        return
      }
      if (!("runs" in data) || !Array.isArray(data.runs)) throw new Error("历史列表返回格式错误")
      if (!data.runs.every(run => run && typeof run.thread_id === "string" && typeof run.checkpoint_id === "string")) {
        throw new Error("历史列表包含无效任务")
      }
      const runs = data.runs as Run[]
      setState({
        runs: params.cursor ? [...state.runs, ...runs] : runs,
        cursor: "next_cursor" in data && typeof data.next_cursor === "string" ? data.next_cursor : undefined,
      })
    } catch (error) {
      if (revision === current) setState("error", error instanceof Error ? error.message : "历史读取失败")
    } finally {
      if (revision === current) setState("loading", false)
    }
  }

  createEffect(() => {
    props.scope
    props.mode
    props.legacy
    const ready = props.ready
    revision++
    setState({ runs: [], detail: undefined, cursor: undefined, error: "", loading: false, query: "", filter: "all" })
    if (ready) void load()
  })

  return <section class="qc-detail-body qc-history" aria-label={props.legacy ? "归档任务" : "服务端研究历史"}>
    <div class="qc-view-toolbar">
      <h3>{props.legacy ? "归档任务" : props.mode === "reports" ? "组织报告与产物" : props.mode === "tasks" ? "组织任务管理" : "服务端研究历史"}</h3>
      <span class="qc-count">{state.runs.length}{state.cursor ? "+" : ""} 个任务</span>
      <RefreshAction label="刷新历史" disabled={!props.ready || state.loading} onClick={() => void load()} />
    </div>
    <div class="qc-filter-bar">
      <label class="qc-search-field"><Icon name="magnifying-glass" /><input type="search" aria-label="搜索执行记录" placeholder="搜索任务或编号" value={state.query} onInput={e => setState("query", e.currentTarget.value)} /></label>
      <select aria-label="任务状态" value={state.filter} onChange={e => setState("filter", e.currentTarget.value)}><option value="all">全部状态</option><For each={[...new Set(state.runs.map(run => run.status))]}>{status => <option value={status}>{runStatusLabel(status)}</option>}</For></select>
    </div>
      <Show when={!props.ready}><WorkspaceEmpty icon="shield" title="登录后查看执行记录" description="当前工作区尚未认证。" /></Show>
      <Show when={state.loading}><p class="qc-loading" role="status">正在读取执行记录…</p></Show>
      <Show when={state.error}><p role="alert">{state.error}</p></Show>
      <Show when={props.ready && !state.loading && !state.error && !state.runs.length}>
        <WorkspaceEmpty icon="checklist" title="暂无执行记录" description="当前工作区还没有已保存的任务。">
          <Show when={props.onNew}><button type="button" class="qc-button qc-button-primary" onClick={props.onNew}><Icon name="plus" size="small" />新建研究</button></Show>
        </WorkspaceEmpty>
      </Show>
      <Show when={state.runs.length > 0 && !visible().length}><WorkspaceEmpty icon="magnifying-glass" title="没有匹配的任务" /></Show>
    <div class="qc-history-layout" classList={{ "has-detail": !!state.detail }}>
    <div class="qc-history-list">
      <For each={visible()}>{run => <button type="button" class="qc-history-row" aria-pressed={state.detail?.thread_id === run.thread_id} disabled={state.loading}
        onClick={() => void load({ thread_id: run.thread_id })}>
        <Icon name="task" /><span class="qc-history-copy"><strong>{run.task || run.thread_id}</strong><small>{run.timestamp || run.thread_id}</small></span>
        <span class={`qc-status qc-status-${run.status}`}>{runStatusLabel(run.status)}</span><Icon name="chevron-right" size="small" />
      </button>}</For>
      <Show when={state.cursor}><button type="button" disabled={state.loading}
        onClick={() => void load({ cursor: state.cursor })}>加载更多</button></Show>
    </div>
    <Show when={state.detail}>{detail => <div class="qc-history-detail" aria-label="历史详情">
      <div class="qc-view-toolbar"><span class={`qc-status qc-status-${detail().status}`}>{runStatusLabel(detail().status)}</span><button type="button" class="qc-icon-action" aria-label="关闭历史详情" title="关闭历史详情" onClick={() => { revision++; setState({ detail: undefined, loading: false, recovering: false }) }}><Icon name="close" /></button></div>
      <h3>{detail().task || detail().thread_id}</h3>
      <p>只读回放 · {detail().timestamp}</p>
      <Show when={detail().engine}><p class="qc-muted">历史来源：归档记录 · {detail().actor_id} · {detail().group}</p></Show>
      <Show when={detail().pending_approval}><p>该任务有待审批中断，需通过 HumanGate 明确处理，不能用普通恢复绕过。</p></Show>
      <Show when={detail().recovery_block_reason}><p role="alert">无法恢复：{detail().recovery_block_reason}</p></Show>
      <Show when={detail().recovery}>{recovery => <details class="qc-detail-section">
        <summary>检查点来源与恢复限制</summary>
        <p>来源状态：{({ missing: "未登记", registered: "已登记", changed: "已变化" })[recovery().provenance]}</p>
        <p>来源版本：{recovery().executor_version ?? "未登记"} · 数据格式版本：{recovery().serializer_version}</p>
        <p>最新检查点：<code>{recovery().latest_checkpoint_id}</code></p>
        <p style={{ "overflow-wrap": "anywhere" }}>检查点摘要：<code>{recovery().checkpoint_digest}</code></p>
        <Show when={recovery().provenance_digest}><p style={{ "overflow-wrap": "anywhere" }}>来源摘要：<code>{recovery().provenance_digest}</code></p></Show>
        <For each={recovery().blockers}>{blocker => <p>{blocker.message}</p>}</For>
        <Show when={recovery().usage}>{usage => <div class="qc-native-usage">
          <span>已用 {usage().used_tokens.toLocaleString()} tokens</span>
          <span>预留 {usage().reserved_tokens.toLocaleString()} tokens</span>
          <span>待核对请求 {usage().unconfirmed_requests}</span>
        </div>}</Show>
      </details>}</Show>
      <Show when={props.legacy && props.recoverLegacy && props.requestLegacyApproval && detail().recovery}><LegacyRecovery
        detail={{ ...detail(), recovery: detail().recovery!, can_resume: detail().can_resume === true, pending_approval: detail().pending_approval === true }}
        resume={props.recoverLegacy!} requestApproval={props.requestLegacyApproval!} onChanged={() => void load({ thread_id: detail().thread_id })} /></Show>
      <Show when={detail().unresolved_operations?.length}>
        <h4>需要核对的工具调用</h4>
        <p>缺少完成回执不代表操作没有发生。请结合工具输出、外部平台记录和任务时间线核对，避免另起任务重复提交同一操作。</p>
        <For each={detail().unresolved_operations}>{operation => <article>
          <strong>{operation.tool || "工具名称请查阅对应检查点"}</strong>
          <p>调用：<code>{operation.call_id}</code> · 回执：{operation.receipt_status}</p>
          <p style={{ "overflow-wrap": "anywhere" }}>核对摘要：{operation.digest}</p>
          <Show when={!props.legacy && detail().group === props.reconcileGroup && props.reconcile}>{reconcile => <ReceiptReview
            threadId={detail().thread_id} checkpointId={detail().checkpoint_id} callId={operation.call_id} digest={operation.digest}
            reconcile={reconcile()} onReviewed={() => void load({ thread_id: detail().thread_id })}
          />}</Show>
        </article>}</For>
      </Show>
      <Show when={!props.legacy && detail().can_resume && props.onRecover}>
        <p>恢复会继续原任务的执行。后端会重新校验身份及最新检查点，不会回退到历史版本。</p>
        <button type="button" disabled={state.loading || state.recovering} onClick={async () => {
          const current = revision
          setState({ recovering: true, error: "" })
          try {
            if (!await props.onRecover?.(detail().thread_id, detail().checkpoint_id)) throw new Error("恢复请求未提交，请检查任务连接后重试。")
          } catch (error) {
            if (current === revision) setState({ recovering: false, error: error instanceof Error ? error.message : "恢复请求提交失败。" })
          }
        }}>{state.recovering ? "已请求恢复，请查看当前任务反馈" : "从最新检查点恢复任务"}</button>
      </Show>
      <Show when={detail().receipt_review_error}><p role="alert">{detail().receipt_review_error}</p></Show>
      <Show when={detail().receipt_reviews?.length}>
        <h4>已提交的外部结果核对记录</h4>
        <p>以下为人工核对结论，覆盖本任务的审核历史；保存审核不代表任务已经恢复执行。</p>
        <For each={detail().receipt_reviews}>{review => <article class="qc-detail-section">
          <strong>{review.decision === "confirmed_completed" ? "确认已完成，补回原结果" : "确认未执行，允许后续重试"}</strong>
          <p>{review.reviewer} · {review.reviewed_at}</p>
          <p>调用：<code>{review.call_id}</code> · 审核：<code>{review.review_id}</code></p>
          <p style={{ "overflow-wrap": "anywhere" }}>证据引用：{review.evidence_ref}</p>
          <p style={{ "white-space": "pre-wrap" }}>{review.note}</p>
          <Show when={review.result_digest}><p style={{ "overflow-wrap": "anywhere" }}>结果摘要：{review.result_digest}</p></Show>
        </article>}</For>
      </Show>
      <label>检查点 <select value={detail().checkpoint_id} disabled={state.loading} onChange={event =>
        void load({ thread_id: detail().thread_id, checkpoint_id: event.currentTarget.value })}>
        <For each={detail().checkpoints}>{id => <option value={id}>{id}</option>}</For>
      </select></label>
      <For each={detail().messages}>{message => <article>
        <h4>{message.type === "ai" ? "Agent" : message.type === "human" ? "任务" : "工具"}</h4>
        <pre style={{ "white-space": "pre-wrap", "overflow-wrap": "anywhere" }}>{typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2)}</pre>
      </article>}</For>
      <Show when={detail().output_data}><h4>结果</h4><pre style={{ "white-space": "pre-wrap", "overflow-wrap": "anywhere" }}>{JSON.stringify(detail().output_data, null, 2)}</pre></Show>
      <Show when={detail().artifacts?.length}><h4>产物</h4><pre style={{ "white-space": "pre-wrap", "overflow-wrap": "anywhere" }}>{JSON.stringify(detail().artifacts, null, 2)}</pre></Show>
      <h4>任务执行时间线</h4>
      <Show when={detail().timeline_error}><p role="status">{detail().timeline_error}</p></Show>
      <p>包含本任务各次运行和恢复的事件，不限于上方选择的检查点。</p>
      <Show when={!detail().timeline?.exists}><p>此历史任务没有持久事件文件，仍可查看已保存的检查点消息。</p></Show>
      <Show when={detail().timeline?.damaged_lines}><p role="alert">检测到 {detail().timeline?.damaged_lines} 条损坏事件，时间线存在缺口。</p></Show>
      <For each={detail().timeline?.events}>{event => <article>
        <h4>{event.type} {event.node ? `· ${event.node}` : ""}</h4>
        <Show when={typeof event.timestamp === "number" && Number.isFinite(event.timestamp)}><small>{new Date(event.timestamp! * 1000).toLocaleString()}</small></Show>
        <pre style={{ "white-space": "pre-wrap", "overflow-wrap": "anywhere" }}>{JSON.stringify(event.data, null, 2)}</pre>
      </article>}</For>
      <Show when={detail().timeline?.has_more}><button type="button" disabled={state.loading} onClick={() => void load({
        thread_id: detail().thread_id, checkpoint_id: detail().checkpoint_id, trace_cursor: detail().timeline?.next_cursor,
      })}>加载更多执行事件</button></Show>
    </div>}</Show>
    </div>
  </section>
}

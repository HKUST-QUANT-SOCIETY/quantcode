import { For, Show, createEffect, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { ReceiptReview } from "./receipt-review"
import type { ReceiptReconciliation } from "./api"

type Run = {
  thread_id: string
  checkpoint_id: string
  timestamp?: string
  task: string
  status: string
  group?: string
}
type Detail = Run & {
  read_only: true
  can_resume?: boolean
  pending_approval?: boolean
  recovery_block_reason?: string
  unresolved_operations?: { call_id: string; digest: string; receipt_status: string; tool?: string }[]
  receipt_reviews?: { review_id: string; call_id: string; reviewer: string; reviewed_at: string; decision: string; evidence_ref: string; note: string; result_digest?: string }[]
  receipt_review_error?: string
  checkpoints: string[]
  messages: { type: string; content: unknown }[]
  artifacts?: unknown[]
  output_data?: unknown
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
  mode?: "tasks" | "reports"
  onRecover?: (threadId: string, checkpointId: string) => Promise<boolean>
  reconcile?: (payload: ReceiptReconciliation) => Promise<unknown>
  reconcileGroup?: string
  fetcher: (tool: "list_run_history" | "get_run_history", params: {
    cursor?: string; thread_id?: string; checkpoint_id?: string; trace_cursor?: number
  }) => Promise<unknown>
}) {
  const [state, setState] = createStore({
    runs: [] as Run[], cursor: undefined as string | undefined,
    detail: undefined as Detail | undefined, loading: false, error: "", recovering: false,
  })
  let revision = 0
  onCleanup(() => revision++)

  async function load(params: { cursor?: string; thread_id?: string; checkpoint_id?: string; trace_cursor?: number } = {}) {
    const current = ++revision
    setState({ loading: true, error: "", recovering: false })
    try {
      const data = await props.fetcher(params.thread_id ? "get_run_history" : "list_run_history", params)
      if (revision !== current) return
      if (!data || typeof data !== "object") throw new Error("历史服务返回格式错误")
      if ("error" in data) throw new Error(String(data.error))
      if (params.thread_id) {
        if (!("read_only" in data) || data.read_only !== true || !("messages" in data) || !Array.isArray(data.messages)
          || !("checkpoints" in data) || !Array.isArray(data.checkpoints)) {
          throw new Error("历史详情返回格式错误")
        }
        const detail = data as Detail
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
    const ready = props.ready
    revision++
    setState({ runs: [], detail: undefined, cursor: undefined, error: "", loading: false })
    if (ready) void load()
  })

  return <section class="qc-detail-body" aria-label="服务端研究历史">
    <div class="qc-detail-section">
      <h3>{props.mode === "reports" ? "组织报告与产物" : props.mode === "tasks" ? "组织任务管理" : "服务端研究历史"}</h3>
      <p>{props.mode ? "组织视图，仅 Admin 可读，跨组读取留有审计记录。" : "记录保存在当前服务器，按人员和工作区隔离。"}查看历史不会重新执行任务。</p>
      <button type="button" disabled={!props.ready || state.loading} onClick={() => void load()}>刷新历史</button>
      <Show when={!props.ready}><p>请先连接已认证的工作区。</p></Show>
      <Show when={state.loading}><p role="status">正在读取…</p></Show>
      <Show when={state.error}><p role="alert">{state.error}</p></Show>
      <Show when={props.ready && !state.loading && !state.error && !state.runs.length}><p>当前工作区还没有已保存的任务。</p></Show>
      <For each={state.runs}>{run => <button type="button" class="qc-recent-row" disabled={state.loading}
        onClick={() => void load({ thread_id: run.thread_id })}>
        <span class="qc-recent-copy"><strong>{run.task || run.thread_id}</strong><small>{run.timestamp}</small></span>
        <span>{run.status === "completed" ? "已完成" : "已保存检查点"}</span>
      </button>}</For>
      <Show when={state.cursor}><button type="button" disabled={state.loading}
        onClick={() => void load({ cursor: state.cursor })}>加载更多</button></Show>
    </div>
    <Show when={state.detail}>{detail => <div class="qc-detail-section" aria-label="历史详情">
      <h3>{detail().task || detail().thread_id}</h3>
      <p>只读回放 · {detail().timestamp}</p>
      <Show when={detail().pending_approval}><p>该任务有待审批中断，需通过 HumanGate 明确处理，不能用普通恢复绕过。</p></Show>
      <Show when={detail().recovery_block_reason}><p role="alert">无法恢复：{detail().recovery_block_reason}</p></Show>
      <Show when={detail().unresolved_operations?.length}>
        <h4>需要核对的工具调用</h4>
        <p>缺少完成回执不代表操作没有发生。请结合工具输出、外部平台记录和任务时间线核对，避免另起任务重复提交同一操作。</p>
        <For each={detail().unresolved_operations}>{operation => <article>
          <strong>{operation.tool || "工具名称请查阅对应检查点"}</strong>
          <p>调用：<code>{operation.call_id}</code> · 回执：{operation.receipt_status}</p>
          <p style={{ "overflow-wrap": "anywhere" }}>核对摘要：{operation.digest}</p>
          <Show when={detail().group === props.reconcileGroup && props.reconcile}>{reconcile => <ReceiptReview
            threadId={detail().thread_id} checkpointId={detail().checkpoint_id} callId={operation.call_id} digest={operation.digest}
            reconcile={reconcile()} onReviewed={() => void load({ thread_id: detail().thread_id })}
          />}</Show>
        </article>}</For>
      </Show>
      <Show when={detail().can_resume && props.onRecover}>
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
  </section>
}

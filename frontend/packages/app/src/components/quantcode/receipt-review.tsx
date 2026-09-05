import { Show, createEffect, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import type { ReceiptReconciliation } from "./api"

export function ReceiptReview(props: {
  threadId: string; checkpointId: string; callId: string; digest: string
  reconcile: (payload: ReceiptReconciliation) => Promise<unknown>
  onReviewed: () => void
}) {
  const [state, setState] = createStore({ decision: "confirmed_completed" as ReceiptReconciliation["decision"], evidence: "", note: "", result: "", confirmed: false, busy: false, error: "" })
  let revision = 0
  onCleanup(() => revision++)
  createEffect(() => {
    props.threadId; props.checkpointId; props.callId; props.digest
    revision++
    setState({ decision: "confirmed_completed", evidence: "", note: "", result: "", confirmed: false, busy: false, error: "" })
  })
  async function submit() {
    if (state.busy || !state.confirmed || !state.evidence.trim() || !state.note.trim()) return
    const current = revision
    setState({ busy: true, error: "" })
    try {
      const payload: ReceiptReconciliation = {
        thread_id: props.threadId, checkpoint_id: props.checkpointId, call_id: props.callId, expected_digest: props.digest,
        decision: state.decision, evidence_ref: state.evidence.trim(), note: state.note.trim(),
      }
      if (state.decision === "confirmed_completed") {
        try { payload.result = JSON.parse(state.result) }
        catch { throw new Error("请填写已核验的原始工具结果，格式须为有效 JSON。") }
      }
      const response = await props.reconcile(payload)
      if (current !== revision) return
      if (!response || typeof response !== "object" || !("execution_started" in response) || response.execution_started !== false || !("review" in response)) {
        throw new Error(response && typeof response === "object" && "error" in response ? String(response.error) : "核对结果未确认，请刷新历史。")
      }
      props.onReviewed()
    } catch (error) { if (current === revision) setState("error", error instanceof Error ? error.message : "核对提交失败") }
    finally { if (current === revision) setState("busy", false) }
  }
  return <details class="qc-detail-section">
    <summary>审核外部执行结果</summary>
    <p>先核对外部平台和原始产物，再提交结论。此操作保留原回执与审核记录，不会启动任务。</p>
    <form onSubmit={event => { event.preventDefault(); void submit() }}>
      <fieldset disabled={state.busy}>
        <label>核对结论<select value={state.decision} onChange={event => setState({ decision: event.currentTarget.value as ReceiptReconciliation["decision"], confirmed: false })}>
          <option value="confirmed_completed">已完成，补回原始结果</option>
          <option value="confirmed_not_executed">确认未执行，允许后续重试</option>
        </select></label>
        <label>外部证据引用<input required maxLength={2000} value={state.evidence} onInput={event => setState({ evidence: event.currentTarget.value, confirmed: false })} /></label>
        <label>核对说明<textarea required maxLength={4000} value={state.note} onInput={event => setState({ note: event.currentTarget.value, confirmed: false })} /></label>
        <Show when={state.decision === "confirmed_completed"}><label>原始工具结果（JSON）<textarea required value={state.result} onInput={event => setState({ result: event.currentTarget.value, confirmed: false })} /></label></Show>
        <label><input type="checkbox" checked={state.confirmed} onChange={event => setState("confirmed", event.currentTarget.checked)} />我已核对外部执行结果，结论与所填证据一致。</label>
        <button type="submit" disabled={!state.confirmed || !state.evidence.trim() || !state.note.trim()}>保存审核记录</button>
      </fieldset>
      <Show when={state.error}><p role="alert">{state.error}</p></Show>
    </form>
  </details>
}

import { Show, createEffect, createUniqueId, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { Button } from "@opencode-ai/ui/button"
import type { OpencodeClient, QuantCodeBudgetReviewState } from "@opencode-ai/sdk/v2"
import { useSDK } from "@/context/sdk"

export function BudgetRequestReview(props: { sessionID: string; client?: OpencodeClient; request: QuantCodeBudgetReviewState["requests"][number]; refresh: () => Promise<unknown> }) {
  const sdk = props.client ? undefined : useSDK()
  const client = () => props.client ?? sdk!().client
  const id = createUniqueId()
  const [state, setState] = createStore({ input: "", output: "", total: "", cost: "", evidence: "", note: "", stopped: false,
    busy: false, saved: false, error: "" })
  createEffect(on(() => props.request.reservation_digest, () => setState({ input: "", output: "", total: "", cost: "",
    evidence: "", note: "", stopped: false, saved: false, error: "" })))
  const abort = new AbortController()
  onCleanup(() => abort.abort())
  const reviewable = () => ["ended", "process_missing"].includes(props.request.status)
  const submit = async (decision: "usage_confirmed" | "confirmed_not_executed") => {
    if (!reviewable() || state.busy || !state.stopped || !state.evidence.trim() || !state.note.trim()) return
    if (decision === "usage_confirmed" && [state.input, state.output, state.total].some(value => !/^\d+$/.test(value))) {
      setState("error", "请完整填写供应商回执中的输入、输出和总用量。")
      return
    }
    setState({ busy: true, error: "" })
    try {
      const result = await client().quantcode.budget.review({ sessionID: props.sessionID,
        quantCodeBudgetReview: { request_id: props.request.request_id, expected_digest: props.request.reservation_digest,
          request_stopped: true, decision, evidence_ref: state.evidence.trim(), note: state.note.trim(),
          ...(decision === "usage_confirmed" ? { receipt: { input_tokens: Number(state.input), output_tokens: Number(state.output),
            tokens: Number(state.total), cost: state.cost.trim() ? Number(state.cost) : null } } : {}),
        },
      }, { signal: abort.signal, throwOnError: false })
      if (abort.signal.aborted) return
      if (result.error || !result.data) throw new Error(result.error?.message ?? "用量核对未保存。")
      setState("saved", true)
      await props.refresh()
    } catch (error) {
      if (!abort.signal.aborted) setState("error", error instanceof Error ? error.message : "核对失败，请刷新当前记录。")
    } finally { if (!abort.signal.aborted) setState("busy", false) }
  }
  return <details class="qc-budget-review">
    <summary>{props.request.model} · 预留 {props.request.reserved_tokens.toLocaleString()} tokens · {reviewable() ? "用量待核对" : "等待请求结束"}</summary>
    <Show when={reviewable()} fallback={<p>请求尚未确认结束，预留额度继续保留。</p>}>
      <Show when={!state.saved} fallback={<p role="status">实际用量已记录，未重新发起模型请求。</p>}>
        <form onSubmit={event => { event.preventDefault(); void submit("usage_confirmed") }}>
          <p>审批员或 Admin 可依据供应商记录补齐用量。预留额度是估计值，不能直接当作实际账单。</p>
          <div class="qc-budget-fields">
            <label for={`${id}-input`}>输入 tokens<input id={`${id}-input`} type="number" min="0" step="1" value={state.input} disabled={state.busy} onInput={event => setState("input", event.currentTarget.value)} /></label>
            <label for={`${id}-output`}>输出 tokens<input id={`${id}-output`} type="number" min="0" step="1" value={state.output} disabled={state.busy} onInput={event => setState("output", event.currentTarget.value)} /></label>
            <label for={`${id}-total`}>总 tokens<input id={`${id}-total`} type="number" min="0" step="1" value={state.total} disabled={state.busy} onInput={event => setState("total", event.currentTarget.value)} /></label>
            <label for={`${id}-cost`}>费用（未知留空）<input id={`${id}-cost`} type="number" min="0" step="any" value={state.cost} disabled={state.busy} onInput={event => setState("cost", event.currentTarget.value)} /></label>
          </div>
          <label for={`${id}-evidence`}>供应商回执或日志位置</label>
          <input id={`${id}-evidence`} required maxLength={2000} value={state.evidence} disabled={state.busy} onInput={event => setState("evidence", event.currentTarget.value)} />
          <label for={`${id}-note`}>核对说明</label>
          <textarea id={`${id}-note`} required maxLength={4000} value={state.note} disabled={state.busy} onInput={event => setState("note", event.currentTarget.value)} />
          <label class="qc-recovery-confirm"><input type="checkbox" checked={state.stopped} disabled={state.busy} onChange={event => setState("stopped", event.currentTarget.checked)} />已核对原模型请求停止</label>
          <Show when={state.error}><p role="alert" class="qc-task-review-error">{state.error}</p></Show>
          <div class="qc-task-review-actions">
            <Button type="button" disabled={state.busy || !state.stopped || !state.note.trim() || !state.evidence.trim()} onClick={() => void submit("confirmed_not_executed")}>确认请求未执行</Button>
            <Button type="submit" disabled={state.busy || !state.stopped || !state.note.trim() || !state.evidence.trim()}>{state.busy ? "正在保存…" : "保存实际用量"}</Button>
          </div>
        </form>
      </Show>
    </Show>
  </details>
}

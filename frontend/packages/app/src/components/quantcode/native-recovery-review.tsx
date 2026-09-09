import { For, Show, createEffect, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import type { OpencodeClient, QuantCodeBudgetReviewState, QuantCodeReceiptState, QuantCodeTaskLockState } from "@opencode-ai/sdk/v2"
import { BudgetRequestReview } from "./budget-review"
import { WriteReceiptReview, TaskLockRecovery } from "./write-receipt-review"
import "./task-review.css"

/** Only mounted after the organization row's source matches this SDK host.
 * Server-side review authorization remains required for every request. */
export function NativeRecoveryReview(props: { sessionID: string; client: OpencodeClient }) {
  const [state, setState] = createStore({ open: false, loading: false, error: "",
    budget: undefined as QuantCodeBudgetReviewState | undefined,
    receipts: undefined as QuantCodeReceiptState | undefined, lock: undefined as QuantCodeTaskLockState | undefined })
  let refresh = async () => {}
  createEffect(on(() => [props.sessionID, props.client] as const, ([sessionID, client]) => {
    const lifetime = new AbortController()
    let loading = false
    setState({ budget: undefined, receipts: undefined, lock: undefined, error: "", loading: false })
    refresh = async () => {
      if (!state.open || loading || lifetime.signal.aborted) return
      loading = true
      setState({ loading: true, error: "" })
      try {
        const options = { signal: lifetime.signal, throwOnError: false as const }
        const [budget, receipts, lock] = await Promise.all([client.quantcode.budget.reviewState({ sessionID }, options),
          client.quantcode.writeReceipt.status({ sessionID }, options), client.quantcode.taskLock.status({ sessionID }, options)])
        if (lifetime.signal.aborted) return
        if (budget.error || receipts.error || lock.error || !budget.data || !receipts.data || !lock.data)
          throw new Error("当前身份无法核对该任务，或原任务授权已变化。")
        if (budget.data.budget.session_id !== sessionID || receipts.data.session_id !== sessionID || lock.data.session_id !== sessionID)
          throw new Error("核对返回不属于当前任务。")
        setState({ budget: budget.data, receipts: receipts.data, lock: lock.data })
      } catch (error) {
        if (!lifetime.signal.aborted) setState({ budget: undefined, receipts: undefined, lock: undefined,
          error: error instanceof Error ? error.message : "无法读取核对记录。" })
      } finally { loading = false; if (!lifetime.signal.aborted) setState("loading", false) }
    }
    const timer = setInterval(() => void refresh(), 10000)
    onCleanup(() => { lifetime.abort(); clearInterval(timer) })
  }))
  return <details class="qc-task-review" open={state.open} onToggle={event => { setState("open", event.currentTarget.open); if (event.currentTarget.open) void refresh() }}>
    <summary>核对异常执行与用量</summary><div class="qc-task-review-body">
      <p>核对只记录已有操作的证据和结果，不会以原成员身份执行任务。</p>
      <button type="button" class="qc-button" disabled={state.loading} onClick={() => void refresh()}>刷新核对记录</button>
      <Show when={state.loading}><p role="status">正在读取…</p></Show>
      <Show when={state.error}><p role="alert">{state.error}</p></Show>
      <For each={state.budget?.requests}>{request => <BudgetRequestReview client={props.client} sessionID={props.sessionID} request={request} refresh={refresh} />}</For>
      <Show when={state.budget?.lock.status === "recovery_required" && state.budget.lock}>{lock => <TaskLockRecovery client={props.client} sessionID={props.sessionID} lock={lock()} budget refresh={refresh} />}</Show>
      <Show when={state.lock?.status === "recovery_required" && state.lock}>{lock => <TaskLockRecovery client={props.client} sessionID={props.sessionID} lock={lock()} refresh={refresh} />}</Show>
      <For each={state.receipts?.unresolved}>{receipt => <WriteReceiptReview client={props.client} sessionID={props.sessionID} receipt={receipt} refresh={refresh} />}</For>
      <Show when={state.budget && state.receipts && state.lock && !state.budget.requests.length && !state.receipts.unresolved.length && state.lock.status === "idle"}>
        <p>没有待核对记录。</p>
      </Show>
    </div>
  </details>
}

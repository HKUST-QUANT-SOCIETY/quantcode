import { For, Show, createUniqueId, createEffect, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { Button } from "@opencode-ai/ui/button"
import type { OpencodeClient, QuantCodeReceiptState, QuantCodeTaskLockState } from "@opencode-ai/sdk/v2"
import { useSDK } from "@/context/sdk"

export function WriteReceiptReview(props: {
  sessionID: string
  client?: OpencodeClient
  receipt: QuantCodeReceiptState["unresolved"][number]
  refresh: () => Promise<unknown>
}) {
  const sdk = props.client ? undefined : useSDK()
  const client = () => props.client ?? sdk!().client
  const id = createUniqueId()
  const [state, setState] = createStore({ evidence: "", note: "", result: "", busy: false, error: "", saved: false })
  createEffect(on(() => props.receipt.receipt_digest, () => setState({ evidence: "", note: "", result: "", error: "", saved: false })))
  const abort = new AbortController()
  onCleanup(() => abort.abort())
  const submit = async (decision: "confirmed_completed" | "confirmed_not_executed") => {
    if (state.busy || !state.evidence.trim() || !state.note.trim()) return
    if (props.receipt.completion_damaged && decision === "confirmed_not_executed") return
    const receipt = props.receipt
    setState({ busy: true, error: "" })
    try {
      const result = decision === "confirmed_completed" ? JSON.parse(state.result) as unknown : undefined
      const response = await client().quantcode.writeReceipt.review({ sessionID: props.sessionID,
        quantCodeReceiptReview: { source_session_id: receipt.source_session_id, message_id: receipt.message_id,
          call_id: receipt.call_id, expected_digest: receipt.operation_digest, expected_receipt_digest: receipt.receipt_digest, decision,
          evidence_ref: state.evidence.trim(), note: state.note.trim(),
          ...(decision === "confirmed_completed" ? { result } : {}),
        },
      }, { signal: abort.signal, throwOnError: false })
      if (abort.signal.aborted) return
      if (response.error || !response.data) throw new Error(response.error?.message ?? "核对未保存，请刷新回执后重试。")
      setState("saved", true)
      await props.refresh()
    } catch (error) {
      if (!abort.signal.aborted) setState("error", error instanceof SyntaxError ? "原始结果格式无效，请填写完整的 JSON 结果。"
        : error instanceof Error ? error.message : "核对未完成，请刷新查看当前记录。")
    } finally {
      if (!abort.signal.aborted) setState("busy", false)
    }
  }
  return <section class="qc-write-receipt" aria-labelledby={`${id}-title`}>
    <header><h3 id={`${id}-title`}>写入回执未完成 · {props.receipt.tool}</h3></header>
    <p>{props.receipt.completion_damaged ? "原完成回执无法校验，只能恢复已验证的原结果，不能将它改为未执行。" : "若任务仍在执行，请等待结果。只有执行已停止且结果未确认时，才需核对文件或外部服务。审批员或 Admin 可记录核对结果；提交不会重新执行工具。"}</p>
    <Show when={props.receipt.files.length}><ul class="qc-task-review-files"><For each={props.receipt.files}>{file => <li><code>{file}</code></li>}</For></ul></Show>
    <details><summary>调用记录</summary><code>{props.receipt.call_id}</code><p>{props.receipt.operation_digest}</p></details>
    <Show when={!state.saved} fallback={<p role="status">核对已记录，未发起重试。</p>}>
      <form onSubmit={event => { event.preventDefault(); void submit("confirmed_not_executed") }}>
        <label for={`${id}-evidence`}>证据位置</label>
        <input id={`${id}-evidence`} required maxLength={2000} value={state.evidence} disabled={state.busy}
          placeholder="核对报告、日志或外部结果的位置" onInput={event => setState("evidence", event.currentTarget.value)} />
        <label for={`${id}-note`}>核对结论</label>
        <textarea id={`${id}-note`} required maxLength={4000} value={state.note} disabled={state.busy}
          placeholder="说明检查了什么，以及实际是否发生写入" onInput={event => setState("note", event.currentTarget.value)} />
        <details><summary>已有成功结果：恢复原调用结果</summary>
          <label for={`${id}-result`}>原始工具结果（JSON）</label>
          <textarea id={`${id}-result`} value={state.result} disabled={state.busy} spellcheck={false}
            onInput={event => setState("result", event.currentTarget.value)} />
          <Button type="button" variant="secondary" disabled={state.busy || !state.result.trim() || !state.evidence.trim() || !state.note.trim()}
            onClick={() => void submit("confirmed_completed")}>确认已完成并保存原结果</Button>
        </details>
        <Show when={state.error}><p role="alert" class="qc-task-review-error">{state.error}</p></Show>
        <Show when={!props.receipt.completion_damaged}><div class="qc-task-review-actions"><Button type="submit" variant="secondary" disabled={state.busy || !state.evidence.trim() || !state.note.trim()}>
          {state.busy ? "正在保存…" : "确认未执行，关闭原调用"}
        </Button></div></Show>
      </form>
    </Show>
  </section>
}

export function TaskLockRecovery(props: { sessionID: string; client?: OpencodeClient; lock: Pick<QuantCodeTaskLockState, "lock_digest">; budget?: boolean; refresh: () => Promise<unknown> }) {
  const sdk = props.client ? undefined : useSDK()
  const client = () => props.client ?? sdk!().client
  const id = createUniqueId()
  const [state, setState] = createStore({ stopped: false, evidence: "", note: "", busy: false, error: "", saved: false })
  createEffect(on(() => props.lock.lock_digest, () => setState({ stopped: false, evidence: "", note: "", error: "", saved: false })))
  const abort = new AbortController()
  onCleanup(() => abort.abort())
  const submit = async () => {
    if (state.busy || !state.stopped || !state.evidence.trim() || !state.note.trim() || !props.lock.lock_digest) return
    setState({ busy: true, error: "" })
    try {
      const input = { expected_digest: props.lock.lock_digest, processes_stopped: true as const,
        evidence_ref: state.evidence.trim(), note: state.note.trim() }
      const options = { signal: abort.signal, throwOnError: false as const }
      const result = props.budget ? await client().quantcode.budget.recoverLock({ sessionID: props.sessionID, quantCodeBudgetLockRecovery: input }, options)
        : await client().quantcode.taskLock.recover({ sessionID: props.sessionID, quantCodeTaskLockRecovery: input }, options)
      if (abort.signal.aborted) return
      if (result.error || !result.data) throw new Error(result.error?.message ?? "未恢复，请刷新后核对原执行状态。")
      setState("saved", true)
      await props.refresh()
    } catch (error) {
      if (!abort.signal.aborted) setState("error", error instanceof Error ? error.message : "恢复未完成。")
    } finally { if (!abort.signal.aborted) setState("busy", false) }
  }
  return <section class="qc-write-receipt" aria-labelledby={`${id}-title`}>
    <header><h3 id={`${id}-title`}>{props.budget ? "预算记录需要恢复" : "上次执行异常退出"}</h3></header>
    <p>{props.budget ? "先确认原模型请求已停止，再解除残留预算锁。已有用量与预留额度保持不变，之后仍需核对缺失的供应商回执。" : "先确认原任务及其启动的程序均已停止，再解除残留执行锁。未确认的写入结果仍需逐项核对，恢复不会自动重试任务。"}</p>
    <Show when={!state.saved} fallback={<p role="status">残留锁已处理，请继续核对写入回执。</p>}>
      <form onSubmit={event => { event.preventDefault(); void submit() }}>
        <label for={`${id}-evidence`}>进程检查证据</label>
        <input id={`${id}-evidence`} required maxLength={2000} value={state.evidence} disabled={state.busy}
          onInput={event => setState("evidence", event.currentTarget.value)} />
        <label for={`${id}-note`}>检查说明</label>
        <textarea id={`${id}-note`} required maxLength={4000} value={state.note} disabled={state.busy}
          onInput={event => setState("note", event.currentTarget.value)} />
        <label class="qc-recovery-confirm"><input type="checkbox" checked={state.stopped} disabled={state.busy}
          onChange={event => setState("stopped", event.currentTarget.checked)} />已核对原任务及其子进程全部停止</label>
        <Show when={state.error}><p role="alert" class="qc-task-review-error">{state.error}</p></Show>
        <div class="qc-task-review-actions"><Button type="submit" disabled={state.busy || !state.stopped || !state.note.trim() || !state.evidence.trim()}>
          {state.busy ? "正在处理…" : "记录核对并解除残留锁"}
        </Button></div>
      </form>
    </Show>
  </section>
}

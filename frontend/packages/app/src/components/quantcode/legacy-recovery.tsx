import { Show, createEffect, createMemo, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import type { QuantCodeLegacyDetail, QuantCodeLegacyResume, QuantCodeLegacyResumeInput, QuantCodeLegacyApprovalInput, QuantCodeNativeGate } from "@opencode-ai/sdk/v2"

type Preview = Pick<QuantCodeLegacyDetail, "thread_id" | "checkpoint_id" | "can_resume" | "pending_approval" | "recovery" | "gate">
export type LegacyRecoveryRequest = (input: QuantCodeLegacyResumeInput, signal: AbortSignal) => Promise<QuantCodeLegacyResume>
export type LegacyApprovalRequest = (input: QuantCodeLegacyApprovalInput, signal: AbortSignal) => Promise<QuantCodeNativeGate>

export function LegacyRecovery(props: { detail: Preview; resume: LegacyRecoveryRequest; requestApproval: LegacyApprovalRequest; onChanged: () => void }) {
  const [state, setState] = createStore({ running: false, requesting: false, stopping: false, error: "", message: "" })
  let controller: AbortController | undefined
  let version = 0
  const binding = createMemo(() => JSON.stringify([props.detail.thread_id, props.detail.checkpoint_id, props.detail.recovery.checkpoint_digest]))
  createEffect(on(binding, () => {
    version++
    controller?.abort()
    setState({ running: false, requesting: false, stopping: false, error: "", message: "" })
  }))
  const timer = setInterval(() => { if (props.detail.pending_approval && !state.running && !state.requesting) props.onChanged() }, 10000)
  onCleanup(() => { clearInterval(timer); version++; controller?.abort() })
  const gateID = () => {
    const gate = props.detail.gate
    return gate && typeof gate === "object" && "gate_id" in gate && typeof gate.gate_id === "string" ? gate.gate_id : undefined
  }
  async function requestApproval() {
    const recovery = props.detail.recovery
    const gate = gateID()
    if (state.running || state.requesting || !gate || !recovery.executor_version || !recovery.provenance_digest) return
    const current = version
    const active = new AbortController()
    controller = active
    setState({ requesting: true, error: "", message: "" })
    try {
      await props.requestApproval({ thread_id: props.detail.thread_id, checkpoint_id: props.detail.checkpoint_id,
        checkpoint_digest: recovery.checkpoint_digest, executor_version: recovery.executor_version,
        provenance_digest: recovery.provenance_digest, expected_gate_id: gate }, active.signal)
      if (current !== version) return
      setState("message", "已提交到审批队列，等待审批人处理。")
      props.onChanged()
    } catch (error) {
      if (current === version) setState("error", error instanceof Error ? error.message : "审批申请未完成。")
    } finally { if (current === version) setState("requesting", false) }
  }
  async function resume() {
    const detail = props.detail
    const recovery = detail.recovery
    if (state.running || !recovery.executor_version || !recovery.provenance_digest) return
    const current = version
    const active = new AbortController()
    controller = active
    setState({ running: true, stopping: false, error: "", message: "" })
    try {
      const result = await props.resume({ thread_id: detail.thread_id, checkpoint_id: detail.checkpoint_id,
        checkpoint_digest: recovery.checkpoint_digest, executor_version: recovery.executor_version,
        provenance_digest: recovery.provenance_digest,
        ...(detail.pending_approval && recovery.approval ? { approval_gate_id: recovery.approval.gate_id, expected_gate_id: gateID() } : {}) }, active.signal)
      if (current !== version) return
      if (!result.resumed) throw new Error(result.recovery.blockers.map(item => item.message).join("；") || "当前检查点不能恢复。")
      setState("message", `恢复执行已返回：${result.status}。`)
      props.onChanged()
    } catch (error) {
      if (current !== version) return
      setState("error", active.signal.aborted ? "已请求停止恢复，请刷新检查点和回执确认执行结果。" : error instanceof Error ? error.message : "恢复未完成，请重新核对检查点。")
    } finally { if (current === version) setState({ running: false, stopping: false }) }
  }
  return <section class="qc-detail-section" aria-label="恢复归档任务">
    <Show when={props.detail.can_resume && !props.detail.pending_approval}>
      <p>继续这个检查点，使用当前模型设置。原任务的归属、方案和回执会再次核验。</p>
      <button type="button" class="qc-button" disabled={state.running || state.requesting} onClick={() => void resume()}>继续原任务</button>
    </Show>
    <Show when={props.detail.pending_approval && props.detail.recovery.gate_available && gateID()}>
      <h4>待审批的原操作</h4><pre class="qc-native-text">{JSON.stringify(props.detail.gate, null, 2)}</pre>
      <Show when={props.detail.recovery.approval?.valid && ["approved", "rejected"].includes(props.detail.recovery.approval!.status)} fallback={
        <button type="button" class="qc-button" disabled={state.running || state.requesting || props.detail.recovery.approval?.status === "pending" && props.detail.recovery.approval.valid} onClick={() => void requestApproval()}>
          {props.detail.recovery.approval?.status === "pending" && props.detail.recovery.approval.valid ? "等待审批队列处理" : state.requesting ? "正在提交审批…" : "提交审批申请"}
        </button>
      }>
        <p>审批结果：{props.detail.recovery.approval?.status === "approved" ? "已批准" : "已拒绝"} · {props.detail.recovery.approval?.decision?.reviewer}</p>
        <button type="button" class="qc-button" disabled={state.running || state.requesting} onClick={() => void resume()}>
          {props.detail.recovery.approval?.status === "approved" ? "按已批准操作继续原任务" : "按拒绝决定结束原操作"}
        </button>
      </Show>
    </Show>
    <Show when={state.running}><p role="status">{state.stopping ? "正在请求停止…" : "原任务恢复执行中…"} <button type="button" disabled={state.stopping} onClick={() => { setState("stopping", true); controller?.abort() }}>停止恢复</button></p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <Show when={state.message}><p role="status">{state.message}</p></Show>
  </section>
}

import { For, Show, createEffect, on, onCleanup } from "solid-js"
import { createStore, reconcile } from "solid-js/store"
import type { OpencodeClient, QuantCodeNativeGate } from "@opencode-ai/sdk/v2"
import { RefreshAction, WorkspaceEmpty } from "./workspace-ui"
import { approvalReference, approvalOutcome, matchesApproval, retryableApproval, decodeApprovalReferences, type ApprovalReference } from "./native-approval-outcome"

type Outcome = { reference: ApprovalReference; gate?: QuantCodeNativeGate; checking: boolean; error: string }

export function NativeApprovalQueue(props: { scope: string; client: OpencodeClient; canApprove: boolean }) {
  const [state, setState] = createStore({ gates: [] as QuantCodeNativeGate[], cursor: undefined as string | undefined,
    loading: false, error: "", busy: "", notes: {} as Record<string, string>, notice: "",
    outcomes: {} as Record<string, Outcome> })
  let load = async (_more = false) => {}
  let check = async (_reference: ApprovalReference) => {}
  let dismiss = (_id: string) => {}
  let decide = async (_gate: QuantCodeNativeGate, _decision: "approve" | "reject") => {}

  createEffect(on(() => [props.scope, props.client, props.canApprove] as const, ([scope, client, canApprove]) => {
    const lifetime = new AbortController()
    const storageKey = `quantcode:approval-outcomes:${encodeURIComponent(scope)}`
    const references = (() => {
      try { return decodeApprovalReferences(sessionStorage.getItem(storageKey)) } catch { return [] }
    })()
    setState({ gates: [], cursor: undefined, loading: false, error: "", busy: "", notice: "" })
    setState("notes", reconcile({}))
    setState("outcomes", reconcile(Object.fromEntries(references.map(reference => [reference.gate_id, { reference, checking: false, error: "" }]))))
    const options = { signal: lifetime.signal, throwOnError: false as const }
    const saveReferences = () => {
      try { sessionStorage.setItem(storageKey, JSON.stringify(Object.values(state.outcomes).map(item => item.reference))) }
      catch { /* This view still retains the pending reference until it closes. */ }
    }
    const apply = (reference: ApprovalReference, gate: QuantCodeNativeGate) => {
      if (!matchesApproval(reference, gate)) throw new Error("返回记录与原审批版本不一致，不能据此重新提交。")
      setState("outcomes", reference.gate_id, { reference, gate, checking: false, error: "" })
      setState("gates", values => retryableApproval(gate)
        ? [...values.filter(item => item.gate_id !== gate.gate_id), gate]
        : values.filter(item => item.gate_id !== gate.gate_id))
    }
    check = async reference => {
      if (lifetime.signal.aborted || state.outcomes[reference.gate_id]?.checking) return
      setState("outcomes", reference.gate_id, { reference, gate: undefined, checking: true, error: "" })
      try {
        const response = await client.quantcode.nativeGate.read({ gateID: reference.gate_id }, options)
        if (lifetime.signal.aborted) return
        if (response.error || !response.data) throw new Error("暂时无法核对原审批结果，请检查当前登录与连接后重试。")
        apply(reference, response.data)
      } catch (error) {
        if (!lifetime.signal.aborted) setState("outcomes", reference.gate_id, { reference, gate: undefined, checking: false,
          error: error instanceof Error ? error.message : "结果待核对，当前不能确认是否已记录决定。" })
      }
    }
    const recheck = check
    load = async (more = false) => {
      if (lifetime.signal.aborted || state.loading || state.busy) return
      setState({ loading: true, error: "" })
      if (!more) setState({ gates: [], cursor: undefined })
      try {
        const response = await client.quantcode.nativeGate.list({ ...(more && state.cursor ? { cursor: state.cursor } : {}) }, options)
        if (lifetime.signal.aborted) return
        if (response.error || !response.data) throw new Error("组织审批暂不可用，请检查登录与连接。")
        const values = more ? [...state.gates, ...response.data.gates] : response.data.gates
        setState({ gates: [...new Map(values.map(gate => [gate.gate_id, gate])).values()], cursor: response.data.next_cursor ?? undefined })
      } catch (error) {
        if (!lifetime.signal.aborted) setState("error", error instanceof Error ? error.message : "读取审批失败。")
      } finally {
        if (!lifetime.signal.aborted) {
          const pending = Object.values(state.outcomes).map(item => item.reference)
          for (let offset = 0; offset < pending.length && !lifetime.signal.aborted; offset += 8)
            await Promise.all(pending.slice(offset, offset + 8).map(recheck))
          if (!lifetime.signal.aborted) setState("loading", false)
        }
      }
    }
    dismiss = id => {
      if (lifetime.signal.aborted || !state.outcomes[id]?.gate || retryableApproval(state.outcomes[id].gate)) return
      setState("outcomes", reconcile(Object.fromEntries(Object.entries(state.outcomes).filter(([key]) => key !== id))))
      saveReferences()
    }
    decide = async (gate, decision) => {
      const note = state.notes[gate.gate_id]?.trim()
      const prior = state.outcomes[gate.gate_id]
      if (!canApprove || lifetime.signal.aborted || state.loading || state.busy || !note || !retryableApproval(gate) ||
        prior && (prior.checking || !retryableApproval(prior.gate))) return
      const reference = approvalReference(gate)
      setState({ busy: gate.gate_id, error: "", notice: "" })
      setState("outcomes", gate.gate_id, { reference, gate: undefined, checking: true, error: "" })
      saveReferences()
      try {
        const response = await client.quantcode.nativeGate.decide({ quantCodeNativeGateReview: {
          gate_id: reference.gate_id, expected_digest: reference.record_digest,
          operation_digest: reference.operation_digest, decision, note,
        } }, options)
        if (lifetime.signal.aborted) return
        if (response.error || !response.data) throw new Error("提交响应未确认，正在核对原审批结果。")
        apply(reference, response.data)
        setState("notice", approvalOutcome(response.data))
      } catch {
        if (lifetime.signal.aborted) return
        setState("outcomes", gate.gate_id, { reference, gate: undefined, checking: false,
          error: "提交响应未确认；核对结果前不会重新发送审批。" })
        await recheck(reference)
      } finally { if (!lifetime.signal.aborted) setState("busy", "") }
    }
    void load()
    onCleanup(() => lifetime.abort())
  }))

  return <section class="qc-native-gates">
    <div class="qc-section-toolbar"><h3>组织审批</h3><RefreshAction label="刷新组织审批" disabled={state.loading || !!state.busy} onClick={() => void load()} /></div>
    <p class="qc-muted">这里显示当前身份有权处理的任务；批准只对应所列资源、参数和版本。</p>
    <Show when={state.error}><p role="alert" class="qc-error-banner">{state.error}</p></Show>
    <Show when={state.notice}><p role="status">{state.notice}</p></Show>
    <For each={Object.values(state.outcomes)}>{outcome => <article class="qc-detail-section" aria-label="审批提交结果">
      <strong>{outcome.checking ? "正在核对审批结果…" : approvalOutcome(outcome.gate)}</strong>
      <p class="qc-muted">原请求 {outcome.reference.gate_id.slice(0, 12)} · 版本 {outcome.reference.record_digest.slice(0, 12)}</p>
      <Show when={outcome.gate?.decision}>{decision => <p>决定人 · {decision().reviewer} · {new Date(decision().timestamp).toLocaleString()}</p>}</Show>
      <Show when={outcome.error}><p role="alert">{outcome.error}</p></Show>
      <Show when={!outcome.gate || retryableApproval(outcome.gate)}>
        <button type="button" class="qc-button" disabled={outcome.checking || !!state.busy} onClick={() => void check(outcome.reference)}>核对原审批结果</button>
      </Show>
      <Show when={outcome.gate && !retryableApproval(outcome.gate)}>
        <button type="button" class="qc-button" disabled={outcome.checking || !!state.busy} onClick={() => dismiss(outcome.reference.gate_id)}>收起结果</button>
      </Show>
    </article>}</For>
    <Show when={!state.loading && !state.error && !state.gates.length && !Object.keys(state.outcomes).length}><WorkspaceEmpty icon="shield" title="没有待处理的组织审批" /></Show>
    <For each={state.gates}>{gate => <article class="qc-detail-section qc-native-gate">
      <div class="qc-section-toolbar"><strong>{gate.request.kind === "merge" ? "共享写入" : "受限资源访问"}</strong><span>待审批</span></div>
      <p class="qc-muted">申请人 · {gate.owner.actor_id} · {gate.owner.group}</p>
      <h4>{gate.request.resource}</h4>
      <Show when={gate.request.resource_version}><p>预期版本 · {gate.request.resource_version}</p></Show>
      <p>{gate.request.description}</p>
      <pre class="qc-native-gate-arguments">{gate.request.arguments_json}</pre>
      <small>有效期至 {new Date(gate.request.expires_at).toLocaleString()}</small>
      <Show when={!props.canApprove}><p class="qc-muted">等待本组审批员或 Admin 处理。</p></Show>
      <Show when={props.canApprove && retryableApproval(gate)}>
        <label for={`gate-${gate.gate_id}`}>审批说明</label>
        <textarea id={`gate-${gate.gate_id}`} value={state.notes[gate.gate_id] ?? ""} maxLength={2048} disabled={!!state.busy}
          onInput={event => setState("notes", gate.gate_id, event.currentTarget.value)} />
        <div class="qc-gate-actions"><For each={["reject", "approve"] as const}>{decision => <button type="button"
          class={`qc-button ${decision === "approve" ? "qc-button-primary" : "qc-button-secondary"}`}
          disabled={state.loading || !!state.busy || !state.notes[gate.gate_id]?.trim() ||
            !!state.outcomes[gate.gate_id] && (state.outcomes[gate.gate_id].checking || !retryableApproval(state.outcomes[gate.gate_id].gate))}
          onClick={() => void decide(gate, decision)}>
          {state.busy === gate.gate_id ? "正在核对…" : decision === "approve" ? "批准本次操作" : "拒绝"}
        </button>}</For></div>
      </Show>
    </article>}</For>
    <Show when={state.cursor}><button type="button" class="qc-button qc-button-secondary" disabled={state.loading || !!state.busy} onClick={() => void load(true)}>加载更多</button></Show>
  </section>
}

import { For, Show, createEffect, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"

type Item = { thread_id: string; checkpoint_id: string; task: string; actor_id: string; gate: { gate_id: string; kind: string; message?: string; reasons?: string[]; resource?: unknown } }
export function ApprovalQueue(props: {
  scope: string
  fetcher: (cursor?: string) => Promise<unknown>
  decide: (threadId: string, checkpointId: string, gateId: string, decision: "approve" | "reject") => Promise<boolean>
}) {
  const [state, setState] = createStore({ items: [] as Item[], loading: false, error: "", busy: "", sent: [] as string[], cursor: undefined as string | undefined })
  let revision = 0
  onCleanup(() => revision++)
  async function load(append = false) {
    const current = ++revision
    setState({ loading: true, error: "" })
    if (!append) setState({ items: [], sent: [], cursor: undefined })
    try {
      const result = await props.fetcher(append ? state.cursor : undefined)
      if (current !== revision) return
      if (!result || typeof result !== "object" || !("gates" in result) || !Array.isArray(result.gates)) throw new Error(result && typeof result === "object" && "error" in result ? String(result.error) : "审批队列不可用")
      if (!result.gates.every(item => item?.thread_id && item?.checkpoint_id && item?.gate?.gate_id && ["merge", "permission"].includes(item.gate.kind))) throw new Error("审批队列包含无效 Gate")
      const cursor = "next_cursor" in result ? result.next_cursor : undefined
      if (cursor != null && typeof cursor !== "string") throw new Error("审批队列分页信息无效")
      const items = result.gates as Item[]
      setState({
        items: append ? [...state.items, ...items.filter(item => !state.items.some(old => old.thread_id === item.thread_id && old.gate.gate_id === item.gate.gate_id))] : items,
        cursor: cursor || undefined,
      })
    } catch (error) { if (current === revision) setState("error", error instanceof Error ? error.message : "读取失败") }
    finally { if (current === revision) setState("loading", false) }
  }
  async function decide(item: Item, decision: "approve" | "reject") {
    if (state.loading || state.busy) return
    const current = revision
    setState({ busy: item.gate.gate_id, error: "" })
    try {
      const accepted = await props.decide(item.thread_id, item.checkpoint_id, item.gate.gate_id, decision)
      if (current !== revision) return
      if (!accepted) throw new Error("审批请求未提交，请检查任务连接后重试。")
      setState("sent", previous => [...previous, item.gate.gate_id])
    } catch (error) {
      if (current === revision) setState("error", error instanceof Error ? error.message : "审批请求提交失败。")
    } finally {
      if (current === revision) setState("busy", "")
    }
  }
  createEffect(() => { props.scope; revision++; setState({ items: [], busy: "" }); void load() })
  return <section class="qc-detail-body" aria-label="同组审批队列">
    <h3>同组待审批任务</h3><p>批准或拒绝仅针对当前展示的 Gate；任务变化后需要重新读取。</p>
    <button type="button" disabled={state.loading || !!state.busy} onClick={() => void load()}>刷新审批队列</button>
    <Show when={state.loading}><p role="status">正在读取…</p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <Show when={!state.loading && !state.error && !state.items.length}><p>当前组没有待处理审批。</p></Show>
    <For each={state.items}>{item => <article class="qc-detail-section">
      <h4>{item.task || item.thread_id}</h4><p>{item.actor_id} · {item.gate.kind}</p><p>{item.gate.message}</p>
      <For each={item.gate.reasons}>{reason => <p>{reason}</p>}</For>
      <Show when={item.gate.resource}><pre style={{ "white-space": "pre-wrap", "overflow-wrap": "anywhere" }}>{JSON.stringify(item.gate.resource, null, 2)}</pre></Show>
      <For each={["approve", "reject"] as const}>{decision => <button type="button" disabled={state.loading || !!state.busy || state.sent.includes(item.gate.gate_id)} onClick={() => void decide(item, decision)}>{decision === "approve" ? "批准" : "拒绝"}</button>}</For>
      <Show when={state.sent.includes(item.gate.gate_id)}><p role="status">已请求处理，请查看任务返回结果。</p></Show>
    </article>}</For>
    <Show when={state.cursor}><button type="button" disabled={state.loading || !!state.busy} onClick={() => void load(true)}>加载更多待审批任务</button></Show>
  </section>
}

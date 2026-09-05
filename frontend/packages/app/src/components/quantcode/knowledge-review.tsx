import { For, Show, createEffect, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"

type Candidate = { name: string; group: string; status?: string; content?: string; digest?: string; error?: string }
export function KnowledgeReview(props: {
  scope: string
  fetcher: () => Promise<unknown>
  review: (name: string, action: "promote" | "reject" | "supersede" | "revoke", digest?: string, replacement?: string) => Promise<unknown>
}) {
  const [state, setState] = createStore({ items: [] as Candidate[], loading: false, error: "", replacement: "", busy: "" })
  let revision = 0
  onCleanup(() => revision++)
  async function load() {
    const current = ++revision
    setState({ loading: true, error: "" })
    try {
      const result = await props.fetcher()
      if (current !== revision) return
      if (!result || typeof result !== "object" || !("candidates" in result) || !Array.isArray(result.candidates)) {
        throw new Error(result && typeof result === "object" && "error" in result ? String(result.error) : "候选列表返回格式错误")
      }
      setState("items", result.candidates as Candidate[])
    } catch (error) {
      if (current === revision) setState("error", error instanceof Error ? error.message : "读取失败")
    } finally { if (current === revision) setState("loading", false) }
  }
  async function review(item: Candidate, action: "promote" | "reject" | "supersede" | "revoke") {
    const current = revision
    setState({ busy: item.name, error: "" })
    try {
      await props.review(item.name, action, item.digest, action === "supersede" ? state.replacement : undefined)
      if (current === revision) await load()
    } catch (error) {
      if (current === revision) setState("error", error instanceof Error ? error.message : "审核失败")
    } finally { setState("busy", "") }
  }
  createEffect(() => { props.scope; revision++; setState({ items: [], replacement: "", busy: "" }); void load() })
  return <section class="qc-detail-body" aria-label="知识候选审核">
    <h3>知识候选审核</h3><p>阅读草稿后再晋升为组内 Skill；审核操作记录当前人员身份。</p>
    <button type="button" disabled={state.loading || !!state.busy} onClick={() => void load()}>刷新候选</button>
    <Show when={state.loading}><p role="status">正在读取…</p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <Show when={!state.loading && !state.error && !state.items.length}><p>当前权限范围内暂无候选。</p></Show>
    <For each={state.items}>{item => <details class="qc-detail-section">
      <summary>{item.name} · {item.group} · {item.status || "draft"}</summary>
      <Show when={item.error}><p role="alert">{item.error}</p></Show>
      <pre style={{ "white-space": "pre-wrap", "overflow-wrap": "anywhere" }}>{item.content}</pre>
      <Show when={!item.status || item.status === "draft" || item.status === "publishing"}>
        <button type="button" disabled={!!state.busy || !item.digest} onClick={() => void review(item, "promote")}>{item.status === "publishing" ? "恢复发布" : "晋升为组内 Skill"}</button>
        <button type="button" disabled={!!state.busy || item.status === "publishing"} onClick={() => void review(item, "reject")}>拒绝候选</button>
        <label>替代候选<select value={state.replacement} onChange={event => setState("replacement", event.currentTarget.value)}><option value="">请选择</option><For each={state.items.filter(other => other.name !== item.name && other.group === item.group)}>{other => <option value={other.name}>{other.name}</option>}</For></select></label>
        <button type="button" disabled={!!state.busy || !state.replacement} onClick={() => void review(item, "supersede")}>标记为已替代</button>
      </Show>
      <Show when={item.status === "promoted" || item.status === "publishing"}>
        <button type="button" disabled={!!state.busy} onClick={() => void review(item, "revoke")}>撤销发布</button>
      </Show>
    </details>}</For>
  </section>
}

import { GitHubConnection } from "./github-connection"
import { For, Show, createEffect, createMemo, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { Icon } from "@opencode-ai/ui/icon"
import { userFacingServiceError } from "./workspace-ui"

import { RepositoryGraph, RepositoryDetail, type GraphRepo } from "./repository-graph"
type Pop = { pop_id: string; change_summary: string; read_status: string; ack_status: string; observed_at: string; old_value?: unknown; new_value?: unknown }

export function GitHubWorkspace(props: {
  scope: string; ready: boolean; visible: boolean
  fetcher: (tool: "get_gitgraph" | "list_pops", cursor?: string) => Promise<unknown>
  update: (id: string, changes: { read?: boolean; ack?: boolean }) => Promise<unknown>
  onUnread: (count: number) => void
  notify?: (count: number) => Promise<void>
  notificationPermission?: () => Promise<boolean>
}) {
  const [state, setState] = createStore({ repos: [] as GraphRepo[], selected: "", selectedSha: "", query: "", pops: [] as Pop[], cursor: undefined as string | undefined, error: "", loading: false, busy: "", notifications: false, notificationError: "", enabling: false })
  let generation = 0
  let running = false
  function readPage(result: unknown) {
    if (!result || typeof result !== "object" || !("pops" in result) || !Array.isArray(result.pops)
      || !result.pops.every(pop => pop && typeof pop.pop_id === "string" && typeof pop.read_status === "string")
      || !("unread_count" in result) || typeof result.unread_count !== "number" || !Number.isSafeInteger(result.unread_count) || result.unread_count < 0
      || !("next_cursor" in result) || (result.next_cursor !== null && typeof result.next_cursor !== "string")) throw new Error("通知分页返回格式错误")
    return { pops: result.pops as Pop[], cursor: result.next_cursor || undefined, unread: result.unread_count }
  }
  async function loadMore() {
    if (running || state.busy || !state.cursor || !props.ready) return
    const version = generation
    running = true
    setState({ loading: true, error: "" })
    try {
      const page = readPage(await props.fetcher("list_pops", state.cursor))
      if (version !== generation) return
      setState({ pops: [...state.pops, ...page.pops.filter(pop => !state.pops.some(old => old.pop_id === pop.pop_id))], cursor: page.cursor })
      props.onUnread(page.unread)
    } catch (error) { if (version === generation) setState("error", error instanceof Error ? error.message : "读取通知失败") }
    finally { if (version === generation) { running = false; setState("loading", false) } }
  }
  let seen: string[] | undefined
  const notificationKey = () => `quantcode.github.notifications:${encodeURIComponent(props.scope)}`
  function saveNotifications() {
    try { localStorage.setItem(notificationKey(), JSON.stringify({ enabled: state.notifications, seen })) }
    catch { setState("notificationError", "无法保存本机通知偏好，刷新后可能需要重新开启。") }
  }
  async function toggleNotifications() {
    const version = generation
    if (state.notifications) { setState("notifications", false); saveNotifications(); return }
    setState({ enabling: true, notificationError: "" })
    try {
      const allowed = await props.notificationPermission?.()
      if (version !== generation) return
      if (!allowed) { setState("notificationError", "系统通知未获授权，请在浏览器或系统设置中允许通知。"); return }
      seen = state.pops.map(pop => pop.pop_id)
      setState("notifications", true)
      saveNotifications()
    } catch { if (version === generation) setState("notificationError", "无法开启系统通知。") }
    finally { if (version === generation) setState("enabling", false) }
  }
  async function refresh(version: number) {
    if (running || state.busy || !props.ready) return
    running = true
    setState({ loading: true, error: "" })
    try {
      const graph = await props.fetcher("get_gitgraph")
      if (version !== generation) return
      if (!graph || typeof graph !== "object" || !("repos" in graph) || !Array.isArray(graph.repos)) throw new Error(graph && typeof graph === "object" && "error" in graph ? String(graph.error) : "GitGraph 返回格式错误")
      setState("repos", graph.repos as GraphRepo[])
      const result = await props.fetcher("list_pops")
      if (version !== generation) return
      const page = readPage(result)
      setState({ pops: page.pops, cursor: page.cursor })
      props.onUnread(page.unread)
      const fresh = seen ? state.pops.filter(pop => pop.read_status === "unread" && !seen!.includes(pop.pop_id)) : []
      seen = [...new Set([...state.pops.map(pop => pop.pop_id), ...(seen ?? [])])].slice(0, 1000)
      saveNotifications()
      if (fresh.length && state.notifications && props.notify) {
        // One summary avoids a burst of OS notifications and keeps repository
        // names and research details off the lock screen.
        await props.notify(fresh.length).catch(() => {
          if (version === generation) setState("notificationError", "系统提醒发送失败，更新仍保存在下方通知列表。")
        })
      }
    } catch (error) {
      if (version === generation) { setState({ error: userFacingServiceError(error, "GitHub 同步暂不可用。"), repos: [], pops: [], cursor: undefined }); props.onUnread(0) }
    } finally {
      if (version === generation) { running = false; setState("loading", false) }
    }
  }
  async function receipt(pop: Pop, changes: { read?: boolean; ack?: boolean }) {
    if (running || state.busy || !props.ready) return
    const version = generation
    setState({ busy: pop.pop_id, error: "" })
    try {
      const result = await props.update(pop.pop_id, changes)
      if (version !== generation) return
      if (!result || typeof result !== "object" || !("pop" in result)
        || !("unread_count" in result) || typeof result.unread_count !== "number" || !Number.isSafeInteger(result.unread_count) || result.unread_count < 0) throw new Error("通知状态返回格式错误")
      setState("pops", item => item.pop_id === pop.pop_id, result.pop as Pop)
      props.onUnread(result.unread_count)
    } catch (error) {
      if (version === generation) setState("error", error instanceof Error ? error.message : "通知状态保存失败")
    } finally { if (version === generation) setState("busy", "") }
  }
  createEffect(() => {
    props.scope
    const ready = props.ready
    const version = ++generation
    running = false
    seen = undefined
    setState({ repos: [], selected: "", pops: [], cursor: undefined, error: "", loading: false, busy: "", notifications: false, notificationError: "", enabling: false })
    try {
      const saved = JSON.parse(localStorage.getItem(notificationKey()) ?? "null")
      if (saved && Array.isArray(saved.seen) && saved.seen.every((id: unknown) => typeof id === "string")) {
        seen = saved.seen.slice(0, 1000)
        setState("notifications", saved.enabled === true)
      }
    } catch { setState("notificationError", "本机通知偏好不可读，系统提醒暂未开启。") }
    props.onUnread(0)
    if (!ready) return
    void refresh(version)
    const timer = setInterval(() => void refresh(version), 60_000)
    onCleanup(() => { clearInterval(timer); generation++ })
  })
  const repos = createMemo(() => state.repos.filter(repo => repo.repo.toLowerCase().includes(state.query.toLowerCase())).sort((a, b) => a.repo.localeCompare(b.repo)))
  const selected = createMemo(() => state.repos.find(repo => repo.repo === state.selected))
  return <section style={{ display: props.visible ? undefined : "none" }} hidden={!props.visible} class="qc-detail-body qc-github-sync" aria-label="GitHub 同步工作台">
    <div class="qc-view-toolbar"><div><h3>GitGraph · 仓库与分支</h3><p>同步当前授权范围；首次同步建立基线。</p></div><button type="button" class="qc-icon-action" aria-label="刷新" title="刷新 GitGraph" disabled={state.loading || !props.ready} onClick={() => void refresh(generation)}><Icon name="reset" size="normal" /></button></div>
    <details class="qc-github-account" open={!state.repos.length}><summary><Icon name="github" size="small" /> GitHub 账号与连接</summary><Show keyed when={props.visible && props.ready ? props.scope : undefined}><GitHubConnection onConnected={() => void refresh(generation)} /></Show></details>
    <Show when={state.loading}><p role="status">正在同步 GitHub…</p></Show>
    <Show when={state.error}><div class="qc-github-error" role="status"><Icon name="github" size="normal" /><div><strong>GitGraph 暂不可用</strong><p>{state.error}</p><p class="qc-muted">连接 GitHub 身份后，这里会显示授权范围内的仓库、分支和更新。</p></div></div></Show>
    <Show when={!state.loading && !state.error && !state.repos.length}><p>当前身份没有可见仓库。</p></Show>
    <div class="qc-repo-browser-toolbar"><label><Icon name="magnifying-glass" /><input type="search" aria-label="搜索仓库" placeholder="搜索项目…" value={state.query} onInput={e => setState("query", e.currentTarget.value)} /></label><span>{repos().length} 个项目</span></div>
    <div class="qc-repo-grid"><For each={repos()}>{repo => <RepositoryGraph repo={repo} onOpen={commit => setState({ selected: repo.repo, selectedSha: commit?.sha ?? "" })} />}</For></div>
    <Show keyed when={props.visible && selected()}>{repo => <RepositoryDetail repo={repo} sha={state.selectedSha} onClose={() => setState("selected", "")} />}</Show>
    <h3>持久通知</h3><p>已读与确认只影响当前账号；确认通知不会批准任务。</p>
    <Show when={state.cursor}><button type="button" disabled={state.loading || !!state.busy} onClick={() => void loadMore()}>加载更多历史通知</button></Show>
    <Show when={props.notify && props.notificationPermission}>
      <button type="button" disabled={!props.ready || state.loading || state.enabling} onClick={() => void toggleNotifications()}>{state.notifications ? "关闭本机系统提醒" : "开启本机系统提醒"}</button>
      <p>仅对新发现的更新发送汇总提醒，首次加载建立基线。关闭客户端后不会发送提醒。</p>
      <Show when={state.notificationError}><p role="alert">{state.notificationError}</p></Show>
    </Show>
    <For each={state.pops}>{pop => <article class="qc-detail-section">
      <h4>{pop.change_summary}</h4><p>{pop.observed_at}</p>
      <p>{String(pop.old_value ?? "新增")} → {String(pop.new_value ?? "删除")}</p>
      <button type="button" disabled={state.loading || !!state.busy || pop.read_status === "read"} onClick={() => void receipt(pop, { read: true })}>{pop.read_status === "read" ? "已读" : "标为已读"}</button>
      <button type="button" disabled={state.loading || !!state.busy || pop.ack_status === "acknowledged"} onClick={() => void receipt(pop, { read: true, ack: true })}>{pop.ack_status === "acknowledged" ? "已确认" : "确认更新"}</button>
    </article>}</For>
  </section>
}

import { For, Show, createEffect, createMemo, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"

type Node = { sha: string; message: string; parents: string[] }
type Repo = { repo: string; default_branch?: string; observed_at: string; sync_status: string; errors: string[]; heads: { branch: string; sha: string; changed?: boolean }[]; commit_nodes: Node[]; dependency_changes: { file: string; old_sha?: string; new_sha?: string }[]; package_changes?: { file: string; package: string; old_value?: string; new_value?: string }[]; dependency_files?: { path: string; version_status?: string }[] }
type Pop = { pop_id: string; change_summary: string; read_status: string; ack_status: string; observed_at: string; old_value?: unknown; new_value?: unknown }

export function GitHubWorkspace(props: {
  scope: string; ready: boolean; visible: boolean
  fetcher: (tool: "get_gitgraph" | "list_pops", cursor?: string) => Promise<unknown>
  update: (id: string, changes: { read?: boolean; ack?: boolean }) => Promise<unknown>
  onUnread: (count: number) => void
  notify?: (count: number) => Promise<void>
  notificationPermission?: () => Promise<boolean>
}) {
  const [state, setState] = createStore({ repos: [] as Repo[], pops: [] as Pop[], cursor: undefined as string | undefined, error: "", loading: false, busy: "", notifications: false, notificationError: "", enabling: false })
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
      setState("repos", graph.repos as Repo[])
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
      if (version === generation) { setState({ error: error instanceof Error ? error.message : "GitHub 同步失败", repos: [], pops: [], cursor: undefined }); props.onUnread(0) }
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
    setState({ repos: [], pops: [], cursor: undefined, error: "", loading: false, busy: "", notifications: false, notificationError: "", enabling: false })
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
  return <section style={{ display: props.visible ? undefined : "none" }} hidden={!props.visible} class="qc-detail-body" aria-label="GitHub 同步工作台">
    <h3>GitGraph · 仓库与分支</h3>
    <p>每分钟同步当前授权范围。首次同步建立基线。图展示各分支最近 30 条提交。</p>
    <button type="button" disabled={state.loading || !props.ready} onClick={() => void refresh(generation)}>刷新</button>
    <Show when={state.loading}><p role="status">正在同步 GitHub…</p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <Show when={!state.loading && !state.error && !state.repos.length}><p>当前身份没有可见仓库。</p></Show>
    <For each={state.repos}>{repo => <details class="qc-detail-section">
      <summary>{repo.repo} · {repo.heads.length} 个分支 · {repo.sync_status}</summary>
      <p>默认分支：{repo.default_branch || "—"} · 同步：{repo.observed_at}</p>
      <For each={repo.errors}>{error => <p role="alert">{error}</p>}</For>
      <table><thead><tr><th>分支</th><th>HEAD</th><th>变化</th></tr></thead><tbody><For each={repo.heads}>{head => <tr><td>{head.branch}</td><td><code>{head.sha.slice(0, 12)}</code></td><td>{head.changed ? "有更新" : "—"}</td></tr>}</For></tbody></table>
      <CommitGraph nodes={repo.commit_nodes} />
      <For each={repo.dependency_changes}>{change => <p>{change.file}：{change.old_sha?.slice(0, 12) || "新增"} → {change.new_sha?.slice(0, 12) || "删除"}（文件版本）</p>}</For>
      <Show when={repo.package_changes?.length}><h4>依赖版本变化</h4><p>declared 表示清单声明，resolved 表示锁文件解析结果；不代表当前服务器已安装或升级。</p></Show>
      <For each={repo.package_changes}>{change => <p>{change.file} · {change.package}：{change.old_value ?? "新增"} → {change.new_value ?? "删除"}</p>}</For>
      <For each={repo.dependency_files?.filter(file => file.version_status !== "PARSED")}>{file => <p>{file.path}：目前仅跟踪文件变化，包版本尚未解析。</p>}</For>
    </details>}</For>
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
function CommitGraph(props: { nodes: Node[] }) {
  const [state, setState] = createStore({ page: 0 })
  const page = () => Math.min(state.page, Math.max(0, Math.ceil(props.nodes.length / 100) - 1))
  const visible = createMemo(() => props.nodes.slice(page() * 100, (page() + 1) * 100))
  const positions = createMemo(() => new Map(visible().map((node, index) => [node.sha, index])))
  const position = (sha: string) => positions().get(sha) ?? -1
  const locate = (sha: string) => {
    const index = props.nodes.findIndex(node => node.sha === sha)
    if (index >= 0) setState("page", Math.floor(index / 100))
  }
  return <div><p>共 {props.nodes.length} 条提交 · 第 {page() + 1} 页</p>
    <button type="button" disabled={page() === 0} onClick={() => setState("page", page() - 1)}>上一页提交</button>
    <button type="button" disabled={(page() + 1) * 100 >= props.nodes.length} onClick={() => setState("page", page() + 1)}>下一页提交</button>
    <div style={{ overflow: "auto", "max-height": "480px" }}><svg width="760" height={Math.max(40, visible().length * 32)} role="img" aria-label="提交父子关系图，分页显示">
    <For each={visible()}>{(node, index) => <g>
      <For each={node.parents}>{(parent, lane) => <Show when={position(parent) >= 0}><path d={`M 12 ${index() * 32 + 16} C ${40 + lane() * 12} ${index() * 32 + 16}, ${40 + lane() * 12} ${position(parent) * 32 + 16}, 12 ${position(parent) * 32 + 16}`} fill="none" stroke="currentColor" opacity="0.3" /></Show>}</For>
      <circle cx="12" cy={index() * 32 + 16} r="4" fill="currentColor" />
      <text x="64" y={index() * 32 + 20} fill="currentColor" font-size="11">{node.sha.slice(0, 8)} {node.message.slice(0, 80)}{node.parents.some(parent => position(parent) < 0) ? " · 父节点在其他页或本次读取不完整" : ""}</text>
    </g>}</For>
  </svg></div>
    <For each={visible().filter(node => node.parents.some(parent => position(parent) < 0))}>{node => <p>
      {node.sha.slice(0, 8)} 的跨页父提交：<For each={node.parents.filter(parent => position(parent) < 0)}>{parent =>
        <button type="button" disabled={!props.nodes.some(item => item.sha === parent)} onClick={() => locate(parent)}>{parent.slice(0, 12)}</button>
      }</For>
    </p>}</For>
  </div>
}

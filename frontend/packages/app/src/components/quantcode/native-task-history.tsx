import { For, Match, Show, Switch, createEffect, createMemo, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { Icon } from "@opencode-ai/ui/icon"
import type { FilePart, Message, Part, QuantCodeTaskSummary, QuantCodePublicationStatus, QuantCodeTaskIndexRead, QuantCodeLegacyProjectionPending } from "@opencode-ai/sdk/v2"
import { useServerSDK } from "@/context/server-sdk"
import { RefreshAction, WorkspaceEmpty, navigateViewTabs, runStatusLabel } from "./workspace-ui"
import { NativeArtifacts, type NativeArtifactSource } from "./native-artifacts"
import { NativeRecoveryReview } from "./native-recovery-review"
import { readTaskDescendants, descendantActivity, isActiveTask, isRunningTask, type TaskDescendant } from "./native-task-tree"
import "./native-task-history.css"

export type NativeTaskRecord = QuantCodeTaskSummary
export type NativeTaskDetail = QuantCodeTaskIndexRead
type Transcript = { info: Message; parts: Part[] }[]
type Detail = { task: NativeTaskRecord; messages: Transcript; descendants: TaskDescendant[]; activeDescendants: number; messageCursor?: string; live?: string }
export type NativeTaskSource = {
  publication?: (signal: AbortSignal) => Promise<QuantCodePublicationStatus>
  artifacts: NativeArtifactSource
  relatives?: (task: NativeTaskRecord, cursor: string | undefined, signal: AbortSignal) => Promise<{ tasks: NativeTaskRecord[]; next_cursor: string | null }>
  list: (input: { cursor?: string; signal?: AbortSignal }) => Promise<{ tasks: NativeTaskRecord[]; legacy_pending?: QuantCodeLegacyProjectionPending[]; next_cursor?: string | null }>
  read: (task: Pick<NativeTaskRecord, "session_id"> & Partial<Pick<NativeTaskRecord, "source_id">>, signal?: AbortSignal) => Promise<NativeTaskDetail>
}

const statuses: Record<string, string> = { busy: "运行中", retry: "重试中", idle: "已停止", pending: "等待执行", queued: "排队中", paused: "已暂停", unknown: "状态未知", cancelled: "已取消" }
const label = (status: string) => statuses[status] ?? runStatusLabel(status)
const date = (timestamp: number) => Number.isFinite(timestamp) && timestamp > 0 ? new Date(timestamp).toLocaleString() : ""
const taskKey = (task: Pick<NativeTaskRecord, "session_id" | "source_id">) => JSON.stringify([task.source_id, task.session_id])
const errorText = (info: Message) => info.role === "assistant" && info.error && "message" in info.error.data
  ? String(info.error.data.message) : undefined
const attachments = (messages: Transcript) => messages.filter(message => message.info.role === "user").flatMap(message => message.parts.flatMap(part => part.type === "file" ? [part] : []))
  .filter((part, index, items) => items.findIndex(item => item.id === part.id) === index)
const documentLink = (file: FilePart) => /^data:(?:image\/(?:png|jpeg|gif|webp)|application\/pdf);base64,/i.test(file.url) ? file.url : undefined

function MessagePartView(props: { part: Part }) {
  const part = () => props.part
  return <Switch>
    <Match when={part().type === "text" || part().type === "reasoning"}>
      <pre class="qc-native-text">{(part() as Extract<Part, { type: "text" }> | Extract<Part, { type: "reasoning" }>).text}</pre>
    </Match>
    <Match when={part().type === "tool"}>
      {(() => {
        const item = part() as Extract<Part, { type: "tool" }>
        return <details class="qc-native-tool" open={item.state.status === "running" || item.state.status === "error"}>
          <summary><Icon name="terminal" size="small" /><strong>{item.tool}</strong><span class={`qc-status qc-status-${item.state.status}`}>{label(item.state.status)}</span></summary>
          <pre class="qc-native-text">{JSON.stringify(item.state.input, null, 2)}</pre>
          <Show when={item.state.status === "completed"}><pre class="qc-native-text">{item.state.status === "completed" ? item.state.output : ""}</pre></Show>
          <Show when={item.state.status === "error"}><p role="alert">{item.state.status === "error" ? item.state.error : ""}</p></Show>
        </details>
      })()}
    </Match>
    <Match when={part().type === "patch"}>
      <p class="qc-native-files">{(part() as Extract<Part, { type: "patch" }>).files.join("\n")}</p>
    </Match>
  </Switch>
}

/** Views use native messages and published task summaries. Organization
 * summaries never grant access to another member's local session endpoints. */
export function NativeTaskHistory(props: {
  scope: string; ready: boolean; currentSessionID?: string; mode?: "tasks" | "reports" | "overview";
  source: NativeTaskSource; organization?: boolean; onOpen?: (sessionID: string) => void; onNew?: () => void;
}) {
  const serverSDK = useServerSDK()
  const [state, setState] = createStore({ tasks: [] as NativeTaskRecord[], legacy: [] as QuantCodeLegacyProjectionPending[], cursor: undefined as string | undefined,
    detail: undefined as Detail | undefined, loading: false, error: "", query: "", filter: "all",
    tab: "activity" as "activity" | "tree" | "reports", stopping: false, stopError: "",
    publication: undefined as QuantCodePublicationStatus | undefined, publicationError: "" })
  const [tree, setTree] = createStore({ tasks: [] as NativeTaskRecord[], cursor: undefined as string | undefined, loading: false, error: "" })
  const visible = createMemo(() => state.tasks.filter(task => (props.mode !== "reports" || task.artifact_count > 0) &&
    (state.filter === "all" || task.status === state.filter) &&
    `${task.title} ${task.actor_id} ${task.group} ${task.session_id}`.toLowerCase().includes(state.query.trim().toLowerCase())))
  const files = createMemo(() => attachments(state.detail?.messages ?? []))
  const result = createMemo(() => state.detail?.messages.findLast(message => message.info.role === "assistant" &&
    !!message.info.time.completed && !message.info.error)?.parts.filter(part => part.type === "text") ?? [])
  let refresh = async (_task?: NativeTaskRecord, _cursor?: string) => {}
  let stop = async () => {}
  let older = async () => {}
  let closeDetail = () => {}
  let loadTree = async (_more = false) => {}

  createEffect(on(() => [state.detail?.task.source_id, state.detail?.task.session_id] as const, () => {
    setTree({ tasks: [], cursor: undefined, error: "", loading: false })
    setState("stopError", "")
  }))

  createEffect(on(() => [props.scope, props.ready, props.currentSessionID, props.mode, props.source, serverSDK()] as const,
    ([, ready, currentID, mode, source, sdk]) => {
      const lifetime = new AbortController()
      let revision = 0
      let timer: ReturnType<typeof setTimeout> | undefined
      let dirty = false
      let taskBoundary: string | undefined
      const schedule = () => {
        if (timer || lifetime.signal.aborted) return
        if (state.loading || state.stopping) { dirty = true; return }
        timer = setTimeout(() => { timer = undefined; void load(state.detail?.task) }, 350)
      }
      setState({ tasks: [], legacy: [], cursor: undefined, detail: undefined, error: "", loading: false, stopping: false, stopError: "",
        tab: mode === "reports" ? "reports" : "activity" })
      const options = { signal: lifetime.signal, throwOnError: false as const }
      loadTree = async (more = false) => {
        const selected = state.detail?.task
        if (!source.relatives || !selected || tree.loading || lifetime.signal.aborted) return
        setTree({ loading: true, error: "" })
        try {
          const page = await source.relatives(selected, more ? tree.cursor : undefined, lifetime.signal)
          if (lifetime.signal.aborted || !state.detail || taskKey(state.detail.task) !== taskKey(selected)) return
          setTree({ tasks: [...new Map([...(more ? tree.tasks : []), ...page.tasks].map(task => [taskKey(task), task])).values()],
            cursor: page.next_cursor ?? undefined })
        } catch {
          if (!lifetime.signal.aborted && state.detail && taskKey(state.detail.task) === taskKey(selected)) setTree("error", "组织任务树读取失败，请重试。")
        } finally {
          if (!lifetime.signal.aborted && state.detail && taskKey(state.detail.task) === taskKey(selected)) setTree("loading", false)
        }
      }
      let readingPublication = false
      const loadPublication = async () => {
        if (!ready || !source.publication || readingPublication || lifetime.signal.aborted) return
        readingPublication = true
        try {
          const status = await source.publication(lifetime.signal)
          if (!lifetime.signal.aborted) setState({ publication: status, publicationError: "" })
        } catch {
          if (!lifetime.signal.aborted) setState({ publication: undefined, publicationError: "无法核验本机任务的组织同步状态。" })
        } finally { readingPublication = false }
      }
      const load = async (selected?: NativeTaskRecord, cursor?: string) => {
        if (!ready || lifetime.signal.aborted) return
        const version = ++revision
        setState({ loading: true, error: "" })
        try {
          const wanted = selected ?? (currentID ? { session_id: currentID } : undefined)
          if (wanted) {
            const loaded = await source.read(wanted, lifetime.signal)
            const task = loaded.task
            if (task.session_id !== wanted.session_id || ("source_id" in wanted && wanted.source_id !== task.source_id)) throw new Error("任务详情身份不一致。")
            const detail: Detail = { task, messages: [], descendants: [], activeDescendants: 0 }
            if (!props.organization && task.directory) {
              const client = sdk.ensureDirSdkContext(task.directory).client
              const prior = state.detail
              const boundary = prior && taskKey(prior.task) === taskKey(task) ? prior.messages[0]?.info.id : undefined
              // Re-read the full expanded window. Keeping only the newest page
              // would remove older messages whenever a live event arrives.
              const transcript = async () => {
                const messages: Transcript = []
                const seen = new Set<string>()
                let before: string | undefined
                while (true) {
                  const response = await client.session.messages({ sessionID: task.session_id, limit: 100, before }, options)
                  if (lifetime.signal.aborted || version !== revision) return undefined
                  if (response.error || !response.data) throw new Error("任务消息暂不可用。")
                  messages.unshift(...response.data)
                  const cursor = response.response.headers.get("X-Next-Cursor") ?? undefined
                  if (!cursor || !boundary || response.data.some(message => message.info.id === boundary)) {
                    return { messages: [...new Map(messages.map(message => [message.info.id, message])).values()], cursor }
                  }
                  if (seen.has(cursor)) throw new Error("消息分页游标重复，请重新打开任务。")
                  seen.add(cursor)
                  before = cursor
                }
              }
              const descendants = readTaskDescendants({ sessionID: task.session_id, directory: task.directory,
                signal: lifetime.signal, children: async sessionID => {
                  const response = await client.session.children({ sessionID }, options)
                  if (response.error || !response.data) throw new Error("任务树暂不可用，无法核对活动后代。")
                  return response.data
                } })
              const [messages, children] = await Promise.all([transcript(), descendants])
              const statuses = await client.session.status({}, options)
              if (lifetime.signal.aborted || version !== revision) return
              if (statuses.error || !statuses.data || !messages) throw new Error("任务详情暂不可用。")
              const activity = descendantActivity(children, statuses.data)
              detail.messages = messages.messages
              detail.descendants = activity.items
              detail.activeDescendants = activity.active
              detail.messageCursor = messages.cursor
              detail.live = statuses.data?.[task.session_id]?.type
            }
            if (!lifetime.signal.aborted && version === revision) setState("detail", detail)
            return
          }
          const tasks: NativeTaskRecord[] = cursor ? [...state.tasks] : []
          const legacy: QuantCodeLegacyProjectionPending[] = cursor ? [...state.legacy] : []
          const seen = new Set<string>()
          let next = cursor
          while (true) {
            const data = await source.list({ cursor: next, signal: lifetime.signal })
            if (lifetime.signal.aborted || version !== revision) return
            tasks.push(...data.tasks)
            legacy.push(...(data.legacy_pending ?? []))
            next = data.next_cursor ?? undefined
            // Refresh through the previous last visible task, so insertions
            // before that boundary cannot push already loaded rows off screen.
            if (cursor || !next || !taskBoundary || [...data.tasks, ...(data.legacy_pending ?? [])].some(task => taskKey(task) === taskBoundary)) break
            if (seen.has(next)) throw new Error("任务分页游标重复，请重新刷新列表。")
            seen.add(next)
          }
          const unique = [...new Map(tasks.map(task => [taskKey(task), task])).values()]
          const previous = [...new Map(legacy.map(task => [taskKey(task), task])).values()]
          const boundary = props.organization ? [...unique, ...previous].toSorted((a, b) =>
            a.source_id === b.source_id ? a.session_id < b.session_id ? -1 : a.session_id > b.session_id ? 1 : 0
              : a.source_id < b.source_id ? -1 : 1).at(-1) : unique.at(-1)
          taskBoundary = boundary ? taskKey(boundary) : undefined
          setState({ tasks: unique, legacy: previous, cursor: next })
        } catch (error) {
          if (!lifetime.signal.aborted && version === revision) setState({ tasks: [], legacy: [], detail: undefined, error: error instanceof Error ? error.message : "任务读取失败。" })
        } finally {
          if (!lifetime.signal.aborted && version === revision) {
            setState("loading", false)
            if (dirty) { dirty = false; schedule() }
          }
        }
      }
      refresh = load
      closeDetail = () => { revision++; setState({ detail: undefined, loading: false, error: "" }) }
      older = async () => {
        const detail = state.detail
        if (!detail?.messageCursor || !detail.task.directory || props.organization || state.loading || lifetime.signal.aborted) return
        const version = ++revision
        setState({ loading: true, error: "" })
        try {
          const response = await sdk.ensureDirSdkContext(detail.task.directory).client.session.messages({
            sessionID: detail.task.session_id, limit: 100, before: detail.messageCursor,
          }, options)
          if (response.error || !response.data) throw new Error("更早的任务消息读取失败。")
          if (version !== revision || lifetime.signal.aborted) return
          const messages = [...response.data, ...detail.messages].filter((message, index, items) =>
            items.findIndex(item => item.info.id === message.info.id) === index)
          setState("detail", { ...detail, messages, messageCursor: response.response.headers.get("X-Next-Cursor") ?? undefined })
        } catch (error) {
          if (!lifetime.signal.aborted && version === revision) setState({ detail: undefined, error: error instanceof Error ? error.message : "读取失败。" })
        } finally {
          if (!lifetime.signal.aborted && version === revision) {
            setState("loading", false)
            if (dirty) { dirty = false; schedule() }
          }
        }
      }
      stop = async () => {
        const detail = state.detail
        if (!detail?.task.directory || detail.task.read_only || props.organization || state.stopping || lifetime.signal.aborted) return
        const selected = taskKey(detail.task)
        setState({ stopping: true, stopError: "" })
        try {
          const response = await sdk.ensureDirSdkContext(detail.task.directory).client.session.abort({ sessionID: detail.task.session_id }, options)
          if (response.error || response.data !== true) throw new Error("停止任务树请求未完成，请刷新后核对实际执行状态。")
          if (lifetime.signal.aborted || !state.detail || taskKey(state.detail.task) !== selected) return
          await load(detail.task)
          if (state.detail && taskKey(state.detail.task) === selected &&
            (isRunningTask(state.detail.live) || isRunningTask(state.detail.task.status) || state.detail.activeDescendants > 0)) {
            setState("stopError", "停止请求已返回，但仍检测到活动任务，请刷新后核对。")
          }
        } catch (error) {
          if (!lifetime.signal.aborted && state.detail && taskKey(state.detail.task) === selected)
            setState("stopError", error instanceof Error ? error.message : "停止任务树请求失败。")
        } finally {
          if (!lifetime.signal.aborted) {
            setState("stopping", false)
            if (dirty) { dirty = false; schedule() }
          }
        }
      }
      const off = sdk.event.listen(event => {
        const type = event.details.type
        if (!type.startsWith("session.") && !type.startsWith("message.") && !type.startsWith("quantcode.")) return
        schedule()
      })
      const interval = props.organization ? setInterval(() => { if (!state.loading) void load(state.detail?.task) }, 10000) : undefined
      setState({ publication: undefined, publicationError: "" })
      const publicationTimer = source.publication ? setInterval(() => void loadPublication(), 10000) : undefined
      void loadPublication()
      if (ready) void load()
      onCleanup(() => { lifetime.abort(); revision++; if (timer) clearTimeout(timer); if (interval) clearInterval(interval); if (publicationTimer) clearInterval(publicationTimer); off() })
    }))

  return <section class="qc-detail-body qc-history qc-native-history" aria-label={props.organization ? "组织任务" : "原生任务"}>
    <div class="qc-view-toolbar"><h3>{props.mode === "overview" ? "组织概览" : props.mode === "reports" ? "报告与产物" : props.organization ? "组织任务" : props.currentSessionID ? "当前任务" : "任务记录"}</h3>
      <Show when={!props.currentSessionID}><span class="qc-count">已加载 {state.tasks.length}{state.cursor ? "+" : ""} 个任务</span></Show>
      <RefreshAction label="刷新任务" disabled={!props.ready || state.loading} onClick={() => void refresh(state.detail?.task)} />
    </div>
    <Show when={props.ready && state.publication}>{status => <p class="qc-native-publication" role="status">
      本机任务同步：{({ starting: "准备中", idle: "已同步", pending: "同步中", retrying: "等待重试" })[status().state]}
      <Show when={status().pending_tasks}> · 待同步 {status().pending_tasks} 项</Show>
      <Show when={status().last_success_at}> · 上次成功 {date(status().last_success_at!)}</Show>
      <Show when={status().last_error}> · {status().last_error === "identity_unavailable" ? "请检查组织登录连接" : "部分任务尚未同步，正在重试"}</Show>
    </p>}</Show>
    <Show when={props.ready && state.publicationError}><p class="qc-native-publication" role="status">{state.publicationError}</p></Show>
    <Show when={props.organization}><p class="qc-muted">这里显示各成员最近同步的任务记录；同步时间不代表任务仍在执行。</p></Show>
    <Show when={props.mode === "overview" && props.ready && !state.error}><div class="qc-native-summary" aria-label="已加载任务统计">
      <div><small>已加载任务</small><strong>{state.tasks.length}</strong></div>
      <div><small>运行中</small><strong>{state.tasks.filter(task => task.status === "running").length}</strong></div>
      <div><small>待审批</small><strong>{state.tasks.filter(task => task.status === "waiting_for_human").length}</strong></div>
      <div><small>异常或预算停止</small><strong>{state.tasks.filter(task => task.status === "error" || task.status === "stopped_budget").length}</strong></div>
    </div></Show>
    <Show when={!props.currentSessionID}><div class="qc-filter-bar"><label class="qc-search-field"><Icon name="magnifying-glass" /><input type="search" aria-label="搜索任务" placeholder="任务、成员或组" value={state.query} onInput={event => setState("query", event.currentTarget.value)} /></label>
      <select aria-label="任务状态" value={state.filter} onChange={event => setState("filter", event.currentTarget.value)}><option value="all">全部状态</option><For each={[...new Set(state.tasks.map(task => task.status))]}>{status => <option value={status}>{label(status)}</option>}</For></select></div></Show>
    <Show when={!props.ready}><WorkspaceEmpty icon="shield" title="登录后查看任务" /></Show>
    <Show when={state.loading}><p class="qc-loading" role="status">正在读取任务…</p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <Show when={state.legacy.length}><div class="qc-detail-section"><h4>等待恢复索引的历史任务</h4>
      <For each={state.legacy}>{task => <p><strong>{task.title}</strong> · {task.message}</p>}</For>
    </div></Show>
    <Show when={props.ready && !state.loading && !state.error && !state.detail && !visible().length && !state.legacy.length}><WorkspaceEmpty icon="checklist" title="暂无任务"><Show when={props.onNew}><button type="button" class="qc-button qc-button-primary" onClick={props.onNew}><Icon name="plus" size="small" />新建任务</button></Show></WorkspaceEmpty></Show>
    <div class="qc-history-layout" classList={{ "has-detail": !!state.detail && !props.currentSessionID }}>
      <Show when={!props.currentSessionID}><div class="qc-history-list"><For each={visible()}>{task => <button type="button" class="qc-history-row" aria-pressed={!!state.detail && taskKey(state.detail.task) === taskKey(task)} onClick={() => void refresh(task)}>
        <Icon name="task" /><span class="qc-history-copy"><strong>{task.title || task.session_id}</strong><small>{task.actor_id} · {task.group} · {date(task.updated_at)}</small></span><span class={`qc-status qc-status-${task.status}`}>{label(task.status)}</span><Icon name="chevron-right" size="small" />
      </button>}</For><Show when={state.cursor}><button type="button" disabled={state.loading} onClick={() => void refresh(undefined, state.cursor)}>加载更多</button></Show></div></Show>
      <Show when={state.detail}>{detail => <div class="qc-history-detail qc-native-detail" classList={{ "is-current": !!props.currentSessionID }}>
        <div class="qc-view-toolbar"><span class={`qc-status qc-status-${detail().task.status}`}>{label(detail().task.status)}</span>
          <Show when={!props.organization && !detail().task.read_only && props.onOpen}><button type="button" class="qc-button" onClick={() => props.onOpen?.(detail().task.session_id)}><Icon name="arrow-right" size="small" />打开任务</button></Show>
          <Show when={!props.organization && !detail().task.read_only && (isRunningTask(detail().live) || isRunningTask(detail().task.status) || detail().activeDescendants > 0)}><button type="button" class="qc-button" disabled={state.stopping} onClick={() => void stop()}><Icon name="stop" size="small" />{state.stopping ? "正在停止任务树…" : "停止任务树"}</button></Show>
          <Show when={!props.currentSessionID}><button type="button" class="qc-icon-action" title="关闭任务详情" aria-label="关闭任务详情" onClick={() => closeDetail()}><Icon name="close" size="small" /></button></Show>
        </div>
        <h3>{detail().task.title}</h3><p class="qc-muted">{detail().task.actor_id} · {detail().task.group} · {date(detail().task.updated_at)}</p>
        <Show when={!props.organization && detail().descendants.length}><p class="qc-muted">后代任务 {detail().descendants.length} 项 · 当前活动 {detail().activeDescendants} 项 <button type="button" class="qc-button" onClick={() => setState("tab", "tree")}>查看任务树</button></p></Show>
        <Show when={state.stopError}><p role="alert">{state.stopError}</p></Show>
        <Show when={detail().task.read_only}><p class="qc-muted">已导入的历史归档，仅供查看。</p></Show>
        <Show when={props.organization}><p class="qc-muted">{detail().task.source_id} · 最近同步 {detail().task.received_at ? date(detail().task.received_at!) : "尚未记录"}</p></Show>
        <Show when={detail().task.model}><p class="qc-muted">{detail().task.agent} · {detail().task.model}</p></Show>
        <Show when={detail().task.solution}><p class="qc-muted">方案 v{detail().task.solution!.version} · {detail().task.solution!.status} · {detail().task.solution!.document_hash.slice(0, 12)}</p></Show>
        <Show when={detail().task.knowledge}>{knowledge => <details class="qc-detail-section">
          <summary>关联知识候选 · {knowledge().candidates.length} 项</summary>
          <p class="qc-muted">候选须在知识审核中确认后才可发布。</p>
          <For each={knowledge().candidates}>{candidate => <p>{candidate.name} · {candidate.status} · {candidate.digest.slice(0, 12)}</p>}</For>
        </details>}</Show>
        <Show when={detail().task.last_error}><p role="alert">{detail().task.last_error}</p></Show>
        <Show when={props.organization && !detail().task.read_only && state.publication?.source_id === detail().task.source_id}>
          <NativeRecoveryReview sessionID={detail().task.session_id} client={serverSDK().client} />
        </Show>
        <div class="qc-native-usage"><span>输入 {detail().task.tokens_input.toLocaleString()}</span><span>输出 {detail().task.tokens_output.toLocaleString()}</span><span>费用 {detail().task.cost === null ? "未定价" : detail().task.cost!.toFixed(4)}</span></div>
        <div class="qc-native-usage"><span>产物 {detail().task.artifact_count}</span><span>预留 {detail().task.reserved_tokens.toLocaleString()}</span><Show when={detail().task.unconfirmed_requests}><span>待核对请求 {detail().task.unconfirmed_requests}</span></Show></div>
        <Show when={!props.organization} fallback={<div class="qc-native-remote-detail">
          <p class="qc-native-publication">此处展示已同步的组织摘要和产物；完整记录请在成员授权的研究宿主查看。</p>
          <Show when={props.source.relatives}>
            <div class="qc-view-toolbar"><h4>任务树</h4><button type="button" class="qc-button" disabled={tree.loading} onClick={() => void loadTree()}>加载任务树</button></div>
            <Show when={tree.loading}><p role="status">正在读取任务树…</p></Show>
            <Show when={tree.error}><p role="alert">{tree.error}</p></Show>
            <For each={tree.tasks}>{task => <button type="button" class="qc-history-row" onClick={() => void refresh(task)}>
              <Icon name={task.parent_session_id ? "branch" : "task"} /><span class="qc-history-copy"><strong>{task.title}</strong><small>{task.parent_session_id ? `父任务：${task.parent_session_id}` : "主任务"}</small></span><span class="qc-status">{label(task.status)}</span>
            </button>}</For>
            <Show when={tree.cursor}><button type="button" class="qc-button" disabled={tree.loading} onClick={() => void loadTree(true)}>加载更多任务</button></Show>
          </Show>
          <NativeArtifacts task={detail().task} source={props.source.artifacts} />
        </div>}>
          <div class="qc-view-tabs qc-native-tabs" role="tablist" aria-label="任务详情" onKeyDown={navigateViewTabs}><For each={[{ id: "activity" as const, label: "执行记录" }, { id: "tree" as const, label: "任务树" }, { id: "reports" as const, label: "报告与产物" }]}>{tab => <button type="button" role="tab" aria-selected={state.tab === tab.id} tabIndex={state.tab === tab.id ? 0 : -1} onClick={() => setState("tab", tab.id)}>{tab.label}</button>}</For></div>
          <Show when={state.tab === "activity"}><Show when={detail().messageCursor}><button type="button" class="qc-button" disabled={state.loading} onClick={() => void older()}>更早的消息</button></Show><For each={detail().messages}>{message => <article class="qc-native-message"><header><strong>{message.info.role === "user" ? "任务" : message.info.agent}</strong><time>{date(message.info.time.created)}</time></header><Show when={errorText(message.info)}><p role="alert">{errorText(message.info)}</p></Show><For each={message.parts}>{part => <MessagePartView part={part} />}</For></article>}</For></Show>
          <Show when={state.tab === "tree"}><div class="qc-native-tree"><Show when={detail().task.parent_session_id}><button type="button" class="qc-button" onClick={() => void refresh({ ...detail().task, session_id: detail().task.parent_session_id! })}><Icon name="arrow-left" size="small" />父任务</button></Show><div class="qc-native-tree-root"><Icon name="task" /><strong>{detail().task.title}</strong></div><For each={detail().descendants}>{child => <button type="button" class="qc-history-row qc-native-child" onClick={() => void refresh({ ...detail().task, session_id: child.session.id })}><Icon name="branch" /><span class="qc-history-copy"><strong>{child.session.title}</strong><small>第 {child.depth} 层 · {child.session.agent} · {date(child.session.time.updated)}</small></span><span class="qc-status">{isActiveTask(child.live) ? label(child.live) : "当前空闲"}</span><Icon name="chevron-right" /></button>}</For><Show when={!detail().descendants.length}><p class="qc-muted">没有子任务。</p></Show></div></Show>
          <Show when={state.tab === "reports"}>
            <NativeArtifacts task={detail().task} source={props.source.artifacts} />
            <Show when={files().length}><h4>用户附件</h4><For each={files()}>{file => <article class="qc-native-artifact"><Icon name="folder" size="small" /><div><strong>{file.filename ?? file.id}</strong><small>{file.mime}</small></div><Show when={documentLink(file)}>{url => <a href={url()} download={file.filename ?? "attachment"} rel="noopener noreferrer">下载附件</a>}</Show></article>}</For></Show>
            <Show when={result().length}><h4>任务结果</h4><For each={result()}>{part => <MessagePartView part={part} />}</For></Show>
          </Show>
        </Show>
      </div>}</Show>
    </div>
  </section>
}

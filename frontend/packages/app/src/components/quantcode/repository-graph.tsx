import { For, Show, createEffect, createMemo, onCleanup, onMount } from "solid-js"
import { createStore } from "solid-js/store"
import { Icon } from "@opencode-ai/ui/icon"
import { useServerSDK } from "@/context/server-sdk"
import { layoutGitGraph, type GitCommit, type GitHead } from "./git-graph-layout"
import "./repository-graph.css"

export type GraphRepo = {
  repo: string; description?: string; default_branch?: string; observed_at?: string; sync_status: string; refresh_pending?: boolean
  heads: GitHead[]; commit_nodes: GitCommit[]; errors: string[]
  dependency_changes: { file: string; old_sha?: string; new_sha?: string }[]
  package_changes?: { file: string; package: string; old_value?: string; new_value?: string }[]
  dependency_files?: { path: string; version_status?: string }[]
}
export type CommitDetail = { sha: string; message: string; author?: string; date?: string; files: { filename: string; status: string; additions: number; deletions: number; patch?: string }[]; has_more: boolean }
const colors = ["#3478cf", "#bb7329", "#33916b", "#9863b2", "#d25365", "#2698a6"]
const color = (lane: number) => colors[lane % colors.length]
export const commitDate = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "日期未提供"

export function RepositoryGraph(props: { repo: GraphRepo; onOpen: (commit?: GitCommit) => void }) {
  return <article class="qc-repo-card">
    <button type="button" class="qc-repo-heading" onClick={() => props.onOpen()} aria-label={`打开仓库 ${props.repo.repo}`}>
      <span class="qc-repo-symbol"><Icon name="branch" /></span><span><small>{props.repo.repo.split("/")[0]}</small><h3>{props.repo.repo.split("/").slice(1).join("/")}</h3></span><Icon name="arrow-right" />
    </button>
    <div class="qc-repo-summary"><span>{props.repo.heads.length} 个分支</span><span>{props.repo.commit_nodes.length} 条提交</span><span classList={{ "is-pending": !!props.repo.refresh_pending }}>{props.repo.refresh_pending ? "待刷新" : props.repo.sync_status === "CONNECTED" ? "已同步" : "部分数据"}</span></div>
    <CommitGraph repo={props.repo} compact onSelect={props.onOpen} />
    <button type="button" class="qc-repo-footer" onClick={() => props.onOpen()}><span>{props.repo.default_branch || "默认分支未提供"}</span><span>详情 <Icon name="arrow-right" size="small" /></span></button>
  </article>
}

export function CommitGraph(props: { repo: GraphRepo; compact?: boolean; selected?: string; onSelect: (node: GitCommit) => void }) {
  const graph = createMemo(() => { try { return { ...layoutGitGraph(props.repo.commit_nodes, props.repo.heads, props.repo.default_branch), error: "" } } catch (error) { return { rows: [], edges: [], lanes: 1, error: String(error) } } })
  const [state, setState] = createStore({ page: 0 })
  const rowHeight = () => props.compact ? 36 : 48
  const count = () => props.compact ? 4 : 100
  const page = () => props.compact ? 0 : Math.min(state.page, Math.max(0, Math.ceil(graph().rows.length / count()) - 1))
  const start = () => page() * count()
  const rows = () => graph().rows.slice(start(), start() + count())
  const height = () => Math.max(rows().length, 1) * rowHeight()
  const x = (lane: number) => 16 + lane * 16
  const y = (row: number) => (row - start()) * rowHeight() + rowHeight() / 2
  const width = () => Math.max(48, (props.compact ? Math.max(1, ...rows().map(row => row.lane + 1), ...graph().edges.filter(edge => edge.from.row < count()).map(edge => edge.lane + 1)) : graph().lanes) * 16 + 24)
  const jump = (sha: string) => {
    const row = graph().rows.find(node => node.sha === sha)
    if (row) { setState("page", Math.floor(row.row / count())); props.onSelect(row) }
  }
  return <div class="qc-commit-graph" classList={{ "is-compact": props.compact }}>
    <Show when={!props.compact}><div class="qc-branch-list" aria-label="全部分支"><For each={[...props.repo.heads].sort((a, b) => Number(b.branch === props.repo.default_branch) - Number(a.branch === props.repo.default_branch))}>{head => <button type="button" disabled={!graph().rows.some(row => row.sha === head.sha)} onClick={() => jump(head.sha)} title={head.sha}><Icon name="branch" size="small" />{head.branch}{head.changed ? " · 更新" : ""}</button>}</For></div></Show>
    <Show when={graph().error}><p role="alert">{graph().error}</p></Show>
    <Show when={rows().length} fallback={<div class="qc-graph-empty"><Icon name="branch" /><p>尚无提交图谱</p><small>同步后显示分支和合并关系</small></div>}>
      <div class="qc-graph-scroll"><div class="qc-graph-body" style={{ "grid-template-columns": `${width()}px minmax(0, 1fr)`, "min-width": props.compact ? undefined : `${width() + 720}px` }}>
        <svg class="qc-lane-canvas" width={width()} height={height()} role="img" aria-label="Git 分支与合并图">
          <For each={graph().edges.filter(edge => edge.from.row < start() + count() && (!edge.to || edge.to.row >= start()))}>{edge => {
            const fromY = y(edge.from.row), toY = edge.to ? y(edge.to.row) : height() + 12
            const fromX = x(edge.from.lane), toX = x(edge.lane)
            const bend = Math.min(24, (toY - fromY) / 2)
            return <path d={fromX === toX ? `M${fromX} ${fromY} V${toY}` : `M${fromX} ${fromY} V${toY - bend * 2} C${fromX} ${toY - bend} ${toX} ${toY - bend} ${toX} ${toY}`} stroke={color(edge.lane)} stroke-width="2" fill="none" stroke-dasharray={edge.to ? undefined : "3 4"} opacity="0.65" />
          }}</For>
          <For each={rows()}>{node => <circle cx={x(node.lane)} cy={y(node.row)} r={node.parents.length > 1 ? 5 : 4} fill={color(node.lane)} stroke="white" stroke-width="1.5" />}</For>
        </svg>
        <div class="qc-commit-rows"><For each={rows()}>{node => <button type="button" class="qc-commit-row" classList={{ "is-selected": props.selected === node.sha }} onClick={() => props.onSelect(node)} title={`${node.message}\n${node.author || "作者未提供"} · ${commitDate(node.date)} · ${node.sha}`}>
          <span class="qc-commit-copy"><span class="qc-commit-message"><For each={node.heads}>{head => <span class="qc-branch-tag" style={{ color: color(node.lane) }}>{head.branch}</span>}</For><span>{node.message.split("\n")[0] || "无提交说明"}</span></span><Show when={props.compact}><small>{node.author || "作者未提供"} · {commitDate(node.date)}</small></Show></span>
          <Show when={!props.compact}><time>{commitDate(node.date)}</time><span class="qc-commit-author">{node.author || "作者未提供"}</span><code>{node.sha.slice(0, 8)}</code></Show>
        </button>}</For></div>
      </div></div>
      <Show when={!props.compact}><div class="qc-graph-pagination"><span>{graph().rows.length} 条已同步提交 · 第 {page() + 1} 页</span><button type="button" disabled={page() === 0} onClick={() => setState("page", page() - 1)}>上一页提交</button><button type="button" disabled={start() + count() >= graph().rows.length} onClick={() => setState("page", page() + 1)}>下一页提交</button></div><p class="qc-graph-boundary">显示各分支最近同步的提交；虚线表示父提交在已同步历史之外。</p></Show>
    </Show>
  </div>
}

export function RepositoryDetail(props: { repo: GraphRepo; sha?: string; onClose: () => void }) {
  const sdk = useServerSDK()
  const [state, setState] = createStore({ selected: props.sha || props.repo.heads.find(head => head.branch === props.repo.default_branch)?.sha || props.repo.commit_nodes[0]?.sha || "", detail: undefined as CommitDetail | undefined, loading: false, error: "", revision: 0 })
  let dialog!: HTMLDialogElement
  onMount(() => dialog.showModal())
  createEffect(() => {
    const sha = state.selected
    state.revision
    if (!sha) return
    let live = true
    onCleanup(() => { live = false })
    setState({ loading: true, error: "", detail: undefined })
    void sdk().client.quantcode.github.commit({ repo: props.repo.repo, sha }).then(response => {
      if (!live) return
      const result = response.data as CommitDetail & { error?: string } | undefined
      if (response.error || !result || result.error || !Array.isArray(result.files) || result.sha !== sha) throw new Error(result?.error || "提交详情暂不可用，请重试。")
      setState({ detail: result, loading: false })
    }).catch(error => { if (live) setState({ loading: false, error: error instanceof Error ? error.message : "提交详情读取失败" }) })
  })
  const selected = () => props.repo.commit_nodes.find(node => node.sha === state.selected)
  return <dialog ref={dialog} class="qc-repo-dialog" aria-label={`${props.repo.repo} Git 图谱`} onClose={props.onClose} onClick={e => { if (e.target === dialog) dialog.close() }}>
    <header class="qc-repo-dialog-header"><div><small>{props.repo.repo.split("/")[0]}</small><h2>{props.repo.repo.split("/").slice(1).join("/")}</h2></div><button type="button" aria-label="关闭仓库详情" onClick={() => dialog.close()}><Icon name="close" /></button></header>
    <div class="qc-repo-dialog-content"><p class="qc-repo-description">{props.repo.description || "仓库未提供简介"}</p><p class="qc-graph-boundary">最近同步：{props.repo.observed_at ? new Date(props.repo.observed_at).toLocaleString("zh-CN") : "尚未同步"}{props.repo.refresh_pending ? " · 缓存待更新" : ""}</p>
    <For each={props.repo.errors}>{error => <p role="alert">{error}</p>}</For>
    <CommitGraph repo={props.repo} selected={state.selected} onSelect={node => setState("selected", node.sha)} />
    <Show when={selected()}><section class="qc-commit-detail" aria-label="提交代码变更"><div class="qc-commit-detail-heading"><h3>{state.detail?.message.split("\n")[0] || selected()?.message}</h3><a href={`https://github.com/${props.repo.repo}/commit/${state.selected}`} target="_blank" rel="noreferrer">在 GitHub 查看完整提交 ↗</a></div><p>{state.detail?.author || selected()?.author || "作者未提供"} · {commitDate(state.detail?.date || selected()?.date)} · <code>{state.selected}</code></p>
    <Show when={state.detail}><pre class="qc-commit-description">{state.detail?.message}</pre></Show>
    <Show when={state.loading}><p role="status">正在读取提交说明与代码变更…</p></Show><Show when={state.error}><p role="alert">{state.error}</p><button type="button" class="qc-button qc-button-secondary" onClick={() => setState("revision", value => value + 1)}>重试读取提交</button></Show>
    <Show when={state.detail?.has_more}><p>此处显示前 100 个文件；其余文件请在 GitHub 完整提交中查看。</p></Show>
    <For each={state.detail?.files}>{file => <details class="qc-diff-file" open><summary><strong>{file.filename}</strong><span>{file.status}</span><b class="is-addition">+{file.additions}</b><b class="is-deletion">−{file.deletions}</b></summary><Show when={file.patch} fallback={<p>此文件没有可用的文本 diff（可能为二进制或超出 GitHub 返回范围）。</p>}><pre><For each={file.patch?.split("\n")}>{line => <span classList={{ "is-addition": line.startsWith("+"), "is-deletion": line.startsWith("-"), "is-hunk": line.startsWith("@@") }}>{line}{"\n"}</span>}</For></pre></Show></details>}</For>
    </section></Show>
    <Show when={props.repo.dependency_changes.length || props.repo.package_changes?.length || props.repo.dependency_files?.some(file => file.version_status !== "PARSED")}><details class="qc-repo-dependencies"><summary>依赖变更</summary><For each={props.repo.dependency_changes}>{change => <p>{change.file}：{change.old_sha?.slice(0, 12) || "新增"} → {change.new_sha?.slice(0, 12) || "删除"}</p>}</For><For each={props.repo.package_changes}>{change => <p>{change.file} · {change.package}：{change.old_value ?? "新增"} → {change.new_value ?? "删除"}</p>}</For><For each={props.repo.dependency_files?.filter(file => file.version_status !== "PARSED")}>{file => <p>{file.path}：仅跟踪文件变化，版本尚未解析。</p>}</For></details></Show>
    </div>
  </dialog>
}

/**
 * F-09 / P-08 GitGraph 面板：组织全部 repo 最新树状态一览（用户点名关键设计）。
 *
 * 数据通道（与 admin-console 同一现实，AG-G 实测结论）：
 * - ① execution_trace 里 admin_repo_status / admin_package_updates 的 tool_result 事件；
 * - ③ 点击触发：顶部"检查更新"按钮经会话发送指令（buildRepoStatusInstruction），
 *   agent 调 admin_repo_status + admin_package_updates，结果回流 trace 后在此渲染。
 * 有更新节点标红高亮（pushed_at 距今 ≤ RECENT_PUSH_MS，阈值常量可调）。
 * 纯 DOM 构建（沿 memory-query 模式，bun test 兼容）。
 */
import type { TraceEvent } from "./result-contract"
import {
  adminToolResultEvents,
  adminToolStatusView,
  isRecord,
  listFromPayload,
  relativeTimeLabel,
  toEpochMs,
} from "./admin-console"

/** 有更新阈值：pushed_at 距今 ≤ 7 天视为有更新（spec F-09，常量可调）。 */
export const RECENT_PUSH_MS = 7 * 24 * 60 * 60 * 1000

export type RepoNode = {
  name?: string
  group?: string
  language?: string
  default_branch?: string
  /** 最近提交摘要 */
  commit?: string
  pushed_at?: number
}

function pickString(source: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === "string" && value.trim()) return value
  }
  return undefined
}

/** admin_repo_status 载荷 → repo 节点（{repos:[…]} 或裸数组；字段取别名防御）。 */
export function reposFromPayload(payload: unknown): RepoNode[] {
  const list = listFromPayload(payload, ["repos"])
  const nodes: RepoNode[] = []
  for (const item of list) {
    if (!isRecord(item)) continue
    nodes.push({
      name: pickString(item, ["name", "repo", "repo_name", "full_name"]),
      group: pickString(item, ["group", "group_name", "owner_group"]),
      language: pickString(item, ["language", "lang", "primary_language"]),
      default_branch: pickString(item, ["default_branch", "branch"]),
      commit: (isRecord(item.latest_commit) ? pickString(item.latest_commit, ["message"]) : undefined)
        ?? pickString(item, ["last_commit_message", "commit_message", "last_commit", "commit_summary", "commit"]),
      pushed_at: toEpochMs(item.pushed_at ?? item.last_push ?? item.updated_at ?? item.timestamp),
    })
  }
  return nodes
}

export function reposFromTrace(events: TraceEvent[] | undefined): RepoNode[] {
  return reposFromPayload(adminToolResultEvents(events, "admin_repo_status").at(-1))
}export type PackageUpdate = {
  repo?: string
  name?: string
  current?: string
  latest?: string
  change?: string
}

/** admin_package_updates 载荷 → 依赖更新清单（{updates:[…]} / {packages:[…]} 或裸数组）。 */
export function packagesFromPayload(payload: unknown): PackageUpdate[] {
  const list = listFromPayload(payload, ["updates", "packages"])
  const updates: PackageUpdate[] = []
  for (const item of list) {
    if (!isRecord(item)) continue
    if (Array.isArray(item.files)) {
      for (const file of item.files.filter(isRecord)) {
        updates.push({
          repo: pickString(item, ["repo"]),
          name: pickString(file, ["file"]),
          change: pickString(file, ["message"]),
        })
      }
      continue
    }
    updates.push({
      repo: pickString(item, ["repo", "repo_name"]),
      name: pickString(item, ["name", "package", "package_name", "dependency"]),
      current: pickString(item, ["current", "current_version", "installed"]),
      latest: pickString(item, ["latest", "latest_version", "available"]),
    })
  }
  return updates
}

export function packagesFromTrace(events: TraceEvent[] | undefined): PackageUpdate[] {
  return packagesFromPayload(adminToolResultEvents(events, "admin_package_updates").at(-1))
}

/** 有更新判定：pushed_at 距今 ≤ thresholdMs（缺 pushed_at = 无从判定 = false）。 */
export function isRecentlyPushed(pushedAtMs: number | undefined, now = Date.now(), thresholdMs = RECENT_PUSH_MS): boolean {
  if (pushedAtMs === undefined) return false
  return now - pushedAtMs <= thresholdMs
}

/** 通道③指令：指示 agent 调 admin_repo_status + admin_package_updates。 */
export function buildRepoStatusInstruction() {
  return (
    "You MUST call the admin_repo_status and admin_package_updates MCP tools NOW. Do NOT chat. Do NOT acknowledge. " +
    "Return the raw tool results so the GitGraph panel can render the repository tree and dependency updates. " +
    "Do not start a new research task."
  )
}

// ---------------------------------------------------------------------------
// 视图
// ---------------------------------------------------------------------------

export type GitGraphPanelProps = {
  /** i18n：panels 传 language.t（key 见 quantcode.gitgraph.*） */
  t: (key: string) => string
  /** 当前 run（读取 admin_repo_status / admin_package_updates 的 tool_result 事件） */
  run?: { execution_trace?: TraceEvent[] } | null
  /** 通道③：经会话发送"检查更新"指令 */
  sendInstruction?: (content: string) => void
}

/** 语言 → 语义点色（GitHub linguist 主色；未知语言回落墨色）。 */
const LANGUAGE_COLORS: Record<string, string> = {
  typescript: "#3178c6",
  javascript: "#d4ac0d",
  python: "#3572a5",
  go: "#00add8",
  rust: "#dea584",
  java: "#b07219",
  "c++": "#f34b7d",
  shell: "#89e051",
}

const RED = "#aa2e23"

export function GitGraphPanelView(props: GitGraphPanelProps): HTMLElement {
  const t = props.t
  const root = document.createElement("div")
  root.className = "qc-gitgraph-panel"
  root.style.cssText = "display:grid;gap:12px;align-content:start;"

  const sectionLabel = (text: string) => {
    const span = document.createElement("span")
    span.className = "qc-section-label"
    span.textContent = text
    return span
  }
  const chip = (text: string, cls?: string, color?: string) => {
    const span = document.createElement("span")
    span.className = cls ? `qc-status ${cls}` : "qc-status"
    if (color) span.style.color = color
    span.textContent = text
    return span
  }

  let groupFilter = "all"
  let lastCheckedAt: number | undefined

  const repos = () => reposFromTrace(props.run?.execution_trace)
  const updates = () => packagesFromTrace(props.run?.execution_trace)

  const intro = document.createElement("div")
  intro.className = "qc-memory-intro"
  const title = document.createElement("h3")
  title.textContent = t("quantcode.gitgraph.title")
  const desc = document.createElement("p")
  desc.style.cssText = "margin:0;font-size:11px;color:var(--qc-muted);line-height:1.7;"
  desc.textContent = t("quantcode.gitgraph.intro")
  intro.append(sectionLabel("GITGRAPH"), title, desc)

  const renderToolbar = () => {
    const bar = document.createElement("div")
    bar.className = "qc-gitgraph-toolbar"
    bar.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:10px;"
    const check = document.createElement("button")
    check.type = "button"
    check.className = "qc-button qc-button-primary qc-gitgraph-check"
    check.disabled = typeof props.sendInstruction !== "function"
    check.textContent = t("quantcode.gitgraph.check")
    check.addEventListener("click", () => {
      if (typeof props.sendInstruction !== "function") return
      props.sendInstruction(buildRepoStatusInstruction())
      lastCheckedAt = Date.now()
      render()
    })
    bar.append(check)
    if (lastCheckedAt !== undefined) {
      const meta = document.createElement("span")
      meta.style.cssText = "color:var(--qc-muted);font-size:10px;"
      meta.textContent = `${t("quantcode.gitgraph.checked")} ${relativeTimeLabel(lastCheckedAt, lastCheckedAt)}`
      bar.append(meta)
    }
    return bar
  }

  /** 语言点：色点 + 语言名（色编码，图表感的最小单位）。 */
  const languageDot = (language: string | undefined) => {
    const holder = document.createElement("span")
    holder.className = "qc-gitgraph-lang"
    holder.style.cssText = "display:inline-flex;align-items:center;gap:5px;color:var(--qc-muted);font-size:9px;"
    const dot = document.createElement("i")
    dot.className = "qc-gitgraph-lang-dot"
    const color = LANGUAGE_COLORS[(language ?? "").toLowerCase()] ?? "var(--qc-muted)"
    dot.style.cssText = `width:7px;height:7px;border-radius:999px;background:${color};display:inline-block;flex:0 0 auto;`
    holder.append(dot)
    if (language) {
      const label = document.createElement("span")
      label.textContent = language
      holder.append(label)
    }
    return holder
  }

  const renderFilters = (groups: string[]) => {
    const filters = document.createElement("div")
    filters.className = "qc-gitgraph-filters"
    filters.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;"
    for (const key of ["all", ...groups]) {
      const selected = groupFilter === key
      const button = document.createElement("button")
      button.type = "button"
      button.className = "qc-gitgraph-filter"
      button.style.cssText =
        "padding:4px 9px;border-radius:999px;font-size:10px;cursor:pointer;" +
        (selected
          ? "background:var(--qc-ink);color:var(--qc-paper);border:1px solid var(--qc-ink);"
          : "background:transparent;color:var(--qc-ink);border:1px solid var(--qc-line);")
      button.textContent = key === "all" ? t("quantcode.admin.filterAll") : key
      button.setAttribute("aria-pressed", String(selected))
      button.addEventListener("click", () => {
        groupFilter = key
        render()
      })
      filters.append(button)
    }
    return filters
  }

  const renderRepoCard = (node: RepoNode, now: number) => {
    const updated = isRecentlyPushed(node.pushed_at, now)
    const card = document.createElement("div")
    card.className = "qc-gitgraph-repo"
    card.setAttribute("data-updated", String(updated))
    // 图表感：卡片左缘的"节点轨"，有更新 → 红节点 + 红缘
    card.style.cssText =
      "display:grid;grid-template-columns:14px minmax(0,1fr);gap:10px;padding:12px;border:1px solid var(--qc-line);" +
      "border-radius:12px;background:rgba(18,18,18,0.015);" +
      (updated ? `border-color:rgba(170,46,35,0.45);background:rgba(170,46,35,0.035);` : "")

    const nodeDot = document.createElement("i")
    nodeDot.className = "qc-gitgraph-node"
    nodeDot.style.cssText = `width:10px;height:10px;margin-top:4px;border-radius:999px;border:1px solid ${
      updated ? RED : "var(--qc-line)"
    };background:${updated ? RED : "transparent"};display:block;`
    card.append(nodeDot)

    const body = document.createElement("div")
    body.style.cssText = "display:grid;gap:6px;min-width:0;"

    const head = document.createElement("div")
    head.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:8px;"
    const name = document.createElement("strong")
    name.style.cssText = "font-size:12px;letter-spacing:0.01em;"
    name.textContent = node.name ?? "—"
    head.append(name)
    if (updated) head.append(chip(t("quantcode.gitgraph.updated"), "qc-status-error"))
    if (node.group) head.append(chip(node.group))
    body.append(head)

    const metaRow = document.createElement("div")
    metaRow.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:10px;"
    metaRow.append(languageDot(node.language))
    if (node.default_branch) {
      const branch = document.createElement("code")
      branch.className = "qc-artifact qc-gitgraph-branch"
      branch.style.cssText = "padding:2px 7px;font-size:9px;"
      branch.textContent = node.default_branch
      metaRow.append(branch)
    }
    body.append(metaRow)

    const foot = document.createElement("div")
    foot.style.cssText = "display:flex;align-items:baseline;justify-content:space-between;gap:12px;"
    const commit = document.createElement("p")
    commit.style.cssText = "margin:0;flex:1;min-width:0;overflow:hidden;font-size:10px;color:var(--qc-muted);text-overflow:ellipsis;white-space:nowrap;"
    commit.textContent = node.commit ?? "—"
    const time = document.createElement("span")
    time.className = "qc-gitgraph-time"
    time.style.cssText = `flex:0 0 auto;font-family:'SFMono-Regular',Consolas,monospace;font-size:8px;${updated ? `color:${RED};` : "color:var(--qc-muted);"}`
    time.textContent = relativeTimeLabel(node.pushed_at, now)
    foot.append(commit, time)
    body.append(foot)

    card.append(body)
    return card
  }

  const renderRepos = (now: number) => {
    const wrap = document.createElement("div")
    wrap.className = "qc-gitgraph-repos"
    wrap.style.cssText = "display:grid;gap:8px;"
    wrap.append(sectionLabel("REPO TREE"))

    const all = repos()
    if (all.length === 0) {
      const hint = document.createElement("p")
      hint.style.cssText = "margin:0;font-size:11px;color:var(--qc-muted);"
      hint.textContent = lastCheckedAt === undefined ? t("quantcode.gitgraph.empty") : t("quantcode.gitgraph.waiting")
      wrap.append(hint)
      return wrap
    }

    const groups = [...new Set(all.map((node) => node.group).filter((group): group is string => !!group))]
    wrap.append(renderFilters(groups))

    // 有更新置顶，其后按 pushed_at 倒序 —— 图表的"时间轴"读法
    const visible = all
      .filter((node) => groupFilter === "all" || node.group === groupFilter)
      .sort((a, b) => {
        const ua = isRecentlyPushed(a.pushed_at, now) ? 1 : 0
        const ub = isRecentlyPushed(b.pushed_at, now) ? 1 : 0
        if (ua !== ub) return ub - ua
        return (b.pushed_at ?? 0) - (a.pushed_at ?? 0)
      })
    const grid = document.createElement("div")
    grid.className = "qc-gitgraph-repo-list"
    for (const node of visible) grid.append(renderRepoCard(node, now))
    wrap.append(grid)
    return wrap
  }

  const renderPackages = () => {
    const wrap = document.createElement("div")
    wrap.className = "qc-gitgraph-packages"
    wrap.style.cssText = "display:grid;gap:8px;"
    wrap.append(sectionLabel("PACKAGE UPDATES"))

    const list = updates()
    if (list.length === 0) {
      const hint = document.createElement("p")
      hint.style.cssText = "margin:0;font-size:11px;color:var(--qc-muted);"
      const latest = adminToolResultEvents(props.run?.execution_trace, "admin_package_updates").at(-1)
      const verifiedEmpty = isRecord(latest) && latest.sync_status === "CONNECTED" && Array.isArray(latest.updates)
      hint.textContent = verifiedEmpty ? t("quantcode.gitgraph.packagesEmpty") : t("quantcode.gitgraph.empty")
      wrap.append(hint)
      return wrap
    }
    for (const update of list) {
      const row = document.createElement("div")
      row.className = "qc-gitgraph-package-row"
      row.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid rgba(18,18,18,0.09);"
      const name = document.createElement("strong")
      name.style.cssText = "font-size:11px;"
      name.textContent = update.name ?? "—"
      row.append(name, chip(t("quantcode.gitgraph.package"), "qc-status-waiting_for_human"))
      if (update.change) {
        const change = document.createElement("span")
        change.textContent = update.change
        row.append(change)
      }
      if (update.current || update.latest) {
        const versions = document.createElement("code")
        versions.className = "qc-artifact"
        versions.style.cssText = "padding:2px 7px;font-size:9px;"
        versions.textContent = `${update.current ?? "?"} → ${update.latest ?? "?"}`
        row.append(versions)
      }
      if (update.repo) {
        const repo = document.createElement("small")
        repo.style.cssText = "color:var(--qc-muted);font-size:9px;"
        repo.textContent = update.repo
        row.append(repo)
      }
      wrap.append(row)
    }
    return wrap
  }

  const render = () => {
    root.replaceChildren()
    root.append(intro, renderToolbar(), adminToolStatusView(props.run?.execution_trace, ["admin_repo_status", "admin_package_updates"]))
    const hasData = repos().length > 0 || updates().length > 0
    if (!hasData && lastCheckedAt === undefined) {
      const empty = document.createElement("div")
      empty.className = "qc-empty-state qc-gitgraph-empty"
      const index = document.createElement("span")
      index.className = "qc-empty-index"
      index.textContent = "F-09"
      const title = document.createElement("h3")
      title.textContent = t("quantcode.gitgraph.emptyTitle")
      const desc = document.createElement("p")
      desc.style.cssText = "margin:12px 0 0;color:var(--qc-muted);font-size:12px;line-height:1.7;max-width:340px;"
      desc.textContent = t("quantcode.gitgraph.empty")
      empty.append(index, title, desc)
      root.append(empty)
      return
    }
    root.append(renderRepos(Date.now()), renderPackages())
  }

  render()
  return root
}

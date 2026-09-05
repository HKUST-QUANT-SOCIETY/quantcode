import { describe, expect, test } from "bun:test"
import {
  GitGraphPanelView,
  isRecentlyPushed,
  packagesFromTrace,
  packagesFromPayload,
  reposFromPayload,
  reposFromTrace,
  RECENT_PUSH_MS,
  buildRepoStatusInstruction,
} from "./gitgraph-panel"
import { toEpochMs } from "./admin-console"
import type { RunAgentResult, TraceEvent } from "./result-contract"

/** 与 zh.ts 同文案的测试用 t（组件要求注入 i18n，见 quantcode.gitgraph.* / quantcode.admin.filterAll）。 */
const ZH: Record<string, string> = {
  "quantcode.gitgraph.title": "GitGraph 全库视图",
  "quantcode.gitgraph.intro": "组织全部 repo 的最新树状态：有更新（7 天内有 push）的节点标红置顶，可按组过滤。",
  "quantcode.gitgraph.check": "检查更新",
  "quantcode.gitgraph.checked": "上次检查",
  "quantcode.gitgraph.empty": "点击「检查更新」，Agent 调用 admin_repo_status / admin_package_updates 后，结果回流到这里；数据只来自真实通道，不造假。",
  "quantcode.gitgraph.emptyTitle": "数据通道尚未接通",
  "quantcode.gitgraph.waiting": "等待 admin_repo_status 结果回流…",
  "quantcode.gitgraph.updated": "有更新",
  "quantcode.gitgraph.packagesEmpty": "依赖全部最新。",
  "quantcode.gitgraph.package": "依赖",
  "quantcode.gitgraph.open": "查看 GitGraph",
  "quantcode.admin.filterAll": "全部",
}
const t = (key: string) => ZH[key] ?? key

const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString()

const REPOS_JSON = JSON.stringify({
  repos: [
    {
      name: "quant-engine",
      group: "factor",
      language: "TypeScript",
      default_branch: "main",
      last_commit_message: "feat: 中性化因子扫描加速",
      pushed_at: iso(1 * 86_400_000), // 1 天前 → 有更新
    },
    {
      name: "pit-valuation",
      group: "fundamental",
      language: "Python",
      default_branch: "develop",
      last_commit_message: "fix: PIT 时点对齐",
      pushed_at: iso(19 * 86_400_000), // 19 天前 → 无更新
    },
  ],
})
const PACKAGES_JSON = JSON.stringify({
  updates: [
    { repo: "quant-engine", name: "zod", current: "3.22.0", latest: "3.23.0" },
  ],
})

function traceRun(...events: TraceEvent[]): RunAgentResult {
  return { status: "completed", execution_trace: events }
}

describe("repo/p parsers", () => {
  test("reposFromTrace parses admin_repo_status tool_result; skips truncated results", () => {
    const run = traceRun(
      { type: "tool_result", data: { tool: "admin_repo_status", result: '{"repos": [{"name": "截断' } },
      { type: "tool_result", data: { tool: "admin_repo_status", result: REPOS_JSON } },
    )
    const repos = reposFromTrace(run.execution_trace)
    expect(repos).toHaveLength(2)
    expect(repos[0]).toMatchObject({
      name: "quant-engine",
      group: "factor",
      language: "TypeScript",
      default_branch: "main",
      commit: "feat: 中性化因子扫描加速",
    })
    expect(typeof repos[0]!.pushed_at).toBe("number")
  })

  test("packagesFromTrace parses admin_package_updates tool_result", () => {
    const updates = packagesFromTrace(traceRun({ type: "tool_result", data: { tool: "admin_package_updates", result: PACKAGES_JSON } }).execution_trace)
    expect(updates).toHaveLength(1)
    expect(updates[0]).toMatchObject({ repo: "quant-engine", name: "zod", current: "3.22.0", latest: "3.23.0" })
  })

  test("epoch seconds / ms / ISO all normalize through toEpochMs", () => {
    expect(toEpochMs(1_760_000_000)).toBe(1_760_000_000_000)
    expect(toEpochMs("2025-10-08T10:00:00Z")).toBe(Date.parse("2025-10-08T10:00:00Z"))
  })
})

describe("isRecentlyPushed (红点高亮阈值)", () => {
  const NOW = Date.parse("2025-10-09T12:00:00Z")

  test("RECENT_PUSH_MS is the 7-day threshold constant", () => {
    expect(RECENT_PUSH_MS).toBe(7 * 24 * 60 * 60 * 1000)
  })

  test("6 days → updated; 8 days → stale; missing pushed_at → not judged", () => {
    expect(isRecentlyPushed(NOW - 6 * 86_400_000, NOW)).toBe(true)
    expect(isRecentlyPushed(NOW - 8 * 86_400_000, NOW)).toBe(false)
    expect(isRecentlyPushed(undefined, NOW)).toBe(false)
  })

  test("threshold is tunable via parameter", () => {
    expect(isRecentlyPushed(NOW - 8 * 86_400_000, NOW, 30 * 86_400_000)).toBe(true)
  })
})

describe("buildRepoStatusInstruction (通道③)", () => {
  test("instructs the agent to call admin_repo_status and admin_package_updates", () => {
    const instruction = buildRepoStatusInstruction()
    expect(instruction).toContain("admin_repo_status")
    expect(instruction).toContain("admin_package_updates")
  })
})

describe("GitGraphPanelView", () => {
  test("no channel data → designed empty placeholder (no fake data)", () => {
    const view = GitGraphPanelView({ t, run: null })
    expect(view.querySelector(".qc-gitgraph-empty h3")?.textContent).toBe(ZH["quantcode.gitgraph.emptyTitle"])
    expect(view.querySelector(".qc-gitgraph-repo")).toBeNull()
    view.remove()
  })

  test("renders repo cards with name / language / branch / commit summary / relative time", () => {
    const view = GitGraphPanelView({ t, run: traceRun({ type: "tool_result", data: { tool: "admin_repo_status", result: REPOS_JSON } }) })
    const repos = [...view.querySelectorAll(".qc-gitgraph-repo")]
    expect(repos).toHaveLength(2)
    expect(repos[0]!.textContent).toContain("quant-engine")
    expect(repos[0]!.textContent).toContain("TypeScript")
    expect(repos[0]!.textContent).toContain("main")
    expect(repos[0]!.textContent).toContain("feat: 中性化因子扫描加速")
    expect(repos[0]!.querySelector(".qc-gitgraph-lang-dot")).not.toBeNull()
    expect(repos[1]!.textContent).toContain("pit-valuation")
    view.remove()
  })

  test("updated node (≤7 days) is flagged red and sorted first; stale node stays plain", () => {
    const view = GitGraphPanelView({ t, run: traceRun({ type: "tool_result", data: { tool: "admin_repo_status", result: REPOS_JSON } }) })
    const repos = [...view.querySelectorAll(".qc-gitgraph-repo")]
    expect(repos[0]!.getAttribute("data-updated")).toBe("true")
    expect(repos[0]!.textContent).toContain("有更新")
    expect(repos[0]!.className).toContain("qc-gitgraph-repo")
    expect(repos[1]!.getAttribute("data-updated")).toBe("false")
    expect(repos[1]!.textContent).not.toContain("有更新")
    view.remove()
  })

  test("group filter chips filter repo cards", () => {
    const view = GitGraphPanelView({ t, run: traceRun({ type: "tool_result", data: { tool: "admin_repo_status", result: REPOS_JSON } }) })
    const filters = [...view.querySelectorAll<HTMLElement>(".qc-gitgraph-filter")]
    expect(filters.map((el) => el.textContent)).toEqual(["全部", "factor", "fundamental"])
    filters.find((el) => el.textContent === "fundamental")!.click()
    const repos = [...view.querySelectorAll(".qc-gitgraph-repo")]
    expect(repos).toHaveLength(1)
    expect(repos[0]!.textContent).toContain("pit-valuation")
    view.remove()
  })

  test("检查更新 button routes the channel-③ instruction and records last check", () => {
    let sent = ""
    const view = GitGraphPanelView({
      t,
      run: null,
      sendInstruction: (content) => {
        sent = content
      },
    })
    view.querySelector<HTMLElement>(".qc-gitgraph-check")!.click()
    expect(sent).toContain("admin_repo_status")
    expect(sent).toContain("admin_package_updates")
    expect(view.textContent).toContain("上次检查")
    view.remove()
  })

  test("package updates render name + current → latest versions", () => {
    const view = GitGraphPanelView({ t, run: traceRun({ type: "tool_result", data: { tool: "admin_package_updates", result: PACKAGES_JSON } }) })
    const rows = [...view.querySelectorAll(".qc-gitgraph-package-row")]
    expect(rows).toHaveLength(1)
    expect(rows[0]!.textContent).toContain("zod")
    expect(rows[0]!.textContent).toContain("3.22.0 → 3.23.0")
    expect(rows[0]!.textContent).toContain("依赖")
    view.remove()
  })
})

test("renders canonical backend commit and dependency-file payloads", () => {
  expect(reposFromPayload({ repos: [{ name: "DataAccess", latest_commit: { message: "Fix PIT" } }] })[0].commit).toBe("Fix PIT")
  expect(packagesFromPayload({ updates: [{ repo: "DataAccess", files: [{ file: "pyproject.toml", message: "Update dependency" }] }] })).toEqual([
    { repo: "DataAccess", name: "pyproject.toml", change: "Update dependency" },
  ])
})

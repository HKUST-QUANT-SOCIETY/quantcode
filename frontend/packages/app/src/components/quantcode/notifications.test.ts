import { describe, expect, test } from "bun:test"
import { NotificationsBell, NotificationsPanel, pendingNotifications, updateNotifications, type QcNotification } from "./notifications"
import type { RunAgentResult } from "./result-contract"

function waiting(threadId: string, timestamp = 1725148800): RunAgentResult {
  return {
    status: "waiting_for_human",
    thread_id: threadId,
    timestamp,
    gate: { kind: "merge", reasons: ["merge_requires_approval"] },
    execution_trace: [{ type: "agent_start", seq: 0, data: { task: `研究任务 ${threadId.slice(0, 8)}` } }],
  }
}

describe("pendingNotifications", () => {
  test("no waiting_for_human runs → empty list (bell shows zero badge)", () => {
    expect(pendingNotifications([{ status: "completed", thread_id: "t1", timestamp: 1725148800 }], null)).toEqual([])
    const bell = NotificationsBell({ count: 0, onClick: () => {} })
    expect(bell.querySelector(".qc-rail-notif-badge")).toBeNull()
    bell.remove()
  })

  test("counts waiting_for_human runs from history except current trace thread, and adds the current trace gate itself", () => {
    const history = [waiting("t-old"), waiting("t-current"), { status: "completed", thread_id: "t-done" }]
    const trace = waiting("t-current")
    const items = pendingNotifications(history, trace)
    expect(items.length).toBe(2)
    expect(items.map((item) => item.thread_id)).toEqual(["t-old", "t-current"])
    const bell = NotificationsBell({ count: items.length, onClick: () => {} })
    expect(bell.querySelector(".qc-rail-notif-badge")?.textContent).toBe("2")
    bell.remove()
  })

  test("items carry task summary, human-readable time and waiting status", () => {
    const items = pendingNotifications([waiting("abcdefgh12", 1725148800)], null)
    expect(items[0]!.task).toBe("研究任务 abcdefgh")
    expect(items[0]!.status).toBe("待审批")
    expect(items[0]!.time).not.toBe("")
    expect(typeof items[0]!.time).toBe("string")
  })

  test("risk verdict waiting state is not presented as an approval notification", () => {
    const risk = waiting("risk-only")
    risk.gate = { kind: "risk", reasons: ["max_drawdown_breach"] }
    expect(pendingNotifications([risk], null)).toEqual([])
  })

  test("NotificationsPanel lists items with 去审批 action, empty state when cleared", () => {
    const panel = NotificationsPanel({ items: pendingNotifications([waiting("abcdefgh12")], null), onClose: () => {}, onApprove: () => {} })
    expect(panel.getAttribute("role")).toBe("dialog")
    expect(panel.querySelectorAll(".qc-notif-item").length).toBe(1)
    expect(panel.textContent).toContain("去审批")
    panel.remove()
    const empty = NotificationsPanel({ items: [], onClose: () => {}, onApprove: () => {} })
    expect(empty.querySelectorAll(".qc-notif-item").length).toBe(0)
    expect(empty.textContent).toContain("没有待处理")
    empty.remove()
  })

  test("clicking 去审批 fires onApprove with the thread id", () => {
    let approved = ""
    const panel = NotificationsPanel({ items: pendingNotifications([waiting("t-approve-me")], null), onClose: () => {}, onApprove: (id) => (approved = id) })
    ;(panel.querySelector(".qc-notif-item") as HTMLElement).click()
    expect(approved).toBe("t-approve-me")
    panel.remove()
  })
})

describe("updateNotifications (F-09 双类 pop)", () => {
  const NOW = Date.parse("2025-10-09T12:00:00Z")

  const runWithTrace = (tool: string, resultJson: string): RunAgentResult => ({
    status: "completed",
    thread_id: `run-${tool}`,
    execution_trace: [{ type: "tool_result", data: { tool, result: resultJson } }],
  })

  const REPOS = JSON.stringify({
    repos: [
      { name: "quant-engine", pushed_at: "2025-10-08T10:00:00Z", last_commit_message: "feat: 扫描加速" },
      { name: "pit-valuation", pushed_at: "2025-09-01T10:00:00Z" }, // 超阈值 → 不产生 pop
      { name: "", pushed_at: "2025-10-08T10:00:00Z" }, // 无名 → 跳过
    ],
  })
  const PACKAGES = JSON.stringify({
    updates: [{ name: "zod", current: "3.22.0", latest: "3.23.0", repo: "quant-engine" }],
  })

  test("repo pop only for nodes within the 7-day threshold; carries repo name + commit detail + relative time", () => {
    const items = updateNotifications([runWithTrace("admin_repo_status", REPOS)], { now: NOW })
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ kind: "repo", task: "quant-engine", detail: "feat: 扫描加速", status: "仓库有新提交" })
    expect(items[0]!.time).not.toBe("")
  })

  test("package pop carries dependency name and version transition", () => {
    const items = updateNotifications([runWithTrace("admin_package_updates", PACKAGES)], { now: NOW })
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ kind: "package", task: "zod", detail: "3.22.0 → 3.23.0", status: "依赖有新版本" })
  })

  test("both kinds deduplicate by id across repeated runs and keep the latest payload", () => {
    const older = JSON.stringify({ repos: [{ name: "quant-engine", pushed_at: "2025-10-05T10:00:00Z", last_commit_message: "旧提交" }] })
    const runs = [runWithTrace("admin_repo_status", older), runWithTrace("admin_repo_status", REPOS)]
    const items = updateNotifications(runs, { now: NOW })
    expect(items.filter((item) => item.kind === "repo")).toHaveLength(1)
    expect(items[0]!.detail).toBe("feat: 扫描加速")
  })

  test("no admin tool results → empty list (no fake reminders)", () => {
    expect(updateNotifications([{ status: "completed", thread_id: "t" }], { now: NOW })).toEqual([])
  })

  test("threshold is tunable via opts (stale repo pops when widened)", () => {
    expect(updateNotifications([runWithTrace("admin_repo_status", REPOS)], { now: NOW, thresholdMs: 90 * 86_400_000 }).length).toBe(2)
  })

  test("badge counts gate + pop notifications together", () => {
    const gate = pendingNotifications([waiting("t-gate")], null)
    const pops: QcNotification[] = updateNotifications(
      [runWithTrace("admin_repo_status", REPOS), runWithTrace("admin_package_updates", PACKAGES)],
      { now: NOW },
    )
    const all = [...gate, ...pops]
    expect(all).toHaveLength(3)
    const bell = NotificationsBell({ count: all.length, onClick: () => {} })
    expect(bell.querySelector(".qc-rail-notif-badge")?.textContent).toBe("3")
    bell.remove()
  })

  test("pop rows render 查看 GitGraph action; click fires onOpenGitgraph (not onApprove)", () => {
    let opened = false
    let approved = ""
    const pops = updateNotifications([runWithTrace("admin_repo_status", REPOS)], { now: NOW })
    const panel = NotificationsPanel({
      items: pops,
      onClose: () => {},
      onApprove: (id) => (approved = id),
      onOpenGitgraph: () => (opened = true),
    })
    const row = panel.querySelector(".qc-notif-item") as HTMLElement
    expect(row.textContent).toContain("quant-engine")
    expect(row.textContent).toContain("查看 GitGraph")
    row.click()
    expect(opened).toBe(true)
    expect(approved).toBe("")
    panel.remove()
  })

  test("gate rows still route to 去审批 with injected i18n for pop labels", () => {
    const panel = NotificationsPanel({
      items: pendingNotifications([waiting("t-gate")], null),
      onClose: () => {},
      onApprove: () => {},
      t: (key) => (key === "quantcode.pop.viewGitgraph" ? "Open GitGraph" : key),
    })
    expect(panel.querySelector(".qc-notif-item")!.textContent).toContain("去审批")
    panel.remove()
  })
})

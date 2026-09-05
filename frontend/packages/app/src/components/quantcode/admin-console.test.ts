import { describe, expect, test } from "bun:test"
import {
  AdminConsoleView,
  adminToolStatusView,
  adminStatusChipClass,
  adminStatusLabel,
  buildAdminQueryInstruction,
  errorsFromTrace,
  groupRuns,
  relativeTimeLabel,
  runsFromTrace,
  toEpochMs,
  type AdminErrorRecord,
  type AdminRunRecord,
} from "./admin-console"
import type { RunAgentResult, TraceEvent } from "./result-contract"
import { isAdminRole } from "./roles"

/** 与 zh.ts 同文案的测试用 t（组件要求注入 i18n，见 quantcode.admin.* / quantcode.gitgraph.* keys）。 */
const ZH: Record<string, string> = {
  "quantcode.admin.title": "Admin 中枢",
  "quantcode.admin.intro": "语义查询台：用自然语言询问组织运行状态，Agent 调用 admin_* 元工具后，结果按组 → 人 → 状态回流至此。",
  "quantcode.admin.inputPlaceholder": "询问：最近每组工作情况 / 各模块运行情况 / 各组错误记录…",
  "quantcode.admin.send": "发送查询",
  "quantcode.admin.presetRuns": "最近每组工作情况",
  "quantcode.admin.presetModules": "各模块运行情况",
  "quantcode.admin.presetErrors": "各组错误记录",
  "quantcode.admin.sent": "查询指令已发送，admin_* 结果回流后自动呈现。",
  "quantcode.admin.waiting": "等待 admin_* 结果回流…",
  "quantcode.admin.emptyTitle": "查询通道尚未接通",
  "quantcode.admin.empty": "发送语义查询后，Agent 调用 admin_list_runs / admin_errors 的结果会回流到这里；数据只来自真实通道，不造假。",
  "quantcode.admin.errorsEmpty": "暂无错误记录，各组运行正常。",
  "quantcode.admin.filterAll": "全部",
  "quantcode.admin.reportsEntry": "报告管理",
  "quantcode.admin.tasksEntry": "任务管理",
  "quantcode.admin.q2Badge": "Q2",
  "quantcode.gitgraph.open": "查看 GitGraph",
}
const t = (key: string) => ZH[key] ?? key

const RUNS_JSON = JSON.stringify({
  runs: [
    { thread_id: "t-1", group: "factor", user: "chen", status: "completed", task: "PB–ROE 中性化扫描", timestamp: 1_760_000_000 },
    { thread_id: "t-2", group: "factor", user: "chen", status: "waiting_for_human", timestamp: 1_760_000_100 },
    { thread_id: "t-3", group: "risk", user: "wang", status: "error", task: "回撤复核", timestamp: 1_760_000_200 },
  ],
})
const ERRORS_JSON = JSON.stringify({
  errors: [
    { thread_id: "t-3", group: "risk", user: "wang", type: "ToolTimeout", message: "回撤复核超时", timestamp: 1_760_000_200 },
    { thread_id: "t-4", group: "factor", user: "chen", type: "DataMissing", message: "行情缺数", timestamp: 1_760_000_300 },
  ],
})

function traceRun(...events: TraceEvent[]): RunAgentResult {
  return { status: "completed", execution_trace: events }
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe("admin trace parsers", () => {
  test("runsFromTrace extracts admin_list_runs tool_result records; skips truncated and other tools", () => {
    const run = traceRun(
      { type: "tool_result", data: { tool: "run_agent", result: RUNS_JSON } },
      { type: "tool_result", data: { tool: "admin_list_runs", result: '{"runs": [{"name": "截断' } },
      { type: "tool_result", data: { tool: "admin_list_runs", result: RUNS_JSON } },
    )
    const runs = runsFromTrace(run.execution_trace)
    expect(runs).toHaveLength(3)
    expect(runs[0]).toMatchObject({ group: "risk", user: "wang", status: "error" })
    expect(runs[0]!.timestamp).toBe(1_760_000_200_000)
  })

  test("runsFromPayload accepts bare arrays and field aliases (owner/state)", () => {
    const runs = runsFromTrace(
      traceRun({
        type: "tool_result",
        data: { tool: "admin_list_runs", result: JSON.stringify([{ group: "model", owner: "li", state: "completed" }]) },
      }).execution_trace,
    )
    expect(runs).toHaveLength(1)
    expect(runs[0]).toMatchObject({ group: "model", user: "li", status: "completed" })
  })

  test("errorsFromTrace extracts records with type tags", () => {
    const errors = errorsFromTrace(traceRun({ type: "tool_result", data: { tool: "admin_errors", result: ERRORS_JSON } }).execution_trace)
    expect(errors).toHaveLength(2)
    expect(errors[0]!.type).toBe("DataMissing")
    expect(errors[0]!.message).toBe("行情缺数")
  })

  test("toEpochMs normalizes epoch seconds / ms / ISO and rejects junk", () => {
    expect(toEpochMs(1_760_000_000)).toBe(1_760_000_000_000)
    expect(toEpochMs(1_760_000_000_000)).toBe(1_760_000_000_000)
    expect(toEpochMs("2025-10-09T00:00:00Z")).toBe(Date.parse("2025-10-09T00:00:00Z"))
    expect(toEpochMs("not-a-date")).toBeUndefined()
    expect(toEpochMs(undefined)).toBeUndefined()
  })

  test("relativeTimeLabel: 刚刚 / 分钟前 / 小时前 / 天前 / 日期", () => {
    const now = Date.now()
    expect(relativeTimeLabel(now - 10_000, now)).toBe("刚刚")
    expect(relativeTimeLabel(now - 3 * 60_000, now)).toBe("3 分钟前")
    expect(relativeTimeLabel(now - 5 * 3_600_000, now)).toBe("5 小时前")
    expect(relativeTimeLabel(now - 2 * 86_400_000, now)).toBe("2 天前")
    expect(relativeTimeLabel(now - 9 * 86_400_000, now)).toContain("月")
    expect(relativeTimeLabel(undefined, now)).toBe("—")
  })
})

describe("groupRuns (组 → 人 → 状态)", () => {
  const runs: AdminRunRecord[] = [
    { group: "factor", user: "chen", status: "completed" },
    { group: "factor", user: "chen", status: "error" },
    { group: "risk", user: "wang", status: "waiting_for_human" },
  ]

  test("aggregates by group then user with completed/failed counts", () => {
    const grouped = groupRuns(runs)
    expect(grouped).toHaveLength(2)
    const factor = grouped.find((entry) => entry.group === "factor")!
    expect(factor.users).toHaveLength(1)
    expect(factor.users[0]!.user).toBe("chen")
    expect(factor.users[0]!.runs).toHaveLength(2)
    expect(factor.total).toBe(2)
    expect(factor.completed).toBe(1)
    expect(factor.failed).toBe(1)
  })

  test("missing group/user fall back to 未分组 / —", () => {
    const grouped = groupRuns([{ status: "completed" }])
    expect(grouped[0]!.group).toBe("未分组")
    expect(grouped[0]!.users[0]!.user).toBe("—")
  })

  test("status chip class + label mapping", () => {
    expect(adminStatusChipClass("completed")).toBe("qc-status-completed")
    expect(adminStatusChipClass("waiting_for_human")).toBe("qc-status-waiting_for_human")
    expect(adminStatusChipClass("error")).toBe("qc-status-error")
    expect(adminStatusChipClass("running")).toBe("")
    expect(adminStatusLabel("completed")).toBe("已完成")
    expect(adminStatusLabel(undefined)).toBe("运行中")
  })
})

describe("buildAdminQueryInstruction (通道③)", () => {
  test("instructs the agent to call admin_list_runs and admin_errors with the query", () => {
    const instruction = buildAdminQueryInstruction("最近每组工作情况")
    expect(instruction).toContain("admin_list_runs")
    expect(instruction).toContain("admin_errors")
    expect(instruction).toContain("最近每组工作情况")
  })
})

describe("AdminConsoleView", () => {
  test("no channel data → designed empty placeholder (no fake data)", () => {
    const view = AdminConsoleView({ t, run: null })
    expect(view.querySelector(".qc-admin-empty h3")?.textContent).toBe(ZH["quantcode.admin.emptyTitle"])
    expect(view.querySelector(".qc-admin-group")).toBeNull()
    view.remove()
  })

  test("trace channel renders 组 → 人 → 状态 grouped cards with status chips", () => {
    const view = AdminConsoleView({ t, run: traceRun({ type: "tool_result", data: { tool: "admin_list_runs", result: RUNS_JSON } }) })
    const groups = [...view.querySelectorAll(".qc-admin-group summary strong")].map((el) => el.textContent)
    expect(groups).toEqual(["risk", "factor"])
    const userRows = [...view.querySelectorAll(".qc-admin-user-row")]
    expect(userRows.length).toBe(3)
    expect(userRows[1]!.textContent).toContain("chen")
    expect(userRows[2]!.textContent).toContain("已完成")
    expect(view.textContent).toContain("PB–ROE 中性化扫描")
    view.remove()
  })

  test("error timeline renders type tags, group filter chips filter rows", () => {
    const view = AdminConsoleView({
      t,
      run: traceRun(
        { type: "tool_result", data: { tool: "admin_errors", result: ERRORS_JSON } },
      ),
    })
    expect(view.querySelectorAll(".qc-admin-error-row")).toHaveLength(2)
    expect(view.textContent).toContain("ToolTimeout")

    const filters = [...view.querySelectorAll<HTMLElement>(".qc-admin-filter")]
    expect(filters.map((el) => el.textContent)).toEqual(["全部", "factor", "risk"])
    filters.find((el) => el.textContent === "risk")!.click()
    expect(view.querySelectorAll(".qc-admin-error-row")).toHaveLength(1)
    expect(view.querySelector(".qc-admin-error-row")!.textContent).toContain("回撤复核超时")
    view.remove()
  })

  test("preset chip fills input; send routes instruction through sendInstruction and shows sent note", () => {
    let sent = ""
    const view = AdminConsoleView({ t, run: null, sendInstruction: (content) => (sent = content) })
    const preset = view.querySelector<HTMLElement>(".qc-admin-preset")!
    expect(preset.textContent).toBe("最近每组工作情况")
    preset.click()
    expect((view.querySelector<HTMLInputElement>(".qc-admin-query-input")!.value)).toBe("最近每组工作情况")
    view.querySelector<HTMLElement>(".qc-admin-send")!.click()
    expect(sent).toContain("admin_list_runs")
    expect(sent).toContain("最近每组工作情况")
    expect(view.querySelector(".qc-admin-sent-note")?.textContent).toBe(ZH["quantcode.admin.sent"])
    view.remove()
  })

  test("manual typing enables the send button; empty query keeps it disabled", () => {
    const view = AdminConsoleView({ t, run: null, sendInstruction: () => {} })
    const input = view.querySelector<HTMLInputElement>(".qc-admin-query-input")!
    const send = view.querySelector<HTMLButtonElement>(".qc-admin-send")!
    expect(send.disabled).toBe(true)
    input.value = "各模块运行情况"
    input.dispatchEvent(new Event("input"))
    expect(send.disabled).toBe(false)
    view.remove()
  })

  test("management entries open GitGraph, reports and task history", () => {
    let opened = false
    const history: string[] = []
    const view = AdminConsoleView({ t, run: null, onOpenGitgraph: () => (opened = true), onOpenHistory: mode => history.push(mode) })
    view.querySelector<HTMLElement>(".qc-admin-open-gitgraph")!.click()
    expect(opened).toBe(true)
    for (const name of ["报告与产物", "任务管理"]) {
      const button = Array.from(view.querySelectorAll("button")).find(item => item.textContent === name)!
      expect(button.disabled).toBe(false)
      button.click()
    }
    expect(history).toEqual(["reports", "tasks"])
    view.remove()
  })
})

describe("admin role visibility (F-09)", () => {
  test("isAdminRole gates the nav item: admin yes, approver/analyst no", () => {
    expect(isAdminRole("admin")).toBe(true)
    expect(isAdminRole("风控负责人")).toBe(false)
    expect(isAdminRole("Quant Society Member")).toBe(false)
  })
})


test("latest snapshot replaces stale rows and retains backend actor_id/ts", () => {
  const events: TraceEvent[] = [
    { type: "tool_result", data: { tool: "admin_list_runs", result: RUNS_JSON } },
    { type: "tool_result", data: { tool: "admin_list_runs", result: JSON.stringify({ runs: [
      { thread_id: "latest", actor_id: "roster-actor", ts: 1_760_000_400, status: "running" },
    ] }) } },
  ]
  expect(runsFromTrace(events)).toHaveLength(1)
  expect(runsFromTrace(events)[0]).toMatchObject({ user: "roster-actor", timestamp: 1_760_000_400_000 })
  events.push({ type: "tool_result", data: { tool: "admin_list_runs", result: '{"runs":[' } })
  expect(runsFromTrace(events)).toEqual([])
  expect(adminToolStatusView(events, ["admin_list_runs"]).textContent).toContain("UNAVAILABLE")
})

test("service failure retains status and clears earlier success", () => {
  const events: TraceEvent[] = [
    { type: "tool_result", data: { tool: "admin_errors", result: ERRORS_JSON } },
    { type: "tool_result", data: { tool: "admin_errors", result: JSON.stringify({ ok: false, error: "Permission denied", status: "FORBIDDEN" }) } },
  ]
  expect(errorsFromTrace(events)).toEqual([])
  expect(adminToolStatusView(events, ["admin_errors"]).textContent).toContain("Permission denied")
})

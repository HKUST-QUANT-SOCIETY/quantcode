import { expect, test, type Page } from "@playwright/test"

// A production bundle normally shares its origin with the host. A static
// artifact preview can select an existing host through the normal saved setting.
test.beforeEach(async ({ page }) => {
  const server = process.env.PLAYWRIGHT_TARGET_SERVER
  if (server) await page.addInitScript(url => {
    localStorage.setItem("opencode.settings.dat:defaultServerUrl", url)
    localStorage.setItem("opencode.global.dat:server", JSON.stringify({
      list: [{ type: "http", http: { url } }], projects: {}, lastProject: {},
    }))
  }, server)
})

for (const mode of ["approval", "recovery"] as const) {
  test(`${mode}: rejected submission remains retryable and only acceptance disables it`, async ({ page }) => {
    await mockContext(page, "analyst")
    await page.goto("/")
    await page.evaluate(async mode => {
      // Render the actual Vite-compiled component with controlled submission
      // outcomes. No research task or approval reaches the running server.
      const path = `/src/components/quantcode/${mode === "approval" ? "approval-queue" : "run-history"}.tsx`
      const source = await (await fetch(path)).text()
      const renderer = source.match(/from "([^"]*solid-js_web\.js[^\"]*)"/)?.[1]
      if (!renderer) throw new Error("Vite Solid renderer was not found")
      const { render } = await import(renderer)
      const component = await import(path)
      const root = document.createElement("div")
      root.setAttribute("data-submission-test", mode)
      root.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:white;overflow:auto;padding:24px"
      document.body.append(root)
      let attempts = 0
      const submit = async () => ++attempts > 1
      const run = { thread_id: "fixture-run", checkpoint_id: "fixture-cp", task: "Retry fixture", status: "error" }
      render(() => mode === "approval"
        ? component.ApprovalQueue({ scope: "fixture", decide: submit,
          fetcher: async () => ({ gates: [{ ...run, actor_id: "fixture", gate: { gate_id: "fixture-gate", kind: "permission" } }], next_cursor: null }) })
        : component.RunHistoryView({ scope: "fixture", ready: true, onRecover: submit,
          fetcher: async (tool: string) => tool === "list_run_history" ? { runs: [run], next_cursor: null }
            : { ...run, read_only: true, can_resume: true, messages: [], checkpoints: [run.checkpoint_id] } }), root)
    }, mode)
    const root = page.locator(`[data-submission-test="${mode}"]`)
    if (mode === "recovery") await root.getByRole("button", { name: /Retry fixture/ }).click()
    const action = root.getByRole("button", { name: mode === "approval" ? "批准" : "从最新检查点恢复任务", exact: true })
    await action.click()
    await expect(root.getByRole("alert")).toContainText("请求未提交")
    await expect(action).toBeEnabled()
    await action.click()
    if (mode === "approval") {
      await expect(action).toBeDisabled()
      await expect(root.getByRole("status")).toContainText("已请求处理")
    } else {
      await expect(root.getByRole("button", { name: "已请求恢复，请查看当前任务反馈", exact: true })).toBeDisabled()
    }
    await expect(root.getByRole("alert")).toHaveCount(0)
  })
}

// Real branded app and HTTP server, deterministic MCP responses. These prove
// browser wiring and role presentation, not SSH or production authorization.
async function mockContext(page: Page, role?: "analyst" | "approver" | "admin", group = "factor") {
  await page.route("**/experimental/quantcode/tool?*", async (route) => {
    const tool = new URL(route.request().url()).searchParams.get("tool")
    const payload = tool === "session_context"
      ? role ? { group, role, actor_id: "browser-fixture", workspace_id: "audit" } : { error: "Authentication required" }
      : tool === "list_skills" ? { skills: [{ id: "factor-evaluation", name: "Factor Evaluation" }] }
      : tool === "list_algorithms" ? { algorithms: [] }
      : tool === "search_memory" ? { status: "EMPTY", hits: [] }
      : tool === "list_capabilities" ? { capabilities: [] }
      : tool === "get_gitgraph" ? { repos: [], sync_status: "CONNECTED" }
      : tool === "list_pops" ? { pops: [], next_cursor: null, unread_count: 0 }
      : tool === "list_distill_candidates" ? { candidates: [] }
      : tool === "list_pending_gates" ? { gates: [], next_cursor: null }
      : { error: "Unavailable fixture service" }
    await route.fulfill({ json: payload })
  })
}

test("history remains read-only, pages events and blocks uncertain recovery", async ({ page }) => {
  await mockContext(page, "analyst")
  const requested: string[] = []
  await page.route("**/experimental/quantcode/tool?*", async route => {
    const query = new URL(route.request().url()).searchParams
    const tool = query.get("tool")
    if (tool !== "list_run_history" && tool !== "get_run_history") return route.fallback()
    requested.push(tool)
    if (tool === "list_run_history") return route.fulfill({ json: { runs: [{ thread_id: "history-1", checkpoint_id: "cp-2", task: "核对回执测试任务", status: "error" }], next_cursor: null } })
    const next = query.get("trace_cursor") === "1"
    await route.fulfill({ json: {
      thread_id: "history-1", checkpoint_id: "cp-2", group: "factor", task: "核对回执测试任务",
      read_only: true, can_resume: false, recovery_block_reason: "存在未确认的外部调用",
      checkpoints: ["cp-2", "cp-1"], messages: [{ type: "ai", content: "保存的结果内容" }],
      artifacts: ["artifact://saved-report"],
      unresolved_operations: [{ call_id: "call-1", digest: "a".repeat(64), receipt_status: "STARTED", tool: "write_report" }],
      timeline: { events: [{ type: "tool_result", data: next ? "第二页事件" : "第一页事件" }], exists: true,
        next_cursor: next ? 2 : 1, has_more: !next, damaged_lines: next ? 1 : 0 },
    } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "执行记录", exact: true }).click()
  await page.getByRole("button", { name: /核对回执测试任务/ }).click()
  const detail = page.getByLabel("历史详情", { exact: true })
  await expect(detail).toContainText("保存的结果内容")
  await expect(detail).toContainText("artifact://saved-report")
  await expect(detail).toContainText("无法恢复：存在未确认的外部调用")
  await expect(detail.getByRole("button", { name: "从最新检查点恢复任务" })).toHaveCount(0)
  await detail.getByRole("button", { name: "加载更多执行事件" }).click()
  await expect(detail).toContainText("第一页事件")
  await expect(detail).toContainText("第二页事件")
  await expect(detail).toContainText("1 条损坏事件")
  expect(requested).toEqual(["list_run_history", "get_run_history", "get_run_history"])
})

test("capability refresh replaces stale state and preserves search focus", async ({ page }) => {
  await mockContext(page, "analyst")
  let requests = 0
  await page.route("**/experimental/quantcode/tool?*", async route => {
    if (new URL(route.request().url()).searchParams.get("tool") !== "list_capabilities") return route.fallback()
    requests++
    await route.fulfill({ json: { capabilities: [{ id: "fixture-component", name: "Catalog component fixture",
      integration_status: requests === 1 ? "UNVERIFIED" : "UNAVAILABLE", maturity_status: "STAGING",
      inputs: ["FixtureInput"], outputs: ["FixtureOutput"], depends_on: ["fixture-data"],
    }] } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "能力目录", exact: true }).click()
  const catalog = page.locator(".qc-capability-catalog")
  await expect(catalog).toContainText("UNVERIFIED")
  await catalog.getByRole("searchbox").fill("FixtureInput")
  await expect(catalog.getByRole("searchbox")).toBeFocused()
  await catalog.getByRole("button", { name: "刷新能力目录" }).click()
  await expect(catalog).toContainText("UNAVAILABLE")
  await expect(catalog).not.toContainText("UNVERIFIED")
  await expect(catalog.getByRole("searchbox")).toHaveValue("FixtureInput")
  await expect(catalog).toContainText("FixtureOutput")
})

test("GitGraph pages commits and saves personal Pop acknowledgement", async ({ page }) => {
  await mockContext(page, "analyst")
  let pop = { pop_id: "pop-fixture", change_summary: "Fixture branch changed", read_status: "unread", ack_status: "pending", observed_at: "2026-09-05T00:00:00Z" }
  const updates: unknown[] = []
  await page.route("**/experimental/quantcode/tool?*", async route => {
    const tool = new URL(route.request().url()).searchParams.get("tool")
    if (tool === "list_pops") return route.fulfill({ json: { pops: [pop], unread_count: pop.read_status === "unread" ? 1 : 0, next_cursor: null } })
    if (tool !== "get_gitgraph") return route.fallback()
    await route.fulfill({ json: { repos: [{ repo: "fixture/repository", default_branch: "main", observed_at: "2026-09-05", sync_status: "CONNECTED", errors: [],
      heads: [{ branch: "main", sha: "commit-000", changed: true }], dependency_changes: [],
      commit_nodes: Array.from({ length: 105 }, (_, i) => ({ sha: `commit-${String(i).padStart(3, "0")}`, message: `Fixture commit ${i}`, parents: i < 104 ? [`commit-${String(i + 1).padStart(3, "0")}`] : [] })),
    }] } })
  })
  await page.route("**/experimental/quantcode/pop", async route => {
    updates.push(route.request().postDataJSON())
    pop = { ...pop, read_status: "read", ack_status: "acknowledged" }
    await route.fulfill({ json: { pop, unread_count: 0 } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "GitGraph", exact: true }).click()
  await page.getByText("fixture/repository · 1 个分支 · CONNECTED", { exact: true }).click()
  const graph = page.getByRole("img", { name: "提交父子关系图，分页显示" })
  await expect(graph.locator("circle")).toHaveCount(100)
  await page.getByRole("button", { name: "下一页提交", exact: true }).click()
  await expect(graph.locator("circle")).toHaveCount(5)
  await expect(page.getByRole("button", { name: "下一页提交", exact: true })).toBeDisabled()
  await page.getByRole("button", { name: "确认更新", exact: true }).click()
  await expect(page.getByRole("button", { name: "已确认", exact: true })).toBeDisabled()
  expect(updates).toEqual([{ pop_id: "pop-fixture", read: true, ack: true }])
  await page.getByRole("button", { name: "刷新", exact: true }).click()
  await expect(page.getByRole("button", { name: "已确认", exact: true })).toBeDisabled()
})

test("unbound identity cannot submit or claim an SSH connection", async ({ page }) => {
  await mockContext(page)
  await page.goto("/")
  await expect(page.getByRole("textbox", { name: "今天研究什么？" })).toBeVisible()
  await page.getByRole("textbox", { name: "今天研究什么？" }).fill("查询可见能力")
  await expect(page.getByRole("button", { name: "开始研究", exact: true })).toBeDisabled()
  await expect(page.locator(".qc-lens-meta-row").first()).toContainText("未认证")
  await expect(page.locator(".qc-lens-meta-row").first()).not.toContainText("factor")
  await expect(page.locator(".qc-lens-meta-row").last()).not.toContainText("SSH:")
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await expect(page.locator(".qc-setting-row").first()).toContainText("未认证")
  await expect(page.locator('input[type="password"], textarea[name*="key"]')).toHaveCount(0)
})

for (const role of ["analyst", "approver", "admin"] as const) {
  test(`${role}: bound group, published skills and scoped navigation`, async ({ page }) => {
    await mockContext(page, role)
    await page.goto("/")
    await expect(page.locator(".qc-identity")).toContainText("browser-fixture")
    await expect(page.getByRole("combobox", { name: "选择 Skill" })).toHaveValue("factor-evaluation")
    await expect(page.getByRole("button", { name: "GitGraph", exact: true })).toBeVisible()
    await expect(page.getByRole("button", { name: "Admin 中枢", exact: true })).toHaveCount(role === "admin" ? 1 : 0)
    await expect(page.locator('select[name="group"], #qc-group')).toHaveCount(0)
    await page.getByRole("button", { name: "Memory", exact: true }).click()
    await expect(page.locator(".qc-memory-search-input")).toBeVisible()
    await page.locator(".qc-memory-search-input").fill("evaluator")
    await page.locator(".qc-memory-search-input").press("Enter")
    await expect(page.locator(".qc-memory-results")).toHaveAttribute("aria-busy", "false")
    await expect(page.locator(".qc-memory-search-input")).toBeFocused()
    await expect(page.locator(".qc-memory-hit-row")).toHaveCount(0)
    await expect(page.locator(".qc-memory-empty")).toBeVisible()
    await page.screenshot({ path: `e2e/test-results/quantcode/${role}-memory.png` })
  })
}

test("HTTP failure in memory is unavailable, never an empty success", async ({ page }) => {
  await mockContext(page, "analyst")
  await page.route("**/experimental/quantcode/tool?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("tool") !== "search_memory") return route.fallback()
    await route.fulfill({ status: 503, json: { error: "Service unavailable" } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "Memory", exact: true }).click()
  await page.locator(".qc-memory-search-input").fill("evaluator")
  await page.locator(".qc-memory-search-input").press("Enter")
  await expect(page.locator(".qc-memory-results")).toHaveAttribute("aria-busy", "false")
  await expect(page.locator(".qc-memory-empty")).toContainText(/未接通|not connected/)
  await expect(page.locator(".qc-memory-hit-row")).toHaveCount(0)
})

for (const viewport of [{ width: 900, height: 650 }, { width: 1440, height: 900 }]) {
  test(`long results scroll inside an inset panel at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await mockContext(page, "admin")
    await page.route("**/experimental/quantcode/tool?*", async (route) => {
      if (new URL(route.request().url()).searchParams.get("tool") !== "search_memory") return route.fallback()
      await route.fulfill({ json: { status: "CONNECTED", hits: Array.from({ length: 30 }, (_, i) => ({
        path: `fixture/knowledge-${i}.md`, scope: "groups", scope_id: "factor",
        snippet: "Verified evaluator contract fixture for browser scrolling tests", score: 30 - i,
      })) } })
    })
    await page.goto("/")
    await expect(page.locator(".qc-identity")).toContainText("browser-fixture")
    await expect(page.getByRole("button", { name: "QuantCode 设置", exact: true })).toBeInViewport()
    await page.getByRole("button", { name: "Memory", exact: true }).click()
    await page.locator(".qc-memory-search-input").fill("evaluator")
    await page.locator(".qc-memory-search-input").press("Enter")
    await expect(page.locator(".qc-memory-hit-row")).toHaveCount(30)
    // Measure in one browser frame: the entering panel translates for 220 ms.
    // Separate boundingBox calls can compare two different animation frames.
    const inset = await page.locator(".qc-memory-search-input").evaluate(input =>
      input.getBoundingClientRect().x - input.closest(".qc-detail-panel")!.getBoundingClientRect().x)
    expect(inset).toBeGreaterThanOrEqual(20)
    expect(await page.locator(".qc-memory-query").evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
    await page.locator(".qc-memory-hit-row").last().scrollIntoViewIfNeeded()
    await expect(page.locator(".qc-memory-hit-row").last()).toBeInViewport()
    await expect(page.getByRole("button", { name: "关闭详情", exact: true })).toBeInViewport()
    await page.screenshot({ path: `e2e/test-results/quantcode/memory-${viewport.width}.png` })
  })
}


for (const group of ["infra", "agent"]) {
  test(`${group}: authenticated team group is accepted without admin elevation`, async ({ page }) => {
    await mockContext(page, "analyst", group)
    await page.goto("/")
    await expect(page.locator(".qc-identity")).toContainText(group)
    await expect(page.getByRole("button", { name: "GitGraph", exact: true })).toBeVisible()
    await expect(page.getByRole("button", { name: "Admin 中枢", exact: true })).toHaveCount(0)
    await page.getByRole("textbox", { name: "今天研究什么？" }).fill("查询本组授权仓库")
    await expect(page.getByRole("button", { name: "开始研究", exact: true })).toBeEnabled()
  })
}

import { expect, test, type Page } from "@playwright/test"

test.use({ locale: "zh-CN" })

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
  await page.route("**/experimental/capabilities*", route => route.fulfill({ json: {
    backgroundSubagents: false, quantcodeUnifiedRuntime: true,
  } }))
  await page.route("**/experimental/quantcode/identities*", route => route.fulfill({ json: { identities: [], error: "No fixture identity configured" } }))
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

test("fresh QuantCode settings can add, edit and select a research server", async ({ page }) => {
  const base = process.env.PLAYWRIGHT_TARGET_SERVER ?? "http://127.0.0.1:5896"
  const managed = `${base}/managed-qa`
  await page.route("**/managed-qa/**", async route => {
    const url = new URL(route.request().url())
    url.pathname = url.pathname.replace("/managed-qa", "")
    if (url.pathname === "/global/event") {
      await route.fulfill({ contentType: "text/event-stream", body: "" })
      return
    }
    const response = await route.fetch({ url: url.href })
    await route.fulfill({ response })
  })
  await mockContext(page)
  await page.goto("/")
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await page.getByRole("button", { name: "管理服务器", exact: true }).click()
  await page.getByRole("button", { name: "添加服务器", exact: true }).click()
  await page.getByRole("textbox", { name: "服务器 URL", exact: true }).fill(managed)
  await page.getByRole("textbox", { name: "服务器名称（可选）", exact: true }).fill("QA managed server")
  await page.getByRole("button", { name: "添加服务器", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await expect(page.locator("#qc-settings-server")).toHaveValue(managed)
  await page.getByRole("button", { name: "管理服务器", exact: true }).click()
  const row = page.locator('[data-slot="list-item"]').filter({ hasText: "QA managed server" })
  await row.getByRole("button").click()
  await page.getByRole("menuitem", { name: "编辑", exact: true }).click()
  await page.getByRole("textbox", { name: "服务器名称（可选）", exact: true }).fill("QA renamed server")
  await page.getByRole("button", { name: "保存", exact: true }).click()
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await expect(page.locator("#qc-settings-server option").filter({ hasText: "QA renamed server" })).toHaveCount(1)
  await page.locator("#qc-settings-server").selectOption(base)
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await expect(page.locator("#qc-settings-server")).toHaveValue(base)
  await page.locator("#qc-settings-server").selectOption(managed)
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await expect(page.locator("#qc-settings-server")).toHaveValue(managed)
})

for (const viewport of [{ width: 900, height: 650 }, { width: 1440, height: 900 }]) {
  test(`identity roster binding, reopen and logout retry at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await mockContext(page)
    let active: string | undefined
    let logoutAttempts = 0
    const session = () => active ? { status: "connected", session_id: "fixture-session", fingerprint: "SHA256:browser-fixture",
      group: active, groups: ["model", "factor"] } : null
    await page.route("**/experimental/quantcode/identities*", route => route.fulfill({ json: {
      identities: [{ id: "host-default", label: "Fixture identity", fingerprint: "SHA256:browser-fixture", host: "fixture.local",
        user: "SSH agent", group: "model", groups: ["model", "factor"] }], session: session(),
    } }))
    await page.route("**/experimental/quantcode/identity/login*", route => {
      expect(route.request().postDataJSON() ?? {}).toEqual({})
      active = "model"
      return route.fulfill({ json: session() })
    })
    await page.route("**/experimental/quantcode/identity/logout*", route => {
      if (++logoutAttempts === 1) return route.fulfill({ status: 400, json: { error: "Fixture revocation failure" } })
      active = undefined
      return route.fulfill({ json: { status: "disconnected" } })
    })
    await page.route("**/experimental/quantcode/tool?*", route => {
      if (new URL(route.request().url()).searchParams.get("tool") !== "session_context") return route.fallback()
      return route.fulfill({ json: active ? { session_id: "fixture-session", actor_id: "browser-fixture", group: active,
        authorized_groups: ["model", "factor"], role: "analyst", workspace_id: "audit" } : { error: "Authentication required" } })
    })
    await page.goto("/")
    await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
    await expect(page.locator("#qc-ssh-group")).toHaveCount(0)
    await page.locator(".qc-ssh").getByRole("button", { name: /^(连接|Connect)$/ }).click()
    await expect(page.locator(".qc-ssh [data-session-group]")).toHaveText("model")
    await page.getByRole("button", { name: "关闭详情", exact: true }).click()
    await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
    await expect(page.locator("#qc-ssh-group")).toHaveCount(0)
    const disconnect = page.locator(".qc-ssh").getByRole("button", { name: /^(断开|Disconnect)$/ })
    await disconnect.scrollIntoViewIfNeeded()
    await expect(disconnect).toBeInViewport()
    await page.screenshot({ path: `e2e/test-results/quantcode/identity-${viewport.width}.png` })
    await disconnect.click()
    await expect(page.locator(".qc-ssh [role=alert]")).toContainText("退出未完成")
    await expect(page.locator("#qc-ssh-group")).toHaveCount(0)
    await disconnect.click()
    await expect(page.locator("#qc-ssh-identity")).toBeVisible()
    await expect(page.locator(".qc-setting-row").first()).toContainText("未认证")
    await expect(page.locator(".qc-ssh [data-session-group]")).toHaveCount(0)
  })
}

test("archived history remains read-only, pages events and blocks uncertain recovery", async ({ page }) => {
  await mockContext(page, "analyst")
  const requested: string[] = []
  await page.route("**/experimental/quantcode/legacy/tasks**", async route => {
    const url = new URL(route.request().url())
    const query = url.searchParams
    const tool = url.pathname.endsWith("/history-1") ? "get_run_history" : "list_run_history"
    requested.push(tool)
    if (tool === "list_run_history") return route.fulfill({ json: { engine: "legacy-python", runs: [{ thread_id: "history-1", checkpoint_id: "cp-2", task: "核对回执测试任务", status: "error" }], next_cursor: null } })
    const next = query.get("trace_cursor") === "1"
    await route.fulfill({ json: {
      engine: "legacy-python", thread_id: "history-1", checkpoint_id: "cp-2", group: "factor", task: "核对回执测试任务",
      read_only: true, can_resume: false, recovery_block_reason: "存在未确认的外部调用",
      recovery: { available: false, provenance: "registered", serializer_version: 1, latest_checkpoint_id: "cp-2",
        checkpoint_digest: "b".repeat(64), blockers: [{ code: "unconfirmed_operation", message: "存在未确认的外部调用" }] },
      checkpoints: ["cp-2", "cp-1"], messages: [{ type: "ai", content: "保存的结果内容" }],
      artifacts: ["artifact://saved-report"],
      unresolved_operations: [{ call_id: "call-1", digest: "a".repeat(64), receipt_status: "STARTED", tool: "write_report" }],
      timeline: { events: [{ type: "tool_result", data: next ? "第二页事件" : "第一页事件" }], exists: true,
        next_cursor: next ? 2 : 1, has_more: !next, damaged_lines: next ? 1 : 0 },
    } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "执行记录", exact: true }).click()
  await page.getByRole("tab", { name: "归档任务", exact: true }).click()
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
  await page.screenshot({ path: "e2e/test-results/quantcode/redesign-history-detail.png" })
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
  await expect(catalog.locator(".qc-capability-results")).not.toContainText("UNVERIFIED")
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
  await page.getByRole("button", { name: "打开仓库 fixture/repository", exact: true }).click()
  const graph = page.getByRole("dialog").getByRole("img", { name: "Git 分支与合并图" })
  await expect(graph.locator("circle")).toHaveCount(100)
  await page.getByRole("button", { name: "下一页提交", exact: true }).click()
  await expect(graph.locator("circle")).toHaveCount(5)
  await expect(page.getByRole("button", { name: "下一页提交", exact: true })).toBeDisabled()
  await page.getByRole("button", { name: "关闭仓库详情" }).click()
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
  test(`${role}: bound group, automatic skills and scoped navigation`, async ({ page }) => {
    await mockContext(page, role)
    await page.goto("/")
    await expect(page.locator(".qc-identity")).toContainText("browser-fixture")
    await expect(page.getByRole("combobox", { name: "选择 Skill" })).toHaveCount(0)
    await expect(page.locator(".qc-skill-select")).toContainText("组 Skill 自动加载")
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
  await expect(page.locator(".qc-memory-empty")).toContainText(/暂不可用|not connected/)
  await expect(page.locator(".qc-memory-hit-row")).toHaveCount(0)
})

for (const viewport of [{ width: 900, height: 650 }, { width: 1440, height: 900 }]) {
  test(`long results scroll inside the workspace at ${viewport.width}px`, async ({ page }) => {
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
    expect(await page.locator(".qc-view-content").evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
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

test("admin: deployment staging and organization history entry points are usable", async ({ page }) => {
  await mockContext(page, "admin")
  let submitted = false
  let deploymentStatus = "STAGING"
  const deployment = {
    deployment_id: "dep-fixture",
    actor_id: "browser-fixture",
    created_at: "2026-09-06T00:00:00Z",
    payload: { artifact_ref: "artifacts/factor/report.json", target: "staging", manifest: { version: "1.2.3" } },
  }
  await page.route("**/experimental/quantcode/deployments**", async (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: { deployments: submitted ? [{ ...deployment, status: deploymentStatus }] : [], executor_status: "UNAVAILABLE", executor_message: "Production executor is not configured" } })
    }
    submitted = true
    return route.fulfill({ json: { ...deployment, status: deploymentStatus } })
  })
  await page.route("**/experimental/quantcode/deployments/cancel**", async (route) => {
    submitted = true
    deploymentStatus = "CANCELLED"
    return route.fulfill({ json: { ...deployment, status: deploymentStatus } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "Admin 中枢", exact: true }).click()
  await page.getByRole("tab", { name: "部署", exact: true }).click()
  const admin = page.getByLabel("Admin 部署管理")
  await expect(admin).toContainText("Production executor is not configured")
  await expect(admin.getByRole("button", { name: "暂存部署请求", exact: true })).toBeDisabled()
  await admin.getByLabel("产物引用").fill("artifacts/factor/report.json")
  await admin.getByLabel("目标环境").fill("staging")
  await admin.getByLabel("版本").fill("1.2.3")
  await admin.getByRole("button", { name: "暂存部署请求", exact: true }).click()
  await expect(admin).toContainText("artifacts/factor/report.json")
  await expect(admin).toContainText("STAGING")
  await admin.getByRole("button", { name: "取消暂存请求", exact: true }).click()
  await expect(admin).toContainText("CANCELLED")
  await page.getByRole("tab", { name: "报告与产物", exact: true }).click()
  await expect(page.getByRole("region", { name: "组织任务", exact: true }).getByRole("heading", { name: "报告与产物", exact: true })).toBeVisible()
})

test("admin: knowledge candidate review is scoped and refreshes after promotion", async ({ page }) => {
  await mockContext(page, "admin")
  let candidateStatus = "draft"
  await page.route("**/experimental/quantcode/tool?*", async (route) => {
    const tool = new URL(route.request().url()).searchParams.get("tool")
    if (tool === "list_distill_candidates") {
      return route.fulfill({ json: { candidates: [{ name: "factor-review-fixture", group: "factor", status: candidateStatus, digest: "a".repeat(64), content: "verified evaluator contract" }] } })
    }
    return route.fallback()
  })
  await page.route("**/experimental/quantcode/candidate**", async (route) => {
    candidateStatus = "promoted"
    return route.fulfill({ json: { ok: true, status: candidateStatus, candidate_name: "factor-review-fixture" } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "Memory", exact: true }).click()
  await page.getByRole("tab", { name: "知识候选审核", exact: true }).click()
  const review = page.getByLabel("知识候选审核")
  await expect(review).toContainText("factor-review-fixture")
  await review.getByText(/factor-review-fixture/).click()
  await review.getByRole("button", { name: "晋升为组内 Skill", exact: true }).click()
  await expect(review).toContainText("promoted")
  await review.getByText(/factor-review-fixture/).click()
  await expect(review.getByRole("button", { name: "撤销发布", exact: true })).toBeVisible()
})

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`workspace views have full layouts and preserve domain boundaries at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await mockContext(page, "admin")
    await page.route("**/experimental/quantcode/tool?*", route => {
      const tool = new URL(route.request().url()).searchParams.get("tool")
      if (tool === "list_run_history") return route.fulfill({ json: { runs: [], next_cursor: null } })
      if (tool === "list_capabilities") return route.fulfill({ json: { capabilities: [{
        id: "evaluator", name: "QuantEvaluator / 批量评估", owner_group: "factor", maturity_status: "PRODUCTION", integration_status: "PARTIAL",
        canonical_repo: "quant_evaluator", when_to_use: "批量评估因子，保留数据与标签契约。", when_not_to_reinvent: "指标口径由组件维护。",
        inputs: ["FactorBatch"], outputs: ["EvaluationArtifact"], api_surface: ["evaluate(FactorBatch, LabelBundle)"],
      }] } })
      if (tool === "search_memory") return route.fulfill({ json: { status: "CONNECTED", hits: [{ path: "global/target-return.md", scope: "global", snippet: "<<目标收益>>契约采用已核验的数据口径。", score: 1 }] } })
      return route.fallback()
    })
    await page.goto("/")
    await expect(page.getByRole("button", { name: "因子评估", exact: true })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "PIT 估值", exact: true })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "账号与登录" })).toContainText("管理员")
    for (const label of ["执行记录", "HumanGate", "Memory", "能力目录"]) {
      await page.getByRole("button", { name: label, exact: true }).click()
      await expect(page.getByRole("heading", { name: label, exact: true }).first()).toBeVisible()
      await expect(page.locator(".qc-stage")).toBeHidden()
      const bounds = await page.locator(".qc-detail-panel").boundingBox()
      expect(bounds!.width).toBeGreaterThan(viewport.width - 190)
      if (label === "Memory") {
        await page.getByRole("tab", { name: "长期知识", exact: true }).press("ArrowRight")
        await expect(page.getByRole("tab", { name: "知识候选审核", exact: true })).toHaveAttribute("aria-selected", "true")
        await page.getByRole("tab", { name: "知识候选审核", exact: true }).press("ArrowLeft")
        await page.getByRole("searchbox").fill("目标收益")
        await page.getByRole("searchbox").press("Enter")
        await expect(page.locator(".qc-memory-hit-row")).toHaveCount(1)
        await expect(page.locator(".qc-memory-snippet")).not.toContainText("<<")
        await expect(page.locator(".qc-knowledge-review")).toHaveCount(0)
      }
      if (label === "能力目录") {
        await expect(page.locator(".qc-capability-card")).toHaveCount(1)
        await page.locator(".qc-capability-details summary").click()
        await expect(page.locator(".qc-capability-details")).toContainText("EvaluationArtifact")
        await page.getByLabel("能力接入状态").selectOption("CONNECTED")
        await expect(page.locator(".qc-capability-empty")).toBeVisible()
        await page.getByLabel("能力接入状态").selectOption("all")
      }
      expect(await page.locator(".qc-view-content").evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
      await page.screenshot({ path: `e2e/test-results/quantcode/redesign-${viewport.width}-${label}.png` })
    }
    await page.getByRole("button", { name: "账号与登录" }).click()
    await expect(page.getByLabel("SSH 账号登录")).toBeVisible()
    await expect(page.locator('input[type="password"], textarea[name*="key"]')).toHaveCount(0)
    await page.screenshot({ path: `e2e/test-results/quantcode/redesign-${viewport.width}-login.png` })
  })
}

test("expired identity clears visible private Memory and offers login", async ({ page }) => {
  await mockContext(page, "analyst")
  let active = true
  await page.route("**/experimental/quantcode/tool?*", route => {
    const tool = new URL(route.request().url()).searchParams.get("tool")
    if (tool === "session_context") return route.fulfill({ json: active ? { session_id: "private-session", actor_id: "member", role: "analyst", group: "factor", workspace_id: "member-space" } : { error: "Session expired" } })
    if (tool === "search_memory") return route.fulfill({ json: { status: "CONNECTED", hits: [{ path: "groups/factor/verified.md", snippet: "private-memory-content" }] } })
    return route.fallback()
  })
  await page.goto("/")
  await expect(page.locator(".qc-identity")).toContainText("member")
  await page.getByRole("button", { name: "Memory", exact: true }).click()
  await page.getByRole("searchbox").fill("verified")
  await page.getByRole("searchbox").press("Enter")
  await expect(page.locator(".qc-memory-results")).toContainText("private-memory-content")
  active = false
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  await expect(page.getByRole("button", { name: "账号与登录" })).toContainText("登录工作区")
  await expect(page.locator(".qc-view-content")).not.toContainText("private-memory-content")
  await expect(page.getByRole("heading", { name: "登录后检索知识" })).toBeVisible()
})

test("QuantCode settings unify shortcut, providers and algorithm catalog", async ({ page }) => {
  await mockContext(page, "analyst", "risk")
  await page.route("**/experimental/quantcode/tool?*", route => {
    if (new URL(route.request().url()).searchParams.get("tool") !== "list_algorithms") return route.fallback()
    return route.fulfill({ json: { algorithms: [{ id: "equal_weight_composite_ranker", description: "Demo scorer: research example only." }] } })
  })
  await page.goto("/")
  await page.getByRole("button", { name: "QuantCode 设置", exact: true }).click()
  await expect(page.getByRole("tab", { name: "账号与连接", exact: true })).toBeVisible()
  await expect(page.locator(".qc-settings-content")).not.toContainText("算法目录")
  await page.getByRole("tab", { name: "模型供应商", exact: true }).click()
  await expect(page.locator(".qc-settings-models")).toContainText("接口 URL 和 API Key")
  await page.locator('[data-component="custom-provider-section"]').getByRole("button").click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toContainText("QuantCode 模型供应商")
  await expect(dialog.locator('input[type="password"]')).toBeVisible()
  await expect(dialog.locator('a[href*="opencode.ai"]')).toHaveCount(0)
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "能力目录", exact: true }).click()
  await page.getByRole("tab", { name: "算法目录", exact: true }).click()
  await expect(page.locator(".qc-algorithm-entry code")).toHaveText("equal_weight_composite_ranker")
  await expect(page.locator(".qc-algorithm-entry details")).not.toHaveAttribute("open")
  await page.locator(".qc-algorithm-entry summary").click()
  await expect(page.locator(".qc-algorithm-entry p")).toBeVisible()
  await page.screenshot({ path: "e2e/test-results/quantcode/settings-algorithms.png" })
  await page.keyboard.press(await page.evaluate(() => /Mac|iPod|iPhone|iPad/.test(navigator.platform)) ? "Meta+," : "Control+,")
  await expect(page.getByRole("tab", { name: "账号与连接", exact: true })).toBeVisible()
  await page.getByRole("tab", { name: "桌面偏好", exact: true }).click()
  await expect(page.getByLabel("任务完成通知")).toBeVisible()
  await page.screenshot({ path: "e2e/test-results/quantcode/settings-preferences.png" })
})

for (const mode of ["local", "browser"] as const) {
  test(mode === "local" ? "GitHub local credentials remain unavailable in a browser" : "GitHub browser connection verifies account and refreshes GitGraph", async ({ page }) => {
    await mockContext(page, "analyst")
    let connected = false
    let pending = false
    let polls = 0
    await page.route("**/experimental/quantcode/github", route => {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toEqual({ mode })
        if (mode === "local") connected = true
        else pending = true
      } else if (pending && ++polls >= 2) connected = true
      return route.fulfill({ json: connected ? { status: "connected", subject: "fixture-user" }
        : pending ? { status: "authorizing", code: "ABCD-EFGH", url: "https://github.com/login/device" } : { status: "disconnected" } })
    })
    await page.route("**/experimental/quantcode/tool?*", route => {
      if (new URL(route.request().url()).searchParams.get("tool") !== "get_gitgraph") return route.fallback()
      return route.fulfill({ json: connected ? { repos: [], sync_status: "CONNECTED" } : { error: "GitHub identity token is not connected" } })
    })
    await page.goto("/")
    await page.getByRole("button", { name: "GitGraph", exact: true }).click()
    if (mode === "local") {
      await expect(page.getByRole("button", { name: "使用本机凭据", exact: true })).toBeDisabled()
      await expect(page.locator(".qc-github-connection")).toContainText("请打开 QuantCode 桌面端")
      expect(connected).toBe(false)
      return
    }
    await page.getByRole("button", { name: "通过 GitHub 登录", exact: true }).click()
    await expect(page.locator(".qc-github-connection")).toContainText("ABCD-EFGH")
    await expect(page.getByRole("button", { name: "打开 GitHub 授权页" })).toBeVisible()
    await expect(page.locator(".qc-github-connection")).toContainText("已连接 fixture-user")
    await expect(page.locator(".qc-github-error")).toHaveCount(0)
    await page.screenshot({ path: `e2e/test-results/quantcode/github-${mode}.png` })
  })
}

test("model connection asks only for URL and API key before listing models", async ({ page }) => {
  await mockContext(page, "analyst")
  await page.route("https://models.example.test/v1/models", route => {
    expect(route.request().headers().authorization).toBe("Bearer fixture-key")
    return route.fulfill({ json: { data: [{ id: "fixture-model" }] }, headers: { "access-control-allow-origin": "*" } })
  })
  await page.goto("/?settings=providers")
  await page.getByRole("tab", { name: "模型供应商", exact: true }).click()
  await page.locator('[data-component="custom-provider-section"]').getByRole("button").click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByLabel("接口 URL", { exact: true })).toHaveValue("")
  await expect(dialog.locator('input[type="password"]')).toHaveValue("")
  await expect(dialog).not.toContainText("提供商 ID")
  await dialog.getByLabel("接口 URL", { exact: true }).fill("https://models.example.test/v1")
  await dialog.locator('input[type="password"]').fill("fixture-key")
  await dialog.getByRole("button", { name: /获取模型/ }).click()
  await expect(dialog.getByRole("textbox", { name: "ID", exact: true })).toHaveValue("fixture-model")
  await expect(dialog.getByRole("textbox", { name: "名称", exact: true })).toHaveValue("fixture-model")
})

for (const width of [1440, 1920]) {
  test(`repository cards show branching graphs and commit patches at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await mockContext(page, "analyst")
    const sha = (i: number) => String(i).padStart(40, "0")
    const nodes = [
      { sha: sha(6), message: "Merge factor validation into main", parents: [sha(4), sha(5)], author: "Alex Chen", date: "2026-09-08T01:00:00Z" },
      { sha: sha(5), message: "feat: validate factor inputs", parents: [sha(3)], author: "Mia Wang", date: "2026-09-07T12:00:00Z" },
      { sha: sha(4), message: "fix: align trading dates", parents: [sha(2)], author: "Alex Chen", date: "2026-09-07T11:00:00Z" },
      { sha: sha(3), message: "test: add contract fixtures", parents: [sha(2)], author: "Mia Wang", date: "2026-09-06T13:00:00Z" },
      { sha: sha(2), message: "feat: factor pipeline", parents: [sha(1)], author: "Alex Chen", date: "2026-09-06T10:00:00Z" },
      { sha: sha(1), message: "Initial commit", parents: [], author: "Alex Chen", date: "2026-09-01T10:00:00Z" },
    ]
    await page.route("**/experimental/quantcode/tool?*", route => {
      if (new URL(route.request().url()).searchParams.get("tool") !== "get_gitgraph") return route.fallback()
      return route.fulfill({ json: { repos: ["FactorEngine", "Modeling", "QuantEvaluator", "DataAccess", "Riskfolio-QS", "VectorBT-QS"].map(name => ({
        repo: `HKUST-QUANT-SOCIETY/${name}`, description: "组织研究组件与版本记录", default_branch: "main", observed_at: "2026-09-08T01:00:00Z", sync_status: "CONNECTED", errors: [], dependency_changes: [],
        heads: [{ branch: "main", sha: sha(6) }, { branch: "feature/validation", sha: sha(5) }], commit_nodes: nodes,
      })) } })
    })
    await page.route("**/experimental/quantcode/github/commit?*", async route => {
      const value = new URL(route.request().url()).searchParams.get("sha")!
      await route.fulfill({ json: { sha: value, message: `${nodes.find(n => n.sha === value)?.message}\n\nValidate schema before evaluating factors.`, author: "Mia Wang", date: "2026-09-07T12:00:00Z", has_more: false,
        files: [{ filename: "src/factors/validate.py", status: "modified", additions: 2, deletions: 1, patch: "@@ -1 +1,2 @@\n-return panel\n+validate_schema(panel)\n+return panel" }] } })
    })
    await page.goto("/")
    await page.getByRole("button", { name: "GitGraph", exact: true }).click()
    await expect(page.locator(".qc-repo-card")).toHaveCount(6)
    const boxes = await page.locator(".qc-repo-card").evaluateAll(cards => cards.map(card => ({ x: card.getBoundingClientRect().x, y: card.getBoundingClientRect().y })))
    expect(boxes[0].y === boxes[1].y).toBe(width > 740)
    if (width >= 1440) expect(boxes[0].y).toBe(boxes[5].y)
    expect(await page.locator(".qc-repo-card").first().locator("circle").evaluateAll(circles => new Set(circles.map(c => c.getAttribute("cx"))).size)).toBeGreaterThan(1)
    expect(await page.locator(".qc-view-content").evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: `e2e/test-results/quantcode/git-cards-${width}.png` })
    await page.getByRole("button", { name: "打开仓库 HKUST-QUANT-SOCIETY/FactorEngine" }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    await dialog.locator(".qc-commit-row").filter({ hasText: "feat: validate factor inputs" }).click()
    await expect(dialog.getByLabel("提交代码变更")).toContainText("Validate schema before evaluating factors.")
    await expect(dialog.locator(".qc-diff-file")).toContainText("+validate_schema(panel)")
    await expect(dialog).toContainText("Mia Wang")
    await page.screenshot({ path: `e2e/test-results/quantcode/git-detail-${width}.png` })
    await page.keyboard.press("Escape")
    await expect(dialog).toHaveCount(0)
  })
}

for (const width of [1440, 1920]) {
  test(`Admin overview shows synchronized task counts and scoped records at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await mockContext(page, "admin")
    const tasks = [
      { actor_id: "researcher-a", group: "factor", title: "核对因子输入契约", status: "completed" },
      { actor_id: "researcher-b", group: "factor", title: "验证横截面数据与计算结果", status: "running" },
      { actor_id: "researcher-c", group: "model", title: "检查训练数据版本", status: "error" },
    ].map((task, index) => ({ ...task, session_id: `ses_admin_fixture_${index}`, root_session_id: `ses_admin_fixture_${index}`,
      source_id: "ui-fixture-source", source_revision: 1, role: "analyst", workspace_id: `fixture-${index}`,
      created_at: 1788825300000, updated_at: 1788825600000, received_at: 1788825610000,
      tokens_input: 100, tokens_output: 30, cost: null, reserved_tokens: 0, unconfirmed_requests: 0,
      artifact_count: 0, artifacts: [], artifact_manifest_hash: "a".repeat(64) }))
    await page.route("**/experimental/quantcode/organization-tasks*", route => route.fulfill({ json: { tasks, next_cursor: null } }))
    await page.goto("/")
    await page.getByRole("button", { name: "Admin 中枢", exact: true }).waitFor()
    await page.getByRole("button", { name: "Admin 中枢", exact: true }).click()
    await expect(page.getByRole("tab", { name: "概览", exact: true })).toHaveAttribute("aria-selected", "true")
    const overview = page.getByRole("region", { name: "组织任务", exact: true })
    await expect(overview.getByRole("heading", { name: "组织概览", exact: true })).toBeVisible()
    await expect(overview.getByLabel("已加载任务统计")).toContainText("已加载任务3运行中1待审批0异常或预算停止1")
    await expect(overview.locator(".qc-history-row")).toHaveCount(3)
    await expect(page.getByLabel("Admin 部署管理")).toHaveCount(0)
    await overview.getByRole("searchbox", { name: "搜索任务" }).fill("factor")
    await expect(overview.locator(".qc-history-row")).toHaveCount(2)
    await overview.getByRole("combobox", { name: "任务状态" }).selectOption("running")
    await expect(overview.locator(".qc-history-row")).toHaveCount(1)
    await expect(overview.locator(".qc-history-row")).toContainText("researcher-b")
    expect(await page.locator(".qc-view-content").evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: `e2e/test-results/quantcode/admin-overview-${width}.png`, fullPage: false })
    await page.getByRole("tab", { name: "任务", exact: true }).click()
    await expect(page.getByRole("tab", { name: "任务", exact: true })).toHaveAttribute("aria-selected", "true")
    await expect(page.locator(".qc-history-row")).toHaveCount(3)
    await page.getByRole("tab", { name: "概览", exact: true }).click()
    await page.getByRole("tab", { name: "部署", exact: true }).click()
    await expect(page.getByLabel("Admin 部署管理")).toBeVisible()
    await page.screenshot({ path: `e2e/test-results/quantcode/admin-deployment-${width}.png` })
  })
}

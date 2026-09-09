import { expect, test, type Page } from "@playwright/test"

type Controls = {
  sdk: () => unknown
  sync: () => unknown
  setTarget: (kind: "session" | "host") => void
  setBusy: (value: boolean) => void
  emit: (type: string, properties: unknown) => void
}
declare global { interface Window { taskReviewFixture: Controls } }

// Real Vite-compiled control and generated HTTP SDK. Only its context providers
// and HTTP authority are fixtures; no task is submitted to the running host.
async function mount(page: Page, initial: "draft" | "frozen" = "frozen") {
  let status = initial
  let gate = "idle"
  let missingSelection = false
  let serverBusy = false
  const submitted: { url: string; body: unknown }[] = []
  await page.route("**/task-review-fixture", route => route.fulfill({ contentType: "text/html", body: "<!doctype html><html><body><main></main></body></html>" }))
  await page.route("**/src/context/sdk.tsx*", route => route.fulfill({ contentType: "application/javascript", body: "export const useSDK = () => window.taskReviewFixture.sdk" }))
  await page.route("**/src/context/sync.tsx*", route => route.fulfill({ contentType: "application/javascript", body: "export const useSync = () => window.taskReviewFixture.sync" }))
  await page.route("**/qa-host-*/**", async route => {
    const url = new URL(route.request().url())
    const id = url.pathname.includes("ses_other") ? "ses_other" : "ses_review"
    const solution = { engine: "quantcode", session_id: id, classification: { complexity: "L2", solution_required: true },
      solution: { id: "solution", goal: "Existing approved intent", status, version: 3, doc_hash: "reviewed-hash",
        acceptance_criteria: ["Original requirements"], file_impact: ["approved.py"], rounds: [] } }
    const reuse = { session_id: id, intent_hash: "original-intent", catalog_checked: true, memory_checked: true,
      proposal: { coverage: "full", proposal_hash: "reuse-hash", components: ["existing-component"], reason: "Reuse existing capability" } }
    if (url.pathname.endsWith("/prompt_async")) {
      submitted.push({ url: url.pathname, body: route.request().postDataJSON() })
      await route.fulfill({ status: 204 })
      return
    }
    if (url.pathname.endsWith("/solution/review")) {
      expect(route.request().postDataJSON()).toEqual({ expected_hash: "reviewed-hash", expected_version: 3, decision: "approve", note: "Approved original scope" })
      status = "frozen"
      await route.fulfill({ json: { ...solution, solution: { ...solution.solution, status } } })
      return
    }
    const body = url.pathname.endsWith("/solution") ? solution
      : url.pathname.endsWith("/reuse") ? reuse
      : url.pathname.endsWith("/write-receipts") ? { session_id: id, root_session_id: id, unresolved: [] }
      : url.pathname.endsWith("/execution-lock") ? { session_id: id, status: gate }
      : url.pathname.endsWith("/budget/review") ? { budget: { root_session_id: id, used: 0, reserved: 0, token_limit: null, unconfirmed_requests: 0, unpriced_requests: 0, status: "ok" }, requests: [], lock: { status: "idle" } }
      : url.pathname.endsWith("/session/status") ? serverBusy ? { [id]: { type: "busy" } } : {}
      : url.pathname.endsWith(`/session/${id}`) ? { id, directory: "/qa", ...(missingSelection ? {} : { agent: "saved-agent", model: { id: "saved-model", providerID: "saved-provider", variant: "saved-variant" } }) }
      : undefined
    if (!body) throw new Error(`Unexpected fixture request: ${url.pathname}`)
    await route.fulfill({ json: body })
  })
  await page.goto("/task-review-fixture")
  await page.evaluate(async () => {
    const path = "/src/components/quantcode/task-review.tsx"
    const source = await (await fetch(path)).text()
    const rendererPath = source.match(/from "([^"]*solid-js_web\.js[^\"]*)"/)?.[1]
    const solidPath = source.match(/from "([^"]*\/solid-js\.js[^\"]*)"/)?.[1]
    if (!rendererPath || !solidPath) throw new Error("Vite Solid imports unavailable")
    const { render } = await import(rendererPath)
    const { createSignal } = await import(solidPath)
    await import("/src/index.css")
    const { createSdkForServer } = await import("/src/utils/server.ts")
    const listeners = new Map<string, Set<(event: { properties: unknown }) => void>>()
    const context = (host: string) => ({ directory: "/qa", client: createSdkForServer({ server: { url: `${location.origin}/${host}` }, directory: "/qa", throwOnError: true }),
      event: { on: (type: string, fn: (event: { properties: unknown }) => void) => {
        const set = listeners.get(type) ?? new Set()
        listeners.set(type, set)
        set.add(fn)
        return () => set.delete(fn)
      } } })
    const [sdk, setSDK] = createSignal(context("qa-host-a"))
    const [session, setSession] = createSignal("ses_review")
    const [busy, setBusy] = createSignal(false)
    window.taskReviewFixture = { sdk, sync: () => ({ data: { session_status: { [session()]: { type: busy() ? "busy" : "idle" } } } }),
      setBusy, setTarget: kind => kind === "session" ? setSession("ses_other") : setSDK(context("qa-host-b")),
      emit: (type, properties) => listeners.get(type)?.forEach(fn => fn({ properties })),
    }
    const { QuantCodeTaskReview } = await import(path)
    render(() => QuantCodeTaskReview({ get sessionID() { return session() }, expanded: true }), document.querySelector("main")!)
  })
  await expect(page.getByText("Existing approved intent")).toBeVisible()
  return { submitted, setGate: (value: string) => { gate = value }, omitSelection: () => { missingSelection = true }, serverBusy: () => { serverBusy = true } }
}

test("approval requires explicit continuation with empty parts and the saved task selection", async ({ page }) => {
  const fixture = await mount(page, "draft")
  await page.getByLabel("确认说明或修改意见").fill("Approved original scope")
  await page.getByRole("button", { name: "确认第 3 版", exact: true }).click()
  const resume = page.getByRole("button", { name: "继续执行", exact: true })
  await expect(resume).toBeEnabled()
  expect(fixture.submitted).toEqual([])
  await resume.click()
  await expect(page.getByRole("button", { name: "已请求继续", exact: true })).toBeDisabled()
  expect(fixture.submitted).toEqual([{ url: "/qa-host-a/session/ses_review/prompt_async", body: {
    parts: [], agent: "saved-agent", model: { providerID: "saved-provider", modelID: "saved-model" }, variant: "saved-variant",
  } }])
  await page.screenshot({ path: "e2e/test-results/task-review-continue.png" })
})

test("pending continuation submits once and an HTTP failure does not retry", async ({ page }) => {
  await mount(page)
  let requests = 0
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route("**/prompt_async", async route => {
    requests++
    await held
    await route.fulfill({ status: 503, json: { message: "Unavailable" } })
  })
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect(page.getByRole("button", { name: "正在提交…", exact: true })).toBeDisabled()
  await expect.poll(() => requests).toBe(1)
  release()
  await expect(page.getByRole("alert")).toContainText("继续请求未确认")
  await expect(page.getByRole("button", { name: "继续执行", exact: true })).toBeDisabled()
  await page.clock.install()
  await page.clock.fastForward(15_000)
  expect(requests).toBe(1)
})

for (const target of ["session", "host"] as const) {
  test(`late preflight after ${target} switch cannot submit or overwrite the new target`, async ({ page }) => {
    const fixture = await mount(page)
    let entered = false
    let release!: () => void
    const held = new Promise<void>(resolve => { release = resolve })
    await page.route("**/qa-host-a/session/ses_review?*", async route => {
      entered = true
      await held
      await route.fulfill({ json: { id: "ses_review", directory: "/qa", agent: "old-agent", model: { id: "old-model", providerID: "old-provider" } } }).catch(() => {})
    })
    await page.getByRole("button", { name: "继续执行", exact: true }).click()
    await expect.poll(() => entered).toBe(true)
    await page.evaluate(kind => window.taskReviewFixture.setTarget(kind), target)
    await expect(page.getByRole("button", { name: "继续执行", exact: true })).toBeEnabled()
    release()
    await expect(page.getByRole("alert")).toHaveCount(0)
    expect(fixture.submitted).toEqual([])
    await page.getByRole("button", { name: "继续执行", exact: true }).click()
    await expect(page.getByRole("button", { name: "已请求继续", exact: true })).toBeDisabled()
    expect(fixture.submitted[0]?.url).toBe(target === "session" ? "/qa-host-a/session/ses_other/prompt_async" : "/qa-host-b/session/ses_review/prompt_async")
  })
}

test("local busy and authoritative server busy both prevent continuation", async ({ page }) => {
  const fixture = await mount(page)
  await page.evaluate(() => window.taskReviewFixture.setBusy(true))
  await expect(page.getByRole("button", { name: "任务执行中", exact: true })).toBeDisabled()
  await page.evaluate(() => window.taskReviewFixture.setBusy(false))
  fixture.serverBusy()
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("任务正在执行")
  expect(fixture.submitted).toEqual([])
})

test("missing saved model or Agent never falls back to a default selection", async ({ page }) => {
  const fixture = await mount(page)
  fixture.omitSelection()
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("尚未保存模型或 Agent")
  expect(fixture.submitted).toEqual([])
})

test("changed execution lock and an asynchronous task error cannot trigger retries", async ({ page }) => {
  const fixture = await mount(page)
  fixture.setGate("active")
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("任务状态已变化")
  expect(fixture.submitted).toEqual([])
  fixture.setGate("idle")
  await page.getByRole("button", { name: "刷新", exact: true }).click()
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect(page.getByRole("button", { name: "已请求继续", exact: true })).toBeDisabled()
  await page.evaluate(() => window.taskReviewFixture.emit("session.error", { sessionID: "ses_review" }))
  await expect(page.getByRole("alert")).toContainText("任务未能继续")
  await page.clock.install()
  await page.clock.fastForward(15_000)
  expect(fixture.submitted).toHaveLength(1)
})

test("an execution error before the HTTP acknowledgement remains visible", async ({ page }) => {
  await mount(page)
  let entered = false
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route("**/prompt_async", async route => {
    entered = true
    await held
    await route.fulfill({ status: 204 })
  })
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect.poll(() => entered).toBe(true)
  await page.evaluate(() => window.taskReviewFixture.emit("session.error", { sessionID: "ses_review" }))
  release()
  await expect(page.getByRole("alert")).toContainText("任务未能继续")
  await expect(page.getByRole("button", { name: "继续执行", exact: true })).toBeDisabled()
  await expect(page.getByRole("status")).toHaveCount(0)
})

test("a late HTTP acknowledgement cannot mark a different session as resumed", async ({ page }) => {
  await mount(page)
  let entered = false
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route("**/prompt_async", async route => {
    entered = true
    await held
    await route.fulfill({ status: 204 }).catch(() => {})
  })
  await page.getByRole("button", { name: "继续执行", exact: true }).click()
  await expect.poll(() => entered).toBe(true)
  await page.evaluate(() => window.taskReviewFixture.setTarget("session"))
  release()
  await expect(page.getByRole("button", { name: "继续执行", exact: true })).toBeEnabled()
  await expect(page.getByRole("status")).toHaveCount(0)
})

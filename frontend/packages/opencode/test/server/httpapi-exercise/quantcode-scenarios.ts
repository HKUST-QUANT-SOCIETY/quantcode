import { Effect } from "effect"
import { createServer } from "node:http"
import { once } from "node:events"
import { mkdir, realpath, writeFile } from "node:fs/promises"
import path from "node:path"
import { check, object } from "./assertions"
import { http, route } from "./dsl"
import { exerciseGlobalRoot } from "./environment"
import type { Scenario, ScenarioContext } from "./types"

const prefix = "/experimental/quantcode"
const missingSession = "ses_httpapi_missing_native"
const hash = "a".repeat(64)
const project = { git: true, config: { mcp: {}, provider: {}, formatter: false as const, lsp: false as const, plugin: [] } }

// Only the external identity authority is fixed. Every request below runs the
// actual middleware, decoder and handler against isolated application storage.
const native = (ctx: ScenarioContext, authenticated = true) => Effect.gen(function* () {
  if (!ctx.directory) throw new Error("Native boundary scenarios need an isolated workspace")
  const workspace = yield* Effect.promise(() => realpath(ctx.directory!))
  const identity = { session_id: "b".repeat(32), actor_id: "httpapi-fixture", group: "factor", role: "analyst",
    workspace_id: "httpapi-fixture-workspace", workspace_path: workspace, github_subject: null,
    resource_scopes: [], authorized_groups: ["factor"], identity_source: "ssh_roster",
    issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60000).toISOString() }
  const requests: string[] = []
  const authority = createServer((request, response) => {
    requests.push(request.url ?? "")
    if (request.url === "/session" && request.headers.authorization === "Bearer httpapi-fixture-token") {
      response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(identity))
      return
    }
    response.writeHead(403, { "content-type": "application/json" }).end(JSON.stringify({ error: "fixture resource is not authorized" }))
  })
  yield* Effect.addFinalizer(() => Effect.promise(async () => {
    authority.closeAllConnections()
    if (authority.listening) await new Promise<void>((resolve, reject) => authority.close(error => error ? reject(error) : resolve()))
  }))
  authority.listen(0, "127.0.0.1")
  yield* Effect.promise(() => once(authority, "listening"))
  const address = authority.address()
  if (!address || typeof address === "string") throw new Error("Native authority fixture did not start")
  const control = path.join(exerciseGlobalRoot, "native-control")
  yield* Effect.promise(() => mkdir(control, { recursive: true, mode: 0o700 }))
  const credential = path.join(control, "identity.json")
  yield* Effect.promise(() => writeFile(credential, JSON.stringify({
    gateway: `http://127.0.0.1:${address.port}`, token: "httpapi-fixture-token",
  }), { mode: 0o600 }))
  const previous = Object.fromEntries(Object.entries(process.env).filter(([key]) => key.startsWith("QUANTCODE_") || key === "OPENCODE_CHANNEL"))
  yield* Effect.addFinalizer(() => Effect.sync(() => {
    for (const key of Object.keys(process.env)) if (key.startsWith("QUANTCODE_") || key === "OPENCODE_CHANNEL") delete process.env[key]
    Object.assign(process.env, previous)
  }))
  for (const key of Object.keys(process.env)) if (key.startsWith("QUANTCODE_")) delete process.env[key]
  Object.assign(process.env, { OPENCODE_CHANNEL: "quantcode", QUANTCODE_UNIFIED_RUNTIME: "1",
    QUANTCODE_WORKSPACES_FILE: path.join(control, "no-extra-grants.json"),
    ...(authenticated ? { QUANTCODE_IDENTITY_SESSION_FILE: credential } : {}) })
  return { identity, requests, workspace }
})

const taskError = (body: unknown) => {
  object(body)
  check(body._tag === "QuantCodeTaskError" && typeof body.message === "string" && !!body.message,
    "missing task or denied organization resource must return the declared task error")
}
const unavailable = (body: unknown) => {
  object(body)
  check(typeof body.error === "string" && !!body.error, "unconfigured service must expose an explicit error")
  check(body.status !== "connected", "unconfigured service cannot claim a connection")
}
const nativeGet = (suffix: string, name: string) => http.protected.get(prefix + suffix, name).inProject(project).seeded(ctx => native(ctx))
const nativePost = (suffix: string, name: string) => http.protected.post(prefix + suffix, name).inProject(project).seeded(ctx => native(ctx))
const resolved = (template: string) => route(prefix + template, { sessionID: missingSession, source_id: "fixture-source", artifact_id: `artifact_${hash}`, gateID: hash, thread_id: "fixture-archived-task" })

const missingTasks = [
  "/session/{sessionID}/task-index", "/session/{sessionID}/solution", "/session/{sessionID}/write-receipts",
  "/session/{sessionID}/execution-lock", "/session/{sessionID}/budget", "/session/{sessionID}/budget/review",
  "/legacy/tasks", "/legacy/tasks/{thread_id}", "/native-gates", "/native-gates/{gateID}",
  "/organization-tasks", "/organization-tasks/{source_id}/{sessionID}",
  "/session/{sessionID}/artifacts", "/session/{sessionID}/artifacts/{artifact_id}",
  "/organization-tasks/{source_id}/{sessionID}/artifacts", "/organization-tasks/{source_id}/{sessionID}/artifacts/{artifact_id}",
]

const absentResourcePosts = [
  { path: "/legacy/request-approval", body: { thread_id: "fixture-archive", checkpoint_id: "fixture-checkpoint", checkpoint_digest: hash,
    executor_version: "fixture", provenance_digest: hash, expected_gate_id: hash } },
  { path: "/legacy/resume", body: { thread_id: "fixture-archive", checkpoint_id: "fixture-checkpoint", checkpoint_digest: hash,
    executor_version: "fixture", provenance_digest: hash } },
  { path: "/native-gates/decide", body: { gate_id: hash, expected_digest: hash, operation_digest: hash, decision: "approve", note: "fixture cannot create an approval" } },
  { path: "/session/{sessionID}/solution", body: { goal: "fixture", acceptance_criteria: ["fixture"], file_impact: ["result.txt"] } },
  { path: "/session/{sessionID}/solution/review", body: { expected_hash: hash, expected_version: 1, decision: "approve", note: "fixture" } },
  { path: "/session/{sessionID}/write-receipts/review", body: { source_session_id: missingSession, message_id: "msg_fixture", call_id: "fixture-call",
    expected_digest: hash, expected_receipt_digest: hash, decision: "confirmed_not_executed", evidence_ref: "fixture", note: "fixture" } },
  { path: "/session/{sessionID}/budget/review", body: { request_id: "fixture-request", expected_digest: hash,
    request_stopped: true, decision: "confirmed_not_executed", evidence_ref: "fixture", note: "fixture" } },
  { path: "/session/{sessionID}/budget/lock/recover", body: { expected_digest: hash, processes_stopped: false, evidence_ref: "fixture", note: "fixture" } },
]

export const quantcodeScenarios: Scenario[] = [
  http.protected.get("/experimental/proxy/models", "quantcode.proxyModels.rejectsLoopback").inProject(project)
    .at(ctx => ({ path: "/experimental/proxy/models?url=http%3A%2F%2F127.0.0.1%3A9%2Fv1", headers: ctx.headers() })).status(400),
  ...missingTasks.map(template => nativeGet(template, `quantcode.boundary.missing${template}`)
    .at(ctx => ({ path: resolved(template) + (template.includes("/artifacts") ? "?source_revision=1" : ""), headers: ctx.headers() }))
    .json(400, taskError)),
  ...absentResourcePosts.map(item => nativePost(item.path, `quantcode.boundary.reject${item.path}`)
    .at(ctx => ({ path: resolved(item.path), headers: ctx.headers(), body: item.body })).json(400, taskError)),
  nativeGet("/session/{sessionID}/reuse", "quantcode.reuse.noTask").at(ctx => ({ path: resolved("/session/{sessionID}/reuse"), headers: ctx.headers() }))
    .json(400, body => { object(body); check(body._tag === "QuantCodeReuseError", "reuse must reject an absent task") }),
  nativeGet("/deployments", "quantcode.deployments.analystDenied").status(400),
  nativePost("/deployments", "quantcode.deployments.bodyCannotElevateRole")
    .at(ctx => ({ path: prefix + "/deployments", headers: ctx.headers(), body: { artifact_ref: "fixture/report", target: "staging", manifest: {}, role: "admin" } }))
    .status(400, ctx => Effect.sync(() => check(!ctx.state.requests.includes("/deployments"), "analyst cannot reach deployment mutation"))),
  nativePost("/deployments/cancel", "quantcode.deployments.cancelRequiresAdmin")
    .at(ctx => ({ path: prefix + "/deployments/cancel", headers: ctx.headers(), body: { deployment_id: "fixture" } })).status(400),
  nativePost("/receipts/reconcile", "quantcode.receipts.analystCannotReconcile")
    .at(ctx => ({ path: prefix + "/receipts/reconcile", headers: ctx.headers(), body: { thread_id: "fixture", checkpoint_id: "fixture",
      call_id: "fixture", expected_digest: hash, decision: "confirmed_not_executed", evidence_ref: "fixture", note: "fixture" } })).status(400),
  nativePost("/candidate", "quantcode.candidate.requiresExactDigest")
    .at(ctx => ({ path: prefix + "/candidate", headers: ctx.headers(), body: { candidate_name: "fixture", action: "promote" } })).status(400),
  nativePost("/pop", "quantcode.pop.requiresReceiptChange")
    .at(ctx => ({ path: prefix + "/pop", headers: ctx.headers(), body: { pop_id: "fixture-pop" } })).status(400),
  nativeGet("/github", "quantcode.github.unconfiguredStatus").json(200, unavailable),
  nativeGet("/github/commit", "quantcode.github.unconfiguredCommit")
    .at(ctx => ({ path: prefix + `/github/commit?repo=fixture/repo&sha=${hash}`, headers: ctx.headers() })).json(200, unavailable),
  nativeGet("/github/credential/prepare", "quantcode.github.unboundSubjectDenied").status(400),
  nativePost("/github/credential/import", "quantcode.github.browserCannotImportCredential")
    .at(ctx => ({ path: prefix + "/github/credential/import", headers: ctx.headers({ origin: "https://fixture.invalid" }),
      body: { version: 1, nonce: "fixture", session_id: ctx.state.identity.session_id, owner_digest: hash, token: "fixture-token-not-a-secret" } })).status(400),
  nativePost("/github", "quantcode.github.localCredentialsRequireDesktop")
    .at(ctx => ({ path: prefix + "/github", headers: ctx.headers(), body: { mode: "local" } })).json(200, unavailable),
  nativeGet("/identities", "quantcode.identity.unconfiguredHost")
    .json(200, body => { unavailable(body); object(body); check(Array.isArray(body.identities) && body.identities.length === 0, "unconfigured host has no identity claims") }),
  nativePost("/identity/login", "quantcode.identity.groupOverrideDenied")
    .at(ctx => ({ path: prefix + "/identity/login", headers: ctx.headers(), body: { group: "agent" } })).status(400),
  nativePost("/identity/challenge", "quantcode.identity.unconfiguredChallenge")
    .at(ctx => ({ path: prefix + "/identity/challenge", headers: ctx.headers(), body: {} })).json(400, body => {
      object(body); check(body._tag === "QuantCodeIdentityApiError", "challenge must fail with the identity contract")
    }),
  nativePost("/identity/verify", "quantcode.identity.unissuedChallengeDenied")
    .at(ctx => ({ path: prefix + "/identity/verify", headers: ctx.headers(), body: { challenge_id: "fixture-unissued", signature: "fixture-invalid" } }))
    .json(400, body => { object(body); check(body._tag === "QuantCodeIdentityApiError", "unissued challenge cannot establish identity") }),
  nativePost("/identity/logout", "quantcode.identity.unconfiguredLogoutCannotClaimSuccess").status(400),
  nativeGet("/task-publication", "quantcode.publication.newHostStartsEmpty").json(200, body => {
    object(body); check(body.state === "starting" && body.pending_tasks === 0 && body.failed_tasks === 0, "new publisher must not invent delivered tasks")
  }),
  nativeGet("/tasks", "quantcode.tasks.emptyAuthorizedWorkspace").json(200, body => {
    object(body); check(Array.isArray(body.tasks) && body.tasks.length === 0 && body.next_cursor === null, "isolated owner sees no invented tasks")
  }),
  nativeGet("/tool", "quantcode.tool.identityIgnoresGroupOverride")
    .at(ctx => ({ path: prefix + "/tool?tool=session_context&group=agent", headers: ctx.headers() }))
    .json(200, (body, ctx) => { object(body); check(body.actor_id === ctx.state.identity.actor_id && body.group === "factor" && body.role === "analyst", "identity must come from authority") }),
  nativeGet("/workspaces", "quantcode.workspaces.onlyAuthorizedRoot").json(200, (body, ctx) => {
    object(body); check(body.login_session_id === ctx.state.identity.session_id, "workspace list must bind the current login")
    check(Array.isArray(body.roots) && body.roots.length === 1, "only the fixture root is granted")
    object(body.roots[0]); check(body.roots[0].directory === ctx.state.workspace, "host cwd cannot become an implicit grant")
  }),
  http.protected.get(prefix + "/workspaces", "quantcode.workspaces.missingIdentityDenied").inProject(project).seeded(ctx => native(ctx, false))
    .json(400, body => { object(body); check(body._tag === "QuantCodeWorkspaceApiError", "missing identity must return a workspace rejection") }),
  nativePost("/session/{sessionID}/execution-lock/recover", "quantcode.executionLock.stopAttestationRequired")
    .at(ctx => ({ path: resolved("/session/{sessionID}/execution-lock/recover"), headers: ctx.headers(),
      body: { expected_digest: hash, processes_stopped: false, evidence_ref: "fixture", note: "fixture" } })).status(400),
  nativePost("/session/{sessionID}/reuse/review", "quantcode.reuse.modelApprovalIsNotADecision")
    .at(ctx => ({ path: resolved("/session/{sessionID}/reuse/review"), headers: ctx.headers(),
      body: { proposal_hash: hash, decision: "model_approved", note: "fixture" } })).status(400),
  nativePost("/session/{sessionID}/solution", "quantcode.solution.arrayStringsRejected")
    .at(ctx => ({ path: resolved("/session/{sessionID}/solution"), headers: ctx.headers(),
      body: { goal: "fixture", acceptance_criteria: "[]", file_impact: "[]" } })).status(400),
  nativeGet("/tool", "quantcode.tool.arbitraryWriteToolDenied")
    .at(ctx => ({ path: prefix + "/tool?tool=write", headers: ctx.headers() })).status(400),
]

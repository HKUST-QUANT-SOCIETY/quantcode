import { QuantCodeSolution } from "@/quantcode/solution"
import { QuantCodeReuse } from "@/quantcode/reuse"
import { QuantCodeTaskLock } from "@/quantcode/task-lock"
import { QuantCodeWriteReceipt } from "@/quantcode/write-receipt"
import { QuantCodeBudget } from "@/quantcode/budget"
import { QuantCodeGate } from "@/quantcode/gate"
import { QuantCodeTaskIndex } from "@/quantcode/task-index"
import { QuantCodeTaskPublisher } from "@/quantcode/task-publisher"
import { QuantCodeOrganizationTasks } from "@/quantcode/organization-tasks"
import { QuantCodeLegacyHost } from "@/quantcode/legacy"
import { QuantCodeKnowledgeHost } from "@/quantcode/knowledge"
import { Provider } from "@/provider/provider"
import { Database } from "@opencode-ai/core/database/database"
import { EventV2Bridge } from "@/event-v2-bridge"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace } from "@/quantcode/workspace"
import { hostGitHub, githubConnection, githubCommit, prepareGitHubCredential, importGitHubCredential } from "./quantcode-github"
import { HttpServerRequest } from "effect/unstable/http"
import { localIdentity, signInLocalIdentity, signOutLocalIdentity, createIdentityChallenge, verifyIdentityChallenge } from "./quantcode-identity"
import { quantcodeManagement } from "./quantcode-management"
import { Account } from "@/account/account"
import { Agent } from "@/agent/agent"
import { BackgroundJob } from "@/background/job"
import { Config } from "@/config/config"
import { InstanceState } from "@/effect/instance-state"
import { RuntimeFlags } from "@/effect/runtime-flags"
import { MCP } from "@/mcp"
import { Project } from "@/project/project"
import { InstanceStore } from "@/project/instance-store"
import { Session } from "@/session/session"
import type { SessionID } from "@/session/schema"
import { ToolJsonSchema } from "@/tool/json-schema"
import { ToolRegistry } from "@/tool/registry"
import { Worktree } from "@/worktree"
import { Effect, Option, Semaphore } from "effect"
import * as HttpServerResponse from "effect/unstable/http/HttpServerResponse"
import { HttpApiBuilder, HttpApiError } from "effect/unstable/httpapi"
import { InstanceHttpApi } from "../api"
import {
  isForbiddenIP,
  lookupAddresses,
  probeProxyModels,
  ProxyModelsQuery,
  validateProxyModelsURL,
} from "../groups/proxy-models"
import {
  ConsoleSwitchPayload,
  QuantCodeToolQuery,
  QuantCodePopPayload,
  QuantCodeReceiptPayload,
  QuantCodeCandidatePayload,
  QuantCodeDeploymentPayload,
  QuantCodeDeploymentCancelPayload,
  SessionListQuery,
  ToolListQuery,
  WorktreeApiError,
  QuantCodeReuseError,
  QuantCodeTaskError,
  QuantCodeIdentityApiError,
  QuantCodeIdentityVerifyPayload,
  QuantCodeWorkspaceApiError,
  QuantCodeWorkspacesQuery,
} from "../groups/experimental"

// All workspace routes share the host credential file. Serialize its entire
// login/logout + MCP transition, not just the signature subprocess.
const identityOperation = Semaphore.makeUnsafe(1)
function withIdentityOperation<A, E, R>(operation: Effect.Effect<A, E, R>) {
  return identityOperation.withPermitsIfAvailable(1)(operation).pipe(Effect.flatMap(Option.match({
    onNone: () => Effect.fail(new HttpApiError.BadRequest({})), onSome: Effect.succeed,
  })))
}

function unwrapQuantCodeResult(result: unknown): unknown {
      if (!result) return { error: "QuantCode MCP is not connected" }
      const payload = result as {
        isError?: boolean
        content?: unknown
        structuredContent?: unknown
      }
      const textContent = Array.isArray(payload.content)
        ? payload.content
            .filter(
              (item): item is { type: "text"; text: string } =>
                typeof item === "object" &&
                item !== null &&
                "type" in item &&
                item.type === "text" &&
                "text" in item &&
                typeof item.text === "string",
            )
            .map((item) => item.text)
        : []
      if (payload.isError) {
        const message = textContent.filter((text) => text.trim()).join("\n\n")
        return { error: message || "QuantCode read-only tool failed" }
      }
      if (payload.structuredContent !== undefined && payload.structuredContent !== null) {
        return payload.structuredContent
      }
      const text = textContent.join("\n").trim()
      if (!text) return {}
      try {
        return JSON.parse(text) as unknown
      } catch {
        return { text }
      }
}

function mapWorktreeError<A, R>(self: Effect.Effect<A, Worktree.Error, R>) {
  return self.pipe(
    Effect.mapError((error) => new WorktreeApiError({ name: error._tag, data: { message: error.message } })),
  )
}

export const experimentalHandlers = HttpApiBuilder.group(InstanceHttpApi, "experimental", (handlers) =>
  Effect.gen(function* () {
    const account = yield* Account.Service
    const agents = yield* Agent.Service
    const config = yield* Config.Service
    const mcp = yield* MCP.Service
    const project = yield* Project.Service
    const instances = yield* InstanceStore.Service
    const registry = yield* ToolRegistry.Service
    const worktreeSvc = yield* Worktree.Service
    const sessions = yield* Session.Service
    const background = yield* BackgroundJob.Service
    const flags = yield* RuntimeFlags.Service
    const database = yield* Database.Service
    const events = yield* EventV2Bridge.Service
    const processes = yield* AppProcess.Service
    const publisher = yield* QuantCodeTaskPublisher.Service
    const providers = yield* Provider.Service

    // Organization management must not depend on a model-tool MCP connection
    // in native mode. Legacy mode keeps its existing authenticated MCP source.
    const currentQuantCodeIdentity = Effect.fn("ExperimentalHttpApi.currentQuantCodeIdentity")(function* () {
      if (QuantCodeIdentity.enabled()) return yield* Effect.tryPromise({
        try: QuantCodeIdentity.currentIdentity, catch: () => new HttpApiError.BadRequest({}),
      })
      const raw = yield* (mcp.callTool ? mcp.callTool("quantcode", "session_context", {}) : Effect.succeed<unknown>(undefined))
        .pipe(Effect.catchCause(() => Effect.fail(new HttpApiError.BadRequest({}))))
      const identity = unwrapQuantCodeResult(raw)
      if (!identity || typeof identity !== "object" || !("session_id" in identity) ||
        typeof identity.session_id !== "string" || !identity.session_id) return yield* new HttpApiError.BadRequest({})
      return { ...identity, session_id: identity.session_id }
    })

    const reuse = (sessionID: string, decision?: QuantCodeReuse.Review) => Effect.gen(function* () {
      if (!QuantCodeIdentity.enabled()) return yield* new QuantCodeReuseError({ message: "统一执行引擎尚未启用。" })
      const current = decision ? yield* QuantCodeReuse.review(sessionID, decision) : yield* QuantCodeReuse.state(sessionID)
      return QuantCodeReuse.publicState(current)
    }).pipe(
      Effect.provideService(Database.Service, database),
      Effect.provideService(EventV2Bridge.Service, events),
      Effect.catchDefect(error => Effect.fail(new QuantCodeReuseError({ message:
        error instanceof QuantCodeReuse.CoverageError || error instanceof QuantCodeIdentity.IdentityError || error instanceof QuantCodeTaskLock.TaskBusyError
          ? error.message : "无法读取或保存能力方案，请刷新当前任务后重试。",
      }))),
    )

    const solution = <A, E>(operation: Effect.Effect<A, E, Database.Service | EventV2Bridge.Service | AppProcess.Service | Provider.Service>) => Effect.gen(function* () {
      if (!QuantCodeIdentity.enabled()) return yield* new QuantCodeTaskError({ message: "统一执行引擎尚未启用。" })
      return yield* operation.pipe(Effect.orDie)
    }).pipe(
      Effect.provideService(Database.Service, database),
      Effect.provideService(EventV2Bridge.Service, events),
      Effect.provideService(AppProcess.Service, processes),
      Effect.provideService(Provider.Service, providers),
      Effect.catchDefect(error => Effect.fail(new QuantCodeTaskError({ message:
        error instanceof QuantCodeTaskLock.TaskBusyError || error instanceof QuantCodeIdentity.IdentityError ||
        error instanceof QuantCodeWriteReceipt.OutcomeUnknown || error instanceof QuantCodeWriteReceipt.ReviewError
        || error instanceof QuantCodeTaskLock.RecoveryError
        || error instanceof QuantCodeBudget.ReviewError || error instanceof QuantCodeBudget.Exhausted
        || error instanceof QuantCodeLegacyHost.LegacyUnavailable
        || error instanceof QuantCodeKnowledgeHost.KnowledgeUnavailable
          ? error.message : "任务操作未完成，内容可能已变化。请重新读取当前版本后再决定。",
      }))),
    )

    const capabilities = Effect.fn("ExperimentalHttpApi.capabilities")(function* () {
      return { backgroundSubagents: flags.experimentalBackgroundSubagents, quantcodeUnifiedRuntime: QuantCodeIdentity.enabled() }
    })

    const getConsole = Effect.fn("ExperimentalHttpApi.console")(function* () {
      const [state, groups] = yield* Effect.all(
        [
          config.getConsoleState(),
          account.orgsByAccount().pipe(Effect.catch(() => Effect.fail(new HttpApiError.InternalServerError({})))),
        ],
        {
          concurrency: "unbounded",
        },
      )
      return {
        consoleManagedProviders: state.consoleManagedProviders,
        ...(state.activeOrgName ? { activeOrgName: state.activeOrgName } : {}),
        switchableOrgCount: groups.reduce((count, group) => count + group.orgs.length, 0),
      }
    })

    const listConsoleOrgs = Effect.fn("ExperimentalHttpApi.consoleOrgs")(function* () {
      const [groups, active] = yield* Effect.all(
        [
          account.orgsByAccount().pipe(Effect.catch(() => Effect.fail(new HttpApiError.InternalServerError({})))),
          account.active().pipe(Effect.catch(() => Effect.fail(new HttpApiError.InternalServerError({})))),
        ],
        {
          concurrency: "unbounded",
        },
      )
      const info = Option.getOrUndefined(active)
      return {
        orgs: groups.flatMap((group) =>
          group.orgs.map((org) => ({
            accountID: group.account.id,
            accountEmail: group.account.email,
            accountUrl: group.account.url,
            orgID: org.id,
            orgName: org.name,
            active: !!info && info.id === group.account.id && info.active_org_id === org.id,
          })),
        ),
      }
    })

    const switchConsole = Effect.fn("ExperimentalHttpApi.consoleSwitch")(function* (ctx: {
      payload: typeof ConsoleSwitchPayload.Type
    }) {
      yield* account
        .use(ctx.payload.accountID, Option.some(ctx.payload.orgID))
        .pipe(Effect.catch(() => Effect.fail(new HttpApiError.BadRequest({}))))
      return true
    })

    const tool = Effect.fn("ExperimentalHttpApi.tool")(function* (ctx: { query: typeof ToolListQuery.Type }) {
      const list = yield* registry.tools({
        providerID: ctx.query.provider,
        modelID: ctx.query.model,
        agent: yield* agents.defaultInfo(),
      })
      return list.map((item) => ({
        id: item.id,
        description: item.description,
        parameters: ToolJsonSchema.fromTool(item),
      }))
    })

    const toolIDs = Effect.fn("ExperimentalHttpApi.toolIDs")(function* () {
      return yield* registry.ids()
    })

    const quantcodeTool = Effect.fn("ExperimentalHttpApi.quantcodeTool")(function* (ctx: {
      query: typeof QuantCodeToolQuery.Type
    }) {
      if (QuantCodeIdentity.enabled() && ctx.query.tool === "list_distill_candidates") return yield* solution(QuantCodeKnowledgeHost.list())
      if (QuantCodeIdentity.enabled() && ctx.query.tool === "session_context") {
        return yield* currentQuantCodeIdentity()
      }
      const args =
        ctx.query.tool === "list_skills"
          ? { group: ctx.query.group ?? "" }
          : ctx.query.tool === "search_memory"
            ? { query: ctx.query.query ?? "", limit: ctx.query.limit ?? 10 }
            : ["list_run_history", "admin_task_history", "admin_report_history", "list_pending_gates", "list_pops"].includes(ctx.query.tool)
              ? { limit: ctx.query.limit ?? 20, cursor: ctx.query.cursor }
              : ["get_run_history", "admin_get_task_history"].includes(ctx.query.tool)
                ? { thread_id: ctx.query.thread_id, checkpoint_id: ctx.query.checkpoint_id, trace_cursor: ctx.query.trace_cursor ?? 0 }
                : {}
      if (ctx.query.tool === "list_skills" && !ctx.query.group?.trim()) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      if (ctx.query.tool === "search_memory" && !ctx.query.query?.trim()) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      if (["get_run_history", "admin_get_task_history"].includes(ctx.query.tool) && !ctx.query.thread_id?.trim()) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      if (["get_gitgraph", "list_pops"].includes(ctx.query.tool)) {
        const identity = yield* currentQuantCodeIdentity()
        const session = identity.session_id
        return yield* Effect.tryPromise({ try: () => hostGitHub(ctx.query.tool, session, args), catch: () => new HttpApiError.BadRequest({}) })
      }
      const result = yield* (mcp.callTool
        ? mcp.callTool("quantcode", ctx.query.tool, args)
        : Effect.succeed<unknown>(undefined))
      return unwrapQuantCodeResult(result)
    })

    const quantcodePop = Effect.fn("ExperimentalHttpApi.quantcodePop")(function* (ctx: {
      payload: typeof QuantCodePopPayload.Type
    }) {
      if (!ctx.payload.pop_id.trim() || (ctx.payload.read === undefined && ctx.payload.ack === undefined)) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      const identity = yield* currentQuantCodeIdentity()
      const session = identity.session_id
      return yield* Effect.tryPromise({ try: () => hostGitHub("update_pop_status", session, ctx.payload), catch: () => new HttpApiError.BadRequest({}) })
    })

    const quantcodeCandidate = Effect.fn("ExperimentalHttpApi.quantcodeCandidate")(function* (ctx: {
      payload: typeof QuantCodeCandidatePayload.Type
    }) {
      if (QuantCodeIdentity.enabled()) {
        if (!ctx.payload.expected_digest) return yield* new HttpApiError.BadRequest({})
        return yield* solution(QuantCodeKnowledgeHost.review({ ...ctx.payload, expected_digest: ctx.payload.expected_digest }))
      }
      if (!ctx.payload.candidate_name.trim() || (ctx.payload.action === "promote" && !ctx.payload.expected_digest)) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      const result = yield* (mcp.callTool
        ? mcp.callTool("quantcode", "review_distill_candidate", ctx.payload)
        : Effect.succeed<unknown>(undefined))
      return unwrapQuantCodeResult(result)
    })

    const manageDeployment = Effect.fn("ExperimentalHttpApi.manageDeployment")(function* (path: "/deployments" | "/deployments/cancel", payload?: unknown) {
      const identity = yield* currentQuantCodeIdentity()
      if (!("role" in identity) || identity.role !== "admin") {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      const sessionID = identity.session_id
      return yield* Effect.tryPromise({ try: () => quantcodeManagement(path, sessionID, payload), catch: () => new HttpApiError.BadRequest({}) })
    })
    const quantcodeDeployments = () => manageDeployment("/deployments")
    const quantcodeReceiptReconcile = Effect.fn("ExperimentalHttpApi.quantcodeReceiptReconcile")(function* (ctx: { payload: typeof QuantCodeReceiptPayload.Type }) {
      const identity = yield* currentQuantCodeIdentity()
      if (!("role" in identity) || !["admin", "approver"].includes(String(identity.role))) return yield* Effect.fail(new HttpApiError.BadRequest({}))
      const sessionID = identity.session_id
      return yield* Effect.tryPromise({ try: () => quantcodeManagement("/receipts/reconcile", sessionID, ctx.payload), catch: () => new HttpApiError.BadRequest({}) })
    })
    const quantcodeDeploymentSubmit = (ctx: { payload: typeof QuantCodeDeploymentPayload.Type }) => manageDeployment("/deployments", ctx.payload)
    const quantcodeDeploymentCancel = (ctx: { payload: typeof QuantCodeDeploymentCancelPayload.Type }) => manageDeployment("/deployments/cancel", ctx.payload)

    const quantcodeIdentities = () => Effect.tryPromise({
      try: localIdentity, catch: (error) => error,
    }).pipe(Effect.catch((error) => Effect.succeed({ identities: [], error: error instanceof Error ? error.message : "Identity bridge unavailable" })))
    const quantcodeWorkspaces = (ctx: { query: typeof QuantCodeWorkspacesQuery.Type }) => Effect.tryPromise({
      try: () => {
        if (!QuantCodeIdentity.enabled()) throw new QuantCodeWorkspace.WorkspaceDenied("当前研究宿主尚未启用统一执行引擎。")
        return QuantCodeWorkspace.list(ctx.query)
      },
      catch: error => new QuantCodeWorkspaceApiError({ message:
        error instanceof QuantCodeIdentity.IdentityError || error instanceof QuantCodeWorkspace.WorkspaceDenied
          ? error.message : "无法读取研究宿主的工作区授权，请联系管理员。" }),
    })
    const quantcodeIdentityLoginWork = Effect.fn("ExperimentalHttpApi.quantcodeIdentityLoginWork")(function* (group?: string) {
      const result = yield* Effect.tryPromise({ try: () => signInLocalIdentity(group), catch: () => new HttpApiError.BadRequest({}) })
      if (QuantCodeIdentity.enabled()) {
        yield* mcp.disconnect("quantcode").pipe(Effect.catch(() => Effect.void))
        // Identity controls use a synthetic host context. Every loaded research
        // workspace also owns transports tied to the replaced host credential.
        yield* instances.disposeAll()
        return result
      }
      yield* mcp.connect("quantcode").pipe(Effect.mapError(() => new HttpApiError.BadRequest({})))
      const confirmed = yield* (mcp.callTool ? mcp.callTool("quantcode", "session_context", {}) : Effect.succeed<unknown>(undefined))
      const identity = unwrapQuantCodeResult(confirmed)
      if (!identity || typeof identity !== "object" || !("actor_id" in identity) || !identity.actor_id) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      if (!result || typeof result !== "object" || !("session_id" in result) || !("session_id" in identity) || result.session_id !== identity.session_id) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      return result
    })
    const quantcodeIdentityLogin = (ctx: { payload?: unknown }) => withIdentityOperation(quantcodeIdentityLoginWork(
      ctx.payload && typeof ctx.payload === "object" && "group" in ctx.payload && typeof ctx.payload.group === "string"
        ? ctx.payload.group : undefined,
    ))
    const quantcodeIdentityChallenge = (ctx: { payload?: unknown }) => withIdentityOperation(Effect.tryPromise({
      try: () => createIdentityChallenge(ctx.payload && typeof ctx.payload === "object" && "identity_id" in ctx.payload ? String(ctx.payload.identity_id) : undefined),
      catch: () => new QuantCodeIdentityApiError({ message: "无法准备登录，请检查研究宿主配置与组织身份服务。" }),
    }))
    const quantcodeIdentityVerify = (ctx: { payload: typeof QuantCodeIdentityVerifyPayload.Type }) => withIdentityOperation(Effect.gen(function* () {
      const result = yield* Effect.tryPromise({
        try: () => verifyIdentityChallenge(ctx.payload),
        catch: () => new QuantCodeIdentityApiError({ message: "登录未完成，身份或登录请求可能已失效，请重试。" }),
      })
      // Authentication succeeds independently of component availability. Old
      // transports must reconnect with the newly verified member credential.
      yield* mcp.disconnect("quantcode").pipe(Effect.catch(() => Effect.void))
      if (QuantCodeIdentity.enabled()) yield* instances.disposeAll()
      return result
    }))
    const quantcodeIdentityLogout = () => withIdentityOperation(Effect.gen(function* () {
      const result = yield* Effect.tryPromise({ try: signOutLocalIdentity, catch: () => new HttpApiError.BadRequest({}) })
      yield* mcp.disconnect("quantcode").pipe(Effect.catchTag("MCP.NotFoundError", () => Effect.void))
      if (QuantCodeIdentity.enabled()) yield* instances.disposeAll()
      return result
    }))

    const worktree = Effect.fn("ExperimentalHttpApi.worktree")(function* () {
      const ctx = yield* InstanceState.context
      return yield* project.sandboxes(ctx.project.id)
    })

    const worktreeCreate = Effect.fn("ExperimentalHttpApi.worktreeCreate")(function* (ctx: {
      payload: typeof Worktree.CreateInput.Type | void
    }) {
      return yield* mapWorktreeError(worktreeSvc.create(ctx.payload ?? undefined))
    })

    const worktreeRemove = Effect.fn("ExperimentalHttpApi.worktreeRemove")(function* (input: {
      payload: Worktree.RemoveInput
    }) {
      const ctx = yield* InstanceState.context
      yield* mapWorktreeError(worktreeSvc.remove(input.payload))
      yield* project.removeSandbox(ctx.project.id, input.payload.directory)
      return true
    })

    const worktreeReset = Effect.fn("ExperimentalHttpApi.worktreeReset")(function* (ctx: {
      payload: Worktree.ResetInput
    }) {
      yield* mapWorktreeError(worktreeSvc.reset(ctx.payload))
      return true
    })

    const session = Effect.fn("ExperimentalHttpApi.session")(function* (ctx: { query: typeof SessionListQuery.Type }) {
      const limit = ctx.query.limit ?? 100
      const all = yield* sessions.listGlobal({
        directory: ctx.query.directory,
        roots: ctx.query.roots,
        start: ctx.query.start,
        cursor: ctx.query.cursor,
        search: ctx.query.search,
        limit: limit + 1,
        archived: ctx.query.archived,
      })
      const list = all.length > limit ? all.slice(0, limit) : all
      return HttpServerResponse.jsonUnsafe(list, {
        headers:
          all.length > limit && list.length > 0
            ? { "x-next-cursor": String(list[list.length - 1].time.updated) }
            : undefined,
      })
    })

    const sessionBackground = Effect.fn("ExperimentalHttpApi.sessionBackground")(function* (ctx: {
      params: { sessionID: SessionID }
    }) {
      if (!flags.experimentalBackgroundSubagents) return false
      const jobs = (yield* background.list()).filter(
        (job) =>
          job.type === "task" &&
          job.status === "running" &&
          job.metadata?.parentSessionId === ctx.params.sessionID &&
          job.metadata.background !== true,
      )
      const promoted = yield* Effect.forEach(jobs, (job) => background.promote(job.id), { concurrency: "unbounded" })
      return promoted.some((job) => job !== undefined)
    })

    const resource = Effect.fn("ExperimentalHttpApi.resource")(function* () {
      return yield* mcp.resources()
    })

    const proxyModels = Effect.fn("ExperimentalHttpApi.proxyModels")(function* (ctx: {
      query: typeof ProxyModelsQuery.Type
    }) {
      let target: URL
      try {
        target = validateProxyModelsURL(ctx.query.url)
      } catch {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }

      // DNS resolution failure is unreachability, not a policy violation.
      const addresses = yield* Effect.tryPromise({
        try: () => lookupAddresses(target.hostname),
        catch: () => undefined,
      }).pipe(Effect.catch(() => Effect.succeed<string[] | undefined>(undefined)))
      if (!addresses) return { ok: false, reachable: false }
      // Re-check resolved addresses so DNS rebinding to a private IP is caught.
      if (addresses.some((address) => isForbiddenIP(address))) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }

      // probeProxyModels never rejects: fetch and JSON failures are folded into
      // the unreachable envelope.
      return yield* Effect.promise(() => probeProxyModels(target))
    })

    return handlers
      .handle("capabilities", capabilities)
      .handle("console", getConsole)
      .handle("consoleOrgs", listConsoleOrgs)
      .handle("consoleSwitch", switchConsole)
      .handle("tool", tool)
      .handle("toolIDs", toolIDs)
      .handle("quantcodeTool", quantcodeTool)
      .handle("quantcodePop", quantcodePop)
      .handle("quantcodeCandidate", quantcodeCandidate)
      .handle("quantcodeDeployments", quantcodeDeployments)
      .handle("quantcodeReceiptReconcile", quantcodeReceiptReconcile)
      .handle("quantcodeDeploymentSubmit", quantcodeDeploymentSubmit)
      .handle("quantcodeDeploymentCancel", quantcodeDeploymentCancel)
      .handle("quantcodeIdentities", quantcodeIdentities)
      .handle("quantcodeWorkspaces", quantcodeWorkspaces)
      .handle("quantcodeIdentityLogin", quantcodeIdentityLogin)
      .handle("quantcodeIdentityChallenge", quantcodeIdentityChallenge)
      .handle("quantcodeIdentityVerify", quantcodeIdentityVerify)
      .handle("quantcodeIdentityLogout", quantcodeIdentityLogout)
      .handle("quantcodeSolution", ctx => solution(QuantCodeSolution.status(ctx.params.sessionID)))
      .handle("quantcodeSolutionProposal", ctx => solution(QuantCodeSolution.propose(ctx.params.sessionID, { ...ctx.payload,
        acceptance_criteria: [...ctx.payload.acceptance_criteria], file_impact: [...ctx.payload.file_impact] })))
      .handle("quantcodeSolutionReview", ctx => solution(QuantCodeSolution.review(ctx.params.sessionID, ctx.payload)))
      .handle("quantcodeReuse", ctx => reuse(ctx.params.sessionID))
      .handle("quantcodeReuseReview", ctx => reuse(ctx.params.sessionID, ctx.payload))
      .handle("quantcodeWriteReceipts", ctx => solution(QuantCodeWriteReceipt.status(ctx.params.sessionID)))
      .handle("quantcodeWriteReceiptReview", ctx => solution(QuantCodeWriteReceipt.review(ctx.params.sessionID, ctx.payload)))
      .handle("quantcodeTaskLock", ctx => solution(QuantCodeTaskLock.status(ctx.params.sessionID)))
      .handle("quantcodeTaskLockRecovery", ctx => solution(QuantCodeTaskLock.recover(ctx.params.sessionID, ctx.payload)))
      .handle("quantcodeBudget", ctx => solution(QuantCodeBudget.status(ctx.params.sessionID)))
      .handle("quantcodePublicationStatus", () => solution(publisher.status()))
      .handle("quantcodeTaskIndex", ctx => solution(QuantCodeTaskIndex.list({ limit: ctx.query.limit, cursor: ctx.query.cursor })))
      .handle("quantcodeTaskIndexRead", ctx => solution(QuantCodeTaskIndex.read(ctx.params.sessionID)))
      .handle("quantcodeOrganizationTasks", ctx => solution(QuantCodeOrganizationTasks.list({ limit: ctx.query.limit,
        cursor: ctx.query.cursor, source_id: ctx.query.source_id, root_session_id: ctx.query.root_session_id })))
      .handle("quantcodeOrganizationTask", ctx => solution(QuantCodeOrganizationTasks.read({ source_id: ctx.params.source_id, session_id: ctx.params.sessionID })))
      .handle("quantcodeTaskArtifacts", ctx => solution(QuantCodeTaskIndex.listArtifacts({ sessionID: ctx.params.sessionID,
        source_revision: ctx.query.source_revision, limit: ctx.query.limit, cursor: ctx.query.cursor })))
      .handle("quantcodeTaskArtifact", ctx => solution(QuantCodeTaskIndex.readArtifact({ sessionID: ctx.params.sessionID,
        source_revision: ctx.query.source_revision, artifact_id: ctx.params.artifact_id, offset: ctx.query.offset })))
      .handle("quantcodeOrganizationArtifacts", ctx => solution(QuantCodeOrganizationTasks.listArtifacts({ source_id: ctx.params.source_id,
        session_id: ctx.params.sessionID, source_revision: ctx.query.source_revision, limit: ctx.query.limit, cursor: ctx.query.cursor })))
      .handle("quantcodeOrganizationArtifact", ctx => solution(QuantCodeOrganizationTasks.readArtifact({ source_id: ctx.params.source_id,
        session_id: ctx.params.sessionID, source_revision: ctx.query.source_revision, artifact_id: ctx.params.artifact_id, offset: ctx.query.offset })))
      .handle("quantcodeLegacyTasks", ctx => solution(QuantCodeLegacyHost.list({ limit: ctx.query.limit, cursor: ctx.query.cursor,
        organization: ctx.query.organization, reports_only: ctx.query.reports_only, group_filter: ctx.query.group_filter })))
      .handle("quantcodeLegacyDetail", ctx => solution(QuantCodeLegacyHost.detail({ thread_id: ctx.params.thread_id,
        checkpoint_id: ctx.query.checkpoint_id, trace_cursor: ctx.query.trace_cursor, organization: ctx.query.organization })))
      .handle("quantcodeLegacyResume", ctx => solution(QuantCodeLegacyHost.resume(ctx.payload)))
      .handle("quantcodeLegacyRequestApproval", ctx => solution(QuantCodeLegacyHost.requestApproval(ctx.payload)))
      .handle("quantcodeBudgetReviewState", ctx => solution(QuantCodeBudget.reviewState(ctx.params.sessionID)))
      .handle("quantcodeBudgetReview", ctx => solution(QuantCodeBudget.reviewUsage(ctx.params.sessionID, ctx.payload)))
      .handle("quantcodeBudgetRecoverLock", ctx => solution(QuantCodeBudget.recoverLock(ctx.params.sessionID, ctx.payload)))
      .handle("quantcodeNativeGates", ctx => solution(QuantCodeGate.list(ctx.query.cursor)))
      .handle("quantcodeNativeGateRead", ctx => solution(QuantCodeGate.read(ctx.params.gateID)))
      .handle("quantcodeNativeGateDecision", ctx => solution(QuantCodeGate.decide(ctx.payload)))
      .handle("quantcodeGitHubCommit", ctx => Effect.tryPromise({ try: () => githubCommit(ctx.query.repo, ctx.query.sha), catch: () => new HttpApiError.BadRequest({}) }))
      .handle("quantcodeGitHubStatus", () => Effect.tryPromise({ try: () => githubConnection(), catch: () => new HttpApiError.BadRequest({}) }))
      .handle("quantcodeGitHubCredentialPrepare", () => Effect.tryPromise({ try: prepareGitHubCredential, catch: () => new HttpApiError.BadRequest({}) }))
      .handle("quantcodeGitHubCredentialImport", ctx => Effect.gen(function* () {
        const request = yield* HttpServerRequest.HttpServerRequest
        if (request.headers.origin) return yield* new HttpApiError.BadRequest({})
        return yield* Effect.tryPromise({ try: () => importGitHubCredential(ctx.payload), catch: () => new HttpApiError.BadRequest({}) })
      }))
      .handle("quantcodeGitHubConnect", (ctx) => Effect.tryPromise({ try: () => githubConnection(ctx.payload.mode), catch: () => new HttpApiError.BadRequest({}) }))
      .handle("worktree", worktree)
      .handle("worktreeCreate", worktreeCreate)
      .handle("worktreeRemove", worktreeRemove)
      .handle("worktreeReset", worktreeReset)
      .handle("session", session)
      .handle("sessionBackground", sessionBackground)
      .handle("resource", resource)
      .handle("proxyModels", proxyModels)
  }),
)

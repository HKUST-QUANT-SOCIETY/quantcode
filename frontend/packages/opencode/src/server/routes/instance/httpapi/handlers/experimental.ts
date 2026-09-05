import { localIdentity, signInLocalIdentity } from "./quantcode-identity"
import { quantcodeManagement } from "./quantcode-management"
import { Account } from "@/account/account"
import { Agent } from "@/agent/agent"
import { BackgroundJob } from "@/background/job"
import { Config } from "@/config/config"
import { InstanceState } from "@/effect/instance-state"
import { RuntimeFlags } from "@/effect/runtime-flags"
import { MCP } from "@/mcp"
import { Project } from "@/project/project"
import { Session } from "@/session/session"
import type { SessionID } from "@/session/schema"
import { ToolJsonSchema } from "@/tool/json-schema"
import { ToolRegistry } from "@/tool/registry"
import { Worktree } from "@/worktree"
import { Effect, Option } from "effect"
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
} from "../groups/experimental"

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
    const registry = yield* ToolRegistry.Service
    const worktreeSvc = yield* Worktree.Service
    const sessions = yield* Session.Service
    const background = yield* BackgroundJob.Service
    const flags = yield* RuntimeFlags.Service

    const capabilities = Effect.fn("ExperimentalHttpApi.capabilities")(function* () {
      return { backgroundSubagents: flags.experimentalBackgroundSubagents }
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
      const result = yield* (mcp.callTool
        ? mcp.callTool("quantcode", "update_pop_status", ctx.payload)
        : Effect.succeed<unknown>(undefined))
      return unwrapQuantCodeResult(result)
    })

    const quantcodeCandidate = Effect.fn("ExperimentalHttpApi.quantcodeCandidate")(function* (ctx: {
      payload: typeof QuantCodeCandidatePayload.Type
    }) {
      if (!ctx.payload.candidate_name.trim() || (ctx.payload.action === "promote" && !ctx.payload.expected_digest)) {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      const result = yield* (mcp.callTool
        ? mcp.callTool("quantcode", "review_distill_candidate", ctx.payload)
        : Effect.succeed<unknown>(undefined))
      return unwrapQuantCodeResult(result)
    })

    const manageDeployment = Effect.fn("ExperimentalHttpApi.manageDeployment")(function* (path: "/deployments" | "/deployments/cancel", payload?: unknown) {
      const result = yield* (mcp.callTool ? mcp.callTool("quantcode", "session_context", {}) : Effect.succeed<unknown>(undefined))
      const identity = unwrapQuantCodeResult(result)
      if (!identity || typeof identity !== "object" || !("role" in identity) || identity.role !== "admin" || !("session_id" in identity) || typeof identity.session_id !== "string") {
        return yield* Effect.fail(new HttpApiError.BadRequest({}))
      }
      const sessionID = identity.session_id
      return yield* Effect.tryPromise({ try: () => quantcodeManagement(path, sessionID, payload), catch: () => new HttpApiError.BadRequest({}) })
    })
    const quantcodeDeployments = () => manageDeployment("/deployments")
    const quantcodeReceiptReconcile = Effect.fn("ExperimentalHttpApi.quantcodeReceiptReconcile")(function* (ctx: { payload: typeof QuantCodeReceiptPayload.Type }) {
      const raw = yield* (mcp.callTool ? mcp.callTool("quantcode", "session_context", {}) : Effect.succeed<unknown>(undefined))
      const identity = unwrapQuantCodeResult(raw)
      if (!identity || typeof identity !== "object" || !("role" in identity) || !["admin", "approver"].includes(String(identity.role))
        || !("session_id" in identity) || typeof identity.session_id !== "string") return yield* Effect.fail(new HttpApiError.BadRequest({}))
      const sessionID = identity.session_id
      return yield* Effect.tryPromise({ try: () => quantcodeManagement("/receipts/reconcile", sessionID, ctx.payload), catch: () => new HttpApiError.BadRequest({}) })
    })
    const quantcodeDeploymentSubmit = (ctx: { payload: typeof QuantCodeDeploymentPayload.Type }) => manageDeployment("/deployments", ctx.payload)
    const quantcodeDeploymentCancel = (ctx: { payload: typeof QuantCodeDeploymentCancelPayload.Type }) => manageDeployment("/deployments/cancel", ctx.payload)

    const quantcodeIdentities = () => Effect.tryPromise({
      try: localIdentity, catch: (error) => error,
    }).pipe(Effect.catch((error) => Effect.succeed({ identities: [], error: error instanceof Error ? error.message : "Identity bridge unavailable" })))
    const quantcodeIdentityLoginWork = Effect.fn("ExperimentalHttpApi.quantcodeIdentityLoginWork")(function* () {
      const result = yield* Effect.tryPromise({ try: signInLocalIdentity, catch: () => new HttpApiError.BadRequest({}) })
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
    let identityConnecting = false
    const quantcodeIdentityLogin = Effect.fn("ExperimentalHttpApi.quantcodeIdentityLogin")(() =>
      Effect.suspend(() => {
        if (identityConnecting) return Effect.fail(new HttpApiError.BadRequest({}))
        identityConnecting = true
        // Admission covers signing, reconnecting MCP, and confirming its exact
        // session. Coalescing only the signature still allowed duplicate connects.
        return quantcodeIdentityLoginWork().pipe(Effect.ensuring(Effect.sync(() => { identityConnecting = false })))
      }),
    )

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
      .handle("quantcodeIdentityLogin", quantcodeIdentityLogin)
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

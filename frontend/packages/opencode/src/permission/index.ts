import { QuantCodeAccess } from "@/quantcode/access"
import { Database } from "@opencode-ai/core/database/database"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { ConfigPermissionV1 } from "@opencode-ai/core/v1/config/permission"
import { InstanceState } from "@/effect/instance-state"
import { Wildcard } from "@opencode-ai/core/util/wildcard"
import { Deferred, Effect, Layer, Context } from "effect"
import os from "os"
import { PermissionV1 } from "@opencode-ai/core/v1/permission"
import { EventV2Bridge } from "@/event-v2-bridge"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { QuantCodeNativeGate } from "@opencode-ai/schema/quantcode-native-gate"
import { QuantCodeGate } from "@/quantcode/gate"

/** Server-only admission input. Public metadata is never sufficient to create
 * an exact gate; only this method can attach its live revalidation closure. */
export interface ExactInput {
  sessionID: PermissionV1.Request["sessionID"]
  tool: NonNullable<PermissionV1.Request["tool"]>
  kind: "merge" | "permission"
  resource: string
  digest: string
  description: string
  server: string
  toolName: string
  catalogDigest: string
  argumentsJson: string
  argumentsDigest: string
  resourceVersion?: string
  revalidate: () => Effect.Effect<void>
}
export type ExactApproval = { gateID: string; recordDigest: string; operationDigest: string }

export const Event = PermissionV1.Event

export interface Interface {
  readonly ask: (input: PermissionV1.AskInput) => Effect.Effect<void, PermissionV1.Error>
  readonly askExact: (input: ExactInput) => Effect.Effect<ExactApproval, PermissionV1.Error>
  readonly reply: (input: PermissionV1.ReplyInput) => Effect.Effect<void, PermissionV1.NotFoundError>
  readonly list: () => Effect.Effect<ReadonlyArray<PermissionV1.Request>>
}

interface PendingEntry {
  exact?: { digest: string; expires: number; remote?: QuantCodeNativeGate.View; resolving?: boolean; revalidate: () => Effect.Effect<void> }
  deciding?: boolean
  loginSession?: string
  info: PermissionV1.Request
  deferred: Deferred.Deferred<void, PermissionV1.RejectedError | PermissionV1.CorrectedError>
}

interface State {
  pending: Map<PermissionV1.ID, PendingEntry>
  approved: PermissionV1.Rule[]
  sessionApproved: Map<string, PermissionV1.Rule[]>
}

export function evaluate(permission: string, pattern: string, ...rulesets: PermissionV1.Ruleset[]): PermissionV1.Rule {
  return (
    rulesets
      .flat()
      .findLast((rule) => Wildcard.match(permission, rule.permission) && Wildcard.match(pattern, rule.pattern)) ?? {
      action: "ask",
      permission,
      pattern: "*",
    }
  )
}

export class Service extends Context.Service<Service, Interface>()("@opencode/Permission") {}

const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const events = yield* EventV2Bridge.Service
    const database = yield* Database.Service
    const authorize = (sessionID: string) => QuantCodeAccess.requireSession(sessionID).pipe(Effect.provideService(Database.Service, database))
    const applyRemoteDecision = (entry: PendingEntry, gate: QuantCodeNativeGate.View) => Effect.gen(function* () {
      const exact = entry.exact
      if (!exact?.remote || exact.resolving || (yield* Deferred.isDone(entry.deferred))) return
      if (exact.resolving) return
      if (gate.record_digest !== exact.remote.record_digest || !QuantCodeGate.matches(gate, exact.remote.request, entry.loginSession!)) throw new Error("组织审批记录与原调用不一致。")
      if (!gate.valid || ["expired", "cancelled"].includes(gate.status)) {
        yield* Deferred.fail(entry.deferred, new PermissionV1.RejectedError())
        return
      }
      if (gate.status === "pending") return
      const decision = gate.decision
      if (!decision || decision.operation_digest !== exact.digest || decision.record_digest !== gate.record_digest ||
          (gate.status === "approved") !== (decision.decision === "approve")) throw new Error("组织审批凭据无效。")
      exact.resolving = true
      yield* Effect.gen(function* () {
        yield* exact.revalidate()
        yield* events.publish(QuantCodeGovernance.GateDecided, { sessionID: entry.info.sessionID,
          request_id: entry.info.id, operation_digest: exact.digest, decision: decision.decision,
          reviewer: decision.reviewer, note: decision.note, timestamp: decision.timestamp })
        yield* events.publish(Event.Replied, { sessionID: entry.info.sessionID, requestID: entry.info.id,
          reply: decision.decision === "approve" ? "once" : "reject" })
        if (decision.decision === "approve") yield* Deferred.succeed(entry.deferred, undefined)
        else yield* Deferred.fail(entry.deferred, new PermissionV1.RejectedError())
      }).pipe(Effect.ensuring(Effect.sync(() => { exact.resolving = false })))
    })
    const state = yield* InstanceState.make<State>(
      Effect.fn("Permission.state")(function* (ctx) {
        void ctx
        const state = {
          pending: new Map<PermissionV1.ID, PendingEntry>(),
          approved: [],
          sessionApproved: new Map<string, PermissionV1.Rule[]>(),
        }

        yield* Effect.addFinalizer(() =>
          Effect.gen(function* () {
            for (const item of state.pending.values()) {
              yield* Deferred.fail(item.deferred, new PermissionV1.RejectedError())
            }
            state.pending.clear()
            state.sessionApproved.clear()
          }),
        )

        return state
      }),
    )

    const requestPermission = Effect.fn("Permission.ask")(function* (input: PermissionV1.AskInput, exact?: ExactInput) {
      const access = yield* authorize(input.sessionID)
      const current = yield* InstanceState.get(state)
      const pending = current.pending
      const approved = access ? current.sessionApproved.get(`${access.identity.session_id}:${input.sessionID}`) ?? [] : current.approved
      const { ruleset, ...request } = input
      let needsAsk = !!exact

      for (const pattern of exact ? [] : request.patterns) {
        const rule = evaluate(request.permission, pattern, ruleset, approved)
        yield* Effect.logInfo("evaluated", { permission: request.permission, pattern, action: rule })
        if (rule.action === "deny") {
          return yield* new PermissionV1.DeniedError({
            ruleset: ruleset.filter((rule) => Wildcard.match(request.permission, rule.permission)),
          })
        }
        if (rule.action === "allow") continue
        needsAsk = true
      }

      if (!needsAsk) return

      const id = request.id ?? PermissionV1.ID.ascending()
      const info: PermissionV1.Request = {
        id,
        sessionID: request.sessionID,
        permission: request.permission,
        patterns: request.patterns,
        metadata: request.metadata,
        always: request.always,
        tool: request.tool,
      }
      yield* Effect.logInfo("asking", { id, permission: info.permission, patterns: info.patterns })

      const deferred = yield* Deferred.make<void, PermissionV1.RejectedError | PermissionV1.CorrectedError>()
      const expires = Math.min(Date.now() + 590_000, access ? Date.parse(access.identity.expires_at) - 1000 : Infinity)
      const entry: PendingEntry = { info, deferred, loginSession: access?.identity.session_id,
        exact: exact ? { digest: exact.digest, expires, revalidate: exact.revalidate } : undefined }
      pending.set(id, entry)
      let exactApproved = false
      return yield* Effect.scoped(Effect.ensuring(
        Effect.gen(function* () {
          if (exact && access) {
            const request: QuantCodeNativeGate.Request = { request_id: id, root_session_id: access.binding.root_session_id,
              session_id: input.sessionID, message_id: exact.tool.messageID, call_id: exact.tool.callID,
              server: exact.server, tool: exact.toolName, kind: exact.kind, resource: exact.resource,
              ...(exact.resourceVersion ? { resource_version: exact.resourceVersion } : {}),
              operation_digest: exact.digest, catalog_digest: exact.catalogDigest, arguments_json: exact.argumentsJson,
              arguments_digest: exact.argumentsDigest, description: exact.description, expires_at: expires }
            if (expires <= Date.now() || Buffer.byteLength(JSON.stringify(request)) > 14000) throw new Error("审批内容过大或登录即将过期，请缩小请求或重新登录。")
            const remote = yield* QuantCodeGate.publish(request, access.identity.session_id)
            entry.exact!.remote = remote
            if (!QuantCodeGate.matches(remote, request, access.identity.session_id)) throw new Error("组织审批发布结果不匹配当前操作。")
          }
          if (exact && access) yield* events.publish(QuantCodeGovernance.GateRequested, {
            sessionID: input.sessionID, request_id: id, operation_digest: exact.digest,
            kind: exact.kind, resource: exact.resource, actor: access.identity.actor_id, expires_at: expires,
          })
          yield* events.publish(Event.Asked, info)
          if (exact) yield* Effect.gen(function* () {
            while (!(yield* Deferred.isDone(deferred))) {
              const gate = yield* QuantCodeGate.read(entry.exact!.remote!.gate_id, access!.identity.session_id)
              yield* applyRemoteDecision(entry, gate)
              if (!(yield* Deferred.isDone(deferred))) yield* Effect.sleep("2 seconds")
            }
          }).pipe(Effect.catchCause(() => Deferred.fail(deferred, new PermissionV1.RejectedError())), Effect.forkScoped)
          yield* (exact ? Deferred.await(deferred).pipe(Effect.timeoutOrElse({
            duration: "10 minutes", orElse: () => Effect.fail(new PermissionV1.RejectedError()),
          })) : Deferred.await(deferred))
          const current = yield* authorize(input.sessionID)
          if (current?.identity.session_id !== access?.identity.session_id) throw new QuantCodeIdentity.IdentityError()
          if (exact) {
            yield* exact.revalidate()
            const gate = yield* QuantCodeGate.read(entry.exact!.remote!.gate_id, access!.identity.session_id)
            if (!gate.valid || gate.status !== "approved" || gate.record_digest !== entry.exact!.remote!.record_digest) throw new Error("审批已失效，请重新申请。")
            exactApproved = true
            return { gateID: gate.gate_id, recordDigest: gate.record_digest, operationDigest: exact.digest }
          }
        }),
        Effect.gen(function* () {
          if (exact && !exactApproved && entry.exact?.remote) yield* QuantCodeGate.cancel(entry.exact.remote, access!.identity.session_id).pipe(Effect.ignoreCause)
          const removed = pending.delete(id)
          // Expiry/cancellation must clear the existing desktop permission
          // prompt; it is not a user approval and creates no approval record.
          if (removed && exact && !exactApproved) yield* events.publish(Event.Replied, { sessionID: input.sessionID, requestID: id, reply: "reject" })
        }),
      ))
    })

    const ask = (input: PermissionV1.AskInput) => requestPermission(input).pipe(Effect.asVoid)
    const askExact = Effect.fn("Permission.askExact")(function* (input: ExactInput) {
      if (!QuantCodeIdentity.enabled() || !/^[a-f0-9]{64}$/.test(input.digest) || !input.resource.trim() ||
          !["merge", "permission"].includes(input.kind)) throw new Error("无效的组织审批请求。")
      yield* input.revalidate()
      const approval = yield* requestPermission({ sessionID: input.sessionID, tool: input.tool,
        permission: `quantcode.${input.kind}`, patterns: [input.resource], always: [], ruleset: [],
        metadata: { quantcodeExactGate: { kind: input.kind, digest: input.digest, resource: input.resource,
          description: input.description, arguments_json: input.argumentsJson } },
      }, input)
      if (!approval) throw new Error("组织审批未形成有效决定。")
      return approval
    })

    const reply = Effect.fn("Permission.reply")(function* (input: PermissionV1.ReplyInput) {
      const current = yield* InstanceState.get(state)
      const pending = current.pending
      const existing = pending.get(input.requestID)
      if (!existing) return yield* new PermissionV1.NotFoundError({ requestID: input.requestID })
      const access = yield* authorize(existing.info.sessionID)
      if (existing.loginSession !== access?.identity.session_id) return yield* new PermissionV1.NotFoundError({ requestID: input.requestID })
      if (existing.deciding) return yield* new PermissionV1.NotFoundError({ requestID: input.requestID })
      if (existing.exact) {
        if (!access || input.expected_digest !== existing.exact.digest || input.reply === "always" ||
            Date.now() >= existing.exact.expires || (input.reply !== "reject" && !["approver", "admin"].includes(access.identity.role))) {
          return yield* new PermissionV1.NotFoundError({ requestID: input.requestID })
        }
        existing.deciding = true
        return yield* Effect.gen(function* () {
          yield* existing.exact!.revalidate()
          const current = yield* authorize(existing.info.sessionID)
          if (current?.identity.session_id !== existing.loginSession || Date.now() >= existing.exact!.expires) {
            return yield* new PermissionV1.NotFoundError({ requestID: input.requestID })
          }
          const remote = existing.exact!.remote
          if (!remote) throw new Error("审批尚未登记到组织服务。")
          if (input.reply === "reject" && access.identity.role === "analyst") {
            yield* QuantCodeGate.cancel(remote, access.identity.session_id)
            yield* Deferred.fail(existing.deferred, new PermissionV1.RejectedError())
            return
          }
          const decision = yield* QuantCodeGate.decide({ gate_id: remote.gate_id, expected_digest: remote.record_digest,
            operation_digest: existing.exact!.digest, decision: input.reply === "reject" ? "reject" : "approve",
            note: input.message?.trim() || (input.reply === "reject" ? "拒绝本次操作" : "确认本次操作的资源、参数和版本"),
          })
          yield* applyRemoteDecision(existing, decision)
        }).pipe(Effect.ensuring(Effect.sync(() => { existing.deciding = false })))
      }
      const key = access ? `${access.identity.session_id}:${existing.info.sessionID}` : undefined
      const approved = key ? current.sessionApproved.get(key) ?? [] : current.approved
      if (key) current.sessionApproved.set(key, approved)

      pending.delete(input.requestID)
      yield* events.publish(Event.Replied, {
        sessionID: existing.info.sessionID,
        requestID: existing.info.id,
        reply: input.reply,
      })

      if (input.reply === "reject") {
        yield* Deferred.fail(
          existing.deferred,
          input.message
            ? new PermissionV1.CorrectedError({ feedback: input.message })
            : new PermissionV1.RejectedError(),
        )

        for (const [id, item] of pending.entries()) {
          if (item.exact) continue
          if (item.info.sessionID !== existing.info.sessionID) continue
          pending.delete(id)
          yield* events.publish(Event.Replied, {
            sessionID: item.info.sessionID,
            requestID: item.info.id,
            reply: "reject",
          })
          yield* Deferred.fail(item.deferred, new PermissionV1.RejectedError())
        }
        return
      }

      yield* Deferred.succeed(existing.deferred, undefined)
      if (input.reply === "once") return

      for (const pattern of existing.info.always) {
        approved.push({
          permission: existing.info.permission,
          pattern,
          action: "allow",
        })
      }

      for (const [id, item] of pending.entries()) {
        if (item.exact) continue
        if (item.info.sessionID !== existing.info.sessionID) continue
        const ok = item.info.patterns.every(
          (pattern) => evaluate(item.info.permission, pattern, approved).action === "allow",
        )
        if (!ok) continue
        pending.delete(id)
        yield* events.publish(Event.Replied, {
          sessionID: item.info.sessionID,
          requestID: item.info.id,
          reply: "always",
        })
        yield* Deferred.succeed(item.deferred, undefined)
      }
    })

    const list = Effect.fn("Permission.list")(function* () {
      const pending = (yield* InstanceState.get(state)).pending
      return Array.from(pending.values(), (item) => item.info)
    })

    return Service.of({ ask, askExact, reply, list })
  }),
)

function expand(pattern: string): string {
  if (pattern.startsWith("~/")) return os.homedir() + pattern.slice(1)
  if (pattern === "~") return os.homedir()
  if (pattern.startsWith("$HOME/")) return os.homedir() + pattern.slice(5)
  if (pattern.startsWith("$HOME")) return os.homedir() + pattern.slice(5)
  return pattern
}

export function fromConfig(permission: ConfigPermissionV1.Info) {
  const ruleset: PermissionV1.Rule[] = []
  for (const [key, value] of Object.entries(permission)) {
    if (typeof value === "string") {
      ruleset.push({ permission: key, action: value, pattern: "*" })
      continue
    }
    ruleset.push(
      ...Object.entries(value).map(([pattern, action]) => ({ permission: key, pattern: expand(pattern), action })),
    )
  }
  return ruleset
}

export function merge(...rulesets: PermissionV1.Ruleset[]): PermissionV1.Rule[] {
  return rulesets.flat()
}

export function disabled(tools: string[], ruleset: PermissionV1.Ruleset): Set<string> {
  const edits = ["edit", "write", "apply_patch"]
  const reads = ["list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"]
  return new Set(
    tools.filter((tool) => {
      const permission = edits.includes(tool) ? "edit" : reads.includes(tool) ? "read" : tool
      const rule = ruleset.findLast((rule) => Wildcard.match(permission, rule.permission))
      return rule?.pattern === "*" && rule.action === "deny"
    }),
  )
}

export const node = LayerNode.make({ service: Service, layer: layer, deps: [EventV2Bridge.node, Database.node] })

export * as Permission from "."

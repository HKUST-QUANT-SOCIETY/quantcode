import path from "node:path"
import { randomUUID } from "node:crypto"
import os from "node:os"
import { Effect, Schema } from "effect"
import { and, asc, eq, inArray } from "drizzle-orm"
import { asSchema, type ModelMessage, type Tool } from "ai"
import type { ProviderMetadata, Usage } from "@opencode-ai/llm"
import { Database } from "@opencode-ai/core/database/database"
import { EventTable } from "@opencode-ai/core/event/sql"
import { Global } from "@opencode-ai/core/global"
import { Flock } from "@opencode-ai/core/util/flock"
import { QuantCodeBudgetEvent } from "@opencode-ai/schema/quantcode-budget"
import { EventV2Bridge } from "@/event-v2-bridge"
import { SessionID } from "@/session/schema"
import type { Provider } from "@/provider/provider"
import { SessionUsage } from "@/session/usage"
import { QuantCodeAccess } from "./access"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeToolCatalog } from "./tool-catalog"
import { EffectBridge } from "@/effect/bridge"

export class ReviewError extends Error {}
const lockDirectory = () => path.join(Global.Path.state, "locks")

/** Budget is a resource stop, never a HumanGate or a model-authored allowance. */
export class Exhausted extends Error {
  readonly code = "stopped_budget"
  constructor(readonly reason: "token_limit" | "capacity_reserved" | "input_too_large") {
    super(reason === "capacity_reserved"
      ? "当前任务的剩余预算已由并行请求占用，或上次请求用量尚未确认。请查看任务用量。"
      : reason === "input_too_large"
        ? "当前输入超出剩余任务预算，模型请求已停止。"
        : "当前任务树的 token 预算已耗尽，已停止后续模型请求和工具执行。")
    this.name = "QuantCodeBudgetExhausted"
  }
}

function configuredLimit() {
  const value = process.env.QUANTCODE_TOKEN_BUDGET ?? "200000"
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error("QUANTCODE_TOKEN_BUDGET 必须为非负整数。")
  return Number(value) === 0 ? null : Number(value)
}

/** Only account changes take a lock. Holding the task execution lock for an
 * entire provider stream would deadlock a parent waiting on a child tool. */
function locked<A, E, R>(root: string, operation: Effect.Effect<A, E, R>) {
  return Effect.scoped(Effect.gen(function* () {
    yield* Flock.effect(`quantcode-budget:${root}`, {
      dir: lockDirectory(), staleMs: Number.POSITIVE_INFINITY, timeoutMs: 5000,
    })
    return yield* operation
  }))
}

const read = Effect.fn("QuantCodeBudget.read")(function* (sessionID: string, root: string) {
  const { db } = yield* Database.Service
  const rows = yield* db.select({ type: EventTable.type, data: EventTable.data }).from(EventTable)
    .where(and(eq(EventTable.aggregate_id, root), inArray(EventTable.type, [
      "quantcode.budget.policy.1", "quantcode.budget.reserved.1", "quantcode.budget.settled.1",
      "quantcode.budget.request_ended.1", "quantcode.budget.reviewed.1",
    ]))).orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
  let policy: typeof QuantCodeBudgetEvent.Policy.data.Type | undefined
  const requests = new Map<string, { reservation: typeof QuantCodeBudgetEvent.Reserved.data.Type;
    settled?: typeof QuantCodeBudgetEvent.Settled.data.Type; ended?: boolean }>()
  for (const row of rows) {
    if (row.type === "quantcode.budget.policy.1") {
      if (policy) throw new Error("任务预算存在重复策略记录，不能继续执行。")
      policy = Schema.decodeUnknownSync(QuantCodeBudgetEvent.Policy.data)(row.data)
      continue
    }
    if (row.type === "quantcode.budget.reserved.1") {
      const reservation = Schema.decodeUnknownSync(QuantCodeBudgetEvent.Reserved.data)(row.data)
      if (!policy || requests.has(reservation.request_id) || reservation.tokens !== reservation.input_estimate + reservation.output_limit) {
        throw new Error("任务预算预留记录不一致，不能继续执行。")
      }
      requests.set(reservation.request_id, { reservation })
      continue
    }
    if (row.type === "quantcode.budget.request_ended.1") {
      const ended = Schema.decodeUnknownSync(QuantCodeBudgetEvent.Ended.data)(row.data)
      const previous = requests.get(ended.request_id)
      if (!previous || previous.reservation.source_session_id !== ended.source_session_id || previous.ended) {
        throw new Error("模型请求结束记录不一致，不能继续执行。")
      }
      previous.ended = true
      continue
    }
    const reviewed = row.type === "quantcode.budget.reviewed.1"
      ? Schema.decodeUnknownSync(QuantCodeBudgetEvent.Reviewed.data)(row.data)
      : undefined
    const settled = reviewed ?? Schema.decodeUnknownSync(QuantCodeBudgetEvent.Settled.data)(row.data)
    const previous = requests.get(settled.request_id)
    if (!previous || previous.settled || previous.reservation.source_session_id !== settled.source_session_id ||
        settled.tokens < settled.input_tokens + settled.output_tokens) throw new Error("任务用量记录不一致，不能继续执行。")
    if (reviewed && (reviewed.reservation_digest !== QuantCodeToolCatalog.digest(previous.reservation) ||
        reviewed.decision === "confirmed_not_executed" && (reviewed.input_tokens !== 0 || reviewed.output_tokens !== 0 || reviewed.tokens !== 0 || reviewed.cost !== 0))) {
      throw new Error("人工核对记录与原模型请求不匹配。")
    }
    previous.settled = settled
  }
  // A host may lower the current cap. Restart/resume and a child session cannot
  // silently raise a task's original budget or reset its consumed amount.
  const configured = configuredLimit()
  const limits = [policy?.token_limit, configured].filter((value): value is number => typeof value === "number")
  const limit = limits.length ? Math.min(...limits) : null
  const values = [...requests.values()]
  const used = values.reduce((sum, item) => sum + (item.settled?.tokens ?? 0), 0)
  const reserved = values.reduce((sum, item) => sum + (item.settled ? 0 : item.reservation.tokens), 0)
  if (!Number.isSafeInteger(used) || !Number.isSafeInteger(reserved)) throw new Error("任务累计用量无效，不能继续执行。")
  const state: QuantCodeBudgetEvent.State = {
    session_id: SessionID.make(sessionID), root_session_id: SessionID.make(root), token_limit: limit,
    used, reserved, remaining: limit === null ? null : Math.max(0, limit - used - reserved),
    known_cost: values.reduce((sum, item) => sum + (item.settled?.cost ?? 0), 0),
    unpriced_requests: values.filter(item => item.settled?.cost == null).length,
    requests: values.length, unconfirmed_requests: values.filter(item => !item.settled).length,
    status: limit !== null && used >= limit ? "stopped_budget" : limit !== null && used + reserved >= limit * 0.8 ? "warning" : "active",
  }
  return { policy, requests, state }
})

const changed = Effect.fn("QuantCodeBudget.changed")(function* (state: QuantCodeBudgetEvent.State, reason?: Exhausted["reason"]) {
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeBudgetEvent.Changed, {
    sessionID: state.root_session_id, state, timestamp: Date.now(), ...(reason ? { reason } : {}),
  })
})

export const status = Effect.fn("QuantCodeBudget.status")(function* (sessionID: string) {
  const access = yield* QuantCodeAccess.requireSession(sessionID)
  if (!access) throw new QuantCodeIdentity.IdentityError()
  const result = yield* read(sessionID, access.binding.root_session_id)
  const current = yield* QuantCodeAccess.requireSession(sessionID)
  if (!current || current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
  return result.state
})

/** Use at tool admission as well as LLM admission. A current request's own
 * reservation does not prohibit its tools; confirmed exhaustion does. */
export const check = Effect.fn("QuantCodeBudget.check")(function* (sessionID: string) {
  if (!QuantCodeIdentity.enabled()) return
  const state = yield* status(sessionID)
  if (state.status === "stopped_budget") throw new Exhausted("token_limit")
})

type Request = {
  sessionID: string; model: Provider.Model; purpose: string; messages: ModelMessage[];
  tools: Record<string, Tool>; options: Record<string, unknown>; maxOutputTokens?: number;
}
export type Reservation = {
  root: string; sessionID: string; requestID: string; loginID: string; outputLimit: number;
}

export const reserve = Effect.fn("QuantCodeBudget.reserve")(function* (input: Request) {
  const access = yield* QuantCodeAccess.requireExecution(input.sessionID)
  if (!access) throw new QuantCodeIdentity.IdentityError()
  const root = access.binding.root_session_id
  const definitions = yield* Effect.promise(() => Promise.all(Object.entries(input.tools).map(async ([name, tool]) => ({
    name, description: tool.description, schema: await asSchema(tool.inputSchema).jsonSchema,
  }))))
  // UTF-8 bytes deliberately overestimate normal text tokenization. Tool
  // schemas and provider options count too. External/media inputs cannot be
  // sized from their URL/base64 text, so reserve the model's whole input window.
  // This is an admission estimate, not a fabricated provider usage receipt.
  // Arbitrary compatible APIs can tokenize differently or ignore max_tokens.
  // Neither this estimate nor the provider's configured context length proves
  // a mathematical spending ceiling. Actual overruns are retained and stop
  // further work; deployments needing an absolute billing cap need one at the
  // model provider/gateway as well.
  const media = input.messages.some(message => Array.isArray(message.content) && message.content.some(part =>
    "type" in part && (part.type === "image" || part.type === "file")))
  const textEstimate = Buffer.byteLength(JSON.stringify({ messages: input.messages, tools: definitions, options: input.options }), "utf8") +
    1024 + input.messages.length * 64 + definitions.length * 64
  const context = input.model.limit.input || input.model.limit.context
  if (media && (!Number.isSafeInteger(context) || context <= 0)) throw new Exhausted("input_too_large")
  const estimatedInput = media ? context : textEstimate
  const requestedOutput = input.maxOutputTokens ?? input.model.limit.output
  if (!Number.isSafeInteger(requestedOutput) || requestedOutput <= 0) throw new Error("模型输出上限无效，无法预留任务预算。")
  return yield* locked(root, Effect.gen(function* () {
    const current = yield* QuantCodeAccess.requireSession(input.sessionID)
    if (!current || current.identity.session_id !== access.identity.session_id || current.binding.root_session_id !== root) throw new QuantCodeIdentity.IdentityError()
    const events = yield* EventV2Bridge.Service
    const previous = yield* read(input.sessionID, root)
    if (!previous.policy) yield* events.publish(QuantCodeBudgetEvent.Policy, {
      sessionID: SessionID.make(root), token_limit: previous.state.token_limit, timestamp: Date.now(),
    })
    const remaining = previous.state.remaining
    if (remaining !== null && estimatedInput >= remaining) {
      const reason = previous.state.status === "stopped_budget" ? "token_limit" : previous.state.reserved ? "capacity_reserved" : "input_too_large"
      yield* changed(previous.state, reason)
      throw new Exhausted(reason)
    }
    const outputLimit = Math.min(requestedOutput, remaining === null ? requestedOutput : remaining - estimatedInput)
    const requestID = randomUUID()
    yield* events.publish(QuantCodeBudgetEvent.Reserved, {
      sessionID: SessionID.make(root), source_session_id: SessionID.make(input.sessionID), request_id: requestID,
      provider: input.model.providerID, model: input.model.id, purpose: input.purpose,
      input_estimate: estimatedInput, output_limit: outputLimit, tokens: estimatedInput + outputLimit, timestamp: Date.now(),
      process: { pid: process.pid, hostname: os.hostname() },
    })
    yield* changed((yield* read(input.sessionID, root)).state)
    return { root, sessionID: input.sessionID, requestID, loginID: access.identity.session_id, outputLimit }
  }))
})

/** Native Usage totals are inclusive; adding cache or reasoning again would
 * double charge. Missing/invalid receipts never release a reservation. */
export function usage(value: Usage | undefined, model: Provider.Model, metadata?: ProviderMetadata) {
  if (!value || !Number.isSafeInteger(value.inputTokens) || !Number.isSafeInteger(value.outputTokens) ||
      value.inputTokens! < 0 || value.outputTokens! < 0) return
  const total = value.totalTokens ?? value.inputTokens! + value.outputTokens!
  if (!Number.isSafeInteger(total) || total < 0) return
  const priced = model.cost.input > 0 || model.cost.output > 0 || typeof metadata?.copilot?.totalNanoAiu === "number"
  return { input: value.inputTokens!, output: value.outputTokens!, total: Math.max(total, value.inputTokens! + value.outputTokens!),
    // A custom URL model normally has no published tariff. Unknown cost must
    // remain explicit rather than showing a misleading zero-cost request.
    cost: priced ? SessionUsage.getUsage({ model, usage: value, metadata }).cost : null }
}

/** Called only by the trusted stream closure, including after logout. Persist
 * spend against the original owner even if the response cannot be shown. */
export const settle = (reservation: Reservation, consumed: NonNullable<ReturnType<typeof usage>>) => locked(reservation.root, Effect.gen(function* () {
  const previous = yield* read(reservation.sessionID, reservation.root)
  const request = previous.requests.get(reservation.requestID)
  if (!request || request.settled) throw new Error("模型请求用量不能重复提交。")
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeBudgetEvent.Settled, {
    sessionID: SessionID.make(reservation.root), source_session_id: SessionID.make(reservation.sessionID), request_id: reservation.requestID,
    input_tokens: consumed.input, output_tokens: consumed.output, tokens: consumed.total, timestamp: Date.now(),
    cost: consumed.cost,
  })
  const state = (yield* read(reservation.sessionID, reservation.root)).state
  yield* changed(state, state.status === "stopped_budget" ? "token_limit" : undefined)
  return state
}))

/** This marks the local stream lifetime ended, not a zero-cost response or a
 * guarantee that a remote provider stopped billing. Unknown spend stays held. */
export const end = Effect.fn("QuantCodeBudget.end")(function* (reservation: Reservation) {
  const previous = (yield* read(reservation.sessionID, reservation.root)).requests.get(reservation.requestID)
  if (!previous || previous.settled || previous.ended) return
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeBudgetEvent.Ended, {
    sessionID: SessionID.make(reservation.root), source_session_id: SessionID.make(reservation.sessionID),
    request_id: reservation.requestID, timestamp: Date.now(),
  })
})

function processState(owner: { hostname: string; pid: number }) {
  if (owner.hostname !== os.hostname()) return "other_host" as const
  try { process.kill(owner.pid, 0) } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return "process_missing" as const
  }
  return "active" as const
}

const lockState = Effect.fn("QuantCodeBudget.lockState")(function* (root: string) {
  const owner = yield* Effect.promise(() => Flock.inspect(`quantcode-budget:${root}`, { dir: lockDirectory() }))
  if (!owner) return { status: "idle" as const }
  const state = processState(owner)
  return { status: state === "process_missing" ? "recovery_required" as const : state,
    lock_digest: QuantCodeToolCatalog.digest(owner) }
})

/** UI-only view; the model gets no mutation or receipt-review capability. */
export const reviewState = Effect.fn("QuantCodeBudget.reviewState")(function* (sessionID: string) {
  const scope = { kind: "read", resource: "budget" } as const
  const access = yield* QuantCodeAccess.requireReview(sessionID, scope)
  const value = yield* read(sessionID, access.binding.root_session_id)
  const state: QuantCodeBudgetEvent.ReviewState = {
    budget: value.state, lock: yield* lockState(access.binding.root_session_id),
    requests: [...value.requests.values()].filter(item => !item.settled).map(item => ({
      request_id: item.reservation.request_id, source_session_id: item.reservation.source_session_id,
      provider: item.reservation.provider, model: item.reservation.model, purpose: item.reservation.purpose,
      reserved_tokens: item.reservation.tokens, timestamp: item.reservation.timestamp,
      reservation_digest: QuantCodeToolCatalog.digest(item.reservation),
      status: item.ended ? "ended" : item.reservation.process ? processState(item.reservation.process) : "unknown",
    })),
  }
  const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
  if (!current || current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
  return state
})

function evidence(input: { evidence_ref: string; note: string }) {
  if (!input.evidence_ref.trim() || input.evidence_ref.length > 2000 || !input.note.trim() || input.note.length > 4000) {
    throw new ReviewError("请提供本次请求的外部证据位置与核对说明。")
  }
}

/** Exact human receipt review, not a budget grant or an automatic retry. */
export const reviewUsage = Effect.fn("QuantCodeBudget.reviewUsage")(function* (sessionID: string, input: QuantCodeBudgetEvent.Review) {
  const access = yield* QuantCodeAccess.requireReview(sessionID, { kind: "read", resource: "budget" })
  evidence(input)
  if (input.request_stopped !== true) throw new ReviewError("请先核实原模型请求已经停止，不能核对仍在执行的请求。")
  yield* locked(access.binding.root_session_id, Effect.gen(function* () {
    const value = yield* read(sessionID, access.binding.root_session_id)
    const previous = value.requests.get(input.request_id)
    if (!previous || previous.settled || QuantCodeToolCatalog.digest(previous.reservation) !== input.expected_digest) {
      throw new ReviewError("模型请求或用量已变化，请刷新后重新核对。")
    }
    if (!previous.ended && (!previous.reservation.process || processState(previous.reservation.process) !== "process_missing")) {
      throw new ReviewError("原模型请求的本机执行尚未确认结束，不能解除预留用量。")
    }
    const receipt = input.decision === "confirmed_not_executed"
      ? { input_tokens: 0, output_tokens: 0, tokens: 0, cost: 0 }
      : input.receipt
    if (!receipt || input.decision === "confirmed_not_executed" && input.receipt !== undefined ||
        ![receipt.input_tokens, receipt.output_tokens, receipt.tokens].every(value => Number.isSafeInteger(value) && value >= 0) ||
        receipt.tokens < receipt.input_tokens + receipt.output_tokens ||
        receipt.cost !== null && (!Number.isFinite(receipt.cost) || receipt.cost < 0)) {
      throw new ReviewError("请填写供应商回执中的完整实际用量；未知费用请明确填写为空。确认未执行不能附带用量。")
    }
    const current = yield* QuantCodeAccess.requireReview(sessionID, {
      kind: "usage", source_session_id: previous.reservation.source_session_id,
      request_id: input.request_id, expected_digest: input.expected_digest, decision: input.decision,
      request_stopped: true, evidence_ref: input.evidence_ref, note: input.note,
      input_digest: QuantCodeToolCatalog.digest(input),
    })
    if (current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
    const events = yield* EventV2Bridge.Service
    yield* events.publish(QuantCodeBudgetEvent.Reviewed, {
      sessionID: SessionID.make(access.binding.root_session_id), source_session_id: previous.reservation.source_session_id,
      request_id: input.request_id, reservation_digest: input.expected_digest, ...receipt,
      request_stopped: true,
      decision: input.decision, reviewer: access.identity.actor_id,
      evidence_ref: input.evidence_ref.trim(), note: input.note.trim(), timestamp: Date.now(),
    })
    const state = (yield* read(sessionID, access.binding.root_session_id)).state
    yield* changed(state, state.status === "stopped_budget" ? "token_limit" : undefined)
  }))
  return yield* reviewState(sessionID)
})

/** Retire only an exact dead local accounting lock. Reservations and actual
 * spend are unchanged; request receipts require their own explicit review. */
export const recoverLock = Effect.fn("QuantCodeBudget.recoverLock")(function* (sessionID: string, input: QuantCodeBudgetEvent.LockRecovery) {
  evidence(input)
  if (input.processes_stopped !== true) throw new ReviewError("请先核对原执行和相关请求均已停止。")
  const scope = { ...input, processes_stopped: true, kind: "budget_lock", input_digest: QuantCodeToolCatalog.digest(input) } as const
  const access = yield* QuantCodeAccess.requireReview(sessionID, scope)
  const key = `quantcode-budget:${access.binding.root_session_id}`
  const dir = lockDirectory()
  const owner = yield* Effect.promise(() => Flock.inspect(key, { dir }))
  if (!owner || QuantCodeToolCatalog.digest(owner) !== input.expected_digest) throw new ReviewError("预算锁已变化，请刷新后重新核对。")
  const events = yield* EventV2Bridge.Service
  const bridge = yield* EffectBridge.make()
  yield* Effect.promise(() => Flock.recover(key, owner, () => bridge.promise(Effect.gen(function* () {
    const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
    if (!current || current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
    yield* events.publish(QuantCodeBudgetEvent.LockRecoveryRecorded, {
      sessionID: SessionID.make(access.binding.root_session_id), lock_digest: input.expected_digest,
      processes_stopped: true,
      reviewer: access.identity.actor_id, evidence_ref: input.evidence_ref.trim(), note: input.note.trim(), timestamp: Date.now(),
    })
  })), { dir })).pipe(Effect.catchDefect(() => Effect.die(new ReviewError("未解除预算锁：原进程仍在运行、来自另一台主机或锁状态已经变化。"))))
  return yield* reviewState(sessionID)
})

export * as QuantCodeBudget from "./budget"

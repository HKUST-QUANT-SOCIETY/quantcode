import { Effect, Schema, Option } from "effect"
import { asc, eq, inArray, and } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { EventTable } from "@opencode-ai/core/event/sql"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { EventV2Bridge } from "@/event-v2-bridge"
import { SessionID } from "@/session/schema"
import { QuantCodeAccess } from "./access"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeToolCatalog } from "./tool-catalog"
import { QuantCodeTaskLock } from "./task-lock"
import { CallToolResultSchema } from "@modelcontextprotocol/sdk/types.js"

/** Same begin-before-effect / uncertain-until-completed rule as the existing
 * runner/tool_receipts.py, using the native event log instead of another DB. */
export class OutcomeUnknown extends Error {
  constructor() { super("该任务存在未确认的写入结果。请先核对原操作，不能自动重新执行或发起其他写入。") }
}
export class ReviewError extends Error {}
export type Operation = {
  sessionID: string; messageID: string; callID?: string; tool: string; args: unknown;
  files: string[]; planHashes: string[]; catalog?: string;
}
export const history = Effect.fn("QuantCodeWriteReceipt.history")(function* (root: string) {
  const { db } = yield* Database.Service
  const rows = yield* db.select({ type: EventTable.type, data: EventTable.data }).from(EventTable)
    .where(and(eq(EventTable.aggregate_id, root), inArray(EventTable.type, ["quantcode.write.started.1", "quantcode.write.completed.1", "quantcode.write.reconciled.1"])))
    .orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
  const records = new Map<string, { start: typeof QuantCodeGovernance.WriteStarted.data.Type;
    result?: { result: unknown }; closed?: boolean; damaged: boolean; digest: string }>()
  for (const row of rows) {
    if (row.type === "quantcode.write.started.1") {
      const start = Schema.decodeUnknownSync(QuantCodeGovernance.WriteStarted.data)(row.data)
      const key = JSON.stringify([start.source_session_id, start.message_id, start.call_id])
      if (records.has(key)) throw new OutcomeUnknown()
      records.set(key, { start, damaged: false, digest: QuantCodeToolCatalog.digest(row.data) })
    } else if (row.type === "quantcode.write.completed.1") {
      const result = Option.getOrUndefined(Schema.decodeUnknownOption(QuantCodeGovernance.WriteCompleted.data)(row.data))
      const item = records.get(JSON.stringify([row.data.source_session_id, row.data.message_id, row.data.call_id]))
      if (!item || item.closed || item.result || item.damaged) throw new OutcomeUnknown()
      item.digest = QuantCodeToolCatalog.digest([item.digest, row.data])
      if (!result || item.start.operation_digest !== result.operation_digest ||
          QuantCodeToolCatalog.digest(result.result) !== result.result_digest) item.damaged = true
      else item.result = result
    } else {
      const review = Schema.decodeUnknownSync(QuantCodeGovernance.WriteReconciled.data)(row.data)
      const item = records.get(JSON.stringify([review.source_session_id, review.message_id, review.call_id]))
      if (!item || item.result || item.closed || item.start.operation_digest !== review.operation_digest ||
          item.digest !== review.prior_receipt_digest || (item.damaged && review.decision !== "confirmed_completed")) throw new OutcomeUnknown()
      if (review.decision === "confirmed_completed") {
        if (!Object.hasOwn(review, "result") || QuantCodeToolCatalog.digest(review.result) !== review.result_digest) throw new OutcomeUnknown()
        item.result = { result: review.result }
      }
      item.closed = true
      item.digest = QuantCodeToolCatalog.digest([item.digest, row.data])
    }
  }
  return records
})

/** Caller holds the existing root task lock through begin, operation and commit.
 * begin is invoked at the actual write boundary, after native permission waits. */
export function run<A, E, R>(input: Operation, execute: (begin: Effect.Effect<void>) => Effect.Effect<A, E, R>) {
  return Effect.gen(function* () {
    if (!input.callID || !input.messageID) throw new Error("写入必须绑定原生工具调用标识。")
    const access = yield* QuantCodeAccess.requireSession(input.sessionID)
    if (!access) throw new QuantCodeIdentity.IdentityError()
    const root = SessionID.make(access.binding.root_session_id)
    const records = yield* history(root)
    const operationDigest = QuantCodeToolCatalog.digest({ ...input, owner: QuantCodeIdentity.ownerOf(access.identity) })
    const key = JSON.stringify([input.sessionID, input.messageID, input.callID])
    const previous = records.get(key)
    if (previous) {
      if (previous.closed && !previous.result) throw new Error("该原调用已确认未执行并关闭。若仍需操作，请在当前方案下发起新的工具调用。")
      if (previous.start.operation_digest !== operationDigest || !previous.result) throw new OutcomeUnknown()
      // The immutable event stores the JSON result produced by this exact
      // trusted invocation, with its content digest checked above.
      return previous.result.result as A
    }
    if ([...records.values()].some(item => !item.result && !item.closed)) throw new OutcomeUnknown()
    const events = yield* EventV2Bridge.Service
    const database = yield* Database.Service
    const common = { sessionID: root, source_session_id: SessionID.make(input.sessionID),
      message_id: input.messageID, call_id: input.callID, operation_digest: operationDigest }
    let started = false
    const begin = Effect.gen(function* () {
      if (started) return
      const current = yield* QuantCodeAccess.requireSession(input.sessionID)
      if (!current || current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
      yield* events.publish(QuantCodeGovernance.WriteStarted, { ...common,
        tool: input.tool, files: input.files, plan_hashes: input.planHashes, timestamp: Date.now() })
      started = true
    }).pipe(Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events))
    const output = yield* execute(begin)
    if (!started) return output
    const encoded = JSON.stringify(output)
    if (encoded === undefined || Buffer.byteLength(encoded) > 2_000_000) throw new OutcomeUnknown()
    const result: unknown = JSON.parse(encoded)
    yield* events.publish(QuantCodeGovernance.WriteCompleted, { ...common, result,
      result_digest: QuantCodeToolCatalog.digest(result), timestamp: Date.now() })
    const current = yield* QuantCodeAccess.requireSession(input.sessionID)
    if (!current || current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
    return output
  })
}

export const status = Effect.fn("QuantCodeWriteReceipt.status")(function* (sessionID: string) {
  const scope = { kind: "read", resource: "write_receipts" } as const
  const access = yield* QuantCodeAccess.requireReview(sessionID, scope)
  const records = yield* history(access.binding.root_session_id)
  const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
  if (!current || current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
  return { session_id: SessionID.make(sessionID), root_session_id: SessionID.make(access.binding.root_session_id),
    unresolved: [...records.values()].filter(item => !item.result && !item.closed).map(item => ({ ...item.start,
      receipt_digest: item.digest, completion_damaged: item.damaged })) }
})

/** Existing receipt_reconciliation.py decision vocabulary, recorded in the
 * native event log. This UI-only review never executes a tool itself. */
export const review = (sessionID: string, input: QuantCodeGovernance.ReceiptReview) => {
  const scope: QuantCodeAccess.ReviewScope = { kind: "write_receipt", source_session_id: input.source_session_id,
    message_id: input.message_id, call_id: input.call_id, expected_digest: input.expected_digest,
    expected_receipt_digest: input.expected_receipt_digest, decision: input.decision,
    evidence_ref: input.evidence_ref, note: input.note, input_digest: QuantCodeToolCatalog.digest(input) }
  return QuantCodeTaskLock.reviewGuard(sessionID, scope, Effect.gen(function* () {
    const access = yield* QuantCodeAccess.requireReview(sessionID, scope)
    if (!input.note.trim() || input.note.length > 4000 || !input.evidence_ref.trim() || input.evidence_ref.length > 2000) throw new ReviewError("请提供外部证据位置与核对说明。")
    const records = yield* history(access.binding.root_session_id)
    const prior = records.get(JSON.stringify([input.source_session_id, input.message_id, input.call_id]))
    if (!prior || prior.closed || prior.result || prior.start.operation_digest !== input.expected_digest || prior.digest !== input.expected_receipt_digest) throw new ReviewError("回执已变化，请重新读取后核对。")
    if (prior.damaged && input.decision !== "confirmed_completed") throw new ReviewError("完成记录损坏只能恢复原结果，不能转为未执行后重试。")
    if (input.decision === "confirmed_completed") {
      const result = input.result
      if (["write", "edit", "apply_patch", "shell", "snapshot_restore", "snapshot_revert"].includes(prior.start.tool) && (!result || typeof result !== "object" || !("output" in result) || typeof result.output !== "string" ||
          !("title" in result) || typeof result.title !== "string" || !("metadata" in result) ||
          !result.metadata || typeof result.metadata !== "object" || Array.isArray(result.metadata))) {
        throw new ReviewError("确认完成必须提供原工具的完整结果对象，包含 title、output 和 metadata。")
      }
      if (!["write", "edit", "apply_patch", "shell", "snapshot_restore", "snapshot_revert"].includes(prior.start.tool)) {
        const parsed = CallToolResultSchema.safeParse(result)
        if (!parsed.success || parsed.data.isError) throw new ReviewError("请提供原组件的完整成功结果，包含 MCP content。")
      }
      if (Buffer.byteLength(JSON.stringify(result)) > 2_000_000) throw new ReviewError("核对结果超出可保存上限。")
    } else if (input.decision !== "confirmed_not_executed" || Object.hasOwn(input, "result")) {
      throw new ReviewError("确认未执行不能附带结果。")
    }
    const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
    if (current.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
    const events = yield* EventV2Bridge.Service
    yield* events.publish(QuantCodeGovernance.WriteReconciled, { sessionID: SessionID.make(access.binding.root_session_id),
      source_session_id: input.source_session_id, message_id: input.message_id, call_id: input.call_id,
      operation_digest: input.expected_digest, decision: input.decision, reviewer: access.identity.actor_id,
      evidence_ref: input.evidence_ref.trim(), note: input.note.trim(), timestamp: Date.now(),
      prior_receipt_digest: prior.digest,
      ...(input.decision === "confirmed_completed" ? { result: input.result, result_digest: QuantCodeToolCatalog.digest(input.result) } : {}),
    })
    return yield* status(sessionID)
  }))
}
export * as QuantCodeWriteReceipt from "./write-receipt"

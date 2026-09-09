import { Effect, Schema } from "effect"
import { randomUUID } from "node:crypto"
import { eq, asc } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { EventTable } from "@opencode-ai/core/event/sql"
import { EventV2Bridge } from "@/event-v2-bridge"
import { SessionID } from "@/session/schema"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { QuantCodeIntent } from "./intent"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeTaskLock } from "./task-lock"
import { QuantCodeToolCatalog, type Admission } from "./tool-catalog"

const object = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
export type Proposal = { coverage: "full" | "partial" | "none"; components: string[]; reason: string }
export type Review = { proposal_hash: string; decision: "approve" | "reject"; note: string }

export class CoverageError extends Error {}

/** Pin both the admitted task and the login before a remote inspection starts. */
export const capture = Effect.fn("QuantCodeReuse.capture")(function* (sessionID: string) {
  const intent = yield* QuantCodeIntent.read(sessionID)
  return { intent_hash: QuantCodeToolCatalog.digest(intent.task),
    authorization_hash: QuantCodeToolCatalog.digest({ login: intent.access.identity.session_id, owner: QuantCodeIdentity.ownerOf(intent.access.identity) }) }
})

export const state = Effect.fn("QuantCodeReuse.state")(function* (sessionID: string) {
  const intent = yield* QuantCodeIntent.read(sessionID)
  const intentHash = QuantCodeToolCatalog.digest(intent.task)
  const authorizationHash = QuantCodeToolCatalog.digest({ login: intent.access.identity.session_id, owner: QuantCodeIdentity.ownerOf(intent.access.identity) })
  const { db } = yield* Database.Service
  const rows = yield* db.select({ type: EventTable.type, data: EventTable.data }).from(EventTable)
    .where(eq(EventTable.aggregate_id, sessionID)).orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
  let capabilities: typeof QuantCodeGovernance.Inspection.data.Type | undefined
  let memory: typeof QuantCodeGovernance.Inspection.data.Type | undefined
  let proposal: typeof QuantCodeGovernance.Coverage.data.Type | undefined
  let review: typeof QuantCodeGovernance.CoverageReviewed.data.Type | undefined
  for (const row of rows) {
    if (row.data.intent_hash !== intentHash) continue
    if (row.type === "quantcode.inspection.1") {
      const item = Schema.decodeUnknownSync(QuantCodeGovernance.Inspection.data)(row.data)
      if (item.authorization_hash !== authorizationHash) continue
      if (item.purpose === "capability_catalog") capabilities = item
      else memory = item
    }
    if (row.type === "quantcode.coverage.proposed.1") {
      proposal = Schema.decodeUnknownSync(QuantCodeGovernance.Coverage.data)(row.data)
      review = undefined
    }
    if (row.type === "quantcode.coverage.reviewed.1") {
      const decision = Schema.decodeUnknownSync(QuantCodeGovernance.CoverageReviewed.data)(row.data)
      // The first durable decision wins. A stale or competing browser request
      // cannot overwrite it or hide a decision for the current proposal.
      if (!review && decision.proposal_hash === proposal?.proposal_hash) review = decision
    }
  }
  // Withdrawal of a published discovery tool invalidates its old receipt.
  const catalog = yield* Effect.promise(() => QuantCodeToolCatalog.load())
  const active = (receipt: typeof capabilities) => {
    const entry = catalog?.tools.find(item => item.server === receipt?.server && item.tool === receipt?.tool)
    return receipt && entry && entry.effect === "read" && entry.purpose === receipt.purpose &&
      QuantCodeToolCatalog.visible(entry, intent.access.identity) &&
      QuantCodeToolCatalog.digest({ release: catalog!.release, entry }) === receipt.catalog_digest
  }
  if (!active(capabilities)) capabilities = undefined
  if (!active(memory)) memory = undefined
  const inspectionHash = capabilities && memory ? QuantCodeToolCatalog.digest([capabilities, memory]) : undefined
  if (proposal?.inspection_hash !== inspectionHash) proposal = undefined
  if (!proposal || review?.proposal_hash !== proposal.proposal_hash) review = undefined
  const current = yield* capture(sessionID)
  if (current.intent_hash !== intentHash || current.authorization_hash !== authorizationHash) throw new CoverageError("任务或登录身份已变化，请重新查询能力覆盖情况。")
  return { sessionID, intent, intentHash, capabilities, memory, inspectionHash, proposal, review }
})

/** Called only with the direct result from the pinned MCP transport, before
 * plugins or text formatting can rewrite it. Ordinary tool output is ignored. */
export const observe = Effect.fn("QuantCodeReuse.observe")(function* (sessionID: string, callID: string, admitted: Admission, raw: unknown, started: Effect.Success<ReturnType<typeof capture>>) {
  const purpose = admitted.entry.purpose
  if (purpose === "ordinary") return
  const envelope = object(raw)
  if (!envelope || envelope.isError) return
  let result = object(envelope.structuredContent)
  if (!result && Array.isArray(envelope.content)) {
    const parts = envelope.content.filter(item => object(item)?.type === "text")
    if (parts.length === 1 && typeof object(parts[0])?.text === "string") {
      try { result = object(JSON.parse(object(parts[0])!.text as string)) } catch { return }
    }
  }
  if (!result || result.error || result.ok === false || ["UNAVAILABLE", "FORBIDDEN"].includes(String(result.status))) return
  const capabilities: { id: string; integration_status: string }[] = []
  if (purpose === "capability_catalog") {
    if (!Array.isArray(result.capabilities)) return
    const ids = new Set<string>()
    for (const raw of result.capabilities) {
      const item = object(raw)
      if (typeof item?.id !== "string" || !item.id.trim() || ids.has(item.id) || typeof item.integration_status !== "string") return
      ids.add(item.id)
      capabilities.push({ id: item.id, integration_status: item.integration_status })
    }
  } else if (!Array.isArray(result.hits)) return
  const current = yield* capture(sessionID)
  if (current.intent_hash !== started.intent_hash || current.authorization_hash !== started.authorization_hash) {
    throw new CoverageError("检索期间任务或身份已变化，该结果不能作为当前任务的执行依据。")
  }
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeGovernance.Inspection, { sessionID: SessionID.make(sessionID),
    ...started, timestamp: Date.now(), purpose,
    server: admitted.entry.server, tool: admitted.entry.tool, call_id: callID,
    catalog_digest: admitted.digest, result_hash: QuantCodeToolCatalog.digest(result), capabilities })
  return result
})

const proposeLocked = Effect.fn("QuantCodeReuse.propose")(function* (sessionID: string, input: Proposal) {
  const current = yield* state(sessionID)
  if (!current.inspectionHash || !current.capabilities || !current.memory) throw new CoverageError("请先实际查询当前任务的能力目录与组内 Memory。")
  if (!input.reason.trim() || !["full", "partial", "none"].includes(input.coverage)) throw new CoverageError("请说明能力覆盖情况与缺口。")
  const ids = new Set(current.capabilities.capabilities.map(item => item.id))
  if (input.components.some(id => !ids.has(id))) throw new CoverageError("复用组件不在当前授权目录中。")
  if (input.coverage === "none" && input.components.length) throw new CoverageError("无覆盖方案不能同时声明复用组件。")
  if (input.coverage === "full" && (!input.components.length || input.components.some(id => current.capabilities!.capabilities.find(item => item.id === id)?.integration_status !== "CONNECTED"))) {
    throw new CoverageError("完整覆盖只能引用非空的 CONNECTED 组件列表。若只有内置文件工具适用，请调用 organization_reuse(action=propose, coverage=none, components=[], reason=说明)，等待用户决定；不能用 full 加空列表。")
  }
  const components = [...new Set(input.components)].sort()
  const reason = input.reason.trim()
  // state() already pins the current intent, login and inspection receipts.
  // Retrying identical content must preserve both approval and rejection.
  if (current.proposal?.coverage === input.coverage && current.proposal.reason === reason &&
      JSON.stringify(current.proposal.components) === JSON.stringify(components)) return current
  const proposal = { sessionID: SessionID.make(sessionID), intent_hash: current.intentHash,
    inspection_hash: current.inspectionHash, coverage: input.coverage,
    components, reason, timestamp: Date.now() }
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeGovernance.Coverage, { ...proposal, proposal_hash: QuantCodeToolCatalog.digest({ ...proposal, nonce: randomUUID() }) })
  return yield* state(sessionID)
})

/** UI-only, never exported as a model tool. */
const reviewLocked = Effect.fn("QuantCodeReuse.review")(function* (sessionID: string, input: Review) {
  const current = yield* state(sessionID)
  if (!current.proposal || current.proposal.proposal_hash !== input.proposal_hash || !input.note.trim()) throw new CoverageError("能力方案已变化，请重新查看后决定。")
  if (!["approve", "reject"].includes(input.decision)) throw new CoverageError("无效的能力方案决定。")
  if (current.review) {
    if (current.review.decision !== input.decision || current.review.note !== input.note.trim()) throw new CoverageError("该能力方案已有决定，请重新提出方案。")
    return current
  }
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeGovernance.CoverageReviewed, { sessionID: SessionID.make(sessionID), intent_hash: current.intentHash,
    proposal_hash: input.proposal_hash, reviewer: current.intent.access.identity.actor_id,
    decision: input.decision, note: input.note.trim(), timestamp: Date.now() })
  const saved = yield* state(sessionID)
  if (saved.proposal?.proposal_hash !== input.proposal_hash || saved.review?.decision !== input.decision || saved.review.note !== input.note.trim()) {
    throw new CoverageError("能力方案或决定已变化，请刷新后查看已记录的决定。")
  }
  return saved
})

export const propose = (sessionID: string, input: Proposal) => QuantCodeTaskLock.guard(sessionID, proposeLocked(sessionID, input))
export const review = (sessionID: string, input: Review) => QuantCodeTaskLock.guard(sessionID, reviewLocked(sessionID, input))

export const requireCoverage = Effect.fn("QuantCodeReuse.requireCoverage")(function* (sessionID: string, capabilityID?: string) {
  const current = yield* state(sessionID)
  if (!current.proposal || !current.inspectionHash) throw new CoverageError("写入前必须实际查询能力目录和组 Memory，再调用 organization_reuse 的 action=propose 说明覆盖情况；纯文字说明不算提交。没有适用的目录组件时使用 coverage=none、components=[]，等待用户决定。")
  if (current.review?.decision === "reject") throw new CoverageError("用户已拒绝该能力方案，不能执行。")
  // A claimed full match authorizes only the actual published component call,
  // not arbitrary newly-written code that purports to replace that component.
  if (current.proposal.coverage === "full" && capabilityID && current.proposal.components.includes(capabilityID)) return
  if (current.review?.decision !== "approve") throw new CoverageError("现有能力不能直接覆盖此写入；请先取得用户对缺口处理方式的决定。")
})

export function publicState(value: Effect.Success<ReturnType<typeof state>>) {
  return { session_id: SessionID.make(value.sessionID), intent_hash: value.intentHash, catalog_checked: !!value.capabilities,
    memory_checked: !!value.memory, proposal: value.proposal, review: value.review }
}
export * as QuantCodeReuse from "./reuse"

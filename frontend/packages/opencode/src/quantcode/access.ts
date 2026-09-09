import { Effect, Schema } from "effect"
import { eq, inArray } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { SessionTable } from "@opencode-ai/core/session/sql"
import { SessionID } from "@/session/schema"
import { QuantCodeIdentity } from "./identity"

/** Read authorization without depending on Session.Service (permissions and
 * event consumers cannot introduce a dependency cycle through the executor). */
export const requireSession = Effect.fn("QuantCodeAccess.requireSession")(function* (sessionID: string) {
  if (!QuantCodeIdentity.enabled()) return
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const { db } = yield* Database.Service
  const row = yield* db.select({ metadata: SessionTable.metadata, directory: SessionTable.directory })
    .from(SessionTable).where(eq(SessionTable.id, SessionID.make(sessionID))).get().pipe(Effect.orDie)
  if (!row) throw new QuantCodeIdentity.IdentityError("任务不存在或不属于当前身份。")
  const binding = QuantCodeIdentity.requireOwner(row.metadata ?? undefined, identity)
  return { identity, binding, directory: row.directory, read_only: QuantCodeIdentity.readOnly(row.metadata ?? undefined) }
})

export const requireExecution = Effect.fn("QuantCodeAccess.requireExecution")(function* (sessionID: string) {
  const access = yield* requireSession(sessionID)
  if (access?.read_only) throw new QuantCodeIdentity.IdentityError("归档任务只能查看，不能恢复为新的原生执行。")
  return access
})

type ReviewEvidence = { expected_digest: string; input_digest: string; evidence_ref: string; note: string }
export type ReviewScope =
  | { kind: "read"; resource: "write_receipts" | "budget" | "execution_lock" }
  | ReviewEvidence & { kind: "write_receipt"; source_session_id: string; message_id: string; call_id: string;
      expected_receipt_digest: string; decision: "confirmed_completed" | "confirmed_not_executed" }
  | ReviewEvidence & { kind: "usage"; source_session_id: string; request_id: string; request_stopped: true;
      decision: "usage_confirmed" | "confirmed_not_executed" }
  | ReviewEvidence & { kind: "execution_lock" | "budget_lock"; processes_stopped: true }

/** Reconcile-only access to a task on this host. Never use this for execution,
 * messages, filesystem access or owner changes. The gateway validates the full
 * original owner's current roster grant independently of the reviewer's grant. */
export const requireReview = Effect.fn("QuantCodeAccess.requireReview")(function* (sessionID: string, scope: ReviewScope) {
  if (!QuantCodeIdentity.enabled()) throw new QuantCodeIdentity.IdentityError()
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const { db } = yield* Database.Service
  const rows = yield* db.select({ id: SessionTable.id, metadata: SessionTable.metadata })
    .from(SessionTable).where(eq(SessionTable.id, SessionID.make(sessionID))).get().pipe(Effect.orDie)
  const binding = QuantCodeIdentity.sessionBinding(rows?.metadata ?? undefined)
  if (!binding) throw new QuantCodeIdentity.IdentityError("本机没有可核对的原生任务。")
  if (scope.kind !== "read") QuantCodeIdentity.requireEditable(rows?.metadata ?? undefined)
  const related = [...new Set([binding.root_session_id, ...("source_session_id" in scope ? [scope.source_session_id] : [])])]
  for (const id of related) {
    const row = yield* db.select({ metadata: SessionTable.metadata }).from(SessionTable)
      .where(eq(SessionTable.id, SessionID.make(id))).get().pipe(Effect.orDie)
    const other = QuantCodeIdentity.sessionBinding(row?.metadata ?? undefined)
    if (!other || other.root_session_id !== binding.root_session_id ||
        JSON.stringify(other.owner) !== JSON.stringify(binding.owner)) {
      throw new QuantCodeIdentity.IdentityError("核对对象不属于同一原生任务树。")
    }
    if (scope.kind !== "read") QuantCodeIdentity.requireEditable(row?.metadata ?? undefined)
  }
  // Ordinary owner self-inspection retains the existing live identity check;
  // cross-member disclosure and every reconciliation need authority audit.
  if (scope.kind === "read" && QuantCodeIdentity.owns(binding, identity)) {
    return { identity, binding, read_only: QuantCodeIdentity.readOnly(rows?.metadata ?? undefined) }
  }
  const response = yield* Effect.promise(() => QuantCodeIdentity.gatewayRequest("reviews.authorize", {
    expected_session_id: identity.session_id, session_id: sessionID,
    root_session_id: binding.root_session_id, owner: binding.owner, scope,
  }))
  if (!response || typeof response !== "object" || !("authorized" in response) || response.authorized !== true ||
      !("reviewer_session_id" in response) || response.reviewer_session_id !== identity.session_id ||
      !("session_id" in response) || response.session_id !== sessionID ||
      !("root_session_id" in response) || response.root_session_id !== binding.root_session_id) {
    throw new QuantCodeIdentity.IdentityError("组织服务未确认本次核对权限。")
  }
  return { identity, binding, read_only: QuantCodeIdentity.readOnly(rows?.metadata ?? undefined) }
})

/** Filter the complete candidate set, not a limited page that can leak another
 * actor's identifiers or incorrectly hide permitted results. */
export const visibleSessions = Effect.fn("QuantCodeAccess.visibleSessions")(function* (sessionIDs: string[]) {
  if (!QuantCodeIdentity.enabled()) return new Set(sessionIDs)
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity().catch(() => undefined))
  if (!identity || sessionIDs.length === 0) return new Set<string>()
  const { db } = yield* Database.Service
  const visible = new Set<string>()
  const ids = [...new Set(sessionIDs)].filter(Schema.is(SessionID))
  // SQLite has a bind-parameter limit; large histories must not fail open or
  // lose permissions merely because more than one page of IDs is present.
  for (let offset = 0; offset < ids.length; offset += 500) {
    const rows = yield* db.select({ id: SessionTable.id, metadata: SessionTable.metadata })
      .from(SessionTable).where(inArray(SessionTable.id, ids.slice(offset, offset + 500).map(id => SessionID.make(id)))).all().pipe(Effect.orDie)
    for (const row of rows) {
      if (QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity)) visible.add(row.id)
    }
  }
  const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (identity.session_id !== current.session_id || JSON.stringify(QuantCodeIdentity.ownerOf(identity)) !== JSON.stringify(QuantCodeIdentity.ownerOf(current))) {
    throw new QuantCodeIdentity.IdentityError("读取过程中身份已变化，请重试。")
  }
  return visible
})

export * as QuantCodeAccess from "./access"

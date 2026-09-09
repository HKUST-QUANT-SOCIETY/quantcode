import { createHash } from "node:crypto"
import { Effect } from "effect"
import { asc, eq, inArray, sql } from "drizzle-orm"
import { z } from "zod"
import { Database } from "@opencode-ai/core/database/database"
import { SessionTable, MessageTable, PartTable, TodoTable, SessionMessageTable, SessionInputTable } from "@opencode-ai/core/session/sql"
import { EventTable, EventSequenceTable } from "@opencode-ai/core/event/sql"
import { EventV2 } from "@opencode-ai/core/event"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import { SessionID } from "@opencode-ai/schema/session-id"
import { Session } from "../session/session"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"

const Hash = z.string().regex(/^[a-f0-9]{64}$/)
const Owner = z.object({
  actor_id: z.string().min(1), group: z.enum(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"]),
  role: z.enum(["analyst", "approver", "admin"]), workspace_id: z.string().min(1), workspace_path: z.string().min(1),
  github_subject: z.string().nullable(), resource_scopes: z.array(z.string()),
}).strict()
export const Declaration = z.object({
  version: z.literal(1), mode: z.literal("read_only"), root_session_id: z.string().min(1),
  source_digest: Hash, owner: Owner,
  sessions: z.array(z.object({ session_id: z.string().min(1), source_digest: Hash }).strict()).min(1).max(500),
  evidence_file: z.string().min(1), evidence_digest: Hash,
  attestation: z.literal("I verified this exact historical session tree belongs to the declared roster owner."),
  note: z.string().min(20).max(10000),
}).strict()
export type Declaration = z.infer<typeof Declaration>

/** Hash decoded scalar columns plus exact stored JSON text (included below).
 * Object keys are normalized; no message/event content is edited or replayed. */
export const digest = (value: unknown): string => createHash("sha256").update(JSON.stringify(value,
  (_, item) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item)).digest("hex")

const snapshot = Effect.fn("QuantCodeUnboundSession.snapshot")(function* (rootID: string) {
  const { db } = yield* Database.Service
  const root = yield* db.select().from(SessionTable).where(eq(SessionTable.id, SessionID.make(rootID))).get().pipe(Effect.orDie)
  if (!root || root.parent_id) throw new Error("Select an existing root session; partial child adoption is not allowed")
  const sessions = [root]
  for (let offset = 0; offset < sessions.length; offset++) {
    if (sessions.length > 500) throw new Error("Historical tree exceeds the reviewed import limit; use a separately reviewed migration")
    const current = sessions[offset]
    if (current.metadata !== null && (typeof current.metadata !== "object" || Array.isArray(current.metadata))) {
      throw new Error("Historical session metadata is malformed")
    }
    if (current.metadata?.quantcode !== undefined || current.metadata?.quantcode_legacy_import !== undefined) {
      throw new Error("The selected tree contains an existing or malformed ownership binding")
    }
    const children = yield* db.select().from(SessionTable).where(eq(SessionTable.parent_id, current.id))
      .orderBy(asc(SessionTable.id)).all().pipe(Effect.orDie)
    for (const child of children) {
      if (sessions.some(item => item.id === child.id)) throw new Error("Historical session ancestry contains a cycle")
      sessions.push(child)
    }
  }
  const records = []
  for (const session of sessions) {
    const messages = yield* db.select({ row: MessageTable, data_text: sql<string>`${MessageTable.data}` }).from(MessageTable)
      .where(eq(MessageTable.session_id, session.id)).orderBy(asc(MessageTable.id)).all().pipe(Effect.orDie)
    const parts = yield* db.select({ row: PartTable, data_text: sql<string>`${PartTable.data}` }).from(PartTable)
      .where(eq(PartTable.session_id, session.id)).orderBy(asc(PartTable.id)).all().pipe(Effect.orDie)
    const events = yield* db.select({ row: EventTable, data_text: sql<string>`${EventTable.data}` }).from(EventTable)
      .where(eq(EventTable.aggregate_id, session.id)).orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
    const sequence = yield* db.select().from(EventSequenceTable).where(eq(EventSequenceTable.aggregate_id, session.id)).get().pipe(Effect.orDie)
    const todos = yield* db.select().from(TodoTable).where(eq(TodoTable.session_id, session.id)).orderBy(asc(TodoTable.position)).all().pipe(Effect.orDie)
    const metadata = yield* db.select({ metadata_text: sql<string | null>`${SessionTable.metadata}` }).from(SessionTable)
      .where(eq(SessionTable.id, session.id)).get().pipe(Effect.orDie)
    const v2messages = yield* db.select({ id: SessionMessageTable.id }).from(SessionMessageTable)
      .where(eq(SessionMessageTable.session_id, session.id)).limit(1).all().pipe(Effect.orDie)
    const v2inputs = yield* db.select({ id: SessionInputTable.id }).from(SessionInputTable)
      .where(eq(SessionInputTable.session_id, session.id)).limit(1).all().pipe(Effect.orDie)
    if (v2messages.length || v2inputs.length) throw new Error("Core V2 history requires a separate protocol-compatible import; refusing to adopt it as desktop V1")
    const ids = new Set(messages.map(item => item.row.id))
    if (parts.some(part => !ids.has(part.row.message_id))) throw new Error("Historical tool/message relationship is inconsistent")
    if ((events.at(-1)?.row.seq ?? -1) !== (sequence?.seq ?? -1)) throw new Error("Historical event sequence and records disagree")
    records.push({ session, metadata_text: metadata?.metadata_text, messages, parts, events, sequence: sequence ?? null, todos })
  }
  return { version: 1 as const, format: "legacy-unbound-native" as const, root_session_id: rootID, records }
})

export const inspect = (rootID: string) => Effect.gen(function* () {
  const { db } = yield* Database.Service
  return yield* db.transaction(() => snapshot(rootID)).pipe(Effect.orDie)
})

/** Maintainer inventory, not an ordinary-user history endpoint. */
export const list = Effect.gen(function* () {
  const { db } = yield* Database.Service
  const rows = yield* db.select({ id: SessionTable.id, parent_id: SessionTable.parent_id, title: SessionTable.title,
    directory: SessionTable.directory, time_created: SessionTable.time_created, metadata: SessionTable.metadata })
    .from(SessionTable).orderBy(asc(SessionTable.id)).all().pipe(Effect.orDie)
  return rows.filter(row => row.metadata?.quantcode === undefined && row.metadata?.quantcode_legacy_import === undefined)
    .map(({ metadata, ...row }) => ({ ...row, state: "legacy-unbound" as const }))
})

export const summary = (source: Effect.Success<ReturnType<typeof inspect>>) => ({
  format: source.format, root_session_id: source.root_session_id, source_digest: digest(source),
  sessions: source.records.map(item => ({ session_id: item.session.id, parent_session_id: item.session.parent_id,
    title: item.session.title, directory: item.session.directory, created_at: item.session.time_created,
    source_digest: digest(item), messages: item.messages.length, parts: item.parts.length, events: item.events.length,
    latest_event_sequence: item.sequence?.seq ?? -1 })),
})

/** Append host ownership as a read-only historical binding in the original
 * event stream. No session/message creation, import loop or executor wake. */
export const bind = Effect.fn("QuantCodeUnboundSession.bind")(function* (
  declaration: Declaration, declarationDigest: string, identity: QuantCodeIdentity.Identity,
  revalidate: () => Promise<void>,
) {
  if (!QuantCodeIdentity.enabled()) throw new Error("Native ownership import requires the explicit host migration switches")
  if (digest(declaration.owner) !== digest(QuantCodeIdentity.ownerOf(identity))) {
    throw new Error("The explicit declared owner does not match the current authoritative roster login")
  }
  const { db } = yield* Database.Service
  const events = yield* EventV2.Service
  return yield* db.transaction(() => Effect.gen(function* () {
    const source = yield* snapshot(declaration.root_session_id)
    if (digest(source) !== declaration.source_digest) throw new Error("Historical source changed; repeat preview and declaration")
    const expected = new Map(declaration.sessions.map(item => [item.session_id, item.source_digest]))
    if (expected.size !== declaration.sessions.length || expected.size !== source.records.length ||
      source.records.some(item => expected.get(item.session.id) !== digest(item))) {
      throw new Error("Declaration must identify every exact session in the original tree")
    }
    const grants = []
    for (const item of source.records) {
      grants.push(yield* Effect.promise(() => QuantCodeWorkspace.authorize(item.session.directory, "read", identity)))
    }
    yield* Effect.promise(revalidate)
    for (const grant of grants) yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
    const imported = Date.now()
    for (const item of source.records) {
      const binding: QuantCodeIdentity.SessionBinding = {
        version: 1, engine: "quantcode", owner: QuantCodeIdentity.ownerOf(identity),
        root_session_id: declaration.root_session_id, parent_session_id: item.session.parent_id ?? undefined,
      }
      const metadata = { ...item.session.metadata, quantcode: binding, quantcode_legacy_import: {
        version: 1, read_only: true, source_digest: digest(item), tree_digest: declaration.source_digest,
        declaration_digest: declarationDigest, evidence_digest: declaration.evidence_digest,
        imported_at: imported, owner_login_session_id: identity.session_id,
      } }
      const original = Session.fromRow(item.session)
      const updated = Math.max(imported, item.session.time_updated)
      const info = { ...original, metadata, time: { ...original.time, updated } }
      yield* events.publish(SessionV1.Event.Updated, { sessionID: item.session.id, info }, {
        commit: () => db.update(SessionTable).set({ metadata, time_updated: updated })
          .where(eq(SessionTable.id, item.session.id)).run().pipe(Effect.orDie, Effect.asVoid),
      })
    }
    yield* Effect.promise(revalidate)
    // Guard against partial/mixed bindings if an unexpected projector changes a row.
    const rows = yield* db.select().from(SessionTable).where(inArray(SessionTable.id, source.records.map(item => item.session.id))).all().pipe(Effect.orDie)
    if (rows.length !== source.records.length || rows.some(row =>
      !QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity))) {
      throw new Error("Historical ownership projection did not commit consistently")
    }
    return { root_session_id: source.root_session_id, imported_sessions: source.records.length,
      source_digest: declaration.source_digest, declaration_digest: declarationDigest, read_only: true as const }
  }), { behavior: "immediate" }).pipe(Effect.orDie)
})

export * as QuantCodeUnboundSession from "./unbound-session"

import { Effect } from "effect"
import { Database } from "@opencode-ai/core/database/database"
import { EventTable } from "@opencode-ai/core/event/sql"
import { asc, eq } from "drizzle-orm"
import { QuantCodeAccess } from "./access"
import { QuantCodeIdentity } from "./identity"

/** Use first admitted user text from immutable event history. Public message
 * edits, deletions and context compaction do not erase the original task scope.
 * This derives a policy view from existing events; it does not copy messages to
 * another authoritative task store. */
export const read = Effect.fn("QuantCodeIntent.read")(function* (sessionID: string) {
  const access = yield* QuantCodeAccess.requireSession(sessionID)
  if (!access) throw new QuantCodeIdentity.IdentityError()
  const { db } = yield* Database.Service
  const events = yield* db.select({ type: EventTable.type, data: EventTable.data }).from(EventTable)
    .where(eq(EventTable.aggregate_id, sessionID)).orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
  const users = new Set<string>()
  const seenMessages = new Set<string>()
  const parts = new Map<string, string>()
  const object = (value: unknown): Record<string, unknown> | undefined =>
    value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
  for (const event of events) {
    if (event.type === "message.updated.1") {
      const info = object(event.data.info)
      if (info?.sessionID !== sessionID || typeof info.id !== "string" || seenMessages.has(info.id)) continue
      seenMessages.add(info.id)
      if (info.role === "user") users.add(info.id)
    }
    if (event.type === "message.part.updated.1") {
      const part = object(event.data.part)
      if (part?.sessionID !== sessionID || typeof part.id !== "string" || typeof part.messageID !== "string" ||
          !users.has(part.messageID) || parts.has(part.id)) continue
      // Remember the first appearance even when it is synthetic, so a later
      // client edit cannot reclassify generated text as a user decision.
      parts.set(part.id, part.type === "text" && !part.synthetic && !part.ignored && typeof part.text === "string" ? part.text : "")
    }
  }
  const task = [...parts.values()].filter(Boolean).join("\n\n")
  if (!task.trim()) throw new Error("任务尚无已记录的用户需求，不能创建方案。")
  return { access, task }
})


export * as QuantCodeIntent from "./intent"

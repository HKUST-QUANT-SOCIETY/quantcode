import { QuantCodeTerminalAccess } from "./terminal-access"
import { Effect } from "effect"
import { eq } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { SessionTable } from "@opencode-ai/core/session/sql"
import { SessionID } from "@/session/schema"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"
import { ProjectTable } from "@opencode-ai/core/project/sql"
import { ProjectSchema } from "@opencode-ai/core/project/schema"
import path from "node:path"

const publicEvents = new Set(["server.connected", "server.heartbeat"])
const record = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined

/** Only inspect protocol fields, never recursively trust a sessionID embedded
 * in tool output, user text, metadata, or a nested resource body. */
export function eventSession(type: string, properties: unknown): string | undefined {
  const data = record(properties)
  if (!data) return
  if (typeof data.sessionID === "string") return data.sessionID
  if (type === "message.updated") {
    const info = record(data.info)
    if (typeof info?.sessionID === "string") return info.sessionID
  }
  if (type === "message.part.updated") {
    const part = record(data.part)
    if (typeof part?.sessionID === "string") return part.sessionID
  }
  if (["session.created", "session.updated", "session.deleted"].includes(type)) {
    const info = record(data.info)
    if (typeof info?.id === "string") return info.id
  }
}

/** One subscriber is pinned to the login session that opened it. A login
 * change closes the stream; queued events cannot switch to the next user. */
export const subscriber = Effect.fn("QuantCodeEventAccess.subscriber")(function* () {
  if (!QuantCodeIdentity.enabled()) return (_type: string, _properties: unknown, _directory?: string) => Effect.succeed(true)
  const { db } = yield* Database.Service
  const admitted = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity().catch(() => undefined))
  return (type: string, properties: unknown, directory?: string) => Effect.gen(function* () {
    const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity().catch(() => undefined))
    if (admitted?.session_id !== current?.session_id || (admitted && current &&
        JSON.stringify(QuantCodeIdentity.ownerOf(admitted)) !== JSON.stringify(QuantCodeIdentity.ownerOf(current)))) {
      throw new QuantCodeIdentity.IdentityError("登录状态已变化，请重新订阅任务事件。")
    }
    if (publicEvents.has(type)) return true
    if (!admitted || !current) return false
    if (type.startsWith("session.next.")) return false
    if (["installation.updated", "installation.update-available"].includes(type)) {
      const data = record(properties)
      return typeof data?.version === "string" && Object.keys(data).every(key => key === "version")
    }
    if (type === "project.updated" || type === "project.directories.updated") {
      const data = record(properties)
      const projectID = type === "project.updated" ? data?.id : data?.projectID
      if (typeof projectID !== "string") return false
      const project = yield* db.select().from(ProjectTable).where(eq(ProjectTable.id, ProjectSchema.ID.make(projectID)))
        .get().pipe(Effect.orDie)
      if (!project) return false
      return yield* Effect.promise(async () => {
        const grant = await QuantCodeWorkspace.authorize(project.worktree, "read", current).catch(() => undefined)
        if (!grant) return false
        if (type === "project.updated") {
          if (typeof data?.worktree !== "string" || !Array.isArray(data.sandboxes)) return false
          // Do not expose another checkout through a shared project's sandbox list.
          for (const target of [data.worktree, ...data.sandboxes]) {
            if (typeof target !== "string" || !path.isAbsolute(target)) return false
            if (!await QuantCodeWorkspace.authorize(target, "read", current).then(() => true, () => false)) return false
          }
        }
        await QuantCodeWorkspace.revalidate(grant)
        return true
      })
    }
    if (["file.edited", "file.watcher.updated", "lsp.updated", "vcs.branch.updated", "worktree.ready", "worktree.failed",
      "server.instance.disposed"].includes(type)) {
      // directory is the trusted bus/location envelope supplied by the HTTP
      // handler, never a similarly named field in tool output or user metadata.
      if (!directory || !path.isAbsolute(directory)) return false
      return yield* Effect.promise(async () => {
        const grant = await QuantCodeWorkspace.authorize(directory, "read", current).catch(() => undefined)
        if (!grant) return false
        const data = record(properties)
        if (!data) return false
        if (type === "file.edited" || type === "file.watcher.updated") {
          if (typeof data.file !== "string") return false
          if (Object.keys(data).some(key => !["file", "event"].includes(key))) return false
          if (!await QuantCodeWorkspace.target(grant, data.file).then(() => true, () => false)) return false
        }
        if (type === "lsp.updated" && Object.keys(data).length) return false
        if (type === "vcs.branch.updated" && Object.keys(data).some(key => key !== "branch")) return false
        if (type === "worktree.ready" && Object.keys(data).some(key => !["name", "branch"].includes(key))) return false
        if (type === "worktree.failed" && Object.keys(data).some(key => key !== "message")) return false
        if (type === "server.instance.disposed" && data.directory !== directory) return false
        await QuantCodeWorkspace.revalidate(grant)
        return true
      })
    }
    if (["pty.created", "pty.updated", "pty.exited", "pty.deleted"].includes(type)) {
      const data = record(properties)
      const id = type === "pty.created" || type === "pty.updated" ? record(data?.info)?.id : data?.id
      return typeof id === "string" && (yield* Effect.promise(() => QuantCodeTerminalAccess.visibleEvent(id, current)))
    }
    const sessionID = eventSession(type, properties)
    if (!sessionID) return false
    const row = yield* db.select({ metadata: SessionTable.metadata }).from(SessionTable)
      .where(eq(SessionTable.id, SessionID.make(sessionID))).get().pipe(Effect.orDie)
    if (row) return QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), current)
    // A trusted deletion event may be projected after the session row is gone.
    // Public sync replay is disabled for the unified engine, so clients cannot
    // synthesize such an event to claim another session's payload.
    if (type === "session.deleted") {
      const info = record(record(properties)?.info)
      return info?.id === sessionID && QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(record(info.metadata)), current)
    }
    return false
  })
})

export * as QuantCodeEventAccess from "./event-access"

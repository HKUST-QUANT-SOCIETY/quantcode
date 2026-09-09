import path from "node:path"
import { open, mkdir, rename, rm } from "node:fs/promises"
import os from "node:os"
import { randomUUID } from "node:crypto"
import { Effect, Schema } from "effect"
import { and, asc, desc, eq, inArray, lt, sql } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { Global } from "@opencode-ai/core/global"
import { SessionTable, MessageTable, PartTable } from "@opencode-ai/core/session/sql"
import { EventTable, EventSequenceTable } from "@opencode-ai/core/event/sql"
import { QuantCodeTaskIndex } from "@opencode-ai/schema/quantcode-task-index"
import { QuantCodeBudgetEvent } from "@opencode-ai/schema/quantcode-budget"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { QuantCodeKnowledge } from "@opencode-ai/schema/quantcode-knowledge"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"
import { readPrivateFile } from "./private-file"
import { SessionID } from "@/session/schema"
import { EventV2Bridge } from "@/event-v2-bridge"
import { Flock } from "@opencode-ai/core/util/flock"
import { isOrphanedInterruptedTool, requiresToolContinuation } from "@/session/message-state"
import { QuantCodeWriteReceipt } from "./write-receipt"
import { QuantCodeArtifacts } from "./artifacts"
import { QuantCodeToolCatalog } from "./tool-catalog"

type Row = typeof SessionTable.$inferSelect
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

/** Stable publisher ID belongs to this host installation, never a remote URL. */
export async function sourceID() {
  const directory = path.join(Global.Path.state, "organization")
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const filename = path.join(directory, "task-source")
  const read = () =>
    readPrivateFile(filename, 256).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined
      throw error
    })
  const existing = await read()
  const id =
    existing ??
    (await Flock.withLock(
      "quantcode-task-source",
      async () => {
        const prior = await read()
        if (prior) return prior
        const temporary = `${filename}.${randomUUID()}.tmp`
        const created = randomUUID()
        try {
          const file = await open(temporary, "wx", 0o600)
          try {
            await file.writeFile(created)
            await file.sync()
          } finally {
            await file.close()
          }
          await rename(temporary, filename)
        } finally {
          await rm(temporary, { force: true })
        }
        return created
      },
      { dir: path.join(directory, "source-locks") },
    ))
  if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error("任务发布宿主标识无效。")
  return id
}

/** Derived only from native messages, parts and durable accounting. Each
 * child carries its own usage; root totals are not added again to every row. */
const summary = Effect.fn("QuantCodeTaskIndex.summary")(function* (row: Row, identity: QuantCodeIdentity.Identity) {
  const binding = QuantCodeIdentity.sessionBinding(row.metadata ?? undefined)
  if (!binding || !QuantCodeIdentity.owns(binding, identity)) throw new QuantCodeIdentity.IdentityError()
  const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(row.directory, "read", identity))
  const { db } = yield* Database.Service
  const revision = () =>
    db
      .select({ seq: sql<number>`coalesce(sum(${EventSequenceTable.seq}), 0)` })
      .from(EventSequenceTable)
      .where(inArray(EventSequenceTable.aggregate_id, [...new Set([row.id, binding.root_session_id])]))
      .get()
      .pipe(Effect.orDie)
  const before = (yield* revision())?.seq ?? 0
  const currentRow = yield* db.select().from(SessionTable).where(eq(SessionTable.id, row.id)).get().pipe(Effect.orDie)
  if (!currentRow) throw new QuantCodeIdentity.IdentityError()
  row = currentRow
  if (!QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity))
    throw new QuantCodeIdentity.IdentityError()
  const messages = yield* db
    .select()
    .from(MessageTable)
    .where(and(eq(MessageTable.session_id, row.id), sql`json_extract(${MessageTable.data}, '$.summary') IS NOT 1`))
    .orderBy(desc(MessageTable.time_created), desc(MessageTable.id))
    .limit(1)
    .all()
    .pipe(Effect.orDie)
  const executionRow = yield* db
    .select()
    .from(EventTable)
    .where(and(eq(EventTable.aggregate_id, row.id), eq(EventTable.type, "quantcode.execution.changed.1")))
    .orderBy(desc(EventTable.seq))
    .limit(1)
    .get()
    .pipe(Effect.orDie)
  const execution = executionRow
    ? Schema.decodeUnknownSync(QuantCodeTaskIndex.ExecutionChanged.data)(executionRow.data)
    : undefined
  const solutionRow = yield* db
    .select({ data: EventTable.data, seq: EventTable.seq })
    .from(EventTable)
    .where(
      and(
        inArray(EventTable.aggregate_id, [...new Set([row.id, binding.root_session_id])]),
        eq(EventTable.type, "quantcode.solution.changed.1"),
      ),
    )
    .orderBy(desc(sql`${EventTable.aggregate_id} = ${row.id}`), desc(EventTable.seq))
    .limit(1)
    .get()
    .pipe(Effect.orDie)
  const solution = solutionRow
    ? Schema.decodeUnknownSync(QuantCodeGovernance.SolutionChanged.data)(solutionRow.data)
    : undefined
  const last = object(messages[0]?.data)
  const error = object(last.error)
  const errorMessage = typeof object(error.data).message === "string" ? String(object(error.data).message) : undefined
  let status: QuantCodeTaskIndex.Summary["status"] = messages.length ? "paused" : "queued"
  if (last.finish === "error" || last.finish === "content-filter") status = "error"
  if (last.error)
    status =
      error.name === "MessageAbortedError"
        ? "cancelled"
        : errorMessage?.includes("预算") || errorMessage?.includes("stopped_budget")
          ? "stopped_budget"
          : "error"
  if (execution && execution.status !== "idle") status = "running"
  const terminalExecution = execution?.status === "idle" && execution.timestamp >= (messages[0]?.time_created ?? 0)
    ? execution.reason : undefined
  if (terminalExecution === "cancelled") status = "cancelled"
  const parts = yield* db
    .select({ id: PartTable.id, message_id: PartTable.message_id, data: PartTable.data })
    .from(PartTable)
    .where(eq(PartTable.session_id, row.id))
    .all()
    .pipe(Effect.orDie)
  const lastParts = parts
    .filter((part) => part.message_id === messages[0]?.id)
    .map((part) => ({ ...part.data, id: part.id, messageID: part.message_id, sessionID: row.id }))
  if (
    status !== "running" && !terminalExecution &&
    last.role === "assistant" &&
    last.finish === "stop" &&
    object(last.time).completed &&
    !last.error &&
    !requiresToolContinuation(lastParts) &&
    !lastParts.some((part) => part.type === "tool" && isOrphanedInterruptedTool(part))
  )
    status = "completed"
  if (
    status === "running" &&
    parts.some(({ data }) => data.type === "tool" && data.state.status === "running" && data.tool === "question")
  )
    status = "waiting_for_human"
  const gateRows = yield* db
    .select({ type: EventTable.type, data: EventTable.data })
    .from(EventTable)
    .where(
      and(
        eq(EventTable.aggregate_id, row.id),
        executionRow ? sql`${EventTable.seq} > ${executionRow.seq}` : undefined,
        inArray(EventTable.type, ["quantcode.gate.requested.1", "quantcode.gate.decided.1"]),
      ),
    )
    .orderBy(asc(EventTable.seq))
    .all()
    .pipe(Effect.orDie)
  const gates = new Set<string>()
  for (const event of gateRows)
    if (typeof event.data.request_id === "string") {
      if (event.type === "quantcode.gate.requested.1") gates.add(event.data.request_id)
      else gates.delete(event.data.request_id)
    }
  if (status === "running" && gates.size) status = "waiting_for_human"
  const usage = yield* db
    .select({ type: EventTable.type, data: EventTable.data })
    .from(EventTable)
    .where(
      and(
        eq(EventTable.aggregate_id, binding.root_session_id),
        inArray(EventTable.type, [
          "quantcode.budget.reserved.1",
          "quantcode.budget.settled.1",
          "quantcode.budget.reviewed.1",
        ]),
        sql`json_extract(${EventTable.data}, '$.source_session_id') = ${row.id}`,
      ),
    )
    .orderBy(asc(EventTable.seq))
    .all()
    .pipe(Effect.orDie)
  const requests = new Map<string, { reserved: number; input?: number; output?: number; cost?: number | null }>()
  for (const event of usage) {
    if (event.type === "quantcode.budget.reserved.1") {
      const item = Schema.decodeUnknownSync(QuantCodeBudgetEvent.Reserved.data)(event.data)
      if (requests.has(item.request_id)) throw new Error("任务用量预留记录重复。")
      requests.set(item.request_id, { reserved: item.tokens })
    } else {
      const item =
        event.type === "quantcode.budget.settled.1"
          ? Schema.decodeUnknownSync(QuantCodeBudgetEvent.Settled.data)(event.data)
          : Schema.decodeUnknownSync(QuantCodeBudgetEvent.Reviewed.data)(event.data)
      const previous = requests.get(item.request_id)
      if (!previous || previous.input !== undefined) throw new Error("任务用量事件不一致。")
      requests.set(item.request_id, {
        reserved: 0,
        input: item.input_tokens,
        output: item.output_tokens,
        cost: item.cost,
      })
    }
  }
  const totals = [...requests.values()]
  const receipts = yield* QuantCodeWriteReceipt.history(binding.root_session_id)
  const unresolved = [...receipts.values()].some((item) => !item.result && !item.closed)
  if (status === "completed" && (unresolved || totals.some((item) => item.input === undefined))) status = "unknown"
  const captured = yield* QuantCodeArtifacts.collect(row.id)
  const knowledgeRow = yield* db.select({ data: EventTable.data }).from(EventTable)
    .where(and(eq(EventTable.aggregate_id, row.id), eq(EventTable.type, "quantcode.knowledge.candidates.observed.1")))
    .orderBy(desc(EventTable.seq)).limit(1).get().pipe(Effect.orDie)
  const knowledge = knowledgeRow ? Schema.decodeUnknownSync(QuantCodeKnowledge.CandidatesObserved.data)(knowledgeRow.data).result : undefined
  if (((yield* revision())?.seq ?? 0) !== before) throw new Error("任务正在更新，请刷新索引。")
  const artifactRefs = captured.artifacts
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
  const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (current.session_id !== identity.session_id) throw new QuantCodeIdentity.IdentityError()
  const userModel = object(last.model)
  // Only the organization gateway stamps received_at on delivered summaries.
  const task = {
    session_id: SessionID.make(row.id),
    root_session_id: SessionID.make(binding.root_session_id),
    ...(binding.parent_session_id ? { parent_session_id: SessionID.make(binding.parent_session_id) } : {}),
    source_id: yield* Effect.promise(sourceID),
    source_revision: before,
    ...(QuantCodeIdentity.readOnly(row.metadata ?? undefined) ? { read_only: true } : {}),
    actor_id: binding.owner.actor_id,
    group: binding.owner.group,
    role: binding.owner.role,
    workspace_id: binding.owner.workspace_id,
    title: row.title,
    status,
    created_at: row.time_created,
    updated_at: Math.max(row.time_updated, execution?.timestamp ?? 0),
    directory: grant.directory,
    ...(typeof last.agent === "string" ? { agent: last.agent } : {}),
    ...(last.role === "assistant" && typeof last.modelID === "string"
      ? { model: `${last.providerID}/${last.modelID}` }
      : typeof userModel.modelID === "string"
        ? { model: `${userModel.providerID}/${userModel.modelID}` }
        : {}),
    tokens_input: totals.reduce((sum, item) => sum + (item.input ?? 0), 0),
    tokens_output: totals.reduce((sum, item) => sum + (item.output ?? 0), 0),
    reserved_tokens: totals.reduce((sum, item) => sum + item.reserved, 0),
    unconfirmed_requests: totals.filter((item) => item.input === undefined).length,
    cost: totals.some((item) => item.cost == null) ? null : totals.reduce((sum, item) => sum + (item.cost ?? 0), 0),
    artifact_count: artifactRefs.length,
    artifacts: artifactRefs.slice(0, 32),
    artifact_manifest_hash: QuantCodeToolCatalog.digest(artifactRefs),
    ...(knowledge ? { knowledge } : {}),
    ...(solution
      ? {
          solution: {
            document_id: solution.document_id,
            document_hash: solution.document_hash,
            version: solution.version,
            status: solution.status,
          },
        }
      : {}),
    ...(errorMessage ? { last_error: errorMessage.slice(0, 500) } : {}),
  } satisfies Omit<QuantCodeTaskIndex.Summary, "received_at">
  return { task, captured, identity, grant }
})

export const list = Effect.fn("QuantCodeTaskIndex.list")(function* (input: { limit?: number; cursor?: string }) {
  if (!QuantCodeIdentity.enabled()) throw new Error("原生任务索引尚未启用。")
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const limit = input.limit ?? 50
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new Error("任务列表页大小无效。")
  const { db } = yield* Database.Service
  let after = input.cursor
    ? Schema.decodeUnknownSync(Schema.fromJsonString(Schema.Struct({ id: SessionID })))(
        Buffer.from(input.cursor, "base64url").toString(),
      )
    : undefined
  const selected: Row[] = []
  while (selected.length <= limit) {
    const page = yield* db
      .select()
      .from(SessionTable)
      .where(
        and(
          sql`json_extract(${SessionTable.metadata}, '$.quantcode.engine') = 'quantcode'`,
          sql`json_extract(${SessionTable.metadata}, '$.quantcode.owner.actor_id') = ${identity.actor_id}`,
          sql`json_extract(${SessionTable.metadata}, '$.quantcode.owner.group') = ${identity.group}`,
          after ? lt(SessionTable.id, after.id) : undefined,
        ),
      )
      .orderBy(desc(SessionTable.id))
      .limit(100)
      .all()
      .pipe(Effect.orDie)
    for (const row of page)
      if (QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity)) {
        if (
          yield* Effect.promise(() =>
            QuantCodeWorkspace.authorize(row.directory, "read", identity).then(
              () => true,
              () => false,
            ),
          )
        )
          selected.push(row)
      }
    if (page.length < 100) break
    const last = page.at(-1)!
    after = { id: last.id }
  }
  const page = selected.slice(0, limit)
  const tasks = yield* Effect.forEach(page, (row) => summary(row, identity).pipe(Effect.map(result => result.task)))
  const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (current.session_id !== identity.session_id) throw new QuantCodeIdentity.IdentityError()
  const last = page.at(-1)
  return {
    tasks,
    next_cursor:
      selected.length > limit && last ? Buffer.from(JSON.stringify({ id: last.id })).toString("base64url") : null,
  }
})

/** Crash reconciliation only records that a known local executor is gone.
 * It never resumes work, completes a tool or clears an uncertain receipt. */
export const reconcileExecution = Effect.fn("QuantCodeTaskIndex.reconcileExecution")(function* (sessionID: string) {
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const { db } = yield* Database.Service
  const row = yield* db
    .select()
    .from(SessionTable)
    .where(eq(SessionTable.id, SessionID.make(sessionID)))
    .get()
    .pipe(Effect.orDie)
  if (!row || !QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity)) return
  const event = yield* db
    .select()
    .from(EventTable)
    .where(and(eq(EventTable.aggregate_id, sessionID), eq(EventTable.type, "quantcode.execution.changed.1")))
    .orderBy(desc(EventTable.seq))
    .limit(1)
    .get()
    .pipe(Effect.orDie)
  if (!event) return
  const execution = Schema.decodeUnknownSync(QuantCodeTaskIndex.ExecutionChanged.data)(event.data)
  if (execution.status === "idle" || execution.hostname !== os.hostname()) return
  try {
    process.kill(execution.pid, 0)
    return
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") return
  }
  const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (current.session_id !== identity.session_id) throw new QuantCodeIdentity.IdentityError()
  const events = yield* EventV2Bridge.Service
  yield* events.publish(
    QuantCodeTaskIndex.ExecutionChanged,
    { ...execution, status: "idle", reason: "executor_lost", pid: process.pid, timestamp: Date.now() },
    {
      // EventV2 runs this hook in the same immediate transaction as the append.
      // A restarted executor must not be overwritten by crash reconciliation.
      commit: () =>
        Effect.gen(function* () {
          const latest = yield* db
            .select({ id: EventTable.id })
            .from(EventTable)
            .where(and(eq(EventTable.aggregate_id, sessionID), eq(EventTable.type, "quantcode.execution.changed.1")))
            .orderBy(desc(EventTable.seq))
            .limit(1)
            .get()
            .pipe(Effect.orDie)
          if (latest?.id !== event.id) throw new Error("任务执行已变化，请重新读取。")
        }),
    },
  )
})

const snapshot = Effect.fn("QuantCodeTaskIndex.snapshot")(function* (sessionID: string) {
  if (!QuantCodeIdentity.enabled()) throw new Error("原生任务索引尚未启用。")
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const { db } = yield* Database.Service
  const row = yield* db
    .select()
    .from(SessionTable)
    .where(eq(SessionTable.id, SessionID.make(sessionID)))
    .get()
    .pipe(Effect.orDie)
  if (!row) throw new QuantCodeIdentity.IdentityError("任务不存在或当前身份无权查看。")
  return yield* summary(row, identity)
})

function artifactCursor(task: QuantCodeTaskIndex.Summary, artifacts: readonly QuantCodeTaskIndex.ArtifactRef[], limit: number) {
  return artifacts.length > limit
    ? Buffer.from(JSON.stringify({ revision: task.source_revision, manifest: task.artifact_manifest_hash, id: artifacts[limit - 1].id })).toString("base64url")
    : null
}

export const read = Effect.fn("QuantCodeTaskIndex.read")(function* (sessionID: string) {
  const detail = yield* snapshot(sessionID)
  return { task: detail.task, artifacts: detail.task.artifacts.map(artifact => ({ ...artifact,
    delivery_status: artifact.capture_status === "available" ? "available" as const : "unavailable" as const })),
    artifacts_next_cursor: artifactCursor(detail.task, detail.captured.artifacts, 32) } satisfies QuantCodeTaskIndex.Read
})

export const listArtifacts = Effect.fn("QuantCodeTaskIndex.listArtifacts")(function* (input: {
  sessionID: string; source_revision: number; limit?: number; cursor?: string;
}) {
  const detail = yield* snapshot(input.sessionID)
  const limit = input.limit ?? 32
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100 || input.source_revision !== detail.task.source_revision)
    throw new Error("产物页大小或任务版本已变化，请重新读取任务。")
  const cursor = input.cursor ? Schema.decodeUnknownSync(Schema.fromJsonString(Schema.Struct({ revision: Schema.Int, manifest: Schema.String, id: Schema.String })))(
    Buffer.from(input.cursor, "base64url").toString()) : undefined
  if (cursor && (cursor.revision !== input.source_revision || cursor.manifest !== detail.task.artifact_manifest_hash))
    throw new Error("产物分页不属于当前任务版本。")
  const selected = detail.captured.artifacts.filter(item => !cursor || item.id > cursor.id)
  return { source_revision: detail.task.source_revision, artifact_manifest_hash: detail.task.artifact_manifest_hash,
    artifact_count: detail.task.artifact_count, artifacts: selected.slice(0, limit).map(artifact => ({ ...artifact,
      delivery_status: artifact.capture_status === "available" ? "available" as const : "unavailable" as const })),
    next_cursor: artifactCursor(detail.task, selected, limit), manifest_complete: true } satisfies QuantCodeTaskIndex.ArtifactList
})

export const readArtifact = Effect.fn("QuantCodeTaskIndex.readArtifact")(function* (input: {
  sessionID: string; source_revision: number; artifact_id: string; offset?: number;
}) {
  const detail = yield* snapshot(input.sessionID)
  if (input.source_revision !== detail.task.source_revision) throw new Error("产物所属任务版本已变化，请重新读取。")
  const artifact = detail.captured.artifacts.find(item => item.id === input.artifact_id)
  if (!artifact) throw new Error("产物不存在或不属于当前任务版本。")
  const offset = input.offset ?? 0
  const data = yield* Effect.promise(() => QuantCodeArtifacts.content(artifact, detail.captured.inline, offset))
  // Reading content is another authorization boundary, even after an index
  // snapshot. No second Session service or remote filesystem call is involved.
  const access = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (access.session_id !== detail.identity.session_id ||
    QuantCodeToolCatalog.digest(QuantCodeIdentity.ownerOf(access)) !== QuantCodeToolCatalog.digest(QuantCodeIdentity.ownerOf(detail.identity)))
    throw new QuantCodeIdentity.IdentityError()
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(detail.grant))
  const { delivery_status, ...content } = data
  return { source_revision: input.source_revision, artifact: { ...artifact, delivery_status }, offset, ...content } satisfies QuantCodeTaskIndex.ArtifactRead
})
export * as QuantCodeTaskIndex from "./task-index"

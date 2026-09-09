import { Context, Effect, Layer, Schema } from "effect"
import { and, asc, desc, eq, inArray, sql } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { SessionTable } from "@opencode-ai/core/session/sql"
import { EventTable } from "@opencode-ai/core/event/sql"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import { SessionID } from "@/session/schema"
import { AppProcess } from "@opencode-ai/core/process"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { EventV2Bridge } from "@/event-v2-bridge"
import { QuantCodeTaskIndex } from "./task-index"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"
import { QuantCodePublication } from "@opencode-ai/schema/quantcode-publication"
import { Artifact } from "@opencode-ai/schema/quantcode-task-index"
import { QuantCodeKnowledge } from "@opencode-ai/schema/quantcode-knowledge"
import { QuantCodeKnowledgeHost } from "./knowledge"
import { QuantCodeToolCatalog } from "./tool-catalog"

export class Service extends Context.Service<Service, {
  init: () => Effect.Effect<void>
  status: () => Effect.Effect<QuantCodePublication.Status>
}>()(
  "@quantcode/TaskPublisher",
) {}

/** Rebuildable delivery queue for an authorized projection. Task execution,
 * outcomes and retries remain entirely in the native session/event services. */
const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const database = yield* Database.Service
    const events = yield* EventV2Bridge.Service
    const processes = yield* AppProcess.Service
    const dirty = new Set<SessionID>()
    const delivered = new Map<SessionID, { revision: number; at: number }>()
    const failed = new Set<SessionID>()
    const observation: { login?: string; attempt?: number; success?: number; publishing?: SessionID; error?: QuantCodePublication.Status["last_error"] } = {}
    let scanAt = 0
    let scanAfter = ""
    if (QuantCodeIdentity.enabled()) {
      const off = yield* events.listen((event) =>
        Effect.sync(() => {
          const id = event.durable?.aggregateID
          if (Schema.is(SessionID)(id)) dirty.add(id)
        }),
      )
      yield* Effect.addFinalizer(() => off)
      yield* Effect.gen(function* () {
        while (true) {
          yield* Effect.sleep("2 seconds")
          yield* Effect.gen(function* () {
            const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
            if (observation.login !== identity.session_id) {
              // No delivery observations or cursors carry across a login.
              observation.login = identity.session_id
              observation.attempt = undefined
              observation.success = undefined
              observation.error = undefined
              delivered.clear()
              failed.clear()
              scanAt = 0
              scanAfter = ""
            }
            if (observation.error === "identity_unavailable") observation.error = failed.size ? "projection_unavailable" : undefined
            const { db } = database
            if (Date.now() - scanAt > 30000) {
              const rows = yield* db
                .select({ id: SessionTable.id })
                .from(SessionTable)
                .where(
                  and(
                    sql`json_extract(${SessionTable.metadata}, '$.quantcode.owner.actor_id') = ${identity.actor_id}`,
                    sql`json_extract(${SessionTable.metadata}, '$.quantcode.owner.group') = ${identity.group}`,
                    sql`${SessionTable.id} > ${scanAfter}`,
                  ),
                )
                .orderBy(SessionTable.id)
                .limit(100)
                .all()
                .pipe(Effect.orDie)
              for (const row of rows) dirty.add(row.id)
              scanAfter = rows.length === 100 ? rows.at(-1)!.id : ""
              if (!scanAfter) scanAt = Date.now()
            }
            for (const sessionID of [...dirty].slice(0, 32)) {
              const row = yield* db
                .select({ metadata: SessionTable.metadata })
                .from(SessionTable)
                .where(eq(SessionTable.id, sessionID))
                .get()
                .pipe(Effect.orDie)
              if (
                !row ||
                !QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity)
              ) {
                dirty.delete(sessionID)
                failed.delete(sessionID)
                continue
              }
              // Capture a generation by consuming first. Events arriving during
              // export enqueue the session again, so late updates are not lost.
              dirty.delete(sessionID)
              observation.publishing = sessionID
              yield* Effect.gen(function* () {
                yield* QuantCodeTaskIndex.reconcileExecution(sessionID)
                const detail = yield* QuantCodeTaskIndex.read(sessionID)
                const summary = detail.task
                const prior = delivered.get(sessionID)
                if (prior?.revision === summary.source_revision && Date.now() - prior.at < 60000) return
                observation.attempt = Date.now()
                const {
                  actor_id,
                  group,
                  role,
                  workspace_id,
                  directory,
                  last_error,
                  ...task
                } = summary
                yield* Effect.promise(() =>
                  QuantCodeIdentity.gatewayRequest("tasks.publish", {
                    expected_session_id: identity.session_id,
                    task: {
                      ...task,
                      ...(last_error ? { last_error: `native_${summary.status}` } : {}),
                    },
                  }),
                )
                if (prior?.revision !== summary.source_revision) {
                  let cursor: string | undefined
                  const pendingArtifacts: typeof summary.artifacts[number][] = []
                  do {
                    const page = yield* QuantCodeTaskIndex.listArtifacts({ sessionID, source_revision: summary.source_revision, cursor })
                    for (const { delivery_status, ...artifact } of page.artifacts) {
                      const binding = { expected_session_id: identity.session_id, source_id: summary.source_id,
                        session_id: sessionID, source_revision: summary.source_revision, artifact }
                      const published = yield* Effect.promise(() => QuantCodeIdentity.gatewayRequest("artifacts.publish", binding))
                      const remote = Schema.decodeUnknownSync(Schema.Struct({ artifact: Artifact, source_revision: Schema.Int, content_complete: Schema.Boolean }))(published)
                      if (remote.source_revision !== summary.source_revision || remote.artifact.id !== artifact.id ||
                          remote.artifact.sha256 !== artifact.sha256) throw new Error("组织产物回执不属于当前版本。")
                      if (artifact.capture_status === "available" && !remote.content_complete) pendingArtifacts.push(artifact)
                    }
                    cursor = page.next_cursor ?? undefined
                  } while (cursor)
                  for (const artifact of pendingArtifacts) {
                    let offset: number | null = 0
                    while (offset !== null) {
                      const chunk: Effect.Success<ReturnType<typeof QuantCodeTaskIndex.readArtifact>> = yield* QuantCodeTaskIndex.readArtifact({ sessionID, source_revision: summary.source_revision,
                        artifact_id: artifact.id, offset })
                      if (chunk.artifact.delivery_status !== "available" || chunk.content === undefined) throw new Error("原任务产物内容暂不可读。")
                      yield* Effect.promise(() => QuantCodeIdentity.gatewayRequest("artifacts.publish", {
                        expected_session_id: identity.session_id, source_id: summary.source_id, session_id: sessionID,
                        source_revision: summary.source_revision, artifact, offset: chunk.offset,
                        content: chunk.content, encoding: chunk.encoding, chunk_sha256: chunk.chunk_sha256 }))
                      offset = chunk.next_offset
                    }
                  }
                }
                if (summary.status === "completed" && !summary.read_only) {
                  const rows = yield* db.select({ data: EventTable.data }).from(EventTable).where(and(
                    eq(EventTable.aggregate_id, sessionID), eq(EventTable.type, "message.part.updated.1"),
                    sql`json_extract(${EventTable.data}, '$.part.type') = 'tool'`,
                    sql`json_extract(${EventTable.data}, '$.part.state.status') IN ('completed','error')`,
                  )).orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
                  const parts = new Map<string, typeof SessionV1.ToolPart.Type>()
                  for (const row of rows) {
                    const part = Schema.decodeUnknownSync(SessionV1.ToolPart)(row.data.part)
                    parts.set(JSON.stringify([part.messageID, part.callID]), part)
                  }
                  // Failed/partial operations cannot become a successful recipe.
                  if (parts.size && [...parts.values()].every(part => part.state.status === "completed" &&
                      !(part.state.metadata?.quantcodeResult && typeof part.state.metadata.quantcodeResult === "object" &&
                        "successful" in part.state.metadata.quantcodeResult && part.state.metadata.quantcodeResult.successful !== true))) {
                    const source = yield* QuantCodeKnowledgeHost.distill({ source_id: summary.source_id,
                      session_id: sessionID, root_session_id: summary.root_session_id, source_revision: summary.source_revision,
                      tools: [...parts.values()].map(part => ({ call_id: QuantCodeToolCatalog.digest([part.messageID, part.callID]), tool: part.tool })),
                    }, identity).pipe(Effect.provideService(AppProcess.Service, processes))
                    const latest = yield* db.select({ id: EventTable.id, data: EventTable.data }).from(EventTable)
                      .where(and(eq(EventTable.aggregate_id, sessionID), eq(EventTable.type, "quantcode.knowledge.candidates.observed.1")))
                      .orderBy(desc(EventTable.seq)).limit(1).get().pipe(Effect.orDie)
                    if (!latest || QuantCodeToolCatalog.digest(latest.data.result) !== QuantCodeToolCatalog.digest(source)) {
                      yield* events.publish(QuantCodeKnowledge.CandidatesObserved, { sessionID: SessionID.make(sessionID), result: source }, {
                        commit: () => Effect.gen(function* () {
                          const current = yield* db.select({ id: EventTable.id }).from(EventTable)
                            .where(and(eq(EventTable.aggregate_id, sessionID), eq(EventTable.type, "quantcode.knowledge.candidates.observed.1")))
                            .orderBy(desc(EventTable.seq)).limit(1).get().pipe(Effect.orDie)
                          if (current?.id !== latest?.id) throw new Error("知识候选记录已变化，请重新同步。")
                        }),
                      })
                    }
                  }
                }
                delivered.set(sessionID, { revision: summary.source_revision, at: Date.now() })
                failed.delete(sessionID)
                observation.success = Date.now()
                observation.error = failed.size ? "projection_unavailable" : undefined
              }).pipe(
                Effect.catchCause(() => Effect.sync(() => {
                  dirty.add(sessionID)
                  failed.add(sessionID)
                  observation.error = "projection_unavailable"
                })),
                Effect.ensuring(Effect.sync(() => { observation.publishing = undefined })),
              )
            }
          }).pipe(
            Effect.provideService(Database.Service, database),
            Effect.provideService(EventV2Bridge.Service, events),
            Effect.catchCause(() => Effect.sync(() => { observation.error = "identity_unavailable" })),
          )
        }
      }).pipe(Effect.forkScoped)
    }
    const status = Effect.fn("QuantCodeTaskPublisher.status")(function* () {
      if (!QuantCodeIdentity.enabled()) throw new Error("组织同步尚未启用。")
      const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
      const source_id = yield* Effect.promise(QuantCodeTaskIndex.sourceID)
      if (observation.login !== identity.session_id) return { source_id, state: "starting", pending_tasks: 0, failed_tasks: 0 } satisfies QuantCodePublication.Status
      const ids = [...new Set([...dirty, ...(observation.publishing ? [observation.publishing] : [])])]
      const visible = new Set<string>()
      for (let offset = 0; offset < ids.length; offset += 500) {
        const rows = yield* database.db.select({ id: SessionTable.id, metadata: SessionTable.metadata, directory: SessionTable.directory })
          .from(SessionTable).where(inArray(SessionTable.id, ids.slice(offset, offset + 500))).all().pipe(Effect.orDie)
        for (const row of rows) {
          if (!QuantCodeIdentity.owns(QuantCodeIdentity.sessionBinding(row.metadata ?? undefined), identity)) continue
          const granted = yield* Effect.promise(() => QuantCodeWorkspace.authorize(row.directory, "read", identity).then(() => true, () => false))
          if (granted) visible.add(row.id)
        }
      }
      const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
      if (current.session_id !== identity.session_id) throw new QuantCodeIdentity.IdentityError()
      const failures = [...failed].filter(id => visible.has(id)).length
      return { source_id, state: observation.error || failures ? "retrying" : visible.size ? "pending" : !scanAt ? "starting" : "idle",
        pending_tasks: visible.size, failed_tasks: failures,
        ...(observation.attempt ? { last_attempt_at: observation.attempt } : {}),
        ...(observation.success ? { last_success_at: observation.success } : {}),
        ...(observation.error ? { last_error: observation.error } : {}),
      } satisfies QuantCodePublication.Status
    })
    return Service.of({ init: () => Effect.void, status })
  }),
)

export const node = LayerNode.make({ service: Service, layer, deps: [Database.node, EventV2Bridge.node, AppProcess.node] })
export * as QuantCodeTaskPublisher from "./task-publisher"

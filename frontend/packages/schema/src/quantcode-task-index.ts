import { Schema } from "effect"
import { optional, NonNegativeInt } from "./schema"
import { SessionID } from "./session-id"
import { Event } from "./event"
import { QuantCodeKnowledge } from "./quantcode-knowledge"

const Hash = Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/))
/** Captured once at the trusted tool-return boundary. Filesystem paths and
 * remote URLs are never organization artifact references. */
export const ArtifactSnapshot = Schema.Struct({
  id: Schema.String.check(Schema.isPattern(/^artifact_[a-f0-9]{64}$/)),
  kind: Schema.Literals(["artifact", "report"]), name: optional(Schema.String), mime: Schema.String,
  bytes: optional(NonNegativeInt), sha256: optional(Hash),
  ref: Schema.String.check(Schema.isPattern(/^(snapshot|unavailable):[a-f0-9]{64}$/)),
  source: Schema.Literals(["attachment", "metadata"]),
  capture_status: Schema.Literals(["available", "unavailable"]),
  unavailable_reason: optional(Schema.Literals(["original_not_captured", "capture_failed", "invalid_content"])),
}).annotate({ identifier: "QuantCodeArtifactSnapshot" })
export interface ArtifactSnapshot extends Schema.Schema.Type<typeof ArtifactSnapshot> {}
export const ArtifactRef = Schema.Struct({
  ...ArtifactSnapshot.fields,
  source_event_id: Schema.String, source_event_seq: NonNegativeInt,
  message_id: Schema.String, call_id: Schema.String, result_digest: Hash,
}).annotate({ identifier: "QuantCodeArtifactRef" })
export interface ArtifactRef extends Schema.Schema.Type<typeof ArtifactRef> {}

export const Artifact = Schema.Struct({
  ...ArtifactRef.fields,
  delivery_status: Schema.Literals(["available", "pending", "unavailable"]),
}).annotate({ identifier: "QuantCodeArtifact" })
export interface Artifact extends Schema.Schema.Type<typeof Artifact> {}
export const ArtifactList = Schema.Struct({
  source_revision: NonNegativeInt, artifact_manifest_hash: Hash, artifact_count: NonNegativeInt,
  artifacts: Schema.Array(Artifact), next_cursor: Schema.NullOr(Schema.String),
  manifest_complete: Schema.Boolean,
}).annotate({ identifier: "QuantCodeArtifactList" })
export interface ArtifactList extends Schema.Schema.Type<typeof ArtifactList> {}
export const ArtifactRead = Schema.Struct({
  source_revision: NonNegativeInt, artifact: Artifact, offset: NonNegativeInt,
  content: optional(Schema.String), encoding: optional(Schema.Literal("base64")),
  chunk_sha256: optional(Hash), next_offset: Schema.NullOr(NonNegativeInt),
}).annotate({ identifier: "QuantCodeArtifactRead" })
export interface ArtifactRead extends Schema.Schema.Type<typeof ArtifactRead> {}

export const SolutionRef = Schema.Struct({
  document_id: Schema.String, document_hash: Schema.String, version: Schema.Int, status: Schema.Literals(["draft", "frozen", "superseded"]),
}).annotate({ identifier: "QuantCodeSolutionRef" })
export interface SolutionRef extends Schema.Schema.Type<typeof SolutionRef> {}

export const Summary = Schema.Struct({
  session_id: SessionID, root_session_id: SessionID, parent_session_id: optional(SessionID),
  source_id: Schema.String, source_revision: NonNegativeInt, received_at: optional(Schema.Finite),
  read_only: optional(Schema.Boolean),
  actor_id: Schema.String, group: Schema.String, role: Schema.String, workspace_id: Schema.String,
  title: Schema.String, status: Schema.Literals(["queued", "running", "completed", "cancelled", "error", "waiting_for_human", "stopped_budget", "paused", "unknown"]),
  created_at: Schema.Finite, updated_at: Schema.Finite, model: optional(Schema.String), agent: optional(Schema.String),
  tokens_input: NonNegativeInt, tokens_output: NonNegativeInt, cost: Schema.NullOr(Schema.Finite),
  reserved_tokens: NonNegativeInt, unconfirmed_requests: NonNegativeInt, artifact_count: NonNegativeInt,
  artifacts: Schema.Array(ArtifactRef),
  artifact_manifest_hash: Hash,
  solution: optional(SolutionRef),
  knowledge: optional(QuantCodeKnowledge.Result),
  last_error: optional(Schema.String), directory: optional(Schema.String),
}).annotate({ identifier: "QuantCodeTaskSummary" })
export interface Summary extends Schema.Schema.Type<typeof Summary> {}
export const LegacyPending = Schema.Struct({
  source_id: Schema.String, session_id: Schema.String, root_session_id: Schema.String,
  source_revision: NonNegativeInt, title: Schema.String,
  state: Schema.Literals(["awaiting_archive", "awaiting_rebuild"]), message: Schema.String,
}).annotate({ identifier: "QuantCodeLegacyProjectionPending" })
export interface LegacyPending extends Schema.Schema.Type<typeof LegacyPending> {}
export const List = Schema.Struct({ tasks: Schema.Array(Summary), legacy_pending: optional(Schema.Array(LegacyPending)),
  next_cursor: Schema.NullOr(Schema.String) }).annotate({ identifier: "QuantCodeTaskList" })
export interface List extends Schema.Schema.Type<typeof List> {}
export const Read = Schema.Struct({ task: Summary, artifacts: Schema.Array(Artifact), artifacts_next_cursor: Schema.NullOr(Schema.String) }).annotate({ identifier: "QuantCodeTaskIndexRead" })
export interface Read extends Schema.Schema.Type<typeof Read> {}
export const ExecutionChanged = Event.define({ type: "quantcode.execution.changed", durable: { aggregate: "sessionID", version: 1 }, schema: {
  sessionID: SessionID, status: Schema.Literals(["idle", "busy", "retry"]), timestamp: Schema.Finite,
  pid: NonNegativeInt, hostname: Schema.String,
  reason: optional(Schema.Literals(["cancelled", "executor_lost"])),
} })
export const ArtifactsCaptured = Event.define({ type: "quantcode.artifacts.captured", durable: { aggregate: "sessionID", version: 1 }, schema: {
  sessionID: SessionID, message_id: Schema.String, call_id: Schema.String, result_digest: Hash,
  artifacts: Schema.Array(ArtifactSnapshot), timestamp: Schema.Finite,
} })
export const Definitions = Event.inventory(ExecutionChanged, ArtifactsCaptured)
export * as QuantCodeTaskIndex from "./quantcode-task-index"

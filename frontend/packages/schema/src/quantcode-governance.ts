/** Shared transitional organization events. They belong to QuantCode's native
 * session history, without adding a second execution store or legacy Part type. */
import { Schema } from "effect"
import { Event } from "./event"
import { SessionID } from "./session-id"
import { optional } from "./schema"

const base = { sessionID: SessionID, intent_hash: Schema.String, timestamp: Schema.Finite }
const durable = { aggregate: "sessionID", version: 1 } as const
export const Inspection = Event.define({ type: "quantcode.inspection", durable, schema: {
  ...base, purpose: Schema.Literals(["capability_catalog", "group_memory"]),
  server: Schema.String, tool: Schema.String, call_id: Schema.String,
  catalog_digest: Schema.String, result_hash: Schema.String, authorization_hash: Schema.String,
  capabilities: Schema.Array(Schema.Struct({ id: Schema.String, integration_status: Schema.String })),
} })
export const Coverage = Event.define({ type: "quantcode.coverage.proposed", durable, schema: {
  ...base, proposal_hash: Schema.String, inspection_hash: Schema.String,
  coverage: Schema.Literals(["full", "partial", "none"]),
  components: Schema.Array(Schema.String), reason: Schema.String,
} })
export const CoverageReviewed = Event.define({ type: "quantcode.coverage.reviewed", durable, schema: {
  ...base, proposal_hash: Schema.String, reviewer: Schema.String,
  decision: Schema.Literals(["approve", "reject"]), note: Schema.String,
} })
export const SolutionChanged = Event.define({ type: "quantcode.solution.changed", durable, schema: {
  sessionID: SessionID, document_id: Schema.String, document_hash: Schema.String,
  version: Schema.Int.check(Schema.isGreaterThan(0)), status: Schema.Literals(["draft", "frozen", "superseded"]),
} })
export const GateRequested = Event.define({ type: "quantcode.gate.requested", durable, schema: {
  sessionID: SessionID, request_id: Schema.String, operation_digest: Schema.String,
  kind: Schema.Literals(["merge", "permission"]), resource: Schema.String,
  actor: Schema.String, expires_at: Schema.Finite,
} })
export const GateDecided = Event.define({ type: "quantcode.gate.decided", durable, schema: {
  sessionID: SessionID, request_id: Schema.String, operation_digest: Schema.String,
  decision: Schema.Literals(["approve", "reject"]), reviewer: Schema.String,
  note: Schema.String, timestamp: Schema.Finite,
} })
export const WriteStarted = Event.define({ type: "quantcode.write.started", durable, schema: {
  sessionID: SessionID, source_session_id: SessionID, message_id: Schema.String, call_id: Schema.String,
  operation_digest: Schema.String, tool: Schema.String, files: Schema.Array(Schema.String),
  plan_hashes: Schema.Array(Schema.String), timestamp: Schema.Finite,
} })
export const WriteCompleted = Event.define({ type: "quantcode.write.completed", durable, schema: {
  sessionID: SessionID, source_session_id: SessionID, message_id: Schema.String, call_id: Schema.String,
  operation_digest: Schema.String, result_digest: Schema.String, result: Schema.Unknown, timestamp: Schema.Finite,
} })
export const WriteReconciled = Event.define({ type: "quantcode.write.reconciled", durable, schema: {
  sessionID: SessionID, source_session_id: SessionID, message_id: Schema.String, call_id: Schema.String,
  operation_digest: Schema.String, decision: Schema.Literals(["confirmed_completed", "confirmed_not_executed"]),
  reviewer: Schema.String, evidence_ref: Schema.String, note: Schema.String, prior_receipt_digest: Schema.String,
  result: optional(Schema.Unknown), result_digest: optional(Schema.String), timestamp: Schema.Finite,
} })
export const ReceiptReview = Schema.Struct({ source_session_id: SessionID, message_id: Schema.String, call_id: Schema.String,
  expected_digest: Schema.String, expected_receipt_digest: Schema.String, decision: Schema.Literals(["confirmed_completed", "confirmed_not_executed"]),
  evidence_ref: Schema.String, note: Schema.String, result: optional(Schema.Unknown),
}).annotate({ identifier: "QuantCodeReceiptReview" })
export interface ReceiptReview extends Schema.Schema.Type<typeof ReceiptReview> {}
export const ReceiptState = Schema.Struct({ session_id: SessionID, root_session_id: SessionID,
  unresolved: Schema.Array(Schema.Struct({ ...WriteStarted.data.fields, receipt_digest: Schema.String, completion_damaged: Schema.Boolean })),
}).annotate({ identifier: "QuantCodeReceiptState" })
export interface ReceiptState extends Schema.Schema.Type<typeof ReceiptState> {}
export const TaskLockRecovery = Schema.Struct({ expected_digest: Schema.String,
  processes_stopped: Schema.Literal(true), evidence_ref: Schema.String, note: Schema.String,
}).annotate({ identifier: "QuantCodeTaskLockRecovery" })
export interface TaskLockRecovery extends Schema.Schema.Type<typeof TaskLockRecovery> {}
export const TaskLockState = Schema.Struct({ session_id: SessionID,
  status: Schema.Literals(["idle", "active", "recovery_required", "other_host"]),
  lock_digest: optional(Schema.String),
}).annotate({ identifier: "QuantCodeTaskLockState" })
export interface TaskLockState extends Schema.Schema.Type<typeof TaskLockState> {}
export const TaskLockRecoveryRecorded = Event.define({ type: "quantcode.task_lock.recovery_recorded", durable, schema: {
  sessionID: SessionID, lock_digest: Schema.String, reviewer: Schema.String, evidence_ref: Schema.String,
  note: Schema.String, timestamp: Schema.Finite,
} })
export const Definitions = Event.inventory(Inspection, Coverage, CoverageReviewed, SolutionChanged, GateRequested, GateDecided, WriteStarted, WriteCompleted, WriteReconciled, TaskLockRecoveryRecorded)
export const ReuseState = Schema.Struct({
  session_id: SessionID, intent_hash: Schema.String, catalog_checked: Schema.Boolean, memory_checked: Schema.Boolean,
  proposal: optional(Coverage.data), review: optional(CoverageReviewed.data),
}).annotate({ identifier: "QuantCodeReuseState" })
export interface ReuseState extends Schema.Schema.Type<typeof ReuseState> {}
export const ReuseReview = Schema.Struct({ proposal_hash: Schema.String,
  decision: Schema.Literals(["approve", "reject"]), note: Schema.String,
}).annotate({ identifier: "QuantCodeReuseReview" })
export interface ReuseReview extends Schema.Schema.Type<typeof ReuseReview> {}

/** Browser/host wire projection of the existing Python SolutionDoc service. */
export const SolutionDocument = Schema.Struct({
  id: Schema.String, goal: Schema.String, status: Schema.Literals(["draft", "frozen", "superseded"]),
  version: Schema.Int.check(Schema.isGreaterThan(0)), doc_hash: Schema.String,
  acceptance_criteria: Schema.Array(Schema.String), file_impact: Schema.Array(Schema.String),
  rounds: Schema.Array(Schema.Struct({ round_no: Schema.Int, feedback: Schema.String, revision: Schema.String, at: Schema.String })),
  needs_human: Schema.Boolean, trivial_exempt: Schema.Boolean,
  created_at: Schema.String, updated_at: Schema.String,
}).annotate({ identifier: "QuantCodeSolutionDocument" })
export interface SolutionDocument extends Schema.Schema.Type<typeof SolutionDocument> {}
export const SolutionState = Schema.Struct({
  engine: Schema.Literal("quantcode"), session_id: SessionID,
  classification: Schema.Struct({ complexity: Schema.Literals(["L0", "L1", "L2", "L3"]), solution_required: Schema.Boolean,
    business_mode: Schema.String, execution_strategy: Schema.String, governance: Schema.String }),
  solution: optional(SolutionDocument),
}).annotate({ identifier: "QuantCodeSolutionState" })
export interface SolutionState extends Schema.Schema.Type<typeof SolutionState> {}
export const SolutionReview = Schema.Struct({ expected_hash: Schema.String, expected_version: Schema.Int.check(Schema.isGreaterThan(0)),
  decision: Schema.Literals(["approve", "reject"]), note: Schema.String,
}).annotate({ identifier: "QuantCodeSolutionReview" })
export interface SolutionReview extends Schema.Schema.Type<typeof SolutionReview> {}
export * as QuantCodeGovernance from "./quantcode-governance"

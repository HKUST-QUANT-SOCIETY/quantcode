import { Schema } from "effect"
import { optional } from "./schema"
import { QuantCodeNativeGate } from "./quantcode-native-gate"

export const Recovery = Schema.Struct({
  available: Schema.Boolean, gate_available: Schema.Boolean, provenance: Schema.Literals(["missing", "registered", "changed"]),
  checkpoint_digest: Schema.String, owner_digest: Schema.String, latest_checkpoint_id: Schema.String,
  serializer_version: Schema.String, executor_version: Schema.NullOr(Schema.String), provenance_digest: Schema.NullOr(Schema.String),
  runtime_digest: Schema.NullOr(Schema.String), approval: optional(Schema.NullOr(QuantCodeNativeGate.View)), approval_error: optional(Schema.String),
  blockers: Schema.Array(Schema.Struct({ code: Schema.String, message: Schema.String })),
  usage: optional(Schema.NullOr(Schema.Struct({ used_tokens: Schema.Int, reserved_tokens: Schema.Int,
    unconfirmed_requests: Schema.Int, requests: Schema.Int, cost: Schema.NullOr(Schema.Finite) }))),
})
export interface Recovery extends Schema.Schema.Type<typeof Recovery> {}

export const ListInput = Schema.Struct({ limit: optional(Schema.Int), cursor: optional(Schema.String),
  organization: optional(Schema.Boolean), reports_only: optional(Schema.Boolean), group_filter: optional(Schema.String) })
export interface ListInput extends Schema.Schema.Type<typeof ListInput> {}
export const DetailInput = Schema.Struct({ thread_id: Schema.String, checkpoint_id: optional(Schema.String),
  trace_cursor: optional(Schema.Int), organization: optional(Schema.Boolean) })
export interface DetailInput extends Schema.Schema.Type<typeof DetailInput> {}
export const ResumeInput = Schema.Struct({ thread_id: Schema.String, checkpoint_id: Schema.String,
  checkpoint_digest: Schema.String, executor_version: Schema.String, provenance_digest: Schema.String,
  approval_gate_id: optional(Schema.String), expected_gate_id: optional(Schema.String) }).annotate({ identifier: "QuantCodeLegacyResumeInput" })
export interface ResumeInput extends Schema.Schema.Type<typeof ResumeInput> {}
export const ApprovalInput = Schema.Struct({ thread_id: Schema.String, checkpoint_id: Schema.String,
  checkpoint_digest: Schema.String, executor_version: Schema.String, provenance_digest: Schema.String,
  expected_gate_id: Schema.String }).annotate({ identifier: "QuantCodeLegacyApprovalInput" })
export interface ApprovalInput extends Schema.Schema.Type<typeof ApprovalInput> {}

const summary = { engine: Schema.Literal("legacy-python"), read_only: Schema.Literal(true),
  thread_id: Schema.String, checkpoint_id: Schema.String, timestamp: Schema.NullOr(Schema.String), task: Schema.String,
  status: Schema.String, group: Schema.NullOr(Schema.String), actor_id: Schema.NullOr(Schema.String),
  workspace_id: Schema.NullOr(Schema.String), iterations: Schema.Finite, artifacts: optional(Schema.Array(Schema.Unknown)),
}
export const Summary = Schema.Struct(summary)
export interface Summary extends Schema.Schema.Type<typeof Summary> {}
export const List = Schema.Struct({ engine: Schema.Literal("legacy-python"), runs: Schema.Array(Summary),
  next_cursor: Schema.NullOr(Schema.String) }).annotate({ identifier: "QuantCodeLegacyList" })
export interface List extends Schema.Schema.Type<typeof List> {}
export const Detail = Schema.Struct({ ...summary, can_resume: Schema.Boolean, recovery: Recovery,
  recovery_block_reason: Schema.String, pending_approval: Schema.Boolean, checkpoints: Schema.Array(Schema.String),
  messages: Schema.Array(Schema.Struct({ type: Schema.String, content: Schema.Unknown, tool_calls: Schema.Array(Schema.Unknown) })),
  final_message: optional(Schema.String), tool_calls: optional(Schema.Array(Schema.Unknown)),
  execution_trace: optional(Schema.Unknown), output_data: optional(Schema.Unknown), timeline: optional(Schema.Unknown), timeline_error: optional(Schema.String),
  unresolved_operations: optional(Schema.Array(Schema.Unknown)), receipt_reviews: optional(Schema.Array(Schema.Unknown)),
  receipt_review_error: optional(Schema.String), gate: optional(Schema.Unknown), errors: optional(Schema.Array(Schema.Unknown)),
}).annotate({ identifier: "QuantCodeLegacyDetail" })
export interface Detail extends Schema.Schema.Type<typeof Detail> {}
export const Resume = Schema.Struct({ engine: Schema.Literal("legacy-python"), thread_id: Schema.String,
  checkpoint_id: Schema.String, resumed: Schema.Boolean, read_only: Schema.Boolean, recovery: Recovery,
  latest_checkpoint_id: optional(Schema.String), status: Schema.String,
}).annotate({ identifier: "QuantCodeLegacyResume" })
export interface Resume extends Schema.Schema.Type<typeof Resume> {}

export * as QuantCodeLegacy from "./quantcode-legacy"

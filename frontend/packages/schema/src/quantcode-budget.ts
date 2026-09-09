/** Shared transitional accounting for the native QuantCode session tree. */
import { Schema } from "effect"
import { Event } from "./event"
import { SessionID } from "./session-id"
import { NonNegativeInt, optional } from "./schema"

const durable = { aggregate: "sessionID", version: 1 } as const
const request = { sessionID: SessionID, source_session_id: SessionID, request_id: Schema.String }
export const Policy = Event.define({ type: "quantcode.budget.policy", durable, schema: {
  sessionID: SessionID, token_limit: Schema.NullOr(NonNegativeInt), timestamp: Schema.Finite,
} })
export const Reserved = Event.define({ type: "quantcode.budget.reserved", durable, schema: {
  ...request, provider: Schema.String, model: Schema.String, purpose: Schema.String,
  input_estimate: NonNegativeInt, output_limit: NonNegativeInt, tokens: NonNegativeInt, timestamp: Schema.Finite,
  process: optional(Schema.Struct({ pid: NonNegativeInt, hostname: Schema.String })),
} })
export const Settled = Event.define({ type: "quantcode.budget.settled", durable, schema: {
  ...request, input_tokens: NonNegativeInt, output_tokens: NonNegativeInt, tokens: NonNegativeInt,
  cost: Schema.NullOr(Schema.Finite.check(Schema.isGreaterThanOrEqualTo(0))),
  timestamp: Schema.Finite,
} })
export const State = Schema.Struct({
  session_id: SessionID, root_session_id: SessionID, token_limit: Schema.NullOr(NonNegativeInt),
  used: NonNegativeInt, reserved: NonNegativeInt, remaining: Schema.NullOr(NonNegativeInt),
  known_cost: Schema.Finite.check(Schema.isGreaterThanOrEqualTo(0)), unpriced_requests: NonNegativeInt,
  requests: NonNegativeInt, unconfirmed_requests: NonNegativeInt,
  status: Schema.Literals(["active", "warning", "stopped_budget"]),
}).annotate({ identifier: "QuantCodeBudgetState" })
export interface State extends Schema.Schema.Type<typeof State> {}
export const Changed = Event.define({ type: "quantcode.budget.changed", durable, schema: {
  sessionID: SessionID, state: State, timestamp: Schema.Finite,
  reason: optional(Schema.Literals(["token_limit", "capacity_reserved", "input_too_large"])),
} })
export const Ended = Event.define({ type: "quantcode.budget.request_ended", durable, schema: {
  ...request, timestamp: Schema.Finite,
} })
const receipt = {
  input_tokens: NonNegativeInt, output_tokens: NonNegativeInt, tokens: NonNegativeInt,
  cost: Schema.NullOr(Schema.Finite.check(Schema.isGreaterThanOrEqualTo(0))),
}
export const Review = Schema.Struct({
  request_id: Schema.String, expected_digest: Schema.String, request_stopped: Schema.Boolean,
  decision: Schema.Literals(["usage_confirmed", "confirmed_not_executed"]),
  receipt: optional(Schema.Struct(receipt)), evidence_ref: Schema.String, note: Schema.String,
}).annotate({ identifier: "QuantCodeBudgetReview" })
export interface Review extends Schema.Schema.Type<typeof Review> {}
export const Reviewed = Event.define({ type: "quantcode.budget.reviewed", durable, schema: {
  ...request, ...receipt, reservation_digest: Schema.String,
  request_stopped: Schema.Literal(true),
  decision: Schema.Literals(["usage_confirmed", "confirmed_not_executed"]),
  reviewer: Schema.String, evidence_ref: Schema.String, note: Schema.String, timestamp: Schema.Finite,
} })
export const LockState = Schema.Struct({
  status: Schema.Literals(["idle", "active", "recovery_required", "other_host"]),
  lock_digest: optional(Schema.String),
})
export const ReviewState = Schema.Struct({
  budget: State, lock: LockState,
  requests: Schema.Array(Schema.Struct({
    request_id: Schema.String, source_session_id: SessionID, provider: Schema.String, model: Schema.String,
    purpose: Schema.String, reserved_tokens: NonNegativeInt, timestamp: Schema.Finite, reservation_digest: Schema.String,
    status: Schema.Literals(["active", "ended", "process_missing", "other_host", "unknown"]),
  })),
}).annotate({ identifier: "QuantCodeBudgetReviewState" })
export interface ReviewState extends Schema.Schema.Type<typeof ReviewState> {}
export const LockRecovery = Schema.Struct({
  expected_digest: Schema.String, processes_stopped: Schema.Boolean, evidence_ref: Schema.String, note: Schema.String,
}).annotate({ identifier: "QuantCodeBudgetLockRecovery" })
export interface LockRecovery extends Schema.Schema.Type<typeof LockRecovery> {}
export const LockRecoveryRecorded = Event.define({ type: "quantcode.budget.lock_recovery_recorded", durable, schema: {
  sessionID: SessionID, lock_digest: Schema.String, reviewer: Schema.String,
  processes_stopped: Schema.Literal(true),
  evidence_ref: Schema.String, note: Schema.String, timestamp: Schema.Finite,
} })
export const Definitions = Event.inventory(Policy, Reserved, Settled, Changed, Ended, Reviewed, LockRecoveryRecorded)
export * as QuantCodeBudgetEvent from "./quantcode-budget"

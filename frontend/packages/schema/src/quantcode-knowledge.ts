import { Schema } from "effect"
import { NonNegativeInt, optional } from "./schema"
import { SessionID } from "./session-id"
import { Event } from "./event"

const Identifier = Schema.String.check(Schema.isPattern(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/))
const Hash = Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/))
export const Input = Schema.Struct({
  source_id: Identifier, session_id: Identifier, root_session_id: Identifier,
  source_revision: NonNegativeInt,
  tools: Schema.Array(Schema.Struct({ call_id: Identifier, tool: Identifier })),
})
export interface Input extends Schema.Schema.Type<typeof Input> {}

export const Candidate = Schema.Struct({
  name: Identifier, group: Schema.String,
  status: Schema.Literals(["draft", "publishing", "promoted", "rejected", "superseded", "revoked"]),
  digest: Hash, tool_sequence: Schema.Array(Identifier),
}).annotate({ identifier: "QuantCodeKnowledgeCandidate" })
export interface Candidate extends Schema.Schema.Type<typeof Candidate> {}
export const Result = Schema.Struct({
  source_id: Identifier, session_id: Identifier, source_revision: NonNegativeInt,
  input_digest: Hash, observed_at: Schema.String, candidates: Schema.Array(Candidate),
}).annotate({ identifier: "QuantCodeKnowledgeResult" })
export interface Result extends Schema.Schema.Type<typeof Result> {}

export const ReviewInput = Schema.Struct({
  candidate_name: Identifier, action: Schema.Literals(["promote", "reject", "supersede", "revoke"]),
  superseded_by: optional(Identifier), expected_digest: Hash,
})
export interface ReviewInput extends Schema.Schema.Type<typeof ReviewInput> {}
const ReviewRecord = Schema.Struct({
  name: Identifier, group: Schema.String, status: Schema.NullOr(Schema.String),
  reviewed_at: Schema.NullOr(Schema.String), reviewer_id: Schema.NullOr(Schema.String),
  superseded_by: Schema.NullOr(Schema.String),
})
export const List = Schema.Struct({ candidates: Schema.Array(Schema.Struct({
  ...ReviewRecord.fields, content: optional(Schema.String), digest: optional(Hash), error: optional(Schema.String),
})) }).annotate({ identifier: "QuantCodeKnowledgeList" })
export interface List extends Schema.Schema.Type<typeof List> {}
export const Review = Schema.Struct({ ok: Schema.Literal(true), candidate: ReviewRecord })
  .annotate({ identifier: "QuantCodeKnowledgeReview" })
export interface Review extends Schema.Schema.Type<typeof Review> {}

export const CandidatesObserved = Event.define({
  type: "quantcode.knowledge.candidates.observed", durable: { aggregate: "sessionID", version: 1 },
  schema: { sessionID: SessionID, result: Result },
})
export const Definitions = Event.inventory(CandidatesObserved)
export * as QuantCodeKnowledge from "./quantcode-knowledge"

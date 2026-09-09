import { Schema } from "effect"
import { NonNegativeInt, optional } from "./schema"

/** Delivery observations only; these do not claim that a task is executing. */
export const Status = Schema.Struct({
  source_id: Schema.String,
  state: Schema.Literals(["starting", "idle", "pending", "retrying"]),
  pending_tasks: NonNegativeInt,
  failed_tasks: NonNegativeInt,
  last_attempt_at: optional(Schema.Finite),
  last_success_at: optional(Schema.Finite),
  last_error: optional(Schema.Literals(["identity_unavailable", "projection_unavailable"])),
}).annotate({ identifier: "QuantCodePublicationStatus" })
export interface Status extends Schema.Schema.Type<typeof Status> {}
export * as QuantCodePublication from "./quantcode-publication"

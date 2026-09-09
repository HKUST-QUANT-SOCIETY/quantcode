import { Schema } from "effect"
import { optional } from "./schema"

export const ID = Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/)).annotate({ identifier: "QuantCodeNativeGateID" })

export const Request = Schema.Struct({ request_id: Schema.String, root_session_id: Schema.String, session_id: Schema.String,
  message_id: Schema.String, call_id: Schema.String, server: Schema.String, tool: Schema.String,
  kind: Schema.Literals(["merge", "permission"]), resource: Schema.String, resource_version: optional(Schema.String),
  operation_digest: Schema.String, catalog_digest: Schema.String, arguments_json: Schema.String,
  arguments_digest: Schema.String, description: Schema.String, expires_at: Schema.Finite,
})
export interface Request extends Schema.Schema.Type<typeof Request> {}
export const Decision = Schema.Struct({ decision: Schema.Literals(["approve", "reject"]), reviewer: Schema.String,
  reviewer_session_id: Schema.String, note: Schema.String, timestamp: Schema.Finite,
  operation_digest: Schema.String, record_digest: Schema.String, receipt_digest: Schema.String,
})
export interface Decision extends Schema.Schema.Type<typeof Decision> {}
export const View = Schema.Struct({ gate_id: ID, record_digest: Schema.String, request: Request,
  owner: Schema.Struct({ session_id: Schema.String, actor_id: Schema.String, group: Schema.String,
    role: Schema.String, workspace_id: Schema.String, resource_scopes: Schema.Array(Schema.String) }),
  status: Schema.Literals(["pending", "approved", "rejected", "expired", "cancelled"]), valid: Schema.Boolean,
  decision: Schema.NullOr(Decision),
}).annotate({ identifier: "QuantCodeNativeGate" })
export interface View extends Schema.Schema.Type<typeof View> {}
export const List = Schema.Struct({ gates: Schema.Array(View), next_cursor: Schema.NullOr(Schema.String) }).annotate({ identifier: "QuantCodeNativeGateList" })
export const Review = Schema.Struct({ gate_id: Schema.String, expected_digest: Schema.String,
  operation_digest: Schema.String, decision: Schema.Literals(["approve", "reject"]), note: Schema.String,
}).annotate({ identifier: "QuantCodeNativeGateReview" })
export interface Review extends Schema.Schema.Type<typeof Review> {}
export * as QuantCodeNativeGate from "./quantcode-native-gate"

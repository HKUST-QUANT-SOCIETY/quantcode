import { Effect, Schema } from "effect"
import { QuantCodeNativeGate } from "@opencode-ai/schema/quantcode-native-gate"
import { QuantCodeIdentity } from "./identity"

/** A gateway decision is an authorized projection. The native permission
 * service still owns waiting, cancellation and the final execution decision. */
export const publish = (request: QuantCodeNativeGate.Request, login: string) => Effect.promise(async () =>
  Schema.decodeUnknownSync(QuantCodeNativeGate.View)(await QuantCodeIdentity.gatewayRequest("publish", {
    ...request, expected_session_id: login,
  })))
export const read = (gateID: string, login?: string) => Effect.promise(async () =>
  Schema.decodeUnknownSync(QuantCodeNativeGate.View)(await QuantCodeIdentity.gatewayRequest("read", {
    gate_id: gateID, ...(login ? { expected_session_id: login } : {}),
  })))
export const list = (cursor?: string) => Effect.promise(async () =>
  Schema.decodeUnknownSync(QuantCodeNativeGate.List)(await QuantCodeIdentity.gatewayRequest("list", {
    limit: 30, ...(cursor ? { cursor } : {}),
  })))
export const decide = (review: QuantCodeNativeGate.Review) => Effect.promise(async () =>
  Schema.decodeUnknownSync(QuantCodeNativeGate.View)(await QuantCodeIdentity.gatewayRequest("decide", { ...review })))
export const cancel = (gate: QuantCodeNativeGate.View, login: string) => Effect.promise(() =>
  QuantCodeIdentity.gatewayRequest("cancel", { gate_id: gate.gate_id, expected_digest: gate.record_digest, expected_session_id: login }))

export function matches(gate: QuantCodeNativeGate.View, request: QuantCodeNativeGate.Request, login: string) {
  return gate.owner.session_id === login && Object.entries(request).every(([key, value]) => gate.request[key as keyof QuantCodeNativeGate.Request] === value)
}
export * as QuantCodeGate from "./gate"

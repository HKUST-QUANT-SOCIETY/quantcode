import { Effect, Schema } from "effect"
import { QuantCodeTaskIndex } from "@opencode-ai/schema/quantcode-task-index"
import { QuantCodeIdentity } from "./identity"

export const list = (input: { limit?: number; cursor?: string; source_id?: string; root_session_id?: string }) => Effect.promise(async () => {
  if (!QuantCodeIdentity.enabled()) throw new Error("原生组织索引尚未启用。")
  return Schema.decodeUnknownSync(QuantCodeTaskIndex.List)(await QuantCodeIdentity.gatewayRequest("tasks.list", input))
})
export const read = (input: { source_id: string; session_id: string }) => Effect.promise(async () => {
  if (!QuantCodeIdentity.enabled()) throw new Error("原生组织索引尚未启用。")
  return Schema.decodeUnknownSync(QuantCodeTaskIndex.Read)(await QuantCodeIdentity.gatewayRequest("tasks.read", input))
})
export const listArtifacts = (input: { source_id: string; session_id: string; source_revision: number; limit?: number; cursor?: string }) => Effect.promise(async () => {
  if (!QuantCodeIdentity.enabled()) throw new Error("原生产物索引尚未启用。")
  return Schema.decodeUnknownSync(QuantCodeTaskIndex.ArtifactList)(await QuantCodeIdentity.gatewayRequest("artifacts.list", input))
})
export const readArtifact = (input: { source_id: string; session_id: string; source_revision: number; artifact_id: string; offset?: number }) => Effect.promise(async () => {
  if (!QuantCodeIdentity.enabled()) throw new Error("原生产物索引尚未启用。")
  return Schema.decodeUnknownSync(QuantCodeTaskIndex.ArtifactRead)(await QuantCodeIdentity.gatewayRequest("artifacts.read", input))
})
export * as QuantCodeOrganizationTasks from "./organization-tasks"

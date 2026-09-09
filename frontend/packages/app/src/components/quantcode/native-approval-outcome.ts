import type { QuantCodeNativeGate } from "@opencode-ai/sdk/v2"

export type ApprovalReference = { gate_id: string; record_digest: string; operation_digest: string }
export const approvalReference = (gate: QuantCodeNativeGate): ApprovalReference => ({ gate_id: gate.gate_id,
  record_digest: gate.record_digest, operation_digest: gate.request.operation_digest })
export function matchesApproval(reference: ApprovalReference, gate: QuantCodeNativeGate) {
  return reference.gate_id === gate.gate_id && reference.record_digest === gate.record_digest &&
    reference.operation_digest === gate.request.operation_digest && (!gate.decision ||
      gate.decision.record_digest === reference.record_digest && gate.decision.operation_digest === reference.operation_digest)
}
export const retryableApproval = (gate?: QuantCodeNativeGate) => !!gate && gate.valid && gate.status === "pending" && gate.decision === null
export function approvalOutcome(gate?: QuantCodeNativeGate) {
  if (!gate) return "结果待核对"
  const recorded = gate.decision ? `已记录${gate.decision.decision === "approve" ? "批准" : "拒绝"}` : ""
  if (gate.status === "expired") return recorded ? `${recorded}；请求现已过期` : "请求已过期"
  if (gate.status === "cancelled") return recorded ? `${recorded}；请求现已取消` : "请求已取消"
  if (recorded) return gate.valid ? recorded : `${recorded}；原执行授权现已失效`
  return retryableApproval(gate) ? "原请求仍待审批，可重新提交" : "原请求当前不可用，需重新申请"
}

/** Only opaque references survive a reload/login. Decisions, arguments,
 * notes and identity data always come from the current authorized read. */
export function decodeApprovalReferences(raw: string | null): ApprovalReference[] {
  if (!raw || raw.length > 262144) return []
  try {
    const values: unknown = JSON.parse(raw)
    if (!Array.isArray(values)) return []
    const result = values.filter((item): item is ApprovalReference => item && typeof item === "object" &&
      Object.keys(item).length === 3 && ["gate_id", "record_digest", "operation_digest"].every(key =>
        typeof item[key] === "string" && /^[a-f0-9]{64}$/.test(item[key])))
    return [...new Map(result.map(item => [item.gate_id, item])).values()]
  } catch { return [] }
}

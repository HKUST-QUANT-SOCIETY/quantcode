import { expect, test } from "bun:test"
import type { QuantCodeNativeGate } from "@opencode-ai/sdk/v2"
import { approvalOutcome, approvalReference, decodeApprovalReferences, matchesApproval, retryableApproval } from "./native-approval-outcome"

const gate: QuantCodeNativeGate = { gate_id: "a".repeat(64), record_digest: "b".repeat(64), status: "pending", valid: true, decision: null,
  owner: { session_id: "fixture-owner-login", actor_id: "fixture-owner", group: "factor", role: "analyst", workspace_id: "fixture", resource_scopes: [] },
  request: { request_id: "fixture", root_session_id: "ses_fixture", session_id: "ses_fixture", message_id: "msg_fixture", call_id: "call_fixture",
    server: "fixture", tool: "fixture", kind: "merge", resource: "fixture", operation_digest: "c".repeat(64), catalog_digest: "d".repeat(64),
    arguments_json: "{}", arguments_digest: "e".repeat(64), description: "fixture", expires_at: 1 } }

test("lost submission responses remain unknown until an exact current receipt is read", () => {
  expect(approvalOutcome()).toBe("结果待核对")
  expect(retryableApproval()).toBe(false)
  expect(matchesApproval(approvalReference(gate), gate)).toBe(true)
  expect(retryableApproval(gate)).toBe(true)
  expect(matchesApproval({ ...approvalReference(gate), operation_digest: "f".repeat(64) }, gate)).toBe(false)
})

test("recorded, expired and invalidated decisions cannot be resubmitted", () => {
  const approved: QuantCodeNativeGate = { ...gate, status: "approved", decision: { decision: "approve", reviewer: "fixture-reviewer",
    reviewer_session_id: "old-login", note: "fixture note", timestamp: 1, operation_digest: gate.request.operation_digest,
    record_digest: gate.record_digest, receipt_digest: "f".repeat(64) } }
  for (const value of [approved, { ...approved, valid: false }, { ...approved, status: "expired" as const },
    { ...gate, status: "cancelled" as const, valid: false }]) expect(retryableApproval(value)).toBe(false)
  expect(approvalOutcome({ ...approved, valid: false })).toContain("已记录批准")
  expect(approvalOutcome({ ...approved, status: "expired", valid: false })).toContain("现已过期")
  const encoded = JSON.stringify([approvalReference(approved)])
  expect(decodeApprovalReferences(encoded)).toEqual([approvalReference(gate)])
  expect(encoded).not.toContain("fixture note")
  expect(encoded).not.toContain("old-login")
})

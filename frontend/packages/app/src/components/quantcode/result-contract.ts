export type TraceEvent = {
  type: string
  event_id?: string
  timestamp?: number
  thread_id?: string
  seq?: number
  iteration?: number | null
  group?: string
  flow_name?: string
  node?: string | null
  data?: Record<string, unknown>
}

export type RunAgentResult = {
  status: string
  task_id?: string
  group?: string
  actor_id?: string
  role?: string
  session_id?: string
  thread_id?: string
  timestamp?: number
  gate?: {
    kind?: string
    gate_id?: string
    message?: string
    reasons?: string[]
    risk_metrics?: Record<string, unknown>
    decision_schema?: { allowed: string[]; default: string }
    review_history?: { decision: string; timestamp: number }[]
  }
  execution_trace?: TraceEvent[]
  output_data?: Record<string, unknown>
  artifacts?: string[]
  risk_metrics?: Record<string, unknown>
  human_decision?: string
  human_review_history?: { decision: string; timestamp: number }[]
  error?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isOptionalString(value: unknown) {
  return value === undefined || typeof value === "string"
}

function isOptionalNumber(value: unknown) {
  return value === undefined || (typeof value === "number" && Number.isFinite(value))
}

function isReviewHistory(value: unknown) {
  return (
    value === undefined ||
    (Array.isArray(value) &&
      value.every(
        (item) =>
          isRecord(item) &&
          typeof item.decision === "string" &&
          typeof item.timestamp === "number" &&
          Number.isFinite(item.timestamp),
      ))
  )
}

function isTraceEvent(value: unknown): value is TraceEvent {
  return (
    isRecord(value) &&
    typeof value.type === "string" &&
    isOptionalString(value.thread_id) &&
    isOptionalNumber(value.seq) &&
    (value.iteration === undefined || value.iteration === null || isOptionalNumber(value.iteration)) &&
    isOptionalString(value.group) &&
    isOptionalString(value.flow_name) &&
    (value.node === undefined || value.node === null || typeof value.node === "string") &&
    (value.data === undefined || isRecord(value.data))
  )
}

function isGate(value: unknown) {
  if (value === undefined) return true
  if (!isRecord(value)) return false
  if (!isOptionalString(value.kind) || !isOptionalString(value.gate_id) || !isOptionalString(value.message))
    return false
  if (
    value.reasons !== undefined &&
    (!Array.isArray(value.reasons) || !value.reasons.every((item) => typeof item === "string"))
  ) {
    return false
  }
  if (value.risk_metrics !== undefined && !isRecord(value.risk_metrics)) return false
  if (value.decision_schema !== undefined) {
    if (!isRecord(value.decision_schema)) return false
    if (
      !Array.isArray(value.decision_schema.allowed) ||
      !value.decision_schema.allowed.every((item) => typeof item === "string")
    ) {
      return false
    }
    if (typeof value.decision_schema.default !== "string") return false
  }
  return isReviewHistory(value.review_history)
}

export function isRunAgentResult(value: unknown): value is RunAgentResult {
  if (!isRecord(value) || typeof value.status !== "string") return false
  if (
    !isOptionalString(value.thread_id) ||
    !isOptionalString(value.task_id) ||
    !isOptionalString(value.group) ||
    !isOptionalString(value.actor_id) ||
    !isOptionalString(value.role) ||
    !isOptionalString(value.session_id) ||
    !isOptionalNumber(value.timestamp)
  ) return false
  if (!isOptionalString(value.human_decision) || !isOptionalString(value.error)) return false
  if (!isGate(value.gate) || !isReviewHistory(value.human_review_history)) return false
  if (
    value.execution_trace !== undefined &&
    (!Array.isArray(value.execution_trace) || !value.execution_trace.every(isTraceEvent))
  ) {
    return false
  }
  if (
    value.artifacts !== undefined &&
    (!Array.isArray(value.artifacts) || !value.artifacts.every((item) => typeof item === "string"))
  ) {
    return false
  }
  if (value.output_data !== undefined && !isRecord(value.output_data)) return false
  if (value.risk_metrics !== undefined && !isRecord(value.risk_metrics)) return false
  return true
}

export function parseRunAgentOutput(output: string): RunAgentResult | undefined {
  try {
    let value: unknown = JSON.parse(output)
    if (!isRunAgentResult(value) && isRecord(value) && Array.isArray(value.content)) {
      const first = value.content[0]
      if (isRecord(first) && typeof first.text === "string") value = JSON.parse(first.text)
    }
    return isRunAgentResult(value) ? value : undefined
  } catch {
    return
  }
}

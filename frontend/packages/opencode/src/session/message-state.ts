import type { SessionV1 } from "@opencode-ai/core/v1/session"

export function isOrphanedInterruptedTool(part: SessionV1.ToolPart) {
  return part.state.status === "error" && part.state.metadata?.interrupted === true
}

/** Providers may report stop while still returning tool calls. Those results
 * must go through the existing loop before the task can be considered done. */
export function requiresToolContinuation(parts: ReadonlyArray<SessionV1.Part>) {
  return parts.some(part => part.type === "tool" && !part.metadata?.providerExecuted && !isOrphanedInterruptedTool(part))
}

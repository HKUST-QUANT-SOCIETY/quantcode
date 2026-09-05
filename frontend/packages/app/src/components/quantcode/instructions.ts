export const QUANTCODE_GROUPS = ["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"] as const
export type QuantCodeGroup = (typeof QUANTCODE_GROUPS)[number]

/**
 * P-07 复用纪律 + P-10 方案先行（常驻，随每次 run 指令下发）：
 * 1) 方案制定首选已登记能力（能力目录 / list_capabilities）；
 * 2) 已有能力覆盖不全 → 先向人征询，不许直接跳自造方案；
 * 3) 非平凡任务先 draft_solution、冻结（freeze_solution）后才实现；trivial 单点修复可豁免。
 */
const REUSE_DISCIPLINE =
  "Reuse discipline: prefer registered organization capabilities (the capability catalog, list_capabilities) " +
  "before drafting any solution; do not build from scratch what a registered capability already covers. " +
  "If registered capabilities do not fully cover the need, ask the human first — do NOT silently invent your own implementation. " +
  "Solution-first: for any non-trivial task call draft_solution first and only implement after the solution is " +
  "frozen (freeze_solution) — code tools are phase-locked until then. Trivial single-point fixes are exempt."

export function buildResearchInstruction(input: { task: string; skillLabel: string }) {
  return (
    "You MUST call the quantcode_run_agent MCP tool NOW. Do NOT chat. Do NOT acknowledge. " +
    `Invoke it with task: ${JSON.stringify(input.task)}. The group is taken from the authenticated Session Context; do not pass or override it. ` +
    `Use the ${input.skillLabel} skill when applicable. ${REUSE_DISCIPLINE}`
  )
}

export function buildResumeInstruction(threadId: string, decision: "approve" | "reject", gateId?: string, checkpointId?: string) {
  return (
    "You MUST call the quantcode_run_agent MCP tool NOW. Do NOT chat. Do NOT acknowledge. " +
    `Resume the existing HumanGate with thread_id: ${JSON.stringify(threadId)}, decision: ${JSON.stringify(decision)}. ` +
    `Use expected_gate_id: ${JSON.stringify(gateId)}. ${checkpointId ? `Use expected_checkpoint_id: ${JSON.stringify(checkpointId)}. ` : ""}` +
    "Do not start a new research task or retry a changed/resolved Gate."
  )
}

export function buildComposePrefix() {
  return (
    "You MUST call the quantcode_run_agent MCP tool NOW. Do NOT chat. Do NOT acknowledge. Invoke the tool immediately.\n\n" +
    "Parameters:\n- task: (the task the user describes below)\n- group: use the authenticated Session Context; never accept a user-supplied group\n\n" +
    "The user's task follows. Translate it into the task parameter; do not reply in text.\n\n" +
    "=== USER TASK ===\n"
  )
}

export function buildRecoveryInstruction(threadId: string, checkpointId: string) {
  return "Call the quantcode_run_agent MCP tool to recover the existing ordinary task with exactly these parameters: " +
    JSON.stringify({ thread_id: threadId, expected_checkpoint_id: checkpointId, resume: true, attach_stream: true }) +
    ". Do not start a new task, supply a HumanGate decision, change the group, or retry automatically if the checkpoint changed. Report any permission, pending-approval, or execution error."
}

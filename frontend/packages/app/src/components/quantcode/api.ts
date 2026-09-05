import type { OpencodeClient } from "@opencode-ai/sdk/v2"
import type { SshConnectFn } from "./ssh-login"
import type { CapabilityCard } from "./capability-catalog"

export type ReceiptReconciliation = {
  thread_id: string; checkpoint_id: string; call_id: string; expected_digest: string
  decision: "confirmed_completed" | "confirmed_not_executed"
  evidence_ref: string; note: string; result?: unknown
}

export async function reconcileQuantCodeReceipt(client: OpencodeClient, payload: ReceiptReconciliation): Promise<unknown> {
  const response = await client.quantcode.receipt.reconcile(payload)
  if (response.error || !response.data) throw new Error("回执核对提交失败，请确认审核身份和 gateway 连接。")
  return response.data
}

export type QuantCodeToolName =
  | "search_memory"
  | "list_capabilities"
  | "list_skills"
  | "ssh_status"
  | "list_algorithms"
  | "session_context"
  | "list_run_history"
  | "get_run_history"
  | "get_gitgraph"
  | "list_pops"
  | "list_distill_candidates"
  | "list_pending_gates"
  | "admin_task_history"
  | "admin_report_history"
  | "admin_get_task_history"

export type QuantCodeSkill = {
  id: string
  name?: string
  description?: string
  pattern?: string
}

export type QuantCodeSkillsResult = {
  group?: string
  skills?: QuantCodeSkill[]
  error?: string
}

export type QuantCodeAlgorithm = { id: string; description?: string }

export type QuantCodeAlgorithmsResult = {
  algorithms?: QuantCodeAlgorithm[]
  error?: string
}

export type QuantCodeMemoryHit = {
  path?: string
  scope?: string
  scope_id?: string
  type?: string
  snippet?: string
  score?: number
}

export type QuantCodeMemoryResult = {
  status?: string
  hits?: QuantCodeMemoryHit[]
  error?: string
}

export type QuantCodeCapabilitiesResult = {
  status?: string
  capabilities?: CapabilityCard[]
  error?: string
}

export type QuantCodeSshStatus = {
  configured?: boolean
  servers?: { name?: string; host?: string; port?: number; user?: string }[]
  group_bindings_ready?: boolean
  group_bindings_count?: number
  error?: string
}

export type QuantCodeSessionContext = {
  session_id?: string
  group?: string
  role?: string
  actor_id?: string
  workspace_id?: string
  workspace_path?: string
  github_subject?: string
  resource_scopes?: string[]
  identity_source?: string
  error?: string
}

export async function readQuantCodeTool(
  client: OpencodeClient,
  tool: QuantCodeToolName,
  group?: string,
  params?: { query?: string; limit?: number; cursor?: string; thread_id?: string; checkpoint_id?: string; trace_cursor?: number },
): Promise<unknown> {
  const response = await client.quantcode.tool.readOnly({
    tool,
    ...(group ? { group } : {}),
    ...(params?.cursor ? { cursor: params.cursor } : {}),
    ...(params?.thread_id ? { thread_id: params.thread_id } : {}),
    ...(params?.checkpoint_id ? { checkpoint_id: params.checkpoint_id } : {}),
    ...(params?.trace_cursor !== undefined ? { trace_cursor: String(params.trace_cursor) } : {}),
    ...(params?.query ? { query: params.query } : {}),
    ...(params?.limit ? { limit: String(params.limit) } : {}),
  })
  if (response.error || response.data === undefined || response.data === null) {
    throw new Error("QuantCode read-only service is unavailable")
  }
  return response.data
}

export async function listQuantCodeSkills(client: OpencodeClient, group: string) {
  const result = (await readQuantCodeTool(client, "list_skills", group)) as QuantCodeSkillsResult | undefined
  if (result?.error) throw new Error(result.error)
  if (!Array.isArray(result?.skills)) throw new Error("Invalid QuantCode skills response")
  return result.skills.filter((skill) => typeof skill?.id === "string" && skill.id.trim())
}

export async function searchQuantCodeMemory(client: OpencodeClient, query: string, limit = 10) {
  const result = (await readQuantCodeTool(client, "search_memory", undefined, { query, limit })) as
    | QuantCodeMemoryResult
    | undefined
  if (result?.error && result.status === "UNAVAILABLE") return null
  if (result?.error) throw new Error(result.error)
  if (!Array.isArray(result?.hits)) throw new Error("Invalid QuantCode memory response")
  return {
    hits: (result?.hits ?? []).map((hit) => ({
      id: hit.path,
      title: hit.path?.split("/").pop() ?? "Memory",
      snippet: hit.snippet,
      score: hit.score,
      scope: hit.scope_id ? `${hit.scope}/${hit.scope_id}` : hit.scope,
    })),
  }
}

export async function listQuantCodeAlgorithms(client: OpencodeClient) {
  const result = (await readQuantCodeTool(client, "list_algorithms")) as QuantCodeAlgorithmsResult | undefined
  if (result?.error) throw new Error(result.error)
  if (!Array.isArray(result?.algorithms)) throw new Error("Invalid QuantCode algorithms response")
  return result.algorithms.filter((algorithm) => typeof algorithm?.id === "string" && algorithm.id.trim())
}

export async function listQuantCodeCapabilities(client: OpencodeClient) {
  const result = (await readQuantCodeTool(client, "list_capabilities")) as QuantCodeCapabilitiesResult | undefined
  if (result?.error) throw new Error(result.error)
  if (!Array.isArray(result?.capabilities)) throw new Error("Invalid QuantCode capabilities response")
  return result.capabilities
}

export async function getQuantCodeSessionContext(client: OpencodeClient) {
  const result = (await readQuantCodeTool(client, "session_context")) as QuantCodeSessionContext | undefined
  if (result?.error) throw new Error(result.error)
  if (!result?.group) throw new Error("QuantCode session context has no bound group")
  if (result.role !== undefined && !["analyst", "approver", "admin"].includes(result.role)) {
    throw new Error("QuantCode session context has an invalid role")
  }
  return result
}

/**
 * ssh_status is deliberately read-only: it reports configured identities but
 * does not claim that a network probe or private-key authentication happened.
 */
export function createSshStatusConnect(client: OpencodeClient): SshConnectFn {
  return async ({ log }) => {
    const result = (await readQuantCodeTool(client, "ssh_status")) as QuantCodeSshStatus | undefined
    const servers = result?.servers ?? []
    if (servers.length > 0) {
      log(`ssh_status: ${servers.length} configured server${servers.length === 1 ? "" : "s"}`)
    }
    log("ssh_status is read-only; network connection probing is not available")
    return {
      status: "error",
      reason: "unavailable",
    }
  }
}


export async function updateQuantCodePop(client: OpencodeClient, pop_id: string, changes: { read?: boolean; ack?: boolean }) {
  const response = await client.quantcode.pop.update({ pop_id, ...changes })
  if (response.error || !response.data) throw new Error("通知状态保存失败")
  if (typeof response.data === "object" && "error" in response.data) throw new Error(String(response.data.error))
  return response.data
}


export async function reviewQuantCodeCandidate(client: OpencodeClient, candidate_name: string,
  action: "promote" | "reject" | "supersede" | "revoke", expected_digest?: string, superseded_by?: string) {
  const response = await client.quantcode.candidate.review({ candidate_name, action, expected_digest, superseded_by })
  if (response.error || !response.data) throw new Error("知识审核服务不可用")
  if (typeof response.data !== "object" || !("ok" in response.data) || response.data.ok !== true) {
    throw new Error(typeof response.data === "object" && "error" in response.data ? String(response.data.error) : "知识审核失败")
  }
  return response.data
}


export function createLocalIdentityConnect(client: OpencodeClient, onConnected: () => void): SshConnectFn {
  return async ({ identityId, log }) => {
    if (identityId !== "host-default") return { status: "error", reason: "未知本机身份" }
    log("正在请求 SSH agent 签名并验证正式 roster…")
    const response = await client.quantcode.identity.login({})
    const result = response.data
    if (response.error || !result || typeof result !== "object" || !("status" in result) || result.status !== "connected" || !("fingerprint" in result) || typeof result.fingerprint !== "string") {
      return { status: "error", reason: "身份认证未完成，请检查本机 SSH agent、gateway 和 roster 配置" }
    }
    onConnected()
    return { status: "connected", fingerprint: result.fingerprint, groups: "groups" in result && Array.isArray(result.groups) ? result.groups : [] }
  }
}

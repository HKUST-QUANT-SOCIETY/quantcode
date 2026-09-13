import { researchEndpoint } from "./quantcode-connection"
import type { ResearchConnection } from "./quantcode-connection"

export type Prepared = { version: 1; nonce: string; session_id: string; owner_digest: string; github_subject: string; expires_at: number }
export class GitHubConnectionError extends Error {}

export function sameIdentity(a: Prepared, b: Prepared) {
  return a.session_id === b.session_id && a.owner_digest === b.owner_digest && a.github_subject === b.github_subject
}

export async function hostRequest(connection: ResearchConnection, route: string, signal: AbortSignal, input?: unknown): Promise<unknown> {
  const headers: Record<string, string> = { Accept: "application/json" }
  if (connection.password) headers.Authorization = `Basic ${Buffer.from(`${connection.username ?? "opencode"}:${connection.password}`).toString("base64")}`
  if (input !== undefined) headers["Content-Type"] = "application/json"
  const url = researchEndpoint(connection, route === "session-context" ? "/experimental/quantcode/tool" : route)
  if (route === "session-context") url.searchParams.set("tool", "session_context")
  const response = await fetch(url, { method: input === undefined ? "GET" : "POST", headers,
    body: input === undefined ? undefined : JSON.stringify(input), redirect: "error",
    signal: AbortSignal.any([signal, AbortSignal.timeout(45000)]) })
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw new GitHubConnectionError("当前研究宿主登录已失效或无权接入 GitHub，请重新登录。")
    if (response.status === 404) throw new GitHubConnectionError("研究宿主尚未提供 GitHub 接入接口，请更新宿主。")
    throw new GitHubConnectionError(`GitHub 接入请求失败（${response.status}），请刷新连接状态后重试。`)
  }
  const bytes = await response.text()
  if (bytes.length > 65536) throw new GitHubConnectionError("研究宿主返回异常的 GitHub 连接结果。")
  return JSON.parse(bytes)
}

export async function prepare(connection: ResearchConnection, signal: AbortSignal): Promise<Prepared> {
  // The host's generic BadRequest response omits the missing roster binding.
  // Read the authenticated context first so that enrollment errors stay actionable.
  const context = await hostRequest(connection, "session-context", signal)
  if (!context || typeof context !== "object" || !("github_subject" in context) || !context.github_subject) {
    throw new GitHubConnectionError("当前组织身份尚未绑定 GitHub 账号，请在组织名册中补充账号绑定后重新登录。")
  }
  const value = await hostRequest(connection, "/experimental/quantcode/github/credential/prepare", signal)
  if (!value || typeof value !== "object") throw new GitHubConnectionError("研究宿主未提供本机凭据接入协议。")
  const result = value as Prepared
  if (result.version !== 1 || typeof result.nonce !== "string" || result.nonce.length > 128 ||
    typeof result.session_id !== "string" || !result.session_id || result.session_id.length > 256 ||
    !/^[a-f0-9]{64}$/.test(result.owner_digest) || !/^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(result.github_subject) ||
    !Number.isFinite(result.expires_at) || result.expires_at <= Date.now()) throw new GitHubConnectionError("研究宿主返回的 GitHub 身份绑定无效。")
  return result
}

export async function connectCredential(target: ResearchConnection, initial: Prepared, token: string, signal: AbortSignal, checkTarget: () => Promise<void>) {
  if (!token || token.length > 16384 || /\s/.test(token)) throw new GitHubConnectionError("此电脑返回的 GitHub 凭据无效。")
  const response = await fetch("https://api.github.com/user", { headers: {
    Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
  }, redirect: "error", signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) })
  if (!response.ok || String((await response.json()).login ?? "").toLowerCase() !== initial.github_subject.toLowerCase()) {
    throw new GitHubConnectionError("本机 GitHub 账号与组织名册不一致，未将凭据发送给研究宿主。")
  }
  const fresh = await prepare(target, signal)
  if (!sameIdentity(initial, fresh)) throw new GitHubConnectionError("研究宿主的组织身份已变化，已取消凭据接入。")
  await checkTarget()
  signal.throwIfAborted()
  const result = await hostRequest(target, "/experimental/quantcode/github/credential/import", signal, {
    version: 1, nonce: fresh.nonce, session_id: fresh.session_id, owner_digest: fresh.owner_digest, token,
  })
  if (!result || typeof result !== "object" || !("status" in result) || result.status !== "connected" ||
    !("subject" in result) || typeof result.subject !== "string" || result.subject.toLowerCase() !== initial.github_subject.toLowerCase()) {
    throw new GitHubConnectionError("研究宿主未确认 GitHub 连接，请刷新连接状态后再决定是否重试。")
  }
  return { status: "connected" as const, subject: result.subject, host: new URL(target.url).host }
}


import { isAbsolute, join } from "node:path"
import { execFile, spawn } from "node:child_process"
import type { ChildProcess } from "node:child_process"
import { createHash, randomUUID } from "node:crypto"
import { QuantCodeIdentity } from "@/quantcode/identity"
import type { QuantCodeGitHub } from "@opencode-ai/schema/quantcode-github"

type Login = { session: string; code?: string; done: boolean; failed: boolean; child: ChildProcess; timer: ReturnType<typeof setTimeout> }
let login: Login | undefined

const preparations = new Map<string, QuantCodeGitHub.CredentialPreparation>()
function ownerDigest(identity: QuantCodeIdentity.Identity) {
  const owner = { ...QuantCodeIdentity.ownerOf(identity), resource_scopes: [...new Set(identity.resource_scopes)].sort() }
  return createHash("sha256").update(JSON.stringify(Object.fromEntries(Object.entries(owner).sort(([a], [b]) =>
    a < b ? -1 : a > b ? 1 : 0)))).digest("hex")
}

export async function prepareGitHubCredential(): Promise<QuantCodeGitHub.CredentialPreparation> {
  const identity = await QuantCodeIdentity.currentIdentity()
  if (!identity.github_subject || !/^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(identity.github_subject)) {
    throw new Error("当前组织身份尚未绑定有效 GitHub 账号。")
  }
  for (const [key, item] of preparations) if (item.expires_at <= Date.now()) preparations.delete(key)
  if (preparations.size >= 512) throw new Error("GitHub 连接请求过多，请稍后重试。")
  const result = { version: 1 as const, nonce: randomUUID(), session_id: identity.session_id,
    owner_digest: ownerDigest(identity), github_subject: identity.github_subject, expires_at: Date.now() + 120000 }
  preparations.set(result.nonce, result)
  return result
}

export async function importGitHubCredential(input: QuantCodeGitHub.CredentialImport): Promise<QuantCodeGitHub.Connection> {
  const prepared = preparations.get(input.nonce)
  preparations.delete(input.nonce)
  if (!prepared || prepared.expires_at <= Date.now() || input.version !== 1 ||
    input.session_id !== prepared.session_id || input.owner_digest !== prepared.owner_digest ||
    !input.token || input.token.length > 16384 || /\s/.test(input.token)) throw new Error("GitHub 连接准备已变化，请重试。")
  const identity = await QuantCodeIdentity.currentIdentity()
  if (identity.session_id !== prepared.session_id || ownerDigest(identity) !== prepared.owner_digest ||
    identity.github_subject !== prepared.github_subject) throw new Error("组织身份已变化，请重新连接 GitHub。")
  const result = await hostGitHub("import", identity.session_id, { token: input.token, owner_digest: prepared.owner_digest })
  const current = await QuantCodeIdentity.currentIdentity()
  if (current.session_id !== prepared.session_id || ownerDigest(current) !== prepared.owner_digest) {
    throw new Error("组织身份已变化，请重新读取 GitHub 连接状态。")
  }
  if (result.status !== "connected" || typeof result.subject !== "string" ||
    result.subject.toLowerCase() !== prepared.github_subject.toLowerCase()) throw new Error("研究宿主未确认 GitHub 连接，请刷新连接状态。")
  return { status: "connected", subject: result.subject }
}

export async function hostGitHub(action: string, session: string, payload: unknown = {}) {
  const python = process.env.QUANTCODE_HOST_PYTHON
  const root = process.env.QUANTCODE_BACKEND_ROOT
  if (!python || !root || !isAbsolute(python) || !isAbsolute(root)) return { error: "研究宿主的 GitHub 服务未配置。" }
  const input = JSON.stringify(payload)
  if (Buffer.byteLength(input) > 1_000_000) return { error: "GitHub 请求超出大小限制。" }
  const output = await new Promise<string | undefined>((resolve) => {
    const child = execFile(python, ["-m", "quantcode.github_host", "--action", action, "--session", session], {
      cwd: root, env: { ...process.env, QUANTCODE_GITHUB_CREDENTIALS_FILE: process.env.QUANTCODE_GITHUB_CREDENTIALS_FILE ?? join(root, ".quantcode", "github-credentials.json") },
      encoding: "utf8", timeout: action === "get_gitgraph" ? 180000 : 30000,
      killSignal: "SIGKILL", maxBuffer: 8_000_000, windowsHide: true,
    }, (error, stdout) => resolve(error ? undefined : stdout))
    // A startup failure can close stdin before the write drains. execFile's
    // callback reports the process error without leaking stderr or paths.
    child.stdin?.on("error", () => undefined)
    child.stdin?.end(input)
  })
  if (output === undefined) return { error: "研究宿主的 GitHub 连接超时或未完成，请刷新状态。" }
  return JSON.parse(output) as Record<string, unknown>
}

export async function githubConnection(mode?: "local" | "browser" | "cancel") {
  const identity = await QuantCodeIdentity.currentIdentity()
  const session = identity.session_id
  if (login && login.session !== session) { login.child.kill("SIGKILL"); clearTimeout(login.timer); login = undefined }
  if (mode === "cancel") { login?.child.kill("SIGKILL"); if (login) clearTimeout(login.timer); login = undefined; return { status: "disconnected" } }
  if (mode === "local") return { error: "读取此电脑凭据请使用 QuantCode 桌面端；远程研究宿主的凭据不是本机凭据。" }
  if (mode === "browser" && !login) {
    // gh owns the OAuth client and credential storage; the browser sees only a short-lived user code.
    const child = spawn("gh", ["auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--scopes", "read:org"], {
      env: { ...process.env, GH_TOKEN: undefined, GITHUB_TOKEN: undefined, GH_BROWSER: process.platform === "win32" ? "cmd /c exit" : "true" },
      stdio: ["ignore", "ignore", "pipe"], windowsHide: true,
    })
    const state: Login = { session, child, done: false, failed: false, timer: setTimeout(() => { child.kill("SIGKILL"); state.failed = true; state.done = true }, 600000) }
    login = state
    let output = ""
    child.stderr.setEncoding("utf8")
    child.stderr.on("data", (chunk: string) => {
      output = (output + chunk).slice(-4096)
      const match = output.match(/\b[A-Z0-9]{4}-[A-Z0-9]{4}\b/)
      if (match) state.code = match[0]
    })
    child.once("error", () => { state.failed = true; state.done = true; clearTimeout(state.timer) })
    child.once("close", (code) => {
      state.failed = state.failed || code !== 0
      state.done = true
      clearTimeout(state.timer)
    })
  }
  if (login?.done) {
    const failed = login.failed
    login = undefined
    return failed ? { error: "GitHub 授权未完成或已过期，请重试。" } : hostGitHub("connect", session)
  }
  if (login) return { status: "authorizing", code: login.code, url: "https://github.com/login/device" }
  return hostGitHub("status", session)
}

export async function githubCommit(repo: string, sha: string) {
  const identity = await QuantCodeIdentity.currentIdentity()
  return hostGitHub("commit", identity.session_id, { repo, sha })
}

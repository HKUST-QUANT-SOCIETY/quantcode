import { app, ipcMain } from "electron"
import type { IpcMainInvokeEvent } from "electron"
import { execFile, spawn } from "node:child_process"
import type { ChildProcess } from "node:child_process"
import { researchEndpoint, resolveResearchConnection } from "./quantcode-connection"
import type { ResearchConnection } from "./quantcode-connection"
import type { ServerReadyData } from "../preload/types"
import type { DesktopGitHubResult } from "@opencode-ai/app/github"

type Prepared = { version: 1; nonce: string; session_id: string; owner_digest: string; github_subject: string; expires_at: number }
type Attempt = { server: string; target: ResearchConnection; identity: Prepared; abort: AbortController;
  child?: ChildProcess; code?: string; error?: string; done: boolean; failed: boolean; connected: boolean; timer: ReturnType<typeof setTimeout> }

class GitHubConnectionError extends Error {}

function sameIdentity(a: Prepared, b: Prepared) {
  return a.session_id === b.session_id && a.owner_digest === b.owner_digest && a.github_subject === b.github_subject
}

async function hostRequest(connection: ResearchConnection, route: string, signal: AbortSignal, input?: unknown): Promise<unknown> {
  const headers: Record<string, string> = { Accept: "application/json" }
  if (connection.password) headers.Authorization = `Basic ${Buffer.from(`${connection.username ?? "opencode"}:${connection.password}`).toString("base64")}`
  if (input !== undefined) headers["Content-Type"] = "application/json"
  const response = await fetch(researchEndpoint(connection, route), { method: input === undefined ? "GET" : "POST", headers,
    body: input === undefined ? undefined : JSON.stringify(input), redirect: "error",
    signal: AbortSignal.any([signal, AbortSignal.timeout(45000)]) })
  if (!response.ok) throw new GitHubConnectionError("研究宿主不支持本机 GitHub 接入或登录已失效，请更新宿主并重新登录。")
  const bytes = await response.text()
  if (bytes.length > 65536) throw new GitHubConnectionError("研究宿主返回异常的 GitHub 连接结果。")
  return JSON.parse(bytes)
}

async function prepare(connection: ResearchConnection, signal: AbortSignal): Promise<Prepared> {
  const value = await hostRequest(connection, "/experimental/quantcode/github/credential/prepare", signal)
  if (!value || typeof value !== "object") throw new GitHubConnectionError("研究宿主未提供本机凭据接入协议。")
  const result = value as Prepared
  if (result.version !== 1 || typeof result.nonce !== "string" || result.nonce.length > 128 ||
    typeof result.session_id !== "string" || !result.session_id || result.session_id.length > 256 ||
    !/^[a-f0-9]{64}$/.test(result.owner_digest) || !/^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(result.github_subject) ||
    !Number.isFinite(result.expires_at) || result.expires_at <= Date.now()) throw new GitHubConnectionError("研究宿主返回的 GitHub 身份绑定无效。")
  return result
}

const localEnvironment = () => {
  const env: NodeJS.ProcessEnv = { ...process.env, GH_TOKEN: undefined, GITHUB_TOKEN: undefined,
    GH_ENTERPRISE_TOKEN: undefined, GITHUB_ENTERPRISE_TOKEN: undefined, GH_HOST: "github.com",
    GIT_TERMINAL_PROMPT: "0", GCM_INTERACTIVE: "never", GIT_ASKPASS: "", SSH_ASKPASS: "", GIT_CONFIG_COUNT: "0",
    GIT_DIR: undefined, GIT_WORK_TREE: undefined, GIT_CONFIG: undefined, GIT_CONFIG_GLOBAL: undefined, GIT_CONFIG_SYSTEM: undefined,
    GIT_CEILING_DIRECTORIES: app.getPath("userData") }
  for (const key of Object.keys(env)) if (/^GIT_CONFIG_(?:KEY|VALUE)_/.test(key)) delete env[key]
  return env
}

function localCommand(command: "gh" | "git", args: string[], signal: AbortSignal, input?: string) {
  return new Promise<string | undefined>((resolve) => {
    const child = execFile(command, args, { cwd: app.getPath("userData"), env: localEnvironment(),
      timeout: 15000, killSignal: "SIGKILL", maxBuffer: 65536, windowsHide: true, encoding: "utf8", signal },
    (error, stdout) => resolve(error ? undefined : stdout))
    child.stdin?.on("error", () => undefined)
    child.stdin?.end(input)
  })
}

async function localCredential(subject: string, signal: AbortSignal) {
  const gh = await localCommand("gh", ["auth", "token", "--hostname", "github.com", "--user", subject], signal)
  if (gh?.trim()) return gh.trim()
  signal.throwIfAborted()
  const git = await localCommand("git", ["-c", "credential.interactive=false", "credential", "fill"], signal,
    `protocol=https\nhost=github.com\nusername=${subject}\n\n`)
  const fields = Object.fromEntries((git ?? "").split(/\r?\n/).filter(line => line.includes("=")).map(line => {
    const position = line.indexOf("=")
    return [line.slice(0, position), line.slice(position + 1)]
  }))
  if (fields.protocol !== "https" || fields.host !== "github.com" || !fields.password) {
    throw new GitHubConnectionError("此电脑未找到该账号的 gh 或 Git 凭据，请使用“通过 GitHub 登录”。")
  }
  return fields.password
}

async function connectCredential(target: ResearchConnection, initial: Prepared, token: string, signal: AbortSignal, checkTarget: () => Promise<void>) {
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

export function registerGitHubIpc(awaitInitialization: () => Promise<ServerReadyData>) {
  const attempts = new Map<number, Attempt>()
  const busy = new Set<number>()
  const epochs = new Map<number, number>()
  const watched = new Set<number>()
  const stop = (sender: number) => {
    epochs.set(sender, (epochs.get(sender) ?? 0) + 1)
    const current = attempts.get(sender)
    current?.abort.abort()
    current?.child?.kill("SIGKILL")
    if (current) clearTimeout(current.timer)
    attempts.delete(sender)
  }
  app.once("will-quit", () => { for (const sender of attempts.keys()) stop(sender) })

  const connection = (server: string) => resolveResearchConnection(server, awaitInitialization)

  ipcMain.handle("quantcode-github-request", async (event: IpcMainInvokeEvent, input: unknown): Promise<DesktopGitHubResult> => {
    const sender = event.sender.id
    let acquired = false
    try {
      const origin = new URL(event.senderFrame?.url ?? "")
      if (event.senderFrame !== event.sender.mainFrame) throw new GitHubConnectionError("GitHub 凭据操作仅允许 QuantCode 桌面窗口。")
      if (!(origin.protocol === "oc:" && origin.hostname === "renderer") &&
        !(!app.isPackaged && ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))) throw new GitHubConnectionError("GitHub 凭据操作仅允许 QuantCode 桌面窗口。")
      if (!input || typeof input !== "object" || !("server" in input) || typeof input.server !== "string" ||
        Object.keys(input).some(key => !["server", "mode"].includes(key))) throw new GitHubConnectionError("无效的 GitHub 连接请求。")
      const mode = "mode" in input ? input.mode : undefined
      if (mode !== undefined && !["local", "browser", "cancel"].includes(String(mode))) throw new GitHubConnectionError("无效的 GitHub 登录方式。")
      if (mode === "cancel") { stop(sender); return { status: "disconnected" } }
      if (busy.has(sender)) return { status: "authorizing", host: attempts.get(sender)?.target.url }
      busy.add(sender)
      acquired = true
      if (!watched.has(sender)) {
        watched.add(sender)
        event.sender.once("destroyed", () => { stop(sender); watched.delete(sender); epochs.delete(sender) })
      }
      if (attempts.get(sender)?.server !== input.server) stop(sender)
      const epoch = epochs.get(sender)
      const target = await connection(input.server)
      const server = input.server
      const checkTarget = async () => {
        if (event.sender.isDestroyed() || epochs.get(sender) !== epoch || JSON.stringify(await connection(server)) !== JSON.stringify(target)) {
          throw new GitHubConnectionError("研究宿主连接已变化，已取消本机凭据接入。")
        }
      }
      const previous = attempts.get(sender)
      if (previous && JSON.stringify(previous.target) !== JSON.stringify(target)) stop(sender)
      const current = attempts.get(sender)
      if (current) {
        const fresh = await prepare(target, current.abort.signal)
        if (!sameIdentity(current.identity, fresh)) { stop(sender); throw new GitHubConnectionError("研究宿主组织身份已变化，已取消本机 GitHub 授权。") }
        if (current.failed) { stop(sender); throw new GitHubConnectionError(current.error ?? "GitHub 授权未完成或已过期，请重试。") }
        if (current.done && !current.connected) {
          const signedIn = await localCommand("gh", ["api", "user", "--hostname", "github.com", "--jq", ".login"], current.abort.signal)
          if (signedIn?.trim().toLowerCase() !== current.identity.github_subject.toLowerCase()) {
            stop(sender)
            throw new GitHubConnectionError("浏览器授权的 GitHub 账号与组织名册不一致，未接入研究宿主。")
          }
          const token = await localCommand("gh", ["auth", "token", "--hostname", "github.com", "--user", current.identity.github_subject], current.abort.signal)
          if (!token) { stop(sender); throw new GitHubConnectionError("此电脑尚未保存组织账号的 GitHub 授权。") }
          const result = await connectCredential(target, current.identity, token.trim(), current.abort.signal, checkTarget)
          current.connected = true
          stop(sender)
          return result
        }
        return { status: "authorizing", code: current.code, url: "https://github.com/login/device", host: new URL(target.url).host }
      }
      const abort = new AbortController()
      const identity = await prepare(target, abort.signal)
      await checkTarget()
      if (!mode) {
        const result = await hostRequest(target, "/experimental/quantcode/github", abort.signal)
        if (result && typeof result === "object" && "status" in result && result.status === "connected" &&
          "subject" in result && typeof result.subject === "string" && result.subject.toLowerCase() === identity.github_subject.toLowerCase()) {
          return { status: "connected", subject: result.subject, host: new URL(target.url).host }
        }
        return { status: "disconnected", host: new URL(target.url).host }
      }
      const state: Attempt = { server: input.server, target, identity, abort, done: false, failed: false, connected: false,
        timer: setTimeout(() => { state.failed = true; state.abort.abort(); state.child?.kill("SIGKILL") }, 600000) }
      attempts.set(sender, state)
      if (mode === "local") {
        const token = await localCredential(identity.github_subject, abort.signal)
        const result = await connectCredential(target, identity, token, abort.signal, checkTarget)
        stop(sender)
        return result
      }
      const child = spawn("gh", ["auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--scopes", "read:org"], {
        cwd: app.getPath("userData"), env: { ...localEnvironment(), GH_BROWSER: process.platform === "win32" ? "cmd /c exit" : "true" },
        stdio: ["ignore", "ignore", "pipe"], windowsHide: true,
      })
      state.child = child
      let output = ""
      child.stderr.setEncoding("utf8")
      child.stderr.on("data", (chunk: string) => { output = (output + chunk).slice(-4096); state.code = output.match(/\b[A-Z0-9]{4}-[A-Z0-9]{4}\b/)?.[0] ?? state.code })
      child.once("error", () => {
        state.error = "无法启动此电脑的 GitHub CLI。请安装或修复 gh 后重试；不会使用远端宿主的账号代替。"
        state.failed = true; state.done = true
      })
      child.once("close", code => { state.failed ||= code !== 0; state.done = true })
      return { status: "authorizing", host: new URL(target.url).host, url: "https://github.com/login/device" }
    } catch (error) {
      stop(sender)
      return { status: "error", error: error instanceof GitHubConnectionError
        ? error.message : "GitHub 连接失败，请检查本机凭据、组织账号与研究宿主连接。" }
    } finally { if (acquired) busy.delete(sender) }
  })
}

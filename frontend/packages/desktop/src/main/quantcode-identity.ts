import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, win32 } from "node:path"
import { promisify } from "node:util"
import type { QuantCodeIdentityDisconnected, QuantCodeIdentityGroup, QuantCodeIdentityInspection, QuantCodeIdentitySession } from "@opencode-ai/app/identity"
import { researchEndpoint } from "./quantcode-connection"
import type { ResearchConnection } from "./quantcode-connection"

const execFileAsync = promisify(execFile)
const groups = new Set(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"])
let signing = false
export type IdentityOperationOptions = { signal?: AbortSignal; checkTarget?: () => Promise<void> }

export async function importKey(_input: ResearchConnection, filename: string) {
  if (!filename || filename.length > 4096) throw new Error("SSH 私钥路径无效。")
  await execFileAsync(executable("ssh-add"), [filename], { encoding: "utf8", timeout: 30000, maxBuffer: 65536, windowsHide: true })
  const derived = await execFileAsync(executable("ssh-keygen"), ["-y", "-f", filename], { encoding: "utf8", timeout: 10000, maxBuffer: 65536, windowsHide: true })
  const key = publicKey(derived.stdout.trim())
  return { fingerprint: key.fingerprint }
}

async function checkTarget(options: IdentityOperationOptions) {
  options.signal?.throwIfAborted()
  await options.checkTarget?.()
  options.signal?.throwIfAborted()
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("研究宿主返回了无效的身份数据。")
  return value as Record<string, unknown>
}

function string(value: unknown, max = 2048): string {
  if (typeof value !== "string" || !value.length || value.length > max || value.includes("\0")) throw new Error("研究宿主返回了无效的身份字段。")
  return value
}

function origin(value: string) {
  const url = new URL(value)
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" ||
      (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))) {
    throw new Error("请选择组织提供的 HTTPS 个人研究宿主，或本机回环连接。")
  }
  return url.origin
}

function serverConfiguration(input: ResearchConnection) {
  const value = object(input)
  if (Object.keys(value).some(key => !["url", "username", "password"].includes(key))) throw new Error("身份连接不接受业务组、身份或本机路径参数。")
  const url = string(value.url)
  researchEndpoint({ url }, "")
  return { url,
    ...(value.username == null || value.username === "" ? {} : { username: string(value.username, 256) }),
    ...(value.password == null || value.password === "" ? {} : { password: string(value.password, 4096) }) }
}

async function request(server: ResearchConnection, route: "identities" | "identity/challenge" | "identity/verify" | "identity/logout" | "session-context", body: unknown, options: IdentityOperationOptions): Promise<unknown> {
  await checkTarget(options)
  const endpoint = researchEndpoint(server, `/experimental/quantcode/${route === "session-context" ? "tool" : route}`)
  if (route === "session-context") endpoint.searchParams.set("tool", "session_context")
  const response = await fetch(endpoint, {
    method: body === undefined ? "GET" : "POST", redirect: "error",
    signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000),
    headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(server.password ? { Authorization: `Basic ${Buffer.from(`${server.username ?? "opencode"}:${server.password}`).toString("base64")}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }).catch(() => { throw new Error("无法连接个人研究宿主，请检查地址和网络。") })
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403
    ? "个人研究宿主拒绝连接，请检查宿主访问权限。" : "组织身份操作未完成，请重新连接。")
  const reader = response.body?.getReader()
  if (!reader) throw new Error("个人研究宿主没有返回身份数据。")
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      size += chunk.value.byteLength
      if (size > 65536) throw new Error("个人研究宿主返回的身份数据过大。")
      chunks.push(chunk.value)
    }
  } finally { await reader.cancel().catch(() => undefined) }
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8")) } catch { throw new Error("个人研究宿主返回了无效的身份数据。") }
}

function group(value: unknown): QuantCodeIdentityGroup {
  const name = string(value, 32)
  if (!groups.has(name)) throw new Error("组织身份的业务组无效。")
  return name as QuantCodeIdentityGroup
}

function authorizedGroups(value: unknown, current: QuantCodeIdentityGroup) {
  if (!Array.isArray(value) || !value.length || value.length > groups.size) throw new Error("组织身份的授权组无效。")
  const result = value.map(group)
  if (!result.includes(current)) throw new Error("组织身份未授权当前业务组。")
  return result
}

function session(value: unknown): QuantCodeIdentitySession {
  const data = object(value)
  const selected = group(data.group)
  const expires = string(data.expires_at, 64)
  if (data.status !== "connected" || data.execution_status !== "disconnected" || !Number.isFinite(Date.parse(expires)) || Date.parse(expires) <= Date.now()) throw new Error("组织身份尚未认证或已经过期。")
  const sessionID = string(data.session_id, 32)
  if (!/^[a-f0-9]{32}$/.test(sessionID)) throw new Error("组织身份会话无效。")
  return { status: "connected", actor_id: string(data.actor_id), session_id: sessionID,
    fingerprint: string(data.fingerprint, 128), group: selected, groups: authorizedGroups(data.groups, selected),
    expires_at: expires, execution_status: "disconnected" }
}

function publicKey(value: unknown) {
  const text = string(value, 16384).trim()
  if (/[\r\n]/.test(text) || text.includes("PRIVATE KEY")) throw new Error("研究宿主必须提供已登记的 SSH 公钥。")
  const [algorithm, encoded] = text.split(/\s+/)
  if (!/^(?:ssh-|ecdsa-|sk-)[A-Za-z0-9@._+-]+$/.test(algorithm ?? "") || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded ?? "")) throw new Error("SSH 公钥格式无效。")
  const bytes = Buffer.from(encoded, "base64")
  if (bytes.length < 5 || bytes.toString("base64").replace(/=+$/, "") !== encoded.replace(/=+$/, "") ||
      bytes.readUInt32BE(0) !== Buffer.byteLength(algorithm) || bytes.subarray(4, 4 + bytes.readUInt32BE(0)).toString() !== algorithm) throw new Error("SSH 公钥内容无效。")
  return { text: `${algorithm} ${encoded}`, fingerprint: `SHA256:${createHash("sha256").update(bytes).digest("base64").replace(/=+$/, "")}` }
}

function executable(name: "ssh-add" | "ssh-keygen") {
  if (process.platform !== "win32") return `/usr/bin/${name}`
  const root = process.env.SystemRoot
  if (!root || !win32.isAbsolute(root)) throw new Error("无法定位系统 OpenSSH，请检查 Windows OpenSSH 安装。")
  return win32.join(root, "System32", "OpenSSH", `${name}.exe`)
}

/** Internal only: never expose arbitrary challenge signing through an IPC. */
async function signChallenge(value: unknown, deadline: number, options: IdentityOperationOptions, selectedGroup?: QuantCodeIdentityGroup) {
  const data = object(value)
  const id = string(data.challenge_id, 32)
  if (!/^[a-f0-9]{32}$/.test(id) || typeof data.ttl_seconds !== "number" || !Number.isInteger(data.ttl_seconds) || data.ttl_seconds < 1 || data.ttl_seconds > 60) throw new Error("登录挑战无效，请重新连接。")
  origin(string(data.gateway_origin))
  const key = publicKey(data.public_key)
  if (key.fingerprint !== data.fingerprint) throw new Error("研究宿主的 SSH 公钥指纹不匹配。")
  const nonce = string(data.nonce, 8192)
  let decoded: unknown
  try { decoded = JSON.parse(nonce) } catch { throw new Error("登录挑战不属于 QuantCode 身份认证。") }
  const challenge = object(decoded)
  if (Object.keys(challenge).sort().join(",") !== "group,nonce,purpose" || challenge.purpose !== "quantcode-login" ||
      !/^[A-Za-z0-9_-]{32,256}$/.test(string(challenge.nonce, 256))) throw new Error("登录挑战不属于 QuantCode 身份认证。")
  group(challenge.group)
  if (selectedGroup && challenge.group !== selectedGroup) throw new Error("研究宿主尚未支持所选工作组，请联系管理员更新宿主。")
  const expires = Math.min(deadline, Date.now() + data.ttl_seconds * 1000)
  await checkTarget(options)
  const identities = await execFileAsync(executable("ssh-add"), ["-L"], { encoding: "utf8", timeout: 10000, maxBuffer: 262144, windowsHide: true, signal: options.signal })
    .catch(() => { throw new Error("本机 SSH agent 不可用或没有身份，请先在系统 SSH agent 中加载已登记的密钥。") })
  if (!identities.stdout.split(/\r?\n/).some(line => {
    if (!line.trim()) return false
    try { return publicKey(line).text === key.text } catch { return false }
  })) throw new Error("本机 SSH agent 中没有该个人研究宿主登记的公钥，请检查宿主或加载对应密钥。")
  const temporary = await mkdtemp(join(tmpdir(), "quantcode-identity-"))
  try {
    await chmod(temporary, 0o700)
    const keyFile = join(temporary, "identity.pub")
    const challengeFile = join(temporary, "challenge")
    await writeFile(keyFile, key.text, { mode: 0o600, flag: "wx" })
    await writeFile(challengeFile, nonce, { mode: 0o600, flag: "wx" })
    await checkTarget(options)
    if (Date.now() >= expires) throw new Error("登录挑战已过期，请重新连接。")
    // -U forces SSH agent use. No private-key file, shell command, namespace,
    // command options or remote URL can be supplied by the renderer.
    await execFileAsync(executable("ssh-keygen"), ["-Y", "sign", "-U", "-f", keyFile, "-n", "quantcode", challengeFile], {
      encoding: "utf8", timeout: Math.min(30000, expires - Date.now()), maxBuffer: 65536, windowsHide: true, signal: options.signal,
      env: { ...process.env, SSH_ASKPASS_REQUIRE: "never" },
    }).catch(() => { throw new Error("本机 SSH agent 未完成签名，请检查密钥授权后重试。") })
    const signature = await readFile(`${challengeFile}.sig`, "utf8")
    if (Date.now() >= expires || signature.length > 16384 || !/^-----BEGIN SSH SIGNATURE-----\r?\n[A-Za-z0-9+/=\r\n]+\r?\n-----END SSH SIGNATURE-----\r?\n?$/.test(signature)) throw new Error("SSH 登录签名无效或已过期，请重新连接。")
    return { challenge_id: id, signature, fingerprint: key.fingerprint }
  } finally { await rm(temporary, { recursive: true, force: true }) }
}

export async function inspect(input: ResearchConnection, options: IdentityOperationOptions = {}): Promise<QuantCodeIdentityInspection> {
  const data = object(await request(serverConfiguration(input), "identities", undefined, options))
  if (typeof data.error === "string") throw new Error(data.error.slice(0, 512))
  if (!Array.isArray(data.identities)) throw new Error("个人研究宿主的身份配置无效。")
  const identities: QuantCodeIdentityInspection["identities"] = data.identities.map(item => {
    const value = object(item)
    const selected = group(value.group)
    return { id: string(value.id), label: string(value.label), fingerprint: string(value.fingerprint, 128),
      host: string(value.host), user: string(value.user), group: selected, groups: authorizedGroups(value.groups, selected) }
  })
  const result = { identities, session: data.session ? session(data.session) : null }
  await checkTarget(options)
  return result
}

export async function connect(input: ResearchConnection, options: IdentityOperationOptions = {}, identityId?: string, selectedGroup?: QuantCodeIdentityGroup): Promise<QuantCodeIdentitySession> {
  if (signing) throw new Error("已有 SSH 身份连接正在进行，请稍候。")
  const server = serverConfiguration(input)
  signing = true
  try {
    const deadline = Date.now() + 60000
    const challenge = await request(server, "identity/challenge", { ...(identityId ? { identity_id: identityId } : {}),
      ...(selectedGroup ? { group: group(selectedGroup) } : {}) }, options)
    const signed = await signChallenge(challenge, deadline, options, selectedGroup)
    await checkTarget(options)
    const result = await request(server, "identity/verify", { challenge_id: signed.challenge_id, signature: signed.signature }, options)
      .then(session).catch(() => { throw new Error("认证结果尚未确认，请刷新该研究宿主的登录状态；如已连接，可明确退出。") })
    if (result.fingerprint !== signed.fingerprint) throw new Error("已认证身份与本机签名身份不匹配，请退出后重新连接。")
    await checkTarget(options).catch(() => { throw new Error("身份已认证，但窗口或连接已变化。请刷新原研究宿主的登录状态；取消不会自动退出。") })
    return result
  } finally { signing = false }
}

export async function disconnect(input: ResearchConnection, options: IdentityOperationOptions = {}): Promise<QuantCodeIdentityDisconnected> {
  if (signing) throw new Error("SSH 身份连接仍在进行，请完成后退出。")
  const server = serverConfiguration(input)
  signing = true
  try {
    const result = object(await request(server, "identity/logout", {}, options))
    if (result.status !== "disconnected") throw new Error("研究宿主未确认身份退出，请重试。")
    await checkTarget(options)
    return { status: "disconnected", execution_status: "disconnected" }
  } finally { signing = false }
}

/** Admin routing never promotes a Linux username/group into an application role. */
export async function requireAdminSession(input: ResearchConnection, expected: QuantCodeIdentitySession, options: IdentityOperationOptions = {}) {
  const context = object(await request(serverConfiguration(input), "session-context", undefined, options))
  if (context.session_id !== expected.session_id || context.actor_id !== expected.actor_id || context.group !== expected.group) {
    throw new Error("组织管理身份已变化，请重新登录。")
  }
  if (context.role !== "admin") throw new Error("这把公钥尚未被组织名册授权为管理员，不能进入组织管理。")
}

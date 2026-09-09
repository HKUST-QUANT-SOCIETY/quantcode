import { lstat, mkdir, open, realpath, rename, unlink } from "node:fs/promises"
import { constants } from "node:fs"
import { createHash, randomUUID } from "node:crypto"
import { dirname, isAbsolute, join } from "node:path"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { z } from "zod"
import { readHostFile, readPrivateFile } from "@/quantcode/private-file"

const execFileAsync = promisify(execFile)
const groupSchema = z.enum(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"])
const rosterSchema = z.object({ group: groupSchema, groups: z.array(groupSchema).min(1) })
const sessionSchema = z.object({
  session_id: z.string().regex(/^[a-f0-9]{32}$/), actor_id: z.string().min(1), group: groupSchema,
  role: z.enum(["analyst", "approver", "admin"]), workspace_id: z.string().min(1), workspace_path: z.string().min(1),
  resource_scopes: z.array(z.string()), authorized_groups: z.array(groupSchema).default([]),
  issued_at: z.string().datetime({ offset: true }), expires_at: z.string().datetime({ offset: true }),
  identity_source: z.literal("ssh_roster"), github_subject: z.string().nullable().optional(),
})
const credentialSchema = z.object({ gateway: z.string(), token: z.string().regex(/^[A-Za-z0-9_-]{32,512}$/), fingerprint: z.string().optional() }).strict()
const pendingChallenges = new Map<string, { configuration: string; credential: string | null; expires: number; key: string; fingerprint: string }>()

function gatewayOrigin(input: string) {
  const url = new URL(input)
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" ||
      (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))) {
    throw new Error("组织身份服务需要 HTTPS 地址或本机回环地址。")
  }
  return url.origin
}

async function configuration() {
  const publicKey = process.env.QUANTCODE_PUBLIC_KEY_FILE
  const publicKeys = [...new Set([publicKey, ...(process.env.QUANTCODE_PUBLIC_KEY_FILES ?? "").split(",").map(value => value.trim())]
    .filter((value): value is string => typeof value === "string" && value.length > 0))]
  const session = process.env.QUANTCODE_IDENTITY_SESSION_FILE
  const gateway = process.env.QUANTCODE_GATEWAY_URL
  if (!publicKeys.length || !session || !gateway) throw new Error("请连接组织为你提供的个人研究宿主；该宿主尚未配置组织身份连接。")
  if (!publicKeys.length || !publicKeys.every(isAbsolute) || !isAbsolute(session)) throw new Error("研究宿主的身份配置无效，请联系管理员。")
  const keys = await Promise.all(publicKeys.map(async file => {
    const key = (await readHostFile(file, 16384).catch(() => { throw new Error("研究宿主无法安全读取已登记的 SSH 公钥。") })).trim()
    const [algorithm, encoded] = key.split(/\s+/)
    if (Buffer.byteLength(key) > 16384 || key.includes("PRIVATE KEY") || /[\r\n]/.test(key) ||
      !/^(?:ssh-|ecdsa-|sk-)[A-Za-z0-9@._+-]+$/.test(algorithm ?? "") || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded ?? "")) throw new Error("研究宿主的 SSH 公钥无效。")
    const bytes = Buffer.from(encoded, "base64")
    if (bytes.length < 5 || bytes.toString("base64").replace(/=+$/, "") !== encoded.replace(/=+$/, "") || bytes.readUInt32BE(0) !== Buffer.byteLength(algorithm) || bytes.subarray(4, 4 + bytes.readUInt32BE(0)).toString() !== algorithm) throw new Error("研究宿主的 SSH 公钥无效。")
    return { publicKey: file, key: `${algorithm} ${encoded}`, fingerprint: `SHA256:${createHash("sha256").update(bytes).digest("base64").replace(/=+$/, "")}` }
  }))
  const result = { publicKey, publicKeys, session, gateway: gatewayOrigin(gateway), keys }
  return { ...result, key: keys[0].key, fingerprint: keys[0].fingerprint, digest: createHash("sha256").update(JSON.stringify(result)).digest("hex") }
}

class GatewayError extends Error {
  constructor(readonly status: number) { super("组织身份服务拒绝了请求，请检查个人研究宿主和 SSH 登记。") }
}

async function request(gateway: string, route: "/auth/identity" | "/auth/challenge" | "/auth/verify" | "/auth/logout" | "/session", payload?: unknown, token?: string): Promise<unknown> {
  const response = await fetch(new URL(route, gatewayOrigin(gateway)), {
    method: payload === undefined ? "GET" : "POST", redirect: "error", signal: AbortSignal.timeout(15000),
    headers: { ...(payload === undefined ? {} : { "Content-Type": "application/json" }), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  }).catch(() => { throw new Error("暂时无法连接组织身份服务，请稍后重试。") })
  if (!response.ok) throw new GatewayError(response.status)
  // Gateway responses contain credentials. Raw bodies and parse exceptions
  // must not be released to the renderer or process logs.
  const raw = await response.text()
  if (Buffer.byteLength(raw) > 65536) throw new Error("组织身份服务返回的数据过大。")
  try { return JSON.parse(raw) } catch { throw new Error("组织身份服务返回了无效数据。") }
}

async function credential(filename: string) {
  const exists = await lstat(filename).then(() => true).catch(error => {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false
    throw new Error("无法读取研究宿主的私有身份记录。")
  })
  if (!exists) return null
  const raw = await readPrivateFile(filename).catch(() => { throw new Error("研究宿主无法安全读取私有身份记录，请联系管理员。") })
  let value: unknown
  try { value = JSON.parse(raw) } catch { throw new Error("研究宿主的私有身份记录损坏，请联系管理员。") }
  const parsed = credentialSchema.safeParse(value)
  if (!parsed.success) throw new Error("研究宿主的私有身份记录损坏，请联系管理员。")
  return { ...parsed.data, gateway: gatewayOrigin(parsed.data.gateway), digest: createHash("sha256").update(raw).digest("hex") }
}

function summary(context: z.infer<typeof sessionSchema>, fingerprint: string) {
  if (Date.parse(context.expires_at) <= Date.now() || context.authorized_groups.length && !context.authorized_groups.includes(context.group)) throw new Error("组织身份已过期，请重新登录。")
  return { status: "connected" as const, actor_id: context.actor_id, session_id: context.session_id, fingerprint,
    group: context.group, groups: context.authorized_groups.length ? context.authorized_groups : [context.group],
    expires_at: context.expires_at, execution_status: "disconnected" as const }
}

async function assertConfiguration(digest: string) {
  if ((await configuration()).digest !== digest) throw new Error("研究宿主的身份配置已变化，请重新连接。")
}

/** Authentication inspection is independent of Python, MCP and execution. */
export async function localIdentity() {
  const config = await configuration()
  const identities = await Promise.all(config.keys.map(async key => {
    const roster = rosterSchema.parse(await request(config.gateway, "/auth/identity", { public_key: key.key }))
    if (!roster.groups.includes(roster.group)) throw new Error("组织身份服务返回了无效的业务组。")
    return { id: key.fingerprint, label: `已登记的 SSH 身份 · ${key.fingerprint}`, fingerprint: key.fingerprint,
      host: new URL(config.gateway).host, user: "SSH agent", ...roster }
  }))
  const record = await credential(config.session)
  const context = record?.gateway === config.gateway
    ? await request(record.gateway, "/session", undefined, record.token).then(value => sessionSchema.parse(value)).catch(error => {
      if (error instanceof GatewayError && error.status === 401) return null
      throw error
    }) : null
  const result = { identities,
    session: context ? summary(context, record?.fingerprint ?? config.fingerprint) : null }
  await assertConfiguration(config.digest)
  if ((await credential(config.session))?.digest !== record?.digest) throw new Error("登录身份正在变化，请刷新。")
  return result
}

/** Only the host's configured public key and authority enter this challenge.
 * The caller cannot supply group, actor, key, workspace, path or gateway. */
export async function createIdentityChallenge(identityId?: string) {
  const config = await configuration()
  const selected = config.keys.find(key => key.fingerprint === identityId) ?? (identityId ? undefined : config.keys[0])
  if (!selected) throw new Error("请选择当前研究宿主登记的 SSH 公钥身份。")
  for (const [id, pending] of pendingChallenges) if (pending.expires <= Date.now()) pendingChallenges.delete(id)
  if (pendingChallenges.size >= 32) throw new Error("登录请求过多，请稍后重试。")
  // A prior interrupted commit retains its token in a known private file so
  // it can be revoked before another login, rather than becoming an orphan.
  await revokeFile(`${config.session}.pending`)
  const prior = await credential(config.session)
  const started = Date.now()
  const result = z.object({ challenge_id: z.string().regex(/^[a-f0-9]{32}$/), nonce: z.string().min(1).max(8192),
    ttl_seconds: z.number().int().positive().max(60), group: groupSchema, groups: z.array(groupSchema) }).parse(
    await request(config.gateway, "/auth/challenge", { public_key: selected.key }))
  await assertConfiguration(config.digest)
  pendingChallenges.set(result.challenge_id, { configuration: config.digest, credential: prior?.digest ?? null,
    expires: started + result.ttl_seconds * 1000, key: selected.key, fingerprint: selected.fingerprint })
  return { challenge_id: result.challenge_id, public_key: selected.key, fingerprint: selected.fingerprint,
    nonce: result.nonce, ttl_seconds: result.ttl_seconds, gateway_origin: config.gateway }
}

async function writeCredential(filename: string, value: { gateway: string; token: string; fingerprint?: string }) {
  const directory = dirname(filename)
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const info = await lstat(directory)
  if (!info.isDirectory() || info.isSymbolicLink() || process.platform !== "win32" &&
      (info.mode & 0o022 || process.getuid && info.uid !== process.getuid())) throw new Error("研究宿主的身份目录必须归当前账户所有，且其他账户不可写入。")
  const canonical = await realpath(directory)
  const temporary = join(canonical, `.identity-${randomUUID()}`)
  const handle = await open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0), 0o600)
  try {
    await handle.writeFile(JSON.stringify(value), "utf8")
    await handle.sync()
    const current = await lstat(directory)
    if (current.dev !== info.dev || current.ino !== info.ino || await realpath(directory) !== canonical) throw new Error("身份目录发生变化，未更新登录记录。")
    await rename(temporary, filename)
  } finally {
    await handle.close()
    await unlink(temporary).catch(error => { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error })
  }
}

async function revokeFile(filename: string) {
  const record = await credential(filename)
  if (!record) return
  const result = z.object({ ok: z.literal(true) }).safeParse(await request(record.gateway, "/auth/logout", {}, record.token))
  if (!result.success) throw new Error("组织身份服务未确认退出，已保留私有记录以便重试。")
  if ((await credential(filename))?.digest !== record.digest) throw new Error("退出期间身份记录发生变化，请重试。")
  await unlink(filename)
}

/** Called under the existing host identityOperation semaphore. It authenticates
 * one member only; successful identity verification is not execution readiness. */
export async function verifyIdentityChallenge(payload: { challenge_id: string; signature: string }) {
  const input = z.object({ challenge_id: z.string().regex(/^[a-f0-9]{32}$/),
    signature: z.string().max(16384).regex(/^-----BEGIN SSH SIGNATURE-----\r?\n[A-Za-z0-9+/=\r\n]+\r?\n-----END SSH SIGNATURE-----\r?\n?$/) }).strict().parse(payload)
  const pending = pendingChallenges.get(input.challenge_id)
  pendingChallenges.delete(input.challenge_id)
  const config = await configuration()
  if (!pending || pending.expires <= Date.now() || pending.configuration !== config.digest ||
      ((await credential(config.session))?.digest ?? null) !== pending.credential) throw new Error("登录挑战已失效，请重新连接。")
  // Another valid challenge may remain after a failed credential commit. Do
  // not overwrite that commit's staged token with a newly issued credential.
  await revokeFile(`${config.session}.pending`)
  await assertConfiguration(config.digest)
  if (!config.keys.some(key => key.key === pending.key && key.fingerprint === pending.fingerprint)) throw new Error("所选 SSH 公钥已从研究宿主配置中移除，请重新选择。")
  const verified = await request(config.gateway, "/auth/verify", { ...input, public_key: pending.key })
  const parsed = z.object({ token: credentialSchema.shape.token, session: sessionSchema }).safeParse(verified)
  if (!parsed.success) throw new Error("组织身份服务未返回有效的登录结果。")
  const staged = `${config.session}.pending`
  // Stage the newly issued token before revoking the previous one. A later
  // failure leaves an explicitly recoverable credential, never a second user.
  await writeCredential(staged, { gateway: config.gateway, token: parsed.data.token, fingerprint: pending.fingerprint }).catch(async () => {
    await request(config.gateway, "/auth/logout", {}, parsed.data.token)
    throw new Error("无法保存研究宿主的私有身份记录，登录未完成。")
  })
  await assertConfiguration(config.digest)
  const current = sessionSchema.parse(await request(config.gateway, "/session", undefined, parsed.data.token))
  if (JSON.stringify(current) !== JSON.stringify(parsed.data.session)) throw new Error("组织身份在登录期间发生变化，请重试。")
  const result = summary(current, pending.fingerprint)
  if (((await credential(config.session))?.digest ?? null) !== pending.credential) throw new Error("登录期间已有另一份身份记录，请重试。")
  await revokeFile(config.session)
  await assertConfiguration(config.digest)
  await rename(staged, config.session)
  pendingChallenges.clear()
  return result
}

/** Development/legacy local-host path only. Desktop remote login uses the
 * challenge bridge, which never asks a remote SSH agent to sign for the user. */
export async function signInLocalIdentity(group?: string) {
  if (group !== undefined) throw new Error("业务组由组织身份自动绑定，不接受组选项。")
  const config = await configuration()
  const python = process.env.QUANTCODE_HOST_PYTHON
  const root = process.env.QUANTCODE_BACKEND_ROOT
  if (!python || !root || !isAbsolute(python) || !isAbsolute(root)) throw new Error("请在 QuantCode 桌面端使用本机 SSH 身份连接。")
  pendingChallenges.clear()
  await revokeFile(`${config.session}.pending`)
  const result = await execFileAsync(python, ["-m", "quantcode.identity_login", "--gateway", config.gateway,
    "--public-key", config.keys[0].publicKey, "--session-file", config.session], {
    cwd: root, encoding: "utf8", timeout: 60000, killSignal: "SIGKILL", maxBuffer: 65536, windowsHide: true,
  }).catch(() => { throw new Error("身份操作失败，请检查 SSH agent 和组织登记。") })
  const context = z.object({ actor_id: z.string().min(1), session_id: z.string().min(1), group: groupSchema,
    groups: z.array(groupSchema), expires_at: z.string() }).parse(JSON.parse(result.stdout))
  return { status: "connected" as const, ...context, fingerprint: config.fingerprint, execution_status: "disconnected" as const }
}

export async function signOutLocalIdentity() {
  const config = await configuration()
  pendingChallenges.clear()
  await revokeFile(`${config.session}.pending`)
  await revokeFile(config.session)
  return { status: "disconnected" as const, execution_status: "disconnected" as const }
}

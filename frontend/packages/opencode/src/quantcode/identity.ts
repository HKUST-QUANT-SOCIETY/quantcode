import { readPrivateFile } from "./private-file"
import { isAbsolute } from "node:path"
import { createHash } from "node:crypto"
import { z } from "zod"

// Host-only migration switch. Product/channel selection alone must not activate
// an incomplete ownership migration or make existing sessions inaccessible.
// Remove the switch only after the M1–M4 final acceptance sequence succeeds.
export const enabled = () => process.env.OPENCODE_CHANNEL === "quantcode" && process.env.QUANTCODE_UNIFIED_RUNTIME === "1"

const identitySchema = z.object({
  session_id: z.string().min(1),
  actor_id: z.string().min(1),
  group: z.enum(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"]),
  role: z.enum(["analyst", "approver", "admin"]),
  workspace_id: z.string().min(1),
  workspace_path: z.string().min(1),
  github_subject: z.string().nullable().optional(),
  resource_scopes: z.array(z.string()),
  authorized_groups: z.array(z.string()).default([]),
  issued_at: z.string().datetime({ offset: true }),
  expires_at: z.string().datetime({ offset: true }),
  identity_source: z.literal("ssh_roster"),
})
export type Identity = z.infer<typeof identitySchema>
export type Owner = Pick<Identity, "actor_id" | "group" | "role" | "workspace_id" | "workspace_path" | "github_subject" | "resource_scopes">
export type SessionBinding = { version: 1; engine: "quantcode"; owner: Owner; parent_session_id?: string; root_session_id: string }

const bindingSchema = z.object({
  version: z.literal(1),
  engine: z.literal("quantcode"),
  owner: identitySchema.pick({ actor_id: true, group: true, role: true, workspace_id: true, workspace_path: true, github_subject: true, resource_scopes: true }),
  parent_session_id: z.string().optional(),
  root_session_id: z.string().min(1),
})

export class IdentityError extends Error {
  constructor(message = "QuantCode 身份已失效，请重新登录。") {
    super(message)
    this.name = "QuantCodeIdentityError"
  }
}

async function credential() {
  const filename = process.env.QUANTCODE_IDENTITY_SESSION_FILE
  if (!filename || !isAbsolute(filename)) throw new IdentityError("请先配置并登录 QuantCode 组织身份。")
  const raw = await readPrivateFile(filename).catch(() => { throw new IdentityError("无法读取 QuantCode 私有身份文件。") })
  const parsed = z.object({ gateway: z.string().url(), token: z.string().min(1).max(512) }).safeParse(JSON.parse(raw))
  if (!parsed.success) throw new IdentityError("QuantCode 身份文件无效。")
  const url = new URL(parsed.data.gateway)
  if (url.username || url.password || url.search || url.hash ||
    (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))) {
    throw new IdentityError("QuantCode 身份服务需要 HTTPS 或本机回环连接。")
  }
  return { ...parsed.data, digest: createHash("sha256").update(raw).digest("hex") }
}

/** Always validate with the authority. Cached display state is never an execution grant. */
export async function currentIdentity(): Promise<Identity> {
  const record = await credential().catch(() => { throw new IdentityError() })
  const response = await fetch(new URL("/session", record.gateway), {
    headers: { Authorization: `Bearer ${record.token}` },
    redirect: "error", signal: AbortSignal.timeout(10000),
  }).catch(() => { throw new IdentityError("QuantCode 身份服务暂不可用，无法验证当前权限。") })
  if (!response.ok) throw new IdentityError()
  const parsed = identitySchema.safeParse(await response.json())
  if (!parsed.success || Date.parse(parsed.data.expires_at) <= Date.now() ||
    (parsed.data.authorized_groups.length && !parsed.data.authorized_groups.includes(parsed.data.group))) throw new IdentityError()
  // A logout/relogin while the authority was responding must not release the old identity.
  if ((await credential()).digest !== record.digest) throw new IdentityError("登录身份正在变化，请重试。")
  return parsed.data
}

/** Host-only gateway transport. Callers select a fixed organization endpoint;
 * credentials stay in this module and are rechecked before releasing data. */
export async function gatewayRequest(endpoint: "publish" | "read" | "decide" | "list" | "cancel" | "tasks.publish" | "tasks.read" | "tasks.list" | "artifacts.publish" | "artifacts.list" | "artifacts.read" | "reviews.authorize", payload: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
  const current = await currentIdentity()
  if (typeof payload.expected_session_id === "string" && payload.expected_session_id !== current.session_id) throw new IdentityError("审批请求所属登录已变化。")
  const record = await credential()
  const verified = await currentIdentity()
  if (verified.session_id !== current.session_id || (await credential()).digest !== record.digest) throw new IdentityError("审批请求期间登录身份已变化。")
  const route = endpoint === "reviews.authorize" ? "/native-reviews/authorize" : endpoint.startsWith("tasks.") ? `/native-tasks/${endpoint.slice(6)}`
    : endpoint.startsWith("artifacts.") ? `/native-tasks/artifacts/${endpoint.slice(10)}` : `/native-gates/${endpoint}`
  const response = await fetch(new URL(route, record.gateway), {
    method: "POST", headers: { Authorization: `Bearer ${record.token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, expected_session_id: current.session_id }), redirect: "error",
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
  })
  if (!response.ok) throw new IdentityError(`组织服务拒绝请求（${response.status}），请刷新当前任务和身份。`)
  const result: unknown = await response.json()
  if ((await credential()).digest !== record.digest) throw new IdentityError("请求期间登录身份已变化。")
  return result
}

export function ownerOf(identity: Identity): Owner {
  return { actor_id: identity.actor_id, group: identity.group, role: identity.role,
    workspace_id: identity.workspace_id, workspace_path: identity.workspace_path,
    github_subject: identity.github_subject ?? null, resource_scopes: [...identity.resource_scopes].sort() }
}

export function sessionBinding(metadata?: Record<string, unknown>): SessionBinding | undefined {
  const parsed = bindingSchema.safeParse(metadata?.quantcode)
  return parsed.success ? parsed.data : undefined
}

export function owns(binding: SessionBinding | undefined, identity: Identity): boolean {
  if (!binding) return false
  const owner = binding.owner
  const current = ownerOf(identity)
  return owner.actor_id === current.actor_id && owner.group === current.group && owner.role === current.role &&
    owner.workspace_id === current.workspace_id && owner.workspace_path === current.workspace_path &&
    (owner.github_subject ?? null) === current.github_subject &&
    JSON.stringify([...new Set(owner.resource_scopes)].sort()) === JSON.stringify([...new Set(current.resource_scopes)].sort())
}

export function requireOwner(metadata: Record<string, unknown> | undefined, identity: Identity): SessionBinding {
  const binding = sessionBinding(metadata)
  if (!owns(binding, identity)) throw new IdentityError(binding
    ? "当前身份无权继续此任务，或任务创建后的权限已变化。"
    : "此记录属于旧执行器，需从历史兼容入口查看，不能直接作为新任务继续。")
  return binding!
}

export function bindSession(identity: Identity, sessionID: string, parent?: { id: string; metadata?: Record<string, unknown> }): SessionBinding {
  if (parent) requireEditable(parent.metadata)
  const inherited = parent ? requireOwner(parent.metadata, identity) : undefined
  return { version: 1, engine: "quantcode", owner: ownerOf(identity),
    parent_session_id: parent?.id, root_session_id: inherited?.root_session_id ?? sessionID }
}

/** Caller metadata is descriptive only. The ownership binding is host-created and immutable. */
export function preserveBinding(current: Record<string, unknown> | undefined, incoming?: Record<string, unknown>) {
  const metadata = { ...incoming }
  delete metadata.quantcode
  delete metadata.quantcode_legacy_import
  if (current?.quantcode) metadata.quantcode = current.quantcode
  if (current?.quantcode_legacy_import) metadata.quantcode_legacy_import = current.quantcode_legacy_import
  return metadata
}

export function readOnly(metadata?: Record<string, unknown>) {
  return metadata?.quantcode_legacy_import !== undefined
}

export function requireEditable(metadata?: Record<string, unknown>) {
  if (readOnly(metadata)) throw new IdentityError("这份归档任务仅供查看，不能继续执行、修改历史或派生任务。")
}

export * as QuantCodeIdentity from "./identity"

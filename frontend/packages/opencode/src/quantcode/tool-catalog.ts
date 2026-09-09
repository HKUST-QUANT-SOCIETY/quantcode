import path from "node:path"
import { createHash } from "node:crypto"
import { lstat } from "node:fs/promises"
import { z } from "zod"
import { Global } from "@opencode-ai/core/global"
import type { Identity } from "./identity"
import { readPrivateFile } from "./private-file"

const hash = z.string().regex(/^[a-f0-9]{64}$/)
const group = z.enum(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"])
const pointer = z.string().regex(/^\/(?:[^/~]|~[01])+(?:\/(?:[^/~]|~[01])+)*$/)
export const entrySchema = z.object({
  server: z.string().min(1), tool: z.string().min(1),
  server_config_hash: hash, input_schema_hash: hash,
  effect: z.enum(["read", "personal_write", "shared_write", "restricted_access", "production", "legacy_executor"]),
  groups: z.array(group).min(1), roles: z.array(z.enum(["analyst", "approver", "admin"])).min(1),
  resource_scopes: z.array(z.string().min(1)).default([]),
  path_arguments: z.array(pointer).default([]),
  resource: z.object({ prefix: z.string().min(1), key_argument: pointer, version_argument: pointer, key_pattern: z.string().min(1) }).strict().optional(),
  purpose: z.enum(["ordinary", "capability_catalog", "group_memory"]).default("ordinary"),
  capability_id: z.string().min(1).optional(),
  status: z.enum(["published", "disabled"]),
}).strict()
const contentSchema = z.object({ server: z.string().min(1), server_config_hash: hash,
  kind: z.enum(["resource", "resource_template", "prompt"]), selector: z.string().min(1),
  groups: z.array(group).min(1), roles: z.array(z.enum(["analyst", "approver", "admin"])).min(1),
  resource_scopes: z.array(z.string().min(1)).default([]), status: z.enum(["published", "disabled"]),
}).strict()
export const releaseSchema = z.object({ version: z.literal(1), release: z.string().min(1),
  published_at: z.string().datetime({ offset: true }), tools: z.array(entrySchema),
  content: z.array(contentSchema).default([]),
}).strict()
export type Entry = z.infer<typeof entrySchema>
export type Origin = { server: string; tool: string; config: unknown; schema: unknown; current?: () => boolean }
export type Admission = { release: string; digest: string; entry: Entry }

export function visible(entry: Entry, identity: Identity) {
  return entry.status === "published" && entry.groups.includes(identity.group) && entry.roles.includes(identity.role) &&
    entry.resource_scopes.every(scope => identity.resource_scopes.includes(scope)) &&
    !["production", "legacy_executor"].includes(entry.effect)
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]))
  return value
}
export function digest(value: unknown) {
  return createHash("sha256").update(JSON.stringify(canonical(value)) ?? "null").digest("hex")
}

/** Releases are read from a host-private file outside model-writable roots.
 * Publishing is a maintainer action. Remote annotations are not authority. */
export async function load() {
  const filename = process.env.QUANTCODE_TOOL_CATALOG_FILE ?? path.join(Global.Path.config, "tool-catalog.json")
  const exists = await lstat(filename).catch((error: NodeJS.ErrnoException) => { if (error.code === "ENOENT") return undefined; throw error })
  if (!exists) return undefined
  const release = releaseSchema.parse(JSON.parse(await readPrivateFile(filename, 2_000_000)))
  const unique = new Set<string>()
  for (const entry of release.tools) {
    const key = JSON.stringify([entry.server, entry.tool])
    if (unique.has(key)) throw new Error("工具目录含重复定义，不能按顺序猜测权限。")
    unique.add(key)
    if (entry.purpose !== "ordinary" && entry.effect !== "read") throw new Error("检索证据工具必须为已审核的只读工具。")
    if (entry.effect === "personal_write" && entry.path_arguments.length === 0) throw new Error("写入工具未声明实际文件参数。")
    if (entry.effect === "shared_write" && entry.status === "published" && !entry.resource) throw new Error("共享写入工具未声明精确资源与版本参数。")
    if (entry.resource) new RegExp(entry.resource.key_pattern)
  }
  return release
}

export async function allowed(origin: Origin, identity: Identity): Promise<Admission | undefined> {
  if (origin.current && !origin.current()) return
  const release = await load()
  const entry = release?.tools.find(item => item.server === origin.server && item.tool === origin.tool)
  if (!release || !entry || !visible(entry, identity)) return
  if (entry.server_config_hash !== digest(origin.config) || entry.input_schema_hash !== digest(origin.schema)) return
  return { release: release.release, digest: digest({ release: release.release, entry }), entry }
}

export async function revalidate(origin: Origin, identity: Identity, admitted: Admission) {
  const current = await allowed(origin, identity)
  if (!current || current.digest !== admitted.digest) throw new Error("工具发布版本或权限已变化，请刷新当前工具目录。")
  return current
}

/** Remote resources and prompt templates are a separate MCP surface. Exact
 * selectors are reviewed explicitly; a template does not grant its expansions. */
export async function content(server: string, config: unknown, kind: "resource" | "resource_template" | "prompt", identity: Identity) {
  const release = await load()
  const entries = release?.content.filter(entry => entry.server === server && entry.kind === kind &&
    entry.server_config_hash === digest(config) && entry.status === "published" && entry.groups.includes(identity.group) &&
    entry.roles.includes(identity.role) && entry.resource_scopes.every(scope => identity.resource_scopes.includes(scope))) ?? []
  return { selectors: new Set(entries.map(entry => entry.selector)), digest: digest({ release: release?.release, entries }) }
}

function at(pointer: string, args: unknown): unknown {
  let value: unknown = args
  for (const segment of pointer.slice(1).split("/").map(part => part.replaceAll("~1", "/").replaceAll("~0", "~"))) {
    if (!value || typeof value !== "object" || !Object.hasOwn(value, segment)) throw new Error("工具缺少声明的资源参数。")
    value = (value as Record<string, unknown>)[segment]
  }
  return value
}

export function resource(entry: Entry, args: unknown) {
  if (!entry.resource) throw new Error("工具未声明资源版本契约。")
  const key = at(entry.resource.key_argument, args)
  const version = at(entry.resource.version_argument, args)
  if (typeof key !== "string" || key.length > 2048 || !new RegExp(entry.resource.key_pattern).test(key) ||
      typeof version !== "number" || !Number.isSafeInteger(version) || version < 0) throw new Error("共享写入需要规范资源标识和明确的预期版本。")
  return { resource: entry.resource.prefix + key, version: String(version) }
}

export function paths(entry: Entry, args: unknown): string[] {
  return entry.path_arguments.flatMap(pointer => {
    const value = at(pointer, args)
    if (typeof value === "string" && value.trim()) return [value]
    if (Array.isArray(value) && value.length && value.every(item => typeof item === "string" && item.trim())) return value as string[]
    throw new Error("工具文件参数必须是非空路径或路径列表。")
  })
}

// Objects are registered by the trusted MCP transport constructor; a plugin
// cannot impersonate a published MCP tool by attaching JSON metadata.
const origins = new WeakMap<object, Origin>()
export function bind<T extends object>(tool: T, origin: Origin): T { origins.set(tool, origin); return tool }
export function origin(tool: object) { return origins.get(tool) }
export * as QuantCodeToolCatalog from "./tool-catalog"

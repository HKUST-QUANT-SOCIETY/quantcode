import { access, realpath, lstat, open } from "node:fs/promises"
import path from "node:path"
import { constants } from "node:fs"
import os from "node:os"
import { z } from "zod"
import { Global } from "@opencode-ai/core/global"
import { QuantCodeIdentity, type Identity } from "./identity"
import { readPrivateFile } from "./private-file"

export const grantSchema = z.object({
  version: z.literal(1),
  grants: z.array(z.object({
    actor_id: z.string().min(1), group: z.string().min(1), workspace_id: z.string().min(1),
    root: z.string().min(1), access: z.enum(["read", "write"]),
  }).strict()),
}).strict()
export type WorkspaceAccess = "read" | "write"
export type WorkspaceGrant = { root: string; directory: string; access: WorkspaceAccess; identity: Identity }

export class WorkspaceDenied extends Error {
  constructor(message = "该目录不在当前身份的授权工作区中。") {
    super(message)
    this.name = "QuantCodeWorkspaceDenied"
  }
}

export function contains(root: string, target: string) {
  const relative = path.relative(root, target)
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`))
}

/** Resolve existing ancestors for a not-yet-created write target. ENOENT is
 * allowed only at the tail; permission errors and dangling links fail closed. */
export async function canonical(target: string): Promise<string> {
  if (!path.isAbsolute(target) || target.includes("\0")) throw new WorkspaceDenied("工作区路径必须为绝对路径。")
  const normalized = path.resolve(target)
  const info = await lstat(normalized).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return undefined
    throw error
  })
  if (info) return realpath(normalized)
  const parent = path.dirname(normalized)
  if (parent === normalized) throw new WorkspaceDenied()
  return path.join(await canonical(parent), path.basename(normalized))
}

export function privatePaths(directory: string) {
  return [
    ...(process.env.QUANTCODE_SHARED_BLACKBOARD_DB ? [path.dirname(process.env.QUANTCODE_SHARED_BLACKBOARD_DB)] : []),
    ...["QUANTCODE_DISTILL_CANDIDATES_DIR", "QUANTCODE_DISTILL_PUBLISH_ROOT"]
      .flatMap(key => process.env[key] ? [process.env[key]!] : []),
    ...["QUANTCODE_LEGACY_CHECKPOINTS_DB", "QUANTCODE_LEGACY_PROVENANCE_FILE"]
      .flatMap(key => process.env[key] ? [path.dirname(process.env[key]!)] : []),
    path.join(os.homedir(), ".ssh"), Global.Path.config, Global.Path.data, Global.Path.state,
    path.join(directory, ".quantcode"),
    path.join(directory, ".opencode"),
    path.join(directory, "opencode.json"), path.join(directory, "opencode.jsonc"),
    path.join(directory, "opencode.config.ts"),
    // Organization host helpers import trusted Python code from this install.
    // Research checkouts must be separate from the running service source.
    ...(process.env.QUANTCODE_BACKEND_ROOT ? [process.env.QUANTCODE_BACKEND_ROOT] : []),
    ...["QUANTCODE_IDENTITY_SESSION_FILE", "QUANTCODE_GITHUB_CREDENTIALS_FILE", "QUANTCODE_WORKSPACES_FILE", "QUANTCODE_DEPLOY_TOKEN_FILE", "QUANTCODE_TOOL_CATALOG_FILE"]
      .flatMap(key => process.env[key] ? [process.env[key]!] : []),
    // Enrollment history and publication locks share these private control
    // directories. Protect the directory, not only the current JSON file.
    ...["QUANTCODE_IDENTITY_SESSION_FILE", "QUANTCODE_WORKSPACES_FILE", "QUANTCODE_TOOL_CATALOG_FILE"]
      .flatMap(key => process.env[key] ? [path.dirname(process.env[key]!)] : []),
  ]
}

async function assertPublicTarget(root: string, target: string) {
  for (const reserved of privatePaths(root)) {
    const resolved = await canonical(reserved)
    if (contains(resolved, target) || contains(path.resolve(reserved), target)) {
      throw new WorkspaceDenied("凭据和组织控制数据不通过普通文件或终端工具开放。")
    }
  }
}

/** Host grants describe the local checkout corresponding to an authenticated
 * research workspace. A requested directory and a remembered project are not
 * grants. The roster directory remains available when it exists on this host. */
export async function authorize(directory: string, access: WorkspaceAccess = "read", suppliedIdentity?: Identity): Promise<WorkspaceGrant> {
  const identity = suppliedIdentity ?? await QuantCodeIdentity.currentIdentity()
  const actual = await realpath(directory).catch(() => { throw new WorkspaceDenied("研究工作目录不存在或不可访问。") })
  const info = await lstat(actual)
  if (!info.isDirectory()) throw new WorkspaceDenied("请选择研究工作目录。")
  const roots = await authorizedRoots(identity)
  const granted = roots.filter(grant => contains(grant.root, actual) && (access === "read" || grant.access === "write"))
    .sort((a, b) => b.root.length - a.root.length)[0]
  if (!granted) throw new WorkspaceDenied()
  await assertPublicTarget(granted.root, actual)
  return { ...granted, directory: actual, identity }
}

async function authorizedRoots(identity: Identity) {
  const roots: { root: string; access: WorkspaceAccess }[] = []
  // Remote roster paths are not silently treated as local paths on Windows.
  if (path.isAbsolute(identity.workspace_path)) {
    const personal = await realpath(identity.workspace_path).catch(() => undefined)
    if (personal) roots.push({ root: personal, access: "write" })
  }
  const filename = process.env.QUANTCODE_WORKSPACES_FILE ?? path.join(Global.Path.config, "workspaces.json")
  const exists = await lstat(filename).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return undefined
    throw error
  })
  if (exists) {
    const parsed = grantSchema.safeParse(JSON.parse(await readPrivateFile(filename, 262144)))
    if (!parsed.success) throw new WorkspaceDenied("本机工作区授权配置无效。")
    for (const grant of parsed.data.grants) {
      if (grant.actor_id !== identity.actor_id || grant.group !== identity.group || grant.workspace_id !== identity.workspace_id) continue
      const root = await realpath(grant.root).catch(() => undefined)
      if (root && path.isAbsolute(grant.root)) roots.push({ root, access: grant.access })
    }
  }
  return roots
}

/** A first-run client has no project directory yet. Discover only this
 * member's usable roots on this host, without project bootstrap or treating
 * the host's working directory (or a loopback URL) as a workspace grant. */
export async function list(input: { preferred?: string; expected_session_id?: string } = {}) {
  const identity = await QuantCodeIdentity.currentIdentity()
  if (input.expected_session_id !== undefined && input.expected_session_id !== identity.session_id) {
    throw new QuantCodeIdentity.IdentityError("选择工作区期间登录身份已变化，请重新选择。")
  }
  const result = await availableWorkspaces(identity, input.preferred)
  const current = await QuantCodeIdentity.currentIdentity()
  if (current.session_id !== identity.session_id ||
      JSON.stringify(QuantCodeIdentity.ownerOf(current)) !== JSON.stringify(QuantCodeIdentity.ownerOf(identity)) ||
      JSON.stringify(await availableWorkspaces(current, input.preferred)) !== JSON.stringify(result)) {
    throw new WorkspaceDenied("工作区授权已变化，请刷新后重新选择。")
  }
  return { login_session_id: identity.session_id, ...result }
}

async function readableDirectory(directory: string) {
  return !!(await lstat(directory).catch(() => undefined))?.isDirectory() &&
    await access(directory, constants.R_OK | constants.X_OK).then(() => true).catch(() => false)
}

async function availableWorkspaces(identity: Identity, requested?: string) {
  const candidates = await authorizedRoots(identity)
  const roots: { directory: string; access: WorkspaceAccess }[] = []
  for (const candidate of candidates) {
    if (roots.some(root => root.directory === candidate.root)) continue
    if (!await readableDirectory(candidate.root)) continue
    try { await assertPublicTarget(candidate.root, candidate.root) } catch (error) {
      if (error instanceof WorkspaceDenied) continue
      throw error
    }
    roots.push({ directory: candidate.root, access:
      candidates.some(grant => grant.root === candidate.root && grant.access === "write") ? "write" : "read" })
  }
  const preferred = requested && path.isAbsolute(requested)
    ? await authorize(requested, "read", identity).then(async grant =>
      await readableDirectory(grant.directory) ? grant.directory : undefined).catch(error => {
      if (error instanceof WorkspaceDenied) return undefined
      throw error
    }) : undefined
  return { roots, ...(preferred ? { preferred } : {}) }
}

export async function target(grant: WorkspaceGrant, requested: string, access: WorkspaceAccess = "read") {
  if (access === "write" && grant.access !== "write") throw new WorkspaceDenied("该工作区只允许读取。")
  const actual = await canonical(path.resolve(grant.directory, requested))
  if (!contains(grant.root, actual)) throw new WorkspaceDenied()
  await assertPublicTarget(grant.root, actual)
  if (access === "write") {
    const info = await lstat(actual).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined
      throw error
    })
    if (info?.isFile() && info.nlink > 1) throw new WorkspaceDenied("不允许通过硬链接别名改写文件，请使用工作区内独立文件。")
  }
  return actual
}

export async function revalidate(grant: WorkspaceGrant) {
  const current = await authorize(grant.directory, grant.access)
  if (current.identity.session_id !== grant.identity.session_id || current.root !== grant.root ||
      JSON.stringify(QuantCodeIdentity.ownerOf(current.identity)) !== JSON.stringify(QuantCodeIdentity.ownerOf(grant.identity))) {
    throw new WorkspaceDenied("读取或执行期间身份/工作区授权已变化。")
  }
  return current
}

/** Read a validated descriptor rather than reopening the untrusted request
 * path in a different filesystem layer. Re-resolve after reading so an ancestor
 * symlink swap cannot release data fetched outside the grant. */
export async function openFile(grant: WorkspaceGrant, requested: string) {
  const actual = await target(grant, requested)
  const handle = await open(actual, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
  try {
    const before = await handle.stat()
    if (!before.isFile()) throw new WorkspaceDenied("该路径不是普通文件。")
    if (before.nlink > 1) throw new WorkspaceDenied("不允许通过硬链接别名读取文件，请使用工作区内独立文件。")
    const validate = async () => {
      const after = await handle.stat()
      const resolved = await target(grant, requested)
      const linked = await lstat(resolved)
      if (resolved !== actual || linked.isSymbolicLink() || before.dev !== linked.dev || before.ino !== linked.ino ||
          before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs ||
          linked.size !== after.size || linked.mtimeMs !== after.mtimeMs || after.nlink > 1 || linked.nlink > 1) {
        throw new WorkspaceDenied("读取期间文件已变化，请重试。")
      }
      await revalidate(grant)
    }
    await validate()
    return { handle, path: actual, size: before.size, validate, close: () => handle.close() }
  } catch (error) {
    await handle.close()
    throw error
  }
}

export async function readFile(grant: WorkspaceGrant, requested: string) {
  const file = await openFile(grant, requested)
  try {
    const content = await file.handle.readFile()
    await file.validate()
    return { content, path: file.path }
  } finally {
    await file.close()
  }
}

export * as QuantCodeWorkspace from "./workspace"

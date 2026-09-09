import { AsyncLocalStorage } from "node:async_hooks"
import { fileURLToPath } from "node:url"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace, type WorkspaceGrant } from "@/quantcode/workspace"

// This scopes the existing server adapters' discovery/probe/spawn calls. It
// does not replace their lifecycle or create another language-server registry.
const context = new AsyncLocalStorage<WorkspaceGrant>()

export function within<T>(grant: WorkspaceGrant | undefined, fn: () => T): T {
  return grant ? context.run(grant, fn) : fn()
}

export function current() {
  if (!QuantCodeIdentity.enabled()) return
  const grant = context.getStore()
  if (!grant) throw new QuantCodeWorkspace.WorkspaceDenied("语言服务必须绑定当前身份的工作区。")
  return grant
}

export async function check(grant?: WorkspaceGrant) {
  if (!grant) return
  await QuantCodeWorkspace.revalidate(grant)
}

/** LSP Locations, LocationLinks and call-hierarchy items can point outside
 * their root. Remove the entire enclosing result rather than leaving a
 * symbol/diagnostic whose source location was not authorized. Free-form hover
 * text is never interpreted as an execution instruction or filesystem path. */
export async function publicResult<T>(value: T, grant?: WorkspaceGrant): Promise<T> {
  if (!grant) return value
  const filter = async (item: unknown): Promise<unknown> => {
    if (item === null || typeof item !== "object") return item
    if (Array.isArray(item)) return (await Promise.all(item.map(filter))).filter(x => x !== undefined)
    if (item instanceof Map) {
      const entries = await Promise.all([...item.entries()].map(async ([key, data]) => {
        if (typeof key !== "string" || !await allowedPath(key, grant)) return
        return [key, await filter(data)] as const
      }))
      return new Map(entries.filter(x => x !== undefined))
    }
    const object = item as Record<string, unknown>
    for (const key of ["uri", "targetUri"]) {
      if (!(key in object)) continue
      if (typeof object[key] !== "string") return
      const file = getFile(object[key])
      if (!file || !await allowedPath(file, grant)) return
    }
    const entries = await Promise.all(Object.entries(object).map(async ([key, data]) => [key, await filter(data)] as const))
    // Invalid nested locations invalidate the enclosing diagnostic/symbol too.
    if (entries.some(([, data]) => data === undefined)) return
    return Object.fromEntries(entries)
  }
  const filtered = await filter(value)
  await check(grant)
  return (filtered ?? null) as T
}

export async function allowedPath(file: string, grant: WorkspaceGrant) {
  return QuantCodeWorkspace.target(grant, file).then(() => true, () => false)
}

export function getFile(uri: string) {
  try {
    const url = new URL(uri)
    if (url.protocol !== "file:" || (url.hostname && url.hostname !== "localhost")) return
    return fileURLToPath(url)
  } catch {
    return
  }
}

export * as LspGovernance from "./governance"

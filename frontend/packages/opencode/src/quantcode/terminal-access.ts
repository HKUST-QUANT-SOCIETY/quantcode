import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"
import type { Identity } from "./identity"
import type { ProcessSandbox } from "./process-sandbox"

// Terminal lifetimes are process-local already (Core Pty). This is a matching
// authorization attachment, not a second terminal or execution registry.
const grants = new Map<string, { grant: WorkspaceGrant; routeDirectory: string; dispose: () => Promise<void> }>()

export function attach(id: string, grant: WorkspaceGrant, sandbox: ProcessSandbox, stop: () => Promise<unknown>, routeDirectory: string, active: () => Promise<boolean>) {
  let pending = false
  let closed = false
  const timer = setInterval(async () => {
    if (pending || closed) return
    pending = true
    try {
      if (!await active()) { await release(id); return }
      await QuantCodeWorkspace.revalidate(grant)
    } catch {
      // Keep trying to stop if the PTY service has not acknowledged removal.
      await stop().then(() => release(id), () => undefined)
    } finally { pending = false }
  }, 2000)
  timer.unref?.()
  grants.set(id, { grant, routeDirectory, dispose: async () => {
    closed = true
    clearInterval(timer)
    await sandbox.dispose()
  } })
}

export async function requireTerminal(id: string, directory: string) {
  const entry = grants.get(id)
  if (!entry) throw new QuantCodeWorkspace.WorkspaceDenied("终端不存在或不属于当前登录会话。")
  const current = await QuantCodeWorkspace.revalidate(entry.grant)
  const requested = await QuantCodeWorkspace.authorize(directory)
  if (requested.directory !== entry.routeDirectory) throw new QuantCodeWorkspace.WorkspaceDenied("终端不属于当前工作目录。")
  return current
}

export async function visible(id: string, directory: string) {
  return requireTerminal(id, directory).then(() => true, () => false)
}

export async function visibleEvent(id: string, identity: Identity) {
  const entry = grants.get(id)
  if (!entry || entry.grant.identity.session_id !== identity.session_id) return false
  return QuantCodeWorkspace.revalidate(entry.grant).then(() => true, () => false)
}

export async function release(id: string) {
  const entry = grants.get(id)
  grants.delete(id)
  await entry?.dispose()
}

export * as QuantCodeTerminalAccess from "./terminal-access"

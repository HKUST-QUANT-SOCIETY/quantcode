import type { Session } from "@opencode-ai/sdk/v2"

export type TaskDescendant = { session: Session; depth: number; live: string }
export const isActiveTask = (status?: string) => status === "busy" || status === "retry"
export const isRunningTask = (status?: string) => isActiveTask(status) || status === "running"

/** Walk only the selected session's authorized children endpoints. A status
 * response contains unrelated sessions too and is never tree membership. */
export async function readTaskDescendants(input: {
  sessionID: string; directory: string; signal: AbortSignal;
  children: (sessionID: string) => Promise<Session[]>;
}) {
  const descendants: Omit<TaskDescendant, "live">[] = []
  const seen = new Set([input.sessionID])
  let parents = [{ id: input.sessionID, depth: 0 }]
  while (parents.length) {
    const next: typeof parents = []
    // Small independent sibling batches avoid serial network latency without
    // launching an unbounded request fan-out for a large task tree.
    for (let offset = 0; offset < parents.length; offset += 8) {
      input.signal.throwIfAborted()
      const batch = parents.slice(offset, offset + 8)
      const pages = await Promise.all(batch.map(parent => input.children(parent.id)))
      input.signal.throwIfAborted()
      for (const [index, children] of pages.entries()) for (const child of children) {
        const parent = batch[index]
        if (child.parentID !== parent.id || child.directory !== input.directory || seen.has(child.id))
          throw new Error("任务树父子关系或工作目录不一致，请刷新后核对。")
        seen.add(child.id)
        const depth = parent.depth + 1
        descendants.push({ session: child, depth })
        next.push({ id: child.id, depth })
      }
    }
    parents = next
  }
  return descendants
}

export function descendantActivity(descendants: Omit<TaskDescendant, "live">[], statuses: Record<string, { type: string }>) {
  const items = descendants.map(item => ({ ...item, live: statuses[item.session.id]?.type ?? "idle" }))
  return { items, active: items.filter(item => isActiveTask(item.live)).length }
}

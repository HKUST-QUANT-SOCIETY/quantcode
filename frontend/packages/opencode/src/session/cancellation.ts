import { Context, Effect } from "effect"
import { eq, inArray } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { SessionTable } from "@opencode-ai/core/session/sql"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { SessionID } from "./schema"

// Process-local admission fence, matching the existing process-local Runners.
// An epoch survives the brief fence so a previously admitted asynchronous
// create/start cannot resume after cancellation has already returned.
const epochs = new Map<string, object>()
const active = new Map<string, number>()
// Only the host prompt-admission phase provides this callback. It is never
// serialized or retained on model execution/finalization after admission.
export const InputAdmission = Context.Reference<(() => void) | undefined>("@quantcode/SessionInputAdmission", {
  defaultValue: () => undefined,
})

export class Cancelling extends Error {
  constructor() { super("任务树正在停止或本次操作已被停止，请等待后重新提交。") }
}

export function admission(binding: QuantCodeIdentity.SessionBinding, sessionID = binding.root_session_id, blockWhileCancelling = false) {
  const root = binding.root_session_id
  if (active.has(root)) throw new Cancelling()
  const captured = [...new Set([root, binding.parent_session_id, sessionID].filter((id): id is string => !!id))]
    .map(id => [id, epochs.get(id)] as const)
  const check = () => {
    if (blockWhileCancelling && active.has(root) || captured.some(([id, epoch]) => epochs.get(id) !== epoch)) throw new Cancelling()
  }
  check()
  return check
}

export function invalidate(sessionID: string) {
  epochs.set(sessionID, {})
}

export function hold(binding: QuantCodeIdentity.SessionBinding, sessionID = binding.root_session_id, invalidateSelected = true) {
  const root = binding.root_session_id
  if (invalidateSelected) invalidate(sessionID)
  active.set(root, (active.get(root) ?? 0) + 1)
  let released = false
  return () => {
    if (released) return
    released = true
    const count = (active.get(root) ?? 1) - 1
    if (count) active.set(root, count)
    else active.delete(root)
  }
}

type Row = typeof SessionTable.$inferSelect
const ownerKey = (binding: QuantCodeIdentity.SessionBinding) => JSON.stringify({ ...binding.owner,
  github_subject: binding.owner.github_subject ?? null,
  resource_scopes: [...new Set(binding.owner.resource_scopes)].sort(),
})

function matches(row: Row, selected: Row, binding: QuantCodeIdentity.SessionBinding) {
  const current = QuantCodeIdentity.sessionBinding(row.metadata ?? undefined)
  return current && current.root_session_id === binding.root_session_id && ownerKey(current) === ownerKey(binding) &&
    row.directory === selected.directory && row.project_id === selected.project_id && row.workspace_id === selected.workspace_id &&
    (current.parent_session_id ?? null) === row.parent_id
}

/** Cancellation is cleanup, including after login revocation. Public callers
 * authorize the selected session before reaching RunState; this independently
 * verifies every persisted ancestry edge before touching another Runner. */
export const lineage = Effect.fn("SessionCancellation.lineage")(function* (sessionID: SessionID) {
  const { db } = yield* Database.Service
  const selected = yield* db.select().from(SessionTable).where(eq(SessionTable.id, sessionID)).get().pipe(Effect.orDie)
  const binding = QuantCodeIdentity.sessionBinding(selected?.metadata ?? undefined)
  if (!selected || !binding) throw new QuantCodeIdentity.IdentityError("停止对象没有有效的原生任务归属。")
  const seen = new Set<string>()
  let current: Row | undefined = selected
  while (current) {
    if (seen.has(current.id) || !matches(current, selected, binding)) throw new QuantCodeIdentity.IdentityError("停止对象的任务树归属不一致。")
    seen.add(current.id)
    if (!current.parent_id) {
      if (current.id !== binding.root_session_id) throw new QuantCodeIdentity.IdentityError("停止对象的根任务不一致。")
      return { selected, binding }
    }
    current = yield* db.select().from(SessionTable).where(eq(SessionTable.id, current.parent_id)).get().pipe(Effect.orDie)
  }
  throw new QuantCodeIdentity.IdentityError("停止对象的父任务不存在。")
})

export const descendants = Effect.fn("SessionCancellation.descendants")(function* (tree: Effect.Success<ReturnType<typeof lineage>>) {
  const { db } = yield* Database.Service
  const rows: Row[] = []
  const seen = new Set<string>([tree.selected.id])
  let parents: SessionID[] = [tree.selected.id]
  let invalid = false
  while (parents.length) {
    const next: SessionID[] = []
    for (let offset = 0; offset < parents.length; offset += 500) {
      const children = yield* db.select().from(SessionTable)
        .where(inArray(SessionTable.parent_id, parents.slice(offset, offset + 500))).all().pipe(Effect.orDie)
      for (const child of children) {
        if (seen.has(child.id) || !matches(child, tree.selected, tree.binding)) { invalid = true; continue }
        seen.add(child.id)
        rows.push(child)
        next.push(child.id)
      }
    }
    parents = next
  }
  return { rows, invalid }
})

export * as SessionCancellation from "./cancellation"

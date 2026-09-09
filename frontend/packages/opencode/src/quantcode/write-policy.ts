import { Effect } from "effect"
import { Patch } from "@/patch"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeAccess } from "./access"
import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"
import { QuantCodeSolution } from "./solution"
import { QuantCodeReuse } from "./reuse"
import { QuantCodeTaskLock } from "./task-lock"
import { QuantCodeWriteReceipt } from "./write-receipt"

const object = (value: unknown): Record<string, unknown> | undefined => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined

/** Parse the actual built-in schema, not model-provided 'files touched' hints. */
export function fileTargets(tool: string, input: unknown): string[] {
  const args = object(input)
  if ((tool === "write" || tool === "edit") && typeof args?.filePath === "string") return [args.filePath]
  if (tool === "apply_patch" && typeof args?.patchText === "string") {
    return Patch.parsePatch(args.patchText).hunks.flatMap(hunk => hunk.type === "update" && hunk.move_path ? [hunk.path, hunk.move_path] : [hunk.path])
  }
  throw new Error("无法从受支持的写入工具参数确定实际文件范围。")
}

export type WriteScope = { grant: WorkspaceGrant; files: string[]; planHashes: string[] }

/** Check every ancestor against its own document. A child cannot inherit only
 * the owner's identity while discarding the parent's solution constraints. */
export const scope = Effect.fn("QuantCodeWritePolicy.scope")(function* (sessionID: string, requested: string[], shell = false, capabilityID?: string, shared = false) {
  const access = yield* QuantCodeAccess.requireSession(sessionID)
  if (!access) throw new QuantCodeIdentity.IdentityError()
  const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(access.directory, "read", access.identity))
  // A read-only shell remains useful in a read-only checkout. Actual writes
  // (including a frozen shell file set) still require a separate write grant.
  const writeGrant = requested.length ? yield* Effect.promise(() => QuantCodeWorkspace.authorize(access.directory, "write", access.identity)) : grant
  const files: string[] = []
  for (const filename of requested) files.push(yield* Effect.promise(() => QuantCodeWorkspace.target(writeGrant, filename, "write")))
  const entries = yield* QuantCodeWriteReceipt.history(access.binding.root_session_id)
  const observed = new Set(files)
  for (const entry of entries.values()) for (const file of entry.start.files) observed.add(file)
  const hashes: string[] = []
  const visited = new Set<string>()
  let next: string | undefined = sessionID
  let shellFiles: string[] | undefined
  while (next) {
    if (visited.has(next) || visited.size > 8) throw new Error("子任务继承链无效或超过深度限制。")
    visited.add(next)
    const ancestor: Effect.Success<ReturnType<typeof QuantCodeAccess.requireSession>> = yield* QuantCodeAccess.requireSession(next)
    if (!ancestor || ancestor.binding.root_session_id !== access.binding.root_session_id || ancestor.directory !== access.directory) {
      throw new Error("子任务身份或工作目录与父任务不一致。")
    }
    const status = yield* QuantCodeSolution.status(next, observed.size, shared)
    const doc = status.solution
    if (shared && (doc?.status !== "frozen" || doc.trivial_exempt)) throw new Error("共享写入需要已冻结的完整方案，不能使用简单修改豁免。")
    if (!shell && (status.classification.solution_required || doc) && doc?.status !== "frozen") {
      throw new Error("方案未冻结，代码工具不可用。请查看并确认当前任务及父任务的方案。")
    }
    if (doc?.status === "frozen") {
      const allowed = yield* Effect.forEach(doc.file_impact, file => Effect.promise(() => QuantCodeWorkspace.target(grant, file)))
      if (files.some(file => !allowed.includes(file))) throw new Error("写入文件不在当前或父任务的冻结方案范围内。")
      hashes.push(doc.doc_hash)
      shellFiles = shellFiles === undefined ? allowed : shellFiles.filter(file => allowed.includes(file))
    } else if (shell) {
      // The process sandbox enforces this empty set. Read-only shell commands
      // remain useful while drafting; arbitrary programs cannot gain writes.
      shellFiles = []
    }
    next = ancestor.binding.parent_session_id
  }
  const targets = shell ? shellFiles ?? [] : [...new Set(files)]
  const effectiveGrant = targets.length ? yield* Effect.promise(() => QuantCodeWorkspace.authorize(access.directory, "write", access.identity)) : grant
  for (const target of targets) yield* Effect.promise(() => QuantCodeWorkspace.target(effectiveGrant, target, "write"))
  if (targets.length || shared) {
    for (const ancestor of visited) yield* QuantCodeReuse.requireCoverage(ancestor, capabilityID)
  }
  return { grant: effectiveGrant, files: targets, planHashes: hashes } satisfies WriteScope
})

/** Serialize native writes within a root task, including descendants. Hold the
 * permit through actual execution; do not release it before recording intent. */
export function guarded<A, E, R>(sessionID: string, files: string[], execute: (scope: WriteScope) => Effect.Effect<A, E, R>, shell = false, capabilityID?: string) {
  return QuantCodeTaskLock.guard(sessionID, Effect.gen(function* () {
    const admitted = yield* scope(sessionID, files, shell, capabilityID)
    return yield* execute(admitted)
  }))
}

export * as QuantCodeWritePolicy from "./write-policy"

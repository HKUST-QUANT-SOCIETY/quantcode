import path from "node:path"
import { mkdir, lstat, realpath } from "node:fs/promises"
import { Effect } from "effect"
import { Global } from "@opencode-ai/core/global"
import { Flock } from "@opencode-ai/core/util/flock"
import { QuantCodeAccess } from "./access"
import { QuantCodeIdentity } from "./identity"
import os from "node:os"
import { QuantCodeToolCatalog } from "./tool-catalog"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { SessionID } from "@/session/schema"
import { EventV2Bridge } from "@/event-v2-bridge"
import { EffectBridge } from "@/effect/bridge"

export class TaskBusyError extends Error {
  constructor() {
    super("当前任务正在执行，或上次执行尚待回执核对。请稍后重试；不要重复发起写入。")
    this.name = "QuantCodeTaskBusyError"
  }
}
export class RecoveryError extends Error {}

async function lockDirectory() {
  const directory = path.join(Global.Path.state, "organization", "task-locks")
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const info = await lstat(directory)
  if (!info.isDirectory() || info.isSymbolicLink() || await realpath(directory) !== directory ||
      (process.platform !== "win32" && (info.mode & 0o077 || (process.getuid && info.uid !== process.getuid())))) {
    throw new RecoveryError("任务锁目录必须由宿主私有管理。")
  }
  return directory
}

export const status = Effect.fn("QuantCodeTaskLock.status")(function* (sessionID: string) {
  const scope = { kind: "read", resource: "execution_lock" } as const
  const access = yield* QuantCodeAccess.requireReview(sessionID, scope)
  const directory = yield* Effect.promise(lockDirectory)
  const owner = yield* Effect.promise(() => Flock.inspect(`quantcode-task:${access.binding.root_session_id}`, { dir: directory }))
  let state: QuantCodeGovernance.TaskLockState["status"] = "idle"
  if (owner) {
    state = "other_host"
    if (owner.hostname === os.hostname()) {
      state = "active"
      try { process.kill(owner.pid, 0) } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ESRCH") state = "recovery_required"
      }
    }
  }
  const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
  if (current?.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
  return { session_id: SessionID.make(sessionID), status: state, ...(owner ? { lock_digest: QuantCodeToolCatalog.digest(owner) } : {}) }
})

/** UI-only evidence-bearing recovery; no retry or receipt mutation. */
export const recover = Effect.fn("QuantCodeTaskLock.recover")(function* (sessionID: string, input: QuantCodeGovernance.TaskLockRecovery) {
  if (input.processes_stopped !== true || !input.note.trim() || input.note.length > 4000 || !input.evidence_ref.trim() || input.evidence_ref.length > 2000) {
    throw new RecoveryError("请先核对原执行及其子进程已停止，并提供证据位置与说明。")
  }
  const scope = { ...input, kind: "execution_lock", input_digest: QuantCodeToolCatalog.digest(input) } as const
  const access = yield* QuantCodeAccess.requireReview(sessionID, scope)
  const dir = yield* Effect.promise(lockDirectory)
  const key = `quantcode-task:${access.binding.root_session_id}`
  const owner = yield* Effect.promise(() => Flock.inspect(key, { dir }))
  if (!owner || QuantCodeToolCatalog.digest(owner) !== input.expected_digest) throw new RecoveryError("执行锁已变化，请刷新后再核对。")
  const events = yield* EventV2Bridge.Service
  const bridge = yield* EffectBridge.make()
  yield* Effect.promise(() => Flock.recover(key, owner, () => bridge.promise(Effect.gen(function* () {
    const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
    if (current?.identity.session_id !== access.identity.session_id) throw new QuantCodeIdentity.IdentityError()
    yield* events.publish(QuantCodeGovernance.TaskLockRecoveryRecorded, {
      sessionID: SessionID.make(access.binding.root_session_id), lock_digest: input.expected_digest,
      reviewer: access.identity.actor_id, evidence_ref: input.evidence_ref.trim(), note: input.note.trim(), timestamp: Date.now(),
    })
  })), { dir })).pipe(Effect.catchDefect(() => Effect.die(new RecoveryError("未解除执行锁：原进程可能仍在运行，或锁状态已变化。请重新核对。"))))
  return yield* status(sessionID)
})

/** Human receipt reconciliation shares the execution lock without acquiring
 * the owner's execution grant. It can only append evidence for existing calls. */
export function reviewGuard<A, E, R>(sessionID: string, scope: Exclude<QuantCodeAccess.ReviewScope, { kind: "read" }>, operation: Effect.Effect<A, E, R>) {
  return Effect.gen(function* () {
    const admitted = yield* QuantCodeAccess.requireReview(sessionID, scope)
    return yield* withTaskLock(admitted.binding.root_session_id, Effect.gen(function* () {
      const current = yield* QuantCodeAccess.requireReview(sessionID, scope)
      if (current.identity.session_id !== admitted.identity.session_id ||
          current.binding.root_session_id !== admitted.binding.root_session_id) throw new QuantCodeIdentity.IdentityError()
      return yield* operation
    }))
  })
}

function withTaskLock<A, E, R>(root: string, operation: Effect.Effect<A, E, R>) {
  return Effect.scoped(Effect.gen(function* () {
    const directory = yield* Effect.promise(lockDirectory)
    // Never steal a lock solely because a long operation stopped heartbeating.
    // Crash recovery must first reconcile its possible external side effects.
    yield* Flock.effect(`quantcode-task:${root}`, {
      dir: directory, staleMs: Number.POSITIVE_INFINITY, timeoutMs: 5000,
    }).pipe(Effect.catchDefect(error => Effect.die(error instanceof Error && error.message.startsWith("Timed out waiting for lock:")
      ? new TaskBusyError() : error)))
    return yield* operation
  }))
}

/** Reuse OpenCode's cross-process lease and scoped release. QuantCode adds
 * only the authenticated root-task key and post-acquisition revalidation. */
export function guard<A, E, R>(sessionID: string, operation: Effect.Effect<A, E, R>) {
  return Effect.gen(function* () {
    const admitted = yield* QuantCodeAccess.requireExecution(sessionID)
    if (!admitted) throw new QuantCodeIdentity.IdentityError()
    return yield* withTaskLock(admitted.binding.root_session_id, Effect.gen(function* () {
      const current = yield* QuantCodeAccess.requireExecution(sessionID)
      if (!current || current.identity.session_id !== admitted.identity.session_id ||
          current.binding.root_session_id !== admitted.binding.root_session_id) {
        throw new QuantCodeIdentity.IdentityError("等待执行期间任务或登录身份已变化。")
      }
      return yield* operation
    }))
  })
}

export * as QuantCodeTaskLock from "./task-lock"

import path from "node:path"
import { mkdir, realpath } from "node:fs/promises"
import { Effect, Schema } from "effect"
import { Global } from "@opencode-ai/core/global"
import { QuantCodeIntent } from "./intent"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { QuantCodeIdentity } from "./identity"
import { EventV2Bridge } from "@/event-v2-bridge"
import { QuantCodeTaskLock } from "./task-lock"
import { AppProcess } from "@opencode-ai/core/process"
import { ChildProcess } from "effect/unstable/process"

export type SolutionStatus = QuantCodeGovernance.SolutionState
export type Proposal = { goal: string; acceptance_criteria: string[]; file_impact: string[]; expected_hash?: string; expected_version?: number }
export type Review = { expected_hash: string; expected_version: number; decision: "approve" | "reject"; note: string }

const invoke = Effect.fn("QuantCodeSolution.invoke")(function* (action: "status" | "propose" | "review", sessionID: string, login: string, payload: unknown, signal?: AbortSignal) {
  const python = process.env.QUANTCODE_HOST_PYTHON
  const configuredRoot = process.env.QUANTCODE_BACKEND_ROOT
  if (!python || !path.isAbsolute(python) || !configuredRoot || !path.isAbsolute(configuredRoot)) throw new Error("QuantCode 组织服务宿主未配置。")
  const root = yield* Effect.promise(() => realpath(configuredRoot))
  const state = path.join(Global.Path.state, "organization")
  yield* Effect.promise(() => mkdir(state, { recursive: true, mode: 0o700 }))
  const processes = yield* AppProcess.Service
  const output = yield* processes.run(ChildProcess.make(python, ["-I", "-c",
    "import sys; sys.path.insert(0, sys.argv.pop(1)); from quantcode.solution_host import main; main()", root,
    "--action", action, "--session", sessionID, "--login", login], {
    cwd: root, stderr: "ignore", extendEnv: false, forceKillAfter: "3 seconds",
    env: { PATH: process.env.PATH, SYSTEMROOT: process.env.SYSTEMROOT, LANG: "C.UTF-8",
      QUANTCODE_IDENTITY_SESSION_FILE: process.env.QUANTCODE_IDENTITY_SESSION_FILE,
      QUANTCODE_SERVICE_STATE_DIR: state, PYTHONDONTWRITEBYTECODE: "1" },
  }), { stdin: JSON.stringify(payload), signal, timeout: "30 seconds", maxOutputBytes: 1_000_000, maxErrorBytes: 0 }).pipe(Effect.orDie)
  if (output.exitCode !== 0 || output.stdoutTruncated) throw new Error("方案服务未完成操作，请重新加载状态。")
  const value = Schema.decodeUnknownSync(Schema.UnknownFromJsonString)(output.stdout.toString("utf8"))
  return decodeStatus(value, sessionID)
})

export function decodeStatus(value: unknown, sessionID: string): SolutionStatus {
  if (value && typeof value === "object" && "error" in value && typeof value.error === "string") throw new Error(value.error)
  // Python's absent document becomes an omitted optional public field.
  let wire = value
  if (value && typeof value === "object" && "solution" in value && value.solution === null) {
    const { solution, ...remaining } = value
    wire = remaining
  }
  const result = Schema.decodeUnknownSync(QuantCodeGovernance.SolutionState)(wire)
  if (result.session_id !== sessionID) throw new Error("方案服务返回了不同任务。")
  return result
}


const request = Effect.fn("QuantCodeSolution.request")(function* (action: "status" | "propose" | "review", sessionID: string, payload: object, signal?: AbortSignal) {
  const current = yield* QuantCodeIntent.read(sessionID)
  const result = yield* invoke(action, sessionID, current.access.identity.session_id, { ...payload, task: current.task }, signal)
  const latest = yield* QuantCodeIntent.read(sessionID)
  if (latest.task !== current.task || latest.access.identity.session_id !== current.access.identity.session_id) {
    throw new QuantCodeIdentity.IdentityError("操作期间任务或登录已变化，请重新读取当前方案。")
  }
  return result
})

export const status = (sessionID: string, observedFileCount = 0, sharedWrite = false) => request("status", sessionID, { file_count: observedFileCount, shared_write: sharedWrite })
const changed = Effect.fn("QuantCodeSolution.changed")(function* (result: SolutionStatus) {
  if (!result.solution) throw new Error("方案服务未返回已保存的文档。")
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeGovernance.SolutionChanged, { sessionID: result.session_id,
    document_id: result.solution.id, document_hash: result.solution.doc_hash,
    version: result.solution.version, status: result.solution.status })
})
export const propose = (sessionID: string, proposal: Proposal, signal?: AbortSignal) =>
  QuantCodeTaskLock.guard(sessionID, request("propose", sessionID, proposal, signal).pipe(Effect.tap(changed)))

/** Host UI only. This function must never be registered in the model catalog. */
export const review = (sessionID: string, decision: Review) =>
  QuantCodeTaskLock.guard(sessionID, request("review", sessionID, decision).pipe(Effect.tap(changed)))

export * as QuantCodeSolution from "./solution"

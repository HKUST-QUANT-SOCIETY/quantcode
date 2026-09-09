import path from "node:path"
import { realpath } from "node:fs/promises"
import { Effect, Schema } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeLegacy } from "@opencode-ai/schema/quantcode-legacy"
import { QuantCodeNativeGate } from "@opencode-ai/schema/quantcode-native-gate"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeLegacyProvider } from "./legacy-provider"

export class LegacyUnavailable extends Error {}

/** Fixed host adapter; no model key, task prompt, source path or checkpoint
 * database is accepted from the browser. It cannot enroll executor provenance. */
const request = Effect.fn("QuantCodeLegacy.request")(function* (
  action: "list" | "detail" | "resume" | "request-approval", payload: unknown, signal?: AbortSignal,
) {
  if (!QuantCodeIdentity.enabled()) throw new LegacyUnavailable("旧任务兼容适配器只在 QuantCode 原生迁移模式开放。")
  signal?.throwIfAborted()
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const configured = process.env.QUANTCODE_BACKEND_ROOT
  const python = process.env.QUANTCODE_HOST_PYTHON
  if (!configured || !path.isAbsolute(configured) || !python || !path.isAbsolute(python)) {
    throw new LegacyUnavailable("旧任务历史服务宿主未配置。")
  }
  const root = yield* Effect.promise(() => realpath(configured))
  const processes = yield* AppProcess.Service
  const command = ChildProcess.make(python, ["-I", "-B", "-c",
    "import sys; sys.path.insert(0, sys.argv.pop(1)); from quantcode.legacy_host import main; main()", root,
    "--action", action, "--login", identity.session_id], { cwd: root, stderr: "ignore", extendEnv: false,
    forceKillAfter: "3 seconds", env: { LANG: "C.UTF-8", PYTHONDONTWRITEBYTECODE: "1", OPENCODE_CHANNEL: "quantcode",
      QUANTCODE_UNIFIED_RUNTIME: "1", QUANTCODE_IDENTITY_SESSION_FILE: process.env.QUANTCODE_IDENTITY_SESSION_FILE,
      QUANTCODE_TOKEN_BUDGET: process.env.QUANTCODE_TOKEN_BUDGET,
      ...(process.env.QUANTCODE_LEGACY_CHECKPOINTS_DB ? { QUANTCODE_LEGACY_CHECKPOINTS_DB: process.env.QUANTCODE_LEGACY_CHECKPOINTS_DB } : {}),
      ...(process.env.QUANTCODE_LEGACY_PROVENANCE_FILE ? { QUANTCODE_LEGACY_PROVENANCE_FILE: process.env.QUANTCODE_LEGACY_PROVENANCE_FILE } : {}),
    } })
  if (action === "resume") return yield* QuantCodeLegacyProvider.run(command, payload, identity, signal)
  const output = yield* processes.run(command, { stdin: JSON.stringify(payload), signal, timeout: "45 seconds", maxOutputBytes: 8_000_000, maxErrorBytes: 0 }).pipe(Effect.orDie)
  if (output.exitCode !== 0 || output.stdoutTruncated) throw new LegacyUnavailable("旧任务历史未完整返回，请缩小查询范围；不会重新执行原任务。")
  const result = Schema.decodeUnknownSync(Schema.UnknownFromJsonString)(output.stdout.toString("utf8"))
  if (result && typeof result === "object" && "error" in result) throw new LegacyUnavailable(String(result.error))
  const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (current.session_id !== identity.session_id || JSON.stringify(QuantCodeIdentity.ownerOf(current)) !== JSON.stringify(QuantCodeIdentity.ownerOf(identity))) {
    throw new QuantCodeIdentity.IdentityError("旧历史查询期间登录身份已变化。")
  }
  return result
})

export const list = (input: QuantCodeLegacy.ListInput = {}, signal?: AbortSignal) =>
  request("list", input, signal).pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeLegacy.List)))
export const detail = (input: QuantCodeLegacy.DetailInput, signal?: AbortSignal) =>
  request("detail", input, signal).pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeLegacy.Detail)))
export const resume = (input: QuantCodeLegacy.ResumeInput, signal?: AbortSignal) =>
  request("resume", input, signal).pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeLegacy.Resume)))
export const requestApproval = (input: QuantCodeLegacy.ApprovalInput, signal?: AbortSignal) =>
  request("request-approval", input, signal).pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeNativeGate.View)))

export * as QuantCodeLegacyHost from "./legacy"

import path from "node:path"
import { realpath } from "node:fs/promises"
import { Effect, Schema } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeKnowledge } from "@opencode-ai/schema/quantcode-knowledge"
import { QuantCodeIdentity } from "./identity"

export class KnowledgeUnavailable extends Error {}

/** Fixed host actions. Distillation is internal; list/review are dedicated
 * management API actions and never expose an additional model tool. */
const request = Effect.fn("QuantCodeKnowledge.request")(function* (
  action: "distill" | "list" | "review", input: unknown, expected?: QuantCodeIdentity.Identity, signal?: AbortSignal,
) {
  if (!QuantCodeIdentity.enabled()) throw new KnowledgeUnavailable("知识候选只在 QuantCode 原生迁移模式开放。")
  signal?.throwIfAborted()
  const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  const original = expected ?? identity
  const same = (current: QuantCodeIdentity.Identity) => current.session_id === original.session_id &&
    JSON.stringify(QuantCodeIdentity.ownerOf(current)) === JSON.stringify(QuantCodeIdentity.ownerOf(original))
  if (!same(identity)) throw new QuantCodeIdentity.IdentityError("知识候选来源任务的登录身份已变化。")
  const configured = process.env.QUANTCODE_BACKEND_ROOT
  const python = process.env.QUANTCODE_HOST_PYTHON
  const candidates = process.env.QUANTCODE_DISTILL_CANDIDATES_DIR
  if (!configured || !path.isAbsolute(configured) || !python || !path.isAbsolute(python) ||
    !candidates || !path.isAbsolute(candidates)) throw new KnowledgeUnavailable("知识候选宿主目录尚未配置。")
  const root = yield* Effect.promise(() => realpath(configured))
  const processes = yield* AppProcess.Service
  const output = yield* processes.run(ChildProcess.make(python, ["-I", "-B", "-c",
    "import sys; sys.path.insert(0, sys.argv.pop(1)); from quantcode.knowledge_host import main; main()", root,
    "--action", action, "--login", identity.session_id], {
    cwd: root, stderr: "ignore", extendEnv: false, forceKillAfter: "3 seconds",
    env: { LANG: "C.UTF-8", PYTHONDONTWRITEBYTECODE: "1", OPENCODE_CHANNEL: "quantcode",
      QUANTCODE_UNIFIED_RUNTIME: "1", QUANTCODE_IDENTITY_SESSION_FILE: process.env.QUANTCODE_IDENTITY_SESSION_FILE,
      QUANTCODE_DISTILL_CANDIDATES_DIR: candidates,
      ...(process.env.QUANTCODE_DISTILL_PUBLISH_ROOT ? { QUANTCODE_DISTILL_PUBLISH_ROOT: process.env.QUANTCODE_DISTILL_PUBLISH_ROOT } : {}),
    },
  }), { stdin: JSON.stringify(input), signal,
    timeout: "45 seconds", maxOutputBytes: 2_000_000, maxErrorBytes: 0 }).pipe(Effect.orDie)
  if (output.exitCode !== 0 || output.stdoutTruncated) throw new KnowledgeUnavailable(action === "distill"
    ? "知识候选未完整登记，任务执行结果已保留，可稍后重试投影。"
    : "知识候选请求未完成，请刷新当前身份、候选摘要和宿主配置后重试。")
  const result = Schema.decodeUnknownSync(Schema.UnknownFromJsonString)(output.stdout.toString("utf8"))
  const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
  if (!same(current)) throw new QuantCodeIdentity.IdentityError("知识候选生成期间登录身份已变化。")
  return result
})

/** The publisher supplies the identity used to read the original ToolParts. */
export const distill = (input: QuantCodeKnowledge.Input, expected: QuantCodeIdentity.Identity, signal?: AbortSignal) =>
  request("distill", Schema.decodeUnknownSync(QuantCodeKnowledge.Input)(input), expected, signal)
    .pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeKnowledge.Result)))
export const list = (signal?: AbortSignal) => request("list", {}, undefined, signal)
  .pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeKnowledge.List)))
export const review = (input: QuantCodeKnowledge.ReviewInput, signal?: AbortSignal) =>
  request("review", Schema.decodeUnknownSync(QuantCodeKnowledge.ReviewInput)(input), undefined, signal)
    .pipe(Effect.map(Schema.decodeUnknownSync(QuantCodeKnowledge.Review)))

export * as QuantCodeKnowledgeHost from "./knowledge"

import path from "node:path"
import { constants } from "node:fs"
import { open, realpath, lstat, mkdir, writeFile, readdir } from "node:fs/promises"
import { createHash } from "node:crypto"
import { Effect } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { z } from "zod"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"
import { QuantCodeProcessSandbox } from "./process-sandbox"
import { readHostFile } from "./private-file"

export const Frame = z.object({ type: z.literal("tool"), sequence: z.number().int().positive(),
  tool_id: z.string().regex(/^[a-zA-Z0-9_-]+$/), args: z.record(z.string(), z.unknown()),
  context: z.record(z.string(), z.unknown()), source_root: z.string(),
  source_files: z.record(z.string(), z.string().regex(/^[a-f0-9]{64}$/)),
  write_paths: z.array(z.string()), readonly: z.boolean(),
}).strict()
export type Frame = z.infer<typeof Frame>
const Result = z.discriminatedUnion("ok", [
  z.object({ ok: z.literal(true), kind: z.enum(["json", "bytes", "bytearray", "null"]), payload_base64: z.string() }).strict(),
  z.object({ ok: z.literal(false), reason: z.string() }).strict(),
])

/** Fixed host transport for one business component. The caller is the pinned
 * archived controller, not a model-facing process or another agent loop. */
export const run = Effect.fn("QuantCodeLegacyTools.run")(function* (input: Frame, identity: QuantCodeIdentity.Identity, signal?: AbortSignal) {
  const processes = yield* AppProcess.Service
  const configured = process.env.QUANTCODE_HOST_PYTHON
  const backend = process.env.QUANTCODE_BACKEND_ROOT
  if (!configured || !backend || !path.isAbsolute(configured) || !path.isAbsolute(backend))
    throw new Error("旧组件隔离宿主尚未配置。")
  const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(identity.workspace_path, input.readonly ? "read" : "write", identity))
  const context = Object.fromEntries(["actor_id", "group", "role", "session_id", "workspace_id", "workspace_path", "github_subject", "resource_scopes", "thread_id", "legacy_creator_session_id"]
    .filter(key => input.context[key] !== undefined).map(key => [key, input.context[key]]))
  for (const field of ["actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject"] as const)
    if ((context[field] ?? null) !== (identity[field] ?? null)) throw new QuantCodeIdentity.IdentityError("旧组件上下文与任务归属不一致。")
  if (context.session_id !== identity.session_id || JSON.stringify([...(context.resource_scopes as string[] ?? [])].sort()) !== JSON.stringify([...identity.resource_scopes].sort()))
    throw new QuantCodeIdentity.IdentityError("旧组件登录和资源权限已变化。")
  if (input.readonly && input.write_paths.length) throw new Error("只读旧组件不能申请写入范围。")
  const writes: string[] = []
  for (const filename of input.write_paths) {
    const target = yield* Effect.promise(() => QuantCodeWorkspace.target(grant, filename, "write"))
    const info = yield* Effect.promise(() => lstat(target).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined
      throw error
    }))
    if (target === grant.root || info?.isDirectory()) throw new Error("旧组件只能写入冻结方案中的精确文件，不能授权整个目录。")
    writes.push(target)
  }
  if (!input.readonly && !writes.length) return { ok: false as const, reason: "旧组件没有已冻结的文件范围，不能启动副作用执行。" }
  const sourceRoot = yield* Effect.promise(() => realpath(input.source_root))
  if (sourceRoot !== input.source_root || QuantCodeWorkspace.contains(grant.root, sourceRoot)) throw new Error("归档执行源码不能位于任务可写目录。")
  const source: { relative: string; content: Buffer }[] = []
  let total = 0
  for (const [relative, digest] of Object.entries(input.source_files)) {
    if (!relative || path.isAbsolute(relative) || relative.includes("\\") || relative.split("/").some(part => !part || part === "." || part === ".."))
      throw new Error("归档源码相对路径无效。")
    const content = yield* Effect.promise(async () => {
      const filename = path.join(sourceRoot, relative)
      if (!QuantCodeWorkspace.contains(sourceRoot, await realpath(filename))) throw new Error("归档源码路径越界。")
      const file = await open(filename, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
      try {
        const before = await file.stat()
        if (!before.isFile() || before.size > 64_000_000) throw new Error("归档源码不是受支持的普通文件。")
        const bytes = await file.readFile()
        const after = await file.stat()
        const linked = await lstat(filename)
        if (before.ino !== linked.ino || before.dev !== linked.dev || before.size !== after.size ||
          before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs || linked.mtimeMs !== after.mtimeMs ||
          createHash("sha256").update(bytes).digest("hex") !== digest) throw new Error("归档源码在组件启动前发生变化。")
        return bytes
      } finally { await file.close() }
    })
    total += content.byteLength
    if (total > 64_000_000) throw new Error("归档源码超过单次隔离宿主大小限制。")
    source.push({ relative, content })
  }
  const interpreter = yield* Effect.promise(() => realpath(configured))
  // preserve the configured venv's library search path when prepare resolves
  // its interpreter symlink. Only bin/lib are readable, never backend secrets.
  const environment = path.dirname(path.dirname(configured))
  const libraries = yield* Effect.promise(async () => {
    if (!await lstat(path.join(environment, "pyvenv.cfg")).then(info => info.isFile(), () => false)) return []
    const root = path.join(environment, "lib")
    return (await readdir(root)).filter(name => /^python\d+\.\d+$/.test(name))
      .map(name => path.join(root, name, "site-packages"))
      .filter(filename => path.isAbsolute(filename))
  })
  if (path.basename(path.dirname(interpreter)) !== "bin") return { ok: false as const, reason: "旧组件 Python 运行环境布局尚不支持隔离执行。" }
  const runtimeRoot = path.dirname(path.dirname(interpreter))
  if (runtimeRoot === path.parse(runtimeRoot).root || QuantCodeWorkspace.contains(grant.root, runtimeRoot) ||
    QuantCodeWorkspace.contains(runtimeRoot, backend)) throw new Error("Python 运行目录不能包含宿主控制目录或研究工作区。")
  const runtimeRoots = yield* Effect.promise(async () => [...new Set(await Promise.all([
    // An interpreter installed outside systemRoots (for example python.org's
    // /Library/Frameworks or uv) still needs its own standard library.
    realpath(runtimeRoot), ...libraries.map(root => realpath(root)),
  ]))])
  const worker = yield* Effect.promise(() => readHostFile(path.join(backend, "quantcode", "legacy_tool_host.py"), 262144))
  const sandbox = yield* Effect.promise(() => QuantCodeProcessSandbox.prepare({ grant, command: interpreter,
    args: ["-I", "-B", "-c", worker], writePaths: writes, runtimeReadRoots: runtimeRoots,
    protectedScratchPaths: ["executor"],
  }))
  return yield* Effect.gen(function* () {
    const staged = path.join(sandbox.env.TMPDIR, "executor")
    for (const file of source) yield* Effect.promise(async () => {
      const destination = path.join(staged, file.relative)
      await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 })
      await writeFile(destination, file.content, { flag: "wx", mode: 0o400 })
    })
    yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
    const result = yield* processes.run(ChildProcess.make(sandbox.command, sandbox.args, {
      cwd: sandbox.cwd, env: sandbox.env, extendEnv: false, forceKillAfter: "3 seconds",
    }), { stdin: JSON.stringify({ tool_id: input.tool_id, args: input.args, context, python_paths: libraries }),
      signal, timeout: "10 minutes", maxOutputBytes: 8_000_000, maxErrorBytes: 0 })
    yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
    if (result.exitCode !== 0 || result.stdoutTruncated) return { ok: false as const, reason: "旧组件隔离执行未完整返回；请核对原调用回执。" }
    return Result.parse(JSON.parse(result.stdout.toString("utf8")))
  }).pipe(Effect.ensuring(Effect.promise(sandbox.dispose)))
})

export * as QuantCodeLegacyTools from "./legacy-tools"

import path from "node:path"
import { lstat, realpath } from "node:fs/promises"
import { Effect } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { z } from "zod"
import { Database } from "@opencode-ai/core/database/database"
import { AppProcess } from "@opencode-ai/core/process"
import type { FSUtil } from "@opencode-ai/core/fs-util"
import { QuantCodeAccess } from "./access"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"
import { split, join, readFile, syncFile } from "@/util/bom"

const fingerprint = z.discriminatedUnion("exists", [
  z.object({ exists: z.literal(false) }).strict(),
  z.object({ exists: z.literal(true), sha256: z.string().regex(/^[a-f0-9]{64}$/),
    device: z.string(), inode: z.string(), modified: z.string(), changed: z.string(), mode: z.number().int(),
  }).strict(),
])
export type Snapshot = {
  exists: boolean
  text: string
  bom: boolean
  token?: { path: string; root: string; rootDevice: string; rootInode: string; fingerprint: z.infer<typeof fingerprint> }
}
export type BytesSnapshot = Pick<Snapshot, "exists" | "token"> & { content: Uint8Array }

/** Fixed stdlib helper shared by edits and descriptor-relative directory reads.
 * It accepts data only; the interpreter, source root and module are host-owned. */
export const runHost = Effect.fn("QuantCodeFileMutation.runHost")(function* (
  processes: AppProcess.Interface, request: Record<string, unknown>, signal?: AbortSignal, maxOutputBytes = 48 * 1024 * 1024,
) {
  const python = process.env.QUANTCODE_HOST_PYTHON
  const configuredRoot = process.env.QUANTCODE_BACKEND_ROOT
  if (!python || !path.isAbsolute(python) || !configuredRoot || !path.isAbsolute(configuredRoot)) {
    throw new Error("QuantCode 受控文件服务宿主未配置。")
  }
  const backend = yield* Effect.promise(() => realpath(configuredRoot))
  return yield* processes.run(ChildProcess.make(python, ["-I", "-S", "-B", "-c",
    "import sys; sys.path.insert(0, sys.argv.pop(1)); from quantcode.file_mutation import main; main()", backend], {
    cwd: backend, stderr: "ignore", extendEnv: false, forceKillAfter: "3 seconds", env: { LANG: "C.UTF-8" },
  }), { stdin: JSON.stringify(request), signal, timeout: "30 seconds", maxOutputBytes, maxErrorBytes: 0 }).pipe(Effect.orDie)
})

/** Bind existing host services once at native-tool initialization. Governance
 * and durable receipts remain in Tool.define; this adds only the filesystem
 * primitive missing from Node (descriptor-relative open/replace/unlink). */
export const make = Effect.fn("QuantCodeFileMutation.make")(function* (fs: FSUtil.Interface) {
  const database = yield* Database.Service
  const processes = yield* AppProcess.Service
  const invoke = Effect.fn("QuantCodeFileMutation.invoke")(function* (
    sessionID: string, filePath: string, action: "read" | "write" | "delete", expected?: Pick<Snapshot, "exists" | "token">, content?: string | Uint8Array, signal?: AbortSignal, executable?: boolean,
  ) {
    signal?.throwIfAborted()
    const owner = yield* QuantCodeAccess.requireSession(sessionID).pipe(Effect.provideService(Database.Service, database))
    if (!owner) throw new QuantCodeIdentity.IdentityError()
    const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(owner.directory, action === "read" ? "read" : "write", owner.identity))
    const target = yield* Effect.promise(() => QuantCodeWorkspace.target(grant, filePath, action === "read" ? "read" : "write"))
    const relative = path.relative(grant.root, target)
    if (!relative) throw new QuantCodeWorkspace.WorkspaceDenied("文件操作不能替换工作区根目录。")
    const rootInfo = yield* Effect.promise(() => lstat(grant.root, { bigint: true }))
    const rootDevice = rootInfo.dev.toString()
    const rootInode = rootInfo.ino.toString()
    if (action !== "read" && (!expected?.token || expected.token.path !== target || expected.token.root !== grant.root ||
        expected.token.rootDevice !== rootDevice || expected.token.rootInode !== rootInode)) {
      throw new Error("文件或工作区在预览后已变化，请重新读取后编辑。")
    }
    const denied: string[] = [".git"]
    for (const reserved of QuantCodeWorkspace.privatePaths(grant.root)) {
      const actual = yield* Effect.promise(() => QuantCodeWorkspace.canonical(reserved))
      if (QuantCodeWorkspace.contains(grant.root, actual)) denied.push(path.relative(grant.root, actual).split(path.sep).join("/"))
    }
    const output = yield* runHost(processes, { version: 1, action, root: grant.root, relative: relative.split(path.sep).join("/"),
      root_device: rootDevice, root_inode: rootInode, denied,
      ...(action !== "read" ? { expected: expected!.token!.fingerprint } : {}),
      ...(action === "write" ? { content: (typeof content === "string" ? Buffer.from(content, "utf8") : Buffer.from(content!)).toString("base64") } : {}),
      ...(action === "write" && executable !== undefined ? { executable } : {}),
    }, signal)
    if (output.exitCode !== 0 || output.stdoutTruncated) throw new Error("受控文件操作未确认完成，请重新核对文件状态。")
    let value: unknown
    try { value = JSON.parse(output.stdout.toString("utf8")) } catch { throw new Error("受控文件服务响应无效。") }
    const result = z.object({ ok: z.literal(true), snapshot: fingerprint, content: z.string() }).strict().safeParse(value)
    if (!result.success) {
      const failure = z.object({ ok: z.literal(false), code: z.string() }).safeParse(value)
      throw new Error(failure.success && failure.data.code === "stale"
        ? "文件在预览后已变化，请重新读取后编辑。"
        : failure.success && failure.data.code === "unsupported_platform"
          ? "此宿主不支持所需的文件句柄隔离，不能降级为普通路径写入。"
          : "受控文件操作被拒绝，请检查工作区权限、符号链接和文件状态。")
    }
    const current = yield* QuantCodeAccess.requireSession(sessionID).pipe(Effect.provideService(Database.Service, database))
    if (!current || current.identity.session_id !== owner.identity.session_id) throw new QuantCodeIdentity.IdentityError()
    yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
    return { ...result.data, token: { path: target, root: grant.root, rootDevice, rootInode, fingerprint: result.data.snapshot } }
  })
  const read = Effect.fn("QuantCodeFileMutation.read")(function* (sessionID: string, filePath: string, signal?: AbortSignal) {
    if (!QuantCodeIdentity.enabled()) {
      const exists = yield* fs.existsSafe(filePath)
      if (exists && (yield* fs.stat(filePath).pipe(Effect.orDie)).type === "Directory") {
        throw new Error(`Cannot edit a directory: ${filePath}`)
      }
      return { exists, ...(exists ? yield* readFile(fs, filePath).pipe(Effect.orDie) : { bom: false, text: "" }) }
    }
    const result = yield* invoke(sessionID, filePath, "read", undefined, undefined, signal)
    return { exists: result.snapshot.exists, ...split(new TextDecoder("utf-8", { ignoreBOM: true }).decode(Buffer.from(result.content, "base64"))), token: result.token }
  })
  const write = (sessionID: string, filePath: string, content: string, expected: Snapshot, signal?: AbortSignal) => QuantCodeIdentity.enabled()
    ? invoke(sessionID, filePath, "write", expected, content, signal).pipe(Effect.asVoid)
    : fs.writeWithDirs(filePath, content).pipe(Effect.orDie)
  const readBytes = Effect.fn("QuantCodeFileMutation.readBytes")(function* (sessionID: string, filePath: string, signal?: AbortSignal) {
    if (!QuantCodeIdentity.enabled()) throw new Error("原始字节文件服务只用于 QuantCode 受控操作。")
    const result = yield* invoke(sessionID, filePath, "read", undefined, undefined, signal)
    return { exists: result.snapshot.exists, content: Buffer.from(result.content, "base64"), token: result.token } satisfies BytesSnapshot
  })
  const writeBytes = (sessionID: string, filePath: string, content: Uint8Array, expected: BytesSnapshot, signal?: AbortSignal, executable?: boolean) =>
    invoke(sessionID, filePath, "write", expected, content, signal, executable).pipe(Effect.asVoid)
  const remove = (sessionID: string, filePath: string, expected: Pick<Snapshot, "exists" | "token">, signal?: AbortSignal) => QuantCodeIdentity.enabled()
    ? invoke(sessionID, filePath, "delete", expected, undefined, signal).pipe(Effect.asVoid)
    : fs.remove(filePath).pipe(Effect.orDie)
  const syncBom = Effect.fn("QuantCodeFileMutation.syncBom")(function* (sessionID: string, filePath: string, bom: boolean, signal?: AbortSignal) {
    if (!QuantCodeIdentity.enabled()) return yield* syncFile(fs, filePath, bom).pipe(Effect.orDie)
    const current = yield* read(sessionID, filePath, signal)
    if (!current.exists) throw new Error("格式化后的文件不存在，请重新核对文件状态。")
    if (current.bom !== bom) yield* write(sessionID, filePath, join(current.text, bom), current, signal)
    return current.text
  })
  return { read, write, remove, syncBom, readBytes, writeBytes }
})

export * as QuantCodeFileMutation from "./file-mutation"

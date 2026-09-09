import { Effect, Layer } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { AppProcess } from "@opencode-ai/core/process"
import { Ripgrep } from "@opencode-ai/core/ripgrep"
import { RipgrepBinary } from "@opencode-ai/core/ripgrep/binary"
import { which } from "@opencode-ai/core/util/which"
import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"
import { QuantCodeProcessSandbox } from "./process-sandbox"
import { QuantCodeFileMutation } from "./file-mutation"
import { constants } from "node:fs"
import type { BigIntStats } from "node:fs"
import { lstat, open } from "node:fs/promises"
import path from "node:path"
import fuzzysort from "fuzzysort"
import type { Match } from "@opencode-ai/schema/filesystem"
import os from "node:os"
import { z } from "zod"

export async function references(directory: string, configured: Record<string, unknown>) {
  const grant = await QuantCodeWorkspace.authorize(directory)
  const result: { name: string; path: string; description?: string }[] = []
  for (const [name, item] of Object.entries(configured)) {
    const data = item && typeof item === "object" ? item as Record<string, unknown> : undefined
    if (data?.hidden === true) continue
    const requested = typeof item === "string" && /^[.~\/]/.test(item) ? item : typeof data?.path === "string" ? data.path : undefined
    if (!requested) continue
    const expanded = requested.startsWith("~/") ? path.join(os.homedir(), requested.slice(2)) : path.resolve(directory, requested)
    const reference = await QuantCodeWorkspace.authorize(expanded, "read", grant.identity).catch(() => undefined)
    if (!reference) continue
    result.push({ name, path: reference.directory, ...(typeof data?.description === "string" ? { description: data.description } : {}) })
    await QuantCodeWorkspace.revalidate(reference)
  }
  await QuantCodeWorkspace.revalidate(grant)
  return result
}

export async function visible(grant: WorkspaceGrant, requested: string) {
  const target = await QuantCodeWorkspace.target(grant, requested).catch(() => undefined)
  if (!target) return false
  const info = await lstat(target).catch(() => undefined)
  return !!info && (!info.isFile() || info.nlink === 1)
}

export async function contextText(grant: WorkspaceGrant, requested: string) {
  const file = await QuantCodeWorkspace.openFile(grant, requested)
  try {
    if (file.size > 262144) throw new Error("工作区上下文文件超过 256 KB，请按需读取相关部分。")
    const text = await file.handle.readFile("utf8")
    if (Buffer.byteLength(text, "utf8") > 262144) throw new Error("工作区上下文文件超过大小限制。")
    await file.validate()
    return text
  } finally {
    await file.close()
  }
}

/** Do not release content obtained through a path that changed while ripgrep
 * ran. Check returned text and submatches against the authorized descriptor;
 * keep Core's regex engine, parsing, line numbers and presentation unchanged. */
export async function visibleMatch(grant: WorkspaceGrant, cwd: string, match: Match) {
  const file = await QuantCodeWorkspace.openFile(grant, path.resolve(cwd, match.entry.path)).catch(() => undefined)
  if (!file) return false
  try {
    const bytes = Buffer.alloc(Math.min(65536, Math.max(0, file.size - match.offset)))
    const result = await file.handle.read(bytes, 0, bytes.length, match.offset)
    const content = bytes.subarray(0, result.bytesRead)
    const expected = match.text.length === 2003 && match.text.endsWith("...") ? match.text.slice(0, -3) : match.text
    if (!content.toString("utf8").startsWith(expected)) return false
    for (const part of match.submatches) {
      if (part.start < 0 || part.end > content.length ||
        content.subarray(part.start, part.end).toString("utf8") !== part.text) return false
    }
    await file.validate()
    return true
  } finally {
    await file.close()
  }
}

/** Reuse Core's ripgrep parser, limits and process lifecycle. Only the process
 * service is replaced for this request, before discovery or content scanning. */
export const search = <A, E>(grant: WorkspaceGrant, process: AppProcess.Interface,
  use: (service: Ripgrep.Interface) => Effect.Effect<A, E>) => Effect.scoped(Effect.gen(function* () {
  const binary = which("rg", { PATH: "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" })
  if (!binary) throw new Error("本机尚未安装搜索工具，请由宿主安装 ripgrep 后重试。")
  const controlled = {
    ...process,
    spawn: (command: ChildProcess.Command) => Effect.gen(function* () {
      if (command._tag !== "StandardCommand") throw new Error("文件检索不接受 Shell 管道。")
      const directory = yield* Effect.promise(() => QuantCodeWorkspace.target(grant, command.options.cwd ?? grant.directory))
      const exclusions: string[] = []
      for (const reserved of QuantCodeWorkspace.privatePaths(grant.root)) {
        const target = yield* Effect.promise(() => QuantCodeWorkspace.canonical(reserved))
        if (!QuantCodeWorkspace.contains(directory, target)) continue
        const relative = path.relative(directory, target).split(path.sep).join("/").replace(/[\\*?\[\]{}]/g, "\\$&")
        exclusions.push(`--glob=!/${relative}`, `--glob=!/${relative}/**`)
      }
      const sandbox = yield* Effect.acquireRelease(Effect.promise(() => QuantCodeProcessSandbox.prepare({
        grant: { ...grant, directory }, command: command.command,
        args: (() => {
          const delimiter = command.args.indexOf("--")
          const index = delimiter < 0 ? command.args.length - 1 : delimiter
          return [...command.args.slice(0, index), ...exclusions, ...command.args.slice(index)]
        })(), writePaths: [],
      })), value => Effect.promise(() => value.dispose()))
      return yield* process.spawn(ChildProcess.make(sandbox.command, sandbox.args, {
        cwd: sandbox.cwd, env: sandbox.env, extendEnv: false, stdin: "ignore", forceKillAfter: "2 seconds",
      }))
    }),
  } satisfies AppProcess.Interface
  const layer = Ripgrep.layer.pipe(
    Layer.provide(Layer.succeed(AppProcess.Service, controlled)),
    Layer.provide(Layer.succeed(RipgrepBinary.Service, { filepath: Effect.succeed(binary) })),
  )
  const work = Ripgrep.Service.use(use).pipe(Effect.provide(layer), Effect.timeout("30 seconds"))
  const watch: Effect.Effect<never> = Effect.gen(function* () {
    while (true) {
      yield* Effect.sleep("2 seconds")
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
    }
  })
  const result = yield* Effect.raceFirst(work, watch)
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
  return result
}))

const directorySnapshot = z.object({ device: z.string(), inode: z.string(), modified: z.string(), changed: z.string() }).strict()
const directoryListing = z.object({ ok: z.literal(true), directory: directorySnapshot,
  entries: z.array(directorySnapshot.extend({ name: z.string().min(1).max(1024), type: z.enum(["file", "directory"]), links: z.string() }).strict()).max(10000),
}).strict()

function snapshot(info: BigIntStats) {
  return { device: info.dev.toString(), inode: info.ino.toString(), modified: info.mtimeNs.toString(), changed: info.ctimeNs.toString() }
}

/** The helper opens every component with openat + NOFOLLOW, binds to this
 * verified descriptor's identity and timestamps, then uses scandir(fd). Node's
 * /dev/fd directory paths cannot be re-opened for enumeration on macOS. */
export const list = (grant: WorkspaceGrant, requested: string, processes: AppProcess.Interface, signal?: AbortSignal) => Effect.scoped(Effect.gen(function* () {
  signal?.throwIfAborted()
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
  const target = yield* Effect.promise(() => QuantCodeWorkspace.target(grant, requested))
  if (process.platform !== "darwin" && process.platform !== "linux") {
    throw new QuantCodeWorkspace.WorkspaceDenied("此平台尚未提供安全的目录句柄读取。")
  }
  const handle = yield* Effect.acquireRelease(
    Effect.promise(() => open(target, constants.O_RDONLY | constants.O_DIRECTORY | (constants.O_NOFOLLOW ?? 0))),
    file => Effect.promise(() => file.close()),
  )
  const before = yield* Effect.promise(() => handle.stat({ bigint: true }))
  if (!before.isDirectory()) throw new QuantCodeWorkspace.WorkspaceDenied("该路径不是目录。")
  const root = yield* Effect.promise(() => lstat(grant.root, { bigint: true }))
  const denied = new Set<string>()
  for (const reserved of QuantCodeWorkspace.privatePaths(grant.root)) {
    const canonical = yield* Effect.promise(() => QuantCodeWorkspace.canonical(reserved))
    for (const entry of [canonical, path.resolve(reserved)]) {
      if (!QuantCodeWorkspace.contains(grant.root, entry)) continue
      const relative = path.relative(grant.root, entry).split(path.sep).join("/")
      if (!relative) throw new QuantCodeWorkspace.WorkspaceDenied()
      denied.add(relative)
    }
  }
  const output = yield* QuantCodeFileMutation.runHost(processes, { version: 1, action: "list", root: grant.root,
    relative: path.relative(grant.root, target).split(path.sep).join("/"),
    root_device: root.dev.toString(), root_inode: root.ino.toString(), denied: [...denied],
    expected_directory: snapshot(before),
  }, signal, 8 * 1024 * 1024)
  if (output.exitCode !== 0 || output.stdoutTruncated) throw new QuantCodeWorkspace.WorkspaceDenied("目录读取未完成或条目过多，请缩小目录范围。")
  let value: unknown
  try { value = JSON.parse(output.stdout.toString("utf8")) } catch { throw new QuantCodeWorkspace.WorkspaceDenied("受控目录服务返回无效数据。") }
  const parsed = directoryListing.safeParse(value)
  if (!parsed.success) {
    const failure = z.object({ ok: z.literal(false), code: z.string() }).safeParse(value)
    throw new QuantCodeWorkspace.WorkspaceDenied(failure.success && failure.data.code === "directory_too_large"
      ? "目录超过 10000 个条目，请选择更具体的研究子目录。"
      : "目录读取被拒绝，可能包含变化中的路径或此宿主不支持安全目录句柄。请重新选择目录。")
  }
  if (JSON.stringify(parsed.data.directory) !== JSON.stringify(snapshot(before))) throw new QuantCodeWorkspace.WorkspaceDenied("读取期间目录已变化，请重试。")
  const seen = new Set<string>()
  const result = yield* Effect.forEach(parsed.data.entries, entry => Effect.promise(async () => {
    signal?.throwIfAborted()
    if ([".", ".."].includes(entry.name) || entry.name.includes("/") || entry.name.includes("\0") || seen.has(entry.name)) throw new QuantCodeWorkspace.WorkspaceDenied("受控目录条目无效。")
    seen.add(entry.name)
    const absolute = path.join(target, entry.name)
    const actual = await QuantCodeWorkspace.target(grant, absolute).catch(() => undefined)
    if (!actual || actual !== absolute) return
    const info = await lstat(absolute, { bigint: true })
    if (info.isSymbolicLink() || (!info.isDirectory() && !info.isFile()) || info.isFile() && info.nlink !== 1n) return
    if (info.dev.toString() !== entry.device || info.ino.toString() !== entry.inode || info.mtimeNs.toString() !== entry.modified ||
        info.ctimeNs.toString() !== entry.changed || info.nlink.toString() !== entry.links ||
        (info.isDirectory() ? "directory" : "file") !== entry.type) throw new QuantCodeWorkspace.WorkspaceDenied("读取期间目录条目已变化，请重试。")
    return { name: entry.name, absolute, path: path.relative(grant.directory, absolute), type: entry.type }
  }))
  const resolved = yield* Effect.promise(() => QuantCodeWorkspace.target(grant, requested))
  const linked = yield* Effect.promise(() => lstat(resolved, { bigint: true }))
  const after = yield* Effect.promise(() => handle.stat({ bigint: true }))
  if (resolved !== target || linked.isSymbolicLink() || JSON.stringify(snapshot(before)) !== JSON.stringify(snapshot(linked)) ||
      JSON.stringify(snapshot(before)) !== JSON.stringify(snapshot(after))) {
    throw new QuantCodeWorkspace.WorkspaceDenied("读取期间目录已变化，请重试。")
  }
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
  signal?.throwIfAborted()
  return result.filter(entry => entry !== undefined).sort((a, b) => a.name.localeCompare(b.name))
}))

export const find = (grant: WorkspaceGrant, process: AppProcess.Interface,
  input: { query: string; limit: number; type?: "file" | "directory" }) => Effect.gen(function* () {
  const entries = yield* search(grant, process, service => service.find({ cwd: grant.directory, pattern: "*", limit: 100000 }))
  const files = (yield* Effect.forEach(entries, entry => Effect.promise(async () =>
    await visible(grant, entry.path) ? entry.path : undefined))).filter(entry => entry !== undefined)
  const directories = new Set<string>()
  for (const file of files) {
    const parts = file.split("/")
    for (let index = 1; index < parts.length; index++) directories.add(parts.slice(0, index).join("/") + "/")
  }
  const candidates = input.type === "file" ? files : input.type === "directory" ? [...directories] : [...files, ...directories]
  const found = fuzzysort.go(input.query, candidates, { limit: input.limit }).map(item => item.target)
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
  return found
})

export * as QuantCodeReadAccess from "./read-access"

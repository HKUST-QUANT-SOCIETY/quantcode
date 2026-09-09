/** QuantCode policy around OpenCode's existing Git-tree snapshot format.
 * The object store is private per owner/workspace. Git never reads the research
 * checkout: only bytes admitted by Workspace.openFile reach hash-object stdin. */
import path from "node:path"
import { isUtf8 } from "node:buffer"
import { mkdir, mkdtemp, lstat, readdir, realpath, rm } from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { Effect } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { formatPatch, structuredPatch } from "diff"
import ignore from "ignore"
import { AppProcess } from "@opencode-ai/core/process"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { Global } from "@opencode-ai/core/global"
import { Database } from "@opencode-ai/core/database/database"
import { which } from "@opencode-ai/core/util/which"
import { EventV2Bridge } from "@/event-v2-bridge"
import { InstanceState } from "@/effect/instance-state"
import { Config } from "@/config/config"
import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeToolCatalog } from "./tool-catalog"
import { QuantCodeAccess } from "./access"
import { QuantCodeFileMutation } from "./file-mutation"
import { QuantCodeWritePolicy } from "./write-policy"
import { QuantCodeWriteReceipt } from "./write-receipt"
import type { Snapshot } from "@/snapshot"

const oid = /^[a-f0-9]{40}$/
const limit = 2 * 1024 * 1024
type Tree = Map<string, { hash: string; mode: string }>
type Store = { directory: string; gitdir: string; index: string; grant: WorkspaceGrant }

export const make = Effect.fn("QuantCodeSnapshotAccess.make")(function* () {
  const processes = yield* AppProcess.Service
  const database = yield* Database.Service
  const events = yield* EventV2Bridge.Service
  const fs = yield* FSUtil.Service
  const config = yield* Config.Service
  const mutation = yield* QuantCodeFileMutation.make(fs)
  const git = Effect.fn("QuantCodeSnapshotAccess.git")(function* (store: Store, args: string[], stdin?: Uint8Array | string) {
    const executable = which("git", { PATH: process.platform === "win32" ? process.env.PATH : "/usr/bin:/bin:/opt/homebrew/bin" })
    if (!executable) throw new Error("快照需要宿主 Git。")
    const result = yield* processes.run(ChildProcess.make(executable, [
      "-c", "core.hooksPath=" + path.join(store.directory, "disabled-hooks"), "-c", "core.fsmonitor=false",
      "-c", "core.attributesFile=" + (process.platform === "win32" ? "NUL" : "/dev/null"),
      "-c", "core.quotepath=false", "--git-dir", store.gitdir, ...args,
    ], { cwd: store.directory, extendEnv: false, forceKillAfter: "3 seconds", env: {
      PATH: path.dirname(executable), HOME: store.directory, XDG_CONFIG_HOME: store.directory,
      GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: process.platform === "win32" ? "NUL" : "/dev/null",
      GIT_INDEX_FILE: store.index,
      GIT_ATTR_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0", LANG: "C.UTF-8",
      ...(process.platform === "win32" && process.env.SystemRoot ? { SystemRoot: process.env.SystemRoot } : {}),
    } }), { stdin, timeout: "30 seconds", maxOutputBytes: 32 * 1024 * 1024, maxErrorBytes: 4096 }).pipe(Effect.orDie)
    if (result.exitCode !== 0 || result.stdoutTruncated) throw new Error("快照 Git 操作未完成，未确认恢复任何文件。")
    return result.stdout
  })

  function withStore<A, E, R>(operation: (store: Store) => Effect.Effect<A, E, R>) {
    return Effect.scoped(Effect.gen(function* () {
      const ctx = yield* InstanceState.context
      const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(ctx.directory))
      const key = QuantCodeToolCatalog.digest({ owner: QuantCodeIdentity.ownerOf(grant.identity), root: grant.root, directory: grant.directory })
      const directory = path.join(Global.Path.data, "snapshot", "quantcode", key)
      yield* Effect.promise(async () => {
        await mkdir(directory, { recursive: true, mode: 0o700 })
        const info = await lstat(directory)
        if (!info.isDirectory() || info.isSymbolicLink() || await realpath(directory) !== directory ||
            process.platform !== "win32" && (info.mode & 0o077 || process.getuid && info.uid !== process.getuid())) {
          throw new Error("快照对象库必须由宿主私有管理。")
        }
      })
      // Git already writes immutable objects atomically. A private index per
      // operation avoids a second cross-process snapshot lock/recovery system.
      const temporary = yield* Effect.acquireRelease(
        Effect.promise(() => mkdtemp(path.join(directory, "operation-"))),
        temporary => Effect.promise(() => rm(temporary, { recursive: true, force: true })),
      )
      const store: Store = { directory, gitdir: path.join(directory, "objects.git"), index: path.join(temporary, "index"), grant }
      const exists = yield* Effect.promise(() => lstat(store.gitdir).catch(error => {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined
        throw error
      }))
      if (!exists) yield* git(store, ["init", "--bare", "--template="])
      if (exists?.isSymbolicLink() || exists && !exists.isDirectory()) throw new Error("快照对象库路径无效。")
      const result = yield* operation(store)
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
      return result
    })).pipe(Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events),
      Effect.provideService(AppProcess.Service, processes))
  }

  const tree = Effect.fn("QuantCodeSnapshotAccess.tree")(function* (store: Store, hash: string) {
    if (!oid.test(hash)) throw new Error("快照标识无效。")
    const output = yield* git(store, ["ls-tree", "-r", "-z", hash])
    const files: Tree = new Map()
    for (const entry of output.toString("utf8").split("\0").filter(Boolean)) {
      const match = /^(100644|100755) blob ([a-f0-9]{40})\t([\s\S]+)$/.exec(entry)
      if (!match || path.isAbsolute(match[3]) || match[3].split("/").some(part => ["", ".", "..", ".git"].includes(part))) {
        throw new Error("快照包含不支持的路径、符号链接或子模块。")
      }
      const target = path.join(store.grant.directory, match[3])
      if ((yield* Effect.promise(() => QuantCodeWorkspace.target(store.grant, target))) !== target) throw new Error("快照文件路径已经改变。")
      files.set(match[3], { mode: match[1], hash: match[2] })
    }
    return files
  })

  const capture = Effect.fn("QuantCodeSnapshotAccess.capture")(function* (store: Store) {
    const files: string[] = []
    const walk = async (directory: string, rules: { base: string; value: ReturnType<typeof ignore> }[]) => {
      const actual = await QuantCodeWorkspace.target(store.grant, directory)
      if (actual !== directory) throw new Error("快照读取期间目录已经改变。")
      const patternFile = path.join(directory, ".gitignore")
      const patternInfo = await lstat(patternFile).catch(error => {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined
        throw error
      })
      const localRules = [...rules]
      if (patternInfo?.isFile() && !patternInfo.isSymbolicLink()) {
        const patterns = await QuantCodeWorkspace.readFile(store.grant, patternFile)
        localRules.push({ base: directory, value: ignore().add(patterns.content.toString("utf8")) })
      }
      for (const entry of await readdir(directory, { withFileTypes: true })) {
        if ([".git", ".quantcode", ".opencode", "opencode.json", "opencode.jsonc", "opencode.config.ts"].includes(entry.name) || entry.isSymbolicLink()) continue
        const filename = path.join(directory, entry.name)
        const relative = path.relative(store.grant.directory, filename).split(path.sep).join("/")
        const ignored = localRules.reduce((previous, rule) => {
          const match = rule.value.test(path.relative(rule.base, filename).split(path.sep).join("/") + (entry.isDirectory() ? "/" : ""))
          return match.ignored ? true : match.unignored ? false : previous
        }, false)
        if (ignored) continue
        try { await QuantCodeWorkspace.target(store.grant, filename) } catch (error) {
          if (error instanceof QuantCodeWorkspace.WorkspaceDenied) continue
          throw error
        }
        if (entry.isDirectory()) { await walk(filename, localRules); continue }
        if (!entry.isFile()) continue
        files.push(relative)
      }
      await QuantCodeWorkspace.revalidate(store.grant)
    }
    yield* Effect.promise(() => walk(store.grant.directory, []))
    yield* git(store, ["read-tree", "--empty"])
    const entries = yield* Effect.forEach(files, file => Effect.scoped(Effect.gen(function* () {
        const opened = yield* Effect.acquireRelease(
          Effect.promise(() => QuantCodeWorkspace.openFile(store.grant, file)), opened => Effect.promise(() => opened.close()),
        )
        if (opened.size > limit) return
        const info = yield* Effect.promise(() => opened.handle.stat())
        const content = yield* Effect.promise(() => opened.handle.readFile())
        yield* Effect.promise(() => opened.validate())
        const hash = (yield* git(store, ["hash-object", "-w", "--stdin"], content)).toString("utf8").trim()
        if (!oid.test(hash)) throw new Error("快照对象写入失败。")
        return `${info.mode & 0o111 ? "100755" : "100644"} ${hash}\t${file}\0`
      })), { concurrency: 8 })
    const staged = entries.filter((entry): entry is string => entry !== undefined)
    if (staged.length) yield* git(store, ["update-index", "-z", "--index-info"], staged.join(""))
    if (staged.length !== files.length) yield* Effect.logInfo("snapshot skipped files above per-file capture limit", { count: files.length - staged.length, limit })
    const hash = (yield* git(store, ["write-tree"])).toString("utf8").trim()
    if (!oid.test(hash)) throw new Error("快照树写入失败。")
    return hash
  })

  const differences = Effect.fn("QuantCodeSnapshotAccess.differences")(function* (store: Store, from: string, to: string) {
    const before = yield* tree(store, from)
    const after = yield* tree(store, to)
    const result: Snapshot.FileDiff[] = []
    for (const file of [...new Set([...before.keys(), ...after.keys()])].sort()) {
      if (before.get(file)?.hash === after.get(file)?.hash && before.get(file)?.mode === after.get(file)?.mode) continue
      const left = before.has(file) ? yield* git(store, ["cat-file", "blob", before.get(file)!.hash]) : Buffer.alloc(0)
      const right = after.has(file) ? yield* git(store, ["cat-file", "blob", after.get(file)!.hash]) : Buffer.alloc(0)
      const binary = left.includes(0) || right.includes(0) || !isUtf8(left) || !isUtf8(right)
      const patch = binary ? undefined : structuredPatch(file, file, left.toString("utf8"), right.toString("utf8"), "", "", { context: Number.MAX_SAFE_INTEGER })
      result.push({ file, status: !before.has(file) ? "added" : !after.has(file) ? "deleted" : "modified",
        patch: patch ? formatPatch(patch) : "",
        additions: patch?.hunks.reduce((sum, hunk) => sum + hunk.lines.filter(line => line.startsWith("+")).length, 0) ?? 0,
        deletions: patch?.hunks.reduce((sum, hunk) => sum + hunk.lines.filter(line => line.startsWith("-")).length, 0) ?? 0 })
    }
    return result
  })

  const apply = Effect.fn("QuantCodeSnapshotAccess.apply")(function* (store: Store, sessionID: string | undefined, patches: Snapshot.Patch[], kind: string) {
    if (!sessionID) throw new Error("恢复快照必须绑定当前任务。")
    const access = yield* QuantCodeAccess.requireSession(sessionID)
    if (!access || access.identity.session_id !== store.grant.identity.session_id || access.directory !== store.grant.directory) throw new QuantCodeIdentity.IdentityError()
    const targets = new Map<string, { hash: string | undefined; mode: string | undefined }>()
    for (const patch of patches) {
      const source = yield* tree(store, patch.hash)
      for (const file of patch.files) {
        const target = yield* Effect.promise(() => QuantCodeWorkspace.target(store.grant, file, "write"))
        if (!QuantCodeWorkspace.contains(store.grant.directory, target)) throw new Error("恢复范围不属于快照工作目录。")
        if (targets.has(target)) continue
        const entry = source.get(path.relative(store.grant.directory, target).split(path.sep).join("/"))
        targets.set(target, { hash: entry?.hash, mode: entry?.mode })
      }
    }
    const files = [...targets.keys()]
    if (!files.length) return
    const operation = randomUUID()
    yield* QuantCodeWritePolicy.guarded(sessionID, files, scope => Effect.gen(function* () {
      const prepared: { file: string; expected: QuantCodeFileMutation.BytesSnapshot;
        content: Buffer | undefined; executable: boolean }[] = []
      for (const [file, target] of targets) {
        const expected = yield* mutation.readBytes(sessionID, file)
        const content = target.hash ? yield* git(store, ["cat-file", "blob", target.hash]) : undefined
        prepared.push({ file, expected, content, executable: target.mode === "100755" })
      }
      yield* QuantCodeWriteReceipt.run({ sessionID, messageID: `snapshot-${operation}`, callID: operation,
        tool: kind, args: { patches }, files, planHashes: scope.planHashes }, begin => Effect.gen(function* () {
        yield* begin
        for (const item of prepared) {
          yield* Effect.promise(() => QuantCodeWorkspace.revalidate(scope.grant))
          if (item.content) yield* mutation.writeBytes(sessionID, item.file, item.content, item.expected, undefined, item.executable)
          else if (item.expected.exists) yield* mutation.remove(sessionID, item.file, item.expected)
        }
        return { title: "恢复任务文件", output: `已恢复 ${files.length} 个文件。`, metadata: { files, snapshots: patches.map(item => item.hash) } }
      }))
    }))
  })

  return {
    cleanup: () => Effect.void, // Trees are durable task references; never prune unreferenced Git trees by age.
    track: () => Effect.gen(function* () {
      if ((yield* config.get()).snapshot === false) return
      return yield* withStore(store => capture(store))
    }),
    patch: (hash: string) => withStore(store => Effect.gen(function* () {
      const current = yield* capture(store)
      const changes = yield* differences(store, hash, current)
      return { hash, files: changes.map(change => path.join(store.grant.directory, change.file!)) }
    })),
    diff: (hash: string) => withStore(store => Effect.gen(function* () {
      const current = yield* capture(store)
      return (yield* differences(store, hash, current)).map(change => change.patch ?? "").join("\n")
    })),
    diffFull: (from: string, to: string) => withStore(store => differences(store, from, to)),
    revert: (patches: Snapshot.Patch[], sessionID?: string) => withStore(store => apply(store, sessionID, patches, "snapshot_revert")),
    restore: (hash: string, sessionID?: string) => withStore(store => Effect.gen(function* () {
      const current = yield* capture(store)
      const changes = yield* differences(store, current, hash)
      // Preserve OpenCode restore semantics: overlay the saved tree, leaving
      // unrelated files created after the snapshot intact. Patch revert owns
      // the separately enumerated deletion behavior.
      yield* apply(store, sessionID, [{ hash, files: changes.filter(change => change.status !== "deleted")
        .map(change => path.join(store.grant.directory, change.file!)) }], "snapshot_restore")
    })),
  }
})

export * as QuantCodeSnapshotAccess from "./snapshot-access"

import path from "node:path"
import { lstat, realpath, mkdir } from "node:fs/promises"
import { Effect } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeWorkspace } from "./workspace"
import { QuantCodeProcessSandbox } from "./process-sandbox"

const ref = (value: string | undefined) => typeof value === "string" && value.length > 0 && value.length < 1024 &&
  !value.startsWith("-") && !/[\x00-\x20\x7f]/.test(value)
const same = (args: string[], expected: string[]) => JSON.stringify(args) === JSON.stringify(expected)

/** Only the existing query grammar is admitted. Public Git.run is not a raw
 * escape hatch for aliases, config mutation, network or repository writes. */
export async function prepareRead(directory: string, original: readonly string[]) {
  const grant = await QuantCodeWorkspace.authorize(directory)
  const args = [...original]
  const command = args.shift()
  const separator = args.indexOf("--")
  const options = separator === -1 ? args : args.slice(0, separator)
  const paths = separator === -1 ? [] : args.slice(separator + 1)
  const simple = command === "rev-parse" && (["--show-prefix", "--show-toplevel", "--git-dir", "--git-common-dir", "HEAD"].some(item => same(args, [item])) || same(args, ["--verify", "HEAD"])) ||
    command === "symbolic-ref" && (same(args, ["--quiet", "--short", "HEAD"]) || args.length === 1 && /^refs\/remotes\/[^\s\0]+\/HEAD$/.test(args[0])) ||
    command === "remote" && (args.length === 0 || args.length === 2 && args[0] === "get-url" && ref(args[1])) ||
    command === "for-each-ref" && same(args, ["--format=%(refname:short)", "refs/heads"]) ||
    command === "config" && same(args, ["init.defaultBranch"]) ||
    command === "rev-list" && args.length === 2 && args[0] === "--max-parents=0" && ["HEAD", "--all"].includes(args[1]) ||
    command === "merge-base" && args.length === 2 && args.every(ref)
  const status = command === "status" && same(options, ["--porcelain=v1", "--untracked-files=all", "--no-renames", "-z"]) && same(paths, ["."])
  const diff = command === "diff" && separator !== -1 && options.every(value =>
    ["--no-index", "--patch", "--no-ext-diff", "--no-renames", "--name-status", "--numstat", "-z"].includes(value) ||
    /^--unified=\d+$/.test(value) || ref(value)) && options.filter(value => !value.startsWith("-")).length <= 1 &&
    (options.includes("--no-index") ? paths.length === 2 && paths[0] === "/dev/null" : paths.length === 1)
  const show = command === "show" && args.length === 1 && ref(args[0]) && args[0].includes(":")
  if (!simple && !status && !diff && !show) throw new QuantCodeWorkspace.WorkspaceDenied("此 Git 操作不属于已授权的只读查询；写操作需要具体任务和文件范围。")

  let root = grant.directory
  while (!await lstat(path.join(root, ".git")).then(() => true, (error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return false
    throw error
  })) {
    if (root === grant.root) break
    const parent = path.dirname(root)
    if (!QuantCodeWorkspace.contains(grant.root, parent)) break
    root = parent
  }
  const marker = path.join(root, ".git")
  const markerInfo = await lstat(marker).catch((error: NodeJS.ErrnoException) => { if (error.code === "ENOENT") return undefined; throw error })
  if (markerInfo?.isSymbolicLink()) throw new QuantCodeWorkspace.WorkspaceDenied("Git 元数据目录不能使用符号链接。")
  let actualGitDirectory = marker
  if (markerInfo?.isFile()) {
    if (markerInfo.size > 4096) throw new QuantCodeWorkspace.WorkspaceDenied("Git 工作树标识过大。")
    const record = (await QuantCodeWorkspace.readFile(grant, marker)).content.toString("utf8").trim()
    if (!record.startsWith("gitdir: ") || record.slice(8).includes("\n")) throw new QuantCodeWorkspace.WorkspaceDenied("Git 工作树标识无效。")
    actualGitDirectory = await QuantCodeWorkspace.target(grant, path.resolve(root, record.slice(8)))
  }
  if (markerInfo && actualGitDirectory) {
    await QuantCodeWorkspace.target(grant, actualGitDirectory)
    const common = path.join(actualGitDirectory, "commondir")
    const commonInfo = await lstat(common).catch((error: NodeJS.ErrnoException) => { if (error.code === "ENOENT") return undefined; throw error })
    if (commonInfo) {
      if (!commonInfo.isFile() || commonInfo.size > 4096) throw new QuantCodeWorkspace.WorkspaceDenied("Git 公共目录标识无效。")
      const relative = (await QuantCodeWorkspace.readFile(grant, common)).content.toString("utf8").trim()
      if (!relative || relative.includes("\n")) throw new QuantCodeWorkspace.WorkspaceDenied("Git 公共目录标识无效。")
      await QuantCodeWorkspace.target(grant, path.resolve(actualGitDirectory, relative))
    }
  }
  if (show) {
    const colon = args[0].indexOf(":")
    const filename = args[0].slice(colon + 1)
    if (!filename || path.isAbsolute(filename) || filename.split("/").includes("..")) throw new QuantCodeWorkspace.WorkspaceDenied()
    await QuantCodeWorkspace.target(grant, path.join(root, filename))
  }
  const resolvedPaths: string[] = []
  for (const filename of paths) {
    if (filename === "/dev/null") { resolvedPaths.push(filename); continue }
    if (filename.startsWith(":") || filename.includes("\0")) throw new QuantCodeWorkspace.WorkspaceDenied("Git 路径必须是明确文件名，不能注入 pathspec。")
    const actual = await QuantCodeWorkspace.target(grant, path.resolve(filename === "." ? grant.directory : root, filename))
    // porcelain v1 / diff -z file names are repository-root-relative even
    // when the app opened a nested directory. Preserve '.' as scoped query.
    resolvedPaths.push(filename === "." ? filename : actual)
  }
  const filtered = separator === -1 ? [...args] : [...options, "--", ...resolvedPaths]
  if ((status || diff) && !options.includes("--no-index")) {
    for (const reserved of QuantCodeWorkspace.privatePaths(root)) {
      const actual = await QuantCodeWorkspace.canonical(reserved)
      if (QuantCodeWorkspace.contains(actual, root)) throw new QuantCodeWorkspace.WorkspaceDenied()
      if (QuantCodeWorkspace.contains(root, actual)) filtered.push(`:(top,exclude,literal)${path.relative(root, actual).split(path.sep).join("/")}`)
    }
  }
  if (diff) filtered.unshift("--no-ext-diff", "--no-textconv", "--ignore-submodules=all")
  if (show) filtered.unshift("--no-ext-diff", "--no-textconv")
  const git = await realpath("/usr/bin/git").catch(() => realpath("/opt/homebrew/bin/git"))
  const sandbox = await QuantCodeProcessSandbox.prepare({ grant, command: git,
    args: ["--no-optional-locks", "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false", "-c", "core.longpaths=true",
      "-c", "core.symlinks=true", "-c", "core.quotepath=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat",
      "-c", "protocol.allow=never", command!, ...filtered], writePaths: [] })
  return { grant, sandbox }
}

export function publicOutput(args: readonly string[], stdout: Buffer) {
  if (args[0] !== "remote" || args[1] !== "get-url") return stdout
  const value = stdout.toString("utf8").trim()
  if (!/^https?:\/\//i.test(value)) return stdout
  const url = new URL(value)
  url.username = ""
  url.password = ""
  url.search = ""
  url.hash = ""
  return Buffer.from(url.toString() + "\n")
}

/** Initialize metadata for a newly enrolled workspace. This host action is
 * separate from read queries and never grants an Agent writable .git access. */
export const init = Effect.fn("QuantCodeGitAccess.init")(function* (directory: string, signal?: AbortSignal) {
  signal?.throwIfAborted()
  const processes = yield* AppProcess.Service
  const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(directory, "write"))
  if (grant.directory !== grant.root) throw new QuantCodeWorkspace.WorkspaceDenied("请为项目根目录登记独立工作区后初始化 Git。")
  const target = path.join(grant.root, ".git")
  yield* Effect.promise(() => QuantCodeWorkspace.target(grant, target, "write"))
  const root = yield* Effect.promise(() => lstat(grant.root, { bigint: true }))
  const python = process.env.QUANTCODE_HOST_PYTHON
  const configured = process.env.QUANTCODE_BACKEND_ROOT
  if (!python || !path.isAbsolute(python) || !configured || !path.isAbsolute(configured)) throw new Error("Git 初始化所需的宿主文件服务未配置。")
  const backend = yield* Effect.promise(() => realpath(configured))
  const created = yield* processes.run(ChildProcess.make(python, ["-I", "-S", "-B", "-c",
    "import sys; sys.path.insert(0, sys.argv.pop(1)); from quantcode.file_mutation import main; main()", backend], {
    cwd: backend, env: { LANG: "C.UTF-8" }, extendEnv: false, stderr: "ignore", forceKillAfter: "3 seconds",
  }), { stdin: JSON.stringify({ version: 1, action: "mkdir_git", root: grant.root, relative: ".git",
    root_device: root.dev.toString(), root_inode: root.ino.toString(), denied: [] }), signal,
    timeout: "15 seconds", maxOutputBytes: 16384, maxErrorBytes: 0 }).pipe(Effect.orDie)
  let record: { ok?: boolean; directory?: { device?: string; inode?: string } }
  try { record = JSON.parse(created.stdout.toString("utf8")) } catch { throw new Error("Git 元数据目录创建结果不明确，请核对目录状态。") }
  if (created.exitCode !== 0 || created.stdoutTruncated || record.ok !== true || !record.directory?.device || !record.directory.inode) {
    throw new Error("Git 元数据目录未创建；已有仓库或异常目录不会被覆盖。")
  }
  const pinned = record.directory
  const revalidate = async () => {
    await QuantCodeWorkspace.revalidate(grant)
    const info = await lstat(target, { bigint: true })
    if (!info.isDirectory() || info.isSymbolicLink() || info.dev.toString() !== pinned.device || info.ino.toString() !== pinned.inode || await realpath(target) !== target) {
      throw new Error("Git 初始化期间元数据目录发生变化，请核对后重试。")
    }
  }
  yield* Effect.promise(revalidate)
  const git = yield* Effect.promise(() => realpath("/usr/bin/git").catch(() => realpath("/opt/homebrew/bin/git")))
  return yield* Effect.scoped(Effect.gen(function* () {
    const sandbox = yield* Effect.acquireRelease(Effect.promise(() => QuantCodeProcessSandbox.prepare({
      grant, command: git, args: [], writePaths: [], controlWritePaths: [target],
    })), value => Effect.promise(() => value.dispose()))
    const template = path.join(sandbox.env.TMPDIR, "empty-git-template")
    yield* Effect.promise(() => mkdir(template, { mode: 0o700 }))
    // prepare's final argument is the fixed git executable. No shell expansion
    // or caller-controlled Git options are added to this metadata-only action.
    const args = [...sandbox.args, "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never", "init",
      `--template=${template}`, "--initial-branch=main", "--", grant.root]
    signal?.throwIfAborted()
    yield* Effect.promise(revalidate)
    const output = yield* processes.run(ChildProcess.make(sandbox.command, args, { cwd: sandbox.cwd, env: sandbox.env,
      extendEnv: false, stdin: "ignore", stderr: "ignore", forceKillAfter: "3 seconds" }), {
      signal, timeout: "30 seconds", maxOutputBytes: 16384, maxErrorBytes: 0,
    }).pipe(Effect.orDie)
    yield* Effect.promise(revalidate)
    if (output.exitCode !== 0 || output.stdoutTruncated) throw new Error("Git 初始化未完成；新建目录已保留以便核对，不会删除已有文件。")
  }))
})

export * as QuantCodeGitAccess from "./git-access"

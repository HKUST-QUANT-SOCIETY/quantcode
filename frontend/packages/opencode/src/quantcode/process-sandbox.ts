import { access, lstat, mkdir, mkdtemp, realpath, rm, open, type FileHandle } from "node:fs/promises"
import { constants } from "node:fs"
import path from "node:path"
import os from "node:os"
import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"

export type ProcessSandbox = {
  command: string
  args: string[]
  cwd: string
  env: Record<string, string>
  dispose: () => Promise<void>
}

/** These are trusted system runtimes, not user/project commands. HOME and all
 * credentials are excluded. A supplied program may read only these roots and
 * its granted workspace; network access is supplied by governed tools instead. */
const systemRoots = () => process.platform === "darwin"
  ? ["/usr", "/bin", "/sbin", "/System", "/Library/Apple", "/Library/Developer/CommandLineTools", "/opt/homebrew"]
  : ["/usr", "/bin", "/sbin", "/lib", "/lib64"]

const exists = (filename: string) => lstat(filename).then(() => true, () => false)
const literal = (value: string) => JSON.stringify(value)

/** Build an OS-enforced launch. writePaths comes from the trusted policy
 * decision, never the model's 'this command is read-only' declaration.
 * Empty writePaths is genuinely read-only outside its disposable scratch dir.
 * A terminal explicitly receives workspace write access, while Agent Shell
 * receives only its admitted plan targets. */
export async function prepare(input: {
  grant: WorkspaceGrant
  command: string
  args: string[]
  writePaths: string[]
  /** Trusted Git initialization only; ordinary tools never set this option. */
  controlWritePaths?: string[]
  /** Host-configured interpreter installation only. Never model arguments. */
  runtimeReadRoots?: string[]
  /** Immutable source staged by the host below its disposable scratch root. */
  protectedScratchPaths?: string[]
}): Promise<ProcessSandbox> {
  await QuantCodeWorkspace.revalidate(input.grant)
  if (process.platform !== "darwin" && process.platform !== "linux") {
    throw new QuantCodeWorkspace.WorkspaceDenied("此平台的进程隔离尚未就绪，不能降级为无限制终端。")
  }
  const command = await realpath(input.command)
  const runtimes = [] as string[]
  for (const item of systemRoots()) if (await exists(item)) runtimes.push(await realpath(item))
  const extraRuntimes: string[] = []
  for (const item of input.runtimeReadRoots ?? []) {
    if (!path.isAbsolute(item) || await realpath(item) !== item || !(await lstat(item)).isDirectory())
      throw new QuantCodeWorkspace.WorkspaceDenied("Python 运行环境必须是宿主指定的规范目录。")
    const backend = process.env.QUANTCODE_BACKEND_ROOT
    if (item === path.parse(item).root || QuantCodeWorkspace.contains(item, os.homedir()) ||
      QuantCodeWorkspace.contains(item, input.grant.root) || QuantCodeWorkspace.contains(input.grant.root, item) ||
      (backend && QuantCodeWorkspace.contains(item, path.resolve(backend))))
      throw new QuantCodeWorkspace.WorkspaceDenied("解释器只读范围不能包含用户目录、任务目录或宿主控制目录。")
    extraRuntimes.push(item)
    runtimes.push(item)
  }
  if (!runtimes.some(root => QuantCodeWorkspace.contains(root, command)) && !QuantCodeWorkspace.contains(input.grant.root, command)) {
    throw new QuantCodeWorkspace.WorkspaceDenied("可执行程序不属于系统运行环境或授权工作区。")
  }
  const writes: string[] = []
  for (const item of input.writePaths) writes.push(await QuantCodeWorkspace.target(input.grant, item, "write"))
  const denied: string[] = []
  for (const item of QuantCodeWorkspace.privatePaths(input.grant.root)) {
    denied.push(await QuantCodeWorkspace.canonical(item))
  }
  // Do not permit a process to modify repository hooks, git configuration or
  // runtime policy files and thereby cause the host to execute outside it.
  const control = path.join(input.grant.root, ".git")
  const controls: FileHandle[] = []
  if (input.controlWritePaths?.length) {
    if (input.grant.access !== "write" || input.grant.directory !== input.grant.root || input.controlWritePaths.length !== 1 ||
        input.controlWritePaths[0] !== control || await realpath(control) !== control) {
      throw new QuantCodeWorkspace.WorkspaceDenied("Git 初始化只能写入当前工作区新建的精确 .git 目录。")
    }
    const handle = await open(control, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW)
    const info = await handle.stat().catch(async error => { await handle.close(); throw error })
    if (!info.isDirectory()) { await handle.close(); throw new QuantCodeWorkspace.WorkspaceDenied() }
    controls.push(handle)
    writes.push(control)
  }
  if (writes.some(item => denied.some(secret => QuantCodeWorkspace.contains(secret, item)))) {
    await Promise.all(controls.map(handle => handle.close()))
    throw new QuantCodeWorkspace.WorkspaceDenied("进程不能修改宿主凭据或仓库控制配置。")
  }
  const scratch = await realpath(await mkdtemp(path.join(os.tmpdir(), "quantcode-process-"))).catch(async error => {
    await Promise.all(controls.map(handle => handle.close()))
    throw error
  })
  const env = {
    PATH: "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
    HOME: path.join(scratch, "home"), TMPDIR: scratch,
    LANG: "en_US.UTF-8", TERM: "xterm-256color",
    GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", GIT_TERMINAL_PROMPT: "0",
  }
  const dispose = async () => {
    await Promise.all(controls.map(handle => handle.close()))
    await rm(scratch, { recursive: true, force: true })
  }
  try {
    await mkdir(path.join(scratch, "home"), { mode: 0o700 })
    const protectedScratch = (input.protectedScratchPaths ?? []).map(relative => {
      const target = path.resolve(scratch, relative)
      if (!relative || path.isAbsolute(relative) || target === scratch || !QuantCodeWorkspace.contains(scratch, target))
        throw new QuantCodeWorkspace.WorkspaceDenied("归档执行副本必须位于独立的临时目录中。")
      return target
    })
    if (process.platform === "darwin") {
      const executable = "/usr/bin/sandbox-exec"
      await access(executable, constants.X_OK)
      const profile = [
        "(version 1)", "(deny default)",
        "(allow process-exec process-fork)", "(allow process-info* (target self))",
        "(allow signal (target same-sandbox))", "(allow sysctl-read)",
        "(allow mach-lookup (global-name \"com.apple.system.logger\") (global-name \"com.apple.system.opendirectoryd.libinfo\"))",
        // Metadata permits traversing ancestors, but not reading their contents.
        "(allow file-read-metadata)",
        ...[...runtimes, input.grant.root, scratch].map(root => `(allow file-read* (subpath ${literal(root)}))`),
        "(allow file-read* (literal \"/private/etc/localtime\") (literal \"/private/etc/passwd\") (literal \"/private/etc/group\"))",
        "(allow file-read* file-write* (literal \"/dev/null\") (literal \"/dev/tty\") (literal \"/dev/ptmx\") (regex #\"^/dev/ttys[0-9]+$\"))",
        "(allow file-read* (literal \"/dev/random\") (literal \"/dev/urandom\"))",
        `(allow file-write* (subpath ${literal(scratch)}))`,
        ...writes.map(root => `(allow file-write* (subpath ${literal(root)}))`),
        ...denied.flatMap(root => {
          const exceptions = extraRuntimes.filter(runtime => QuantCodeWorkspace.contains(root, runtime))
          return [`(deny file-write* (subpath ${literal(root)}))`, exceptions.length
            ? `(deny file-read* (require-all (subpath ${literal(root)}) ${exceptions.map(runtime => `(require-not (subpath ${literal(runtime)}))`).join(" ")}))`
            : `(deny file-read* (subpath ${literal(root)}))`]
        }),
        ...protectedScratch.map(root => `(deny file-write* (subpath ${literal(root)}))`),
        ...(controls.length ? [] : [`(deny file-write* (subpath ${literal(control)}))`]),
      ].join("\n")
      return { command: "/usr/bin/env", args: ["-i", ...Object.entries(env).map(([key, value]) => `${key}=${value}`), executable, "-p", profile, command, ...input.args], cwd: input.grant.directory, env, dispose }
    }
    const executable = await exists("/usr/bin/bwrap") ? "/usr/bin/bwrap" : "/bin/bwrap"
    await access(executable, constants.X_OK)
    const args = ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
    for (const [key, value] of Object.entries(env)) args.push("--setenv", key, value)
    for (const root of [...new Set([...systemRoots(), ...runtimes])]) {
      if (await exists(root)) args.push("--ro-bind", root, root)
    }
    args.push("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc")
    for (const item of ["/etc/localtime", "/etc/passwd", "/etc/group"]) {
      if (await exists(item)) args.push("--ro-bind", item, item)
    }
    args.push("--ro-bind", input.grant.root, input.grant.root, "--bind", scratch, scratch)
    for (const target of protectedScratch) args.push("--ro-bind", target, target)
    for (const target of writes) {
      // Exact new-file mount points require staged materialization by the
      // caller. Never widen to a writable parent to make a bind succeed.
      if (!await exists(target)) throw new QuantCodeWorkspace.WorkspaceDenied("新文件需通过受控写入工具创建，Shell 不扩大父目录写权限。")
      // Pin the source directory before bubblewrap resolves its mount path.
      // A swapped .git symlink cannot redirect this writable bind elsewhere.
      args.push("--bind", target === control && controls.length ? `/proc/${process.pid}/fd/${controls[0].fd}` : target, target)
    }
    if (!controls.length && await exists(control)) args.push("--ro-bind", control, control)
    for (const target of denied) {
      if (!QuantCodeWorkspace.contains(input.grant.root, target) || !await exists(target)) continue
      const info = await lstat(target)
      args.push(info.isDirectory() ? "--tmpfs" : "--ro-bind", ...(info.isDirectory() ? [target] : ["/dev/null", target]))
    }
    // Reinstall only the explicit interpreter roots hidden by a broader
    // private backend directory; the rest of that directory remains absent.
    for (const runtime of extraRuntimes) args.push("--ro-bind", runtime, runtime)
    args.push("--chdir", input.grant.directory, "--", command, ...input.args)
    return { command: "/usr/bin/env", args: ["-i", ...Object.entries(env).map(([key, value]) => `${key}=${value}`), executable, ...args], cwd: input.grant.directory, env, dispose }
  } catch (error) {
    await dispose()
    if (error instanceof QuantCodeWorkspace.WorkspaceDenied) throw error
    throw new QuantCodeWorkspace.WorkspaceDenied("无法准备系统进程隔离，请检查宿主 sandbox-exec/bubblewrap 支持。")
  }
}

export * as QuantCodeProcessSandbox from "./process-sandbox"

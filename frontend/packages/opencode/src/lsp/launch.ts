import type { ChildProcessWithoutNullStreams } from "child_process"
import { Process } from "@/util/process"
import { Shell } from "@opencode-ai/core/shell"
import { Npm } from "@opencode-ai/core/npm"
import { which } from "@opencode-ai/core/util/which"
import { Module } from "@opencode-ai/core/util/module"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeProcessSandbox } from "@/quantcode/process-sandbox"
import { QuantCodeWorkspace } from "@/quantcode/workspace"
import { LspGovernance } from "./governance"
import path from "node:path"
import { access, realpath } from "node:fs/promises"
import { constants } from "node:fs"
import { Filesystem } from "@/util/filesystem"
import type { Readable } from "node:stream"

type Child = Process.Child & ChildProcessWithoutNullStreams
const managed = new WeakMap<Process.Child, () => Promise<void>>()

export function spawn(cmd: string, args: string[], opts?: Process.Options): Promise<Child>
export function spawn(cmd: string, opts?: Process.Options): Promise<Child>
export async function spawn(cmd: string, argsOrOpts?: string[] | Process.Options, opts?: Process.Options) {
  const args = Array.isArray(argsOrOpts) ? [...argsOrOpts] : []
  const cfg = Array.isArray(argsOrOpts) ? opts : argsOrOpts
  const grant = LspGovernance.current()
  const sandbox = grant ? await QuantCodeProcessSandbox.prepare({
    grant: { ...grant, directory: await QuantCodeWorkspace.target(grant, cfg?.cwd ?? grant.directory) },
    command: path.isAbsolute(cmd) ? cmd : cmd.includes(path.sep) ? path.resolve(grant.directory, cmd)
      : which(cmd, { PATH: "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" }) ?? cmd,
    args, writePaths: [],
  }) : undefined
  // env:null clears even NODE_OPTIONS/LD_PRELOAD before env -i starts. Adapters'
  // inherited env, shell and abort options cannot weaken the controlled launch.
  const proc = await Promise.resolve().then(() => Process.spawn(sandbox ? [sandbox.command, ...sandbox.args] : [cmd, ...args], {
    ...(sandbox ? { cwd: sandbox.cwd, env: null, detached: process.platform !== "win32" } : cfg),
    stdin: "pipe", stdout: "pipe", stderr: "pipe",
  }) as Child).catch(async error => {
    await sandbox?.dispose()
    throw error
  })

  if (sandbox && grant) {
    let closing: Promise<void> | undefined
    let checking = false
    const cleanup = () => closing ??= (async () => {
      clearInterval(timer)
      await Shell.killTree(proc)
      await sandbox.dispose()
    })()
    const timer = setInterval(() => {
      if (checking || closing) return
      checking = true
      void LspGovernance.check(grant).catch(cleanup).finally(() => { checking = false }).catch(() => undefined)
    }, 2000)
    timer.unref()
    managed.set(proc, cleanup)
    void proc.exited.then(cleanup, cleanup).catch(() => undefined)
  }

  if (!proc.stdin || !proc.stdout || !proc.stderr) {
    await stop(proc)
    throw new Error("Process output not available")
  }

  return proc
}

export async function stop(proc: ChildProcessWithoutNullStreams) {
  const cleanup = managed.get(proc as Child)
  if (cleanup) return cleanup()
  return Process.stop(proc)
}

/** Discovery must not invoke Npm.which's implicit installation in QuantCode.
 * Existing workspace/system packages remain supported by the same adapters. */
export async function packageBinary(pkg: string, bin?: string) {
  const grant = LspGovernance.current()
  if (!grant) return Npm.which(pkg, bin)
  const name = bin ?? pkg.split("/").pop()!
  for (const candidate of [path.join(grant.directory, "node_modules", ".bin", name),
    findBinary(name)]) {
    if (!candidate) continue
    const resolved = await realpath(candidate).catch(() => undefined)
    if (!resolved) continue
    if (QuantCodeWorkspace.contains(grant.root, resolved)) await QuantCodeWorkspace.target(grant, resolved)
    if (await access(resolved, constants.X_OK).then(() => true, () => false)) return resolved
  }
}

export function findBinary(command: string) {
  const grant = LspGovernance.current()
  if (!grant) return which(command)
  return which(command, { PATH: [path.join(grant.directory, "node_modules", ".bin"),
    path.join(grant.root, "node_modules", ".bin"), path.join(grant.directory, ".venv", "bin"),
    "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin"].join(path.delimiter) })
}

export async function resolveModule(name: string, directory: string) {
  const resolved = Module.resolve(name, directory)
  const grant = LspGovernance.current()
  if (!resolved || !grant) return resolved
  return QuantCodeWorkspace.target(grant, resolved).catch(() => undefined)
}

export async function readText(file: string) {
  const grant = LspGovernance.current()
  if (!grant) return Filesystem.readText(file)
  return (await QuantCodeWorkspace.readFile(grant, file)).content.toString("utf8")
}

export async function probe(command: string[], opts: Process.RunOptions = {}): Promise<Process.TextResult> {
  if (!QuantCodeIdentity.enabled()) return Process.text(command, { ...opts, nothrow: true })
  const grant = LspGovernance.current()!
  const proc = await spawn(command[0], command.slice(1), opts)
  const timer = setTimeout(() => { void stop(proc).catch(() => undefined) }, 10000)
  const collect = async (stream: Readable) => {
    const chunks: Buffer[] = []
    let length = 0
    for await (const chunk of stream) {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
      length += buffer.length
      if (length > 64000) throw new Error("语言服务探测输出超出限制。")
      chunks.push(buffer)
    }
    return Buffer.concat(chunks)
  }
  try {
    proc.stdin.end()
    const [code, stdout, stderr] = await Promise.all([proc.exited, collect(proc.stdout), collect(proc.stderr)])
    await LspGovernance.check(grant)
    return { code, stdout, stderr, text: stdout.toString("utf8") }
  } finally {
    clearTimeout(timer)
    await stop(proc)
  }
}

export * as LspLaunch from "./launch"

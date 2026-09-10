import { execFile, spawn } from "node:child_process"
import { createConnection, createServer } from "node:net"
import { isAbsolute, win32 } from "node:path"
import { promisify } from "node:util"
import { setTimeout } from "node:timers/promises"
import type { QuantCodeIdentityGroup, QuantCodeSshConnection } from "@opencode-ai/app/identity"

const execFileAsync = promisify(execFile)
export const ORG_SERVERS = [
  { id: "server-a", label: "Server A", host: "43.154.17.120" },
  { id: "server-b", label: "Server B", host: "150.109.79.42" },
  { id: "server-c", label: "Server C", host: "150.109.115.216" },
] as const
export type OrgServer = (typeof ORG_SERVERS)[number]
const groupNames = new Set<QuantCodeIdentityGroup>(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"])

export function usernameFromKeyFile(filename: string): string | undefined {
  const base = filename.split(/[\\/]/).pop() ?? ""
  const name = base.replace(/\.(pem|key)$/i, "").replace(/(?:[_-](?:ed25519|rsa|ecdsa|dsa))(?:[_-](?:private|key))?$/i, "")
  if (/^id(?:_|$)/i.test(name) || /^(?:private|key|ssh-key)$/i.test(name) || /\.pub$/i.test(base)) return
  return /^[a-z_][a-z0-9_-]{0,63}$/i.test(name) ? name : undefined
}

export function requireUsername(username: string) {
  if (!/^[a-z_][a-z0-9_-]{0,63}$/i.test(username)) throw new Error("请输入有效的 Linux 用户名，例如 qc-chenzhenhong。")
  return username
}

export function systemSshExecutable(name: "ssh" | "ssh-add" | "ssh-keygen") {
  if (process.platform !== "win32") return `/usr/bin/${name}`
  const root = process.env.SystemRoot
  if (!root || !win32.isAbsolute(root)) throw new Error("请先安装 Windows OpenSSH Client。")
  return win32.join(root, "System32", "OpenSSH", `${name}.exe`)
}

export function sshArguments(keyFile: string, username: string, host: string) {
  if (!isAbsolute(keyFile) || keyFile.includes("\0")) throw new Error("请通过系统选择器选择本地私钥文件。")
  requireUsername(username)
  return ["-F", process.platform === "win32" ? "NUL" : "/dev/null", "-i", keyFile, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-l", username, host]
}

async function runRemote(server: OrgServer, username: string, keyFile: string, command: string, signal?: AbortSignal) {
  const result = await execFileAsync(systemSshExecutable("ssh"), [...sshArguments(keyFile, username, server.host), command],
    { encoding: "utf8", timeout: 15000, maxBuffer: 32768, windowsHide: true, signal })
  return result.stdout
}

export function businessGroups(output: string): QuantCodeIdentityGroup[] {
  return [...new Set(output.trim().split(/\s+/).filter((name): name is QuantCodeIdentityGroup => groupNames.has(name as QuantCodeIdentityGroup)))]
}

export type ResearchProfile = { version: 1; release: string; ssh_host: string; ssh_port: 22; ssh_user: string;
  remote_port: number; local_port: number; url: string; username: "quantcode"; password: string }

export function parseResearchProfile(raw: string, username: string): ResearchProfile {
  try {
    if (Buffer.byteLength(raw) > 16384) throw new Error()
    const profile = JSON.parse(raw) as Partial<ResearchProfile> | null
    const keys = ["version", "release", "ssh_host", "ssh_port", "ssh_user", "remote_port", "local_port", "url", "username", "password"]
    if (!profile || typeof profile !== "object" || Array.isArray(profile) || Object.keys(profile).length !== keys.length ||
      keys.some(key => !(key in profile)) || profile.version !== 1 || profile.ssh_port !== 22 ||
      typeof profile.release !== "string" || !profile.release || typeof profile.ssh_host !== "string" || !profile.ssh_host ||
      profile.ssh_user !== username || profile.username !== "quantcode" ||
      typeof profile.password !== "string" || !/^[A-Za-z0-9_-]{32,128}$/.test(profile.password) ||
      [profile.remote_port, profile.local_port].some(port => typeof port !== "number" || !Number.isInteger(port) || port < 1024 || port > 65535) ||
      profile.url !== `http://127.0.0.1:${profile.local_port}`) throw new Error()
    return profile as ResearchProfile
  } catch {
    throw new Error("个人研究宿主连接信息无效，请联系管理员重新下发。")
  }
}

export type OrgAccount = { groups: QuantCodeIdentityGroup[]; profile: ResearchProfile }
  | { administrator: true; groups: QuantCodeIdentityGroup[]; systemGroups: string[] }

export async function readOrgAccount(server: OrgServer, username: string, keyFile: string, signal?: AbortSignal): Promise<OrgAccount> {
  const identity = (await runRemote(server, username, keyFile, "id -un && groups", signal)).trim().split(/\r?\n/)
  if (identity.shift()?.trim() !== username) throw new Error("服务器返回的 SSH 账号不一致，请重新登录。")
  const systemGroups = identity.join(" ").trim().split(/\s+/).filter(Boolean)
  const groups = businessGroups(systemGroups.join(" "))
  // This selects the SSH operations path only. Organization admin still
  // requires the gateway's verified role; sudo membership grants nothing here.
  if (systemGroups.includes("quant-admin")) return { administrator: true, groups, systemGroups }
  const raw = await runRemote(server, username, keyFile, "cat ~/.quantcode/test-v1/connection.json", signal)
    .catch(() => { throw new Error("SSH 登录成功，但个人研究宿主尚未开通，请联系管理员。") })
  return { groups, profile: parseResearchProfile(raw, username) }
}

export async function readAdminProfile(server: OrgServer, username: string, keyFile: string, signal?: AbortSignal) {
  const raw = await runRemote(server, username, keyFile, "cat ~/.quantcode/admin/connection.json", signal)
    .catch(() => { throw new Error("组织管理通道尚未配置。服务器运维可以独立使用；请为管理员开通独立组织管理宿主。") })
  return parseResearchProfile(raw, username)
}

export async function readServerAdminStatus(server: OrgServer, username: string, keyFile: string, signal?: AbortSignal) {
  return runRemote(server, username, keyFile, "uname -sr && uptime && df -h /", signal)
}

export function sshFailure(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  if (/Permission denied|publickey/i.test(message)) return "这把密钥或用户名未登记"
  if (/REMOTE HOST IDENTIFICATION|Host key verification/i.test(message)) return "服务器指纹发生变化，请联系管理员核对"
  if (/个人研究宿主|工作组|组织身份|组织管理|本机 SSH/.test(message)) return message
  return "暂时无法连接，请检查网络后重试"
}

export type ResearchTunnel = { connection: QuantCodeSshConnection; alive: () => boolean; stop: () => void }

async function availablePort(preferred: number) {
  const reserve = (port: number) => new Promise<number>((resolve, reject) => {
    const server = createServer()
    server.once("error", reject)
    server.listen(port, "127.0.0.1", () => {
      const address = server.address()
      server.close(error => error ? reject(error) : resolve(typeof address === "object" && address ? address.port : 0))
    })
  })
  return reserve(preferred).catch(() => reserve(0))
}

export async function openResearchTunnel(server: OrgServer, username: string, keyFile: string, profile: ResearchProfile,
  signal?: AbortSignal, localPort?: number): Promise<ResearchTunnel> {
  signal?.throwIfAborted()
  const port = await availablePort(localPort ?? profile.local_port)
  const base = sshArguments(keyFile, username, server.host)
  const child = spawn(systemSshExecutable("ssh"), ["-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3", "-L", `127.0.0.1:${port}:127.0.0.1:${profile.remote_port}`, ...base],
    { stdio: ["ignore", "ignore", "pipe"], windowsHide: true })
  let failed = false
  child.once("error", () => { failed = true })
  child.stderr.resume()
  const stop = () => { if (!child.killed) child.kill() }
  const alive = () => !failed && !child.killed && child.exitCode === null && child.signalCode === null
  signal?.addEventListener("abort", stop, { once: true })
  child.once("exit", () => signal?.removeEventListener("abort", stop))
  try {
    const deadline = Date.now() + 12000
    while (Date.now() < deadline && alive()) {
      signal?.throwIfAborted()
      const listening = await new Promise<boolean>(resolve => {
        const socket = createConnection({ host: "127.0.0.1", port })
        const done = (ok: boolean) => { socket.destroy(); resolve(ok) }
        socket.once("connect", () => done(true))
        socket.once("error", () => done(false))
        socket.setTimeout(300, () => done(false))
      })
      if (listening && alive()) return { connection: { url: `http://127.0.0.1:${port}`, username: profile.username,
        password: profile.password, displayName: `${server.label} · ${username}` }, alive, stop }
      await setTimeout(100, undefined, { signal })
    }
    throw new Error("无法建立个人研究宿主连接，请检查 SSH 和网络。")
  } catch (error) {
    stop()
    throw error
  }
}

import { execFile, spawn } from "node:child_process"
import { createConnection, createServer } from "node:net"
import { isAbsolute, win32 } from "node:path"
import { readFile, mkdtemp, writeFile } from "node:fs/promises"
import { homedir, userInfo, tmpdir } from "node:os"
import { join } from "node:path"
import { promisify } from "node:util"
import { superviseSshTunnel } from "./ssh-tunnel-supervisor"
import type { QuantCodeIdentityGroup, QuantCodeSshConnection } from "@opencode-ai/app/identity"

const execFileAsync = promisify(execFile)
export const ORG_SERVERS = [
  { id: "server-a", label: "Server A", host: "43.154.17.120" },
  { id: "server-b", label: "Server B", host: "150.109.79.42" },
  { id: "server-c", label: "Server C", host: "150.109.115.216" },
] as const
export type OrgServer = (typeof ORG_SERVERS)[number] & { sshHost?: string }
const groupNames = new Set<QuantCodeIdentityGroup>(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"])
// Public host keys verified through the administrator's existing SSH connections.
const orgHostKeys = `43.154.17.120 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIInsv+7UYNIlVm2CVNhHS4YkWX6C5GA8aYclRMm2yx5j
150.109.79.42 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIkhPeBbgyVniaa+lsFYOQZewxATVYFdkpyTuEWbmPOo
150.109.115.216 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHo9wycmjTpXiX6loNgBBb2C2hIhWSvsDDBuUlt0I7zJ
`
let hostKeysFile: Promise<string> | undefined
function organizationHostKeys() {
  return hostKeysFile ??= (async () => {
    const directory = await mkdtemp(join(tmpdir(), 'quantcode-hosts-'))
    const file = join(directory, 'known_hosts')
    await writeFile(file, orgHostKeys, { mode: 0o600, flag: 'wx' })
    return file
  })()
}

export function usernameFromKeyFile(filename: string): string | undefined {
  const base = filename.split(/[\\/]/).pop() ?? ""
  const name = base.replace(/\.(pem|key)$/i, "").replace(/(?:[_-](?:ed25519|rsa|ecdsa|dsa))(?:[_-](?:private|key))?$/i, "")
  if (/^id(?:_|$)/i.test(name) || /^(?:private|key|ssh-key)$/i.test(name) || /\.pub$/i.test(base)) return
  return /^[a-z_][a-z0-9_-]{0,63}$/i.test(name) ? name : undefined
}

export function requireUsername(username: string) {
  if (!/^[a-z_][a-z0-9_-]{0,63}$/i.test(username)) throw new Error("请输入有效的 Linux 用户名，填写平时 SSH 登录使用的账号即可。")
  return username
}

export function systemSshExecutable(name: "ssh" | "ssh-add" | "ssh-keygen") {
  if (process.platform !== "win32") return `/usr/bin/${name}`
  const root = process.env.SystemRoot
  if (!root || !win32.isAbsolute(root)) throw new Error("请先安装 Windows OpenSSH Client。")
  return win32.join(root, "System32", "OpenSSH", `${name}.exe`)
}

export function sshArguments(keyFile: string, username: string, host: string, alias = host, knownHosts?: string) {
  if (!isAbsolute(keyFile) || keyFile.includes("\0")) throw new Error("请通过系统选择器选择本地私钥文件。")
  requireUsername(username)
  return ["-T", "-i", keyFile, "-o", 'RemoteCommand=none', "-o", `HostName=${host}`, "-o", `HostKeyAlias=${host}`, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
    ...(knownHosts ? ['-o', `UserKnownHostsFile="${knownHosts.replace(/\\/g, '/').replace(/"/g, '\\"')}"`, '-o', `GlobalKnownHostsFile=${process.platform === 'win32' ? 'NUL' : '/dev/null'}`, '-o', 'HostKeyAlgorithms=ssh-ed25519'] : []),
    "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-l", username, alias]
}

export async function resolveSshTarget(server: OrgServer, fallback: string, signal?: AbortSignal, preferConfig = true) {
  const deadline = AbortSignal.any([AbortSignal.timeout(8000), ...(signal ? [signal] : [])])
  const config = await readFile(join(homedir(), '.ssh', 'config'), 'utf8').catch(() => '')
  const aliases = [...config.matchAll(/^\s*Host\s+(.+)$/gmi)].flatMap(match => match[1].split(/\s+/))
    .filter(host => /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(host))
  for (const alias of [...new Set([...aliases.slice(0, 64), server.host])]) {
    signal?.throwIfAborted()
    if (deadline.aborted) break
    const resolved = await execFileAsync(systemSshExecutable('ssh'), ['-G', alias], {
      encoding: 'utf8', timeout: 3000, maxBuffer: 65536, windowsHide: true, signal: deadline,
    }).catch(() => undefined)
    if (!resolved) continue
    const values = Object.fromEntries(resolved.stdout.split(/\r?\n/).map(line => {
      const index = line.indexOf(' '); return [line.slice(0, index), line.slice(index + 1)]
    }))
    if (values.hostname !== server.host) continue
    const configured = values.user && (aliases.includes(alias) || values.user !== userInfo().username) ? values.user : ''
    return { server: { ...server, sshHost: alias }, username: preferConfig ? configured || fallback : fallback || configured }
  }
  return { server, username: fallback }
}

async function runRemote(server: OrgServer, username: string, keyFile: string, command: string, signal?: AbortSignal) {
  const result = await execFileAsync(systemSshExecutable("ssh"), [...sshArguments(keyFile, username, server.host, server.sshHost, await organizationHostKeys()), command],
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

type WorkspaceRoute = { serverId: string; username: string; fingerprints: string[] }
export type OrgAccount = { groups: QuantCodeIdentityGroup[]; profile: ResearchProfile }
  | { administrator: true; groups: QuantCodeIdentityGroup[]; systemGroups: string[]; routes?: WorkspaceRoute[] }
  | { routes: WorkspaceRoute[] }

export function parseWorkspaceRoutes(raw: string): Extract<OrgAccount, { routes: unknown }> {
  const value = JSON.parse(raw)
  if (value?.version !== 1 || !Array.isArray(value.routes) || value.routes.length > 8) throw new Error('工作区发现协议无效，请联系管理员更新连接入口。')
  if (value.status !== 'registered') throw new Error(value.status === 'invalid'
    ? 'SSH 已连接，但工作区登记配置无效，请联系管理员。' : 'SSH 已连接，但此账号尚未登记 QuantCode 工作区，请联系管理员。')
  for (const route of value.routes) {
    if (!route || !ORG_SERVERS.some(server => server.id === route.serverId) || typeof route.username !== 'string' ||
      !Array.isArray(route.fingerprints) || !route.fingerprints.length || route.fingerprints.length > 16 ||
      !route.fingerprints.every((key: unknown) => typeof key === 'string' && /^SHA256:[A-Za-z0-9+/]{43}$/.test(key))) throw new Error('工作区登记包含无效目标，请联系管理员。')
    requireUsername(route.username)
  }
  return { routes: value.routes }
}

export async function readOrgAccount(server: OrgServer, username: string, keyFile: string, signal?: AbortSignal): Promise<OrgAccount> {
  const identity = (await runRemote(server, username, keyFile, "id -un && groups", signal)).trim().split(/\r?\n/)
  if (identity.shift()?.trim() !== username) throw new Error("服务器返回的 SSH 账号不一致，请重新登录。")
  const systemGroups = identity.join(" ").trim().split(/\s+/).filter(Boolean)
  const groups = businessGroups(systemGroups.join(" "))
  // This selects the SSH operations path only. Organization admin still
  // requires the gateway's verified role; sudo membership grants nothing here.
  if (systemGroups.includes("quant-admin")) {
    const raw = await runRemote(server, username, keyFile,
      "if test -x /usr/local/bin/quantcode-connect; then /usr/local/bin/quantcode-connect; else printf '{\"version\":1,\"status\":\"not_configured\",\"routes\":[]}'; fi", signal)
    const description = JSON.parse(raw)
    if (description?.status === 'registered') return { administrator: true, groups, systemGroups, ...parseWorkspaceRoutes(raw) }
    if (description?.version !== 1 || description.status !== 'not_configured') throw new Error('SSH 管理权限已确认，但工作区登记配置无效，请联系管理员。')
    return { administrator: true, groups, systemGroups }
  }
  const raw = await runRemote(server, username, keyFile,
    "if test -e ~/.quantcode/test-v1/connection.json; then printf 'QUANTCODE_PROFILE\\n'; cat ~/.quantcode/test-v1/connection.json; elif test -x /usr/local/bin/quantcode-connect; then /usr/local/bin/quantcode-connect; else printf '{\"version\":1,\"status\":\"not_configured\",\"routes\":[]}'; fi", signal)
    .catch(error => { if (signal?.aborted) throw error; throw new Error('SSH 已连接，但无法读取工作区配置，请检查文件权限、服务状态或网络。') })
  if (raw.startsWith('QUANTCODE_PROFILE\n')) return { groups, profile: parseResearchProfile(raw.slice('QUANTCODE_PROFILE\n'.length), username) }
  return parseWorkspaceRoutes(raw)
}

export async function readAdminProfile(server: OrgServer, username: string, keyFile: string, signal?: AbortSignal) {
  const raw = await runRemote(server, username, keyFile, "cat ~/.quantcode/admin/connection.json", signal)
    .catch(() => { throw new Error("管理员服务尚未开通，请完成服务器端管理员配置后重试。") })
  return parseResearchProfile(raw, username)
}

export async function readServerAdminStatus(server: OrgServer, username: string, keyFile: string, signal?: AbortSignal) {
  return runRemote(server, username, keyFile, "uname -sr && uptime && df -h /", signal)
}

export function sshFailure(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  if (/Permission denied|publickey/i.test(message)) return "这把密钥或用户名未登记"
  if (/REMOTE HOST IDENTIFICATION|Host key verification/i.test(message)) return "服务器指纹发生变化，请联系管理员核对"
  if (/个人研究宿主|工作组|工作区|组织身份|组织管理|本机 SSH|系统 SSH|私钥需要解锁/.test(message)) return message
  return "暂时无法连接，请检查网络后重试"
}

export type ResearchTunnel = { connection: QuantCodeSshConnection; alive: () => boolean; stop: () => void;
  ensureConnected?: (timeoutMs?: number) => Promise<void>; status?: ReturnType<typeof superviseSshTunnel>["status"];
  subscribe?: ReturnType<typeof superviseSshTunnel>["subscribe"]; reconnect?: () => Promise<void> }

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
  signal?: AbortSignal, localPort?: number, initialSignal?: AbortSignal): Promise<ResearchTunnel> {
  signal?.throwIfAborted()
  initialSignal?.throwIfAborted()
  const port = await availablePort(localPort ?? profile.local_port)
  initialSignal?.throwIfAborted()
  const base = sshArguments(keyFile, username, server.host, server.sshHost, await organizationHostKeys())
  const supervised = superviseSshTunnel({
    signal,
    launch: () => spawn(systemSshExecutable("ssh"), ["-v", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
      "-o", "ServerAliveCountMax=2", "-L", `127.0.0.1:${port}:127.0.0.1:${profile.remote_port}`, ...base],
      { stdio: ["ignore", "ignore", "pipe"], windowsHide: true }),
    // A different local process may take the port between retries. A TCP
    // connect alone must never certify that our SSH process owns the listener.
    forwardingReady: stderr => stderr.includes(`debug1: Local forwarding listening on 127.0.0.1 port ${port}.`),
    probe: () => new Promise<boolean>(resolve => {
        const socket = createConnection({ host: "127.0.0.1", port })
        const done = (ok: boolean) => { socket.destroy(); resolve(ok) }
        socket.once("connect", () => done(true))
        socket.once("error", () => done(false))
        socket.setTimeout(300, () => done(false))
    }),
  })
  const cancelInitial = () => supervised.stop()
  initialSignal?.addEventListener("abort", cancelInitial, { once: true })
  try {
    await supervised.ensureConnected()
    initialSignal?.throwIfAborted()
    return { ...supervised, connection: { url: `http://127.0.0.1:${port}`, username: profile.username,
      password: profile.password, displayName: `${server.label} · ${username}` } }
  } catch (error) {
    supervised.stop()
    throw error
  } finally { initialSignal?.removeEventListener("abort", cancelInitial) }
}

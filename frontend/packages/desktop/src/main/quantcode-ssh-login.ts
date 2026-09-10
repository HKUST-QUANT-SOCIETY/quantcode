import { execFile } from "node:child_process"
import { promisify } from "node:util"

const execFileAsync = promisify(execFile)

/** 组织统一的三台研究服务器（内置，成员不需要配置地址）。 */
export const ORG_SERVERS = [
  { id: "server-a", label: "Server A · 数据", host: "43.154.17.120" },
  { id: "server-b", label: "Server B · 计算", host: "150.109.79.42" },
  { id: "server-c", label: "Server C · GPU", host: "150.109.115.216" },
] as const

export type OrgServerId = (typeof ORG_SERVERS)[number]["id"]
export type OrgServer = { id: OrgServerId; label: string; host: string; username: string; groups: string[] }

function sshExecutable() {
  if (process.platform !== "win32") return "/usr/bin/ssh"
  const root = process.env.SystemRoot
  if (!root) throw new Error("无法定位系统 OpenSSH，请先安装 Windows OpenSSH Client。")
  return `${root}\\System32\\OpenSSH\\ssh.exe`
}

async function runRemote(host: string, username: string, keyFile: string, command: string, timeoutMs = 15000): Promise<string> {
  const result = await execFileAsync(sshExecutable(), [
    "-i", keyFile,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes",
    `${username}@${host}`,
    command,
  ], { encoding: "utf8", timeout: timeoutMs, maxBuffer: 65536, windowsHide: true })
  return result.stdout
}

/** 从私钥文件名解析 SSH 用户名（教程约定：文件名带成员 Linux 用户名）。 */
export function usernameFromKeyFile(filename: string): string | null {
  const base = filename.split(/[\\/]/).pop() ?? ""
  const stripped = base.replace(/\.(pub|pem|key)?$/i, "").replace(/(_|-)?(ed25519|rsa|ecdsa|dsa)?(_|-)?(private|key)?$/i, "")
  const match = stripped.match(/^[A-Za-z][A-Za-z0-9_-]{1,31}$/)
  return match ? stripped : null
}

export type KeyScanResult = {
  username: string
  servers: OrgServer[]
  failed: { id: string; reason: "unreachable" | "not-enrolled" }[]
}

/** 登录后对选定服务器做一次轻量校验（不收集组，只确认可登录）。 */
export async function probeOrgServer(keyFile: string, username: string, serverId?: string): Promise<void> {
  const target = ORG_SERVERS.find(org => org.id === serverId) ?? ORG_SERVERS[0]
  await runRemote(target.host, username, keyFile, "true")
}

/** 用成员私钥依次 SSH 三台组织服务器：登录成功的服务器上收集所属组。 */
export async function scanOrgServers(keyFile: string, usernameHint?: string): Promise<KeyScanResult> {
  const username = (usernameHint ?? "").trim() || usernameFromKeyFile(keyFile)
  if (!username) throw new Error("无法从私钥文件名解析 SSH 用户名，请手动输入一次（之后会记住）。")
  const servers: OrgServer[] = []
  const failed: KeyScanResult["failed"] = []
  for (const org of ORG_SERVERS) {
    try {
      const groupsOut = await runRemote(org.host, username, keyFile, "id -nG $(whoami) | tr ' ' '\\n' | grep -v '^qc-' | tr '\\n' ','")
      const groups = groupsOut.split(",").map(item => item.trim()).filter(Boolean)
      servers.push({ ...org, username, groups })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      failed.push({ id: org.id, reason: /Permission denied|publickey/i.test(message) ? "not-enrolled" : "unreachable" })
    }
  }
  if (!servers.length && failed.every(item => item.reason === "unreachable")) {
    throw new Error("暂时无法连接组织服务器，请检查网络后重试。")
  }
  if (!servers.length) {
    throw new Error("这把密钥没有在任何组织服务器登记。请确认私钥对应文件名中的用户名，并联系管理员完成公钥登记。")
  }
  return { username, servers, failed }
}

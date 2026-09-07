import { readFile } from "node:fs/promises"
import { createHash } from "node:crypto"
import { isAbsolute } from "node:path"

function configuration() {
  const python = process.env.QUANTCODE_HOST_PYTHON
  const root = process.env.QUANTCODE_BACKEND_ROOT
  const publicKey = process.env.QUANTCODE_PUBLIC_KEY_FILE
  const session = process.env.QUANTCODE_IDENTITY_SESSION_FILE
  const gateway = process.env.QUANTCODE_GATEWAY_URL
  if (!python || !root || !publicKey || !session || !gateway) throw new Error("本机身份桥未配置：需要 Python、后端目录、公钥文件、会话文件和 gateway 地址")
  if (![python, root, publicKey, session].every(isAbsolute)) throw new Error("身份桥路径必须为绝对路径")
  const target = new URL(gateway)
  if (target.protocol !== "https:" && !(target.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(target.hostname))) throw new Error("Gateway 需要 HTTPS 或本地回环地址")
  return { python, root, publicKey, session, gateway }
}

export async function localIdentity() {
  const config = configuration()
  const key = (await readFile(config.publicKey, "utf8").catch(() => { throw new Error("无法读取配置的 SSH 公钥文件，请检查路径与文件权限") })).trim()
  if (key.includes("PRIVATE KEY") || !/^(ssh-|ecdsa-|sk-)/.test(key)) throw new Error("配置必须指向 SSH 公钥")
  const encoded = key.split(/\s+/)[1]
  if (!encoded || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw new Error("SSH 公钥内容格式错误")
  const bytes = Buffer.from(encoded, "base64")
  if (!bytes.length || bytes.toString("base64").replace(/=+$/, "") !== encoded.replace(/=+$/, "")) throw new Error("SSH 公钥内容格式错误")
  const fingerprint = `SHA256:${createHash("sha256").update(bytes).digest("base64").replace(/=+$/, "")}`
  const context = await runIdentity(["--inspect"])
  if (typeof context.group !== "string" || !Array.isArray(context.groups) || !context.groups.every(group => typeof group === "string") || !context.groups.includes(context.group)) {
    throw new Error("身份桥返回无效授权组")
  }
  const session = context.session as { session_id?: string; group?: string; groups?: string[] } | null
  return {
    identities: [{ id: "host-default", label: `本机 SSH agent · ${fingerprint}`, fingerprint,
      host: new URL(config.gateway).host, user: "SSH agent", group: context.group, groups: context.groups }],
    session: session?.session_id && session.group
      ? { status: "connected", session_id: session.session_id, fingerprint, group: session.group, groups: session.groups }
      : null,
  }
}

async function runIdentity(args: string[]): Promise<Record<string, unknown>> {
  const config = configuration()
  const child = Bun.spawn([config.python, "-m", "quantcode.identity_login", "--gateway", config.gateway,
    "--public-key", config.publicKey, "--session-file", config.session, ...args], {
    cwd: config.root, stdin: "ignore", stdout: "pipe", stderr: "ignore",
  })
  const timeout = setTimeout(() => child.kill(), 60000)
  try {
    const output = await new Response(child.stdout).text()
    if (await child.exited !== 0) throw new Error("身份操作失败：请检查 SSH agent、gateway 和正式 roster")
    const context = JSON.parse(output)
    if (!context || typeof context !== "object" || Array.isArray(context)) throw new Error("身份桥返回格式错误")
    return context
  } finally { clearTimeout(timeout) }
}

export async function signInLocalIdentity(group?: string) {
  const identities = await localIdentity()
  if (group && !identities.identities[0].groups.includes(group)) throw new Error("未授权的组")
  const context = await runIdentity(group ? ["--group", group] : [])
  if (!context.actor_id || !context.group || !context.session_id || (group && context.group !== group)) throw new Error("身份桥返回无效会话")
  return { status: "connected", actor_id: context.actor_id, session_id: context.session_id,
    fingerprint: identities.identities[0].fingerprint, group: context.group,
    groups: Array.isArray(context.groups) ? context.groups : [context.group] }
}

export async function signOutLocalIdentity() {
  const result = await runIdentity(["--logout"])
  if (result.status !== "disconnected") throw new Error("身份桥未确认退出")
  return { status: "disconnected" }
}

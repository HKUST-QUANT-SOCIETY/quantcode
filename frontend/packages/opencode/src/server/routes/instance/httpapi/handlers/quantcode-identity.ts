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
  return { identities: [{ id: "host-default", label: `本机 SSH agent · ${fingerprint}`, fingerprint, host: new URL(config.gateway).host, user: "SSH agent" }] }
}

let pending: Promise<unknown> | undefined
export function signInLocalIdentity(): Promise<unknown> {
  if (pending) return pending
  pending = signIn().finally(() => { pending = undefined })
  return pending
}

async function signIn() {
  const config = configuration()
  const identities = await localIdentity()
  const child = Bun.spawn([config.python, "-m", "quantcode.identity_login", "--gateway", config.gateway,
    "--public-key", config.publicKey, "--session-file", config.session], {
    cwd: config.root, stdin: "ignore", stdout: "pipe", stderr: "ignore",
  })
  const timeout = setTimeout(() => child.kill(), 45000)
  try {
    const output = await new Response(child.stdout).text()
    if (await child.exited !== 0) throw new Error("SSH agent 登录失败：请检查 agent 是否载入密钥、gateway 连通性及正式 roster")
    const context = JSON.parse(output) as { actor_id?: string; group?: string; session_id?: string }
    if (!context.actor_id || !context.group || !context.session_id) throw new Error("身份桥返回无效会话")
    return { status: "connected", actor_id: context.actor_id, session_id: context.session_id, fingerprint: identities.identities[0].fingerprint, groups: [context.group] }
  } finally { clearTimeout(timeout) }
}

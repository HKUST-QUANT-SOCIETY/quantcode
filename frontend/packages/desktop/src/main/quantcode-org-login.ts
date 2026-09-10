import type { QuantCodeIdentityGroup, QuantCodeSshLoginResult, QuantCodeSshLoginScan, QuantCodeSshLoginChoice, QuantCodeServerAdminSession } from "@opencode-ai/app/identity"
import { connect, importKey, inspect, requireAdminSession } from "./quantcode-identity"
import { ORG_SERVERS, openResearchTunnel, readOrgAccount, readAdminProfile, readServerAdminStatus, requireUsername, sshFailure, usernameFromKeyFile } from "./quantcode-ssh-login"
import type { OrgServer, ResearchTunnel, OrgAccount } from "./quantcode-ssh-login"

type SavedLogin = { keyFile: string; username: string; serverId: string; group: string; fingerprint: string; actorId: string; localPort: number; organizationAdmin?: boolean }
function savedLogin(value: unknown): SavedLogin | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return
  const data = value as Partial<SavedLogin>
  if ([data.keyFile, data.username, data.serverId, data.group, data.fingerprint, data.actorId].some(item => typeof item !== "string" || !item) ||
    typeof data.localPort !== "number" || !Number.isInteger(data.localPort) || data.localPort < 1024 || data.localPort > 65535) return
  return data as SavedLogin
}
type LoginStore = { get: (key: string) => unknown; set: (key: string, value: unknown) => void }
const hostConnection = (connection: ResearchTunnel["connection"]) => ({ url: connection.url, username: connection.username, password: connection.password })
const dependencies = { readOrgAccount, readAdminProfile, readServerAdminStatus, requireAdminSession, openResearchTunnel, inspect, connect,
  importKey: (file: string) => importKey({ url: "http://127.0.0.1" }, file) }

/** Each desktop window owns its selected key and SSH transports. Renderer input
 * can select a discovered server/group, never a key path, command or credential. */
export function createOrgLogin(store: LoginStore, deps = dependencies) {
  const lifetime = new AbortController()
  const tunnels = new Map<string, ResearchTunnel>()
  const administrators = new Map<string, OrgServer>()
  let activeAdmin: { keyFile: string; session: QuantCodeServerAdminSession } | undefined
  const choices = new Map<string, { server: OrgServer; tunnel: ResearchTunnel; groups: QuantCodeIdentityGroup[] }>()
  let keyFile = ""
  let fingerprint = ""
  let username = ""
  let activeUrl = ""

  const ensureOpen = () => lifetime.signal.throwIfAborted()
  const transport = async (server: OrgServer, user: string, file: string, key: string, preferred?: number, known?: OrgAccount, organizationAdmin = false) => {
    const account = known ?? await deps.readOrgAccount(server, user, file, lifetime.signal)
    if (organizationAdmin && !("administrator" in account)) throw new Error("当前 SSH 账号没有服务器管理授权。")
    if (!organizationAdmin && "administrator" in account) throw new Error("请使用管理员入口。")
    const profile = organizationAdmin ? await deps.readAdminProfile(server, user, file, lifetime.signal)
      : "profile" in account ? account.profile : undefined
    if (!profile) throw new Error("管理连接无效。")
    const id = `${server.id}:${user}:${key}:${organizationAdmin ? "admin" : "member"}`
    let tunnel = tunnels.get(id)
    if (!tunnel?.alive()) {
      tunnel?.stop()
      tunnel = await deps.openResearchTunnel(server, user, file, profile, lifetime.signal, preferred)
      tunnels.set(id, tunnel)
    }
    ensureOpen()
    return { account, tunnel }
  }
  const activateAdmin = (server: OrgServer, expires = new Date(Date.now() + 60 * 60_000).toISOString()) => {
    activeAdmin = { keyFile, session: { serverId: server.id, serverLabel: server.label, username, fingerprint, expires_at: expires } }
    store.set("lastServerAdmin", activeAdmin)
    return activeAdmin.session
  }
  const verifyAdmin = async () => {
    if (!activeAdmin || Date.parse(activeAdmin.session.expires_at) <= Date.now()) return undefined
    const record = activeAdmin
    const server = ORG_SERVERS.find(item => item.id === record.session.serverId)
    if (!server) return undefined
    const account = await deps.readOrgAccount(server, record.session.username, record.keyFile, lifetime.signal)
    ensureOpen()
    if (!("administrator" in account) || activeAdmin !== record) throw new Error("服务器管理授权已变化，请重新登录。")
    return { record, server }
  }

  return {
    async scan(input: { keyFile?: string; username?: string }): Promise<QuantCodeSshLoginScan> {
      ensureOpen()
      choices.clear()
      administrators.clear()
      for (const [id, tunnel] of tunnels) {
        if (tunnel.connection.url === activeUrl) continue
        tunnel.stop()
        tunnels.delete(id)
      }
      if (input.keyFile) { keyFile = input.keyFile; fingerprint = "" }
      if (!keyFile) throw new Error("请先选择本地私钥文件。")
      if (!fingerprint) {
        const key = await deps.importKey(keyFile).catch(() => { throw new Error("本机 SSH Agent 未能加载私钥，请确认所选文件是私钥；带口令的密钥请先在系统中解锁。") })
        fingerprint = key.fingerprint
      }
      ensureOpen()
      const raw = store.get("usernames")
      const remembered = raw && typeof raw === "object" && !Array.isArray(raw) && Object.values(raw).every(value => typeof value === "string")
        ? raw as Record<string, string> : {}
      username = input.username?.trim() || remembered[fingerprint] || usernameFromKeyFile(keyFile) || ""
      if (!username) return { username: "", needsUsername: true, servers: [], failed: [] }
      requireUsername(username)
      // An explicit correction is key-specific and survives app restarts, even
      // when the subsequent network probe fails.
      if (input.username?.trim()) store.set("usernames", { ...remembered, [fingerprint]: username })
      const result: QuantCodeSshLoginScan = { username, servers: [], administrators: [], failed: [] }
      for (const server of ORG_SERVERS) {
        ensureOpen()
        try {
          const account = await deps.readOrgAccount(server, username, keyFile, lifetime.signal)
          if ("administrator" in account) {
            administrators.set(server.id, server)
            result.administrators!.push({ ...server, username, systemGroups: account.systemGroups })
            continue
          }
          const { tunnel } = await transport(server, username, keyFile, fingerprint, undefined, account)
          const identity = (await deps.inspect(hostConnection(tunnel.connection), { signal: lifetime.signal })).identities.find(item => item.fingerprint === fingerprint)
          if (!identity) throw new Error("个人研究宿主未登记这把公钥，请联系管理员。")
          // Research accounts intentionally have only a private Unix group.
          // Linux discovery orders known groups; the roster supplies the full
          // authorized list without granting additional filesystem access.
          const groups = [...new Set([...account.groups.filter(group => identity.groups.includes(group)), ...identity.groups])]
          if (!groups.length) throw new Error("组织名册尚未分配工作组，请联系管理员。")
          choices.set(server.id, { server, tunnel, groups })
          result.servers.push({ ...server, username, groups })
        } catch (error) {
          ensureOpen()
          result.failed.push({ id: server.id, reason: sshFailure(error) })
        }
      }
      if (!result.servers.length && !result.administrators?.length) throw new Error(`用户名 ${username} 未能连接可用工作区。${result.failed.map(item => `${item.id}: ${item.reason}`).join("；")}`)
      return result
    },
    async login(input: QuantCodeSshLoginChoice): Promise<QuantCodeSshLoginResult> {
      ensureOpen()
      if ("administrator" in input) {
        if (input.administrator === "organization" && input.serverId !== "server-c") throw new Error("组织管理使用 Server C 的独立入口。")
        const server = administrators.get(input.serverId) ?? (input.administrator === "organization" && activeAdmin
          ? ORG_SERVERS.find(item => item.id === "server-c") : undefined)
        if (!server) throw new Error("请先用管理员私钥探测服务器。")
        const account = await deps.readOrgAccount(server, username, keyFile, lifetime.signal)
        if (!("administrator" in account)) throw new Error("当前 SSH 账号没有服务器管理授权。")
        if (input.administrator === "servers") {
          const admin = activateAdmin(server)
          store.set("lastMode", "server-admin")
          return { mode: "server-admin", admin }
        }
        if (input.administrator !== "organization") throw new Error("管理员入口无效。")
        const { tunnel } = await transport(server, username, keyFile, fingerprint, undefined, account, true)
        const identity = (await deps.inspect(hostConnection(tunnel.connection), { signal: lifetime.signal })).identities.find(item => item.fingerprint === fingerprint)
        if (!identity) throw new Error("这把公钥尚未登记到组织管理服务。")
        const session = await deps.connect(hostConnection(tunnel.connection), { signal: lifetime.signal }, fingerprint)
        await deps.requireAdminSession(hostConnection(tunnel.connection), session, { signal: lifetime.signal })
        ensureOpen()
        const saved: SavedLogin = { keyFile, username, serverId: server.id, group: session.group, fingerprint, actorId: session.actor_id,
          localPort: Number(new URL(tunnel.connection.url).port), organizationAdmin: true }
        store.set("lastLogin", saved)
        store.set("lastMode", "organization-admin")
        const admin = activateAdmin(server)
        activeUrl = tunnel.connection.url
        return { mode: "organization-admin", connection: { ...tunnel.connection, organizationAdmin: true }, session, admin }
      }
      const choice = choices.get(input.serverId)
      if (!choice || !choice.groups.includes(input.group)) throw new Error("请先选择已探测到的工作组和服务器。")
      const identity = (await deps.inspect(hostConnection(choice.tunnel.connection), { signal: lifetime.signal })).identities.find(item => item.fingerprint === fingerprint)
      if (!identity?.groups.includes(input.group)) throw new Error("组织工作组已变化，请重新登录。")
      const session = await deps.connect(hostConnection(choice.tunnel.connection), { signal: lifetime.signal }, fingerprint, input.group)
      ensureOpen()
      if (session.group !== input.group || session.fingerprint !== fingerprint) throw new Error("组织身份与所选工作组不一致，请联系管理员更新研究宿主。")
      const saved: SavedLogin = { keyFile, username, serverId: choice.server.id, group: session.group, fingerprint,
        actorId: session.actor_id, localPort: Number(new URL(choice.tunnel.connection.url).port) }
      store.set("lastLogin", saved)
      store.set("lastMode", "member")
      activeAdmin = undefined
      store.set("lastServerAdmin", null)
      activeUrl = choice.tunnel.connection.url
      return { connection: choice.tunnel.connection, session }
    },
    async restore() {
      ensureOpen()
      if (store.get("lastMode") === "server-admin") {
        const raw = store.get("lastServerAdmin") as { keyFile?: unknown; session?: Partial<QuantCodeServerAdminSession> } | undefined
        if (!raw || typeof raw.keyFile !== "string" || !raw.session ||
          [raw.session.serverId, raw.session.serverLabel, raw.session.username, raw.session.fingerprint, raw.session.expires_at].some(value => typeof value !== "string" || !value) ||
          !Number.isFinite(Date.parse(raw.session.expires_at!)) || Date.parse(raw.session.expires_at!) <= Date.now()) return null
        activeAdmin = { keyFile: raw.keyFile, session: raw.session as QuantCodeServerAdminSession }
        const verified = await verifyAdmin()
        if (!verified) return null
        keyFile = verified.record.keyFile
        username = verified.record.session.username
        fingerprint = verified.record.session.fingerprint
        administrators.set(verified.server.id, verified.server)
        return { admin: verified.record.session }
      }
      const record = savedLogin(store.get("lastLogin"))
      if (!record) return null
      const server = ORG_SERVERS.find(item => item.id === record.serverId)
      if (!server) return null
      requireUsername(record.username)
      const { tunnel } = await transport(server, record.username, record.keyFile, record.fingerprint, record.localPort, undefined, record.organizationAdmin)
      const current = await deps.inspect(hostConnection(tunnel.connection), { signal: lifetime.signal })
      ensureOpen()
      if (current.session && (current.session.fingerprint !== record.fingerprint || current.session.actor_id !== record.actorId || current.session.group !== record.group)) {
        tunnel.stop()
        throw new Error("研究宿主的登录身份已变化，请重新登录。")
      }
      if (record.organizationAdmin && current.session) await deps.requireAdminSession(hostConnection(tunnel.connection), current.session, { signal: lifetime.signal })
      if (record.organizationAdmin && current.session) {
        keyFile = record.keyFile
        username = record.username
        fingerprint = record.fingerprint
        administrators.set(server.id, server)
        activateAdmin(server, current.session.expires_at)
      }
      activeUrl = tunnel.connection.url
      const session = current.session?.fingerprint === record.fingerprint && current.session.actor_id === record.actorId && current.session.group === record.group
        ? current.session : null
      return { connection: { ...tunnel.connection, ...(record.organizationAdmin ? { organizationAdmin: true } : {}) }, session,
        ...(record.organizationAdmin && current.session && activeAdmin ? { admin: activeAdmin.session } : {}) }
    },
    async adminStatus() {
      const verified = await verifyAdmin()
      if (!verified) { activeAdmin = undefined; return null }
      const report = await deps.readServerAdminStatus(verified.server, verified.record.session.username, verified.record.keyFile, lifetime.signal)
      ensureOpen()
      if (activeAdmin !== verified.record) throw new Error("服务器管理身份已变化，请重试。")
      return { session: verified.record.session, report }
    },
    adminDisconnect() {
      activeAdmin = undefined
      store.set("lastServerAdmin", null)
      if (store.get("lastMode") === "server-admin") store.set("lastMode", null)
    },
    connection(url: string) {
      const connection = [...tunnels.values()].find(item => item.connection.url === url && item.alive())?.connection
      return connection ? hostConnection(connection) : undefined
    },
    close() {
      lifetime.abort()
      for (const tunnel of tunnels.values()) tunnel.stop()
      tunnels.clear()
      choices.clear()
      administrators.clear()
      activeAdmin = undefined
    },
  }
}

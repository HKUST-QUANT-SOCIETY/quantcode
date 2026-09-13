import type { QuantCodeIdentityGroup, QuantCodeSshLoginResult, QuantCodeSshLoginScan, QuantCodeSshLoginChoice, QuantCodeServerAdminSession, QuantCodeIdentitySession, QuantCodeConnectionState } from "@opencode-ai/app/identity"
import { connect, disconnect, importKey, inspect, requireAdminSession } from "./quantcode-identity"
import { ORG_SERVERS, openResearchTunnel, readOrgAccount, readAdminProfile, readServerAdminStatus, requireUsername, sshFailure, usernameFromKeyFile } from "./quantcode-ssh-login"
import type { ResearchConnection } from "./quantcode-connection"
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
const dependencies = { readOrgAccount, readAdminProfile, readServerAdminStatus, requireAdminSession, openResearchTunnel, inspect, connect, disconnect,
  importKey: (file: string) => importKey({ url: "http://127.0.0.1" }, file) }

/** Each desktop window owns its selected key and SSH transports. Renderer input
 * can select a discovered server/group, never a key path, command or credential. */
export function createOrgLogin(store: LoginStore, deps = dependencies, onTransportChange?: (state: QuantCodeConnectionState) => void) {
  const lifetime = new AbortController()
  const tunnels = new Map<string, ResearchTunnel>()
  const administrators = new Map<string, OrgServer>()
  let activeAdmin: { keyFile: string; session: QuantCodeServerAdminSession; connection: ResearchConnection; identity: QuantCodeIdentitySession } | undefined
  const choices = new Map<string, { server: OrgServer; tunnel: ResearchTunnel; groups: QuantCodeIdentityGroup[] }>()
  let keyFile = ""
  let fingerprint = ""
  let username = ""
  let activeUrl = ""
  const transcript: string[] = []
  let pendingAttempt: AbortController | undefined
  const log = (message: string) => { transcript.push(`${new Date().toLocaleTimeString()}  ${message}`); if (transcript.length > 80) transcript.shift() }
  const matches = (tunnel: ResearchTunnel, server: string) => tunnel.connection.managedId === server || tunnel.connection.url === server || tunnel.connection.previousUrls?.includes(server)
  const connectionState = (tunnel: ResearchTunnel): QuantCodeConnectionState => ({ server: tunnel.connection.managedId ?? tunnel.connection.url,
    url: tunnel.connection.url, ...(tunnel.status?.() ?? { state: tunnel.alive() ? "connected" : "offline", generation: 0 }) })

  const ensureOpen = () => lifetime.signal.throwIfAborted()
  const beginAttempt = (signal?: AbortSignal) => {
    pendingAttempt?.abort()
    const controller = new AbortController()
    pendingAttempt = controller
    const combined = AbortSignal.any([lifetime.signal, controller.signal, ...(signal ? [signal] : [])])
    return { signal: combined, check: () => combined.throwIfAborted(), finish: () => { if (pendingAttempt === controller) pendingAttempt = undefined } }
  }
  const cancelAttempt = () => {
    pendingAttempt?.abort()
    pendingAttempt = undefined
    choices.clear()
    administrators.clear()
    for (const [id, tunnel] of tunnels) if (tunnel.connection.url !== activeUrl) { tunnel.stop(); tunnels.delete(id) }
  }
  const selectKey = (file: string) => { cancelAttempt(); keyFile = file; fingerprint = ""; username = ""; transcript.length = 0 }
  const transport = async (server: OrgServer, user: string, file: string, key: string, preferred?: number, known?: OrgAccount, organizationAdmin = false, signal = lifetime.signal) => {
    signal.throwIfAborted()
    const account = known ?? await deps.readOrgAccount(server, user, file, signal)
    if (organizationAdmin && !("administrator" in account)) throw new Error("当前 SSH 账号没有服务器管理授权。")
    if (!organizationAdmin && "administrator" in account) throw new Error("请使用管理员入口。")
    const profile = organizationAdmin ? await deps.readAdminProfile(server, user, file, signal)
      : "profile" in account ? account.profile : undefined
    if (!profile) throw new Error("管理连接无效。")
    const id = `${server.id}:${user}:${key}:${organizationAdmin ? "admin" : "member"}`
    let tunnel = tunnels.get(id)
    if (tunnel?.ensureConnected) await tunnel.ensureConnected()
    if (!tunnel?.alive()) {
      tunnel?.stop()
      tunnel = await deps.openResearchTunnel(server, user, file, profile, lifetime.signal, preferred, signal)
      tunnel.connection.managedId = `quantcode-ssh:${server.id}:${user}:${key}:${organizationAdmin ? "admin" : "member"}`
      tunnel.connection.previousUrls = [...new Set([profile.url, ...(preferred ? [`http://127.0.0.1:${preferred}`] : [])])]
      tunnels.set(id, tunnel)
      const watched = tunnel
      tunnel.subscribe?.(state => {
        log(`${server.label} · ${state.state}${state.reason ? ` · ${state.reason}` : ""}`)
        onTransportChange?.(connectionState(watched))
      })
    }
    ensureOpen()
    signal.throwIfAborted()
    tunnel.connection.verifiedAt = Date.now()
    return { account, tunnel }
  }
  const activateAdmin = (server: OrgServer, connection: ResearchConnection, identity: QuantCodeIdentitySession) => {
    activeAdmin = { keyFile, connection, identity, session: { serverId: server.id, serverLabel: server.label, username, fingerprint, expires_at: identity.expires_at } }
    return activeAdmin.session
  }
  const verifyAdmin = async (serverId?: string) => {
    if (!activeAdmin || Date.parse(activeAdmin.identity.expires_at) <= Date.now()) return undefined
    const record = activeAdmin
    await deps.requireAdminSession(record.connection, record.identity, { signal: lifetime.signal })
    const server = ORG_SERVERS.find(item => item.id === (serverId ?? record.session.serverId))
    if (!server) throw new Error("请选择内置服务器。")
    const account = await deps.readOrgAccount(server, record.session.username, record.keyFile, lifetime.signal)
    ensureOpen()
    if (!("administrator" in account) || activeAdmin !== record) throw new Error("管理员权限已变化，请重新登录。")
    return { record, server }
  }

  return {
    progress: () => [...transcript],
    beginSelection() { ensureOpen(); transcript.length = 0; log("等待选择本地 SSH 私钥文件…") },
    selectKey,
    cancelAttempt,
    connectionState(server: string) {
      const tunnel = [...tunnels.values()].find(tunnel => matches(tunnel, server))
      return tunnel ? connectionState(tunnel) : null
    },
    async reconnect(server: string) {
      const tunnel = [...tunnels.values()].find(tunnel => matches(tunnel, server))
      if (!tunnel) throw new Error("未找到当前工作连接，请重新登录。")
      if (tunnel.reconnect) await tunnel.reconnect()
      else if (!tunnel.alive()) throw new Error("工作连接已关闭，请重新登录。")
    },
    async scan(input: { keyFile?: string; username?: string }, signal?: AbortSignal): Promise<QuantCodeSshLoginScan> {
      ensureOpen()
      signal?.throwIfAborted()
      if (input.keyFile) selectKey(input.keyFile)
      const operation = beginAttempt(signal)
      try {
        operation.check()
        choices.clear()
        administrators.clear()
        for (const [id, tunnel] of tunnels) {
          if (tunnel.connection.url === activeUrl) continue
          tunnel.stop()
          tunnels.delete(id)
        }
        if (!keyFile) throw new Error("请先选择本地私钥文件。")
        if (!fingerprint) {
          log("正在将所选私钥加载到本机 SSH Agent…")
          const key = await deps.importKey(keyFile).catch(() => { throw new Error("本机 SSH Agent 未能加载私钥，请确认所选文件是私钥；带口令的密钥请先在系统中解锁。") })
          operation.check()
          fingerprint = key.fingerprint
          log(`本机密钥已就绪 · ${fingerprint}`)
        }
        operation.check()
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
          operation.check()
          log(`连接 ${server.label} · ssh ${username}@${server.host}`)
          try {
            const account = await deps.readOrgAccount(server, username, keyFile, operation.signal)
            operation.check()
            log(`${server.label} SSH 身份验证通过，正在读取组授权`)
            if ("administrator" in account) {
              log(`${server.label} · 已识别管理员账号`)
              administrators.set(server.id, server)
              result.administrators!.push({ ...server, username, systemGroups: account.systemGroups })
              continue
            }
            const { tunnel } = await transport(server, username, keyFile, fingerprint, undefined, account, false, operation.signal)
            const identity = (await deps.inspect(hostConnection(tunnel.connection), { signal: operation.signal })).identities.find(item => item.fingerprint === fingerprint)
            operation.check()
            if (!identity) throw new Error("个人研究宿主未登记这把公钥，请联系管理员。")
            // Research accounts intentionally have only a private Unix group.
            // Linux discovery orders known groups; the roster supplies the full
            // authorized list without granting additional filesystem access.
            const groups = [...new Set([...account.groups.filter(group => identity.groups.includes(group)), ...identity.groups])]
            if (!groups.length) throw new Error("组织名册尚未分配工作组，请联系管理员。")
            log(`${server.label} · 授权工作组：${groups.join("、")}`)
            choices.set(server.id, { server, tunnel, groups })
            result.servers.push({ ...server, username, groups })
          } catch (error) {
            operation.check()
            log(`${server.label} · ${sshFailure(error)}`)
            result.failed.push({ id: server.id, reason: sshFailure(error) })
          }
        }
        if (!result.servers.length && !result.administrators?.length) throw new Error(`用户名 ${username} 未能连接可用工作区。${result.failed.map(item => `${item.id}: ${item.reason}`).join("；")}`)
        return result
      } finally { operation.finish() }
    },
    async login(input: QuantCodeSshLoginChoice, signal?: AbortSignal): Promise<QuantCodeSshLoginResult> {
      ensureOpen()
      signal?.throwIfAborted()
      const operation = beginAttempt(signal)
      try {
        operation.check()
        log("正在连接所选工作区并完成组织签名认证…")
        if ("administrator" in input) {
          if (input.serverId !== "server-c") throw new Error("组织管理使用 Server C 的独立入口。")
          const server = administrators.get(input.serverId) ?? (input.administrator === "organization" && activeAdmin
            ? ORG_SERVERS.find(item => item.id === "server-c") : undefined)
          if (!server) throw new Error("请先用管理员私钥探测服务器。")
          const account = await deps.readOrgAccount(server, username, keyFile, operation.signal)
          if (!("administrator" in account)) throw new Error("当前 SSH 账号没有服务器管理授权。")
          // Both legacy entry names now complete the same full administrator
          // login. SSH access alone can never create a partial logged-in state.
          if (!["servers", "organization"].includes(input.administrator)) throw new Error("管理员入口无效。")
          const { tunnel } = await transport(server, username, keyFile, fingerprint, undefined, account, true, operation.signal)
          const identity = (await deps.inspect(hostConnection(tunnel.connection), { signal: operation.signal })).identities.find(item => item.fingerprint === fingerprint)
          if (!identity) throw new Error("这把公钥尚未登记到组织管理服务。")
          const session = await deps.connect(hostConnection(tunnel.connection), { signal: operation.signal }, fingerprint)
          await deps.requireAdminSession(hostConnection(tunnel.connection), session, { signal: operation.signal })
          operation.check()
          const saved: SavedLogin = { keyFile, username, serverId: server.id, group: session.group, fingerprint, actorId: session.actor_id,
            localPort: Number(new URL(tunnel.connection.url).port), organizationAdmin: true }
          store.set("lastLogin", saved)
          store.set("lastMode", "organization-admin")
          const admin = activateAdmin(server, hostConnection(tunnel.connection), session)
          activeUrl = tunnel.connection.url
          log(`已登录 · ${session.actor_id} · 管理员 · 全部权限`)
          return { mode: "organization-admin", connection: { ...tunnel.connection, organizationAdmin: true }, session, admin }
        }
        const choice = choices.get(input.serverId)
        if (!choice || !choice.groups.includes(input.group)) throw new Error("请先选择已探测到的工作组和服务器。")
        const identity = (await deps.inspect(hostConnection(choice.tunnel.connection), { signal: operation.signal })).identities.find(item => item.fingerprint === fingerprint)
        if (!identity?.groups.includes(input.group)) throw new Error("组织工作组已变化，请重新登录。")
        const session = await deps.connect(hostConnection(choice.tunnel.connection), { signal: operation.signal }, fingerprint, input.group)
        operation.check()
        if (session.group !== input.group || session.fingerprint !== fingerprint) throw new Error("组织身份与所选工作组不一致，请联系管理员更新研究宿主。")
        const saved: SavedLogin = { keyFile, username, serverId: choice.server.id, group: session.group, fingerprint,
          actorId: session.actor_id, localPort: Number(new URL(choice.tunnel.connection.url).port) }
        store.set("lastLogin", saved)
        store.set("lastMode", "member")
        activeAdmin = undefined
        activeUrl = choice.tunnel.connection.url
        log(`已登录 · ${session.actor_id} · ${session.group}`)
        return { connection: choice.tunnel.connection, session }
      } finally { operation.finish() }
    },
    async restore() {
      ensureOpen()
      // Previous releases only proved SSH access. Require one real admin
      // login when upgrading; never manufacture organization authorization.
      if (store.get("lastMode") === "server-admin") return { needsLogin: true as const }
      const record = savedLogin(store.get("lastLogin"))
      if (!record) return null
      const server = ORG_SERVERS.find(item => item.id === record.serverId)
      if (!server) return null
      requireUsername(record.username)
      log(`恢复连接 · ${server.label} · ssh ${record.username}@${server.host}`)
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
        activateAdmin(server, hostConnection(tunnel.connection), current.session)
      }
      activeUrl = tunnel.connection.url
      store.set("lastLogin", { ...record, localPort: Number(new URL(tunnel.connection.url).port) })
      const session = current.session?.fingerprint === record.fingerprint && current.session.actor_id === record.actorId && current.session.group === record.group
        ? current.session : null
      log(current.session ? `已恢复有效会话 · ${current.session.actor_id}` : "连接已恢复，组织会话需要重新认证")
      return { connection: { ...tunnel.connection, ...(record.organizationAdmin ? { organizationAdmin: true } : {}) }, session,
        ...(record.organizationAdmin && current.session && activeAdmin ? { admin: activeAdmin.session } : {}) }
    },
    async adminStatus(input?: { serverId?: string }) {
      const verified = await verifyAdmin(input?.serverId)
      if (!verified) { activeAdmin = undefined; return null }
      const report = await deps.readServerAdminStatus(verified.server, verified.record.session.username, verified.record.keyFile, lifetime.signal)
      ensureOpen()
      if (activeAdmin !== verified.record) throw new Error("服务器管理身份已变化，请重试。")
      return { session: { ...verified.record.session, serverId: verified.server.id, serverLabel: verified.server.label }, report }
    },
    async adminDisconnect() {
      if (!activeAdmin) return
      await deps.disconnect(activeAdmin.connection, { signal: lifetime.signal })
      activeAdmin = undefined
    },
    released(url: string) {
      if (activeAdmin?.connection.url === url) activeAdmin = undefined
    },
    connection(url: string) {
      const connection = [...tunnels.values()].find(item => matches(item, url) && item.alive())?.connection
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

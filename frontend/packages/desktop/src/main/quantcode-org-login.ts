import type { QuantCodeIdentityGroup, QuantCodeSshLoginResult, QuantCodeSshLoginScan, QuantCodeSshLoginChoice, QuantCodeServerAdminSession, QuantCodeIdentitySession, QuantCodeConnectionState } from "@opencode-ai/app/identity"
import { connect, disconnect, importKey, inspect, requireAdminSession, IdentityResultUncertain } from "./quantcode-identity"
import { ORG_SERVERS, openResearchTunnel, readOrgAccount, readAdminProfile, readServerAdminStatus, requireUsername, sshFailure, usernameFromKeyFile, resolveSshTarget } from "./quantcode-ssh-login"
import type { ResearchConnection } from "./quantcode-connection"
import type { OrgServer, ResearchTunnel, OrgAccount } from "./quantcode-ssh-login"
import { randomUUID } from 'node:crypto'

type SavedLogin = { keyFile: string; username: string; serverId: string; group: string; fingerprint: string; actorId: string; localPort: number; organizationAdmin?: boolean; requiresConfirmation?: boolean; sessionId?: string; attemptId?: string }
function savedLogin(value: unknown): SavedLogin | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return
  const data = value as Partial<SavedLogin>
  if ([data.keyFile, data.username, data.serverId, data.group, data.fingerprint, data.actorId].some(item => typeof item !== "string" || !item) ||
    typeof data.localPort !== "number" || !Number.isInteger(data.localPort) || data.localPort < 1024 || data.localPort > 65535) return
  return data as SavedLogin
}
type LoginStore = { get: (key: string) => unknown; set: (key: string, value: unknown) => void }
const hostConnection = (connection: ResearchTunnel["connection"]) => ({ url: connection.url, username: connection.username, password: connection.password })
const dependencies = { readOrgAccount, readAdminProfile, readServerAdminStatus, requireAdminSession, openResearchTunnel, inspect, connect, disconnect, resolveSshTarget,
  importKey: (file: string) => importKey({ url: "http://127.0.0.1" }, file) }
type LoginDependencies = Omit<typeof dependencies, 'resolveSshTarget'> & { resolveSshTarget?: typeof resolveSshTarget }

/** Each desktop window owns its selected key and SSH transports. Renderer input
 * can select a discovered server/group, never a key path, command or credential. */
export function createOrgLogin(store: LoginStore, deps: LoginDependencies = dependencies, onTransportChange?: (state: QuantCodeConnectionState) => void) {
  const lifetime = new AbortController()
  const tunnels = new Map<string, ResearchTunnel>()
  const profiles = new Map<string, string>()
  const administrators = new Map<string, OrgServer>()
  let activeAdmin: { keyFile: string; session: QuantCodeServerAdminSession; connection: ResearchConnection; identity: QuantCodeIdentitySession } | undefined
  const choices = new Map<string, { server: OrgServer; username: string; tunnel: ResearchTunnel; groups: QuantCodeIdentityGroup[] }>()
  const adminUsers = new Map<string, string>()
  let keyFile = ""
  let fingerprint = ""
  let username = ""
  let activeUrl = ""
  const transcript: string[] = []
  let pendingAttempt: AbortController | undefined
  let pendingLogin: { record: SavedLogin; server: OrgServer; tunnel: ResearchTunnel } | undefined
  let completed: QuantCodeSshLoginResult | undefined
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
    adminUsers.clear()
    for (const [id, tunnel] of tunnels) if (tunnel.connection.url !== activeUrl && tunnel !== pendingLogin?.tunnel) { tunnel.stop(); tunnels.delete(id) }
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
    const revision = JSON.stringify(profile)
    let tunnel = tunnels.get(id)
    const previous = tunnel
    if (profiles.get(id) === revision && tunnel?.ensureConnected) await tunnel.ensureConnected().catch(() => undefined)
    if (!tunnel?.alive() || profiles.get(id) !== revision) {
      // Keep the previous connection until its replacement can be established.
      tunnel = await deps.openResearchTunnel(server, user, file, profile, lifetime.signal, preferred, signal)
      tunnel.connection.managedId = `quantcode-ssh:${server.id}:${user}:${key}:${organizationAdmin ? "admin" : "member"}`
      tunnel.connection.previousUrls = [...new Set([profile.url, ...(previous ? [previous.connection.url, ...(previous.connection.previousUrls ?? [])] : []), ...(preferred ? [`http://127.0.0.1:${preferred}`] : [])])]
      tunnels.set(id, tunnel)
      profiles.set(id, revision)
      if (activeUrl === previous?.connection.url) activeUrl = tunnel.connection.url
      previous?.stop()
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
  const beginLogin = (server: OrgServer, tunnel: ResearchTunnel, user: string, group: string, organizationAdmin = false) => {
    if (store.get('pendingLogin')) throw new Error('另一份登录结果尚未确认，请先核对或退出原登录。')
    const record: SavedLogin = { keyFile, username: user, serverId: server.id, group, fingerprint, actorId: 'pending',
      localPort: Number(new URL(tunnel.connection.url).port), organizationAdmin, requiresConfirmation: true, attemptId: randomUUID() }
    pendingLogin = { record, server, tunnel }
    completed = undefined
    store.set('pendingLogin', record)
  }
  const completeLogin = (record: SavedLogin, tunnel: ResearchTunnel, server: OrgServer, session: QuantCodeIdentitySession): QuantCodeSshLoginResult => {
    if (session.fingerprint !== record.fingerprint || session.group !== record.group) throw new Error('登录身份已变化，请核对原工作区。')
    store.set('lastLogin', { ...record, actorId: session.actor_id, sessionId: session.session_id, requiresConfirmation: true })
    store.set('lastMode', record.organizationAdmin ? 'organization-admin' : 'member')
    store.set('pendingLogin', null)
    activeUrl = tunnel.connection.url
    pendingLogin = undefined
    activeAdmin = undefined
    if (record.organizationAdmin) {
      keyFile = record.keyFile; username = record.username; fingerprint = record.fingerprint
      const admin = activateAdmin(server, hostConnection(tunnel.connection), session)
      completed = { mode: 'organization-admin', connection: { ...tunnel.connection, organizationAdmin: true }, session, admin }
    } else completed = { connection: tunnel.connection, session }
    return completed
  }

  return {
    progress: () => [...transcript],
    beginSelection() { ensureOpen(); transcript.length = 0; log("等待选择本地 SSH 私钥文件…") },
    selectKey,
    selectedKey: () => keyFile,
    cancelAttempt,
    needsResolution: () => !!store.get('pendingLogin') || !!completed && !!savedLogin(store.get('lastLogin'))?.requiresConfirmation,
    acknowledge(sessionId: string) {
      if (!completed || completed.session.session_id !== sessionId) throw new Error('登录身份已变化，请重新核验。')
      const saved = savedLogin(store.get('lastLogin'))
      if (!saved || saved.sessionId !== sessionId) throw new Error('登录身份已变化，请重新核验。')
      store.set('lastLogin', { ...saved, requiresConfirmation: false })
    },
    async resolveLogin() {
      ensureOpen()
      if (!pendingLogin) {
        if (!completed || !savedLogin(store.get('lastLogin'))?.requiresConfirmation) return null
        const current = await deps.inspect(hostConnection(completed.connection), { signal: lifetime.signal })
        if (!current.session) { completed = undefined; return null }
        if (current.session.session_id !== completed.session.session_id) throw new Error('登录身份已变化，请重新核验当前工作区。')
        return completed
      }
      const { record, server, tunnel } = pendingLogin
      const result = await deps.inspect(hostConnection(tunnel.connection), { signal: lifetime.signal })
      if (!result.session) throw new Error('认证结果仍未确认。可以稍后核对，或明确退出本次登录。')
      if (record.organizationAdmin) await deps.requireAdminSession(hostConnection(tunnel.connection), result.session, { signal: lifetime.signal })
      ensureOpen()
      return completeLogin(record, tunnel, server, result.session)
    },
    async exitAttempt() {
      const connection = pendingLogin?.tunnel.connection ?? completed?.connection
      if (!connection) return
      const expected = pendingLogin?.record ?? completed?.session
      const target = pendingLogin?.record ?? savedLogin(store.get('lastLogin'))
      const current = await deps.inspect(hostConnection(connection), { signal: lifetime.signal })
      if (current.session && expected && (current.session.fingerprint !== expected.fingerprint || current.session.group !== expected.group)) throw new Error('工作区已切换身份，不能退出另一份会话。')
      await deps.disconnect(hostConnection(connection), { signal: lifetime.signal })
      store.set('pendingLogin', null)
      const saved = savedLogin(store.get('lastLogin'))
      if (saved?.serverId === target?.serverId && saved?.username === target?.username && saved?.fingerprint === expected?.fingerprint && saved?.group === expected?.group) store.set('lastLogin', null)
      pendingLogin = undefined; completed = undefined
      if (activeAdmin?.connection.url === connection.url) activeAdmin = undefined
      if (activeUrl === connection.url) activeUrl = ''
      cancelAttempt()
    },
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
      if (pendingLogin) throw new Error('请先核对上次登录结果，或明确退出本次登录。')
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
          const key = await deps.importKey(keyFile)
          operation.check()
          fingerprint = key.fingerprint
          log(`本机密钥已就绪 · ${fingerprint}`)
        }
        operation.check()
        const raw = store.get("usernames")
        const remembered = raw && typeof raw === "object" && !Array.isArray(raw) && Object.values(raw).every(value => typeof value === "string")
          ? raw as Record<string, string> : {}
        username = input.username?.trim() || remembered[fingerprint] || usernameFromKeyFile(keyFile) || ""
        const queue = await Promise.all(ORG_SERVERS.map(server => deps.resolveSshTarget?.(server, username, operation.signal, !input.username?.trim()) ?? { server, username }))
        if (!queue.some(target => target.username)) return { username: "", needsUsername: true, servers: [], failed: [] }
        if (username) requireUsername(username)
        // An explicit correction is key-specific and survives app restarts, even
        // when the subsequent network probe fails.
        if (input.username?.trim()) store.set("usernames", { ...remembered, [fingerprint]: username })
        const result: QuantCodeSshLoginScan = { username, servers: [], administrators: [], failed: [] }
        const visited = new Set<string>()
        for (let index = 0; index < queue.length && index < 12; index++) {
          operation.check()
          const { server, username: user } = queue[index]
          if (!user || choices.has(server.id) || visited.has(`${server.id}:${user}`)) continue
          visited.add(`${server.id}:${user}`)
          const probeSignal = AbortSignal.any([operation.signal, AbortSignal.timeout(18000)])
          log(`连接 ${server.label} · ssh ${user}@${server.host}`)
          try {
            const account = await deps.readOrgAccount(server, user, keyFile, probeSignal)
            operation.check()
            log(`${server.label} SSH 身份验证通过，正在读取组授权`)
            if ('routes' in account) {
              const routes = account.routes.filter(route => route.fingerprints.includes(fingerprint))
              if (!routes.length) throw new Error('SSH 已连接，但这把公钥尚未关联 QuantCode 工作区，请联系管理员核对公钥登记。')
              for (const route of routes) {
                const target = ORG_SERVERS.find(item => item.id === route.serverId)
                if (!target) continue
                const resolved = await deps.resolveSshTarget?.(target, route.username, operation.signal, false) ?? { server: target, username: route.username }
                queue.splice(index + 1, 0, resolved)
                log(`${server.label} · 已找到授权工作区，继续连接 ${target.label}`)
              }
              continue
            }
            if ("administrator" in account) {
              log(`${server.label} · 已识别管理员账号`)
              administrators.set(server.id, server)
              adminUsers.set(server.id, user)
              result.administrators!.push({ ...server, username: user, systemGroups: account.systemGroups })
              continue
            }
            const { tunnel } = await transport(server, user, keyFile, fingerprint, undefined, account, false, probeSignal)
            const identity = (await deps.inspect(hostConnection(tunnel.connection), { signal: probeSignal })).identities.find(item => item.fingerprint === fingerprint)
            operation.check()
            if (!identity) throw new Error("个人研究宿主未登记这把公钥，请联系管理员。")
            // Research accounts intentionally have only a private Unix group.
            // Linux discovery orders known groups; the roster supplies the full
            // authorized list without granting additional filesystem access.
            const groups = [...new Set([...account.groups.filter(group => identity.groups.includes(group)), ...identity.groups])]
            if (!groups.length) throw new Error("组织名册尚未分配工作组，请联系管理员。")
            log(`${server.label} · 授权工作组：${groups.join("、")}`)
            choices.set(server.id, { server, username: user, tunnel, groups })
            result.failed = result.failed.filter(item => item.id !== server.id)
            result.servers.push({ ...server, username: user, groups })
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
      let authenticated = false
      try {
        operation.check()
        log("正在连接所选工作区并完成组织签名认证…")
        if ("administrator" in input) {
          if (input.serverId !== "server-c") throw new Error("组织管理使用 Server C 的独立入口。")
          const server = administrators.get(input.serverId) ?? (input.administrator === "organization" && activeAdmin
            ? ORG_SERVERS.find(item => item.id === "server-c") : undefined)
          if (!server) throw new Error("请先用管理员私钥探测服务器。")
          username = adminUsers.get(input.serverId) ?? username
          const account = await deps.readOrgAccount(server, username, keyFile, operation.signal)
          if (!("administrator" in account)) throw new Error("当前 SSH 账号没有服务器管理授权。")
          // Both legacy entry names now complete the same full administrator
          // login. SSH access alone can never create a partial logged-in state.
          if (!["servers", "organization"].includes(input.administrator)) throw new Error("管理员入口无效。")
          const { tunnel } = await transport(server, username, keyFile, fingerprint, undefined, account, true, operation.signal)
          const identity = (await deps.inspect(hostConnection(tunnel.connection), { signal: operation.signal })).identities.find(item => item.fingerprint === fingerprint)
          if (!identity) throw new Error("这把公钥尚未登记到组织管理服务。")
          beginLogin(server, tunnel, username, identity.group, true)
          const session = await deps.connect(hostConnection(tunnel.connection), { signal: operation.signal }, fingerprint)
          authenticated = true
          await deps.requireAdminSession(hostConnection(tunnel.connection), session, { signal: operation.signal })
          operation.check()
          const result = completeLogin(pendingLogin!.record, tunnel, server, session)
          log(`已登录 · ${session.actor_id} · 管理员 · 全部权限`)
          return result
        }
        const choice = choices.get(input.serverId)
        if (!choice || !choice.groups.includes(input.group)) throw new Error("请先选择已探测到的工作组和服务器。")
        const identity = (await deps.inspect(hostConnection(choice.tunnel.connection), { signal: operation.signal })).identities.find(item => item.fingerprint === fingerprint)
        if (!identity?.groups.includes(input.group)) throw new Error("组织工作组已变化，请重新登录。")
        beginLogin(choice.server, choice.tunnel, choice.username, input.group)
        const session = await deps.connect(hostConnection(choice.tunnel.connection), { signal: operation.signal }, fingerprint, input.group)
        authenticated = true
        operation.check()
        if (session.group !== input.group || session.fingerprint !== fingerprint) throw new Error("组织身份与所选工作组不一致，请联系管理员更新研究宿主。")
        const result = completeLogin(pendingLogin!.record, choice.tunnel, choice.server, session)
        log(`已登录 · ${session.actor_id} · ${session.group}`)
        return result
      } catch (cause) {
        if (pendingLogin && !authenticated && !(cause instanceof IdentityResultUncertain)) {
          pendingLogin = undefined
          store.set('pendingLogin', null)
        }
        throw cause
      } finally { operation.finish() }
    },
    async restore(signal?: AbortSignal) {
      ensureOpen()
      const operation = beginAttempt(signal)
      try {
      // Previous releases only proved SSH access. Require one real admin
      // login when upgrading; never manufacture organization authorization.
      if (store.get("lastMode") === "server-admin") return { needsLogin: true as const }
      const pending = savedLogin(store.get('pendingLogin'))
      const record = pending ?? savedLogin(store.get("lastLogin"))
      if (!record) return null
      const server = ORG_SERVERS.find(item => item.id === record.serverId)
      if (!server) return null
      requireUsername(record.username)
      log(`恢复连接 · ${server.label} · ssh ${record.username}@${server.host}`)
      const target = await deps.resolveSshTarget?.(server, record.username, operation.signal, false) ?? { server, username: record.username }
      const { tunnel } = await transport(target.server, record.username, record.keyFile, record.fingerprint, record.localPort, undefined, record.organizationAdmin, operation.signal)
      const current = await deps.inspect(hostConnection(tunnel.connection), { signal: operation.signal })
      operation.check()
      if (current.session && (current.session.fingerprint !== record.fingerprint || !pending && current.session.actor_id !== record.actorId || current.session.group !== record.group)) {
        tunnel.stop()
        throw new Error("研究宿主的登录身份已变化，请重新登录。")
      }
      if (record.organizationAdmin && current.session) await deps.requireAdminSession(hostConnection(tunnel.connection), current.session, { signal: operation.signal })
      operation.check()
      if (record.organizationAdmin && current.session) {
        keyFile = record.keyFile
        username = record.username
        fingerprint = record.fingerprint
        administrators.set(server.id, server)
        activateAdmin(server, hostConnection(tunnel.connection), current.session)
      }
      activeUrl = tunnel.connection.url
      store.set("lastLogin", { ...record, localPort: Number(new URL(tunnel.connection.url).port), sessionId: current.session?.session_id })
      const session = current.session?.fingerprint === record.fingerprint && (pending || current.session.actor_id === record.actorId) && current.session.group === record.group
        ? current.session : null
      if (pending) pendingLogin = { record, server: target.server, tunnel }
      if (session) {
        completed = { connection: { ...tunnel.connection, organizationAdmin: record.organizationAdmin }, session,
          ...(record.organizationAdmin && activeAdmin ? { mode: 'organization-admin', admin: activeAdmin.session } : {}) }
        if (pending) completeLogin(record, tunnel, target.server, session)
      }
      log(current.session ? `已恢复有效会话 · ${current.session.actor_id}` : "连接已恢复，组织会话需要重新认证")
      return { connection: { ...tunnel.connection, ...(record.organizationAdmin ? { organizationAdmin: true } : {}) }, session,
        requiresConfirmation: !!pending || !!record.requiresConfirmation,
        ...(record.organizationAdmin && current.session && activeAdmin ? { admin: activeAdmin.session } : {}) }
      } finally { operation.finish() }
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
      const tunnel = [...tunnels.values()].find(item => matches(item, url))
      if (activeAdmin?.connection.url === (tunnel?.connection.url ?? url)) activeAdmin = undefined
      if (completed?.connection.url === (tunnel?.connection.url ?? url)) completed = undefined
    },
    connection(url: string) {
      const connection = [...tunnels.values()].find(item => matches(item, url) && item.alive())?.connection
      return connection ? hostConnection(connection) : undefined
    },
    close() {
      lifetime.abort()
      for (const tunnel of tunnels.values()) tunnel.stop()
      tunnels.clear()
      profiles.clear()
      choices.clear()
      administrators.clear()
      adminUsers.clear()
      activeAdmin = undefined
      pendingLogin = undefined
      completed = undefined
      keyFile = fingerprint = username = activeUrl = ''
    },
  }
}

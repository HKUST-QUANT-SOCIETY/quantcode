import { describe, expect, test } from "bun:test"
import type { QuantCodeIdentitySession } from "@opencode-ai/app/identity"
import { createOrgLogin } from "./quantcode-org-login"
import { businessGroups, parseResearchProfile, sshArguments, usernameFromKeyFile } from "./quantcode-ssh-login"

const keyFile = "/fixture/qc-chenzhenhong_ed25519"
const fingerprint = "SHA256:fixture"
const profile = { version: 1 as const, release: "test", ssh_host: "150.109.115.216", ssh_port: 22 as const,
  ssh_user: "qc-chenzhenhong", remote_port: 49196, local_port: 48196, url: "http://127.0.0.1:48196",
  username: "quantcode" as const, password: "a".repeat(48) }
const session: QuantCodeIdentitySession = { status: "connected", actor_id: "chenzhenhong", session_id: "a".repeat(32),
  fingerprint, group: "model", groups: ["model", "factor"], expires_at: "2099-01-01T00:00:00Z", execution_status: "disconnected" }
function fixture() {
  const data = new Map<string, unknown>()
  const calls: string[] = []
  let current: QuantCodeIdentitySession | null = null
  const deps: NonNullable<Parameters<typeof createOrgLogin>[1]> = {
    disconnect: async () => { current = null; calls.push("logout"); return { status: "disconnected", execution_status: "disconnected" } },
    readAdminProfile: async () => profile,
    readServerAdminStatus: async () => "Linux 6.8\nup 3 days\nFilesystem 20% used",
    requireAdminSession: async () => {},
    importKey: async () => { calls.push("import"); return { fingerprint } },
    readOrgAccount: async (server, username) => {
      calls.push(`groups:${server.id}:${username}`)
      return { profile: { ...profile, ssh_user: username }, groups: ["model", "factor"] }
    },
    openResearchTunnel: async server => {
      calls.push(`tunnel:${server.id}`)
      return { connection: { url: `http://127.0.0.1:${48196 + "abc".indexOf(server.id.at(-1)!)}`,
        username: profile.username, password: profile.password, displayName: server.label }, alive: () => true,
        stop: () => { calls.push(`stop:${server.id}`) } }
    },
    inspect: async connection => {
      expect(Object.keys(connection).sort()).toEqual(["password", "url", "username"])
      return { identities: [{ id: fingerprint, fingerprint, label: "fixture", host: "fixture", user: "agent", group: "model", groups: ["model", "factor"] }], session: current }
    },
    connect: async (connection, _options, identityId, group) => {
      calls.push(`login:${connection.url}:${group}`)
      expect(identityId).toBe(fingerprint)
      return current = { ...session, group: group ?? "model" }
    },
  }
  const store = { get: (key: string) => data.get(key), set: (key: string, value: unknown) => { data.set(key, value) } }
  return { data, calls, deps, store, setSession: (value: QuantCodeIdentitySession | null) => { current = value } }
}

describe("organization SSH login", () => {
  test("cancelling a scan rejects late discovery without closing the active workspace", async () => {
    const f = fixture(), login = createOrgLogin(f.store, f.deps)
    await login.scan({ keyFile })
    const connected = await login.login({ serverId: "server-b", group: "model" })
    const entered = Promise.withResolvers<void>(), late = Promise.withResolvers<Awaited<ReturnType<typeof f.deps.readOrgAccount>>>()
    f.deps.readOrgAccount = async () => { entered.resolve(); return late.promise }
    const signal = new AbortController()
    const pending = login.scan({}, signal.signal).then(() => undefined, error => error)
    await entered.promise
    signal.abort()
    login.cancelAttempt()
    late.resolve({ profile, groups: ["model"] })
    expect(await pending).toBeDefined()
    expect(login.connection(connected.connection.url)?.url).toBe(connected.connection.url)
    expect(f.calls).not.toContain("stop:server-b")
    login.close()
  })
  test("server administrators bypass member profiles and receive separate management entries", async () => {
    const f = fixture()
    f.deps.readOrgAccount = async () => ({ administrator: true, groups: [], systemGroups: ["quantadmin", "quant-admin"] })
    f.deps.openResearchTunnel = async () => { throw new Error("administrator scan must not open a member host") }
    const login = createOrgLogin(f.store, f.deps)
    const scan = await login.scan({ keyFile, username: "quantadmin" })
    expect(scan.servers).toEqual([])
    expect(scan.administrators?.map(server => server.id)).toEqual(["server-a", "server-b", "server-c"])
    expect(scan.failed).toEqual([])
    login.close()
  })
  test("administrator login always signs the full identity, including the legacy operations entry", async () => {
    const f = fixture()
    f.deps.readOrgAccount = async () => ({ administrator: true, groups: [], systemGroups: ["quant-admin"] })
    let checked = 0
    f.deps.requireAdminSession = async () => { checked++ }
    const login = createOrgLogin(f.store, f.deps)
    await login.scan({ keyFile, username: "quantadmin" })
    const result = await login.login({ serverId: "server-c", administrator: "servers" })
    expect(result.mode).toBe("organization-admin")
    expect(result.session.session_id).toBeTruthy()
    expect(result.admin?.expires_at).toBe(result.session.expires_at)
    expect(f.calls.some(call => call.startsWith("login:"))).toBe(true)
    expect(checked).toBe(1)
    expect((await login.adminStatus({ serverId: "server-a" }))?.session.serverId).toBe("server-a")
    expect(checked).toBe(2)
    await login.adminDisconnect()
    expect(f.calls).toContain("logout")
    expect(await login.adminStatus()).toBeNull()
    login.close()
  })
  test("old operations-only records cannot restore a claimed administrator login", async () => {
    const f = fixture()
    f.data.set("lastMode", "server-admin")
    const login = createOrgLogin(f.store, f.deps)
    expect(await login.restore()).toEqual({ needsLogin: true })
    expect(await login.adminStatus()).toBeNull()
    login.close()
  })
  test("organization administration uses its dedicated profile and verified role", async () => {
    const f = fixture()
    f.deps.readOrgAccount = async () => ({ administrator: true, groups: [], systemGroups: ["quant-admin"] })
    let profiles = 0
    f.deps.readAdminProfile = async () => { profiles++; return profile }
    f.deps.requireAdminSession = async () => { throw new Error("not an organization admin") }
    const login = createOrgLogin(f.store, f.deps)
    await login.scan({ keyFile, username: "quantadmin" })
    expect(profiles).toBe(0)
    await expect(login.login({ serverId: "server-c", administrator: "organization" })).rejects.toThrow("not an organization admin")
    expect(f.data.get("lastLogin")).toBeUndefined()
    f.deps.requireAdminSession = async () => {}
    const result = await login.login({ serverId: "server-c", administrator: "organization" })
    expect(result.mode).toBe("organization-admin")
    expect(result.connection?.organizationAdmin).toBe(true)
    expect(profiles).toBe(2)
    login.close()
  })
  test("a member cannot promote itself by choosing the administrator entry", async () => {
    const f = fixture()
    const login = createOrgLogin(f.store, f.deps)
    await login.scan({ keyFile, username: "quantadmin" })
    await expect(login.login({ serverId: "server-c", administrator: "servers" })).rejects.toThrow("管理员私钥")
    expect(await login.adminStatus()).toBeNull()
    login.close()
  })
  test("revoked organization authority denies server operations too", async () => {
    const f = fixture()
    f.deps.readOrgAccount = async () => ({ administrator: true, groups: [], systemGroups: ["quant-admin"] })
    const login = createOrgLogin(f.store, f.deps)
    await login.scan({ keyFile, username: "quantadmin" })
    await login.login({ serverId: "server-c", administrator: "organization" })
    f.deps.requireAdminSession = async () => { throw new Error("admin session revoked") }
    await expect(login.adminStatus()).rejects.toThrow("admin session revoked")
    login.close()
  })
  test("key names preserve qc usernames; generic names prompt; shell-like usernames are rejected", () => {
    expect(usernameFromKeyFile(keyFile)).toBe("qc-chenzhenhong")
    expect(usernameFromKeyFile("C:\\Keys\\qc-chenzhenhong_ed25519.pem")).toBe("qc-chenzhenhong")
    for (const file of ["id_ed25519", "id_ed25519_github", "private.key", "qc-user_ed25519.pub"]) expect(usernameFromKeyFile(file)).toBeUndefined()
    expect(businessGroups("qc-user model factor model sudo\n")).toEqual(["model", "factor"])
    expect(() => sshArguments(keyFile, "-oProxyCommand=anything", "fixture")).toThrow("Linux 用户名")
  })
  test("connection profile rejects another member, non-loopback URL and invalid ports", () => {
    expect(parseResearchProfile(JSON.stringify(profile), profile.ssh_user)).toEqual(profile)
    for (const change of [{ ssh_user: "qc-other" }, { remote_port: 22 }, { url: "http://external.example" }]) {
      expect(() => parseResearchProfile(JSON.stringify({ ...profile, ...change }), profile.ssh_user)).toThrow("连接信息无效")
    }
  })
  test("scan imports first, visits A/B/C, and only selected host/group authenticates", async () => {
    const f = fixture()
    const login = createOrgLogin(f.store, f.deps)
    const scan = await login.scan({ keyFile })
    expect(scan.servers.map(server => server.id)).toEqual(["server-a", "server-b", "server-c"])
    expect(f.calls.filter(call => call.startsWith("groups:"))).toEqual([
      "groups:server-a:qc-chenzhenhong", "groups:server-b:qc-chenzhenhong", "groups:server-c:qc-chenzhenhong"])
    expect(f.calls[0]).toBe("import")
    expect(JSON.stringify(scan)).not.toContain(keyFile)
    expect(JSON.stringify(scan)).not.toContain(profile.password)
    const result = await login.login({ serverId: "server-b", group: "factor" })
    expect(result.connection.url).toBe("http://127.0.0.1:48197")
    expect(result.session.group).toBe("factor")
    expect(f.calls.filter(call => call.startsWith("login:"))).toEqual(["login:http://127.0.0.1:48197:factor"])
    expect(JSON.stringify(f.data.get("lastLogin"))).not.toContain(profile.password)
    login.close()
  })
  test("generic filename asks once and username correction survives reopening", async () => {
    const f = fixture()
    const login = createOrgLogin(f.store, f.deps)
    expect(await login.scan({ keyFile: "/fixture/id_ed25519" })).toMatchObject({ needsUsername: true })
    await login.scan({ username: "qc-chenzhenhong" })
    login.close()
    const next = createOrgLogin(f.store, f.deps)
    expect(await next.scan({ keyFile: "/fixture/id_ed25519" })).toMatchObject({ username: "qc-chenzhenhong" })
    next.close()
  })
  test("roster fills private-only Linux groups; unrelated Unix groups cannot grant access", async () => {
    const f = fixture()
    f.deps.readOrgAccount = async () => ({ profile, groups: ["risk"] })
    const login = createOrgLogin(f.store, f.deps)
    const scan = await login.scan({ keyFile })
    expect(scan.servers[0].groups).toEqual(["model", "factor"])
    expect((await login.login({ serverId: "server-c", group: "factor" })).session.group).toBe("factor")
    await expect(login.login({ serverId: "server-c", group: "risk" })).rejects.toThrow("已探测")
    login.close()
  })
  test("unenrolled host is skipped; an invented host/group cannot authenticate", async () => {
    const f = fixture()
    const read = f.deps.readOrgAccount
    f.deps.readOrgAccount = async (...args) => {
      if (args[0].id === "server-a") throw new Error("Permission denied (publickey)")
      return read(...args)
    }
    const login = createOrgLogin(f.store, f.deps)
    const scan = await login.scan({ keyFile })
    expect(scan.servers.map(server => server.id)).toEqual(["server-b", "server-c"])
    expect(scan.failed).toEqual([{ id: "server-a", reason: "这把密钥或用户名未登记" }])
    await expect(login.login({ serverId: "server-a", group: "model" })).rejects.toThrow("已探测")
    await expect(login.login({ serverId: "server-b", group: "risk" })).rejects.toThrow("已探测")
    expect(f.calls.some(call => call.startsWith("login:"))).toBe(false)
    login.close()
  })
  test("reopen restores an existing session; expiration never silently signs a new login", async () => {
    const f = fixture()
    const login = createOrgLogin(f.store, f.deps)
    await login.scan({ keyFile })
    await login.login({ serverId: "server-b", group: "factor" })
    login.close()
    f.calls.length = 0
    const next = createOrgLogin(f.store, f.deps)
    expect((await next.restore())?.session?.group).toBe("factor")
    expect(f.calls).toEqual(["groups:server-b:qc-chenzhenhong", "tunnel:server-b"])
    f.setSession(null)
    expect((await next.restore())?.session).toBeNull()
    expect(f.calls.some(call => call.startsWith("login:"))).toBe(false)
    f.setSession({ ...session, actor_id: "someone-else", group: "factor" })
    await expect(next.restore()).rejects.toThrow("登录身份已变化")
    next.close()
  })
})

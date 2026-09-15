import { app, BrowserWindow, dialog, ipcMain, shell } from "electron"
import type { IpcMainInvokeEvent, WebContentsDidStartNavigationEventParams } from "electron"
import type { ServerReadyData } from "../preload/types"
import { inspect, connect, disconnect, importKey, agentIdentities } from "./quantcode-identity"
import { openKeyTerminal } from './quantcode-key-terminal'
import { createHash } from 'node:crypto'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { resolveResearchConnection } from "./quantcode-connection"
import { createOrgLogin } from "./quantcode-org-login"
import { getStore } from "./store"
import { businessGroups } from "./quantcode-ssh-login"
import { sshAgent } from './quantcode-ssh-agent'

function requireDesktopFrame(event: IpcMainInvokeEvent) {
  const origin = new URL(event.senderFrame?.url ?? "")
  if (event.sender.isDestroyed() || event.senderFrame !== event.sender.mainFrame ||
      !(origin.protocol === "oc:" && origin.hostname === "renderer") &&
      !(!app.isPackaged && ["http:", "https:"].includes(origin.protocol) && ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))) {
    throw new Error("身份操作仅允许 QuantCode 桌面窗口。")
  }
}

function serverKey(input: unknown) {
  if (!input || typeof input !== "object" || !("server" in input) || typeof input.server !== "string" ||
      !input.server || input.server.length > 4096 || Object.keys(input).some(key => key !== "server" && key !== "identityId")) {
    throw new Error("请选择已保存的个人研究宿主。")
  }
  return input.server
}

function identityId(input: unknown) {
  if (!input || typeof input !== "object" || !("identityId" in input) || input.identityId === undefined) return undefined
  if (typeof input.identityId !== "string" || !input.identityId || input.identityId.length > 256) throw new Error("请选择已登记的 SSH 公钥身份。")
  return input.identityId
}

export function registerIdentityIpc(awaitInitialization: () => Promise<ServerReadyData>) {
  const active = new Map<number, { server: string; controller: AbortController; action: string }>()
  const orgLogins = new Map<number, ReturnType<typeof createOrgLogin>>()
  const resolveConnection = async (sender: number, server: string) => orgLogins.get(sender)?.connection(server) ?? resolveResearchConnection(server, awaitInitialization)
  const orgLogin = (event: IpcMainInvokeEvent) => {
    const cached = orgLogins.get(event.sender.id)
    if (cached) return cached
    const login = createOrgLogin(getStore("quantcode.identity.dat"), undefined, state => {
      if (!event.sender.isDestroyed()) event.sender.send("quantcode-ssh-connection-state", state)
    })
    const id = event.sender.id
    const close = () => {
      login.close()
      orgLogins.delete(id)
      event.sender.removeListener("did-start-navigation", navigation)
    }
    const navigation = (details: WebContentsDidStartNavigationEventParams) => {
      if (details.isMainFrame && !details.isSameDocument) close()
    }
    event.sender.once("destroyed", close)
    event.sender.once("render-process-gone", close)
    event.sender.on("did-start-navigation", navigation)
    orgLogins.set(id, login)
    return login
  }
  app.once("will-quit", () => { for (const login of orgLogins.values()) login.close() })
  app.once("will-quit", () => { for (const operation of active.values()) operation.controller.abort() })
  const pickKey = async (event: IpcMainInvokeEvent) => {
    const owner = BrowserWindow.fromWebContents(event.sender)
    if (!owner || owner.isDestroyed()) throw new Error("登录窗口已关闭，请重新打开 QuantCode。")
    owner.show()
    owner.focus()
    return dialog.showOpenDialog(owner, { properties: ["openFile"], title: "选择本地 SSH 私钥" })
  }
  ipcMain.handle("quantcode-ssh-login-cancel", (event: IpcMainInvokeEvent) => {
    requireDesktopFrame(event)
    const operation = active.get(event.sender.id)
    if (operation?.server !== "org" || operation.action === "select-key") return
    operation.controller.abort()
  })
  ipcMain.handle('quantcode-ssh-login-unlock-key', async (event: IpcMainInvokeEvent) => {
    requireDesktopFrame(event)
    await openKeyTerminal(orgLogin(event).selectedKey()).catch(() => { throw new Error('无法打开系统终端。请手动用 ssh-add 解锁所选私钥，然后重新探测。') })
  })
  ipcMain.handle('quantcode-ssh-login-agent-keys', async (event: IpcMainInvokeEvent) => {
    requireDesktopFrame(event)
    return (await agentIdentities()).map(key => ({ fingerprint: key.fingerprint, label: `已加载身份 · ${key.fingerprint}` }))
  })
  ipcMain.handle('quantcode-ssh-agent-status', async (event: IpcMainInvokeEvent) => {
    requireDesktopFrame(event)
    return sshAgent.status()
  })
  ipcMain.handle('quantcode-ssh-agent-start', async (event: IpcMainInvokeEvent) => {
    requireDesktopFrame(event)
    return sshAgent.start()
  })
  ipcMain.handle('quantcode-ssh-agent-settings', async (event: IpcMainInvokeEvent) => {
    requireDesktopFrame(event)
    if (process.platform !== 'win32') throw new Error('请在系统中安装 OpenSSH 客户端。')
    await shell.openExternal('ms-settings:optionalfeatures')
  })
  ipcMain.handle('quantcode-ssh-login-select-agent', async (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    if (!input || typeof input !== 'object' || !('fingerprint' in input) || typeof input.fingerprint !== 'string') throw new Error('请选择本机 SSH 身份。')
    const previous = active.get(event.sender.id)
    if (previous && ['inspect', 'restore'].includes(previous.action)) {
      previous.controller.abort()
      active.delete(event.sender.id)
    }
    if (active.has(event.sender.id)) throw new Error('身份操作正在进行，请稍候。')
    const identity = (await agentIdentities()).find(key => key.fingerprint === input.fingerprint)
    if (!identity) throw new Error('所选公钥不在本机 Agent 中，请刷新身份。')
    const directory = join(app.getPath('userData'), 'ssh-identities')
    await mkdir(directory, { recursive: true, mode: 0o700 })
    const file = join(directory, `${createHash('sha256').update(identity.fingerprint).digest('hex')}.pub`)
    await writeFile(file, identity.text + '\n', { mode: 0o600, flag: 'wx' }).catch(async error => {
      if (error.code !== 'EEXIST' || (await readFile(file, 'utf8')).trim() !== identity.text) throw new Error('无法保存本机公钥引用。')
    })
    requireDesktopFrame(event)
    orgLogin(event).selectKey(file)
  })
  ipcMain.handle("quantcode-ssh-connection-state", (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    return orgLogins.get(event.sender.id)?.connectionState(serverKey(input)) ?? null
  })
  ipcMain.handle("quantcode-ssh-reconnect", (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    const login = orgLogins.get(event.sender.id)
    if (!login) throw new Error("请先完成组织登录。")
    return login.reconnect(serverKey(input))
  })
  ipcMain.handle("quantcode-identity-cancel", (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    const server = serverKey(input)
    const operation = active.get(event.sender.id)
    if (operation?.server === server) operation.controller.abort()
  })
  const actions = { inspect, connect, disconnect }
  for (const action of ["inspect", "connect", "disconnect"] as const) {
    ipcMain.handle(`quantcode-identity-${action}`, async (event: IpcMainInvokeEvent, input: unknown) => {
      requireDesktopFrame(event)
      const server = serverKey(input)
      const sender = event.sender.id
      if (active.has(sender)) throw new Error("身份操作正在进行，请稍候。")
      const controller = new AbortController()
      const stop = () => controller.abort()
      const navigation = (details: WebContentsDidStartNavigationEventParams) => {
        if (details.isMainFrame && !details.isSameDocument) stop()
      }
      const frame = event.senderFrame
      active.set(sender, { server, controller, action })
      event.sender.once("destroyed", stop)
      event.sender.once("render-process-gone", stop)
      event.sender.on("did-start-navigation", navigation)
      try {
        const resolve = () => resolveConnection(sender, server)
        const connection = await resolve()
        const checkTarget = async () => {
          controller.signal.throwIfAborted()
          requireDesktopFrame(event)
          if (event.sender.mainFrame !== frame || JSON.stringify(await resolve()) !== JSON.stringify(connection)) {
            throw new Error("研究宿主连接已变化，请重新登录。")
          }
        }
        await checkTarget()
        const result = action === "connect"
          ? await actions[action](connection, { signal: controller.signal, checkTarget }, identityId(input))
          : await actions[action](connection, { signal: controller.signal, checkTarget })
        if (action === "disconnect") orgLogins.get(sender)?.released(server)
        return result
      } finally {
        event.sender.removeListener("destroyed", stop)
        event.sender.removeListener("render-process-gone", stop)
        event.sender.removeListener("did-start-navigation", navigation)
        controller.abort()
        if (active.get(sender)?.controller === controller) active.delete(sender)
      }
    })
  }
  ipcMain.handle("quantcode-identity-import-key", async (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    const server = serverKey(input)
    const connection = await resolveConnection(event.sender.id, server)
    const picked = await pickKey(event)
    if (picked.canceled || !picked.filePaths[0]) return null
    const file = picked.filePaths[0]
    const result = await importKey(connection, file)
    return result
  })
  for (const action of ["select-key", "scan", "connect", "restore", "progress", "admin-status", "admin-disconnect", 'resolve', 'exit-attempt', 'acknowledge'] as const) {
    ipcMain.handle(`quantcode-ssh-login-${action}`, async (event: IpcMainInvokeEvent, input: unknown) => {
      requireDesktopFrame(event)
      const sender = event.sender.id
      if (action === "progress") return orgLogin(event).progress()
      if (action === 'resolve' && !orgLogin(event).needsResolution()) return null
      if (action === "admin-status") {
        if (input !== undefined && (!input || typeof input !== "object" || !("serverId" in input) || typeof input.serverId !== "string" || Object.keys(input).some(key => key !== "serverId"))) throw new Error("服务器参数无效。")
        return orgLogin(event).adminStatus(input as { serverId?: string } | undefined)
      }
      if (action === 'acknowledge') {
        if (!input || typeof input !== 'object' || !('sessionId' in input) || typeof input.sessionId !== 'string') throw new Error('登录结果无效。')
        return orgLogin(event).acknowledge(input.sessionId)
      }
      const previous = active.get(sender)
      if (previous && ((action === 'resolve' || action === 'exit-attempt') && previous.action === 'inspect' ||
        (action === "select-key" || action === "scan") && ['inspect', 'restore'].includes(previous.action))) {
        previous.controller.abort()
        active.delete(sender)
      }
      if (active.has(sender)) throw new Error("身份操作正在进行，请稍候。")
      const controller = new AbortController()
      active.set(sender, { server: "org", controller, action })
      const frame = event.senderFrame
      const login = orgLogin(event)
      const cancel = () => {
        login.cancelAttempt()
        if (active.get(sender)?.controller === controller) active.delete(sender)
      }
      controller.signal.addEventListener("abort", cancel, { once: true })
      let deadline = action === "connect" || action === 'restore' ? setTimeout(() => controller.abort(), action === 'restore' ? 20000 : 90000) : undefined
      try {
        if (action === "select-key") {
          login.beginSelection()
          const picked = await pickKey(event)
          if (picked.canceled || !picked.filePaths[0]) return false
          requireDesktopFrame(event)
          if (event.sender.mainFrame !== frame) throw new Error("登录窗口已变化，请重试。")
          login.selectKey(picked.filePaths[0])
          return true
        }
        if (action === "admin-disconnect") return login.adminDisconnect()
        if (action === 'resolve') return await login.resolveLogin()
        if (action === 'exit-attempt') return await login.exitAttempt()
        if (action === "restore") return await login.restore(controller.signal).catch(() => ({ needsLogin: true as const }))
        if (action === "connect") {
          if (!input || typeof input !== "object" || !("serverId" in input) || typeof input.serverId !== "string") throw new Error("请选择登录入口。")
          if ("administrator" in input) {
            if (!["servers", "organization"].includes(String(input.administrator)) || Object.keys(input).some(key => key !== "serverId" && key !== "administrator")) throw new Error("管理员入口无效。")
            return await login.login({ serverId: input.serverId, administrator: input.administrator as "servers" | "organization" }, controller.signal)
          }
          if (!("group" in input) || typeof input.group !== "string" || Object.keys(input).some(key => key !== "serverId" && key !== "group")) throw new Error("请选择工作组。")
          const group = businessGroups(input.group)[0]
          if (!group || group !== input.group) throw new Error("工作组无效。")
          return await login.login({ serverId: input.serverId, group }, controller.signal)
        }
        if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).some(key => key !== "chooseKey" && key !== "username")) throw new Error("登录参数无效。")
        const selected = input as { chooseKey?: unknown; username?: unknown }
        if (selected.chooseKey !== undefined && typeof selected.chooseKey !== "boolean" ||
          selected.username !== undefined && (typeof selected.username !== "string" || selected.username.length > 64)) throw new Error("登录参数无效。")
        const username = typeof selected.username === "string" ? selected.username : undefined
        if (!selected.chooseKey) {
          deadline = setTimeout(() => controller.abort(), 90000)
          return await login.scan({ username }, controller.signal)
        }
        login.beginSelection()
        const picked = await pickKey(event)
        if (picked.canceled || !picked.filePaths[0]) return null
        requireDesktopFrame(event)
        if (event.sender.mainFrame !== frame) throw new Error("登录窗口已变化，请重试。")
        deadline = setTimeout(() => controller.abort(), 90000)
        return await login.scan({ keyFile: picked.filePaths[0], username }, controller.signal)
      } finally {
        if (deadline) clearTimeout(deadline)
        controller.signal.removeEventListener("abort", cancel)
        if (active.get(sender)?.controller === controller) active.delete(sender)
      }
    })
  }
  return resolveConnection
}

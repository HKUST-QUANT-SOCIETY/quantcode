import { app, dialog, ipcMain } from "electron"
import type { IpcMainInvokeEvent, WebContentsDidStartNavigationEventParams } from "electron"
import type { ServerReadyData } from "../preload/types"
import { inspect, connect, disconnect, importKey } from "./quantcode-identity"
import { resolveResearchConnection } from "./quantcode-connection"
import { createOrgLogin } from "./quantcode-org-login"
import { getStore } from "./store"
import { businessGroups } from "./quantcode-ssh-login"

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
  const active = new Map<number, { server: string; controller: AbortController }>()
  const orgLogins = new Map<number, ReturnType<typeof createOrgLogin>>()
  const orgLogin = (event: IpcMainInvokeEvent) => {
    const cached = orgLogins.get(event.sender.id)
    if (cached) return cached
    const login = createOrgLogin(getStore("quantcode.identity.dat"))
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
      active.set(sender, { server, controller })
      event.sender.once("destroyed", stop)
      event.sender.once("render-process-gone", stop)
      event.sender.on("did-start-navigation", navigation)
      try {
        const resolve = () => orgLogins.get(sender)?.connection(server) ?? resolveResearchConnection(server, awaitInitialization)
        const connection = await resolve()
        const checkTarget = async () => {
          controller.signal.throwIfAborted()
          requireDesktopFrame(event)
          if (event.sender.mainFrame !== frame || JSON.stringify(await resolve()) !== JSON.stringify(connection)) {
            throw new Error("研究宿主连接已变化，请重新登录。")
          }
        }
        await checkTarget()
        return action === "connect"
          ? await actions[action](connection, { signal: controller.signal, checkTarget }, identityId(input))
          : await actions[action](connection, { signal: controller.signal, checkTarget })
      } finally {
        event.sender.removeListener("destroyed", stop)
        event.sender.removeListener("render-process-gone", stop)
        event.sender.removeListener("did-start-navigation", navigation)
        controller.abort()
        active.delete(sender)
      }
    })
  }
  ipcMain.handle("quantcode-identity-import-key", async (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    const server = serverKey(input)
    const connection = await resolveResearchConnection(server, awaitInitialization)
    const picked = await dialog.showOpenDialog({ properties: ["openFile"], title: "导入 SSH 私钥到本机 Agent" })
    if (picked.canceled || !picked.filePaths[0]) return null
    const file = picked.filePaths[0]
    const result = await importKey(connection, file)
    return result
  })
  for (const action of ["scan", "connect", "restore", "admin-status", "admin-disconnect"] as const) {
    ipcMain.handle(`quantcode-ssh-login-${action}`, async (event: IpcMainInvokeEvent, input: unknown) => {
      requireDesktopFrame(event)
      const sender = event.sender.id
      if (action === "admin-status") return orgLogin(event).adminStatus()
      if (active.has(sender)) throw new Error("身份操作正在进行，请稍候。")
      const controller = new AbortController()
      active.set(sender, { server: "org", controller })
      const frame = event.senderFrame
      const login = orgLogin(event)
      const cancel = () => { login.close(); orgLogins.delete(sender) }
      controller.signal.addEventListener("abort", cancel, { once: true })
      try {
        if (action === "admin-disconnect") return login.adminDisconnect()
        if (action === "restore") return await login.restore().catch(() => ({ needsLogin: true as const }))
        if (action === "connect") {
          if (!input || typeof input !== "object" || !("serverId" in input) || typeof input.serverId !== "string") throw new Error("请选择登录入口。")
          if ("administrator" in input) {
            if (!["servers", "organization"].includes(String(input.administrator)) || Object.keys(input).some(key => key !== "serverId" && key !== "administrator")) throw new Error("管理员入口无效。")
            return await login.login({ serverId: input.serverId, administrator: input.administrator as "servers" | "organization" })
          }
          if (!("group" in input) || typeof input.group !== "string" || Object.keys(input).some(key => key !== "serverId" && key !== "group")) throw new Error("请选择工作组。")
          const group = businessGroups(input.group)[0]
          if (!group || group !== input.group) throw new Error("工作组无效。")
          return await login.login({ serverId: input.serverId, group })
        }
        if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).some(key => key !== "chooseKey" && key !== "username")) throw new Error("登录参数无效。")
        const selected = input as { chooseKey?: unknown; username?: unknown }
        if (selected.chooseKey !== undefined && typeof selected.chooseKey !== "boolean" ||
          selected.username !== undefined && (typeof selected.username !== "string" || selected.username.length > 64)) throw new Error("登录参数无效。")
        const username = typeof selected.username === "string" ? selected.username : undefined
        if (!selected.chooseKey) return await login.scan({ username })
        const picked = await dialog.showOpenDialog({ properties: ["openFile"], title: "选择本地 SSH 私钥" })
        if (picked.canceled || !picked.filePaths[0]) return null
        requireDesktopFrame(event)
        if (event.sender.mainFrame !== frame) throw new Error("登录窗口已变化，请重试。")
        return await login.scan({ keyFile: picked.filePaths[0], username })
      } finally {
        controller.signal.removeEventListener("abort", cancel)
        active.delete(sender)
      }
    })
  }
}

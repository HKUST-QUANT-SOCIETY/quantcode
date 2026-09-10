import { app, dialog, ipcMain } from "electron"
import type { IpcMainInvokeEvent, WebContentsDidStartNavigationEventParams } from "electron"
import type { ServerReadyData } from "../preload/types"
import { inspect, connect, disconnect, importKey } from "./quantcode-identity"
import { resolveResearchConnection } from "./quantcode-connection"
import { scanOrgServers, probeOrgServer } from "./quantcode-ssh-login"

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
        const connection = await resolveResearchConnection(server, awaitInitialization)
        const checkTarget = async () => {
          controller.signal.throwIfAborted()
          requireDesktopFrame(event)
          if (event.sender.mainFrame !== frame || JSON.stringify(await resolveResearchConnection(server, awaitInitialization)) !== JSON.stringify(connection)) {
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
  // 组织 SSH 登录向导：主进程弹系统选择器拿私钥绝对路径（Electron 42+ 渲染层
  // 拿不到 File.path）→ 三台内置服务器探测 → 返回 (组 × 服务器) 与后续探测所需路径
  ipcMain.handle("quantcode-ssh-login-scan", async (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    const record = (input && typeof input === "object" ? input : {}) as { keyFile?: unknown; username?: unknown }
    let keyFile = typeof record.keyFile === "string" ? record.keyFile : ""
    if (!keyFile) {
      const picked = await dialog.showOpenDialog({ properties: ["openFile"], title: "选择本地 SSH 私钥", filters: [{ name: "SSH 私钥", extensions: ["*"] }] })
      if (picked.canceled || !picked.filePaths[0]) return null
      keyFile = picked.filePaths[0]
    } else if (keyFile.length > 4096) {
      throw new Error("私钥路径无效。")
    }
    const username = typeof record.username === "string" && record.username.trim() ? record.username.trim() : undefined
    if (username !== undefined && username.length > 64) throw new Error("用户名无效。")
    const result = await scanOrgServers(keyFile, username)
    return { ...result, keyFile }
  })
  ipcMain.handle("quantcode-ssh-login-probe", async (event: IpcMainInvokeEvent, input: unknown) => {
    requireDesktopFrame(event)
    if (!input || typeof input !== "object") throw new Error("参数无效。")
    const record = input as { keyFile?: unknown; username?: unknown }
    if (typeof record.keyFile !== "string" || !record.keyFile) throw new Error("请选择本地私钥文件。")
    if (typeof record.username !== "string" || !record.username) throw new Error("请输入 SSH 用户名。")
    try {
      await probeOrgServer(record.keyFile, record.username)
      return { ok: true as const }
    } catch (error) {
      return { ok: false as const, reason: error instanceof Error ? error.message : String(error) }
    }
  })
}

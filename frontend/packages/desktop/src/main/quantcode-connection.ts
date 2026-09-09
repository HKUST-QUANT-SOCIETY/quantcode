import type { ServerReadyData } from "../preload/types"

export type ResearchConnection = { url: string; username?: string | null; password?: string | null }

/** Main-process credential bridges only address a saved research connection.
 * The renderer supplies a key, never a new URL, header, password or path. */
export async function resolveResearchConnection(server: string, awaitInitialization: () => Promise<ServerReadyData>): Promise<ResearchConnection> {
  if (server === "sidecar") {
    const local = await awaitInitialization()
    researchEndpoint(local, "")
    return local
  }
  const { getStore } = await import("./store")
  const raw = getStore("opencode.global.dat").get("server")
  const saved = typeof raw === "string" ? JSON.parse(raw) : raw
  const items = saved && typeof saved === "object" && "list" in saved && Array.isArray(saved.list) ? saved.list : []
  const found = items.find((item: unknown) => typeof item === "string" ? item === server : item && typeof item === "object" &&
    ("http" in item && item.http && typeof item.http === "object" && "url" in item.http ? item.http.url === server : "url" in item && item.url === server))
  if (!found) throw new Error("请先在 QuantCode 中保存并选择研究宿主连接。")
  const value = typeof found === "string" ? { url: found } : "http" in found ? found.http : found
  if (!value || typeof value.url !== "string" || (value.username !== undefined && typeof value.username !== "string") ||
    (value.password !== undefined && typeof value.password !== "string")) throw new Error("研究宿主连接配置无效。")
  researchEndpoint(value, "")
  return value
}

export function researchEndpoint(connection: ResearchConnection, fixedRoute: string) {
  const url = new URL(connection.url)
  if (url.username || url.password || url.search || url.hash || (url.protocol !== "https:" &&
    !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))) {
    throw new Error("凭据只能用于 HTTPS 或本机回环研究宿主。")
  }
  if (fixedRoute && (!fixedRoute.startsWith("/") || fixedRoute.startsWith("//") || fixedRoute.includes("?") || fixedRoute.includes("#"))) {
    throw new Error("研究宿主接口必须使用固定相对路径。")
  }
  return new URL(url.href.replace(/\/$/, "") + fixedRoute)
}

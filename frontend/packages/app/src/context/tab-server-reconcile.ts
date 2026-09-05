import { resolveServerKey, ServerConnection } from "./server"

type ServerTab = {
  server: ServerConnection.Key
}

export function reconcileTabServers<T extends ServerTab>(
  tabs: T[],
  connections: ServerConnection.Any[],
  key: (tab: T) => string,
) {
  const servers = new Set(connections.map(ServerConnection.key))
  const rekeyed = new Map<string, string>()
  const removed = new Set<string>()
  const next = tabs.flatMap((tab) => {
    const resolved = resolveServerKey(tab.server, connections)
    if (!servers.has(resolved)) {
      removed.add(key(tab))
      return []
    }
    if (resolved === tab.server) return [tab]
    const updated = { ...tab, server: resolved }
    rekeyed.set(key(tab), key(updated))
    return [updated]
  })
  return { tabs: next, rekeyed, removed }
}

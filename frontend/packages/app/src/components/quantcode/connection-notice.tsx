import { Show, createEffect, createMemo, onCleanup } from "solid-js"
import { useParams } from "@solidjs/router"
import { createStore } from "solid-js/store"
import { usePlatform } from "@/context/platform"
import { resolveServerKey, ServerConnection, useServer } from "@/context/server"
import { requireServerKey } from "@/utils/session-route"
import { useGlobal } from "@/context/global"
import type { QuantCodeConnectionState } from "@/identity"
import { Button } from "@opencode-ai/ui/button"

export function QuantCodeConnectionNotice() {
  const platform = usePlatform(), server = useServer(), global = useGlobal()
  const params = useParams<{ serverKey?: string }>()
  const target = createMemo(() => {
    const key = params.serverKey ? resolveServerKey(requireServerKey(params.serverKey), server.list) : server.key
    return server.list.find(conn => ServerConnection.key(conn) === key)
  })
  const [state, setState] = createStore({ connection: undefined as QuantCodeConnectionState | undefined, busy: false, error: "" })
  createEffect(() => {
    const conn = target(), key = conn ? String(ServerConnection.key(conn)) : "", url = conn?.http.url
    let live = true
    setState({ connection: undefined, error: "", busy: false })
    const update = (next: QuantCodeConnectionState | null) => {
      if (!live || !next || next.server !== key && next.url !== url) return
      const restored = state.connection && state.connection.state !== "connected" && next.state === "connected"
      setState({ connection: next, error: "" })
      if (restored && conn) void global.ensureServerCtx(conn).queryClient.invalidateQueries()
    }
    void platform.identity?.sshConnectionState?.({ server: key }).then(update).catch(() => {})
    const off = platform.identity?.onSshConnectionState?.(update)
    onCleanup(() => { live = false; off?.() })
  })
  const reconnect = async () => {
    const conn = target()
    if (state.busy || !conn) return
    const key = ServerConnection.key(conn)
    const current = () => !!target() && ServerConnection.key(target()!) === key
    setState({ busy: true, error: "" })
    try { await platform.identity?.sshReconnect?.({ server: key }) }
    catch (error) { if (current()) setState("error", error instanceof Error ? error.message : "连接尚未恢复，请重试。") }
    finally { if (current()) setState("busy", false) }
  }
  return <Show when={state.connection && state.connection.state !== "connected"}>
    <div role="status" class="flex shrink-0 items-center gap-3 border-b border-border-weak-base px-4 py-2 text-sm">
      <span class="flex-1">{state.error || state.connection?.reason || "正在恢复工作连接，原任务和工作目录已保留。"}</span>
      <Button size="small" disabled={state.busy} onClick={reconnect}>{state.busy ? "正在重连…" : "重新连接"}</Button>
    </div>
  </Show>
}

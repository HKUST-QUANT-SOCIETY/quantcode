import { Show, createEffect, onCleanup, untrack } from "solid-js"
import { createStore } from "solid-js/store"
import { useServerSDK } from "@/context/server-sdk"
import { usePlatform } from "@/context/platform"
import { ServerConnection } from "@/context/server"

export function GitHubConnection(props: { onConnected: () => void }) {
  const sdk = useServerSDK()
  const platform = usePlatform()
  const [state, setState] = createStore({ status: "idle", subject: "", code: "", url: "", error: "", busy: false })
  let live = true
  let generation = 0
  const selected = () => ServerConnection.key(sdk().server)
  const host = () => { try { return new URL(sdk().server.http.url).host } catch { return "当前研究宿主" } }
  onCleanup(() => { live = false; void platform.github?.request({ server: selected(), mode: "cancel" }) })
  async function request(mode?: "local" | "browser" | "cancel") {
    if (state.busy) return
    const revision = generation
    const server = selected()
    setState({ busy: true, error: "" })
    try {
      const wasAuthorizing = state.status === "authorizing"
      const response = platform.github
        ? { data: await platform.github.request({ server, mode }), error: undefined }
        : await (mode ? sdk().client.quantcode.github.connect({ mode }) : sdk().client.quantcode.github.status())
      const result = response.data as { status?: string; subject?: string; code?: string; url?: string; error?: string } | undefined
      if (!live || revision !== generation || selected() !== server) return
      if (response.error || !result) throw new Error("GitHub 连接服务不可用，请检查当前服务版本。")
      setState({ status: result.status ?? "error", subject: result.subject ?? "", code: result.code ?? "", url: result.url ?? "", error: result.error ?? "" })
      if (result.status === "connected" && (mode !== undefined || wasAuthorizing)) props.onConnected()
    } catch (error) { if (live && revision === generation) setState({ status: "error", error: error instanceof Error ? error.message : "GitHub 连接失败" }) }
    finally { if (live && revision === generation) setState("busy", false) }
  }
  createEffect(() => {
    const server = selected()
    generation++
    setState({ status: "idle", subject: "", code: "", error: "", busy: false })
    untrack(() => void request())
    onCleanup(() => { generation++; void platform.github?.request({ server, mode: "cancel" }) })
  })
  createEffect(() => {
    if (state.status !== "authorizing") return
    const timer = setInterval(() => void request(), 2000)
    onCleanup(() => clearInterval(timer))
  })
  return <div class="qc-github-connection">
    <p>选择一种方式连接 GitHub。请使用组织名册绑定的账号，仓库范围仍按当前身份核验。</p>
    <p>连接到研究宿主：<strong>{host()}</strong>。{platform.github ? "所选 GitHub 凭据将由此电脑安全传给该宿主，用于读取授权仓库。" : "浏览器授权保存在该研究宿主；使用此电脑已有凭据请打开 QuantCode 桌面端。"}</p>
    <div class="qc-gate-actions">
      <button type="button" class="qc-button qc-button-primary" disabled={state.busy || state.status === "authorizing"} onClick={() => void request("browser")}>通过 GitHub 登录</button>
      <button type="button" class="qc-button qc-button-secondary" disabled={!platform.github || state.busy || state.status === "authorizing"} onClick={() => void request("local")}>使用本机凭据</button>
    </div>
    <Show when={state.status === "authorizing"}>
      <p role="status">{state.code ? "在 GitHub 授权页输入以下一次性代码：" : "正在向 GitHub 请求授权…"}</p>
      <Show when={state.code}><code class="qc-artifact">{state.code}</code><button type="button" class="qc-button qc-button-primary" onClick={() => platform.openLink("https://github.com/login/device")}>打开 GitHub 授权页</button></Show>
      <button type="button" class="qc-button qc-button-secondary" onClick={() => void request("cancel")}>取消授权</button>
    </Show>
    <Show when={state.status === "connected"}><p role="status">已连接 {state.subject}</p><button type="button" class="qc-button qc-button-secondary" onClick={props.onConnected}>刷新 GitGraph</button></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
  </div>
}

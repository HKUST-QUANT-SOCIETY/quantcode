import { For, Show, createEffect, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import type { OpencodeClient } from "@opencode-ai/sdk/v2"
import { userFacingServiceError } from "./workspace-ui"

type Record = { deployment_id: string; actor_id: string; status: string; created_at: string; payload: { artifact_ref: string; target: string; manifest: unknown } }
export function DeploymentPanel(props: { scope: string; client: OpencodeClient }) {
  const [state, setState] = createStore({ records: [] as Record[], artifact: "", target: "", version: "", busy: false, error: "", message: "" })
  let revision = 0
  onCleanup(() => revision++)
  async function load() {
    const current = ++revision
    setState({ busy: true, error: "" })
    try {
      const response = await props.client.quantcode.deployment.list()
      if (current !== revision) return
      const data = response.data
      if (response.error || !data || typeof data !== "object" || !("deployments" in data) || !Array.isArray(data.deployments)) throw new Error(data && typeof data === "object" && "error" in data ? String(data.error) : "部署管理服务不可用")
      setState({ records: data.deployments as Record[], message: "executor_message" in data ? String(data.executor_message) : "" })
    } catch (error) { if (current === revision) setState("error", userFacingServiceError(error, "部署管理通道暂不可用。")) }
    finally { if (current === revision) setState("busy", false) }
  }
  async function submit(cancel?: string) {
    const current = revision
    setState({ busy: true, error: "" })
    try {
      const response = cancel
        ? await props.client.quantcode.deployment.cancel({ deployment_id: cancel })
        : await props.client.quantcode.deployment.submit({ artifact_ref: state.artifact.trim(), target: state.target.trim(), manifest: { version: state.version.trim() } })
      if (current !== revision) return
      if (response.error || !response.data || (typeof response.data === "object" && "error" in response.data)) throw new Error("部署请求失败，未确认成功。请刷新记录后重试。")
      await load()
    } catch (error) { if (current === revision) setState("error", error instanceof Error ? error.message : "操作失败") }
    finally { if (current === revision) setState("busy", false) }
  }
  createEffect(() => { props.scope; revision++; setState({ records: [], artifact: "", target: "", version: "", error: "", message: "" }); void load() })
  return <section class="qc-detail-body qc-deployment" aria-label="Admin 部署管理">
    <div class="qc-view-toolbar"><div><h3>部署管理</h3><p>提交已调试产物的引用和版本。暂存不表示已经部署到生产。</p></div></div>
    <Show when={state.message}><p role="status">{state.message}</p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <div class="qc-deployment-form">
      <label>产物引用<input aria-label="产物引用" value={state.artifact} onInput={event => setState("artifact", event.currentTarget.value)} /></label>
      <label>目标环境<input aria-label="目标环境" value={state.target} onInput={event => setState("target", event.currentTarget.value)} /></label>
      <label>版本<input aria-label="版本" value={state.version} onInput={event => setState("version", event.currentTarget.value)} /></label>
      <div class="qc-deployment-actions"><button type="button" class="qc-button qc-button-primary" disabled={state.busy || !state.artifact.trim() || !state.target.trim() || !state.version.trim()} onClick={() => void submit()}>暂存部署请求</button><button type="button" class="qc-button qc-button-secondary" disabled={state.busy} onClick={() => void load()}>刷新记录</button></div>
    </div>
    <For each={state.records}>{record => <article class="qc-detail-section"><h4>{record.payload.artifact_ref}</h4><p>{record.payload.target} · {record.status} · {record.actor_id} · {record.created_at}</p><pre>{JSON.stringify(record.payload.manifest)}</pre><Show when={record.status === "STAGING"}><button type="button" disabled={state.busy} onClick={() => void submit(record.deployment_id)}>取消暂存请求</button></Show></article>}</For>
  </section>
}

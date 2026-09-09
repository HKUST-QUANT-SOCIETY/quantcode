import { For, Show, createEffect, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import type { QuantCodeArtifact, QuantCodeArtifactList, QuantCodeArtifactRead, QuantCodeTaskSummary } from "@opencode-ai/sdk/v2"
import { Icon } from "@opencode-ai/ui/icon"

export type NativeArtifactSource = {
  list: (task: QuantCodeTaskSummary, cursor: string | undefined, signal: AbortSignal) => Promise<QuantCodeArtifactList>
  read: (task: QuantCodeTaskSummary, artifact: QuantCodeArtifact, offset: number, signal: AbortSignal) => Promise<QuantCodeArtifactRead>
}

const digest = async (bytes: Uint8Array<ArrayBuffer>) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
  .map(byte => byte.toString(16).padStart(2, "0")).join("")
const key = (task: QuantCodeTaskSummary) => JSON.stringify([task.source_id, task.session_id, task.source_revision])
const status = { available: "可查看", pending: "正在同步", unavailable: "原始内容未保存" }

/** Existing task projection endpoints provide immutable references and chunks.
 * Downloads never dereference a report URL or a member's filesystem path. */
export function NativeArtifacts(props: { task: QuantCodeTaskSummary; source: NativeArtifactSource }) {
  const [state, setState] = createStore({ items: [] as QuantCodeArtifact[], cursor: undefined as string | undefined,
    loading: false, error: "", downloading: "", bytes: 0, complete: false,
    file: undefined as { id: string; name: string; url: string; text?: string } | undefined })
  let load = async (_more = false) => {}
  let read = async (_artifact: QuantCodeArtifact) => {}
  let cancel = () => {}
  createEffect(on(() => [key(props.task), props.source] as const, () => {
    const task = props.task
    const source = props.source
    const lifetime = new AbortController()
    let download: AbortController | undefined
    let objectURL: string | undefined
    let boundary: string | undefined
    setState({ items: [], cursor: undefined, loading: false, error: "", downloading: "", bytes: 0, file: undefined, complete: false })
    const clearFile = () => { if (objectURL) URL.revokeObjectURL(objectURL); objectURL = undefined; setState("file", undefined) }
    load = async (more = false) => {
      if (state.loading || lifetime.signal.aborted) return
      setState({ loading: true, error: "" })
      try {
        const items = more ? [...state.items] : []
        let cursor = more ? state.cursor : undefined
        let complete = false
        const seen = new Set<string>()
        while (true) {
          const page = await source.list(task, cursor, lifetime.signal)
          if (lifetime.signal.aborted) return
          if (page.source_revision !== task.source_revision || page.artifact_manifest_hash !== task.artifact_manifest_hash) throw new Error("任务版本已变化，请刷新任务详情。")
          items.push(...page.artifacts)
          cursor = page.next_cursor ?? undefined
          complete = page.manifest_complete
          if (more || !cursor || !boundary || page.artifacts.some(item => item.id === boundary)) break
          if (seen.has(cursor)) throw new Error("产物分页没有继续，请刷新任务详情。")
          seen.add(cursor)
        }
        const unique = [...new Map(items.map(item => [item.id, item])).values()]
        boundary = unique.at(-1)?.id
        setState({ items: unique, cursor, complete })
      } catch (error) {
        if (!lifetime.signal.aborted) {
          download?.abort()
          clearFile()
          setState({ items: [], cursor: undefined, complete: false,
            error: error instanceof Error ? error.message : "产物列表读取失败。" })
        }
      } finally { if (!lifetime.signal.aborted) setState("loading", false) }
    }
    cancel = () => download?.abort()
    read = async (artifact) => {
      if (state.downloading || artifact.delivery_status !== "available" || artifact.bytes === undefined || !artifact.sha256) return
      clearFile()
      const controller = new AbortController()
      download = controller
      const signal = AbortSignal.any([lifetime.signal, controller.signal])
      setState({ downloading: artifact.id, error: "", bytes: 0 })
      try {
        const chunks: Uint8Array<ArrayBuffer>[] = []
        let offset = 0
        while (true) {
          const chunk = await source.read(task, artifact, offset, signal)
          signal.throwIfAborted()
          if (chunk.source_revision !== task.source_revision || chunk.artifact.delivery_status !== "available" || chunk.artifact.id !== artifact.id ||
              chunk.artifact.sha256 !== artifact.sha256 || chunk.artifact.bytes !== artifact.bytes ||
              chunk.offset !== offset || chunk.content === undefined || chunk.encoding !== "base64") throw new Error("产物内容版本不一致，请重新读取。")
          const bytes = Uint8Array.from(atob(chunk.content), char => char.charCodeAt(0))
          if (bytes.length > 65536 || await digest(bytes) !== chunk.chunk_sha256) throw new Error("产物传输校验失败。")
          chunks.push(bytes)
          offset += bytes.length
          if (offset > artifact.bytes || chunk.next_offset !== null && chunk.next_offset !== offset) throw new Error("产物分页长度不一致。")
          setState("bytes", offset)
          if (chunk.next_offset === null) break
          if (!bytes.length) throw new Error("产物传输没有继续，请重试。")
        }
        if (offset !== artifact.bytes) throw new Error("产物尚未完整传输。")
        const blob = new Blob(chunks, { type: "application/octet-stream" })
        const bytes = new Uint8Array(await blob.arrayBuffer())
        if (await digest(bytes) !== artifact.sha256) throw new Error("完整产物校验失败，未生成下载文件。")
        signal.throwIfAborted()
        const text = bytes.length <= 1024 * 1024 && /^(text\/(plain|markdown|csv)|application\/json)(;|$)/i.test(artifact.mime)
          ? new TextDecoder().decode(bytes) : undefined
        objectURL = URL.createObjectURL(blob)
        setState("file", { id: artifact.id, name: artifact.name ?? artifact.id, url: objectURL, text })
      } catch (error) {
        if (!lifetime.signal.aborted) setState("error", controller.signal.aborted ? "已取消产物读取。" : error instanceof Error ? error.message : "产物读取失败。")
      } finally { if (!lifetime.signal.aborted) setState("downloading", "") }
    }
    void load()
    const refresh = setInterval(() => {
      if (!state.loading && (!state.complete || state.items.some(item => item.delivery_status === "pending") || state.file)) void load()
    }, 10000)
    onCleanup(() => { clearInterval(refresh); lifetime.abort(); download?.abort(); if (objectURL) URL.revokeObjectURL(objectURL) })
  }))
  return <section aria-label="任务产物">
    <div class="qc-view-toolbar"><h4>报告与产物</h4><button type="button" class="qc-button" disabled={state.loading} onClick={() => void load()}>刷新产物</button></div>
    <Show when={state.loading}><p role="status">正在读取产物…</p></Show>
    <Show when={!state.loading && !state.complete && !state.error}><p class="qc-muted">产物清单正在同步，完整校验后可下载。</p></Show>
    <Show when={state.error}><p role="alert">{state.error}</p></Show>
    <For each={state.items}>{artifact => <article class="qc-native-artifact">
      <Icon name="folder" size="small" /><div><strong>{artifact.name ?? artifact.id}</strong><small>{artifact.mime} · {artifact.bytes === undefined ? "大小未知" : `${artifact.bytes.toLocaleString()} 字节`} · {status[artifact.delivery_status]}</small>
        <Show when={artifact.unavailable_reason}><p class="qc-muted">这次调用没有保存可验证的原始产物内容。</p></Show>
        <Show when={artifact.delivery_status === "available"}><button type="button" class="qc-button" disabled={!!state.downloading} onClick={() => void read(artifact)}>读取产物</button></Show>
        <Show when={state.downloading === artifact.id}><p role="status">已读取 {state.bytes.toLocaleString()} 字节 <button type="button" onClick={() => cancel()}>取消</button></p></Show>
        <Show when={state.file?.id === artifact.id && state.file}>{file => <><a href={file().url} download={file().name}>下载完整文件</a><Show when={file().text !== undefined}><pre class="qc-native-text">{file().text}</pre></Show></>}</Show>
      </div>
    </article>}</For>
    <Show when={state.cursor}><button type="button" class="qc-button" disabled={state.loading} onClick={() => void load(true)}>加载更多产物</button></Show>
    <Show when={!state.loading && state.complete && !state.items.length && !state.error}><p class="qc-muted">没有产物记录。</p></Show>
  </section>
}

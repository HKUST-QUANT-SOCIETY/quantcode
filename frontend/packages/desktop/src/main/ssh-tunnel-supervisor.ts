import type { ChildProcess } from "node:child_process"

export type SshTransportState = { state: "connecting" | "connected" | "reconnecting" | "offline" | "closed"; generation: number; reason?: string }

/** One owner and one fixed endpoint for the lifetime of an SSH connection.
 * Reconnecting transport never replays HTTP requests or signs a new login. */
export function superviseSshTunnel(input: {
  launch: () => ChildProcess
  probe: () => Promise<boolean>
  forwardingReady?: (stderr: string) => boolean
  signal?: AbortSignal
  retryDelayMs?: number
  connectTimeoutMs?: number
}) {
  let state: SshTransportState = { state: "connecting", generation: 0 }
  let child: ChildProcess | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempts = 0
  let stopped = false
  let epoch = 0
  const listeners = new Set<(state: SshTransportState) => void>()
  const publish = (next: SshTransportState) => { state = next; for (const listener of listeners) listener(next) }
  const alive = () => state.state === "connected" && !!child && !child.killed && child.exitCode === null && child.signalCode === null
  const stop = () => {
    if (stopped) return
    stopped = true
    epoch++
    if (timer) clearTimeout(timer)
    child?.kill()
    child = undefined
    input.signal?.removeEventListener("abort", stop)
    publish({ state: "closed", generation: state.generation })
    listeners.clear()
  }
  const connect = () => {
    if (stopped) return
    if (timer) clearTimeout(timer)
    const attempt = ++epoch
    publish({ state: state.generation ? "reconnecting" : "connecting", generation: state.generation })
    let stderr = ""
    let forwardingReady = !input.forwardingReady
    let process: ChildProcess
    const failed = (reason?: string) => {
      if (stopped || attempt !== epoch) return
      epoch++
      process?.kill()
      child = undefined
      const fatal = /Permission denied|No more authentication methods|Host key verification|REMOTE HOST IDENTIFICATION/i.test(stderr)
      const message = fatal ? "SSH 身份或服务器指纹需要重新核验，请重新登录。" : reason ?? "连接中断，正在自动恢复。"
      publish({ state: fatal ? "offline" : "reconnecting", generation: state.generation, reason: message })
      if (!fatal) timer = setTimeout(connect, Math.min(30_000, (input.retryDelayMs ?? 1000) * 2 ** Math.min(attempts++, 5)))
    }
    try { process = input.launch(); child = process } catch { failed("无法启动本机 SSH，请检查系统 SSH 安装。"); return }
    process.stderr?.on("data", data => {
      stderr = (stderr + String(data)).slice(-2048)
      if (input.forwardingReady?.(stderr)) forwardingReady = true
    })
    process.once("error", () => failed("本机 SSH 进程启动失败，正在重试。"))
    process.once("exit", (code, signal) => failed(`SSH 连接已退出（${signal ?? code ?? "unknown"}），正在自动恢复。`))
    const deadline = Date.now() + (input.connectTimeoutMs ?? 12000)
    const probe = async () => {
      if (stopped || attempt !== epoch) return
      const connected = forwardingReady && await input.probe().catch(() => false)
      if (stopped || attempt !== epoch) return
      if (connected && !process.killed && process.exitCode === null && process.signalCode === null) {
        attempts = 0
        publish({ state: "connected", generation: state.generation + 1 })
        return
      }
      if (Date.now() >= deadline) { failed("SSH 连接建立超时，正在重试。"); return }
      timer = setTimeout(() => void probe(), 100)
    }
    void probe()
  }
  const ensureConnected = (timeoutMs = 12000) => {
    if (alive()) return Promise.resolve()
    if (stopped || state.state === "offline") return Promise.reject(new Error(state.reason ?? "SSH 连接已关闭。"))
    return new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => { clearTimeout(deadline); listeners.delete(changed); error ? reject(error) : resolve() }
      const changed = (value: SshTransportState) => {
        if (value.state === "connected") finish()
        if (value.state === "closed" || value.state === "offline") finish(new Error(value.reason ?? "SSH 连接已关闭。"))
      }
      const deadline = setTimeout(() => finish(new Error("连接仍在恢复中，请稍后重试。")), timeoutMs)
      listeners.add(changed)
    })
  }
  input.signal?.addEventListener("abort", stop, { once: true })
  if (input.signal?.aborted) stop()
  else connect()
  return {
    alive, stop, ensureConnected, status: () => ({ ...state }),
    subscribe(listener: (state: SshTransportState) => void) { listeners.add(listener); listener(state); return () => { listeners.delete(listener) } },
    reconnect() {
      if (stopped) return Promise.reject(new Error("SSH 连接已关闭，请重新登录。"))
      epoch++
      child?.kill()
      attempts = 0
      connect()
      return ensureConnected()
    },
  }
}

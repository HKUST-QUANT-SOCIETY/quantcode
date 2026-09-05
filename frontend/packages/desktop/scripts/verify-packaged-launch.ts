#!/usr/bin/env bun

type DevToolsTarget = {
  type?: string
  title?: string
  url?: string
  webSocketDebuggerUrl?: string
}

type EvaluationResponse = {
  id?: number
  error?: { message?: string }
  result?: {
    exceptionDetails?: { text?: string }
    result?: { value?: unknown }
  }
}

type RendererState = {
  readyState?: string
  rootChildren?: number
  bodyText?: string
  userAgent?: string
  icon?: string
  product?: string
  fatalError?: boolean
  interactiveControls?: number
  quantcodeWorkspace?: boolean
  sidecarUrl?: string
  sidecarHealthy?: boolean
  error?: string
}

const rawEndpoint = process.env.QUANTCODE_SMOKE_DEBUG_URL
if (!rawEndpoint) throw new Error("QUANTCODE_SMOKE_DEBUG_URL is required")

const endpoint = new URL(rawEndpoint)
if (endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1" || endpoint.pathname !== "/json/list") {
  throw new Error("QUANTCODE_SMOKE_DEBUG_URL must be a loopback http://127.0.0.1:<port>/json/list URL")
}
if (!endpoint.port || Number(endpoint.port) < 1 || Number(endpoint.port) > 65_535) {
  throw new Error("QUANTCODE_SMOKE_DEBUG_URL must include a valid port")
}

const pid = Number(process.env.QUANTCODE_SMOKE_PID)
if (!Number.isSafeInteger(pid) || pid < 1) throw new Error("QUANTCODE_SMOKE_PID must be a running process ID")

const timeoutMs = Number(process.env.QUANTCODE_SMOKE_TIMEOUT_MS ?? 60_000)
if (!Number.isFinite(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 120_000) {
  throw new Error("QUANTCODE_SMOKE_TIMEOUT_MS must be between 1000 and 120000")
}

const deadline = Date.now() + timeoutMs

function remaining(limit = 5_000) {
  const value = Math.min(limit, deadline - Date.now())
  if (value <= 0) throw new Error("packaged launch deadline expired")
  return value
}

function requireProcessAlive() {
  try {
    process.kill(pid, 0)
  } catch {
    throw new Error(`packaged QuantCode process ${pid} exited before verification completed`)
  }
}

async function readJson(url: URL, label: string) {
  const response = await fetch(url, { signal: AbortSignal.timeout(remaining()) })
  if (!response.ok) throw new Error(`${label} returned ${response.status}`)
  return response.json() as Promise<unknown>
}

async function readTargets() {
  const value = await readJson(endpoint, "DevTools endpoint")
  return Array.isArray(value) ? (value as DevToolsTarget[]) : []
}

async function evaluate(target: DevToolsTarget) {
  if (!target.webSocketDebuggerUrl) throw new Error("renderer target has no debugger URL")

  const debuggerUrl = new URL(target.webSocketDebuggerUrl)
  if (debuggerUrl.protocol !== "ws:" || debuggerUrl.hostname !== "127.0.0.1" || debuggerUrl.port !== endpoint.port) {
    throw new Error(`renderer debugger is not bound to the expected loopback endpoint: ${debuggerUrl}`)
  }

  const socket = new WebSocket(debuggerUrl)
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("renderer debugger connection timed out")), remaining())
    socket.addEventListener(
      "open",
      () => {
        clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
    socket.addEventListener(
      "error",
      () => {
        clearTimeout(timer)
        reject(new Error("failed to connect to renderer debugger"))
      },
      { once: true },
    )
  })

  try {
    const id = 1
    const response = await new Promise<EvaluationResponse>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("renderer evaluation timed out")), remaining(10_000))
      socket.addEventListener("message", (event) => {
        const value = JSON.parse(String(event.data)) as EvaluationResponse
        if (value.id !== id) return
        clearTimeout(timer)
        resolve(value)
      })
      socket.send(
        JSON.stringify({
          id,
          method: "Runtime.evaluate",
          params: {
            expression: `
              (async () => {
                try {
                  if (!window.api || typeof window.api.awaitInitialization !== "function") {
                    return { error: "QuantCode preload API is unavailable" }
                  }
                  const sidecar = await window.api.awaitInitialization()
                  const headers = new Headers()
                  if (sidecar.password) {
                    headers.set("authorization", "Basic " + btoa((sidecar.username || "opencode") + ":" + sidecar.password))
                  }
                  const health = await fetch(new URL("/global/health", sidecar.url), {
                    headers,
                    cache: "no-store",
                    signal: AbortSignal.timeout(3000),
                  })
                  return {
                    readyState: document.readyState,
                    rootChildren: document.querySelector("#root")?.children.length ?? 0,
                    bodyText: document.body?.innerText?.slice(0, 2000) ?? "",
                    userAgent: navigator.userAgent,
                    icon: document.querySelector('link[rel="icon"]')?.href ?? "",
                    product: document.body?.dataset.product,
                    quantcodeWorkspace: Boolean(document.querySelector('[data-quantcode-workspace="true"]')),
                    fatalError: Boolean(document.querySelector('[data-page="error"]')),
                    interactiveControls: document.querySelectorAll("button, a[href], input, textarea, select").length,
                    sidecarUrl: sidecar.url,
                    sidecarHealthy: health.ok,
                  }
                } catch (error) {
                  return { error: error instanceof Error ? error.message : String(error) }
                }
              })()
            `,
            awaitPromise: true,
            returnByValue: true,
          },
        }),
      )
    })

    if (response.error?.message) throw new Error(`renderer debugger error: ${response.error.message}`)
    if (response.result?.exceptionDetails) {
      throw new Error(`renderer evaluation failed: ${response.result.exceptionDetails.text ?? "unknown error"}`)
    }
    const value = response.result?.result?.value
    if (!value || typeof value !== "object") throw new Error("renderer returned no evaluation result")
    return value as RendererState
  } finally {
    socket.close()
  }
}

function validateState(target: DevToolsTarget, state: RendererState) {
  if (target.title !== "QuantCode") return `unexpected renderer title: ${target.title ?? "<empty>"}`
  if (state.error) return `renderer initialization failed: ${state.error}`
  if (state.readyState !== "complete" || (state.rootChildren ?? 0) < 1) {
    return `renderer DOM not ready: ${JSON.stringify(state)}`
  }
  if (!state.userAgent?.includes("Electron/")) return `renderer is not Electron: ${state.userAgent ?? "<empty>"}`
  if (!state.icon?.endsWith("/quantcode-icon.png")) return `unexpected product icon: ${state.icon ?? "<empty>"}`
  if (state.product !== "quantcode") return `unexpected product marker: ${state.product ?? "<missing>"}`
  if (!state.quantcodeWorkspace) return "renderer did not mount the QuantCode research workspace"
  if (state.fatalError) return `renderer reached the fatal error page: ${state.bodyText ?? ""}`
  if ((state.interactiveControls ?? 0) < 1) return "renderer has not reached an interactive application surface"
  if (!state.sidecarHealthy) return `sidecar health check failed: ${state.sidecarUrl ?? "<missing URL>"}`
}

let lastError = "no renderer target"
let firstPassAt = 0
while (Date.now() < deadline) {
  try {
    requireProcessAlive()
    const targets = await readTargets()
    const target = targets.find((item) => item.type === "page" && item.url?.startsWith("oc://renderer/"))
    if (!target) {
      lastError = `renderer target not ready (targets=${targets.map((item) => `${item.type ?? "?"}:${item.url ?? "?"}`).join(",")})`
      firstPassAt = 0
    } else {
      const state = await evaluate(target)
      lastError = validateState(target, state) ?? ""
      if (lastError) {
        firstPassAt = 0
      } else if (!firstPassAt) {
        firstPassAt = Date.now()
      } else if (Date.now() - firstPassAt >= 2_000) {
        requireProcessAlive()
        console.log(
          JSON.stringify({
            ok: true,
            pid,
            title: target.title,
            url: target.url,
            sidecarUrl: state.sidecarUrl,
            stableForMs: Date.now() - firstPassAt,
          }),
        )
        process.exit(0)
      }
    }
  } catch (error) {
    lastError = error instanceof Error ? error.message : String(error)
    firstPassAt = 0
  }

  await Bun.sleep(Math.min(500, Math.max(0, deadline - Date.now())))
}

throw new Error(`QuantCode packaged launch smoke test timed out: ${lastError}`)

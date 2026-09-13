/** A failed authority read must not remove the next opportunity to revalidate. */
export function monitorIdentity<T>(input: {
  read: (signal: AbortSignal) => Promise<T>
  ready: (value: T) => void
  unavailable: () => void
  intervalMs?: number
}) {
  let active: AbortController | undefined
  let disposed = false
  let queued = false
  const refresh = async () => {
    if (disposed) return
    if (active) { queued = true; return }
    const controller = new AbortController()
    active = controller
    try {
      const value = await input.read(AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]))
      if (!disposed && !controller.signal.aborted) input.ready(value)
    } catch {
      if (!disposed && !controller.signal.aborted) input.unavailable()
    } finally {
      if (active === controller) active = undefined
      if (queued && !disposed) { queued = false; void refresh() }
    }
  }
  const timer = setInterval(() => void refresh(), input.intervalMs ?? 60_000)
  return { refresh, dispose() { disposed = true; active?.abort(); clearInterval(timer) } }
}

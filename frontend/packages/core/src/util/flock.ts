import path from "path"
import os from "os"
import { randomBytes, randomUUID } from "crypto"
import { mkdir, readFile, rm, stat, lstat, rename, utimes, writeFile } from "fs/promises"
import { Hash } from "./hash"
import { Effect } from "effect"

export type FlockGlobal = {
  state: string
}

export namespace Flock {
  let global: FlockGlobal | undefined

  export function setGlobal(g: FlockGlobal) {
    global = g
  }

  const root = () => {
    if (!global) throw new Error("Flock global not set")
    return path.join(global.state, "locks")
  }

  // Defaults for callers that do not provide timing options.
  const defaultOpts = {
    staleMs: 60_000,
    timeoutMs: 5 * 60_000,
    baseDelayMs: 100,
    maxDelayMs: 2_000,
  }

  export interface WaitEvent {
    key: string
    attempt: number
    delay: number
    waited: number
  }

  export type Wait = (input: WaitEvent) => void | Promise<void>

  export interface Options {
    dir?: string
    signal?: AbortSignal
    staleMs?: number
    timeoutMs?: number
    baseDelayMs?: number
    maxDelayMs?: number
    onWait?: Wait
  }

  type Opts = {
    staleMs: number
    timeoutMs: number
    baseDelayMs: number
    maxDelayMs: number
  }

  type Owned = {
    acquired: true
    startHeartbeat: (intervalMs?: number) => void
    release: () => Promise<void>
  }

  export interface Lease {
    release: () => Promise<void>
    [Symbol.asyncDispose]: () => Promise<void>
  }

  export interface Owner {
    token: string
    pid: number
    hostname: string
    createdAt: string
  }

  /** Read lease ownership for explicit recovery. No timestamps imply expiry. */
  export async function inspect(key: string, input: Pick<Options, "dir"> = {}): Promise<Owner | undefined> {
    const directory = path.join(input.dir ?? root(), Hash.fast(key) + ".lock")
    const info = await lstat(directory).catch((error) => {
      if (code(error) === "ENOENT") return undefined
      throw error
    })
    if (!info) return undefined
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Invalid lock directory")
    const filename = path.join(directory, "meta.json")
    const meta = await lstat(filename)
    if (!meta.isFile() || meta.isSymbolicLink() || meta.size > 16_384) throw new Error("Invalid lock metadata")
    const owner = JSON.parse(await readFile(filename, "utf8")) as Partial<Owner>
    if (typeof owner.token !== "string" || !owner.token || !Number.isSafeInteger(owner.pid) || owner.pid! <= 0 ||
        typeof owner.hostname !== "string" || typeof owner.createdAt !== "string") throw new Error("Invalid lock owner")
    return owner as Owner
  }

  /** Recover only an exact, dead local owner after the caller records evidence.
   * This never sends a signal to a process or treats EPERM as process death. */
  export async function recover(key: string, expected: Owner, record: (owner: Owner) => Promise<void>, input: Pick<Options, "dir"> = {}) {
    const directory = input.dir ?? root()
    return recoverOwned(key, expected, record, directory, 0)
  }

  function deadLocalOwner(owner: Owner) {
    if (owner.hostname !== os.hostname()) return false
    try { process.kill(owner.pid, 0); return false } catch (error) { return code(error) === "ESRCH" }
  }

  async function recoverOwned(key: string, expected: Owner, record: (owner: Owner) => Promise<void>, directory: string, depth: number): Promise<void> {
    if (depth > 8) throw new Error("Repeated recovery crashes require host lock inspection")
    // A recovery process can itself crash. Recover its dead mutex owner using
    // the same token/host/process checks, never a time-based eviction. Recovery
    // mutexes carry no task effects, so they do not create task approval data.
    const blocker = await inspect(`recovery:${key}`, { dir: directory })
    if (blocker && deadLocalOwner(blocker)) {
      await recoverOwned(`recovery:${key}`, blocker, async () => {}, directory, depth + 1)
    }
    return withLock(`recovery:${key}`, async () => {
      const same = (value: Owner | undefined) => value && value.token === expected.token && value.pid === expected.pid &&
        value.hostname === expected.hostname && value.createdAt === expected.createdAt
      const owner = await inspect(key, { dir: directory })
      if (!same(owner) || !deadLocalOwner(owner!)) throw new Error("Lock changed or its owner is still running on this or another host")
      await record(owner!)
      if (!same(await inspect(key, { dir: directory }))) throw new Error("Lock changed during recovery")
      const lockfile = path.join(directory, Hash.fast(key) + ".lock")
      const retired = `${lockfile}.recovered-${randomUUID()}`
      // Retire the exact stale directory before new callers can acquire it.
      // Delete only this retired path; never a replacement owner's directory.
      await rename(lockfile, retired)
      await rm(retired, { recursive: true })
    }, { dir: directory, staleMs: Number.POSITIVE_INFINITY, timeoutMs: 5000 })
  }

  function code(err: unknown) {
    if (typeof err !== "object" || err === null || !("code" in err)) return
    const value = err.code
    if (typeof value !== "string") return
    return value
  }

  function sleep(ms: number, signal?: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
      if (signal?.aborted) {
        reject(signal.reason ?? new Error("Aborted"))
        return
      }

      let timer: NodeJS.Timeout | undefined

      const done = () => {
        signal?.removeEventListener("abort", abort)
        resolve()
      }

      const abort = () => {
        if (timer) {
          clearTimeout(timer)
        }
        signal?.removeEventListener("abort", abort)
        reject(signal?.reason ?? new Error("Aborted"))
      }

      signal?.addEventListener("abort", abort, { once: true })
      timer = setTimeout(done, ms)
    })
  }

  function jitter(ms: number) {
    const j = Math.floor(ms * 0.3)
    const d = Math.floor(Math.random() * (2 * j + 1)) - j
    return Math.max(0, ms + d)
  }

  function mono() {
    return performance.now()
  }

  function wall() {
    return performance.timeOrigin + mono()
  }

  async function stats(file: string) {
    try {
      return await stat(file)
    } catch (err) {
      const errCode = code(err)
      if (errCode === "ENOENT" || errCode === "ENOTDIR") return
      throw err
    }
  }

  async function stale(lockDir: string, heartbeatPath: string, metaPath: string, staleMs: number) {
    // Stale detection allows automatic recovery after crashed owners.
    const now = wall()
    const heartbeat = await stats(heartbeatPath)
    if (heartbeat) {
      return now - heartbeat.mtimeMs > staleMs
    }

    const meta = await stats(metaPath)
    if (meta) {
      return now - meta.mtimeMs > staleMs
    }

    const dir = await stats(lockDir)
    if (!dir) {
      return false
    }

    return now - dir.mtimeMs > staleMs
  }

  async function tryAcquireLockDir(lockDir: string, opts: Opts): Promise<Owned | { acquired: false }> {
    const token = randomUUID?.() ?? randomBytes(16).toString("hex")
    const metaPath = path.join(lockDir, "meta.json")
    const heartbeatPath = path.join(lockDir, "heartbeat")

    try {
      await mkdir(lockDir, { mode: 0o700 })
    } catch (err) {
      if (code(err) !== "EEXIST") {
        throw err
      }

      if (!(await stale(lockDir, heartbeatPath, metaPath, opts.staleMs))) {
        return { acquired: false }
      }

      const breakerPath = lockDir + ".breaker"
      try {
        await mkdir(breakerPath, { mode: 0o700 })
      } catch (claimErr) {
        const errCode = code(claimErr)
        if (errCode === "EEXIST") {
          const breaker = await stats(breakerPath)
          if (breaker && wall() - breaker.mtimeMs > opts.staleMs) {
            await rm(breakerPath, { recursive: true, force: true }).catch(() => undefined)
          }
          return { acquired: false }
        }

        if (errCode === "ENOENT" || errCode === "ENOTDIR") {
          return { acquired: false }
        }

        throw claimErr
      }

      try {
        // Breaker ownership ensures only one contender performs stale cleanup.
        if (!(await stale(lockDir, heartbeatPath, metaPath, opts.staleMs))) {
          return { acquired: false }
        }

        await rm(lockDir, { recursive: true, force: true })

        try {
          await mkdir(lockDir, { mode: 0o700 })
        } catch (retryErr) {
          const errCode = code(retryErr)
          if (errCode === "EEXIST" || errCode === "ENOTEMPTY") {
            return { acquired: false }
          }
          throw retryErr
        }
      } finally {
        await rm(breakerPath, { recursive: true, force: true }).catch(() => undefined)
      }
    }

    const meta = {
      token,
      pid: process.pid,
      hostname: os.hostname(),
      createdAt: new Date().toISOString(),
    }

    await writeFile(heartbeatPath, "", { flag: "wx" }).catch(async () => {
      await rm(lockDir, { recursive: true, force: true })
      throw new Error("Lock acquired but heartbeat already existed (possible compromise).")
    })

    await writeFile(metaPath, JSON.stringify(meta, null, 2), { flag: "wx" }).catch(async () => {
      await rm(lockDir, { recursive: true, force: true })
      throw new Error("Lock acquired but meta.json already existed (possible compromise).")
    })

    let timer: NodeJS.Timeout | undefined

    const startHeartbeat = (intervalMs = Math.max(100, Math.floor(opts.staleMs / 3))) => {
      if (timer) return
      // Non-expiring leases deliberately require explicit crash recovery.
      // Passing Infinity to setInterval would instead schedule every 1 ms.
      if (!Number.isFinite(intervalMs)) return
      // Heartbeat prevents long critical sections from being evicted as stale.
      timer = setInterval(() => {
        const t = new Date()
        void utimes(heartbeatPath, t, t).catch(() => undefined)
      }, intervalMs)
      timer.unref?.()
    }

    const release = async () => {
      if (timer) {
        clearInterval(timer)
        timer = undefined
      }

      const current = await readFile(metaPath, "utf8")
        .then((raw) => {
          const parsed = JSON.parse(raw)
          if (!parsed || typeof parsed !== "object") return {}
          return {
            token: "token" in parsed && typeof parsed.token === "string" ? parsed.token : undefined,
          }
        })
        .catch((err) => {
          const errCode = code(err)
          if (errCode === "ENOENT" || errCode === "ENOTDIR") {
            throw new Error("Refusing to release: lock is compromised (metadata missing).")
          }
          if (err instanceof SyntaxError) {
            throw new Error("Refusing to release: lock is compromised (metadata invalid).")
          }
          throw err
        })
      // Token check prevents deleting a lock that was re-acquired by another process.
      if (current.token !== token) {
        throw new Error("Refusing to release: lock token mismatch (not the owner).")
      }

      await rm(lockDir, { recursive: true, force: true })
    }

    return {
      acquired: true,
      startHeartbeat,
      release,
    }
  }

  async function acquireLockDir(
    lockDir: string,
    input: { key: string; onWait?: Wait; signal?: AbortSignal },
    opts: Opts,
  ) {
    const stop = mono() + opts.timeoutMs
    let attempt = 0
    let waited = 0
    let delay = opts.baseDelayMs

    while (true) {
      input.signal?.throwIfAborted()

      const res = await tryAcquireLockDir(lockDir, opts)
      if (res.acquired) {
        return res
      }

      if (mono() > stop) {
        throw new Error(`Timed out waiting for lock: ${input.key}`)
      }

      attempt += 1
      const ms = jitter(delay)
      await input.onWait?.({
        key: input.key,
        attempt,
        delay: ms,
        waited,
      })
      await sleep(ms, input.signal)
      waited += ms
      delay = Math.min(opts.maxDelayMs, Math.floor(delay * 1.7))
    }
  }

  export async function acquire(key: string, input: Options = {}): Promise<Lease> {
    input.signal?.throwIfAborted()
    const cfg: Opts = {
      staleMs: input.staleMs ?? defaultOpts.staleMs,
      timeoutMs: input.timeoutMs ?? defaultOpts.timeoutMs,
      baseDelayMs: input.baseDelayMs ?? defaultOpts.baseDelayMs,
      maxDelayMs: input.maxDelayMs ?? defaultOpts.maxDelayMs,
    }
    const dir = input.dir ?? root()

    await mkdir(dir, { recursive: true })
    const lockfile = path.join(dir, Hash.fast(key) + ".lock")
    const lock = await acquireLockDir(
      lockfile,
      {
        key,
        onWait: input.onWait,
        signal: input.signal,
      },
      cfg,
    )
    lock.startHeartbeat()

    const release = () => lock.release()
    return {
      release,
      [Symbol.asyncDispose]() {
        return release()
      },
    }
  }

  export async function withLock<T>(key: string, fn: () => Promise<T>, input: Options = {}) {
    await using _ = await acquire(key, input)
    input.signal?.throwIfAborted()
    return await fn()
  }

  export const effect = Effect.fn("Flock.effect")(function* (key: string, input: Options = {}) {
    return yield* Effect.acquireRelease(
      Effect.promise((signal) => Flock.acquire(key, { ...input, signal })).pipe(
        Effect.withSpan("Flock.acquire", {
          attributes: { key },
        }),
      ),
      (lock) => Effect.promise(() => lock.release()).pipe(Effect.withSpan("Flock.release")),
    ).pipe(Effect.asVoid)
  })
}

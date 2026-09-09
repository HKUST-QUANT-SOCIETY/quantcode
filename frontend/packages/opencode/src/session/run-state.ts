import { QuantCodeAccess } from "@/quantcode/access"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { Database } from "@opencode-ai/core/database/database"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { InstanceState } from "@/effect/instance-state"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import { Runner } from "@/effect/runner"
import { BackgroundJob } from "@/background/job"
import { Effect, Exit, Latch, Layer, Scope, Context, Deferred } from "effect"
import { Session } from "./session"
import { SessionID } from "./schema"
import { SessionStatus } from "./status"
import { SessionCancellation } from "./cancellation"

export interface Interface {
  readonly assertNotBusy: (sessionID: SessionID) => Effect.Effect<void, Session.BusyError>
  readonly cancel: (sessionID: SessionID) => Effect.Effect<void>
  readonly ensureRunning: (
    sessionID: SessionID,
    onInterrupt: Effect.Effect<SessionV1.WithParts>,
    work: Effect.Effect<SessionV1.WithParts>,
    admission?: () => void,
  ) => Effect.Effect<SessionV1.WithParts>
  readonly startShell: (
    sessionID: SessionID,
    onInterrupt: Effect.Effect<SessionV1.WithParts>,
    work: Effect.Effect<SessionV1.WithParts>,
    ready?: Latch.Latch,
  ) => Effect.Effect<SessionV1.WithParts, Session.BusyError>
}

export class Service extends Context.Service<Service, Interface>()("@opencode/SessionRunState") {}

const stoppingRunners = new WeakMap<Runner.Runner<SessionV1.WithParts>, Deferred.Deferred<void>>()
export const stopRunner = (running: Runner.Runner<SessionV1.WithParts>) => Effect.uninterruptible(Effect.gen(function* () {
  const previous = stoppingRunners.get(running)
  if (previous) return yield* Deferred.await(previous)
  const done = Deferred.makeUnsafe<void>()
  stoppingRunners.set(running, done)
  return yield* Effect.gen(function* () {
    const exit = yield* running.cancel.pipe(Effect.exit)
    yield* Deferred.done(done, exit)
    return yield* exit
  }).pipe(Effect.ensuring(Effect.sync(() => {
    if (stoppingRunners.get(running) === done) stoppingRunners.delete(running)
  })))
}))

const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const background = yield* BackgroundJob.Service
    const status = yield* SessionStatus.Service
    const database = yield* Database.Service

    // Use the existing runner/fiber cancellation mechanism. This watchdog does
    // not schedule work or own a second task state; it only revokes live work.
    const guarded = (sessionID: SessionID, work: Effect.Effect<SessionV1.WithParts>, check?: () => void) => Effect.gen(function* () {
      if (!QuantCodeIdentity.enabled()) return yield* work
      check?.()
      const admitted = yield* QuantCodeAccess.requireExecution(sessionID).pipe(Effect.provideService(Database.Service, database))
      if (!admitted) throw new QuantCodeIdentity.IdentityError()
      check?.()
      const watch: Effect.Effect<never> = Effect.gen(function* () {
        while (true) {
          yield* Effect.sleep("2 seconds")
          const current = yield* QuantCodeAccess.requireExecution(sessionID).pipe(Effect.provideService(Database.Service, database))
          if (!current || current.identity.session_id !== admitted.identity.session_id) {
            throw new QuantCodeIdentity.IdentityError("登录会话已改变，任务执行已停止。")
          }
        }
      })
      // raceFirst interrupts the watcher on normal completion. That interrupt
      // is not an identity revocation and must not cancel valid background work.
      return yield* Effect.raceFirst(work, watch).pipe(Effect.onExit(exit => Exit.isFailure(exit)
        ? cancelNativeTree(sessionID, true) : Effect.void))
    })

    const state = yield* InstanceState.make(
      Effect.fn("SessionRunState.state")(function* () {
        const scope = yield* Scope.Scope
        const runners = new Map<SessionID, Runner.Runner<SessionV1.WithParts>>()
        yield* Effect.addFinalizer(
          Effect.fnUntraced(function* () {
            yield* Effect.forEach(runners.values(), (runner) => runner.cancel, {
              concurrency: "unbounded",
              discard: true,
            })
            runners.clear()
          }),
        )
        return { runners, scope }
      }),
    )

    const runner = Effect.fn("SessionRunState.runner")(function* (
      sessionID: SessionID,
      onInterrupt: Effect.Effect<SessionV1.WithParts>,
    ) {
      const data = yield* InstanceState.get(state)
      const existing = data.runners.get(sessionID)
      if (existing) return existing
      const next = Runner.make<SessionV1.WithParts>(data.scope, {
        onIdle: Effect.gen(function* () {
          data.runners.delete(sessionID)
          yield* status.set(sessionID, { type: "idle" })
        }),
        onBusy: status.set(sessionID, { type: "busy" }),
        onInterrupt,
      })
      data.runners.set(sessionID, next)
      return next
    })

    const assertNotBusy = Effect.fn("SessionRunState.assertNotBusy")(function* (sessionID: SessionID) {
      const data = yield* InstanceState.get(state)
      const existing = data.runners.get(sessionID)
      if (existing?.busy) yield* busyError(sessionID)
    })

    const cancel = Effect.fn("SessionRunState.cancel")(function* (sessionID: SessionID) {
      if (QuantCodeIdentity.enabled()) return yield* cancelNativeTree(sessionID)
      const data = yield* InstanceState.get(state)
      const existing = data.runners.get(sessionID)
      // Interrupt the parent before discovering descendants so it cannot
      // launch another child after the cancellation snapshot was collected.
      if (existing) yield* existing.cancel
      yield* cancelBackgroundJobs(background, sessionID)
      if (existing && !data.runners.get(sessionID)?.busy) yield* status.set(sessionID, { type: "idle" }, "cancelled")
      // Without a local runner there is no execution to certify as stopped.
      // The durable projection independently reconciles a known dead executor.
    })

    const cancelNativeTree = Effect.fn("SessionRunState.cancelNativeTree")(function* (sessionID: SessionID, descendantsOnly = false) {
      const tree = yield* SessionCancellation.lineage(sessionID).pipe(Effect.provideService(Database.Service, database))
      const data = yield* InstanceState.get(state)
      const instance = yield* InstanceState.context
      if (instance.directory !== tree.selected.directory) throw new QuantCodeIdentity.IdentityError("任务执行宿主与停止请求的工作目录不一致。")
      return yield* Effect.acquireUseRelease(
        Effect.sync(() => SessionCancellation.hold(tree.binding, sessionID, !descendantsOnly)),
        () => Effect.gen(function* () {
          const stopped = new Set<SessionID>()
          // Stop this Runner before discovering descendants. The root fence
          // also rejects new starts and child Session.Created commits while
          // parent/child interruption finalizers are still being processed.
          const parent = data.runners.get(sessionID)
          if (!descendantsOnly && parent) {
            yield* stopRunner(parent)
            stopped.add(sessionID)
          }
          const children = yield* SessionCancellation.descendants(tree).pipe(Effect.provideService(Database.Service, database))
          for (const child of children.rows) SessionCancellation.invalidate(child.id)
          for (const child of children.rows) {
            const running = data.runners.get(child.id)
            if (!running) continue
            yield* stopRunner(running)
            stopped.add(child.id)
          }
          const selected = new Map<string, typeof tree.selected>([tree.selected, ...children.rows].map(row => [row.id, row]))
          const jobs = yield* background.list()
          for (const job of jobs) {
            if (job.status !== "running") continue
            const own = typeof job.metadata?.sessionId === "string" ? job.metadata.sessionId : job.id
            const row = selected.get(own)
            if (!row || descendantsOnly && row.id === sessionID || job.type === "task" && job.id !== row.id ||
              typeof job.metadata?.parentSessionId === "string" && job.metadata.parentSessionId !== row.parent_id) continue
            // Membership is proven by SessionTable, never by a job merely
            // claiming parentSessionId. A reopened child has no running job
            // and was already handled through the Runner map above.
            yield* background.cancel(job.id)
            stopped.add(row.id)
          }
          for (const id of stopped) if (!data.runners.get(id)?.busy) yield* status.set(id, { type: "idle" }, "cancelled")
          if (children.invalid) throw new QuantCodeIdentity.IdentityError("部分后代任务归属异常，未取消这些不匹配的记录。")
        }),
        release => Effect.sync(release),
      ).pipe(Effect.uninterruptible)
    })

    const ensureRunning = Effect.fn("SessionRunState.ensureRunning")(function* (
      sessionID: SessionID,
      onInterrupt: Effect.Effect<SessionV1.WithParts>,
      work: Effect.Effect<SessionV1.WithParts>,
      admission?: () => void,
    ) {
      admission?.()
      const admitted = QuantCodeIdentity.enabled()
        ? yield* QuantCodeAccess.requireExecution(sessionID).pipe(Effect.provideService(Database.Service, database)) : undefined
      const current = admitted && !admission ? SessionCancellation.admission(admitted.binding, sessionID) : undefined
      const check = () => { admission?.(); current?.() }
      return yield* (yield* runner(sessionID, onInterrupt)).ensureRunning(guarded(sessionID, work, check))
    })

    const startShell = Effect.fn("SessionRunState.startShell")(function* (
      sessionID: SessionID,
      onInterrupt: Effect.Effect<SessionV1.WithParts>,
      work: Effect.Effect<SessionV1.WithParts>,
      ready?: Latch.Latch,
    ) {
      const admitted = QuantCodeIdentity.enabled()
        ? yield* QuantCodeAccess.requireExecution(sessionID).pipe(Effect.provideService(Database.Service, database)) : undefined
      const check = admitted ? SessionCancellation.admission(admitted.binding, sessionID) : undefined
      return yield* (yield* runner(sessionID, onInterrupt))
        .startShell(guarded(sessionID, work, check).pipe(Effect.ensuring(ready ? ready.open : Effect.void)), ready)
        .pipe(Effect.catchTag("RunnerBusy", () => Effect.fail(busyError(sessionID))))
    })

    return Service.of({ assertNotBusy, cancel, ensureRunning, startShell })
  }),
)

const cancelBackgroundJobs = Effect.fn("SessionRunState.cancelBackgroundJobs")(function* (
  background: BackgroundJob.Interface,
  sessionID: SessionID,
  descendantsOnly = false,
) {
  const pending = new Set<string>([sessionID])
  const cancelled = new Set<string>()
  while (true) {
    const jobs = yield* background.list()
    // A completed intermediary may still have a running background child.
    // Discover the full ancestry before filtering for jobs that need stopping.
    let size = -1
    while (size !== pending.size) {
      size = pending.size
      for (const job of jobs) {
        const own = job.metadata?.sessionId
        const parent = job.metadata?.parentSessionId
        if (!pending.has(job.id) && !(typeof own === "string" && pending.has(own)) &&
            !(typeof parent === "string" && pending.has(parent))) continue
        pending.add(job.id)
        if (typeof own === "string") pending.add(own)
      }
    }
    const batch = jobs.filter(job => job.status === "running" && !cancelled.has(job.id) && pending.has(job.id) &&
      (!descendantsOnly || job.id !== sessionID && job.metadata?.sessionId !== sessionID))
    if (!batch.length) return
    yield* Effect.forEach(
      batch,
      (job) =>
        background.cancel(job.id).pipe(
          Effect.tap(() =>
            Effect.sync(() => {
              cancelled.add(job.id)
              pending.add(job.id)
              if (typeof job.metadata?.sessionId === "string") pending.add(job.metadata.sessionId)
            }),
          ),
        ),
      { concurrency: "unbounded", discard: true },
    )
  }
})

function busyError(sessionID: SessionID) {
  return new Session.BusyError({ sessionID })
}

export const node = LayerNode.make({ service: Service, layer: layer, deps: [BackgroundJob.node, SessionStatus.node, Database.node] })

export * as SessionRunState from "./run-state"

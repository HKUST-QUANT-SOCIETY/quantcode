import { expect } from "bun:test"
import { NodeHttpServer, NodeServices } from "@effect/platform-node"
import { AppNodeBuilder } from "@opencode-ai/core/effect/app-node-builder"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { Database } from "@opencode-ai/core/database/database"
import { AppProcess } from "@opencode-ai/core/process"
import { EventV2Bridge } from "@/event-v2-bridge"
import { SessionTable } from "@opencode-ai/core/session/sql"
import { SessionProjector } from "@opencode-ai/core/session/projector"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { Deferred, Effect, Exit, Fiber, Latch, Layer, Schema, Scope } from "effect"
import { HttpRouter, HttpServer, HttpServerResponse } from "effect/unstable/http"
import { eq } from "drizzle-orm"
import { writeFile } from "node:fs/promises"
import path from "node:path"
import { Session } from "@/session/session"
import { SessionRunState } from "@/session/run-state"
import { SessionPrompt } from "@/session/prompt"
import { Agent } from "@/agent/agent"
import { Config } from "@/config/config"
import { Truncate } from "@/tool/truncate"
import { ToolRegistry } from "@/tool/registry"
import { TaskTool, type TaskPromptOps } from "@/tool/task"
import { SessionCancellation } from "@/session/cancellation"
import { SessionStatus } from "@/session/status"
import { BackgroundJob } from "@/background/job"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { InstanceBootstrap } from "@/project/bootstrap"
import { InstanceStore } from "@/project/instance-store"
import { RuntimeFlags } from "@/effect/runtime-flags"
import { Runner } from "@/effect/runner"
import { WorkspaceV2 } from "@opencode-ai/core/workspace"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { ModelV2 } from "@opencode-ai/core/model"
import { MessageID } from "@/session/schema"
import { TestInstance, tmpdirScoped } from "../fixture/fixture"
import { awaitWithTimeout, testEffect } from "../lib/effect"

const it = testEffect(Layer.mergeAll(NodeHttpServer.layerTest, NodeServices.layer, AppNodeBuilder.build(
  LayerNode.group([Database.node, AppProcess.node, EventV2Bridge.node, BackgroundJob.node, SessionStatus.node,
    Agent.node, Config.node, Truncate.node, ToolRegistry.node, RuntimeFlags.node,
    Session.node, SessionRunState.node, SessionPrompt.node, SessionProjector.node, CrossSpawnSpawner.node, InstanceStore.node]),
  [[RuntimeFlags.node, RuntimeFlags.layer({ experimentalWorkspaces: false, experimentalBackgroundSubagents: true })],
    [InstanceBootstrap.node, Layer.succeed(InstanceBootstrap.Service, InstanceBootstrap.Service.of({ run: Effect.void }))]],
)))

const fixture = Effect.gen(function* () {
  const { directory } = yield* TestInstance
  const now = Date.now()
  const identity: QuantCodeIdentity.Identity = { session_id: "fixture-cancellation-login", actor_id: "fixture-cancellation-owner",
    group: "factor", role: "analyst", workspace_id: "fixture-cancellation-workspace", workspace_path: directory,
    github_subject: null, resource_scopes: [], authorized_groups: ["factor"], identity_source: "ssh_roster",
    issued_at: new Date(now).toISOString(), expires_at: new Date(now + 60_000).toISOString() }
  // Only the external roster response is fixed. All Session/Event/Runner,
  // ownership traversal, child creation and BackgroundJob code is real.
  let respond = () => Effect.succeed(HttpServerResponse.jsonUnsafe(identity))
  yield* HttpRouter.add("GET", "/session", Effect.suspend(() => respond())).pipe(HttpRouter.serve, Layer.build)
  const server = yield* HttpServer.HttpServer
  const control = yield* tmpdirScoped()
  const credential = path.join(control, "fixture-identity.json")
  const gateway = HttpServer.formatAddress(server.address).replace("0.0.0.0", "127.0.0.1").replace("[::]", "[::1]")
  yield* Effect.promise(() => writeFile(credential, JSON.stringify({ gateway, token: "fixture-only" }), { mode: 0o600 }))
  yield* Effect.acquireRelease(Effect.sync(() => {
    const values = { OPENCODE_CHANNEL: "quantcode", QUANTCODE_UNIFIED_RUNTIME: "1", QUANTCODE_IDENTITY_SESSION_FILE: credential,
      QUANTCODE_WORKSPACES_FILE: path.join(control, "no-extra-grants.json") }
    const previous = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]))
    Object.assign(process.env, values)
    return previous
  }), previous => Effect.sync(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }))
  return { identity, sessions: yield* Session.Service, runs: yield* SessionRunState.Service,
    background: yield* BackgroundJob.Service, status: yield* SessionStatus.Service, database: yield* Database.Service,
    identityResponse: (next: typeof respond) => { respond = next } }
})

function result(session: Session.Info): SessionV1.WithParts {
  return { info: { id: MessageID.make("msg_fixture_cancelled"), sessionID: session.id,
    role: "user", time: { created: Date.now() }, agent: "fixture",
    model: { providerID: ProviderV2.ID.make("fixture"), modelID: ModelV2.ID.make("fixture") } }, parts: [] }
}

const running = (host: Effect.Success<typeof fixture>, session: Session.Info, cleanup: Effect.Effect<void> = Effect.void) => Effect.gen(function* () {
  const ready = yield* Deferred.make<void>()
  const stopped = yield* Deferred.make<void>()
  const fiber = yield* host.runs.ensureRunning(session.id, Effect.succeed(result(session)), Effect.gen(function* () {
    yield* host.status.set(session.id, { type: "busy" })
    yield* Deferred.succeed(ready, undefined)
    return yield* Effect.never
  }).pipe(Effect.onInterrupt(() => cleanup.pipe(Effect.andThen(Deferred.succeed(stopped, undefined)), Effect.asVoid)))).pipe(Effect.forkChild)
  yield* awaitWithTimeout(Deferred.await(ready), "fixture runner did not start")
  return { fiber, stopped }
})

it.instance("parent cancellation stops reopened descendants and fences new starts and child creation", () => Effect.gen(function* () {
  const host = yield* fixture
  const parent = yield* host.sessions.create({ title: "parent" })
  const child = yield* host.sessions.create({ parentID: parent.id, title: "reopened child" })
  const grandchild = yield* host.sessions.create({ parentID: child.id, title: "grandchild" })
  const unrelated = yield* host.sessions.create({ title: "unrelated" })
  const old = yield* host.background.start({ id: child.id, type: "task", metadata: { sessionId: child.id, parentSessionId: parent.id }, run: Effect.succeed("original completed call") })
  expect((yield* host.background.wait({ id: old.id })).info?.status).toBe("completed")
  const entered = yield* Deferred.make<void>()
  const release = yield* Deferred.make<void>()
  const p = yield* running(host, parent, Deferred.succeed(entered, undefined).pipe(Effect.andThen(Deferred.await(release))))
  const c = yield* running(host, child)
  const g = yield* running(host, grandchild)
  const other = yield* running(host, unrelated)
  const prior = SessionCancellation.admission(QuantCodeIdentity.requireOwner(parent.metadata, host.identity))
  const cancellation = yield* host.runs.cancel(parent.id).pipe(Effect.forkChild)
  yield* Effect.gen(function* () {
    yield* awaitWithTimeout(Deferred.await(entered), "parent did not enter cancellation")
    expect(Exit.isFailure(yield* host.sessions.create({ parentID: child.id }).pipe(Effect.exit))).toBe(true)
    expect(Exit.isFailure(yield* host.runs.ensureRunning(child.id, Effect.succeed(result(child)), Effect.succeed(result(child))).pipe(Effect.exit))).toBe(true)
  }).pipe(Effect.ensuring(Deferred.succeed(release, undefined)))
  expect(Exit.isSuccess(yield* awaitWithTimeout(Fiber.await(cancellation), "parent cancellation did not finish"))).toBe(true)
  for (const work of [p, c, g]) {
    expect(yield* Deferred.isDone(work.stopped)).toBe(true)
    yield* awaitWithTimeout(Fiber.await(work.fiber), "descendant caller did not resolve")
  }
  expect(yield* Deferred.isDone(other.stopped)).toBe(false)
  expect(() => prior()).toThrow(SessionCancellation.Cancelling)
  expect(() => SessionCancellation.admission(QuantCodeIdentity.requireOwner(parent.metadata, host.identity))).not.toThrow()
  yield* host.runs.cancel(unrelated.id)
}), { config: { formatter: false, lsp: false, mcp: {} } })

it.instance("failed shell admission releases readiness and does not deadlock cancellation", () => Effect.gen(function* () {
  const host = yield* fixture
  const task = yield* host.sessions.create({ title: "shell admission" })
  const secondRequest = yield* Deferred.make<void>()
  const release = yield* Deferred.make<void>()
  let requests = 0
  host.identityResponse(() => Effect.gen(function* () {
    if (++requests === 1) return HttpServerResponse.jsonUnsafe(host.identity)
    yield* Deferred.succeed(secondRequest, undefined)
    yield* Deferred.await(release)
    return HttpServerResponse.jsonUnsafe({ error: "fixture revoked" }, { status: 401 })
  }))
  const ready = yield* Latch.make()
  let executed = false
  const shell = yield* host.runs.startShell(task.id, Effect.succeed(result(task)), Effect.sync(() => {
    executed = true
    return result(task)
  }), ready).pipe(Effect.forkChild)
  yield* awaitWithTimeout(Deferred.await(secondRequest), "shell guard did not reach its second identity check")
  const cancel = yield* host.runs.cancel(task.id).pipe(Effect.forkChild)
  yield* Deferred.succeed(release, undefined)
  yield* awaitWithTimeout(Fiber.await(cancel), "cancel waited forever for shell readiness")
  yield* awaitWithTimeout(Fiber.await(shell), "rejected shell did not finish")
  yield* awaitWithTimeout(ready.await, "guard failure left the shell readiness latch closed")
  expect(executed).toBe(false)
}), { config: { formatter: false, lsp: false, mcp: {} } })

it.instance("stopping the same Runner again cancels its new execution", () => Effect.gen(function* () {
  const host = yield* fixture
  const task = yield* host.sessions.create({ title: "same Runner reuse" })
  const runner = Runner.make<SessionV1.WithParts>(yield* Scope.Scope, { onInterrupt: Effect.succeed(result(task)) })
  yield* SessionRunState.stopRunner(runner)
  for (let iteration = 0; iteration < 2; iteration++) {
    const started = yield* Deferred.make<void>()
    const stopped = yield* Deferred.make<void>()
    const work = yield* runner.ensureRunning(Deferred.succeed(started, undefined).pipe(Effect.andThen(Effect.never),
      Effect.onInterrupt(() => Deferred.succeed(stopped, undefined).pipe(Effect.asVoid)))).pipe(Effect.forkChild)
    yield* awaitWithTimeout(Deferred.await(started), "reused Runner did not start")
    yield* SessionRunState.stopRunner(runner)
    yield* awaitWithTimeout(Fiber.await(work), "cached prior stop skipped the new execution")
    expect(yield* Deferred.isDone(stopped)).toBe(true)
  }
}), { config: { formatter: false, lsp: false, mcp: {} } })

it.instance("children inherit parent workspace and stale notification admission cannot commit input", () => Effect.gen(function* () {
  const host = yield* fixture
  const workspaceID = WorkspaceV2.ID.make("wrk_fixture_cancellation")
  const parent = yield* host.sessions.create({ title: "parent workspace", workspaceID })
  const child = yield* host.sessions.create({ parentID: parent.id, title: "inherited workspace" })
  expect(child.workspaceID).toBe(parent.workspaceID)
  expect(child.projectID).toBe(parent.projectID)
  expect(Exit.isFailure(yield* host.sessions.create({ parentID: parent.id,
    workspaceID: WorkspaceV2.ID.make("wrk_other_fixture") }).pipe(Effect.exit))).toBe(true)
  const admission = SessionCancellation.admission(QuantCodeIdentity.requireOwner(parent.metadata, host.identity))
  const creating = yield* Deferred.make<void>()
  const release = yield* Deferred.make<void>()
  let holdIdentity = true
  host.identityResponse(() => Effect.gen(function* () {
    if (holdIdentity) {
      yield* Deferred.succeed(creating, undefined)
      yield* Deferred.await(release)
    }
    return HttpServerResponse.jsonUnsafe(host.identity)
  }))
  const lateChild = yield* host.sessions.create({ parentID: parent.id, title: "stale tool creation" }).pipe(
    Effect.provideService(SessionCancellation.InputAdmission, admission), Effect.forkChild)
  yield* Effect.gen(function* () {
    yield* awaitWithTimeout(Deferred.await(creating), "child creation did not reach its identity lookup")
    yield* host.runs.cancel(parent.id)
  }).pipe(Effect.ensuring(Effect.gen(function* () { holdIdentity = false; yield* Deferred.succeed(release, undefined) })))
  expect(Exit.isFailure(yield* awaitWithTimeout(Fiber.await(lateChild), "stale child creation did not finish"))).toBe(true)
  expect((yield* host.sessions.children(parent.id)).map(item => item.id)).toEqual([child.id])
  const input = result(parent)
  expect(Exit.isFailure(yield* host.sessions.updateMessage(input.info).pipe(
    Effect.provideService(SessionCancellation.InputAdmission, admission), Effect.exit))).toBe(true)
  expect(yield* host.sessions.messages({ sessionID: parent.id })).toEqual([])
  let resumed = false
  expect(Exit.isFailure(yield* host.runs.ensureRunning(parent.id, Effect.succeed(input), Effect.sync(() => {
    resumed = true
    return input
  }), admission).pipe(Effect.exit))).toBe(true)
  expect(resumed).toBe(false)
}), { config: { formatter: false, lsp: false, mcp: {} } })

it.instance("parent cancellation never follows a foreign owner or a job's forged parent metadata", () => Effect.gen(function* () {
  const host = yield* fixture
  const parent = yield* host.sessions.create({ title: "parent" })
  const valid = yield* host.sessions.create({ parentID: parent.id, title: "valid child" })
  const foreign = yield* host.sessions.create({ parentID: parent.id, title: "foreign child" })
  const changedOwner = yield* host.sessions.create({ parentID: parent.id, title: "changed owner" })
  const unrelated = yield* host.sessions.create({ title: "unrelated" })
  const validRun = yield* running(host, valid)
  const foreignRun = yield* running(host, foreign)
  const otherRun = yield* running(host, unrelated)
  const forged = yield* host.background.start({ id: unrelated.id, type: "task",
    metadata: { sessionId: unrelated.id, parentSessionId: parent.id }, run: Effect.never })
  const foreignJob = yield* host.background.start({ id: changedOwner.id, type: "task",
    metadata: { sessionId: changedOwner.id, parentSessionId: parent.id }, run: Effect.never })
  const binding = QuantCodeIdentity.requireOwner(foreign.metadata, host.identity)
  yield* host.database.db.update(SessionTable).set({ metadata: { ...foreign.metadata,
    quantcode: { ...binding, root_session_id: unrelated.id } } })
    .where(eq(SessionTable.id, foreign.id)).run().pipe(Effect.orDie)
  const otherBinding = QuantCodeIdentity.requireOwner(changedOwner.metadata, host.identity)
  yield* host.database.db.update(SessionTable).set({ metadata: { ...changedOwner.metadata,
    quantcode: { ...otherBinding, owner: { ...otherBinding.owner, actor_id: "foreign-actor", resource_scopes: ["foreign-scope"] } } } })
    .where(eq(SessionTable.id, changedOwner.id)).run().pipe(Effect.orDie)
  expect(Exit.isFailure(yield* host.runs.cancel(parent.id).pipe(Effect.exit))).toBe(true)
  expect(yield* Deferred.isDone(validRun.stopped)).toBe(true)
  expect(yield* Deferred.isDone(foreignRun.stopped)).toBe(false)
  expect(yield* Deferred.isDone(otherRun.stopped)).toBe(false)
  expect((yield* host.background.get(forged.id))?.status).toBe("running")
  expect((yield* host.background.get(foreignJob.id))?.status).toBe("running")
  yield* host.database.db.update(SessionTable).set({ metadata: foreign.metadata }).where(eq(SessionTable.id, foreign.id)).run().pipe(Effect.orDie)
  yield* host.database.db.update(SessionTable).set({ metadata: changedOwner.metadata }).where(eq(SessionTable.id, changedOwner.id)).run().pipe(Effect.orDie)
  yield* host.runs.cancel(foreign.id)
  yield* host.runs.cancel(changedOwner.id)
  yield* host.runs.cancel(unrelated.id)
  yield* host.background.cancel(forged.id)
}), { config: { formatter: false, lsp: false, mcp: {} } })

it.instance("real TaskTool failure notifications arrive, but late notifications cannot revive a cancelled parent", () => Effect.gen(function* () {
  const host = yield* fixture
  const prompt = yield* SessionPrompt.Service
  const tool = yield* TaskTool
  const definition = yield* tool.init()
  for (const scenario of ["normal_error", "late_cancel"] as const) {
    const parent = yield* host.sessions.create({ title: scenario, agent: "build" })
    const assistant = Schema.decodeUnknownSync(SessionV1.Assistant)({ id: `msg_fixture_${scenario}`, sessionID: parent.id,
      parentID: `msg_fixture_input_${scenario}`, role: "assistant", mode: "build", agent: "build", cost: 0,
      path: { cwd: parent.directory, root: parent.directory }, modelID: "fixture", providerID: "fixture",
      tokens: { input: 0, output: 0, reasoning: 0, cache: { read: 0, write: 0 } }, time: { created: Date.now() } })
    yield* host.sessions.updateMessage(assistant)
    const blocked = yield* Deferred.make<void>()
    const release = yield* Deferred.make<void>()
    const notified = yield* Deferred.make<Exit.Exit<SessionV1.WithParts>>()
    let parentPrompt = false
    host.identityResponse(() => Effect.gen(function* () {
      if (scenario === "late_cancel" && parentPrompt) {
        yield* Deferred.succeed(blocked, undefined)
        yield* Deferred.await(release)
      }
      return HttpServerResponse.jsonUnsafe(host.identity)
    }))
    const ops: TaskPromptOps = {
      cancel: id => host.runs.cancel(id),
      resolvePromptParts: text => Effect.succeed([{ type: "text", text }]),
      prompt: (input, admission) => Effect.gen(function* () {
        if (input.sessionID !== parent.id) {
          const child = yield* host.sessions.get(input.sessionID).pipe(Effect.orDie)
          return yield* host.runs.ensureRunning(child.id, Effect.succeed(result(child)),
            scenario === "normal_error" ? Effect.die(new Error("fixture provider error")) : Effect.succeed(result(child)), admission)
        }
        parentPrompt = true
        // Only model execution is omitted. The real TaskTool notify/inject,
        // real Prompt admission and Session/Event input commits remain intact.
        const exit = yield* prompt.prompt({ ...input, noReply: true,
          model: { providerID: assistant.providerID, modelID: assistant.modelID } }, admission).pipe(Effect.orDie, Effect.exit)
        yield* Deferred.succeed(notified, exit)
        return yield* exit
      }),
    }
    yield* definition.execute({ description: "notification regression", prompt: "fixture only", subagent_type: "general", background: true }, {
      sessionID: parent.id, messageID: assistant.id, agent: "build", callID: `call_${scenario}`,
      abort: new AbortController().signal, extra: { promptOps: ops }, messages: [],
      metadata: () => Effect.void, ask: () => Effect.void,
    })
    if (scenario === "late_cancel") {
      yield* Effect.gen(function* () {
        yield* awaitWithTimeout(Deferred.await(blocked), "real parent Prompt did not reach delayed identity lookup")
        yield* host.runs.cancel(parent.id)
      }).pipe(Effect.ensuring(Deferred.succeed(release, undefined)))
    }
    const outcome = yield* awaitWithTimeout(Deferred.await(notified), "TaskTool did not deliver its expected notification")
    const messages = yield* host.sessions.messages({ sessionID: parent.id })
    if (scenario === "normal_error") {
      expect(Exit.isSuccess(outcome)).toBe(true)
      expect(messages.some(message => message.parts.some(part => part.type === "text" && part.text.includes("Background task failed")))).toBe(true)
    } else {
      expect(Exit.isFailure(outcome)).toBe(true)
      expect(messages.map(message => message.info.id)).toEqual([assistant.id])
    }
  }
}), { config: { formatter: false, lsp: false, mcp: {} } })

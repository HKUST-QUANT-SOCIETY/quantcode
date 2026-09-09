import { expect } from "bun:test"
import { Effect, Layer, Schema } from "effect"
import { AppNodeBuilder } from "@opencode-ai/core/effect/app-node-builder"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { Database } from "@opencode-ai/core/database/database"
import { AppProcess } from "@opencode-ai/core/process"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { Global } from "@opencode-ai/core/global"
import { SessionProjector } from "@opencode-ai/core/session/projector"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import { EventTable } from "@opencode-ai/core/event/sql"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { ModelV2 } from "@opencode-ai/core/model"
import { asc, eq } from "drizzle-orm"
import { createServer } from "node:http"
import { once } from "node:events"
import { readFile, realpath, writeFile } from "node:fs/promises"
import { createHash, randomUUID } from "node:crypto"
import path from "node:path"
import { EventV2Bridge } from "../../src/event-v2-bridge"
import { Session } from "../../src/session/session"
import { SessionTools } from "../../src/session/tools"
import { SessionProcessor } from "../../src/session/processor"
import { Agent } from "../../src/agent/agent"
import { Skill } from "../../src/skill"
import { MCP } from "../../src/mcp"
import { Plugin } from "../../src/plugin"
import { Permission } from "../../src/permission"
import { Provider } from "../../src/provider/provider"
import { ToolRegistry } from "../../src/tool/registry"
import { Tool } from "../../src/tool/tool"
import { WriteTool } from "../../src/tool/write"
import { Truncate } from "../../src/tool/truncate"
import { Format } from "../../src/format"
import { LSP } from "../../src/lsp/lsp"
import { MessageID, PartID } from "../../src/session/schema"
import { InstanceBootstrap } from "../../src/project/bootstrap"
import { QuantCodeIdentity } from "../../src/quantcode/identity"
import { QuantCodeArtifacts } from "../../src/quantcode/artifacts"
import { QuantCodeReuse } from "../../src/quantcode/reuse"
import { QuantCodeSolution } from "../../src/quantcode/solution"
import { QuantCodeToolCatalog } from "../../src/quantcode/tool-catalog"
import { QuantCodeWritePolicy } from "../../src/quantcode/write-policy"
import { QuantCodeWriteReceipt } from "../../src/quantcode/write-receipt"
import { QuantCodeTaskContext } from "../../src/quantcode/task-context"
import { TestInstance, tmpdirScoped } from "../fixture/fixture"
import { testEffect } from "../lib/effect"

const it = testEffect(AppNodeBuilder.build(LayerNode.group([Database.node, AppProcess.node, CrossSpawnSpawner.node,
  Session.node, SessionProjector.node, EventV2Bridge.node, Agent.node, MCP.node, Plugin.node, Permission.node,
  Truncate.node, Format.node, LSP.node, FSUtil.node, Skill.node]),
[[InstanceBootstrap.node, Layer.succeed(InstanceBootstrap.Service, InstanceBootstrap.Service.of({ run: Effect.void }))]]))

const model: Provider.Model = {
  id: ModelV2.ID.make("fixture"), providerID: ProviderV2.ID.make("fixture"), name: "Fixture",
  api: { id: "fixture", url: "http://127.0.0.1:1", npm: "@ai-sdk/openai-compatible" },
  capabilities: { temperature: false, reasoning: false, attachment: false, toolcall: true, interleaved: false,
    input: { text: true, audio: false, image: false, video: false, pdf: false },
    output: { text: true, audio: false, image: false, video: false, pdf: false } },
  cost: { input: 0, output: 0, cache: { read: 0, write: 0 } }, limit: { context: 10000, input: 9000, output: 1000 },
  status: "active", options: {}, headers: {}, release_date: "2026-09-09",
}
const resultSchema = Schema.Struct({ title: Schema.String, output: Schema.String, metadata: Schema.Record(Schema.String, Schema.Unknown) })

const setup = Effect.gen(function* () {
  const instance = yield* TestInstance
  const control = yield* tmpdirScoped()
  const statePath = Global.Path.state
  if (!statePath.includes(`opencode-test-data-${process.pid}${path.sep}`)) throw new Error("Artifact tests require isolated test state")
  Global.Path.state = yield* Effect.promise(() => realpath(statePath))
  yield* Effect.addFinalizer(() => Effect.sync(() => { Global.Path.state = statePath }))
  const root = path.resolve(import.meta.dirname, "../../../../..")
  const identity: QuantCodeIdentity.Identity = {
    session_id: randomUUID().replaceAll("-", ""), actor_id: "fixture-artifact-owner", group: "factor", role: "analyst",
    workspace_id: "fixture-artifact-workspace", workspace_path: instance.directory, github_subject: null,
    resource_scopes: [], authorized_groups: ["factor"], identity_source: "ssh_roster",
    issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 300000).toISOString(),
  }
  const authority = createServer((request, response) => {
    if (request.url !== "/session" || request.headers.authorization !== "Bearer fixture-artifact-token") {
      response.writeHead(401).end()
      return
    }
    response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(identity))
  })
  yield* Effect.addFinalizer(() => Effect.promise(async () => {
    authority.closeAllConnections()
    if (authority.listening) await new Promise<void>((resolve, reject) => authority.close(error => error ? reject(error) : resolve()))
  }))
  authority.listen(0, "127.0.0.1")
  yield* Effect.promise(() => once(authority, "listening"))
  const address = authority.address()
  if (!address || typeof address === "string") throw new Error("Fixture authority unavailable")
  const credential = path.join(control, "identity.json")
  const catalogFile = path.join(control, "catalog.json")
  yield* Effect.promise(() => writeFile(credential, JSON.stringify({
    gateway: `http://127.0.0.1:${address.port}`, token: "fixture-artifact-token",
  }), { mode: 0o600 }))
  const entries = ["capability_catalog", "group_memory"].map(purpose => QuantCodeToolCatalog.entrySchema.parse({
    server: "fixture", tool: purpose, purpose, effect: "read", groups: ["factor"], roles: ["analyst"],
    status: "published", server_config_hash: "a".repeat(64), input_schema_hash: "b".repeat(64),
  }))
  const release = "fixture-artifact-catalog"
  yield* Effect.promise(() => writeFile(catalogFile, JSON.stringify({ version: 1, release,
    published_at: new Date().toISOString(), tools: entries }), { mode: 0o600 }))
  const values = { OPENCODE_CHANNEL: "quantcode", QUANTCODE_UNIFIED_RUNTIME: "1", QUANTCODE_IDENTITY_SESSION_FILE: credential,
    QUANTCODE_WORKSPACES_FILE: path.join(control, "no-extra-grants.json"), QUANTCODE_TOOL_CATALOG_FILE: catalogFile,
    QUANTCODE_HOST_PYTHON: path.join(root, ".venv/bin/python"), QUANTCODE_BACKEND_ROOT: root }
  const previous = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]))
  yield* Effect.addFinalizer(() => Effect.sync(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }))
  Object.assign(process.env, values)
  const sessions = yield* Session.Service
  const session = yield* sessions.create({ title: "Artifact capture fixture", permission: [{ permission: "*", pattern: "*", action: "allow" }] })
  const user: SessionV1.User = { id: MessageID.ascending(), sessionID: session.id, role: "user", time: { created: Date.now() },
    agent: "build", model: { providerID: model.providerID, modelID: model.id } }
  yield* sessions.updateMessage(user)
  yield* sessions.updatePart({ id: PartID.ascending(), sessionID: session.id, messageID: user.id, type: "text", text: "Create artifact.txt with the requested fixture bytes." })
  for (const entry of entries) {
    const captured = yield* QuantCodeReuse.capture(session.id)
    yield* QuantCodeReuse.observe(session.id, entry.tool, { entry, release, digest: QuantCodeToolCatalog.digest({ release, entry }) },
      { structuredContent: entry.purpose === "capability_catalog" ? { capabilities: [] } : { hits: [] } }, captured)
  }
  const coverage = yield* QuantCodeReuse.propose(session.id, { coverage: "none", components: [], reason: "Explicit fixture write needs no component." })
  yield* QuantCodeReuse.review(session.id, { proposal_hash: coverage.proposal!.proposal_hash, decision: "approve", note: "Approve only this fixture write." })
  const proposal = yield* QuantCodeSolution.propose(session.id, { goal: "Create artifact.txt", acceptance_criteria: ["Exact fixture bytes"], file_impact: ["artifact.txt"] })
  yield* QuantCodeSolution.review(session.id, { expected_hash: proposal.solution!.doc_hash, expected_version: proposal.solution!.version,
    decision: "approve", note: "Approve only artifact.txt." })
  const assistant: SessionV1.Assistant = { id: MessageID.ascending(), sessionID: session.id, role: "assistant", parentID: user.id,
    time: { created: Date.now() }, modelID: model.id, providerID: model.providerID, mode: "build", agent: "build",
    path: { cwd: instance.directory, root: instance.directory }, cost: 0, tokens: { input: 0, output: 0, reasoning: 0, cache: { read: 0, write: 0 } } }
  yield* sessions.updateMessage(assistant)
  const filepath = path.join(instance.directory, "artifact.txt")
  const args = { filePath: filepath, content: "Original immutable artifact bytes\n" }
  const callID = "fixture-artifact-write"
  let part: SessionV1.ToolPart = { id: PartID.ascending(), messageID: assistant.id, sessionID: session.id, type: "tool",
    callID, tool: "write", state: { status: "pending", input: args, raw: JSON.stringify(args) } }
  yield* sessions.updatePart(part)
  const processor: Pick<SessionProcessor.Handle, "message" | "updateToolCall" | "completeToolCall"> = {
    message: assistant,
    updateToolCall: (_call, update) => Effect.gen(function* () {
      part = update(part)
      yield* sessions.updatePart(part)
      return part
    }),
    completeToolCall: (_call, output) => Effect.gen(function* () {
      part = { ...part, state: { ...output, input: args, status: "completed", time: { start: Date.now(), end: Date.now() } } }
      yield* sessions.updatePart(part)
    }),
  }
  const truncate = yield* Truncate.Service
  let formatted = 0
  const wrapped = yield* Tool.init(yield* WriteTool.pipe(Effect.provideService(Truncate.Service, { ...truncate,
    output: (text, options, agent) => Effect.gen(function* () { formatted++; return yield* truncate.output(text, { ...options, maxBytes: 1 }, agent) }),
  })))
  const registry: ToolRegistry.Interface = { ids: () => Effect.succeed([wrapped.id]), all: () => Effect.succeed([wrapped]),
    named: () => Effect.die(new Error("Named tools are outside this fixture")), tools: () => Effect.succeed([wrapped]) }
  const agents = yield* Agent.Service
  const agent = yield* agents.get("build")
  if (!agent) throw new Error("Fixture build agent missing")
  const tools = yield* SessionTools.resolve({ agent, model, session, processor, messages: [], bypassAgentCheck: false,
    promptOps: { cancel: () => Effect.void, resolvePromptParts: () => Effect.succeed([]), prompt: () => Effect.die(new Error("No model runs in this fixture")) },
  }).pipe(Effect.provideService(ToolRegistry.Service, registry))
  const invoke = () => Effect.gen(function* () {
    const execute = tools.write.execute
    if (!execute) throw new Error("Resolved write tool missing")
    const output = yield* Effect.promise(async () => Schema.decodeUnknownSync(resultSchema)(await execute(args, {
      toolCallId: callID, messages: [], abortSignal: new AbortController().signal,
    })))
    yield* processor.completeToolCall(callID, output)
    return output
  })
  return { session, user, agent, identity, assistant, filepath, args, callID, invoke, formatted: () => formatted, database: yield* Database.Service }
})

it.instance("identical coverage retries preserve decisions while changed content or login cannot reuse approval", () => Effect.gen(function* () {
  const fixture = yield* setup
  const approved = yield* QuantCodeReuse.state(fixture.session.id)
  const proposal = { coverage: approved.proposal!.coverage, components: [...approved.proposal!.components],
    reason: approved.proposal!.reason }
  const repeated = yield* QuantCodeReuse.propose(fixture.session.id, proposal)
  expect(repeated.proposal).toEqual(approved.proposal)
  expect(repeated.review).toEqual(approved.review)
  const changed = { ...proposal, reason: "A different proposed scope requires another review." }
  const revised = yield* QuantCodeReuse.propose(fixture.session.id, changed)
  expect(revised.proposal!.proposal_hash).not.toBe(approved.proposal!.proposal_hash)
  expect(revised.review).toBeUndefined()
  const rejected = yield* QuantCodeReuse.review(fixture.session.id, { proposal_hash: revised.proposal!.proposal_hash,
    decision: "reject", note: "Do not proceed with this revision." })
  const retried = yield* QuantCodeReuse.propose(fixture.session.id, changed)
  expect(retried.proposal).toEqual(rejected.proposal)
  expect(retried.review).toEqual(rejected.review)
  fixture.identity.session_id = randomUUID().replaceAll("-", "")
  const afterLogin = yield* QuantCodeReuse.propose(fixture.session.id, changed).pipe(Effect.exit)
  expect(afterLogin._tag).toBe("Failure")
}), { config: { formatter: false, lsp: false, mcp: {}, plugin: [] } })

it.instance("resumed native context reflects live reviews without changing the authorized intent", () => Effect.gen(function* () {
  const fixture = yield* setup
  const sessions = yield* Session.Service
  const before = yield* QuantCodeReuse.state(fixture.session.id)
  const resumed = { ...fixture.user, id: MessageID.ascending() }
  yield* sessions.updateMessage(resumed)
  const load = (user: SessionV1.User) => QuantCodeTaskContext.load({ session: fixture.session,
    messageID: fixture.assistant.id, agent: fixture.agent, user })
  const reviewState = (context: { context: string[] }) => JSON.parse(context.context.find(line =>
    line.startsWith("Current task review state"))!.split("\n")[1])
  const initial = reviewState(yield* load(fixture.user))
  expect(initial.action).toBe("task_input")
  const continued = yield* load(resumed)
  expect(reviewState(continued)).toMatchObject({ action: "resume_original_task", intent_hash: before.intentHash,
    coverage: { decision: "approve", proposal_hash: before.proposal!.proposal_hash }, solution: { status: "frozen" } })
  expect(continued.system.join("\n")).toContain("do not require the user to repeat an already recorded approval")
  expect(continued.context.join("\n")).not.toContain("Approve only this fixture write.")
  expect((yield* QuantCodeReuse.state(fixture.session.id)).intentHash).toBe(before.intentHash)
  const changed = { ...fixture.user, id: MessageID.ascending() }
  yield* sessions.updateMessage(changed)
  yield* sessions.updatePart({ id: PartID.ascending(), sessionID: fixture.session.id, messageID: changed.id,
    type: "text", text: "Also create a second file with a different purpose." })
  const current = reviewState(yield* load(changed))
  expect(current.action).toBe("task_input")
  expect(current.intent_hash).not.toBe(before.intentHash)
  expect(current.coverage.decision).toBeNull()
  expect(current.coverage.proposal_hash).toBeNull()
}), { config: { formatter: false, lsp: false, mcp: {}, plugin: [] } })

it.instance("fresh native write captures final result before receipt and replay keeps original bytes", () => Effect.gen(function* () {
  const fixture = yield* setup
  const first = yield* fixture.invoke()
  expect(first.metadata.truncated).toBe(true)
  const captured = yield* QuantCodeArtifacts.collect(fixture.session.id)
  expect(captured.artifacts).toHaveLength(1)
  const artifact = captured.artifacts[0]
  expect(artifact.capture_status).toBe("available")
  expect(artifact.sha256).toBe(createHash("sha256").update(fixture.args.content).digest("hex"))
  const bytes = yield* Effect.promise(() => QuantCodeArtifacts.content(artifact, captured.inline, 0))
  expect(bytes.delivery_status).toBe("available")
  expect("content" in bytes && Buffer.from(bytes.content!, "base64").toString()).toBe(fixture.args.content)
  const events = yield* fixture.database.db.select().from(EventTable).where(eq(EventTable.aggregate_id, fixture.session.id)).orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
  const snapshot = events.find(event => event.type === "quantcode.artifacts.captured.1")!
  const completed = events.find(event => event.type === "quantcode.write.completed.1")!
  expect(snapshot.seq).toBeLessThan(completed.seq)
  expect(snapshot.data.result_digest).toBe(completed.data.result_digest)
  expect(completed.data.result_digest).toBe(QuantCodeToolCatalog.digest(first))
  yield* Effect.promise(() => writeFile(fixture.filepath, "Subsequent different workspace bytes\n"))
  const replayed = yield* fixture.invoke()
  expect(replayed).toEqual(first)
  expect(fixture.formatted()).toBe(1)
  expect(yield* Effect.promise(() => readFile(fixture.filepath, "utf8"))).toBe("Subsequent different workspace bytes\n")
  const replay = yield* QuantCodeArtifacts.collect(fixture.session.id)
  expect(replay.artifacts).toEqual(captured.artifacts)
  expect(yield* Effect.promise(() => QuantCodeArtifacts.content(replay.artifacts[0], replay.inline, 0))).toEqual(bytes)
}), { config: { formatter: false, lsp: false, mcp: {}, plugin: [] } })

it.instance("legacy completed receipt without capture never invents original bytes on replay", () => Effect.gen(function* () {
  const fixture = yield* setup
  yield* QuantCodeWritePolicy.guarded(fixture.session.id, [fixture.filepath], admitted => QuantCodeWriteReceipt.run({
    sessionID: fixture.session.id, messageID: fixture.assistant.id, callID: fixture.callID, tool: "write", args: fixture.args,
    files: admitted.files, planHashes: admitted.planHashes,
  }, begin => Effect.gen(function* () {
    yield* begin
    yield* Effect.promise(() => writeFile(fixture.filepath, fixture.args.content))
    return { title: "artifact.txt", output: "Old recorded write result", metadata: {
      artifacts: [{ path: fixture.filepath, name: "artifact.txt", mime: "text/plain", kind: "artifact" }],
      quantcodeWrite: { files: admitted.files, planHashes: admitted.planHashes },
    } }
  })))
  yield* Effect.promise(() => writeFile(fixture.filepath, "Only current bytes remain\n"))
  yield* fixture.invoke()
  const captured = yield* QuantCodeArtifacts.collect(fixture.session.id)
  expect(captured.artifacts).toHaveLength(1)
  expect(captured.artifacts[0]).toMatchObject({ capture_status: "unavailable", unavailable_reason: "original_not_captured" })
  expect(yield* Effect.promise(() => QuantCodeArtifacts.content(captured.artifacts[0], captured.inline, 0))).toEqual({ delivery_status: "unavailable", next_offset: null })
  expect(yield* Effect.promise(() => readFile(fixture.filepath, "utf8"))).toBe("Only current bytes remain\n")
}), { config: { formatter: false, lsp: false, mcp: {}, plugin: [] } })

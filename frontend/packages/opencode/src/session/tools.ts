import { QuantCodeToolCatalog } from "@/quantcode/tool-catalog"
import { QuantCodeWritePolicy } from "@/quantcode/write-policy"
import { QuantCodeReuse } from "@/quantcode/reuse"
import { EventV2Bridge } from "@/event-v2-bridge"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeTaskLock } from "@/quantcode/task-lock"
import { QuantCodeWriteReceipt } from "@/quantcode/write-receipt"
import { QuantCodeBudget } from "@/quantcode/budget"
import { QuantCodeMcpContext } from "@/quantcode/mcp-context"
import { QuantCodeGate } from "@/quantcode/gate"
import { QuantCodeArtifacts } from "@/quantcode/artifacts"
import { createHash } from "node:crypto"
import { Database } from "@opencode-ai/core/database/database"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { Agent } from "@/agent/agent"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import { Provider } from "@/provider/provider"
import { ProviderTransform } from "@/provider/transform"
import { MCP } from "@/mcp"
import { Permission } from "@/permission"
import { Tool } from "@/tool/tool"
import { ToolJsonSchema } from "@/tool/json-schema"
import { ToolRegistry } from "@/tool/registry"
import { Truncate } from "@/tool/truncate"

import { Plugin } from "@/plugin"
import type { TaskPromptOps } from "@/tool/task"
import { type Tool as AITool, tool, jsonSchema, type ToolExecutionOptions, asSchema } from "ai"
import { Effect, Option, Schema } from "effect"
import { MessageV2 } from "./message-v2"
import { Session } from "./session"
import { SessionProcessor } from "./processor"
import { PartID } from "./schema"
import { EffectBridge } from "@/effect/bridge"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { ModelV2 } from "@opencode-ai/core/model"
import { isRecord } from "@/util/record"

const MCP_RESOURCE_TOOLS = {
  list: "list_mcp_resources",
  listTemplates: "list_mcp_resource_templates",
  read: "read_mcp_resource",
} as const
const MAX_MCP_RESOURCE_BLOB_BYTES = 10 * 1024 * 1024
const SUPPORTED_MCP_RESOURCE_ATTACHMENT_MIMES = new Set([
  "application/pdf",
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
])

export const resolve = Effect.fn("SessionTools.resolve")(function* (input: {
  agent: Agent.Info
  model: Provider.Model
  session: Session.Info
  processor: Pick<SessionProcessor.Handle, "message" | "updateToolCall" | "completeToolCall">
  bypassAgentCheck: boolean
  messages: SessionV1.WithParts[]
  promptOps: TaskPromptOps
}) {
  const tools: Record<string, AITool> = {}
  const run = yield* EffectBridge.make()
  const plugin = yield* Plugin.Service
  const permission = yield* Permission.Service
  const registry = yield* ToolRegistry.Service
  const mcp = yield* MCP.Service
  const truncate = yield* Truncate.Service
  const database = yield* Database.Service
  const events = yield* EventV2Bridge.Service
  const processes = yield* AppProcess.Service

  const validateIdentity = Effect.fn("SessionTools.quantcodeIdentity")(function* () {
    if (!QuantCodeIdentity.enabled()) return
    const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
    QuantCodeIdentity.requireOwner(input.session.metadata, current)
  })
  yield* validateIdentity()

  const context = (args: Record<string, unknown>, options: ToolExecutionOptions): Tool.Context => ({
    sessionID: input.session.id,
    abort: options.abortSignal!,
    messageID: input.processor.message.id,
    callID: options.toolCallId,
    extra: { model: input.model, bypassAgentCheck: input.bypassAgentCheck, promptOps: input.promptOps },
    agent: input.agent.name,
    messages: input.messages,
    metadata: (val) =>
      input.processor.updateToolCall(options.toolCallId, (match) => {
        if (!["running", "pending"].includes(match.state.status)) return match
        return {
          ...match,
          state: {
            title: val.title,
            metadata: val.metadata,
            status: "running",
            input: args,
            time: { start: Date.now() },
          },
        }
      }),
    ask: (req) =>
      permission
        .ask({
          ...req,
          sessionID: input.session.id,
          tool: { messageID: input.processor.message.id, callID: options.toolCallId },
          ruleset: Permission.merge(input.agent.permission, input.session.permission ?? []),
        })
        .pipe(Effect.orDie),
  })

  for (const item of yield* registry.tools({
    modelID: ModelV2.ID.make(input.model.api.id),
    providerID: input.model.providerID,
    agent: input.agent,
  })) {
    const schema = ProviderTransform.schema(input.model, ToolJsonSchema.fromTool(item))
    tools[item.id] = tool({
      description: item.description,
      inputSchema: jsonSchema(schema),
      execute(args, options) {
        return run.promise(
          Effect.gen(function* () {
            const ctx = context(args, options)
            yield* plugin.trigger(
              "tool.execute.before",
              { tool: item.id, sessionID: ctx.sessionID, callID: ctx.callID },
              { args },
            )
            yield* validateIdentity()
            const result = yield* item.execute(args, ctx)
            yield* validateIdentity()
            if (QuantCodeIdentity.enabled()) yield* QuantCodeArtifacts.capture({ sessionID: ctx.sessionID,
              messageID: ctx.messageID, callID: options.toolCallId, result }).pipe(
              Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events))
            const output = {
              ...result,
              attachments: result.attachments?.map((attachment) => ({
                ...attachment,
                id: PartID.ascending(),
                sessionID: ctx.sessionID,
                messageID: input.processor.message.id,
              })),
            }
            yield* plugin.trigger(
              "tool.execute.after",
              { tool: item.id, sessionID: ctx.sessionID, callID: ctx.callID, args },
              output,
            )
            if (options.abortSignal?.aborted) {
              yield* input.processor.completeToolCall(options.toolCallId, output)
            }
            return output
          }),
        )
      },
    })
  }

  const hasMcpResourceServer = Object.values(yield* mcp.clients()).some(
    (client) => !!client.getServerCapabilities()?.resources,
  )
  if (hasMcpResourceServer) {
    tools[MCP_RESOURCE_TOOLS.list] = tool({
      description:
        "Lists resources provided by connected MCP servers. Resources provide context such as files, database schemas, or application-specific information.",
      inputSchema: jsonSchema(
        ProviderTransform.schema(input.model, {
          type: "object",
          properties: {
            server: {
              type: "string",
              description: "Optional MCP server name. When omitted, lists resources from every connected server.",
            },
          },
          additionalProperties: false,
        }),
      ),
      execute(args, opts) {
        return run.promise(
          Effect.gen(function* () {
            const parsed = parseListMcpResourcesArgs(args)
            const ctx = context(toRecord(args), opts)
            const clients = yield* mcp.clients()
            const resourceServers = Object.entries(clients)
              .filter((entry) => !!entry[1].getServerCapabilities()?.resources)
              .map((entry) => entry[0])
              .sort((a, b) => a.localeCompare(b))
            if (parsed.server && !resourceServers.includes(parsed.server)) {
              throw new Error(
                resourceServers.length === 0
                  ? `MCP server "${parsed.server}" does not support resources`
                  : `MCP server "${parsed.server}" does not support resources. Available resource servers: ${resourceServers.join(", ")}`,
              )
            }
            const permissionPatterns = parsed.server
              ? [`mcp:${parsed.server}:*`]
              : resourceServers.map((server) => `mcp:${server}:*`)
            yield* plugin.trigger(
              "tool.execute.before",
              { tool: MCP_RESOURCE_TOOLS.list, sessionID: ctx.sessionID, callID: opts.toolCallId },
              { args },
            )
            yield* ctx.ask({
              permission: "read",
              metadata: parsed.server ? { server: parsed.server } : {},
              patterns: permissionPatterns,
              always: permissionPatterns,
            })

            yield* validateIdentity()
            const resources = Object.values(yield* mcp.resources(parsed.server))
            const filtered = resources
              .filter((resource) => !parsed.server || resource.client === parsed.server)
              .toSorted((a, b) =>
                (a.client + "\u0000" + a.name + "\u0000" + a.uri).localeCompare(
                  b.client + "\u0000" + b.name + "\u0000" + b.uri,
                ),
              )
            const content = JSON.stringify({ resources: filtered.map(formatMcpResource) }, null, 2)
            const truncated = yield* truncate.output(content, {}, input.agent)
            const output = {
              title: parsed.server ? `MCP resources: ${parsed.server}` : "MCP resources",
              metadata: {
                count: filtered.length,
                servers: resourceServers,
                ...(parsed.server ? { server: parsed.server } : {}),
                truncated: truncated.truncated,
                ...(truncated.truncated && { outputPath: truncated.outputPath }),
              },
              output: truncated.content,
            }
            yield* plugin.trigger(
              "tool.execute.after",
              { tool: MCP_RESOURCE_TOOLS.list, sessionID: ctx.sessionID, callID: opts.toolCallId, args },
              output,
            )
            if (opts.abortSignal?.aborted) {
              yield* input.processor.completeToolCall(opts.toolCallId, output)
            }
            return output
          }),
        )
      },
    })

    tools[MCP_RESOURCE_TOOLS.listTemplates] = tool({
      description:
        "Lists resource templates provided by connected MCP servers. Resource templates are parameterized resources that can be read after filling in their URI template.",
      inputSchema: jsonSchema(
        ProviderTransform.schema(input.model, {
          type: "object",
          properties: {
            server: {
              type: "string",
              description:
                "Optional MCP server name. When omitted, lists resource templates from every connected server.",
            },
          },
          additionalProperties: false,
        }),
      ),
      execute(args, opts) {
        return run.promise(
          Effect.gen(function* () {
            const parsed = parseListMcpResourcesArgs(args)
            const ctx = context(toRecord(args), opts)
            const clients = yield* mcp.clients()
            const resourceServers = Object.entries(clients)
              .filter((entry) => !!entry[1].getServerCapabilities()?.resources)
              .map((entry) => entry[0])
              .sort((a, b) => a.localeCompare(b))
            if (parsed.server && !resourceServers.includes(parsed.server)) {
              throw new Error(
                resourceServers.length === 0
                  ? `MCP server "${parsed.server}" does not support resources`
                  : `MCP server "${parsed.server}" does not support resources. Available resource servers: ${resourceServers.join(", ")}`,
              )
            }
            const permissionPatterns = parsed.server
              ? [`mcp:${parsed.server}:*`]
              : resourceServers.map((server) => `mcp:${server}:*`)
            yield* plugin.trigger(
              "tool.execute.before",
              { tool: MCP_RESOURCE_TOOLS.listTemplates, sessionID: ctx.sessionID, callID: opts.toolCallId },
              { args },
            )
            yield* ctx.ask({
              permission: "read",
              metadata: parsed.server ? { server: parsed.server } : {},
              patterns: permissionPatterns,
              always: permissionPatterns,
            })

            const templates = Object.values(yield* mcp.resourceTemplates(parsed.server))
            const filtered = templates
              .filter((template) => !parsed.server || template.client === parsed.server)
              .toSorted((a, b) =>
                (a.client + "\u0000" + a.name + "\u0000" + a.uriTemplate).localeCompare(
                  b.client + "\u0000" + b.name + "\u0000" + b.uriTemplate,
                ),
              )
            const content = JSON.stringify({ resourceTemplates: filtered.map(formatMcpResourceTemplate) }, null, 2)
            const truncated = yield* truncate.output(content, {}, input.agent)
            const output = {
              title: parsed.server ? `MCP resource templates: ${parsed.server}` : "MCP resource templates",
              metadata: {
                count: filtered.length,
                servers: resourceServers,
                ...(parsed.server ? { server: parsed.server } : {}),
                truncated: truncated.truncated,
                ...(truncated.truncated && { outputPath: truncated.outputPath }),
              },
              output: truncated.content,
            }
            yield* plugin.trigger(
              "tool.execute.after",
              { tool: MCP_RESOURCE_TOOLS.listTemplates, sessionID: ctx.sessionID, callID: opts.toolCallId, args },
              output,
            )
            if (opts.abortSignal?.aborted) {
              yield* input.processor.completeToolCall(opts.toolCallId, output)
            }
            return output
          }),
        )
      },
    })

    tools[MCP_RESOURCE_TOOLS.read] = tool({
      description:
        "Read a specific resource from an MCP server using the server name and resource URI. The URI is an MCP identifier and does not need to be a file URL.",
      inputSchema: jsonSchema(
        ProviderTransform.schema(input.model, {
          type: "object",
          properties: {
            server: {
              type: "string",
              description: "MCP server name exactly as returned by list_mcp_resources.",
            },
            uri: {
              type: "string",
              description: "Resource URI to read. Use the exact URI string returned by list_mcp_resources.",
            },
          },
          required: ["server", "uri"],
          additionalProperties: false,
        }),
      ),
      execute(args, opts) {
        return run.promise(
          Effect.gen(function* () {
            const parsed = parseReadMcpResourceArgs(args)
            const ctx = context(toRecord(args), opts)
            const clients = yield* mcp.clients()
            const client = clients[parsed.server]
            if (!client) {
              throw new Error(`MCP server "${parsed.server}" is not connected`)
            }
            if (!client.getServerCapabilities()?.resources) {
              throw new Error(`MCP server "${parsed.server}" does not support resources`)
            }
            yield* plugin.trigger(
              "tool.execute.before",
              { tool: MCP_RESOURCE_TOOLS.read, sessionID: ctx.sessionID, callID: opts.toolCallId },
              { args },
            )
            yield* ctx.ask({
              permission: "read",
              metadata: { server: parsed.server, uri: parsed.uri },
              patterns: [`mcp:${parsed.server}:${parsed.uri}`],
              always: [`mcp:${parsed.server}:*`],
            })

            const content = yield* mcp.readResource(parsed.server, parsed.uri)
            if (!content) throw new Error(`Failed to read MCP resource: ${parsed.server}/${parsed.uri}`)

            const formatted = formatMcpResourceContent(parsed.server, parsed.uri, content)
            const truncated = yield* truncate.output(formatted.text, {}, input.agent)
            const output = {
              title: `MCP resource: ${parsed.uri}`,
              metadata: {
                server: parsed.server,
                uri: parsed.uri,
                contents: formatted.contents,
                attachments: formatted.attachments.length,
                truncated: truncated.truncated,
                ...(truncated.truncated && { outputPath: truncated.outputPath }),
              },
              output: truncated.content,
              attachments: formatted.attachments.map((attachment) => ({
                ...attachment,
                id: PartID.ascending(),
                sessionID: ctx.sessionID,
                messageID: input.processor.message.id,
              })),
            }
            yield* plugin.trigger(
              "tool.execute.after",
              { tool: MCP_RESOURCE_TOOLS.read, sessionID: ctx.sessionID, callID: opts.toolCallId, args },
              output,
            )
            if (opts.abortSignal?.aborted) {
              yield* input.processor.completeToolCall(opts.toolCallId, output)
            }
            return output
          }),
        )
      },
    })
  }

  for (const [key, definition] of Object.entries(yield* mcp.tools())) {
    const origin = QuantCodeToolCatalog.origin(definition)
    const item = { ...definition }
    const execute = item.execute
    if (!execute) continue

    const schema = yield* Effect.promise(() => Promise.resolve(asSchema(item.inputSchema).jsonSchema))
    const transformed = ProviderTransform.schema(input.model, { ...schema, properties: schema.properties ?? {} })
    item.inputSchema = jsonSchema(transformed)
    item.execute = (args, opts) =>
      run.promise(
        Effect.gen(function* () {
          const ctx = context(args, opts)
          yield* plugin.trigger(
            "tool.execute.before",
            { tool: key, sessionID: ctx.sessionID, callID: opts.toolCallId },
            { args },
          )
          const result: Awaited<ReturnType<NonNullable<typeof execute>>> = yield* Effect.gen(function* () {
            yield* validateIdentity()
            const callArgs = QuantCodeIdentity.enabled() ? structuredClone(args) : args
            const call = (native?: QuantCodeMcpContext.NativeCall, revalidate?: Effect.Effect<void>) => Effect.gen(function* () {
              const response = yield* Effect.promise(() => execute(callArgs, native ? QuantCodeMcpContext.bind(opts, native) : opts))
              if (native) {
                yield* (revalidate ?? validateIdentity())
                // Capture only the bytes returned by a fresh component call.
                // Receipt replay skips this boundary and never reopens old paths.
                yield* QuantCodeArtifacts.capture({ sessionID: ctx.sessionID, messageID: ctx.messageID,
                  callID: opts.toolCallId, result: response, fresh: true }).pipe(
                  Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events))
              }
              return response
            })
            if (!QuantCodeIdentity.enabled()) {
              yield* ctx.ask({ permission: key, metadata: {}, patterns: ["*"], always: ["*"] })
              return yield* call()
            }
            if (!origin) throw new Error("工具缺少可信 MCP 来源记录。")
            const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
            const admission = yield* Effect.promise(() => QuantCodeToolCatalog.allowed(origin, identity))
            if (!admission) throw new Error("该 MCP 工具未发布或不在当前身份权限范围内。")
            if (Permission.evaluate(key, "*", input.agent.permission, input.session.permission ?? []).action === "deny") {
              throw new Error("当前任务明确禁止此工具，组织审批不能覆盖该拒绝。")
            }
            const argumentsJson = JSON.stringify(callArgs)
            const argumentsDigest = createHash("sha256").update(argumentsJson).digest("hex")
            const native: QuantCodeMcpContext.NativeCall = { version: 1, server: origin.server, login_session_id: identity.session_id,
              native_session_id: ctx.sessionID, root_session_id: QuantCodeIdentity.requireOwner(input.session.metadata, identity).root_session_id,
              message_id: ctx.messageID, call_id: opts.toolCallId, catalog_digest: admission.digest,
              arguments_json: argumentsJson, arguments_digest: argumentsDigest }
            if (["shared_write", "restricted_access"].includes(admission.entry.effect)) {
              const shared = admission.entry.effect === "shared_write"
              const initialScope = shared ? yield* QuantCodeWritePolicy.scope(ctx.sessionID,
                QuantCodeToolCatalog.paths(admission.entry, callArgs), false, admission.entry.capability_id, true).pipe(
                Effect.provideService(Database.Service, database), Effect.provideService(AppProcess.Service, processes)) : undefined
              const resource = shared ? QuantCodeToolCatalog.resource(admission.entry, callArgs) : { resource: `${origin.server}/${origin.tool}`, version: undefined }
              const intent = yield* QuantCodeReuse.capture(ctx.sessionID)
              const expires = Date.now() + 10 * 60_000
              const digest = QuantCodeToolCatalog.digest({ intent, args: callArgs, catalog: admission.digest,
                session: ctx.sessionID, message: input.processor.message.id, call: opts.toolCallId, resource,
                planHashes: initialScope?.planHashes })
              if (Buffer.byteLength(argumentsJson) > 8192) throw new Error("审批参数过大，请缩小请求后再申请。")
              const description = shared ? "按已冻结方案写入共享资源；审批仅适用于所列完整参数和预期版本。" : "申请读取已发布的受限资源；审批仅适用于所列完整参数。"
              const revalidate = () => run.run(Effect.gen(function* () {
                yield* validateIdentity()
                const current = yield* QuantCodeReuse.capture(ctx.sessionID)
                if (QuantCodeToolCatalog.digest(current) !== QuantCodeToolCatalog.digest(intent) || opts.abortSignal?.aborted || Date.now() >= expires) {
                  throw new Error("待审批操作的任务、身份或执行状态已变化。")
                }
                if (shared) {
                  const scope = yield* QuantCodeWritePolicy.scope(ctx.sessionID, initialScope!.files, false, admission.entry.capability_id, true)
                    .pipe(Effect.provideService(Database.Service, database), Effect.provideService(AppProcess.Service, processes))
                  if (JSON.stringify(scope.planHashes) !== JSON.stringify(initialScope!.planHashes)) throw new Error("审批期间方案已变更，请重新申请。")
                }
                yield* Effect.promise(() => QuantCodeToolCatalog.revalidate(origin, identity, admission))
              }))
              const approval = yield* permission.askExact({ sessionID: ctx.sessionID,
                tool: { messageID: input.processor.message.id, callID: opts.toolCallId },
                kind: shared ? "merge" : "permission", resource: resource.resource, resourceVersion: resource.version, digest,
                description, server: origin.server, toolName: origin.tool, catalogDigest: admission.digest,
                argumentsJson, argumentsDigest, revalidate,
              }).pipe(Effect.orDie)
              return yield* QuantCodeTaskLock.guard(ctx.sessionID, Effect.gen(function* () {
                yield* revalidate()
                const gate = yield* QuantCodeGate.read(approval.gateID, identity.session_id)
                if (!gate.valid || gate.status !== "approved" || gate.record_digest !== approval.recordDigest ||
                    gate.request.operation_digest !== digest || gate.request.arguments_digest !== argumentsDigest) throw new Error("执行前审批已失效。")
                const context = { ...native, gate_id: approval.gateID, operation_digest: digest }
                const result = shared ? yield* QuantCodeWriteReceipt.run({ sessionID: ctx.sessionID, messageID: ctx.messageID,
                  callID: opts.toolCallId, tool: key, args: callArgs, files: initialScope!.files, planHashes: initialScope!.planHashes, catalog: admission.digest,
                }, begin => Effect.gen(function* () {
                  opts.abortSignal?.throwIfAborted()
                  yield* begin
                  return yield* call(context, revalidate())
                })).pipe(Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events)) : yield* call(context, revalidate())
                yield* revalidate()
                return result
              })).pipe(Effect.provideService(Database.Service, database))
            }
            yield* ctx.ask({ permission: key, metadata: {}, patterns: ["*"], always: ["*"] })
            yield* validateIdentity()
            yield* Effect.promise(() => QuantCodeToolCatalog.revalidate(origin, identity, admission))
            const checkResult = validateIdentity().pipe(Effect.andThen(
              Effect.promise(() => QuantCodeToolCatalog.revalidate(origin, identity, admission))))
            const inspection = admission.entry.purpose !== "ordinary" ? yield* QuantCodeReuse.capture(ctx.sessionID) : undefined
            const response = admission.entry.effect === "personal_write"
              ? yield* QuantCodeWritePolicy.guarded(ctx.sessionID, QuantCodeToolCatalog.paths(admission.entry, callArgs), admitted => QuantCodeWriteReceipt.run({
                  sessionID: ctx.sessionID, messageID: ctx.messageID, callID: opts.toolCallId, tool: key, args: callArgs,
                  files: admitted.files, planHashes: admitted.planHashes, catalog: admission.digest,
                }, begin => Effect.gen(function* () {
                  yield* ctx.metadata({ metadata: { quantcodeWrite: { files: admitted.files, planHashes: admitted.planHashes }, catalog: admission.digest } })
                  yield* Effect.promise(() => QuantCodeToolCatalog.revalidate(origin, identity, admission))
                  opts.abortSignal?.throwIfAborted()
                  yield* begin
                  return yield* call(native, checkResult)
                })), false, admission.entry.capability_id).pipe(Effect.provideService(Database.Service, database), Effect.provideService(AppProcess.Service, processes), Effect.provideService(EventV2Bridge.Service, events))
              : yield* call(native, checkResult)
            yield* validateIdentity()
            yield* Effect.promise(() => QuantCodeToolCatalog.revalidate(origin, identity, admission))
            if (inspection) yield* QuantCodeReuse.observe(ctx.sessionID, opts.toolCallId, admission, response, inspection).pipe(
              Effect.provideService(EventV2Bridge.Service, events),
              Effect.provideService(Database.Service, database),
            )
            return response
          }).pipe(
            Effect.withSpan("Tool.execute", {
              attributes: {
                "tool.name": key,
                "tool.call_id": opts.toolCallId,
                "session.id": ctx.sessionID,
                "message.id": input.processor.message.id,
              },
            }),
          )
          if (QuantCodeIdentity.enabled()) yield* QuantCodeArtifacts.capture({ sessionID: ctx.sessionID,
            messageID: ctx.messageID, callID: opts.toolCallId, result }).pipe(
            Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events))
          yield* plugin.trigger(
            "tool.execute.after",
            { tool: key, sessionID: ctx.sessionID, callID: opts.toolCallId, args },
            result,
          )

          const textParts: string[] = []
          const attachments: Omit<SessionV1.FilePart, "id" | "sessionID" | "messageID">[] = []
          for (const contentItem of result.content) {
            if (contentItem.type === "text") textParts.push(contentItem.text)
            else if (contentItem.type === "image") {
              attachments.push({
                type: "file",
                mime: contentItem.mimeType,
                url: `data:${contentItem.mimeType};base64,${contentItem.data}`,
              })
            } else if (contentItem.type === "resource") {
              const { resource } = contentItem
              if (resource.text) textParts.push(resource.text)
              if (resource.blob) {
                const mime = resource.mimeType ?? "application/octet-stream"
                const size = base64Size(resource.blob)
                if (!SUPPORTED_MCP_RESOURCE_ATTACHMENT_MIMES.has(mime)) {
                  textParts.push(
                    `[Binary MCP resource omitted: ${resource.uri} (${mime}, ${formatBytes(size)}) is not a supported attachment type]`,
                  )
                  continue
                }
                if (size > MAX_MCP_RESOURCE_BLOB_BYTES) {
                  textParts.push(
                    `[Binary MCP resource omitted: ${resource.uri} (${mime}, ${formatBytes(size)}) exceeds ${formatBytes(MAX_MCP_RESOURCE_BLOB_BYTES)}]`,
                  )
                  continue
                }
                attachments.push({
                  type: "file",
                  mime,
                  url: `data:${mime};base64,${resource.blob}`,
                  filename: resource.uri,
                })
              }
            }
          }

          const truncated = yield* truncate.output(textParts.join("\n\n"), {}, input.agent)
          const structured = isRecord(result.structuredContent) ? result.structuredContent
            : Option.getOrUndefined(Schema.decodeUnknownOption(Schema.UnknownFromJsonString)(textParts.join("\n\n")))
          const payload = isRecord(structured) ? structured : {}
          const resultStatus = String(payload.result_status ?? payload.status ?? "").toLowerCase()
          const metadata = {
            ...result.metadata,
            ...(QuantCodeIdentity.enabled() ? { quantcodeResult: {
              successful: result.isError !== true && !payload.error && payload.success !== false &&
                (!resultStatus || ["ok", "success", "succeeded", "completed", "available", "connected", "implemented"].includes(resultStatus)) &&
                !["mock", "proxy", "staging"].includes(String(payload.environment ?? payload.source ?? "").toLowerCase()),
              status: resultStatus,
            } } : {}),
            truncated: truncated.truncated,
            ...(truncated.truncated && { outputPath: truncated.outputPath }),
          }

          const output = {
            title: "",
            metadata,
            output: truncated.content,
            attachments: attachments.map((attachment) => ({
              ...attachment,
              id: PartID.ascending(),
              sessionID: ctx.sessionID,
              messageID: input.processor.message.id,
            })),
            content: result.content,
          }
          if (opts.abortSignal?.aborted) {
            yield* input.processor.completeToolCall(opts.toolCallId, output)
          }
          return output
        }),
      )
    tools[key] = item
  }

  if (QuantCodeIdentity.enabled()) {
    for (const [name, definition] of Object.entries(tools)) {
      const execute = definition.execute
      if (!execute) continue
      tools[name] = { ...definition, execute: async (args, options) => {
        options.abortSignal?.throwIfAborted()
        await run.promise(validateIdentity())
        await run.promise(QuantCodeBudget.check(input.session.id).pipe(Effect.provideService(Database.Service, database)))
        const result = await execute(args, options)
        await run.promise(validateIdentity())
        return result
      } }
    }
  }
  return tools
})

function toRecord(value: unknown) {
  if (isRecord(value)) return value
  return {}
}

function parseListMcpResourcesArgs(value: unknown) {
  const args = toRecord(value)
  return { server: optionalString(args, "server") }
}

function parseReadMcpResourceArgs(value: unknown) {
  const args = toRecord(value)
  return { server: requiredString(args, "server"), uri: requiredString(args, "uri") }
}

function optionalString(args: Record<string, unknown>, key: string) {
  const value = args[key]
  if (value === undefined || value === null || value === "") return undefined
  if (typeof value !== "string") throw new Error(`${key} must be a string`)
  return value
}

function requiredString(args: Record<string, unknown>, key: string) {
  const value = optionalString(args, key)
  if (value) return value
  throw new Error(`${key} is required`)
}

function formatMcpResource(resource: MCP.Resource) {
  const result = Object.fromEntries(Object.entries(resource).filter((entry) => entry[0] !== "client"))
  return { ...result, server: resource.client }
}

function formatMcpResourceTemplate(template: Record<string, unknown> & { client: string }) {
  const result = Object.fromEntries(Object.entries(template).filter((entry) => entry[0] !== "client"))
  return { ...result, server: template.client }
}

function formatMcpResourceContent(server: string, uri: string, content: { contents: unknown }) {
  const items = (Array.isArray(content.contents) ? content.contents : [content.contents]).filter(isRecord)
  const text: string[] = []
  const attachments: Omit<SessionV1.FilePart, "id" | "sessionID" | "messageID">[] = []

  for (const item of items) {
    const itemUri = typeof item.uri === "string" ? item.uri : uri
    const mime = typeof item.mimeType === "string" ? item.mimeType : "application/octet-stream"
    if (typeof item.text === "string") {
      text.push(`Resource: ${itemUri}\nMIME: ${mime}\n${item.text}`)
      continue
    }
    if (typeof item.blob === "string") {
      const size = base64Size(item.blob)
      if (!SUPPORTED_MCP_RESOURCE_ATTACHMENT_MIMES.has(mime)) {
        text.push(
          `[Binary MCP resource omitted: ${itemUri} (${mime}, ${formatBytes(size)}) is not a supported attachment type]`,
        )
        continue
      }
      if (size > MAX_MCP_RESOURCE_BLOB_BYTES) {
        text.push(
          `[Binary MCP resource omitted: ${itemUri} (${mime}, ${formatBytes(size)}) exceeds ${formatBytes(MAX_MCP_RESOURCE_BLOB_BYTES)}]`,
        )
        continue
      }
      text.push(`[Binary MCP resource attached: ${itemUri} (${mime})]`)
      attachments.push({
        type: "file",
        mime,
        url: `data:${mime};base64,${item.blob}`,
        filename: itemUri,
      })
      continue
    }
    text.push(`[MCP resource content without text or blob: ${itemUri}]`)
  }

  return {
    contents: items.length,
    attachments,
    text: text.join("\n\n") || `MCP resource ${uri} from ${server} returned no contents.`,
  }
}

function base64Size(value: string) {
  const trimmed = value.replace(/\s/g, "")
  const padding = trimmed.endsWith("==") ? 2 : trimmed.endsWith("=") ? 1 : 0
  return Math.max(0, Math.floor((trimmed.length * 3) / 4) - padding)
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.ceil(value / 1024)} KB`
  return `${Math.ceil(value / (1024 * 1024))} MB`
}

export * as SessionTools from "./tools"

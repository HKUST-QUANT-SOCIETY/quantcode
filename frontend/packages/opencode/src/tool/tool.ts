import { Database } from "@opencode-ai/core/database/database"
import { AppProcess } from "@opencode-ai/core/process"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWritePolicy } from "@/quantcode/write-policy"
import { QuantCodeWriteReceipt } from "@/quantcode/write-receipt"
import { QuantCodeArtifacts } from "@/quantcode/artifacts"
import { EventV2Bridge } from "@/event-v2-bridge"
import type { EventV2 } from "@opencode-ai/core/event"
import { QuantCodeBudget } from "@/quantcode/budget"
import { PermissionV1 } from "@opencode-ai/core/v1/permission"
import { Effect, Schema } from "effect"
import { SessionV1 } from "@opencode-ai/core/v1/session"
import type { JSONSchema7 } from "@ai-sdk/provider"
import type { MessageV2 } from "../session/message-v2"
import type { Permission } from "../permission"
import type { SessionID, MessageID } from "../session/schema"
import * as Truncate from "./truncate"
import { Agent } from "@/agent/agent"

interface Metadata {
  [key: string]: any
}

// TODO: remove this hack
export type DynamicDescription = (agent: Agent.Info) => Effect.Effect<string>

/**
 * Raised when the LLM calls a tool with arguments that fail the parameter
 * schema. This is the canonical "rewrite the input" tool error: the typed
 * error class makes it matchable upstream, and its `message` getter produces
 * the model-facing prose that the AI SDK feeds back as the tool result.
 */
export class InvalidArgumentsError extends Schema.TaggedErrorClass<InvalidArgumentsError>()(
  "ToolInvalidArgumentsError",
  {
    tool: Schema.String,
    detail: Schema.String,
  },
) {
  override get message() {
    return `The ${this.tool} tool was called with invalid arguments: ${this.detail}.\nPlease rewrite the input so it satisfies the expected schema.`
  }
}

export type Context<M extends Metadata = Metadata> = {
  sessionID: SessionID
  messageID: MessageID
  agent: string
  abort: AbortSignal
  callID?: string
  extra?: { [key: string]: unknown }
  messages: SessionV1.WithParts[]
  metadata(input: { title?: string; metadata?: M }): Effect.Effect<void>
  ask(input: Omit<PermissionV1.Request, "id" | "sessionID" | "tool">): Effect.Effect<void>
}

export interface ExecuteResult<M extends Metadata = Metadata> {
  title: string
  metadata: M
  output: string
  attachments?: Omit<SessionV1.FilePart, "id" | "sessionID" | "messageID">[]
}

export interface Def<
  Parameters extends Schema.Decoder<unknown> = Schema.Decoder<unknown>,
  M extends Metadata = Metadata,
  R = never,
> {
  id: string
  description: string
  parameters: Parameters
  jsonSchema?: JSONSchema7
  execute(args: Schema.Schema.Type<Parameters>, ctx: Context): Effect.Effect<ExecuteResult<M>, never, R>
  formatValidationError?(error: unknown): string
}
export type DefWithoutID<
  Parameters extends Schema.Decoder<unknown> = Schema.Decoder<unknown>,
  M extends Metadata = Metadata,
  R = never,
> = Omit<Def<Parameters, M, R>, "id">

export interface Info<
  Parameters extends Schema.Decoder<unknown> = Schema.Decoder<unknown>,
  M extends Metadata = Metadata,
> {
  id: string
  init: () => Effect.Effect<DefWithoutID<Parameters, M>>
}

type Init<Parameters extends Schema.Decoder<unknown>, M extends Metadata> =
  | DefWithoutID<Parameters, M, Database.Service | AppProcess.Service>
  | (() => Effect.Effect<DefWithoutID<Parameters, M, Database.Service | AppProcess.Service>>)

export type InferParameters<T> =
  T extends Info<infer P, any>
    ? Schema.Schema.Type<P>
    : T extends Effect.Effect<Info<infer P, any>, any, any>
      ? Schema.Schema.Type<P>
      : never
export type InferMetadata<T> =
  T extends Info<any, infer M> ? M : T extends Effect.Effect<Info<any, infer M>, any, any> ? M : never

export type InferDef<T> =
  T extends Info<infer P, infer M>
    ? Def<P, M>
    : T extends Effect.Effect<Info<infer P, infer M>, any, any>
      ? Def<P, M>
      : never

function wrap<Parameters extends Schema.Decoder<unknown>, Result extends Metadata>(
  id: string,
  init: Init<Parameters, Result>,
  truncate: Truncate.Interface,
  agents: Agent.Interface,
  database: Database.Interface,
  processes: AppProcess.Interface,
  events: EventV2.Interface,
) {
  const finalize = (result: ExecuteResult<Result>, agentName: string): Effect.Effect<ExecuteResult<Result>> =>
    Effect.gen(function* () {
      if (result.metadata.truncated !== undefined) return result
      const agent = yield* agents.get(agentName)
      const truncated = yield* truncate.output(result.output, {}, agent)
      return {
        ...result,
        output: truncated.content,
        metadata: {
          ...result.metadata,
          truncated: truncated.truncated,
          ...(truncated.truncated && { outputPath: truncated.outputPath }),
        },
      }
    })
  return () =>
    Effect.gen(function* () {
      const toolInfo = typeof init === "function" ? { ...(yield* init()) } : { ...init }
      // Compile the parser closure once per tool init; `decodeUnknownEffect`
      // allocates a new closure per call, so hoisting avoids re-closing it for
      // every LLM tool invocation.
      const decode = Schema.decodeUnknownEffect(toolInfo.parameters)
      const execute = toolInfo.execute
      const wrappedExecute: Def<Parameters, Result>["execute"] = (args, ctx) => {
        const attrs = {
          "tool.name": id,
          "session.id": ctx.sessionID,
          "message.id": ctx.messageID,
          ...(ctx.callID ? { "tool.call_id": ctx.callID } : {}),
        }
        return Effect.gen(function* () {
          if (QuantCodeIdentity.enabled()) ctx.abort.throwIfAborted()
          yield* QuantCodeBudget.check(ctx.sessionID).pipe(Effect.provideService(Database.Service, database))
          const decoded = yield* decode(args).pipe(
            Effect.mapError(
              (error) =>
                new InvalidArgumentsError({
                  tool: id,
                  detail: toolInfo.formatValidationError ? toolInfo.formatValidationError(error) : String(error),
                }),
            ),
          )
          const result = yield* (QuantCodeIdentity.enabled() && ["write", "edit", "apply_patch"].includes(id)
            ? QuantCodeWritePolicy.guarded(ctx.sessionID, QuantCodeWritePolicy.fileTargets(id, decoded), admitted => QuantCodeWriteReceipt.run({
                sessionID: ctx.sessionID, messageID: ctx.messageID, callID: ctx.callID, tool: id, args: decoded,
                files: admitted.files, planHashes: admitted.planHashes,
              }, begin => Effect.gen(function* () {
                const callID = ctx.callID
                if (!callID) throw new Error("写入必须绑定原生工具调用标识。")
                yield* ctx.metadata({ metadata: { quantcodeWrite: { files: admitted.files, planHashes: admitted.planHashes } } })
                const checkedContext = { ...ctx, ask: (request: Omit<PermissionV1.Request, "id" | "sessionID" | "tool">) => ctx.ask(request).pipe(
                  Effect.andThen(Effect.gen(function* () {
                    ctx.abort.throwIfAborted()
                    const current = yield* QuantCodeWritePolicy.scope(ctx.sessionID, admitted.files)
                    if (JSON.stringify(current.planHashes) !== JSON.stringify(admitted.planHashes)) throw new Error("确认期间方案已变化，请重新执行当前操作。")
                    if (request.permission === "edit") yield* begin
                  })),
                  Effect.provideService(Database.Service, database),
                  Effect.provideService(AppProcess.Service, processes),
                ) }
                const output = yield* execute(decoded as Schema.Schema.Type<Parameters>, checkedContext)
                const result = yield* finalize({ ...output, metadata: { ...output.metadata,
                  quantcodeWrite: { files: admitted.files, planHashes: admitted.planHashes } } }, ctx.agent)
                // Only the real invocation reaches this boundary. The receipt
                // and artifact event share the finalized result on every replay.
                yield* QuantCodeArtifacts.capture({ sessionID: ctx.sessionID, messageID: ctx.messageID,
                  callID, result, fresh: true })
                return result
              }))).pipe(Effect.provideService(Database.Service, database), Effect.provideService(AppProcess.Service, processes), Effect.provideService(EventV2Bridge.Service, events))
            : Effect.suspend(() => execute(decoded as Schema.Schema.Type<Parameters>, ctx)).pipe(Effect.provideService(Database.Service, database), Effect.provideService(AppProcess.Service, processes)))
          return yield* finalize(result, ctx.agent)
        }).pipe(Effect.orDie, Effect.withSpan("Tool.execute", { attributes: attrs }))
      }
      return { ...toolInfo, execute: wrappedExecute }
    })
}

export function define<
  Parameters extends Schema.Decoder<unknown>,
  Result extends Metadata,
  R,
  ID extends string = string,
>(
  id: ID,
  init: Effect.Effect<Init<Parameters, Result>, never, R>,
): Effect.Effect<Info<Parameters, Result>, never, R | Truncate.Service | Agent.Service | Database.Service | AppProcess.Service | EventV2Bridge.Service> & { id: ID } {
  return Object.assign(
    Effect.gen(function* () {
      const resolved = yield* init
      const truncate = yield* Truncate.Service
      const agents = yield* Agent.Service
      const database = yield* Database.Service
      const processes = yield* AppProcess.Service
      const events = yield* EventV2Bridge.Service
      return { id, init: wrap(id, resolved, truncate, agents, database, processes, events) }
    }),
    { id },
  )
}

export function init<P extends Schema.Decoder<unknown>, M extends Metadata>(
  info: Info<P, M>,
): Effect.Effect<Def<P, M>> {
  return Effect.gen(function* () {
    const init = yield* info.init()
    return {
      ...init,
      id: info.id,
    }
  })
}

export * as Tool from "./tool"

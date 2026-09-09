import { Effect, Queue, Schema, Stream } from "effect"
import { z } from "zod"
import { generateText, jsonSchema, tool, type ModelMessage } from "ai"
import { AppProcess } from "@opencode-ai/core/process"
import type { ChildProcess } from "effect/unstable/process"
import { Provider } from "@/provider/provider"
import { LLMAISDK } from "@/session/llm/ai-sdk"
import { QuantCodeBudget } from "./budget"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeWorkspace } from "./workspace"
import { QuantCodeLegacyTools } from "./legacy-tools"

const frame = z.discriminatedUnion("type", [
  QuantCodeLegacyTools.Frame,
  z.object({ type: z.literal("ready"), sequence: z.number().int().positive() }).strict(),
  z.object({ type: z.literal("authorize"), sequence: z.number().int().positive() }).strict(),
  z.object({ type: z.literal("model"), sequence: z.number().int().positive(), request_id: z.string().regex(/^[a-f0-9]{32}$/),
    max_output: z.number().int().positive(),
    messages: z.array(z.object({ type: z.enum(["system", "human", "ai", "tool"]), content: z.string(),
      tool_calls: z.array(z.object({ id: z.string().min(1), name: z.string().min(1), args: z.record(z.string(), z.unknown()), type: z.string().optional() })),
      tool_call_id: z.string().nullable(), name: z.string().nullable() })),
    tools: z.array(z.object({ name: z.string().regex(/^[a-zA-Z0-9_-]+$/), description: z.string(), schema: z.record(z.string(), z.unknown()) })),
  }).strict(),
  z.object({ type: z.literal("result"), result: z.unknown() }).strict(),
])

/** Each model frame is one existing Provider request. The archived graph owns
 * continuation and tools; this transport never executes a tool or admits a task. */
export const run = Effect.fn("QuantCodeLegacyProvider.run")(function* (
  command: ChildProcess.Command, payload: unknown, identity: QuantCodeIdentity.Identity, signal?: AbortSignal,
) {
  return yield* Effect.scoped(Effect.gen(function* () {
    const processes = yield* AppProcess.Service
    const providers = yield* Provider.Service
    const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(identity.workspace_path, "write", identity))
    const authorize = Effect.fn("QuantCodeLegacyProvider.authorize")(function* () {
      const current = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
      if (current.session_id !== identity.session_id ||
          JSON.stringify(QuantCodeIdentity.ownerOf(current)) !== JSON.stringify(QuantCodeIdentity.ownerOf(identity))) {
        throw new QuantCodeIdentity.IdentityError("旧任务恢复期间身份或权限发生变化。")
      }
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
      signal?.throwIfAborted()
    })
    const handle = yield* processes.spawn(command).pipe(Effect.orDie)
    const replies = yield* Queue.make<string>()
    yield* Stream.fromQueue(replies).pipe(Stream.map(value => new TextEncoder().encode(value + "\n")),
      Stream.run(handle.stdin), Effect.forkScoped)
    yield* Queue.offer(replies, JSON.stringify(payload))
    const requested = new Set<string>()
    let sequence = 0
    let selected: Provider.Model | undefined
    let result: unknown
    let receivedResult = false
    const consume = handle.stdout.pipe(Stream.decodeText(), Stream.splitLines, Stream.runForEach(line => Effect.gen(function* () {
      if (Buffer.byteLength(line, "utf8") > 8_000_000) throw new Error("旧执行器模型帧超过宿主限制。")
      const value = frame.parse(Schema.decodeUnknownSync(Schema.UnknownFromJsonString)(line))
      if (receivedResult) throw new Error("旧执行器返回重复的完成结果。")
      if (value.type === "result") {
        result = value.result
        receivedResult = true
        yield* Queue.shutdown(replies)
        return
      }
      if (value.sequence !== sequence + 1) throw new Error("旧执行器模型请求顺序不一致。")
      sequence = value.sequence
      yield* authorize()
      if (value.type === "ready") {
        if (selected) throw new Error("旧执行器重复准备模型连接。")
        const defaults = yield* providers.defaultModel()
        selected = yield* providers.getModel(defaults.providerID, defaults.modelID)
        if (!Number.isSafeInteger(selected.limit.output) || selected.limit.output <= 0) throw new Error("当前模型需要配置有效的输出 token 上限。")
        yield* Queue.offer(replies, JSON.stringify({ sequence, result: {
          provider: selected.providerID, model: selected.id, max_output: selected.limit.output,
        } }))
        return
      }
      if (value.type === "authorize") {
        if (!selected) throw new Error("旧执行器尚未绑定宿主 Provider。")
        yield* Queue.offer(replies, JSON.stringify({ sequence, result: { authorized: true } }))
        return
      }
      if (value.type === "tool") {
        if (!selected) throw new Error("旧执行器尚未绑定宿主 Provider。")
        const result = yield* QuantCodeLegacyTools.run(value, identity, signal)
        yield* authorize()
        yield* Queue.offer(replies, JSON.stringify({ sequence, result }))
        return
      }
      if (!selected || requested.has(value.request_id) || value.max_output > selected.limit.output) throw new Error("旧任务模型请求未获准或已处理。")
      requested.add(value.request_id)
      const model = yield* providers.getModel(selected.providerID, selected.id)
      if (JSON.stringify(model) !== JSON.stringify(selected)) throw new Error("模型设置已变化，请重新核对旧任务检查点。")
      const language = yield* providers.getLanguage(model)
      const messages: ModelMessage[] = value.messages.map(message => {
        if (message.type === "system") return { role: "system", content: message.content }
        if (message.type === "human") return { role: "user", content: message.content }
        if (message.type === "tool") {
          if (!message.tool_call_id || !message.name) throw new Error("旧工具结果缺少原调用标识。")
          return { role: "tool", content: [{ type: "tool-result", toolCallId: message.tool_call_id, toolName: message.name,
            output: { type: "text", value: message.content } }] }
        }
        return { role: "assistant", content: [
          ...(message.content ? [{ type: "text" as const, text: message.content }] : []),
          ...message.tool_calls.map(call => ({ type: "tool-call" as const, toolCallId: call.id, toolName: call.name, input: call.args })),
        ] }
      })
      if (new Set(value.tools.map(item => item.name)).size !== value.tools.length) throw new Error("旧模型请求含重复工具定义。")
      const tools = Object.fromEntries(value.tools.map(item => [item.name, tool({ description: item.description,
        inputSchema: jsonSchema<Record<string, unknown>>(item.schema) })]))
      // No independent endpoint, retries, tool execution or agent stop policy.
      const completion = yield* Effect.promise(abortSignal => generateText({ model: language, messages, tools,
        maxOutputTokens: value.max_output, maxRetries: 0, abortSignal: signal ? AbortSignal.any([signal, abortSignal]) : abortSignal }))
      const usage = QuantCodeBudget.usage(LLMAISDK.usage(completion.totalUsage), model,
        LLMAISDK.providerMetadata(completion.providerMetadata))
      if (!usage) throw new Error("模型未提供实际用量；原任务预留保持未结算，禁止自动重试。")
      // The Python ledger persists the original owner's spend before asking
      // for another authorization, including revocation during this request.
      yield* Queue.offer(replies, JSON.stringify({ sequence, result: { text: completion.text, usage,
        tool_calls: completion.toolCalls.map(call => ({ id: call.toolCallId, name: call.toolName, args: call.input, type: "tool_call" })),
      } }))
    })))
    const watch: Effect.Effect<never> = Effect.gen(function* () {
      while (true) {
        yield* Effect.sleep("2 seconds")
        yield* authorize()
      }
    })
    yield* Effect.raceFirst(Effect.gen(function* () {
      yield* consume.pipe(Effect.orDie)
      const exitCode = yield* handle.exitCode.pipe(Effect.orDie)
      if (exitCode !== 0 || !receivedResult) throw new Error("旧执行器未完整返回；请重新查看检查点和未确认回执。")
    }), watch)
    yield* authorize()
    if (result && typeof result === "object" && "error" in result) throw new Error(String(result.error))
    return result
  }))
})

export * as QuantCodeLegacyProvider from "./legacy-provider"

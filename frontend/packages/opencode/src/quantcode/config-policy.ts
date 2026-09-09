import { z } from "zod"
import { QuantCodeIdentity } from "./identity"
import type { ConfigV1 } from "@opencode-ai/core/v1/config/config"

const model = z.object({ name: z.string().min(1),
  limit: z.object({ context: z.number().int().nonnegative(), input: z.number().int().positive().optional(), output: z.number().int().nonnegative() }).strict().optional(),
  modalities: z.object({ input: z.array(z.enum(["text", "audio", "image", "video", "pdf"])), output: z.array(z.enum(["text", "audio", "image", "video", "pdf"])) }).strict().optional(),
  attachment: z.boolean().optional(), reasoning: z.boolean().optional(), temperature: z.boolean().optional(), tool_call: z.boolean().optional(),
}).strict()
const models = z.record(z.string().min(1), model)
export const validProviderID = (value: string) => /^[a-z0-9][a-z0-9_-]*$/.test(value) && !["constructor", "prototype", "__proto__"].includes(value)

/** Match the SDK's one-trailing-slash removal followed by '/endpoint'.
 * Repeated slashes remain significant API paths. */
export function modelURL(value: unknown) {
  if (typeof value !== "string" || /\{(?:env|file):|\$\{/i.test(value)) return
  try {
    const url = new URL(value)
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) return
    return url.href.endsWith("/") ? url.href : url.href + "/"
  } catch { return }
}

export function credentialMatches(value: { type: string; metadata?: Record<string, string> } | undefined, url: unknown) {
  const target = modelURL(url)
  return !!target && value?.type === "api" && !!value.metadata && modelURL(value.metadata.quantcode_base_url) === target &&
    Object.keys(value.metadata).length === 1
}
const provider = z.object({
  npm: z.literal("@ai-sdk/openai-compatible"), name: z.string().min(1),
  options: z.object({ baseURL: z.string().url().refine(value => {
    const url = new URL(value)
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash &&
      !/\{(?:env|file):|\$\{/i.test(value)
  }) }).strict(),
  models,
}).strict()
const updateSchema = z.object({
  provider: z.record(z.string().refine(validProviderID), provider).optional(),
  model: z.string().optional(), small_model: z.string().optional(),
  disabled_providers: z.array(z.string()).optional(),
}).strict()

/** Use the same contract when loading host provider definitions. A provider ID
 * colliding with a built-in never inherits its transports, environment keys or
 * remote catalog. Unknown executable/credential options fail closed. */
export function connection(value: unknown) {
  const parsed = provider.safeParse(value)
  if (!parsed.success || !Object.keys(parsed.data.models).length || /\{(?:env|file):|\$\{/i.test(JSON.stringify(parsed.data))) return
  return parsed.data
}

/** Config endpoints share connection descriptions, never credential-bearing
 * legacy options. This does not rewrite the host file or the execution source. */
export function publicConfig(value: ConfigV1.Info): ConfigV1.Info {
  if (!QuantCodeIdentity.enabled()) return value
  const providers = Object.fromEntries(Object.entries(value.provider ?? {}).filter(([id]) => validProviderID(id)).map(([id, config]) => {
    const data = config && typeof config === "object" && !Array.isArray(config) ? config as Record<string, unknown> : {}
    const options = data.options && typeof data.options === "object" ? data.options as Record<string, unknown> : {}
    const parsedURL = typeof options.baseURL === "string" ? (() => {
      try { const url = new URL(options.baseURL); return !url.username && !url.password && !url.search && !url.hash ? options.baseURL : undefined } catch { return undefined }
    })() : undefined
    const entries = data.models && typeof data.models === "object" ? data.models as Record<string, unknown> : {}
    return [id, { npm: "@ai-sdk/openai-compatible", name: typeof data.name === "string" ? data.name : id,
      options: { baseURL: parsedURL }, models: Object.fromEntries(Object.entries(entries).map(([modelID, entry]) => {
      const parsed = model.safeParse(entry)
      return [modelID, parsed.success ? parsed.data : { name: modelID }]
    })) }]
  }))
  // Other host config may hold MCP headers/env, server passwords, private
  // instructions or executable paths. The UI has dedicated status endpoints
  // for tools/LSP and needs none of those secrets to render model settings.
  return { provider: providers, model: value.model, small_model: value.small_model,
    disabled_providers: value.disabled_providers, enabled_providers: value.enabled_providers,
    permission: { "*": "ask" }, plugin: [], share: "disabled" }
}

/** The desktop settings surface configures models, not host code execution.
 * MCP commands/plugins, permission defaults, tool paths and shell executables
 * remain operator-owned settings. Admin product role is not a host-shell grant. */
export async function assertUpdate(value: unknown) {
  if (!QuantCodeIdentity.enabled()) return
  await QuantCodeIdentity.currentIdentity()
  const parsed = updateSchema.safeParse(value)
  if (!parsed.success) throw new Error("桌面仅可修改模型连接设置；工具、插件与权限配置由宿主维护员管理。")
  const text = JSON.stringify(parsed.data)
  if (/\{(?:env|file):/i.test(text)) throw new Error("模型设置不能引用宿主环境变量或私有文件。")
}

export * as QuantCodeConfigPolicy from "./config-policy"

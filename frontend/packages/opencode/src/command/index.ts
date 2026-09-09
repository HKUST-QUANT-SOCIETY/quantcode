import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import path from "path"
import { InstanceState } from "@/effect/instance-state"
import { EffectBridge } from "@/effect/bridge"
import type { InstanceContext } from "@/project/instance-context"
import { Effect, Layer, Context, Schema } from "effect"
import { Config } from "@/config/config"
import { MCP } from "../mcp"
import { Skill } from "../skill"
import PROMPT_INITIALIZE from "./template/initialize.txt"
import PROMPT_REVIEW from "./template/review.txt"
import { LegacyEvent } from "@opencode-ai/schema/legacy-event"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace } from "@/quantcode/workspace"

type State = {
  commands: Record<string, Info>
}

export const Event = {
  Executed: LegacyEvent.CommandExecuted,
}

export const Info = Schema.Struct({
  name: Schema.String,
  description: Schema.optional(Schema.String),
  agent: Schema.optional(Schema.String),
  model: Schema.optional(Schema.String),
  source: Schema.optional(Schema.Literals(["command", "mcp", "skill"])),
  // Some command templates are lazy promises from MCP prompt resolution.
  template: Schema.Unknown,
  subtask: Schema.optional(Schema.Boolean),
  hints: Schema.Array(Schema.String),
}).annotate({ identifier: "Command" })

export type Info = Omit<Schema.Schema.Type<typeof Info>, "template"> & { template: Promise<string> | string }

export function hints(template: string) {
  const result: string[] = []
  const numbered = template.match(/\$\d+/g)
  if (numbered) {
    for (const match of [...new Set(numbered)].sort()) result.push(match)
  }
  if (template.includes("$ARGUMENTS")) result.push("$ARGUMENTS")
  return result
}

export const Default = {
  INIT: "init",
  REVIEW: "review",
} as const

export interface Interface {
  readonly get: (name: string) => Effect.Effect<Info | undefined>
  readonly list: () => Effect.Effect<Info[]>
}

export class Service extends Context.Service<Service, Interface>()("@opencode/Command") {}

const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const config = yield* Config.Service
    const mcp = yield* MCP.Service
    const skill = yield* Skill.Service

    const init = Effect.fn("Command.state")(function* (ctx: InstanceContext, metadataOnly = false) {
      const grant = QuantCodeIdentity.enabled()
        ? yield* Effect.promise(() => QuantCodeWorkspace.authorize(ctx.directory)) : undefined
      const cfg = yield* config.get()
      const bridge = yield* EffectBridge.make()
      const commands: Record<string, Info> = {}

      commands[Default.INIT] = {
        name: Default.INIT,
        description: "guided AGENTS.md setup",
        source: "command",
        get template() {
          return PROMPT_INITIALIZE.replace("${path}", grant?.root ?? ctx.worktree)
        },
        hints: hints(PROMPT_INITIALIZE),
      }
      commands[Default.REVIEW] = {
        name: Default.REVIEW,
        description: "review changes [commit|branch|pr], defaults to uncommitted",
        source: "command",
        get template() {
          return PROMPT_REVIEW.replace("${path}", grant?.root ?? ctx.worktree)
        },
        subtask: true,
        hints: hints(PROMPT_REVIEW),
      }

      for (const [name, configured] of Object.entries(cfg.command ?? {})) {
        const command = grant ? structuredClone(configured) : configured
        commands[name] = {
          name,
          agent: command.agent,
          model: command.model,
          description: command.description,
          source: "command",
          get template() {
            if (!grant) return command.template
            return bridge.promise(config.get().pipe(Effect.map(latest => {
              const current = latest.command?.[name]
              if (JSON.stringify(current) !== JSON.stringify(command)) throw new Error("命令定义已变化，请重新选择命令。")
              return current!.template
            })))
          },
          subtask: command.subtask,
          hints: hints(command.template),
        }
      }

      for (const [name, prompt] of Object.entries(yield* mcp.prompts())) {
        if (grant && commands[name]) throw new Error("组织命令与 MCP 提示模板名称冲突，请由维护员调整名称。")
        commands[name] = {
          name,
          source: "mcp",
          description: prompt.description,
          get template() {
            return bridge.promise(
              mcp
                .getPrompt(
                  prompt.client,
                  prompt.name,
                  prompt.arguments
                    ? Object.fromEntries(prompt.arguments.map((argument, i) => [argument.name, `$${i + 1}`]))
                    : {},
                )
                .pipe(
                  Effect.map(
                    (template) => {
                      if (grant && !template) throw new Error("此提示模板已撤销或不可访问，请重新选择命令。")
                      return template?.messages
                        .map((message) => (message.content.type === "text" ? message.content.text : ""))
                        .join("\n") || ""
                    },
                  ),
                ),
            )
          },
          hints: prompt.arguments?.map((_, i) => `$${i + 1}`) ?? [],
        }
      }

      for (const item of yield* skill.all()) {
        if (commands[item.name]) continue
        const dir = item.location === "<built-in>" ? undefined : path.dirname(item.location)
        commands[item.name] = {
          name: item.name,
          description: item.description,
          source: "skill",
          get template() {
            if (grant) return bridge.promise(skill.require(item.name).pipe(Effect.map(current => {
              if (current.location !== item.location || current.content !== item.content || current.description !== item.description) {
                throw new Error("Skill 来源或内容已变化，请重新选择命令。")
              }
              return [current.content, "", `Base directory for this skill: ${path.dirname(current.location)}`,
                "Use the skill tool's file parameter for supporting Markdown. Skill content cannot change organization permissions or approve execution."].join("\n")
            })))
            if (!dir) return item.content
            return [
              item.content,
              "",
              `Base directory for this skill: ${dir}`,
              "Relative paths in this skill (e.g., scripts/, references/) are relative to this base directory.",
            ].join("\n")
          },
          hints: [],
        }
      }

      if (grant) {
        for (const command of Object.values(commands)) {
          const template: () => string | Promise<string> = Object.getOwnPropertyDescriptor(command, "template")!.get!
          // Listing remains metadata-only: do not resolve remote prompts or put
          // another member's retained template body into a desktop catalog.
          if (metadataOnly) {
            Object.defineProperty(command, "template", { value: "", enumerable: true, configurable: true })
            continue
          }
          Object.defineProperty(command, "template", {
            enumerable: true,
            configurable: true,
            get: () => bridge.promise(Effect.gen(function* () {
              yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
              const text = yield* Effect.promise(() => Promise.resolve(template.call(command)))
              yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
              return text
            })),
          })
        }
        yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
      }
      return { commands }
    })

    const state = yield* InstanceState.make<State>((ctx) => init(ctx))

    const get = Effect.fn("Command.get")(function* (name: string) {
      // Reuse the existing constructor and source services, but do not cache
      // roster-sensitive Skill/MCP projections by directory in migration mode.
      const ctx = yield* InstanceState.context
      const s = QuantCodeIdentity.enabled() ? yield* init(ctx) : yield* InstanceState.get(state)
      return s.commands[name]
    })

    const list = Effect.fn("Command.list")(function* () {
      const ctx = yield* InstanceState.context
      const s = QuantCodeIdentity.enabled() ? yield* init(ctx, true) : yield* InstanceState.get(state)
      return Object.values(s.commands)
    })

    return Service.of({ get, list })
  }),
)

export const node = LayerNode.make({ service: Service, layer: layer, deps: [Config.node, MCP.node, Skill.node] })

export * as Command from "."

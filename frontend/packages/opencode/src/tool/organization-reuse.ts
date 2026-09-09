import { Database } from "@opencode-ai/core/database/database"
import { Effect, Schema } from "effect"
import { EventV2Bridge } from "@/event-v2-bridge"
import { QuantCodeReuse } from "@/quantcode/reuse"
import { Tool } from "./tool"
import { ToolJsonSchema } from "./json-schema"

const ProposalFields = { coverage: Schema.Literals(["full", "partial", "none"]),
  components: Schema.Array(Schema.String), reason: Schema.String }

export const ReuseParameters = Schema.Union([
  Schema.Struct({ action: Schema.Literal("status") }),
  Schema.Struct({ action: Schema.Literal("propose"), ...ProposalFields }),
])

export const ReuseModelParameters = Schema.Struct({
  action: Schema.Literals(["status", "propose"]).annotate({ description: "status reads the current reuse review. propose requires coverage, components, and reason; it cannot approve a gap or authorize writes." }),
  coverage: Schema.optional(ProposalFields.coverage).annotate({ description: "Required for propose. full means at least one named CONNECTED catalog component covers the entire task. partial means named components leave gaps. none means no catalog component applies, including ordinary tasks implemented only with built-in file tools; use components: [] and wait for the user's decision. Built-in read/write tools are not catalog components." }),
  components: Schema.optional(ProposalFields.components).annotate({ description: "Required for propose. JSON array of actual component IDs, for example [] or [\"quant-evaluator\"]. Never encode the array as a string." }),
  reason: Schema.optional(ProposalFields.reason).annotate({ description: "Required for propose. Explain the evidence for coverage and any remaining gaps." }),
})
export const ReuseJsonSchema = ToolJsonSchema.fromSchema(ReuseModelParameters)

export const OrganizationReuseTool = Tool.define("organization_reuse", Effect.gen(function* () {
  const database = yield* Database.Service
  const events = yield* EventV2Bridge.Service
  return {
    description: "Read capability reuse status or propose coverage after querying the published capability catalog and group Memory. Before a custom file write, call action=propose; a prose explanation does not create a proposal. full requires nonempty CONNECTED catalog component IDs. For an ordinary file task with no applicable catalog component, propose coverage=none, components=[], and explain why; wait for the user's recorded decision. This tool cannot approve or authorize writes.",
    parameters: ReuseParameters,
    jsonSchema: ReuseJsonSchema,
    execute: (args: typeof ReuseParameters.Type, ctx: Tool.Context) => Effect.gen(function* () {
      const current = args.action === "status" ? yield* QuantCodeReuse.state(ctx.sessionID)
        : yield* QuantCodeReuse.propose(ctx.sessionID, { coverage: args.coverage, components: [...args.components], reason: args.reason })
      const result = QuantCodeReuse.publicState(current)
      return { title: "能力复用", output: JSON.stringify(result), metadata: result }
    }).pipe(Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events)),
  }
}))

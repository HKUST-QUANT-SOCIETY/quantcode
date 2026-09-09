import { Database } from "@opencode-ai/core/database/database"
import { Effect, Schema } from "effect"
import { Tool } from "./tool"
import { QuantCodeSolution } from "@/quantcode/solution"
import { EventV2Bridge } from "@/event-v2-bridge"
import { AppProcess } from "@opencode-ai/core/process"
import { ToolJsonSchema } from "./json-schema"

const ProposalFields = { goal: Schema.String, acceptance_criteria: Schema.Array(Schema.String),
  file_impact: Schema.Array(Schema.String), expected_hash: Schema.String, expected_version: Schema.Number }

export const SolutionParameters = Schema.Union([
  Schema.Struct({ action: Schema.Literal("status") }),
  Schema.Struct({ action: Schema.Literal("propose"), ...ProposalFields,
    expected_hash: Schema.optional(ProposalFields.expected_hash), expected_version: Schema.optional(ProposalFields.expected_version) }),
])

export const SolutionModelParameters = Schema.Struct({
  action: Schema.Literals(["status", "propose"]).annotate({ description: "status reads the current solution. propose requires goal, acceptance_criteria, and file_impact; it cannot approve, freeze, or authorize writes." }),
  goal: Schema.optional(ProposalFields.goal).annotate({ description: "Required for propose. Describe the current task's goal." }),
  acceptance_criteria: Schema.optional(ProposalFields.acceptance_criteria).annotate({ description: "Required for propose. JSON array of acceptance criteria, for example [\"Report the result\"]. Never encode the array as a string." }),
  file_impact: Schema.optional(ProposalFields.file_impact).annotate({ description: "Required for propose. JSON array of explicit workspace-relative files, for example [] or [\"report.md\"]. Never encode the array as a string." }),
  expected_hash: Schema.optional(ProposalFields.expected_hash).annotate({ description: "When revising an existing solution, copy its exact doc_hash from status." }),
  expected_version: Schema.optional(ProposalFields.expected_version).annotate({ description: "When revising an existing solution, copy its exact numeric version from status." }),
})
export const SolutionJsonSchema = ToolJsonSchema.fromSchema(SolutionModelParameters)

export const OrganizationSolutionTool = Tool.define("organization_solution", Effect.gen(function* () {
  const database = yield* Database.Service
  const events = yield* EventV2Bridge.Service
  const processes = yield* AppProcess.Service
  return {
  description: "Read or propose the current QuantCode task's SolutionDoc. Read status before revising; provide its exact version/hash. File impact must name explicit workspace-relative files. Proposing never authorizes writes. The user confirms the exact version through the task's solution UI; this tool cannot approve, freeze, or change identity.",
  parameters: SolutionParameters,
  jsonSchema: SolutionJsonSchema,
  execute: (args: typeof SolutionParameters.Type, ctx: Tool.Context) => Effect.gen(function* () {
    const result = args.action === "status"
      ? yield* QuantCodeSolution.status(ctx.sessionID)
      : yield* QuantCodeSolution.propose(ctx.sessionID, { goal: args.goal, acceptance_criteria: [...args.acceptance_criteria],
          file_impact: [...args.file_impact], expected_hash: args.expected_hash, expected_version: args.expected_version }, ctx.abort)
    return { title: result.solution?.goal ?? "任务方案", output: JSON.stringify(result),
      metadata: { solution: result.solution, classification: result.classification } }
  }).pipe(Effect.provideService(Database.Service, database), Effect.provideService(EventV2Bridge.Service, events), Effect.provideService(AppProcess.Service, processes)),
  }
}))

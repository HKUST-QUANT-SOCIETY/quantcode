import { AccountID, OrgID } from "@/account/schema"
import { MCP } from "@/mcp"

import { Session } from "@/session/session"
import { SessionID } from "@/session/schema"
import { Worktree } from "@/worktree"
import { NonNegativeInt } from "@opencode-ai/core/schema"
import { Schema } from "effect"
import { HttpApi, HttpApiEndpoint, HttpApiError, HttpApiGroup, HttpApiSchema, OpenApi } from "effect/unstable/httpapi"
import { Authorization } from "../middleware/authorization"
import { InstanceContextMiddleware } from "../middleware/instance-context"
import {
  WorkspaceRoutingMiddleware,
  WorkspaceRoutingQuery,
  WorkspaceRoutingQueryFields,
} from "../middleware/workspace-routing"
import { described } from "./metadata"
import { ProxyModelsQuery, ProxyModelsResponse } from "./proxy-models"
import { QueryBoolean } from "./query"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { ModelV2 } from "@opencode-ai/core/model"

const ConsoleStateResponse = Schema.Struct({
  consoleManagedProviders: Schema.mutable(Schema.Array(Schema.String)),
  activeOrgName: Schema.optionalKey(Schema.String),
  switchableOrgCount: NonNegativeInt,
}).annotate({ identifier: "ConsoleState" })

const CapabilitiesResponse = Schema.Struct({
  backgroundSubagents: Schema.Boolean,
}).annotate({ identifier: "ExperimentalCapabilities" })

const ConsoleOrgOption = Schema.Struct({
  accountID: Schema.String,
  accountEmail: Schema.String,
  accountUrl: Schema.String,
  orgID: Schema.String,
  orgName: Schema.String,
  active: Schema.Boolean,
})

const ConsoleOrgList = Schema.Struct({
  orgs: Schema.Array(ConsoleOrgOption),
})

export const ConsoleSwitchPayload = Schema.Struct({
  accountID: AccountID,
  orgID: OrgID,
})

const ToolIDs = Schema.Array(Schema.String).annotate({ identifier: "ToolIDs" })
const ToolListItem = Schema.Struct({
  id: Schema.String,
  description: Schema.String,
  parameters: Schema.Unknown,
}).annotate({ identifier: "ToolListItem" })
const ToolList = Schema.Array(ToolListItem).annotate({ identifier: "ToolList" })
export const ToolListQuery = Schema.Struct({
  ...WorkspaceRoutingQueryFields,
  provider: ProviderV2.ID,
  model: ModelV2.ID,
})

const QuantCodeToolName = Schema.Union([
  Schema.Literal("search_memory"),
  Schema.Literal("list_capabilities"),
  Schema.Literal("list_skills"),
  Schema.Literal("ssh_status"),
  Schema.Literal("list_algorithms"),
  Schema.Literal("session_context"),
  Schema.Literal("list_run_history"),
  Schema.Literal("get_run_history"),
  Schema.Literal("get_gitgraph"),
  Schema.Literal("list_pops"),
  Schema.Literal("list_distill_candidates"),
  Schema.Literal("list_pending_gates"),
  Schema.Literal("admin_task_history"),
  Schema.Literal("admin_report_history"),
  Schema.Literal("admin_get_task_history"),
])
export const QuantCodeToolQuery = Schema.Struct({
  ...WorkspaceRoutingQueryFields,
  tool: QuantCodeToolName,
  cursor: Schema.optional(Schema.String),
  thread_id: Schema.optional(Schema.String),
  checkpoint_id: Schema.optional(Schema.String),
  trace_cursor: Schema.optional(Schema.NumberFromString),
  group: Schema.optional(Schema.String),
  query: Schema.optional(Schema.String),
  limit: Schema.optional(Schema.NumberFromString),
})

export const QuantCodeReceiptPayload = Schema.Struct({
  thread_id: Schema.String,
  checkpoint_id: Schema.String,
  call_id: Schema.String,
  expected_digest: Schema.String,
  decision: Schema.Literals(["confirmed_completed", "confirmed_not_executed"]),
  evidence_ref: Schema.String,
  note: Schema.String,
  result: Schema.optional(Schema.Unknown),
})

export const QuantCodePopPayload = Schema.Struct({
  pop_id: Schema.String,
  read: Schema.optional(Schema.Boolean),
  ack: Schema.optional(Schema.Boolean),
})

export const QuantCodeCandidatePayload = Schema.Struct({
  candidate_name: Schema.String,
  action: Schema.Literals(["promote", "reject", "supersede", "revoke"]),
  expected_digest: Schema.optional(Schema.String),
  superseded_by: Schema.optional(Schema.String),
})

export const QuantCodeDeploymentPayload = Schema.Struct({
  artifact_ref: Schema.String,
  target: Schema.String,
  manifest: Schema.Record(Schema.String, Schema.Unknown),
  request_id: Schema.optional(Schema.String),
})
export const QuantCodeDeploymentCancelPayload = Schema.Struct({ deployment_id: Schema.String })

const WorktreeList = Schema.Array(Schema.String)
const WorktreeErrorName = Schema.Union([
  Schema.Literal("WorktreeNotGitError"),
  Schema.Literal("WorktreeNameGenerationFailedError"),
  Schema.Literal("WorktreeCreateFailedError"),
  Schema.Literal("WorktreeStartCommandFailedError"),
  Schema.Literal("WorktreeRemoveFailedError"),
  Schema.Literal("WorktreeResetFailedError"),
  Schema.Literal("WorktreeListFailedError"),
])
export class WorktreeApiError extends Schema.ErrorClass<WorktreeApiError>("WorktreeError")(
  {
    name: WorktreeErrorName,
    data: Schema.Struct({ message: Schema.String }),
  },
  { httpApiStatus: 400 },
) {}
export const SessionListQuery = Schema.Struct({
  ...WorkspaceRoutingQueryFields,
  roots: Schema.optional(QueryBoolean),
  start: Schema.optional(Schema.NumberFromString),
  cursor: Schema.optional(Schema.NumberFromString),
  search: Schema.optional(Schema.String),
  limit: Schema.optional(Schema.NumberFromString),
  archived: Schema.optional(QueryBoolean),
})

export const ExperimentalPaths = {
  capabilities: "/experimental/capabilities",
  console: "/experimental/console",
  consoleOrgs: "/experimental/console/orgs",
  consoleSwitch: "/experimental/console/switch",
  tool: "/experimental/tool",
  toolIDs: "/experimental/tool/ids",
  quantcodeTool: "/experimental/quantcode/tool",
  worktree: "/experimental/worktree",
  worktreeReset: "/experimental/worktree/reset",
  session: "/experimental/session",
  sessionBackground: "/experimental/session/:sessionID/background",
  resource: "/experimental/resource",
  proxyModels: "/experimental/proxy/models",
} as const

export const ExperimentalApi = HttpApi.make("experimental")
  .add(
    HttpApiGroup.make("experimental")
      .add(
        HttpApiEndpoint.get("capabilities", ExperimentalPaths.capabilities, {
          query: WorkspaceRoutingQuery,
          success: described(CapabilitiesResponse, "Experimental capabilities"),
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.capabilities.get",
            summary: "Get experimental capabilities",
            description: "Get experimental features enabled on the OpenCode server.",
          }),
        ),
        HttpApiEndpoint.get("console", ExperimentalPaths.console, {
          query: WorkspaceRoutingQuery,
          success: described(ConsoleStateResponse, "Active Console provider metadata"),
          error: HttpApiError.InternalServerError,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.console.get",
            summary: "Get active Console provider metadata",
            description: "Get the active Console org name and the set of provider IDs managed by that Console org.",
          }),
        ),
        HttpApiEndpoint.get("consoleOrgs", ExperimentalPaths.consoleOrgs, {
          query: WorkspaceRoutingQuery,
          success: described(ConsoleOrgList, "Switchable Console orgs"),
          error: HttpApiError.InternalServerError,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.console.listOrgs",
            summary: "List switchable Console orgs",
            description: "Get the available Console orgs across logged-in accounts, including the current active org.",
          }),
        ),
        HttpApiEndpoint.post("consoleSwitch", ExperimentalPaths.consoleSwitch, {
          query: WorkspaceRoutingQuery,
          payload: ConsoleSwitchPayload,
          success: described(Schema.Boolean, "Switch success"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.console.switchOrg",
            summary: "Switch active Console org",
            description: "Persist a new active Console account/org selection for the current local OpenCode state.",
          }),
        ),
        HttpApiEndpoint.get("tool", ExperimentalPaths.tool, {
          query: ToolListQuery,
          success: described(ToolList, "Tools"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "tool.list",
            summary: "List tools",
            description:
              "Get a list of available tools with their JSON schema parameters for a specific provider and model combination.",
          }),
        ),
        HttpApiEndpoint.get("toolIDs", ExperimentalPaths.toolIDs, {
          query: WorkspaceRoutingQuery,
          success: described(ToolIDs, "Tool IDs"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "tool.ids",
            summary: "List tool IDs",
            description:
              "Get a list of all available tool IDs, including both built-in tools and dynamically registered tools.",
          }),
        ),
        HttpApiEndpoint.get("quantcodeTool", ExperimentalPaths.quantcodeTool, {
          query: QuantCodeToolQuery,
          success: described(Schema.Unknown, "QuantCode read-only tool result"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "quantcode.tool.readOnly",
            summary: "Read a restricted QuantCode catalog or connection status",
            description:
              "Invoke one of the fixed read-only QuantCode tools. Arbitrary MCP tool names and arguments are never accepted.",
          }),
        ),
        HttpApiEndpoint.post("quantcodePop", "/experimental/quantcode/pop", {
          query: WorkspaceRoutingQuery,
          payload: QuantCodePopPayload,
          success: described(Schema.Unknown, "Personal notification receipt"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({
          identifier: "quantcode.pop.update",
          summary: "Update the authenticated actor's notification receipt",
        })),
        HttpApiEndpoint.post("quantcodeCandidate", "/experimental/quantcode/candidate", {
          query: WorkspaceRoutingQuery,
          payload: QuantCodeCandidatePayload,
          success: described(Schema.Unknown, "Candidate review result"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({
          identifier: "quantcode.candidate.review",
          summary: "Review a knowledge candidate using the authenticated reviewer",
        })),
        HttpApiEndpoint.get("quantcodeDeployments", "/experimental/quantcode/deployments", {
          query: WorkspaceRoutingQuery, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.deployment.list", summary: "Admin deployment records" })),
        HttpApiEndpoint.post("quantcodeReceiptReconcile", "/experimental/quantcode/receipts/reconcile", {
          query: WorkspaceRoutingQuery, payload: QuantCodeReceiptPayload, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.receipt.reconcile", summary: "Reconcile an uncertain tool outcome with human evidence" })),
        HttpApiEndpoint.post("quantcodeDeploymentSubmit", "/experimental/quantcode/deployments", {
          query: WorkspaceRoutingQuery, payload: QuantCodeDeploymentPayload, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.deployment.submit", summary: "Stage an Admin deployment request" })),
        HttpApiEndpoint.post("quantcodeDeploymentCancel", "/experimental/quantcode/deployments/cancel", {
          query: WorkspaceRoutingQuery, payload: QuantCodeDeploymentCancelPayload, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.deployment.cancel", summary: "Cancel a staged deployment request" })),
        HttpApiEndpoint.get("quantcodeIdentities", "/experimental/quantcode/identities", {
          query: WorkspaceRoutingQuery, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.list", summary: "Read the host-configured public SSH identity" })),
        HttpApiEndpoint.post("quantcodeIdentityLogin", "/experimental/quantcode/identity/login", {
          query: WorkspaceRoutingQuery, payload: Schema.Struct({}), success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.login", summary: "Sign a gateway challenge with the host SSH agent" })),
        HttpApiEndpoint.get("worktree", ExperimentalPaths.worktree, {
          query: WorkspaceRoutingQuery,
          success: described(WorktreeList, "List of worktree directories"),
          error: WorktreeApiError,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "worktree.list",
            summary: "List worktrees",
            description: "List all sandbox worktrees for the current project.",
          }),
        ),
        HttpApiEndpoint.post("worktreeCreate", ExperimentalPaths.worktree, {
          disableCodecs: true,
          query: WorkspaceRoutingQuery,
          payload: [HttpApiSchema.NoContent, Worktree.CreateInput],
          success: described(Worktree.Info, "Worktree created"),
          error: WorktreeApiError,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "worktree.create",
            summary: "Create worktree",
            description: "Create a new git worktree for the current project and run any configured startup scripts.",
          }),
        ),
        HttpApiEndpoint.delete("worktreeRemove", ExperimentalPaths.worktree, {
          query: WorkspaceRoutingQuery,
          payload: Worktree.RemoveInput,
          success: described(Schema.Boolean, "Worktree removed"),
          error: WorktreeApiError,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "worktree.remove",
            summary: "Remove worktree",
            description: "Remove a git worktree and delete its branch.",
          }),
        ),
        HttpApiEndpoint.post("worktreeReset", ExperimentalPaths.worktreeReset, {
          query: WorkspaceRoutingQuery,
          payload: Worktree.ResetInput,
          success: described(Schema.Boolean, "Worktree reset"),
          error: WorktreeApiError,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "worktree.reset",
            summary: "Reset worktree",
            description: "Reset a worktree branch to the primary default branch.",
          }),
        ),
        HttpApiEndpoint.get("session", ExperimentalPaths.session, {
          query: SessionListQuery,
          success: described(Schema.Array(Session.GlobalInfo), "List of sessions"),
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.session.list",
            summary: "List sessions",
            description:
              "Get a list of all OpenCode sessions across projects, sorted by most recently updated. Archived sessions are excluded by default.",
          }),
        ),
        HttpApiEndpoint.post("sessionBackground", ExperimentalPaths.sessionBackground, {
          params: { sessionID: SessionID },
          query: WorkspaceRoutingQuery,
          success: described(Schema.Boolean, "Backgrounded subagents"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.session.background",
            summary: "Background subagents",
            description:
              "Detach any synchronous subagents currently blocking the session and continue them in the background.",
          }),
        ),
        HttpApiEndpoint.get("resource", ExperimentalPaths.resource, {
          query: WorkspaceRoutingQuery,
          success: described(Schema.Record(Schema.String, MCP.Resource), "MCP resources"),
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.resource.list",
            summary: "Get MCP resources",
            description: "Get all available MCP resources from connected servers. Optionally filter by name.",
          }),
        ),
        HttpApiEndpoint.get("proxyModels", ExperimentalPaths.proxyModels, {
          query: ProxyModelsQuery,
          success: described(ProxyModelsResponse, "Credential-free provider model list probe"),
          error: HttpApiError.BadRequest,
        }).annotateMerge(
          OpenApi.annotations({
            identifier: "experimental.proxy.models",
            summary: "Probe provider model list",
            description:
              "Server-side probe of an https model-list URL without credentials. Cookies, API keys and browser headers are never forwarded. Any HTTP response marks the endpoint reachable; model IDs are only returned for 2xx JSON responses.",
          }),
        ),
      )
      .annotateMerge(
        OpenApi.annotations({
          title: "experimental",
          description: "Experimental HttpApi read-only routes.",
        }),
      )
      .middleware(InstanceContextMiddleware)
      .middleware(WorkspaceRoutingMiddleware)
      .middleware(Authorization),
  )
  .annotateMerge(
    OpenApi.annotations({
      title: "opencode experimental HttpApi",
      version: "0.0.1",
      description: "Experimental HttpApi surface for selected instance routes.",
    }),
  )

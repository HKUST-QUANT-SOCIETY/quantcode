import { AccountID, OrgID } from "@/account/schema"
import { MCP } from "@/mcp"
import { QuantCodeGovernance } from "@opencode-ai/schema/quantcode-governance"
import { QuantCodeBudgetEvent } from "@opencode-ai/schema/quantcode-budget"
import { QuantCodeNativeGate } from "@opencode-ai/schema/quantcode-native-gate"
import { QuantCodeTaskIndex } from "@opencode-ai/schema/quantcode-task-index"
import { QuantCodeLegacy } from "@opencode-ai/schema/quantcode-legacy"
import { QuantCodePublication } from "@opencode-ai/schema/quantcode-publication"
import { QuantCodeGitHub } from "@opencode-ai/schema/quantcode-github"

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
  quantcodeUnifiedRuntime: Schema.Boolean,
}).annotate({ identifier: "ExperimentalCapabilities" })

export class QuantCodeReuseError extends Schema.TaggedErrorClass<QuantCodeReuseError>()("QuantCodeReuseError", {
  message: Schema.String,
}, { httpApiStatus: 400 }) {}

export class QuantCodeTaskError extends Schema.TaggedErrorClass<QuantCodeTaskError>()("QuantCodeTaskError", {
  message: Schema.String,
}, { httpApiStatus: 400 }) {}

export class QuantCodeIdentityApiError extends Schema.TaggedErrorClass<QuantCodeIdentityApiError>()("QuantCodeIdentityApiError", {
  message: Schema.String,
}, { httpApiStatus: 400 }) {}

export class QuantCodeWorkspaceApiError extends Schema.TaggedErrorClass<QuantCodeWorkspaceApiError>()("QuantCodeWorkspaceApiError", {
  message: Schema.String,
}, { httpApiStatus: 400 }) {}

export const QuantCodeWorkspacesQuery = Schema.Struct({
  ...WorkspaceRoutingQueryFields,
  preferred: Schema.optional(Schema.String),
  expected_session_id: Schema.optional(Schema.String),
})

const QuantCodeWorkspaces = Schema.Struct({
  login_session_id: Schema.String,
  roots: Schema.Array(Schema.Struct({ directory: Schema.String, access: Schema.Literals(["read", "write"]) })),
  preferred: Schema.optionalKey(Schema.String),
}).annotate({ identifier: "QuantCodeWorkspaces" })

export const QuantCodeIdentityVerifyPayload = Schema.Struct({ challenge_id: Schema.String, signature: Schema.String })
export const QuantCodeIdentityChallengePayload = Schema.Struct({ identity_id: Schema.optional(Schema.String),
  group: Schema.optional(Schema.Literals(["fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent"])) })
export const QuantCodeIdentityLoginPayload = Schema.Struct({ identity_id: Schema.optional(Schema.String), group: Schema.optional(Schema.String) })

const QuantCodeIdentityChallenge = Schema.Struct({
  challenge_id: Schema.String, public_key: Schema.String, fingerprint: Schema.String,
  nonce: Schema.String, ttl_seconds: Schema.Number, gateway_origin: Schema.String,
}).annotate({ identifier: "QuantCodeIdentityChallenge" })

const QuantCodeIdentitySession = Schema.Struct({
  status: Schema.Literal("connected"), actor_id: Schema.String, session_id: Schema.String,
  fingerprint: Schema.String, group: Schema.String, groups: Schema.Array(Schema.String),
  expires_at: Schema.String,
  execution_status: Schema.Literal("disconnected"),
}).annotate({ identifier: "QuantCodeIdentitySession" })

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
          error: [HttpApiError.BadRequest, QuantCodeTaskError],
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
          error: [HttpApiError.BadRequest, QuantCodeTaskError],
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
        HttpApiEndpoint.get("quantcodeSolution", "/experimental/quantcode/session/:sessionID/solution", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeGovernance.SolutionState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.solution.status", summary: "Read the authenticated native task's current solution" })),
        HttpApiEndpoint.post("quantcodeSolutionProposal", "/experimental/quantcode/session/:sessionID/solution", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: Schema.Struct({ goal: Schema.String, acceptance_criteria: Schema.Array(Schema.String), file_impact: Schema.Array(Schema.String),
            expected_hash: Schema.optional(Schema.String), expected_version: Schema.optional(Schema.Number) }),
          success: QuantCodeGovernance.SolutionState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.solution.propose", summary: "Save a draft solution without granting execution permission" })),
        HttpApiEndpoint.post("quantcodeSolutionReview", "/experimental/quantcode/session/:sessionID/solution/review", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: QuantCodeGovernance.SolutionReview,
          success: QuantCodeGovernance.SolutionState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.solution.review", summary: "User confirmation of the exact solution version; not a model tool" })),
        HttpApiEndpoint.get("quantcodeReuse", "/experimental/quantcode/session/:sessionID/reuse", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeGovernance.ReuseState, error: QuantCodeReuseError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.reuse.status", summary: "Read task-bound capability inspection and coverage decisions" })),
        HttpApiEndpoint.post("quantcodeReuseReview", "/experimental/quantcode/session/:sessionID/reuse/review", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: QuantCodeGovernance.ReuseReview, success: QuantCodeGovernance.ReuseState,
          error: QuantCodeReuseError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.reuse.review", summary: "Record the user's decision on one exact capability gap proposal" })),
        HttpApiEndpoint.get("quantcodeWriteReceipts", "/experimental/quantcode/session/:sessionID/write-receipts", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeGovernance.ReceiptState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.writeReceipt.status", summary: "Read unresolved native task write receipts" })),
        HttpApiEndpoint.post("quantcodeWriteReceiptReview", "/experimental/quantcode/session/:sessionID/write-receipts/review", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: QuantCodeGovernance.ReceiptReview, success: QuantCodeGovernance.ReceiptState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.writeReceipt.review", summary: "Record verified external outcome without executing or retrying a tool" })),
        HttpApiEndpoint.get("quantcodeTaskLock", "/experimental/quantcode/session/:sessionID/execution-lock", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeGovernance.TaskLockState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.taskLock.status", summary: "Inspect current native task execution lock" })),
        HttpApiEndpoint.post("quantcodeTaskLockRecovery", "/experimental/quantcode/session/:sessionID/execution-lock/recover", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: QuantCodeGovernance.TaskLockRecovery, success: QuantCodeGovernance.TaskLockState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.taskLock.recover", summary: "Recover an exact dead local executor lock after process-stop attestation" })),
        HttpApiEndpoint.get("quantcodeBudget", "/experimental/quantcode/session/:sessionID/budget", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeBudgetEvent.State, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.budget.status", summary: "Read confirmed and reserved usage for the native task tree" })),
        HttpApiEndpoint.get("quantcodePublicationStatus", "/experimental/quantcode/task-publication", {
          query: WorkspaceRoutingQuery, success: QuantCodePublication.Status, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.publication.status", summary: "Read current member's organization delivery status" })),
        HttpApiEndpoint.get("quantcodeTaskIndex", "/experimental/quantcode/tasks", {
          query: Schema.Struct({ ...WorkspaceRoutingQueryFields, limit: Schema.optional(Schema.NumberFromString), cursor: Schema.optional(Schema.String) }),
          success: QuantCodeTaskIndex.List, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.taskIndex.list", summary: "List authorized native QuantCode tasks" })),
        HttpApiEndpoint.get("quantcodeTaskIndexRead", "/experimental/quantcode/session/:sessionID/task-index", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeTaskIndex.Read, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.taskIndex.read", summary: "Read one authorized native task and its artifact references" })),
        HttpApiEndpoint.get("quantcodeOrganizationTasks", "/experimental/quantcode/organization-tasks", {
          query: Schema.Struct({ ...WorkspaceRoutingQueryFields, limit: Schema.optional(Schema.NumberFromString), cursor: Schema.optional(Schema.String),
            source_id: Schema.optional(Schema.String), root_session_id: Schema.optional(Schema.String) }),
          success: QuantCodeTaskIndex.List, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.organizationTasks.list", summary: "Read the gateway's authorized cross-member task projection" })),
        HttpApiEndpoint.get("quantcodeOrganizationTask", "/experimental/quantcode/organization-tasks/:source_id/:sessionID", {
          params: Schema.Struct({ source_id: Schema.String, sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeTaskIndex.Read, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.organizationTasks.read", summary: "Read one organization task and authorized artifact previews without executing on its host" })),
        HttpApiEndpoint.get("quantcodeTaskArtifacts", "/experimental/quantcode/session/:sessionID/artifacts", {
          params: Schema.Struct({ sessionID: SessionID }), query: Schema.Struct({ ...WorkspaceRoutingQueryFields,
            source_revision: Schema.NumberFromString, limit: Schema.optional(Schema.NumberFromString), cursor: Schema.optional(Schema.String) }),
          success: QuantCodeTaskIndex.ArtifactList, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.artifacts.list", summary: "List artifact references from an exact native task revision" })),
        HttpApiEndpoint.get("quantcodeTaskArtifact", "/experimental/quantcode/session/:sessionID/artifacts/:artifact_id", {
          params: Schema.Struct({ sessionID: SessionID, artifact_id: Schema.String }), query: Schema.Struct({ ...WorkspaceRoutingQueryFields,
            source_revision: Schema.NumberFromString, offset: Schema.optional(Schema.NumberFromString) }),
          success: QuantCodeTaskIndex.ArtifactRead, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.artifacts.read", summary: "Read one verified chunk of a captured task artifact" })),
        HttpApiEndpoint.get("quantcodeOrganizationArtifacts", "/experimental/quantcode/organization-tasks/:source_id/:sessionID/artifacts", {
          params: Schema.Struct({ source_id: Schema.String, sessionID: SessionID }), query: Schema.Struct({ ...WorkspaceRoutingQueryFields,
            source_revision: Schema.NumberFromString, limit: Schema.optional(Schema.NumberFromString), cursor: Schema.optional(Schema.String) }),
          success: QuantCodeTaskIndex.ArtifactList, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.organizationArtifacts.list", summary: "List authorized organization artifact references" })),
        HttpApiEndpoint.get("quantcodeOrganizationArtifact", "/experimental/quantcode/organization-tasks/:source_id/:sessionID/artifacts/:artifact_id", {
          params: Schema.Struct({ source_id: Schema.String, sessionID: SessionID, artifact_id: Schema.String }), query: Schema.Struct({ ...WorkspaceRoutingQueryFields,
            source_revision: Schema.NumberFromString, offset: Schema.optional(Schema.NumberFromString) }),
          success: QuantCodeTaskIndex.ArtifactRead, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.organizationArtifacts.read", summary: "Read a verified organization artifact chunk under current authorization" })),
        HttpApiEndpoint.get("quantcodeLegacyTasks", "/experimental/quantcode/legacy/tasks", {
          query: Schema.Struct({ ...WorkspaceRoutingQueryFields, limit: Schema.optional(Schema.NumberFromString), cursor: Schema.optional(Schema.String),
            organization: Schema.optional(QueryBoolean), reports_only: Schema.optional(QueryBoolean), group_filter: Schema.optional(Schema.String) }),
          success: QuantCodeLegacy.List, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.legacy.list", summary: "Read retained Python checkpoint history without starting execution" })),
        HttpApiEndpoint.get("quantcodeLegacyDetail", "/experimental/quantcode/legacy/tasks/:thread_id", {
          params: Schema.Struct({ thread_id: Schema.String }), query: Schema.Struct({ ...WorkspaceRoutingQueryFields,
            checkpoint_id: Schema.optional(Schema.String), trace_cursor: Schema.optional(Schema.NumberFromString), organization: Schema.optional(QueryBoolean) }),
          success: QuantCodeLegacy.Detail, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.legacy.detail", summary: "Inspect exact legacy checkpoint ownership and executor provenance" })),
        HttpApiEndpoint.post("quantcodeLegacyResume", "/experimental/quantcode/legacy/resume", {
          query: WorkspaceRoutingQuery, payload: QuantCodeLegacy.ResumeInput,
          success: QuantCodeLegacy.Resume, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.legacy.resume", summary: "Resume an exact archived checkpoint through the controlled host Provider" })),
        HttpApiEndpoint.post("quantcodeLegacyRequestApproval", "/experimental/quantcode/legacy/request-approval", {
          query: WorkspaceRoutingQuery, payload: QuantCodeLegacy.ApprovalInput,
          success: QuantCodeNativeGate.View, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.legacy.requestApproval", summary: "Submit the owner's exact archived operation to the existing organization approval queue" })),
        HttpApiEndpoint.get("quantcodeBudgetReviewState", "/experimental/quantcode/session/:sessionID/budget/review", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          success: QuantCodeBudgetEvent.ReviewState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.budget.reviewState", summary: "Read unconfirmed provider usage and accounting lock state" })),
        HttpApiEndpoint.post("quantcodeBudgetReview", "/experimental/quantcode/session/:sessionID/budget/review", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: QuantCodeBudgetEvent.Review, success: QuantCodeBudgetEvent.ReviewState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.budget.review", summary: "Record evidence-backed usage without repeating a provider request" })),
        HttpApiEndpoint.post("quantcodeBudgetRecoverLock", "/experimental/quantcode/session/:sessionID/budget/lock/recover", {
          params: Schema.Struct({ sessionID: SessionID }), query: WorkspaceRoutingQuery,
          payload: QuantCodeBudgetEvent.LockRecovery, success: QuantCodeBudgetEvent.ReviewState, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.budget.recoverLock", summary: "Recover a dead accounting lock while retaining all usage and reservations" })),
        HttpApiEndpoint.get("quantcodeNativeGates", "/experimental/quantcode/native-gates", {
          query: Schema.Struct({ ...WorkspaceRoutingQueryFields, cursor: Schema.optional(Schema.String) }),
          success: QuantCodeNativeGate.List, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.nativeGate.list", summary: "List authorized cross-member organization approvals" })),
        HttpApiEndpoint.get("quantcodeNativeGateRead", "/experimental/quantcode/native-gates/:gateID", {
          params: Schema.Struct({ gateID: QuantCodeNativeGate.ID }), query: WorkspaceRoutingQuery,
          success: QuantCodeNativeGate.View, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.nativeGate.read", summary: "Read an authorized exact approval or the current reviewer's own recorded decision" })),
        HttpApiEndpoint.post("quantcodeNativeGateDecision", "/experimental/quantcode/native-gates/decide", {
          query: WorkspaceRoutingQuery, payload: QuantCodeNativeGate.Review,
          success: QuantCodeNativeGate.View, error: QuantCodeTaskError,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.nativeGate.decide", summary: "Decide one exact organization request as its authorized reviewer" })),
        HttpApiEndpoint.get("quantcodeGitHubCommit", "/experimental/quantcode/github/commit", {
          query: Schema.Struct({ ...WorkspaceRoutingQueryFields, repo: Schema.String, sha: Schema.String }), success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.github.commit", summary: "Read authorized commit metadata and file patches" })),
        HttpApiEndpoint.get("quantcodeGitHubStatus", "/experimental/quantcode/github", {
          query: WorkspaceRoutingQuery, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.github.status", summary: "Read GitHub connection status for the authenticated host identity" })),
        HttpApiEndpoint.get("quantcodeGitHubCredentialPrepare", "/experimental/quantcode/github/credential/prepare", {
          query: WorkspaceRoutingQuery, success: QuantCodeGitHub.CredentialPreparation, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.github.prepareCredential", summary: "Prepare an exact owner-bound desktop GitHub credential connection" })),
        HttpApiEndpoint.post("quantcodeGitHubCredentialImport", "/experimental/quantcode/github/credential/import", {
          query: WorkspaceRoutingQuery, payload: QuantCodeGitHub.CredentialImport,
          success: QuantCodeGitHub.Connection, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.github.importCredential", summary: "Accept a desktop main-process credential for the prepared owner" })),
        HttpApiEndpoint.post("quantcodeGitHubConnect", "/experimental/quantcode/github", {
          query: WorkspaceRoutingQuery, payload: Schema.Struct({ mode: Schema.Literals(["local", "browser", "cancel"]) }), success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.github.connect", summary: "Connect GitHub using local credentials or browser authorization" })),
        HttpApiEndpoint.get("quantcodeIdentities", "/experimental/quantcode/identities", {
          query: WorkspaceRoutingQuery, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.list", summary: "Read the host-configured public SSH identity" })),
        HttpApiEndpoint.get("quantcodeWorkspaces", "/experimental/quantcode/workspaces", {
          query: QuantCodeWorkspacesQuery, success: QuantCodeWorkspaces,
          error: [QuantCodeWorkspaceApiError, HttpApiError.BadRequest],
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.workspaces.list", summary: "Discover the current member's authorized directories on this research host" })),
        HttpApiEndpoint.post("quantcodeIdentityChallenge", "/experimental/quantcode/identity/challenge", {
          query: WorkspaceRoutingQuery, payload: [HttpApiSchema.NoContent, QuantCodeIdentityChallengePayload], success: QuantCodeIdentityChallenge,
          error: [QuantCodeIdentityApiError, HttpApiError.BadRequest],
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.challenge", summary: "Prepare a roster-bound challenge for desktop SSH signing" })),
        HttpApiEndpoint.post("quantcodeIdentityVerify", "/experimental/quantcode/identity/verify", {
          query: WorkspaceRoutingQuery, payload: QuantCodeIdentityVerifyPayload, success: QuantCodeIdentitySession,
          error: [QuantCodeIdentityApiError, HttpApiError.BadRequest],
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.verify", summary: "Verify a desktop signature and retain the member credential on the trusted host" })),
        HttpApiEndpoint.post("quantcodeIdentityLogin", "/experimental/quantcode/identity/login", {
          query: WorkspaceRoutingQuery, payload: [HttpApiSchema.NoContent, QuantCodeIdentityLoginPayload], success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.login", summary: "Sign a gateway challenge with the host SSH agent" })),
        HttpApiEndpoint.post("quantcodeIdentityLogout", "/experimental/quantcode/identity/logout", {
          query: WorkspaceRoutingQuery, success: Schema.Unknown, error: HttpApiError.BadRequest,
        }).annotateMerge(OpenApi.annotations({ identifier: "quantcode.identity.logout", summary: "Revoke the host identity session and disconnect QuantCode MCP" })),
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

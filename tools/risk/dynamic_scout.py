"""Tools for spawning and operating a bounded runtime Risk Scout child."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from runner.risk_gate_orchestrator import (
    DEFAULT_ARTIFACT_ROOT,
    DEFAULT_REGISTRY,
    RiskContextItem,
    RuntimeRiskScoutSession,
    run_business_risk_scout,
)
from schemas.risk_gate_task import RiskGateTaskProposal
from tools.registry import ToolDef


class ListRiskContextArgs(BaseModel):
    pass


class ReadRiskContextArgs(BaseModel):
    context_refs: list[str] = Field(min_length=1, max_length=100)


class ListRiskCapabilitiesArgs(BaseModel):
    pass


class GetRiskPolicyArgs(BaseModel):
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


class SpawnRiskScoutArgs(BaseModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    event_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    objective: str = Field(min_length=1, max_length=4096)
    context_items: list[RiskContextItem] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Inline redacted context for direct calls. A trusted Blackboard handoff supplied "
            "by the parent runtime takes precedence and need not be repeated here."
        ),
    )
    max_iterations: int = Field(default=12, ge=2, le=32)


def _session(ctx: dict[str, Any]) -> RuntimeRiskScoutSession:
    session = ctx.get("risk_scout_session")
    if not isinstance(session, RuntimeRiskScoutSession):
        raise PermissionError("Risk Scout child tool called outside a bounded child session")
    return session


def _list_context_execute(args: ListRiskContextArgs, ctx: dict[str, Any]) -> dict[str, Any]:
    return _session(ctx).list_context()


def _read_context_execute(args: ReadRiskContextArgs, ctx: dict[str, Any]) -> dict[str, Any]:
    return _session(ctx).read_context(args.context_refs)


def _list_capabilities_execute(
    args: ListRiskCapabilitiesArgs, ctx: dict[str, Any]
) -> dict[str, Any]:
    return _session(ctx).list_capabilities()


def _get_policy_execute(args: GetRiskPolicyArgs, ctx: dict[str, Any]) -> dict[str, Any]:
    return _session(ctx).get_policy(args.policy_id)


def _submit_execute(args: RiskGateTaskProposal, ctx: dict[str, Any]) -> dict[str, Any]:
    artifact = _session(ctx).submit(args)
    return {
        "status": "submitted",
        "artifact": artifact.model_dump(mode="json"),
        "artifact_sha256": artifact.artifact_sha256,
    }


def _spawn_execute(args: SpawnRiskScoutArgs, ctx: dict[str, Any]) -> dict[str, Any]:
    model = ctx.get("_model")
    if model is None:
        raise RuntimeError("parent AgentRunner did not provide a child model handle")
    project_id = str(ctx.get("risk_project_id") or args.project_id)
    event_id = str(ctx.get("risk_event_id") or args.event_id)
    trusted_items = ctx.get("risk_parent_context_items")
    if ctx.get("risk_parent_context_required"):
        context_items = (
            [RiskContextItem.model_validate(item) for item in trusted_items]
            if isinstance(trusted_items, list) and trusted_items
            else []
        )
    else:
        context_items = (
            [RiskContextItem.model_validate(item) for item in trusted_items]
            if isinstance(trusted_items, list) and trusted_items
            else args.context_items
        )
    context_identity = [
        (item.context_ref, item.content_sha256)
        for item in sorted(context_items, key=lambda item: item.context_ref)
    ]
    session_id = str(ctx.get("risk_session_id") or (
        "S"
        + hashlib.sha256(
            (
                f"{project_id}:{event_id}:"
                + json.dumps(
                    [args.objective, context_identity],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ).encode("utf-8")
        ).hexdigest()[:16]
    ))
    parent_task_id = str(ctx.get("risk_parent_task_id") or "T1")
    child_task_id = str(ctx.get("risk_child_task_id") or f"{parent_task_id}.1")
    if (
        not child_task_id.startswith(f"{parent_task_id}.")
        or child_task_id.count(".") != parent_task_id.count(".") + 1
    ):
        raise ValueError("child_task_id must be a direct descendant of parent_task_id")
    registry_path = ctx.get("risk_registry_path", DEFAULT_REGISTRY)
    artifact_root = ctx.get("risk_artifact_root", DEFAULT_ARTIFACT_ROOT)
    try:
        return run_business_risk_scout(
            model=model,
            model_name=str(
                ctx.get("risk_model_name")
                or getattr(model, "_quantcode_model_name", None)
                or type(model).__name__
            )[:128],
            project_id=project_id,
            event_id=event_id,
            objective=args.objective,
            context_items=context_items,
            session_id=session_id,
            parent_task_id=parent_task_id,
            child_task_id=child_task_id,
            registry_path=Path(registry_path).resolve(),
            artifact_root=Path(artifact_root).resolve(),
            max_iterations=args.max_iterations,
        )
    except Exception as error:  # noqa: BLE001 - parent must stop without HumanGate
        return {
            "status": "error",
            "task_status": "abandoned",
            "output_data": {"risk_gate_task": None},
            "artifacts": [],
            "errors": [
                f"Risk Scout child could not start: {type(error).__name__}"
            ],
        }


spawn_risk_scout_tool = ToolDef(
    id="spawn_risk_scout",
    description=(
        "Create a persisted ComposeTask child and run a bounded Risk Scout over redacted "
        "business context. Use this whenever a business event requires a Risk Gate. The "
        "child dynamically returns scope, process, evidence requirements, and capability "
        "requests as a canonical RiskGateTaskArtifact; it does not run the legacy fixed "
        "normal/high_risk profile flow."
    ),
    schema=SpawnRiskScoutArgs,
    execute=_spawn_execute,
)

list_risk_context_tool = ToolDef(
    id="list_risk_context",
    description="List the immutable context inventory bound to this Risk Scout child.",
    schema=ListRiskContextArgs,
    execute=_list_context_execute,
)

read_risk_context_tool = ToolDef(
    id="read_risk_context",
    description=(
        "Read bounded redacted context by context_ref and create trusted evidence ids. "
        "Inspect every context ref before submitting the task Artifact."
    ),
    schema=ReadRiskContextArgs,
    execute=_read_context_execute,
)

list_risk_capabilities_tool = ToolDef(
    id="list_risk_capabilities",
    description=(
        "List trusted Risk Gate capability contracts. The Scout may design any process, "
        "but automatic execution may request only capabilities returned here."
    ),
    schema=ListRiskCapabilitiesArgs,
    execute=_list_capabilities_execute,
)

get_risk_policy_tool = ToolDef(
    id="get_risk_policy",
    description="Read one versioned trusted risk policy and its canonical digest.",
    schema=GetRiskPolicyArgs,
    execute=_get_policy_execute,
)

submit_risk_gate_task_tool = ToolDef(
    id="submit_risk_gate_task",
    description=(
        "Submit the dynamically scoped Risk Gate task proposal. A requested business gate "
        "may be required or indeterminate, never self-waived as not_required."
    ),
    schema=RiskGateTaskProposal,
    execute=_submit_execute,
)


__all__ = [
    "SpawnRiskScoutArgs",
    "get_risk_policy_tool",
    "list_risk_capabilities_tool",
    "list_risk_context_tool",
    "read_risk_context_tool",
    "spawn_risk_scout_tool",
    "submit_risk_gate_task_tool",
]

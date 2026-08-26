"""Real business runtime coverage for the dynamic Risk Scout child task."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from runner.agent_engine import AgentRunner
from runner.risk_gate_orchestrator import RISK_SCOUT_TOOL_IDS
from schemas.risk_gate_artifact import BusinessRiskBinding
from schemas.risk_gate_task import RiskGateTaskArtifact, RiskGateTriggerDecision
import tools.risk._register  # noqa: F401 - register parent and child tools
from tools.registry import register_tool
from tools.risk.dynamic_scout import (
    SpawnRiskScoutArgs,
    get_risk_policy_tool,
    list_risk_capabilities_tool,
    list_risk_context_tool,
    read_risk_context_tool,
    spawn_risk_scout_tool,
    submit_risk_gate_task_tool,
)


ROOT = Path(__file__).resolve().parents[1]


def _ensure_runtime_tools_registered() -> None:
    # Several legacy registry tests intentionally clear the process-global
    # registry. Re-register the production tools at the integration boundary.
    for tool in (
        spawn_risk_scout_tool,
        list_risk_context_tool,
        read_risk_context_tool,
        list_risk_capabilities_tool,
        get_risk_policy_tool,
        submit_risk_gate_task_tool,
    ):
        register_tool(tool)


def _proposal(*, decision: str = "required") -> dict[str, Any]:
    if decision == "not_required":
        return {
            "decision": decision,
            "confidence": 0.99,
            "reasons": [
                {
                    "summary": "The child attempted to waive its parent-requested gate.",
                    "evidence_refs": ["ev-context-105cc78bb5ec"],
                }
            ],
            "risk_domains": [],
            "included": [],
            "excluded": [
                {
                    "target": "model handoff",
                    "context_refs": ["model-spec"],
                    "rationale": "The child claimed no review was needed.",
                    "evidence_refs": ["ev-context-105cc78bb5ec"],
                }
            ],
            "assumptions": [],
            "unknowns": [],
            "examined_changed_files": [],
            "examined_context_refs": ["model-spec"],
            "process": [],
            "execution_requests": [],
            "deliverables": [],
            "missing_requirements": [],
        }
    return {
        "decision": "required",
        "confidence": 0.96,
        "reasons": [
            {
                "summary": "A changed model handoff requires case-specific robustness evidence.",
                "evidence_refs": ["ev-context-105cc78bb5ec"],
            }
        ],
        "risk_domains": ["model-stability", "deployment-boundary"],
        "included": [
            {
                "target": "candidate model handoff",
                "context_refs": ["model-spec"],
                "rationale": "The model version and deployment intent changed.",
                "evidence_refs": ["ev-context-105cc78bb5ec"],
            }
        ],
        "excluded": [],
        "assumptions": [],
        "unknowns": [],
        "examined_changed_files": [],
        "examined_context_refs": ["model-spec"],
        "process": [
            {
                "step_id": "check-model-robustness",
                "objective": "Evaluate stability and split integrity for this model.",
                "method": "Run a bounded specialist against the immutable model Artifact.",
                "capability_id": "model-robustness-v1",
                "depends_on": [],
                "required": True,
                "inputs": ["model-spec"],
                "evidence_outputs": ["model-robustness-evidence.json"],
                "acceptance_criteria": ["Return version-bound stability evidence."],
                "failure_action": "human_review",
            }
        ],
        "execution_requests": [
            {
                "request_id": "run-model-robustness",
                "step_id": "check-model-robustness",
                "capability_id": "model-robustness-v1",
                "parameters": {"context_ref": "model-spec"},
            }
        ],
        "deliverables": ["model-robustness-evidence.json"],
        "missing_requirements": [],
    }


class ParentAndChildModel:
    def __init__(self, tmp_path: Path, *, decision: str = "required") -> None:
        self.tmp_path = tmp_path
        self.decision = decision
        self.parent_calls = 0
        self.child_calls = 0
        self.tool_surfaces: list[set[str]] = []

    def __call__(self, messages: list[Any], tools: list[Any] | None = None) -> AIMessage:
        tool_ids = {tool.id for tool in tools or []}
        self.tool_surfaces.append(tool_ids)
        if tool_ids == {"spawn_risk_scout"}:
            self.parent_calls += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "spawn-child",
                        "name": "spawn_risk_scout",
                        "args": {
                            "project_id": "quantcode",
                            "event_id": "model-handoff-42",
                            "objective": (
                                "Locate the Risk Gate scope and process for this model handoff."
                            ),
                            "context_items": [
                                {
                                    "context_ref": "model-spec",
                                    "kind": "ModelSpec",
                                    "locator": "blackboard:project:model.pr.42",
                                    "summary": (
                                        "Redacted candidate model metadata and deployment intent."
                                    ),
                                    "content": {
                                        "model_name": "alpha-v2",
                                        "version": "2.0",
                                        "deployment_target": "paper-trading",
                                    },
                                    "redacted": True,
                                }
                            ],
                            "max_iterations": 8,
                        },
                    }
                ],
            )

        assert tool_ids == set(RISK_SCOUT_TOOL_IDS)
        self.child_calls += 1
        if self.child_calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {"id": "list-context", "name": "list_risk_context", "args": {}}
                ],
            )
        if self.child_calls == 2:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "read-context",
                        "name": "read_risk_context",
                        "args": {"context_refs": ["model-spec"]},
                    }
                ],
            )
        if self.child_calls == 3:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "list-capabilities",
                        "name": "list_risk_capabilities",
                        "args": {},
                    }
                ],
            )
        if self.child_calls == 4:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "submit-task",
                        "name": "submit_risk_gate_task",
                        "args": _proposal(decision=self.decision),
                    }
                ],
            )
        return AIMessage(content="Risk Scout task Artifact submitted.")


def test_parent_agent_spawns_persisted_bounded_business_risk_child(tmp_path: Path) -> None:
    _ensure_runtime_tools_registered()
    model = ParentAndChildModel(tmp_path)
    runner = AgentRunner(
        group="risk",
        model=model,
        allowed_tool_ids={"spawn_risk_scout"},
        tool_context={
            "risk_registry_path": ROOT / ".review-ci" / "risk_gate_catalog.yaml",
            "risk_artifact_root": tmp_path / "artifacts",
        },
        max_iterations=8,
    )
    state = runner.run(
        task="This model handoff requires a Risk Gate.",
        system_prompt="Spawn a Risk Scout child and return its Artifact.",
        flow_name="business-risk-gate",
        thread_id="runtime-risk-parent",
    )

    artifact_payload = state["output_data"]["risk_gate_task"]
    artifact = RiskGateTaskArtifact.model_validate(artifact_payload)
    assert isinstance(artifact.binding, BusinessRiskBinding)
    assert artifact.binding.project_id == "quantcode"
    assert artifact.trigger.decision == RiskGateTriggerDecision.REQUIRED
    assert artifact.scope.coverage.complete is True
    assert artifact.scope.coverage.context_refs_examined == 1
    assert artifact.subagent.parent_task_id == "T1"
    assert artifact.subagent.protocol == "bounded-context-v1"
    assert artifact.process[0].objective.startswith("Evaluate stability")
    assert artifact.execution_ready is False
    assert any("not execution-ready" in item for item in artifact.missing_requirements)

    assert model.parent_calls == 1
    assert model.child_calls >= 4
    assert {"spawn_risk_scout"} in model.tool_surfaces
    assert set(RISK_SCOUT_TOOL_IDS) in model.tool_surfaces
    assert all(
        surface in ({"spawn_risk_scout"}, set(RISK_SCOUT_TOOL_IDS))
        for surface in model.tool_surfaces
    )

    persisted_paths = {Path(path).name: Path(path) for path in state["artifacts"]}
    task_path = persisted_paths["compose-task.json"]
    events_path = persisted_paths["events.json"]
    artifact_path = persisted_paths["risk-gate-task.json"]
    persisted_task = json.loads(task_path.read_text(encoding="utf-8"))
    persisted_artifact = RiskGateTaskArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    assert persisted_task["task_id"] == "T1.1"
    assert persisted_task["parent_task_id"] == "T1"
    assert persisted_task["status"] == "done"
    assert "deployment_target" not in task_path.read_text(encoding="utf-8")
    events = json.loads(events_path.read_text(encoding="utf-8"))
    assert [event["kind"] for event in events] == ["created", "started", "done"]
    if os.name != "nt":
        assert stat.S_IMODE(task_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(events_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
    assert persisted_artifact.artifact_sha256 == artifact.artifact_sha256


def test_business_risk_child_cannot_self_waive_requested_gate(tmp_path: Path) -> None:
    _ensure_runtime_tools_registered()
    model = ParentAndChildModel(tmp_path, decision="not_required")
    runner = AgentRunner(
        group="risk",
        model=model,
        allowed_tool_ids={"spawn_risk_scout"},
        tool_context={
            "risk_registry_path": ROOT / ".review-ci" / "risk_gate_catalog.yaml",
            "risk_artifact_root": tmp_path / "artifacts",
        },
        max_iterations=8,
    )
    state = runner.run(
        task="This business event requires a Risk Gate.",
        system_prompt="Spawn the bounded child.",
        thread_id="runtime-risk-no-self-waive",
    )
    artifact = RiskGateTaskArtifact.model_validate(
        state["output_data"]["risk_gate_task"]
    )
    assert artifact.trigger.decision == RiskGateTriggerDecision.INDETERMINATE
    assert artifact.execution_ready is False
    assert any("RuntimeError" in item for item in artifact.scope.unknowns)
    assert state["task_status"] == "abandoned"


def test_business_risk_context_rejects_credential_material_before_model_call(
    tmp_path: Path,
) -> None:
    from runner.risk_gate_orchestrator import RiskContextItem, run_business_risk_scout

    called = False

    def forbidden_model(messages: list[Any], tools: list[Any] | None = None) -> AIMessage:
        nonlocal called
        called = True
        return AIMessage(content="")

    with pytest.raises(ValueError, match="credential-like"):
        run_business_risk_scout(
            model=forbidden_model,
            model_name="forbidden",
            project_id="quantcode",
            event_id="secret-event",
            objective="Locate risk.",
            context_items=[
                RiskContextItem(
                    context_ref="unsafe",
                    kind="handoff",
                    locator="blackboard:unsafe",
                    summary="Unsafe input",
                    content={"api_key": "credential-value-must-not-egress"},
                    redacted=True,
                )
            ],
            session_id="S0123456789abcdef",
            parent_task_id="T1",
            child_task_id="T1.1",
            artifact_root=tmp_path / "artifacts",
        )
    assert called is False


def test_trusted_parent_handoff_overrides_model_supplied_inline_context(
    tmp_path: Path,
) -> None:
    _ensure_runtime_tools_registered()
    model = ParentAndChildModel(tmp_path)
    trusted_content = {
        "model_name": "alpha-v2",
        "version": "trusted-2.0",
        "deployment_target": "paper-trading",
    }
    args = SpawnRiskScoutArgs(
        project_id="quantcode",
        event_id="model-handoff-42",
        objective="Locate the Risk Gate scope and process for this model handoff.",
        context_items=[
            {
                "context_ref": "model-spec",
                "kind": "ModelSpec",
                "locator": "model:inline-untrusted",
                "summary": "Model-supplied inline context must not replace parent context.",
                "content": {"version": "tampered"},
                "redacted": True,
            }
        ],
        max_iterations=8,
    )
    result = spawn_risk_scout_tool.execute(
        args,
        {
            "_model": model,
            "risk_registry_path": ROOT / ".review-ci" / "risk_gate_catalog.yaml",
            "risk_artifact_root": tmp_path / "trusted-artifacts",
            "risk_parent_context_items": [
                {
                    "context_ref": "model-spec",
                    "kind": "ModelSpec",
                    "locator": "blackboard:project:model.pr.42",
                    "summary": "Trusted redacted handoff.",
                    "content": trusted_content,
                    "redacted": True,
                }
            ],
        },
    )
    artifact = RiskGateTaskArtifact.model_validate(result["artifact"])
    expected_digest = hashlib.sha256(
        json.dumps(
            trusted_content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    context_evidence = next(
        item for item in artifact.evidence if item.context_refs == ["model-spec"]
    )
    assert context_evidence.content_sha256 == expected_digest
    assert context_evidence.locator == "blackboard:project:model.pr.42"

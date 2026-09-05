"""v5 top-level contract tests.

These tests intentionally encode the new boundary semantics instead of
preserving pre-v5 risk/budget/deploy gate behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from runner.agent_mcp_tool import RunAgentArgs, _run_agent_execute
from runner.agent_nodes import make_budget_check_node
from runner.routing.router import RouteDecision, route_next_step
from schemas.capability_card import CapabilityCard
from schemas.human_gate import HumanGateInterruptPayload
from tools.risk.statistics_stub import calc_risk_stub
from tools.strategy.deployment_candidate import deployment_candidate_execute, DeploymentCandidateArgs
from runner.task_classifier import classify_task
from runner.gitgraph_service import GitGraphBaselineStore, dependency_changes
from runner.pop_service import PopService
from schemas.pop import Pop
from datetime import datetime, timezone
from quantcode.identity_challenge import ChallengeStore, IdentityChallengeError
from runner.admin_operations import submit_deploy
from schemas.admin_deploy import AdminDeployRequest


ROOT = Path(__file__).resolve().parents[2]


def test_risk_verdict_does_not_create_human_gate() -> None:
    result = route_next_step(
        {
            "risk_metrics": calc_risk_stub("high_risk"),
            "risk_profile": {"scenario": "high_risk"},
        }
    )
    assert result.decision == RouteDecision.CONTINUE


def test_budget_exhaustion_is_runtime_stop() -> None:
    node = make_budget_check_node()
    result = node({"budget_tokens": 10, "budget_used": 11, "output_data": {}})
    assert result["status"] == "stopped_budget"
    assert result["output_data"]["budget_exhausted"] is True


def test_unauthenticated_run_agent_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTCODE_ALLOW_UNAUTH", raising=False)
    monkeypatch.delenv("QUANTCODE_ENV", raising=False)
    result = _run_agent_execute(RunAgentArgs(task="inspect"), ctx={})
    assert result["status"] == "error"
    assert "AUTHENTICATION_REQUIRED" in result["error"]


def test_strategy_tool_only_creates_admin_candidate() -> None:
    result = deployment_candidate_execute(
        DeploymentCandidateArgs(strategy_name="demo", verdict="pass"), {}
    )
    assert result["status"] == "pending_admin"
    assert result["deployed"] is False


def test_ordinary_tool_catalog_has_no_deploy() -> None:
    from quantcode import mcp_server

    assert "deploy_alphaflow" not in {tool.id for tool in mcp_server.registry.list_all()}


def test_human_gate_payload_whitelist() -> None:
    payload = HumanGateInterruptPayload(
        gate_id="hg_test",
        message="shared write",
        reasons=[],
        kind="merge",
    )
    assert payload.kind == "merge"
    with pytest.raises(ValueError):
        HumanGateInterruptPayload(
            gate_id="hg_risk",
            message="risk verdict",
            reasons=[],
            kind="risk",  # type: ignore[arg-type]
        )


def test_capability_card_v2_matches_json_schema() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "capability-card.schema.json").read_text(encoding="utf-8")
    )
    card = CapabilityCard(
        id="demo",
        name="Demo capability",
        type="asset",
        canonical_repo="org/demo",
        maturity_status="STAGING",
        integration_status="PARTIAL",
        when_to_use="when needed",
        when_not_to_reinvent="reuse this",
        owner_group="factor",
        distilled_at="2026-09-04",
    )
    jsonschema.validate(card.model_dump(), schema)


def test_task_classification_keeps_complexity_and_governance_separate() -> None:
    query = classify_task("查看组件状态")
    assert query.complexity == "L0"
    assert query.governance == "read_only"
    assert query.solution_required is False

    shared = classify_task("修改共享主线", file_count=1, shared_write=True)
    assert shared.complexity == "L3"
    assert shared.governance == "shared_write"
    assert shared.solution_required is True

    solution = classify_task("/solution 为 factor 组增加 export 脚本")
    assert solution.complexity == "L2"
    assert solution.solution_required is True

    with pytest.raises(PermissionError):
        classify_task("deploy artifact", deploy=True, admin=False)


def test_gitgraph_baseline_dependency_diff_and_pop_dedupe(tmp_path: Path) -> None:
    baseline = GitGraphBaselineStore(tmp_path / "baseline.json")
    assert baseline.changed("repo", "a1") == (None, "a1")
    baseline.save({"repo": "a1"})
    assert baseline.changed("repo", "a1") is None
    assert dependency_changes({"numpy": "1"}, {"numpy": "2"}) == [
        {"package": "numpy", "old_value": "1", "new_value": "2"}
    ]

    pop = Pop(
        pop_id="p1",
        type="package",
        repo_or_package="numpy",
        change_summary="1 → 2",
        old_value="1",
        new_value="2",
        observed_at=datetime.now(timezone.utc),
        source="github",
        visibility_context="actor:alice",
        dedupe_key="numpy:1:2",
    )
    service = PopService(tmp_path / "pops.db")
    assert service.put(pop) is True
    assert service.put(pop) is False
    assert service.update_status("p1", read=True, ack=True).ack_status == "acknowledged"


def test_ssh_challenge_is_one_time_and_bound_to_fingerprint() -> None:
    store = ChallengeStore(ttl_seconds=60)
    issued = store.issue("SHA256:test")
    with pytest.raises(IdentityChallengeError):
        store.consume(str(issued["challenge_id"]), "SHA256:other")
    with pytest.raises(IdentityChallengeError):
        store.consume(str(issued["challenge_id"]), "SHA256:test")

    issued = store.issue("SHA256:test")
    assert store.consume(str(issued["challenge_id"]), "SHA256:test") == issued["nonce"]


def test_admin_deploy_is_management_plane_and_truthfully_staging(tmp_path: Path) -> None:
    request = AdminDeployRequest(artifact_ref="artifact://factor/demo", target="production")
    with pytest.raises(PermissionError):
        submit_deploy(request, session_role="analyst", evidence_dir=tmp_path)
    with pytest.raises(PermissionError):
        submit_deploy(request, session_role="admin", evidence_dir=tmp_path)
    result = submit_deploy(request, session_role="admin", actor_id="admin-1", evidence_dir=tmp_path, database=tmp_path / "deployments.db")
    assert result.status == "STAGING"
    assert result.record_hash

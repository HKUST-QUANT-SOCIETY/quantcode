"""Tests for risk:gate LangGraph flow."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flows.risk_gate import (
    build_workflow,
    calc_risk_metrics,
    check_human_gate,
    finalize_output,
    generate_risk_profile,
    read_model_spec,
    resume_risk_gate,
    write_pr_comment,
)
from runner.compose_executor import execute_compose_flow, unregister_flow
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id
from schemas import RiskProfile
from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache


def _fixture_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _make_input_data(**overrides):
    data = {
        "scenario": "normal",
        "model_spec": _fixture_model_spec(),
        "pr_number": "42",
        "head_sha": "abcdef1234567890",
        "pr_url": "https://github.com/hkust-quant-society/quantcode/pull/42",
    }
    data.update(overrides)
    return data


def _flow_input(**overrides):
    data = _make_input_data(**overrides)
    return {
        "dedupe_db_path": overrides.get("dedupe_db_path"),
        "artifacts_root": overrides.get("artifacts_root", "artifacts/risk/pr-comments"),
        **{k: v for k, v in data.items() if k not in ("dedupe_db_path", "artifacts_root")},
    }


@pytest.fixture(autouse=True)
def cleanup():
    yield
    clear_checkpointer_cache()
    clear_write_pr_comment_dedupe_cache()
    unregister_flow("risk", "risk:gate")


def test_read_model_spec_parses_fixture():
    result = read_model_spec({"input_data": _make_input_data()})
    assert result["model_spec"]["model_name"] == "pb_roe_ranker"


def test_normal_nodes_chain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {
        "input_data": _make_input_data(
            dedupe_db_path=str(tmp_path / "dedupe.sqlite"),
            artifacts_root=str(tmp_path / "pr-comments"),
        ),
        "artifacts": [],
        "errors": [],
    }
    state.update(read_model_spec(state))
    state.update(calc_risk_metrics(state))
    profile_update = generate_risk_profile(state)
    state.update(profile_update)
    state["artifacts"] = list(profile_update.get("artifacts", []))
    state.update(check_human_gate(state))
    comment_update = write_pr_comment(state)
    state.update(comment_update)
    state["artifacts"] = list(profile_update.get("artifacts", [])) + list(
        comment_update.get("artifacts", [])
    )
    state.update(finalize_output(state))

    output = state["output_data"]
    assert output["status"] == "completed"
    assert output["acceptance"]["verdict"] == "pass"
    assert output["human_decision"] is None
    assert output["pr_comment"]["comment_id"].startswith("comment-42-")
    assert RiskProfile(**output["risk_profile"]).strategy_id == "pb_roe_ranker"
    assert output["gate_result"]["requires_human"] is False
    assert (tmp_path / state["artifacts"][0]).exists()
    assert (tmp_path / state["artifacts"][1]).exists()


def test_risk_gate_normal_flow_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    from flows.risk_gate import register_risk_gate_flow

    monkeypatch.chdir(tmp_path)
    thread_id = make_thread_id("risk", "risk:gate", ts=1, suffix="normal")
    register_risk_gate_flow(checkpoint_db=tmp_path / "checkpoints.db")

    result = execute_compose_flow(
        group="risk",
        flow_name="risk:gate",
        input_data=_flow_input(
            dedupe_db_path=str(tmp_path / "dedupe.sqlite"),
            artifacts_root=str(tmp_path / "pr-comments"),
        ),
        thread_id=thread_id,
    )

    assert result["errors"] == []
    output = result["output_data"]
    assert output["status"] == "completed"
    assert output["acceptance"]["verdict"] == "pass"
    assert all(check["passed"] for check in output["acceptance"]["checks"])
    assert output["human_decision"] is None
    assert output["pr_comment"]["comment_id"].startswith("comment-42-")
    assert RiskProfile(**output["risk_profile"]).max_drawdown == 0.08
    assert output["gate_result"]["requires_human"] is False
    assert any(path.endswith("-profile.json") for path in result["artifacts"])
    assert any("pr-comments" in path for path in result["artifacts"])
    assert all((tmp_path / path).exists() for path in result["artifacts"])


def test_high_risk_triggers_interrupt_pause(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    app = build_workflow(checkpoint_db=tmp_path / "checkpoints.db")
    thread_id = make_thread_id("risk", "risk:gate", ts=2, suffix="high-risk")
    config = {"configurable": {"thread_id": thread_id}}

    paused = app.invoke(
        {
            "group": "risk",
            "flow_name": "risk:gate",
            "thread_id": thread_id,
            "input_data": _flow_input(
                scenario="high_risk",
                dedupe_db_path=str(tmp_path / "dedupe.sqlite"),
                artifacts_root=str(tmp_path / "pr-comments"),
            ),
            "output_data": None,
            "artifacts": [],
            "errors": [],
        },
        config=config,
    )

    snapshot = app.get_state(config)
    assert snapshot.next == ("run_tool_pipeline",)
    assert paused.get("__interrupt__")
    interrupt_payload = paused["__interrupt__"][0].value
    assert interrupt_payload["message"] == "⏸️ 等待人工审批"
    assert interrupt_payload["gate_id"].startswith("hg_")
    assert interrupt_payload["risk_profile"]["strategy_id"] == "pb_roe_ranker"
    assert "max_drawdown" in interrupt_payload["reasons"]
    assert not any("pr-comments" in path for path in (paused.get("artifacts") or []))


def test_high_risk_approve_resumes_and_writes_comment(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    app = build_workflow(checkpoint_db=tmp_path / "checkpoints.db")
    thread_id = make_thread_id("risk", "risk:gate", ts=3, suffix="approve")
    config = {"configurable": {"thread_id": thread_id}}
    init_state = {
        "group": "risk",
        "flow_name": "risk:gate",
        "thread_id": thread_id,
        "input_data": _flow_input(
            scenario="high_risk",
            dedupe_db_path=str(tmp_path / "dedupe.sqlite"),
            artifacts_root=str(tmp_path / "pr-comments"),
        ),
        "output_data": None,
        "artifacts": [],
        "errors": [],
    }

    app.invoke(init_state, config=config)
    result = resume_risk_gate(app, thread_id, "approve")

    output = result["output_data"]
    assert result["gate_decision"] == "approve"
    assert output["status"] == "completed"
    assert output["human_decision"] == "approve"
    assert output["acceptance"]["verdict"] == "fail"
    assert any(not check["passed"] for check in output["acceptance"]["checks"])
    assert output["gate_result"]["decision"] == "approve"
    assert output["pr_comment"]["comment_id"].startswith("comment-42-")
    assert RiskProfile(**output["risk_profile"]).max_drawdown == 0.22
    assert any("pr-comments" in path for path in result["artifacts"])
    assert (tmp_path / result["artifacts"][-1]).exists()


def test_high_risk_reject_ends_without_comment(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    app = build_workflow(checkpoint_db=tmp_path / "checkpoints.db")
    thread_id = make_thread_id("risk", "risk:gate", ts=4, suffix="reject")
    config = {"configurable": {"thread_id": thread_id}}
    init_state = {
        "group": "risk",
        "flow_name": "risk:gate",
        "thread_id": thread_id,
        "input_data": _flow_input(
            scenario="high_risk",
            dedupe_db_path=str(tmp_path / "dedupe.sqlite"),
            artifacts_root=str(tmp_path / "pr-comments"),
        ),
        "output_data": None,
        "artifacts": [],
        "errors": [],
    }

    app.invoke(init_state, config=config)
    result = resume_risk_gate(app, thread_id, "reject")

    output = result["output_data"]
    assert result["gate_decision"] == "reject"
    assert output["status"] == "rejected"
    assert output["human_decision"] == "reject"
    assert output["pr_comment"] is None
    assert output["acceptance"]["verdict"] == "fail"
    assert any(not check["passed"] for check in output["acceptance"]["checks"])
    assert result.get("comment_id") is None
    assert not any("pr-comments" in path for path in (result.get("artifacts") or []))

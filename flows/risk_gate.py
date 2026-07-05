"""Day 3 risk:gate flow — normal path + HumanGate interrupt/resume."""
from __future__ import annotations

import json
import operator
import time
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from runner.acceptance import AcceptanceResult, run_acceptance as run_acceptance_checks
from schemas import ModelSpec, RiskProfile, RiskThresholds
from tools.risk.risk_tools import (
    calc_risk,
    check_gate,
    generate_risk_profile as build_risk_profile,
    read_blackboard,
    write_pr_comment as write_pr_comment_artifact,
)

try:
    from langgraph.types import Command, interrupt

    _INTERRUPT_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback path tested via flag
    Command = None  # type: ignore[assignment,misc]
    interrupt = None  # type: ignore[assignment]
    _INTERRUPT_AVAILABLE = False

HUMAN_REVIEW_NODE = "human_review"
_GATE_MESSAGE = "⏸️ 等待人工审批"


class RiskFlowState(TypedDict, total=False):
    """JSON-serializable state for risk:gate."""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    model_spec: dict[str, Any]
    risk_metrics: dict[str, Any]
    risk_profile: dict[str, Any]
    gate_check: dict[str, Any]
    gate_decision: str | None
    gate_id: str | None
    human_gate_payload: dict[str, Any] | None
    pr_comment: dict[str, str] | None
    acceptance: dict[str, Any]
    comment_id: str | None


def read_model_spec(state: RiskFlowState) -> dict[str, Any]:
    """从 input_data / blackboard 读取并校验 ModelSpec。"""
    blackboard = read_blackboard(state["input_data"])
    spec = ModelSpec(**blackboard["model_spec"])
    return {"model_spec": spec.model_dump(mode="json")}


def calc_risk_metrics(state: RiskFlowState) -> dict[str, Any]:
    """调用 risk tools 计算风控指标。"""
    input_data = state["input_data"]
    scenario = input_data.get("scenario", "normal")
    metrics = calc_risk(state["model_spec"], scenario=scenario)
    return {"risk_metrics": metrics}


def generate_risk_profile(state: RiskFlowState) -> dict[str, Any]:
    """生成 RiskProfile 并写入 artifact。"""
    input_data = state["input_data"]
    profile = build_risk_profile(
        state["model_spec"],
        state["risk_metrics"],
        pr_url=input_data.get("pr_url"),
    )
    profile_data = profile.model_dump(mode="json")

    artifact_path = Path("artifacts") / "risk" / f"{profile.strategy_id}-profile.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "risk_profile": profile_data,
        "artifacts": [artifact_path.as_posix()],
    }


def check_human_gate(state: RiskFlowState) -> dict[str, Any]:
    """检查是否需人工审批；超阈值时 interrupt 暂停 workflow。"""
    profile = RiskProfile(**state["risk_profile"])
    thresholds = RiskThresholds()
    gate_check = check_gate(profile, thresholds)

    if not gate_check["requires_human"]:
        return {"gate_check": gate_check}

    if _INTERRUPT_AVAILABLE and not state.get("gate_decision"):
        gate_id = _make_gate_id(state)
        resume_payload = interrupt(
            {
                "gate_id": gate_id,
                "message": _GATE_MESSAGE,
                "risk_profile": state["risk_profile"],
                "reasons": gate_check["reasons"],
            }
        )
        decision = resume_payload.get("decision") if isinstance(resume_payload, dict) else None
    else:
        gate_id = state.get("gate_id") or _make_gate_id(state)
        decision = state.get("gate_decision")

    updates: dict[str, Any] = {
        "gate_check": gate_check,
        "gate_id": gate_id,
        "gate_decision": decision,
        "human_gate_payload": {
            "gate_id": gate_id,
            "message": _GATE_MESSAGE,
            "risk_profile": state["risk_profile"],
            "reasons": gate_check["reasons"],
            "decision": decision,
        },
    }
    return updates


def human_review(state: RiskFlowState) -> dict[str, Any]:
    """人审节点：approve 后继续，reject 由 finalize_output 汇总结果。"""
    return {}


def write_pr_comment(state: RiskFlowState) -> dict[str, Any]:
    """写入 PR comment artifact。"""
    if state.get("gate_decision") == "reject":
        return {}

    input_data = state["input_data"]
    profile = RiskProfile(**state["risk_profile"])
    comment = write_pr_comment_artifact(
        profile,
        pr_number=str(input_data.get("pr_number", "demo")),
        head_sha=input_data.get("head_sha", "deadbeef"),
        pr_url=input_data.get("pr_url"),
        artifacts_root=input_data.get(
            "artifacts_root",
            "artifacts/risk/pr-comments",
        ),
        dedupe_db_path=input_data.get("dedupe_db_path"),
    )
    return {
        "comment_id": comment["comment_id"],
        "pr_comment": comment,
        "artifacts": [comment["artifact_path"]],
    }


def finalize_output(state: RiskFlowState) -> dict[str, Any]:
    """运行 acceptance 并组装最终 output_data。"""
    profile_data = state["risk_profile"]
    acceptance = run_acceptance_checks(
        "risk-gate",
        profile_data,
        thresholds=_risk_acceptance_thresholds(),
    )
    acceptance_data = _acceptance_to_dict(acceptance)

    gate_result = state.get("human_gate_payload") or state.get("gate_check") or {}
    human_decision = state.get("gate_decision")
    rejected = human_decision == "reject"
    status = "rejected" if rejected else "completed"
    pr_comment = None if rejected else state.get("pr_comment")

    return {
        "acceptance": acceptance_data,
        "output_data": {
            "status": status,
            "risk_profile": profile_data,
            "gate_result": gate_result,
            "human_decision": human_decision,
            "pr_comment": pr_comment,
            "acceptance": acceptance_data,
        },
    }


def _route_after_check(state: RiskFlowState) -> str:
    gate_check = state.get("gate_check") or {}
    if not gate_check.get("requires_human"):
        return "write_pr_comment"
    if state.get("gate_decision") == "reject":
        return "finalize_output"
    return HUMAN_REVIEW_NODE


def build_workflow(
    checkpoint_db: str | PathLike[str] | None = None,
    *,
    use_interrupt_before_fallback: bool = False,
):
    """Build the LangGraph app for risk:gate."""
    try:
        from langgraph.graph import END

        from runner.langgraph_base import (
            START,
            create_workflow,
            get_checkpointer,
        )
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph base is not available. Install langgraph and retry."
        ) from exc

    nodes = {
        "read_model_spec": read_model_spec,
        "calc_risk_metrics": calc_risk_metrics,
        "generate_risk_profile": generate_risk_profile,
        "check_human_gate": check_human_gate,
        HUMAN_REVIEW_NODE: human_review,
        "write_pr_comment": write_pr_comment,
        "finalize_output": finalize_output,
    }
    edges = [
        (START, "read_model_spec"),
        ("read_model_spec", "calc_risk_metrics"),
        ("calc_risk_metrics", "generate_risk_profile"),
        ("generate_risk_profile", "check_human_gate"),
        (HUMAN_REVIEW_NODE, "write_pr_comment"),
        ("write_pr_comment", "finalize_output"),
        ("finalize_output", END),
    ]
    workflow = create_workflow(nodes, edges, state_schema=RiskFlowState)
    workflow.add_conditional_edges(
        "check_human_gate",
        _route_after_check,
        {
            "write_pr_comment": "write_pr_comment",
            HUMAN_REVIEW_NODE: HUMAN_REVIEW_NODE,
            "finalize_output": "finalize_output",
        },
    )

    compile_kwargs: dict[str, Any] = {"checkpointer": get_checkpointer(checkpoint_db)}
    if use_interrupt_before_fallback or not _INTERRUPT_AVAILABLE:
        compile_kwargs["interrupt_before"] = [HUMAN_REVIEW_NODE]

    return workflow.compile(**compile_kwargs)


def register_risk_gate_flow(
    checkpoint_db: str | PathLike[str] | None = None,
    *,
    overwrite: bool = True,
):
    """Register risk:gate to FLOW_REGISTRY."""
    from runner.compose_executor import register_flow

    app = build_workflow(checkpoint_db)
    register_flow("risk", "risk:gate", app, overwrite=overwrite)
    return app


def resume_risk_gate(
    app: Any,
    thread_id: str,
    decision: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resume a paused risk:gate flow after human review."""
    if not _INTERRUPT_AVAILABLE or Command is None:
        raise RuntimeError("langgraph.types.Command is required to resume risk:gate")

    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if config:
        cfg.update(config)
    return app.invoke(Command(resume={"decision": decision}), config=cfg)


def _make_gate_id(state: RiskFlowState) -> str:
    thread_id = state.get("thread_id", "risk")
    safe_tid = thread_id.replace(":", "_").replace("/", "_")
    return f"hg_{safe_tid}_{int(time.time())}"


def _risk_acceptance_thresholds() -> dict[str, float]:
    limits = RiskThresholds()
    return {
        "max_drawdown": limits.max_drawdown,
        "position_limit": limits.position_limit_usage,
        "correlation_limit": limits.correlation_limit,
    }


def _acceptance_to_dict(result: AcceptanceResult) -> dict[str, Any]:
    return {
        "verdict": result.verdict,
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "message": check.message,
            }
            for check in result.checks
        ],
    }

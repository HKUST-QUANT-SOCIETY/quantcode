"""Risk gate orchestrator — tool-based path with LangGraph interrupt/resume.

Primary entry for risk:gate (PR #17). Tools are registered in tools/risk/_register.py
and filtered by .opencode/groups/risk/tool_allowlist.yaml.

两条路径:
- **CI / GitHub Actions**: 使用 ``build_risk_agent()`` + ``run_tool_pipeline`` 的确定性
  scripted pipeline（保留 interrupt/resume），适合确定性环境。
- **OpenCode ReAct**: 使用 ``run_risk_agent_react()``（基于 ``AgentRunner(group="risk")``），
  让 LLM 自主决定 tool 调用顺序，HumanGate interrupt 仍由 LangGraph 承载。
"""
from __future__ import annotations

import json
import operator
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from runner.acceptance import (
    AcceptanceResult,
    risk_thresholds,
    run_acceptance as run_acceptance_checks,
)
from runner.human_gate import (
    build_interrupt_payload,
    gate_check,
    make_gate_id,
    parse_resume_decision,
)
from schemas import ModelSpec, RiskProfile, RiskThresholds
from tools.risk.risk_tools import (
    calc_risk,
    generate_risk_profile as build_risk_profile,
    read_blackboard,
    write_pr_comment as write_pr_comment_artifact,
)

try:
    from langgraph.types import Command, interrupt

    _INTERRUPT_AVAILABLE = True
except ImportError:  # pragma: no cover
    Command = None  # type: ignore[assignment,misc]
    interrupt = None  # type: ignore[assignment]
    _INTERRUPT_AVAILABLE = False

HUMAN_REVIEW_NODE = "human_review"


class RiskAgentState(TypedDict, total=False):
    """JSON-serializable state for risk:gate agent."""

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


def run_tool_pipeline(state: RiskAgentState) -> dict[str, Any]:
    """Execute the risk tool sequence (scripted ReAct-compatible pipeline)."""
    input_data = state["input_data"]
    updates: dict[str, Any] = {"artifacts": []}

    blackboard = read_blackboard(input_data)
    spec = ModelSpec(**blackboard["model_spec"])
    model_spec = spec.model_dump(mode="json")
    updates["model_spec"] = model_spec

    scenario = input_data.get("scenario", "normal")
    risk_metrics = calc_risk(model_spec, scenario=scenario)
    updates["risk_metrics"] = risk_metrics

    profile = build_risk_profile(
        model_spec,
        risk_metrics,
        pr_url=input_data.get("pr_url"),
    )
    profile_data = profile.model_dump(mode="json")
    updates["risk_profile"] = profile_data

    artifact_path = Path("artifacts") / "risk" / f"{profile.strategy_id}-profile.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    updates["artifacts"] = [artifact_path.as_posix()]

    thresholds = RiskThresholds()
    check = gate_check(profile, thresholds)
    updates["gate_check"] = check

    if not check["requires_human"]:
        return updates

    gate_id = state.get("gate_id") or make_gate_id(state.get("thread_id", "risk"))
    if _INTERRUPT_AVAILABLE and not state.get("gate_decision"):
        resume_payload = interrupt(
            build_interrupt_payload(
                gate_id=gate_id,
                risk_profile=profile_data,
                reasons=check["reasons"],
            )
        )
        decision = parse_resume_decision(resume_payload)
    else:
        decision = state.get("gate_decision")

    updates.update({
        "gate_id": gate_id,
        "gate_decision": decision,
        "human_gate_payload": build_interrupt_payload(
            gate_id=gate_id,
            risk_profile=profile_data,
            reasons=check["reasons"],
            decision=decision,
        ),
    })
    return updates


def human_review(state: RiskAgentState) -> dict[str, Any]:
    """HumanGate placeholder node (interrupt_before fallback target)."""
    return {}


def write_pr_comment_node(state: RiskAgentState) -> dict[str, Any]:
    """Write PR comment artifact (skip on reject)."""
    if state.get("gate_decision") == "reject":
        return {}

    input_data = state["input_data"]
    profile = RiskProfile(**state["risk_profile"])
    comment_kwargs: dict[str, Any] = {
        "pr_number": str(input_data.get("pr_number", "demo")),
        "head_sha": input_data.get("head_sha", "deadbeef"),
        "pr_url": input_data.get("pr_url"),
        "artifacts_root": input_data.get("artifacts_root", "artifacts/risk/pr-comments"),
        "dedupe_db_path": input_data.get("dedupe_db_path"),
    }
    if "post_to_github" in input_data:
        comment_kwargs["post_to_github"] = input_data["post_to_github"]
    if input_data.get("github_repo"):
        comment_kwargs["github_repo"] = input_data["github_repo"]
    if input_data.get("github_token"):
        comment_kwargs["github_token"] = input_data["github_token"]
    comment = write_pr_comment_artifact(profile, **comment_kwargs)
    return {
        "comment_id": comment["comment_id"],
        "pr_comment": comment,
        "artifacts": [comment["artifact_path"]],
    }


def finalize_output(state: RiskAgentState) -> dict[str, Any]:
    """Run acceptance and assemble output_data."""
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


def _route_after_pipeline(state: RiskAgentState) -> str:
    gate_check_data = state.get("gate_check") or {}
    if not gate_check_data.get("requires_human"):
        return "write_pr_comment"
    if state.get("gate_decision") == "reject":
        return "finalize_output"
    return HUMAN_REVIEW_NODE


def build_risk_agent(
    checkpoint_db: str | PathLike[str] | None = None,
):
    """Build the LangGraph app for risk:gate (tool-based primary path)."""
    try:
        from langgraph.graph import END

        from runner.langgraph_base import START, create_workflow, get_checkpointer
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph base is not available. Install langgraph and retry."
        ) from exc

    nodes = {
        "run_tool_pipeline": run_tool_pipeline,
        HUMAN_REVIEW_NODE: human_review,
        "write_pr_comment": write_pr_comment_node,
        "finalize_output": finalize_output,
    }
    edges = [
        (START, "run_tool_pipeline"),
        (HUMAN_REVIEW_NODE, "write_pr_comment"),
        ("write_pr_comment", "finalize_output"),
        ("finalize_output", END),
    ]
    workflow = create_workflow(nodes, edges, state_schema=RiskAgentState)
    workflow.add_conditional_edges(
        "run_tool_pipeline",
        _route_after_pipeline,
        {
            "write_pr_comment": "write_pr_comment",
            HUMAN_REVIEW_NODE: HUMAN_REVIEW_NODE,
            "finalize_output": "finalize_output",
        },
    )

    compile_kwargs: dict[str, Any] = {"checkpointer": get_checkpointer(checkpoint_db)}
    if not _INTERRUPT_AVAILABLE:
        compile_kwargs["interrupt_before"] = [HUMAN_REVIEW_NODE]

    return workflow.compile(**compile_kwargs)


def register_risk_gate_flow(
    checkpoint_db: str | PathLike[str] | None = None,
    *,
    overwrite: bool = True,
):
    """Register risk:gate to FLOW_REGISTRY."""
    from runner.compose_executor import register_flow

    app = build_risk_agent(checkpoint_db)
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


def _risk_acceptance_thresholds() -> dict[str, float]:
    """acceptance 阈值单源：configs/acceptance.risk.yaml → RiskThresholds 兜底。

    yaml 单值以 runner.acceptance.risk_thresholds() 为出口（risk 组 yaml 未配置
    等场景回退 RiskThresholds 同源代码默认，行为与历史一致）。
    """
    limits = risk_thresholds()
    return {
        "max_drawdown": limits["max_drawdown"],
        "position_limit": limits["position_limit"],
        "correlation_limit": limits["correlation_limit"],
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


# ---------------------------------------------------------------------------
# Day 4: ReAct 路径 — AgentRunner(group="risk") + HumanGate interrupt
# ---------------------------------------------------------------------------


def run_risk_agent_react(
    task: str,
    *,
    model=None,
    checkpoint_db: str | PathLike[str] | None = None,
    thread_id: str | None = None,
    max_iterations: int = 10,
) -> dict:
    """用 AgentRunner(group="risk") 自主 ReAct 跑 risk 流程。

    与 ``build_risk_agent()`` 的 scripted pipeline 不同，本函数让 LLM 自主决定
    tool 调用顺序，实现真正的 ReAct 推理。HumanGate interrupt 通过
    ``route_gate_node`` 承载（当 LLM 调 check_gate 且返回 requires_human=True 时触发）。

    Args:
        task: 用户任务描述（如 "处理 PR #42 的风险检查"）。
        model: LLM callable。不传则尝试从 config.json 创建 DeepSeek LLM。
        checkpoint_db: SqliteSaver checkpoint 路径（必传，HumanGate checkpoint 需要）。
        thread_id: 显式指定 thread_id。
        max_iterations: 最大迭代步数。

    Returns:
        AgentRunner.run() 的最终 state dict。

    Raises:
        ValueError: model=None 且 config.json 未配置。

    Example::

        final = run_risk_agent_react(
            "处理 PR #42 的风险检查",
            checkpoint_db=".quantcode/checkpoints.db",
        )
        if "__interrupt__" in final:
            # 需要人审，在 UI 中展示 interrupt payload
            ...
    """
    from runner.agent_engine import AgentRunner

    if model is None:
        try:
            from runner.llm_provider import create_deepseek_llm

            model = create_deepseek_llm()
        except ValueError:
            raise ValueError(
                "run_risk_agent_react: model 未传且 config.json 未配置。"
                "请传入 model 参数或配置 config.json（参考 config.example.json）。"
            )

    if checkpoint_db is None:
        raise ValueError(
            "run_risk_agent_react: checkpoint_db 必传（HumanGate checkpoint 需要 SqliteSaver）。"
        )

    runner = AgentRunner(
        group="risk",
        model=model,
        checkpoint_db=checkpoint_db,
        max_iterations=max_iterations,
    )

    return runner.run(
        task=task,
        skill_name="risk-gate",
        system_prompt=(
            "You are a risk control agent. Your job is to:\n"
            "1. Read the blackboard with read_blackboard(input_data)\n"
            "2. Calculate risk metrics with calc_risk(model_spec, scenario)\n"
            "3. Generate a risk profile with generate_risk_profile(model_spec, risk_metrics)\n"
            "4. Check the gate with check_gate(risk_profile)\n"
            "5. If gate requires human review, stop and wait for approval\n"
            "6. If approved or no human review needed, write a PR comment with write_pr_comment\n\n"
            "Always proceed step by step. Call tools in order. "
            "If check_gate returns requires_human=True, stop and do NOT call write_pr_comment."
        ),
        thread_id=thread_id,
    )

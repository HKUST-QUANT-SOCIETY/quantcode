"""Day 2 factor:autoeval flow business nodes.

The node functions in this module are intentionally usable before the shared
LangGraph runner lands. `build_workflow()` wires them into LangGraph once
`runner.langgraph_base` is available.
"""
from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any, TypedDict

from runner.acceptance import AcceptanceResult, run_acceptance as run_acceptance_checks
from schemas import (
    DecayMetrics,
    FactorReport,
    FactorSpec,
    FactorVerdict,
    ICMetrics,
    LayeredBacktest,
    TurnoverMetrics,
)


class FactorFlowState(TypedDict, total=False):
    """JSON-serializable state for factor:autoeval."""

    group: str
    flow_name: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: list[str]
    errors: list[str]
    input_spec: dict[str, Any]
    eval_result: dict[str, Any]
    report: dict[str, Any]
    acceptance: dict[str, Any]
    _memory: Any  # compose_executor 注入的 MemoryService handle（node 端经 _memory() 解析）


def _memory(state: FactorFlowState) -> Any:
    """解析 compose_executor 注入的 MemoryService（state["_memory"] handle）。

    直接调 node（单测）或未注入 memory 时返回 None，各 node 据此跳过 memory 读写。
    """
    handle = state.get("_memory")
    if isinstance(handle, dict) and "_tid" in handle:
        from runner.compose_executor import get_memory

        return get_memory(handle["_tid"])
    return None


def validate_factor_spec(state: FactorFlowState) -> dict[str, Any]:
    """Validate raw input_data against FactorSpec; memory 注入时做 dedupe + 写 progress。"""
    spec = FactorSpec(**state["input_data"])
    input_spec = spec.model_dump(mode="json")

    memory = _memory(state)
    if memory is None:
        return {"input_spec": input_spec}

    group = state.get("group", "factor")
    # 先看是否已跑过同 input（dedupe：memory 当作跨 invoke 的"缓存"）
    cached = memory.search(
        query=spec.name,
        scope="groups",
        scope_id=group,
        type="progress",
        limit=1,
    )
    errors: list[str] = []
    if cached and cached[0].snippet:
        errors.append(
            f"validate_factor_spec: 命中 dedupe cache，跳过：{cached[0].path}"
        )
    else:
        memory.write(
            scope="groups",
            scope_id=group,
            type="progress",
            key="factor_validation",
            body=(
                "# validate_factor_spec\n\n"
                f"- factor_name: {spec.name}\n"
                "- validated_at: <ts>\n"
            ),
            requester_group=group,
        )
    return {"input_spec": input_spec, "errors": errors}


def call_autoeval_api(state: FactorFlowState) -> dict[str, Any]:
    """Return a deterministic Day 2 AutoEval result.

    Real AutoFactorEvaluation integration is intentionally deferred. This node
    preserves the public shape needed by report generation and acceptance tests.
    memory 注入时顺带查 history 上的 AutoEval 版本数。
    """
    spec = FactorSpec(**state["input_spec"])
    eval_result = _mock_autoeval_result(spec)

    memory = _memory(state)
    if memory is not None:
        history = memory.search(
            query="autoeval_version",
            scope="groups",
            scope_id=state.get("group", "factor"),
            type="memory",
            limit=3,
        )
        if history:
            eval_result["historical_versions_count"] = len(history)

    return {"eval_result": eval_result}


def generate_factor_report(state: FactorFlowState) -> dict[str, Any]:
    """Map AutoEval-style metrics to FactorReport and write the report artifact."""
    spec = FactorSpec(**state["input_spec"])
    eval_result = state["eval_result"]

    report = FactorReport(
        factor_name=spec.name,
        factor_version=eval_result.get("factor_version"),
        evaluation_period=spec.date_range,
        universe=spec.universe,
        ic_metrics=ICMetrics(
            ic_mean=eval_result["ic_mean"],
            ic_std=eval_result["ic_std"],
            ir=eval_result["ir"],
            t_stat=eval_result["t_stat"],
        ),
        turnover=TurnoverMetrics(
            monthly=eval_result["turnover_monthly"],
            annual=eval_result.get("turnover_annual"),
        ),
        decay=DecayMetrics(**eval_result.get("decay", {})),
        layered_backtest=LayeredBacktest(**eval_result.get("layered_backtest", {})),
        verdict=_report_verdict(eval_result),
        fail_reasons=list(eval_result.get("fail_reasons", [])),
        eval_run_id=eval_result.get("eval_run_id"),
        route_recommendation=eval_result.get("route_recommendation"),
        target_tier=eval_result.get("target_tier"),
        horizons=list(eval_result.get("horizons", [])),
        performance_tags=list(eval_result.get("performance_tags", [])),
        action_tags=list(eval_result.get("action_tags", [])),
        semantic_label=eval_result.get("semantic_label"),
        admission_reason=eval_result.get("admission_reason"),
    )

    report_data = report.model_dump(mode="json")
    artifact_path = Path("artifacts") / "factor" / f"{report.factor_name}-report.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    artifact = artifact_path.as_posix()

    # 写一条 notes 到 Memory（量化组员后续会读；未注入 memory 时跳过）
    memory = _memory(state)
    if memory is not None:
        group = state.get("group", "factor")
        memory.write(
            scope="groups",
            scope_id=group,
            type="notes",
            key=f"factor_report_{spec.name}",
            body=(
                "# factor_report\n\n"
                f"- factor: {spec.name}\n"
                f"- ic: {eval_result['ic_mean']}\n"
                f"- ir: {eval_result['ir']}\n"
                f"- artifact: {artifact}\n"
            ),
            requester_group=group,
        )

    return {
        "report": report_data,
        "output_data": report_data,
        "artifacts": [artifact],
    }


def run_acceptance(state: FactorFlowState) -> dict[str, Any]:
    """Run factor:autoeval acceptance checks against the generated report."""
    report = state["report"]
    result = run_acceptance_checks("factor:autoeval", report)
    return {"acceptance": _acceptance_to_dict(result)}


def build_workflow(checkpoint_db: str | PathLike[str] | None = None):
    """Build the LangGraph app once the shared runner base is available."""
    try:
        from runner.langgraph_base import (
            create_workflow,
            default_compose_edges,
            get_checkpointer,
        )
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph base is not available yet. Node functions can be tested "
            "directly; call build_workflow() after runner/langgraph_base.py lands."
        ) from exc

    nodes = {
        "validate": validate_factor_spec,
        "call_autoeval": call_autoeval_api,
        "generate_report": generate_factor_report,
        "acceptance": run_acceptance,
    }
    edges = default_compose_edges(["validate", "call_autoeval", "generate_report", "acceptance"])
    workflow = create_workflow(nodes, edges, state_schema=FactorFlowState)
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


def _mock_autoeval_result(spec: FactorSpec) -> dict[str, Any]:
    """Deterministic mock AutoEval payload for the Day 2 demo path."""
    payload = dict(MOCK_AUTOEVAL_PAYLOAD_V1)
    # spec 相关的动态字段
    payload["eval_run_id"] = f"{spec.name}-day2-mock-eval"
    payload["horizons"] = [1, spec.forward_return_horizon, 20]
    return payload


# Day 4 起:把 mock 字典提到模块级常量,tools/factor/autoeval.py 降级路径共享,
# 避免双维护。Lead 接真 AutoEval API 时只需替换 _mock_autoeval_result 函数体,
# autoeval 降级路径自动跟新(import 同一个常量)。
MOCK_AUTOEVAL_PAYLOAD_V1: dict[str, Any] = {
    "factor_version": "day2-mock",
    "eval_run_id": "stub-eval",  # generic;_mock_autoeval_result(spec) 会用 spec.name 覆盖
    "ic_mean": 0.045,
    "ic_std": 0.05625,
    "ir": 0.8,
    "t_stat": 2.5,
    "turnover_monthly": 0.25,
    "turnover_annual": 3.0,
        "decay": {
            "ic_1d": 0.055,
            "ic_3d": 0.050,
            "ic_5d": 0.045,
            "ic_10d": 0.035,
            "ic_20d": 0.025,
        },
        "layered_backtest": {
            "top_decile_annual_return": 0.12,
            "bottom_decile_annual_return": -0.03,
            "long_short_annual_return": 0.15,
            "long_short_sharpe": 1.1,
        },
        "route_recommendation": "tier3b_satellite",
        "target_tier": "Tier3B",
        "horizons": [1, 5, 20],  # generic;_mock_autoeval_result(spec) 会用 spec.forward_return_horizon 覆盖
        "performance_tags": ["day2_mock"],
        "action_tags": ["needs_real_autoeval_day3"],
        "semantic_label": "quality",
        "admission_reason": "Day 2 mock passes factor:autoeval acceptance thresholds",
        "fail_reasons": [],
    }


def _report_verdict(eval_result: dict[str, Any]) -> FactorVerdict:
    # 阈值单源 configs/acceptance.factor.yaml（架构决策 3「配置不喂 LLM」），
    # 经 runner.acceptance.factor_thresholds() 出口（内部已回退代码默认）。
    from runner.acceptance import factor_thresholds

    t = factor_thresholds()
    if eval_result.get("fail_reasons"):
        return FactorVerdict.FAIL
    if (
        abs(eval_result.get("ic_mean", 0.0)) >= t["ic_abs_min"]
        and eval_result.get("ir", 0.0) >= t["ir_min"]
        and eval_result.get("turnover_monthly", 1.0) <= t["turnover_monthly_max"]
        and eval_result.get("t_stat", 0.0) >= t["t_stat_min"]
    ):
        return FactorVerdict.PASS
    return FactorVerdict.MARGINAL


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

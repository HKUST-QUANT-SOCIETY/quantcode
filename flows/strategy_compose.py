"""strategy:compose Compose 流 — 信号筛选 → 组合权重 → 回测 → verdict。

节点序列（node 本体零业务逻辑，只串 tools/strategy 已注册的真实 tool）：
    select_signals   = select_signals（weight_hint 排序筛选）
    → combine_signals  = combine_signals（归一权重到 target_gross_exposure）
    → run_backtest     = run_strategy_backtest（StrategyReport stub 回测）
    → verdict          = 内联阈值判读：sharpe >= 0.5 且 max_drawdown <= 0.25 才 pass，
                         与 run_strategy_backtest 工具自身 verdict 规则对齐
                         （sharpe < 0.5 → fail；max_dd > 0.25 → needs_human）。

deploy_strategy 不放进流：needs_human 语义保留在工具层（人审由 HumanGate 处理）。

input_data 约定（对齐 schemas.strategy.StrategySpec 字段）：
    - strategy_name / as_of_date / candidates[{signal_id, source_group, weight_hint}]
    - max_positions / target_gross_exposure 可选
    - blackboard_db_path 可选（本流当前不写 blackboard，占位对齐其他流）

import flows.strategy_compose 即注册 ("strategy", "strategy:compose") 到 FLOW_REGISTRY
（注册语句在 runner/compose_executor.py 底部统一 import）。
"""
from __future__ import annotations

import json
import operator
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from tools.registry import registry

# 触发 strategy 组 tool 注册（幂等）
import tools.strategy._register  # noqa: F401

# verdict 内联阈值（与 tools/strategy/run_strategy_backtest.py 的工具层规则一致）
SHARPE_MIN = 0.5
MAX_DD_MAX = 0.25


class StrategyComposeFlowState(TypedDict, total=False):
    """strategy:compose 流的 state（风格对齐 FactorFlowState）。"""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    selected: dict[str, Any]
    weights: dict[str, Any]
    backtest_report: dict[str, Any]
    verdict: dict[str, Any]
    _memory: Any


def _ctx(state: StrategyComposeFlowState) -> dict[str, Any]:
    return {
        "thread_id": state.get("thread_id") or "strategy-compose-flow",
        "group": state.get("group") or "strategy",
    }


def select_signals_node(state: StrategyComposeFlowState) -> dict[str, Any]:
    """select_signals：候选按 weight_hint 排序筛选。"""
    input_data = state.get("input_data") or {}
    args: dict[str, Any] = {"candidates": input_data["candidates"]}
    if input_data.get("max_positions") is not None:
        args["max_positions"] = input_data["max_positions"]
    elif input_data.get("signal_ids") is not None and input_data.get("weight_hints") is not None:
        raise ValueError(
            "strategy:compose expects candidates[], not parallel signal_ids/weight_hints"
        )
    result = registry.call("select_signals", args, _ctx(state))
    return {"selected": result}


def combine_signals_node(state: StrategyComposeFlowState) -> dict[str, Any]:
    """combine_signals：selected → weight（sum = target_gross_exposure）。"""
    input_data = state.get("input_data") or {}
    args: dict[str, Any] = {"selected": state["selected"]["selected"]}
    if input_data.get("target_gross_exposure") is not None:
        args["target_gross_exposure"] = input_data["target_gross_exposure"]
    result = registry.call("combine_signals", args, _ctx(state))
    if not result["weights"]:
        raise RuntimeError(
            "combine_signals produced empty weights — check strategy:compose input_data"
        )
    return {"weights": result}


def run_strategy_backtest_node(state: StrategyComposeFlowState) -> dict[str, Any]:
    """run_strategy_backtest：weights → StrategyReport（stub 回测）。"""
    input_data = state.get("input_data") or {}
    args = {
        "strategy_name": input_data["strategy_name"],
        "as_of_date": input_data["as_of_date"],
        "weights": state["weights"]["weights"],
    }
    if input_data.get("lookback_days") is not None:
        args["lookback_days"] = input_data["lookback_days"]
    report = registry.call("run_strategy_backtest", args, _ctx(state))
    return {"backtest_report": report}


def strategy_verdict_node(state: StrategyComposeFlowState) -> dict[str, Any]:
    """内联 verdict：sharpe >= 0.5 且 max_drawdown <= 0.25 才 pass。"""
    report = state["backtest_report"]
    backtest = report.get("backtest", {})
    sharpe = backtest.get("sharpe")
    max_dd = backtest.get("max_drawdown")

    fail_reasons: list[str] = []
    if sharpe is None or sharpe < SHARPE_MIN:
        fail_reasons.append(f"sharpe {sharpe} < {SHARPE_MIN}")
    if max_dd is None or max_dd > MAX_DD_MAX:
        fail_reasons.append(f"max_drawdown {max_dd} > {MAX_DD_MAX}")

    verdict = "pass" if not fail_reasons else "fail"
    output = {
        "strategy_name": report["strategy_name"],
        "as_of_date": report["as_of_date"],
        "selected_signals": report["selected_signals"],
        "backtest": backtest,
        "tool_verdict": report.get("verdict"),
        "verdict": verdict,
        "fail_reasons": fail_reasons,
        "note": (
            "deploy_strategy not part of this flow; "
            "needs_human semantics stay in the tool layer (HumanGate)"
        ),
    }

    artifact_path = (
        Path("artifacts") / "strategy" / f"{report['strategy_name']}-report.json"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"verdict": output, "output_data": output, "artifacts": [artifact_path.as_posix()]}


def build_workflow(checkpoint_db: str | PathLike[str] | None = None):
    """Build the LangGraph app（结构对齐 flows.factor_autoeval.build_workflow）。"""
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
        "select_signals": select_signals_node,
        "combine_signals": combine_signals_node,
        "run_backtest": run_strategy_backtest_node,
        "verdict": strategy_verdict_node,
    }
    edges = default_compose_edges(list(nodes.keys()))
    workflow = create_workflow(nodes, edges, state_schema=StrategyComposeFlowState)
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


# ---------------------------------------------------------------------------
# 注册（import 即注册）
# ---------------------------------------------------------------------------

_FLOW_GROUP = "strategy"
_FLOW_NAME = "strategy:compose"


def register(overwrite: bool = False) -> None:
    from runner.compose_executor import register_flow

    register_flow(_FLOW_GROUP, _FLOW_NAME, build_workflow(), overwrite=overwrite)


def _auto_register() -> None:
    try:
        register(overwrite=False)
    except KeyError:
        pass


_auto_register()
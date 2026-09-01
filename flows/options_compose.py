"""options:compose Compose 流 — 波动率曲面 → Greeks → 日频回测 → verdict。

节点序列（node 本体零业务逻辑，只串 tools/options 已注册的真实 tool）：
    build_vol_surface = build_vol_surface（BS 反推 IV，落 vol_surface.json artifact）
    → calc_greeks       = calc_greeks（读 surface artifact 计算组合 Greeks）
    → run_stub_backtest = run_options_backtest_stub（Day6 真实现：日频 BS 盯市
                          回测 engine=="options_v1"，节点名保留历史 id 防链路断）
    → verdict           = 内联判定：surface quality != "mock" 且 Greeks 四项非零才 pass；
                          回测以 report.engine 标注真实引擎版本。

input_data 约定（对齐 schemas.options.OptionsSpec 字段）：
    - strategy_name / underlying / as_of_date / data_path
    - forward_price / risk_free_rate / call_quantity / put_quantity 可选
    - backtest_start_date / backtest_end_date 可选（缺省 as_of_date 前后 30 天，
      仅用于 stub 回测区间参数，不影响策略逻辑）

import flows.options_compose 即注册 ("options", "options:compose") 到 FLOW_REGISTRY
（注册语句在 runner/compose_executor.py 底部统一 import）。
"""
from __future__ import annotations

import json
import operator
from datetime import date, timedelta
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from tools.registry import registry

# 触发 options 组 tool 注册（幂等）
import tools.options._register  # noqa: F401


class OptionsComposeFlowState(TypedDict, total=False):
    """options:compose 流的 state（风格对齐 FactorFlowState）。"""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    vol_surface: dict[str, Any]
    greeks: dict[str, Any]
    stub_backtest: dict[str, Any]
    verdict: dict[str, Any]
    _memory: Any


def _ctx(state: OptionsComposeFlowState) -> dict[str, Any]:
    return {
        "thread_id": state.get("thread_id") or "options-compose-flow",
        "group": state.get("group") or "options",
    }


def _parse_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw))


def build_vol_surface_node(state: OptionsComposeFlowState) -> dict[str, Any]:
    """build_vol_surface：期权链数据 → IV 曲面（写 vol_surface.json）。"""
    input_data = state.get("input_data") or {}
    args: dict[str, Any] = {
        "strategy_name": input_data["strategy_name"],
        "underlying": input_data["underlying"],
        "as_of_date": input_data["as_of_date"],
    }
    if input_data.get("data_path"):
        args["data_path"] = input_data["data_path"]
    if input_data.get("forward_price") is not None:
        args["forward_price"] = input_data["forward_price"]
    if input_data.get("risk_free_rate") is not None:
        args["risk_free_rate"] = input_data["risk_free_rate"]
    surface = registry.call("build_vol_surface", args, _ctx(state))

    artifacts: list[str] = []
    if surface.get("artifact_path"):
        artifacts.append(surface["artifact_path"])
    return {"vol_surface": surface, "artifacts": artifacts}


def calc_greeks_node(state: OptionsComposeFlowState) -> dict[str, Any]:
    """calc_greeks：surface + 持仓 → 组合 Greeks。"""
    input_data = state.get("input_data") or {}
    surface = state["vol_surface"]
    args: dict[str, Any] = {
        "underlying": surface["underlying"],
        "as_of_date": surface["as_of_date"],
        "spot_price": surface["forward_price"],
    }
    if input_data.get("call_quantity") is not None:
        args["call_quantity"] = input_data["call_quantity"]
    if input_data.get("put_quantity") is not None:
        args["put_quantity"] = input_data["put_quantity"]
    if surface.get("artifact_path"):
        args["surface_artifact_path"] = surface["artifact_path"]
    greeks = registry.call("calc_greeks", args, _ctx(state))
    return {"greeks": greeks}


def run_options_backtest_stub_node(state: OptionsComposeFlowState) -> dict[str, Any]:
    """run_stub_backtest：真实现日频 BS 盯市回测（engine == options_v1）。"""
    input_data = state.get("input_data") or {}
    as_of = _parse_date(input_data["as_of_date"])
    end_raw = input_data.get("backtest_end_date")
    start_raw = input_data.get("backtest_start_date")
    end = _parse_date(end_raw) if end_raw else as_of
    start = _parse_date(start_raw) if start_raw else end - timedelta(days=30)
    report = registry.call(
        "run_options_backtest_stub",
        {
            "strategy_name": input_data["strategy_name"],
            "underlying": input_data["underlying"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        _ctx(state),
    )
    # Day6 真实化：守卫从「notes 含 stub」升级为引擎标注（契约单源 schemas/options.py）
    if report.get("engine") != "options_v1":
        raise RuntimeError(
            "run_options_backtest_stub report must carry engine == 'options_v1'; refusing flow output"
        )
    return {"stub_backtest": report}


def options_verdict_node(state: OptionsComposeFlowState) -> dict[str, Any]:
    """内联 verdict：quality != mock 且 Greeks 四项齐才 pass；回测 engine 标注。"""
    surface = state["vol_surface"]
    greeks = state["greeks"]
    backtest = state["stub_backtest"]

    quality = surface.get("data_quality") or "mock"
    portfolio = greeks.get("portfolio_greeks", {})
    greeks_ok = all(
        portfolio.get(k) not in (None, 0)
        for k in ("delta", "gamma", "vega", "theta")
    )

    fail_reasons: list[str] = []
    if quality == "mock":
        fail_reasons.append(f"surface data_quality == mock (quality={quality})")
    if not greeks_ok:
        fail_reasons.append("portfolio greeks incomplete/zero (delta/gamma/vega/theta)")

    verdict = "pass" if not fail_reasons else "fail"
    output = {
        "strategy_name": backtest["strategy_name"],
        "underlying": surface["underlying"],
        "surface_data_quality": quality,
        "surface_backend": surface.get("interpolation_method"),
        "greeks": portfolio,
        "stub_backtest": backtest,
        "backtest_note": backtest.get("engine"),  # Day6：真引擎标注（原恒 "stub"）
        "tool_notes": backtest.get("notes"),
        "verdict": verdict,
        "fail_reasons": fail_reasons,
    }

    artifact_path = (
        Path("artifacts") / "options" / f"{backtest['strategy_name']}-stub-report.json"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
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
        "build_vol_surface": build_vol_surface_node,
        "calc_greeks": calc_greeks_node,
        "run_stub_backtest": run_options_backtest_stub_node,
        "verdict": options_verdict_node,
    }
    edges = default_compose_edges(list(nodes.keys()))
    workflow = create_workflow(nodes, edges, state_schema=OptionsComposeFlowState)
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


# ---------------------------------------------------------------------------
# 注册（import 即注册）
# ---------------------------------------------------------------------------

_FLOW_GROUP = "options"
_FLOW_NAME = "options:compose"


def register(overwrite: bool = False) -> None:
    from runner.compose_executor import register_flow

    register_flow(_FLOW_GROUP, _FLOW_NAME, build_workflow(), overwrite=overwrite)


def _auto_register() -> None:
    try:
        register(overwrite=False)
    except KeyError:
        pass


_auto_register()
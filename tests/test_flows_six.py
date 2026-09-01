"""tests/test_flows_six.py — 四条新 Compose 流 smoke 测试。

覆盖流（每个测试一条：构造输入 → invoke → 断言最终 state 的产物/verdict 键）：
- ("model", "model:submit")            flows/model_submit.py
- ("strategy", "strategy:compose")     flows/strategy_compose.py
- ("options", "options:compose")       flows/options_compose.py
- ("fundamental", "fundamental:research") flows/fundamental_research.py

测试模式：ScriptedLLM 不适用（Compose 流没有 LLM 节点），这里按
tests/test_factor_autoeval_flow.py 的模式直接构造 state / 调 node 函数，
并各附一条 build_workflow().invoke 全图 smoke。

Stub 行为如实标注：
- extract_financial 是 hash 造数 stub（revenue/ebit/fcf 由 ticker 字符序数 seed 派生），
  本测试只断言结构链路，不做真数据。
- run_strategy_backtest / run_options_backtest_stub / build_vol_surface（数据缺失时）
  与 dcf_valuation 均为 stub，产出 deterministic mock 指标。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from runner.langgraph_base import clear_checkpointer_cache, make_thread_id

pytest.importorskip("langgraph")
pytest.importorskip("langgraph.checkpoint.sqlite")


@pytest.fixture(autouse=True)
def _ensure_flow_tools_registered():
    """确保四条流依赖的 tool 已注册。

    其他测试文件（test_agent_nodes / test_cross_group_stability 等）用
    ``registry._tools.clear()`` 清空全局 registry；模块级 ``_register`` import
    只跑一次。这里按 test_day5_jerry_demos.py 的同款方式每个测试前显式
    reload 注册模块，防止撞上空 registry（KeyError: Tool 'read_pr' not found）。
    """
    import importlib
    import tools.fundamental._register as fundamental_register
    import tools.model._register as model_register
    import tools.options._register as options_register
    import tools.strategy._register as strategy_register

    importlib.reload(model_register)
    importlib.reload(strategy_register)
    importlib.reload(options_register)
    importlib.reload(fundamental_register)
    yield

# ---------------------------------------------------------------------------
# 1) model:submit
# ---------------------------------------------------------------------------

MODEL_PR_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_model_pr" / "README.md"


def _model_input() -> dict:
    return {"pr_path": str(MODEL_PR_FIXTURE)}


def test_model_submit_flow_state(tmp_path, monkeypatch):
    """model:submit：README fixture → ModelSpec → blackboard + risk review。"""
    monkeypatch.chdir(tmp_path)
    from flows.model_submit import ModelSubmitFlowState  # noqa: F401

    from flows.model_submit import (
        build_workflow,
        generate_model_spec_node,
        handoff_to_risk,
        parse_pr_input,
        produce_output,
    )

    state: dict = {
        "group": "model",
        "flow_name": "model:submit",
        "thread_id": "t-model-smoke",
        "input_data": {
            **_model_input(),
            "blackboard_db_path": str(tmp_path / "blackboard.db"),
        },
        "artifacts": [],
        "errors": [],
    }
    state.update(parse_pr_input(state))
    state.update(generate_model_spec_node(state))
    state.update(handoff_to_risk(state))
    state.update(produce_output(state))

    assert state["model_spec"]["model_name"] == "pb_roe_ranker"
    assert state["model_spec"]["model_type"] == "boosting"
    assert state["handoff"]["risk_review"]["to_group"] == "risk"
    assert state["handoff"]["risk_review"]["status"] == "pending"
    assert state["output_data"]["blackboard_key"].startswith("model.pb_roe_ranker_spec")
    assert (tmp_path / state["artifacts"][0]).exists()


def test_model_submit_langgraph_invoke(tmp_path, monkeypatch):
    """model:submit 全图 compile+invoke smoke。"""
    from flows.model_submit import build_workflow

    monkeypatch.chdir(tmp_path)
    app = build_workflow(checkpoint_db=tmp_path / "ckpt.db")
    thread_id = make_thread_id("model", "model:submit", ts=11, suffix="smoke")
    try:
        result = app.invoke(
            {
                "group": "model",
                "flow_name": "model:submit",
                "thread_id": thread_id,
                "input_data": {
                    **_model_input(),
                    "blackboard_db_path": str(tmp_path / "blackboard.db"),
                },
                "output_data": None,
                "artifacts": [],
                "errors": [],
            },
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        clear_checkpointer_cache()

    assert result["output_data"]["model_spec"]["model_name"] == "pb_roe_ranker"
    assert result["handoff"]["risk_review"]["status"] == "pending"
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# 2) strategy:compose
# ---------------------------------------------------------------------------

def _strategy_input() -> dict:
    return {
        "strategy_name": "dual_momentum_smoke",
        "as_of_date": "2026-06-30",
        "candidates": [
            {"signal_id": "pb_roe", "source_group": "factor", "weight_hint": 0.5},
            {"signal_id": "momentum20", "source_group": "factor", "weight_hint": 0.7},
        ],
    }


def test_strategy_compose_flow_state(tmp_path, monkeypatch):
    """strategy:compose：select → combine → backtest → verdict（阈值内联）。"""
    from flows.strategy_compose import (
        combine_signals_node,
        run_strategy_backtest_node,
        select_signals_node,
        strategy_verdict_node,
    )

    monkeypatch.chdir(tmp_path)
    state: dict = {
        "group": "strategy",
        "flow_name": "strategy:compose",
        "thread_id": "t-strategy-smoke",
        "input_data": _strategy_input(),
        "artifacts": [],
        "errors": [],
    }
    state.update(select_signals_node(state))
    state.update(combine_signals_node(state))
    state.update(run_strategy_backtest_node(state))
    state.update(strategy_verdict_node(state))

    # stub 回测指标由 weight 分散度决定；双信号权重小 → sharpe 高、回撤低 → pass
    assert state["weights"]["weights"], "weights must be non-empty"
    verdict = state["verdict"]
    assert verdict["verdict"] == "pass"
    assert verdict["fail_reasons"] == []
    assert verdict["backtest"]["sharpe"] >= 0.5
    assert verdict["backtest"]["max_drawdown"] <= 0.25
    assert (tmp_path / state["artifacts"][0]).exists()


def _invoke_registered(group, flow_name, input_data, tmp_path, ts):
    """走 FLOW_REGISTRY 的全图 smoke helper。

    自动注册的 app 绑定默认 checkpoint DB；这里按 test_factor_autoeval_flow.py
    的方式用 tmp checkpoint db 重新 build + overwrite 注册，测试后还原，
    避免 clear_checkpointer_cache() 关闭共享连接导致 "closed database"。
    """
    from runner.compose_executor import (
        FLOW_REGISTRY,
        execute_compose_flow,
        register_flow,
        unregister_flow,
    )

    saved_app = FLOW_REGISTRY.get((group, flow_name))
    flow_mod = {
        "model": "flows.model_submit",
        "strategy": "flows.strategy_compose",
        "options": "flows.options_compose",
        "fundamental": "flows.fundamental_research",
    }[group]
    import importlib

    module = importlib.import_module(flow_mod)
    # 先清缓存（关掉共享默认 conn），再 build 绑定 tmp ckpt 的新 app
    clear_checkpointer_cache()
    register_flow(
        group, flow_name, module.build_workflow(checkpoint_db=tmp_path / "ckpt.db"),
        overwrite=True,
    )
    try:
        return execute_compose_flow(
            group=group,
            flow_name=flow_name,
            input_data=input_data,
            thread_id=make_thread_id(group, flow_name, ts=ts, suffix="smoke"),
        )
    finally:
        FLOW_REGISTRY.pop((group, flow_name), None)
        if saved_app is not None:
            FLOW_REGISTRY[(group, flow_name)] = saved_app
        clear_checkpointer_cache()


def test_strategy_compose_langgraph_invoke(tmp_path, monkeypatch):
    """strategy:compose 全图 smoke：走 FLOW_REGISTRY（注册在 import 时）。"""
    from runner.compose_executor import execute_compose_flow  # noqa: F401

    monkeypatch.chdir(tmp_path)
    result = _invoke_registered(
        "strategy", "strategy:compose", _strategy_input(), tmp_path, ts=12
    )

    assert result["errors"] == []
    assert result["state"]["verdict"]["verdict"] == "pass"
    assert "deploy_strategy" in result["output_data"]["note"]


# ---------------------------------------------------------------------------
# 3) options:compose
# ---------------------------------------------------------------------------

def _options_input() -> dict:
    return {
        "strategy_name": "gc_covered_call_smoke",
        "underlying": "GC",
        "as_of_date": "2026-06-27",
        "data_path": "data/sample_options/gc_options_merged_sample.csv",
        "call_quantity": 10,
        "put_quantity": 0,
    }


def test_options_compose_flow_state(tmp_path, monkeypatch):
    """options:compose：vol surface → greeks → stub backtest → verdict。"""
    from flows.options_compose import (
        build_vol_surface_node,
        calc_greeks_node,
        options_verdict_node,
        run_options_backtest_stub_node,
    )
    from tools.registry import PROJECT_ROOT as TOOL_PROJECT_ROOT

    monkeypatch.chdir(tmp_path)
    state: dict = {
        "group": "options",
        "flow_name": "options:compose",
        "thread_id": "t-options-smoke",
        "input_data": _options_input(),
        "artifacts": [],
        "errors": [],
    }
    state.update(build_vol_surface_node(state))
    state.update(calc_greeks_node(state))
    state.update(run_options_backtest_stub_node(state))
    state.update(options_verdict_node(state))

    # sample CSV 真行 → quality=sample_bs_iv（非 mock）
    assert state["vol_surface"]["data_quality"] == "sample_bs_iv"
    portfolio = state["greeks"]["portfolio_greeks"]
    assert all(portfolio[k] != 0 for k in ("delta", "gamma", "vega", "theta"))
    # Day6 真实化：回测为引擎标注（原 notes 含 "stub"，现 engine=="options_v1"）
    assert state["stub_backtest"]["engine"] == "options_v1"
    assert state["verdict"]["verdict"] == "pass"
    assert state["verdict"]["backtest_note"] == "options_v1"
    # build_vol_surface 落盘在工具层绝对路径 PROJECT_ROOT/artifacts/...（不改 cwd）
    assert (
        TOOL_PROJECT_ROOT / "artifacts" / "options" / "gc_covered_call_smoke" / "vol_surface.json"
    ).exists()


def test_options_compose_langgraph_invoke(tmp_path, monkeypatch):
    """options:compose 全图 smoke（artifact 落 tmp cwd）。"""
    from runner.compose_executor import execute_compose_flow  # noqa: F401

    monkeypatch.chdir(tmp_path)
    result = _invoke_registered(
        "options", "options:compose", _options_input(), tmp_path, ts=13
    )

    assert result["errors"] == []
    assert result["output_data"]["verdict"] == "pass"
    assert result["output_data"]["backtest_note"] == "options_v1"


# ---------------------------------------------------------------------------
# 4) fundamental:research
# ---------------------------------------------------------------------------

def _fundamental_input() -> dict:
    return {
        "target_identifier": "2097.HK",
        "target_name": "蜜雪冰城",
        "as_of_date": "2024-06-30",  # fixture 中 3 篇 <= 此日期，DOC-LEAK-2026 被过滤
        "research_questions": ["蜜雪冰城的增长驱动与估值合理性？"],
        "wacc": 0.10,
        "growth_rate": 0.08,
    }


def test_fundamental_research_flow_state(tmp_path, monkeypatch):
    """fundamental:research：PIT 检索 → extract → DCF → render → acceptance。

    注：extract_financial 为 hash 造数 stub（非真数据），本测试仅验证链路与键。
    """
    from flows.fundamental_research import (
        build_workflow as _build,  # noqa: F401  确保 tool 注册
        dcf_valuation_node,
        extract_financial_node,
        pit_rag_search_node,
        render_report_node,
        run_acceptance,
    )

    state: dict = {
        "group": "fundamental",
        "flow_name": "fundamental:research",
        "thread_id": "t-fundamental-smoke",
        "input_data": _fundamental_input(),
        "artifacts": [],
        "errors": [],
    }
    state.update(pit_rag_search_node(state))
    state.update(extract_financial_node(state))
    state.update(dcf_valuation_node(state))
    state.update(render_report_node(state))
    state.update(run_acceptance(state))

    assert state["pit_result"]["pit_rule"] == "published_at <= as_of_date"
    assert state["pit_result"]["filtered_count"] >= 1  # DOC-LEAK-2026 被 PIT 过滤
    assert state["financials"]["fcf_ttm"] > 0  # stub hash 造数，非真实财务
    assert state["dcf_result"]["fair_value_per_share"] > 0
    assert state["research_report"]["markdown_path"].startswith("artifacts/research/")
    # typst 未安装 → pdf 缺失，_check_research_pdf 的 pdf_rendered 失败 → 整体 fail
    assert state["research_report"]["pdf_path"] is None
    assert state["research_report"]["typst_used"] is False
    assert state["acceptance"]["verdict"] == "fail"
    names = {c["name"] for c in state["acceptance"]["checks"]}
    assert {"pdf_rendered", "sections_complete", "citations"} <= names
    assert state["output_data"]["citations_count"] >= 1


def test_fundamental_research_langgraph_invoke(tmp_path, monkeypatch):
    """fundamental:research 全图 smoke；acceptance 复用 research-pdf 规则。"""
    from runner.compose_executor import execute_compose_flow  # noqa: F401

    monkeypatch.chdir(tmp_path)
    result = _invoke_registered(
        "fundamental", "fundamental:research", _fundamental_input(), tmp_path, ts=14
    )

    state = result["state"]
    assert state["dcf_result"]["equity_value"] > 0
    # render_report 落盘在工具层绝对路径 PROJECT_ROOT/artifacts/research/（不改 cwd）
    from tools.registry import PROJECT_ROOT as TOOL_PROJECT_ROOT

    assert (
        TOOL_PROJECT_ROOT / state["research_report"]["markdown_path"]
    ).exists()
    assert state["acceptance"]["verdict"] in ("pass", "fail")


# ---------------------------------------------------------------------------
# 注册方式验证：import 即注册（compose_executor 底部统一 import）
# ---------------------------------------------------------------------------

def test_four_flows_registered_at_import():
    from runner.compose_executor import FLOW_REGISTRY

    expected = [
        ("fundamental", "fundamental:research"),
        ("model", "model:submit"),
        ("options", "options:compose"),
        ("strategy", "strategy:compose"),
    ]
    for key in expected:
        assert key in FLOW_REGISTRY, f"{key} not registered at import"
        assert FLOW_REGISTRY[key] is not None
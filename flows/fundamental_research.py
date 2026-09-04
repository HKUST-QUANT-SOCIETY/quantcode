"""fundamental:research Compose 流 — PIT 检索 → 财务提取 → DCF → 研报 → 验收。

节点序列（node 本体零业务逻辑，只串 tools/fundamental 已注册的真实 tool）：
    pit_rag_search   = pit_rag_search（Chroma / fixture 语料，强制 published_at <= as_of_date）
    → extract_financial = extract_financial（stub：ticker hash 造数，source_doc_ids 取
                          documents id；测试中不做真数据）
    → dcf_valuation     = dcf_valuation（Gordon DCF stub，输入 fcf 来自上一步）
    → render_report     = render_report（markdown + 可选 Typst PDF artifact）
    → acceptance        = 复用 runner/acceptance.py 的 _check_research_pdf 规则
                          （skill="research-pdf"）：pdf_rendered / sections / citations；
                          typst 缺失时 pdf 必然失败 → 整体 fail，与工具层行为一致。

input_data 约定（对齐 schemas.fundamental.ResearchSpec 字段）：
    - target_identifier / as_of_date / research_questions（list[str]）
    - target_name / growth_rate / wacc / top_k 可选
    - force_fixture 可选（True 跳过 Chroma 仅读 fixture，测试稳定）；本流默认 True，
      复现 agent 侧用法可控语义

import flows.fundamental_research 即注册 ("fundamental", "fundamental:research")
到 FLOW_REGISTRY（注册语句在 runner/compose_executor.py 底部统一 import）。
"""
from __future__ import annotations

import operator
from os import PathLike
from typing import Annotated, Any, TypedDict

from runner.acceptance import AcceptanceResult, run_acceptance as run_acceptance_checks
from tools.registry import registry

# 触发 fundamental 组 tool 注册（幂等）
import tools.fundamental._register  # noqa: F401


class FundamentalResearchFlowState(TypedDict, total=False):
    """fundamental:research 流的 state（风格对齐 FactorFlowState）。"""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    pit_result: dict[str, Any]
    financials: dict[str, Any]
    dcf_result: dict[str, Any]
    research_report: dict[str, Any]
    acceptance: dict[str, Any]
    _memory: Any


def _ctx(state: FundamentalResearchFlowState) -> dict[str, Any]:
    return {
        "thread_id": state.get("thread_id") or "fundamental-research-flow",
        "group": state.get("group") or "fundamental",
    }


def pit_rag_search_node(state: FundamentalResearchFlowState) -> dict[str, Any]:
    """pit_rag_search：PIT 语料检索（无 lookahead）。"""
    input_data = state.get("input_data") or {}
    args: dict[str, Any] = {
        "query": _default_query(input_data),
        "as_of_date": input_data["as_of_date"],
        "force_fixture": True,  # 流内默认 fixture，保证 deterministic；显式覆盖走工具层
    }
    if input_data.get("top_k") is not None:
        args["top_k"] = input_data["top_k"]
    if input_data.get("force_fixture") is not None:
        args["force_fixture"] = input_data["force_fixture"]
    result = registry.call("pit_rag_search", args, _ctx(state))
    return {"pit_result": result}


def _default_query(input_data: dict[str, Any]) -> str:
    questions = input_data.get("research_questions") or []
    return str(questions[0]) if questions else str(input_data["target_identifier"])


def extract_financial_node(state: FundamentalResearchFlowState) -> dict[str, Any]:
    """extract_financial：stub 财务提取（hash 造数；citations 取 PIT doc ids）。"""
    input_data = state.get("input_data") or {}
    args = {
        "target_identifier": input_data["target_identifier"],
        "as_of_date": input_data["as_of_date"],
        "documents": state["pit_result"].get("documents", []),
    }
    result = registry.call("extract_financial", args, _ctx(state))
    return {"financials": result}


def dcf_valuation_node(state: FundamentalResearchFlowState) -> dict[str, Any]:
    """dcf_valuation：extract_financial 的 fcf/shares → Gordon DCF stub。"""
    input_data = state.get("input_data") or {}
    financials = state["financials"]
    if not financials.get("fcf_ttm") or financials["fcf_ttm"] <= 0:
        raise RuntimeError(
            "dcf_valuation requires positive fcf_ttm; extract_financial stub returned "
            f"{financials.get('fcf_ttm')}"
        )
    args: dict[str, Any] = {
        "target_identifier": input_data["target_identifier"],
        "fcf_ttm": financials["fcf_ttm"],
        "shares_outstanding_m": financials["shares_outstanding_m"],
    }
    if input_data.get("growth_rate") is not None:
        args["growth_rate"] = input_data["growth_rate"]
    if input_data.get("wacc") is not None:
        args["wacc"] = input_data["wacc"]
    result = registry.call("dcf_valuation", args, _ctx(state))
    return {"dcf_result": result}


def render_report_node(state: FundamentalResearchFlowState) -> dict[str, Any]:
    """render_report：markdown（+ 可选 Typst PDF）研报 artifact。"""
    input_data = state.get("input_data") or {}
    pit = state["pit_result"]
    args: dict[str, Any] = {
        "target_identifier": input_data["target_identifier"],
        "as_of_date": input_data["as_of_date"],
        "research_questions": input_data.get("research_questions") or [],
        "financials": state["financials"],
        "dcf": state["dcf_result"],
        "documents": pit.get("documents", []),
        "pit_filtered_count": pit.get("filtered_count", 0),
        "citations_count": len(pit.get("documents", [])),
    }
    if input_data.get("target_name"):
        args["target_name"] = input_data["target_name"]
    if input_data.get("fair_value_per_share") is not None:
        args["fair_value_per_share"] = input_data["fair_value_per_share"]
    result = registry.call("render_report", args, _ctx(state))
    return {"research_report": result}


def run_acceptance(state: FundamentalResearchFlowState) -> dict[str, Any]:
    """research-pdf 验收（复用 runner/acceptance.py 的 _check_research_pdf 规则）。"""
    report = state["research_report"]
    result = run_acceptance_checks("research-pdf", report)
    return {
        "acceptance": _acceptance_to_dict(result),
        "output_data": {
            **report,
            "acceptance_verdict": result.verdict,
        },
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


def build_workflow(checkpoint_db: str | PathLike[str] | None = None):
    """Build the LangGraph app（结构对齐 flows.factor_evaluation_adapter.build_workflow）。"""
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
        "pit_rag_search": pit_rag_search_node,
        "extract_financial": extract_financial_node,
        "dcf_valuation": dcf_valuation_node,
        "render_report": render_report_node,
        "acceptance": run_acceptance,
    }
    edges = default_compose_edges(list(nodes.keys()))
    workflow = create_workflow(nodes, edges, state_schema=FundamentalResearchFlowState)
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


# ---------------------------------------------------------------------------
# 注册（import 即注册）
# ---------------------------------------------------------------------------

_FLOW_GROUP = "fundamental"
_FLOW_NAME = "fundamental:research"


def register(overwrite: bool = False) -> None:
    from runner.compose_executor import register_flow

    register_flow(_FLOW_GROUP, _FLOW_NAME, build_workflow(), overwrite=overwrite)


def _auto_register() -> None:
    try:
        register(overwrite=False)
    except KeyError:
        pass


_auto_register()
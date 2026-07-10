"""注册 fundamental 组全部 tool — Day 4/5 刘炽。"""
from __future__ import annotations

from tools.common.mark_task_done import mark_task_done_tool
from tools.common.request_human_review import request_human_review_tool
from tools.fundamental.dcf_valuation import dcf_valuation_tool
from tools.fundamental.extract_financial import extract_financial_tool
from tools.fundamental.pit_rag_search import pit_rag_search_tool
from tools.fundamental.render_report import render_report_tool
from tools.registry import register_tool

register_tool(pit_rag_search_tool)
register_tool(extract_financial_tool)
register_tool(dcf_valuation_tool)
register_tool(render_report_tool)
register_tool(request_human_review_tool)
register_tool(mark_task_done_tool)

__all__ = [
    "pit_rag_search_tool",
    "extract_financial_tool",
    "dcf_valuation_tool",
    "render_report_tool",
    "request_human_review_tool",
    "mark_task_done_tool",
]

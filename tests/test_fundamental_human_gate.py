"""Fundamental AgentRunner 研报审阅标记（非阻断）— Day5 刘炽 / v0.2 收窄改写。

2026-09-01 HumanGate 收窄（F-03 / governance G2-A8）：研报产出不 gate——
``request_human_review`` 由 LangGraph 真阻断 interrupt 改为非阻断审阅标记：
写 review_requested 标记后直接放行，流程完成、全程零 ``__interrupt__``。
"""
from __future__ import annotations

import importlib
import shutil
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import tools.fundamental._register  # noqa: F401
from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import registry


class ScriptedLLM:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="done")
        self._idx += 1
        return resp


def _ai(name: str, args: dict, cid: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": cid}],
    )


@pytest.fixture(autouse=True)
def _reload():
    importlib.reload(tools.fundamental._register)
    yield
    clear_checkpointer_cache()


def test_fundamental_allowlist_includes_human_review():
    ids = {t.id for t in registry.get_tools_for_group("fundamental")}
    assert "request_human_review" in ids
    assert "mark_task_done" in ids


def test_fundamental_agentrunner_review_marker_non_blocking():
    """研报审阅收窄语义：审阅标记存在 + 全程零 interrupt + 流程完成。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        clear_checkpointer_cache()
        llm = ScriptedLLM(
            [
                _ai(
                    "render_report",
                    {
                        "target_identifier": "2097.HK",
                        "target_name": "蜜雪冰城",
                        "as_of_date": "2025-01-01",
                        "fair_value_per_share": 43.47,
                        "use_typst": False,
                    },
                    "c1",
                ),
                _ai(
                    "request_human_review",
                    {"reason": "研报待研究员验收"},
                    "c2",
                ),
                # 无需任何 resume：标记后直接放行，收尾完成。
                _ai("mark_task_done", {"summary": "研报已挂审阅标记，报告平台承接"}, "c3"),
            ]
        )
        runner = AgentRunner(
            group="fundamental",
            model=llm,
            checkpoint_db=tmp / "ckpt.db",
        )
        final = runner.run(
            task="渲染研报并挂审阅标记",
            skill_name="fundamental-compose",
            thread_id="fund-review-1",
            flow_name="fundamental_hg",
        )

        # 1) 全程零 human_gate interrupt
        assert "__interrupt__" not in final
        # 2) 流程完成（不再停在 waiting_for_human，无需 resume）
        assert final.get("task_status") == "done"
        # 3) 审阅标记存在（随 tool_result 进 messages / execution_trace）
        tool_outputs = [str(getattr(m, "content", "")) for m in final["messages"]]
        assert any("review_requested" in output for output in tool_outputs), (
            f"expected review marker in tool outputs; got {tool_outputs}"
        )
        trace_types = [e.get("type") for e in (final.get("execution_trace") or [])]
        assert "human_gate" not in trace_types
    finally:
        clear_checkpointer_cache()
        shutil.rmtree(tmp, ignore_errors=True)

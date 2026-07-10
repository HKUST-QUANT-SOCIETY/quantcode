"""Fundamental AgentRunner human-gate interrupt/resume — Day5 刘炽."""
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


def test_fundamental_agentrunner_human_gate_interrupt_resume():
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
                # After human approve resume, finish the graph cleanly.
                _ai("mark_task_done", {"summary": "研报已人审通过"}, "c3"),
            ]
        )
        runner = AgentRunner(
            group="fundamental",
            model=llm,
            checkpoint_db=tmp / "ckpt.db",
        )
        paused = runner.stream(
            task="渲染研报并提交人审",
            skill_name="fundamental-compose",
            thread_id="fund-hg-1",
            flow_name="fundamental_hg",
        )
        assert (
            paused.get("status") == "waiting_for_human"
            or "__interrupt__" in paused
            or any(
                e.get("type") == "human_gate"
                for e in (paused.get("execution_trace") or [])
            )
        ), f"expected human gate, got keys={list(paused.keys())}"

        resumed = runner.resume(
            thread_id="fund-hg-1",
            decision="approve",
            skill_name="fundamental-compose",
            flow_name="fundamental_hg",
        )
        assert "__interrupt__" not in resumed
        assert resumed.get("task_status") == "done"
    finally:
        clear_checkpointer_cache()
        shutil.rmtree(tmp, ignore_errors=True)

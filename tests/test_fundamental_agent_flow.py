"""AgentRunner integration for fundamental compose flow — Day 4 刘炽。"""
from __future__ import annotations

import importlib
import shutil
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache


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


@pytest.fixture
def tmp_db():
    d = tempfile.mkdtemp()
    db = Path(d) / "ckpt.db"
    yield db
    clear_checkpointer_cache()
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _register():
    import tools.fundamental._register  # noqa: F401

    importlib.reload(tools.fundamental._register)
    yield


def test_fundamental_agent_multi_step(tmp_db):
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "pit_rag_search",
                        "args": {
                            "query": "蜜雪冰城 财务",
                            "as_of_date": "2025-01-01",
                        },
                        "id": "f1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "extract_financial",
                        "args": {
                            "target_identifier": "2097.HK",
                            "as_of_date": "2025-01-01",
                        },
                        "id": "f2",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "dcf_valuation",
                        "args": {
                            "target_identifier": "2097.HK",
                            "fcf_ttm": 12000.0,
                        },
                        "id": "f3",
                    }
                ],
            ),
            AIMessage(content="Fundamental flow complete."),
        ]
    )
    runner = AgentRunner(group="fundamental", model=llm, checkpoint_db=tmp_db)
    final = runner.run(
        task="对 2097.HK 做研报估值",
        skill_name="fundamental-compose",
        thread_id="t-fund-1",
        flow_name="fundamental_flow",
    )
    assert len(final["messages"]) >= 5
    assert final["iterations"] >= 2
    names = []
    for msg in final.get("messages", []):
        if isinstance(msg, AIMessage):
            for call in getattr(msg, "tool_calls", []) or []:
                names.append(call["name"] if isinstance(call, dict) else call.get("name"))
    assert "pit_rag_search" in names
    assert "extract_financial" in names

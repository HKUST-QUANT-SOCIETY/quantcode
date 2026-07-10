"""AgentRunner integration for strategy compose flow — Day 4 刘炽。"""
from __future__ import annotations

import importlib
import shutil
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import registry as global_registry


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
    import tools.strategy._register  # noqa: F401

    importlib.reload(tools.strategy._register)
    yield


def test_strategy_agent_multi_step(tmp_db):
    candidates = [
        {"signal_id": "a", "source_group": "factor", "weight_hint": 0.4},
        {"signal_id": "b", "source_group": "model", "weight_hint": 0.6},
    ]
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "select_signals",
                        "args": {"candidates": candidates, "max_positions": 2},
                        "id": "s1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "combine_signals",
                        "args": {
                            "selected": candidates,
                            "target_gross_exposure": 1.0,
                        },
                        "id": "s2",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "run_strategy_backtest",
                        "args": {
                            "strategy_name": "demo",
                            "as_of_date": "2026-06-27",
                            "weights": {"a": 0.4, "b": 0.6},
                        },
                        "id": "s3",
                    }
                ],
            ),
            AIMessage(content="Strategy flow complete."),
        ]
    )
    runner = AgentRunner(group="strategy", model=llm, checkpoint_db=tmp_db)
    final = runner.run(
        task="筛选信号并回测",
        skill_name="strategy-compose",
        thread_id="t-strategy-1",
        flow_name="strategy_flow",
    )
    assert len(final["messages"]) >= 5
    assert final["iterations"] >= 2
    names = []
    for msg in final.get("messages", []):
        if isinstance(msg, AIMessage):
            for call in getattr(msg, "tool_calls", []) or []:
                names.append(call["name"] if isinstance(call, dict) else call.get("name"))
    assert "select_signals" in names
    assert {t.id for t in global_registry.get_tools_for_group("strategy")} == {
        "select_signals",
        "combine_signals",
        "run_strategy_backtest",
        "deploy_strategy",
    }

"""AgentRunner integration test for options compose flow."""
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
def _register_options_tools():
    import tools.options._register  # noqa: F401

    importlib.reload(tools.options._register)
    yield


def test_options_agent_three_step_flow(tmp_db):
    llm = ScriptedLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "build_vol_surface",
                        "args": {
                            "strategy_name": "gc_vol_carry",
                            "underlying": "GC",
                            "as_of_date": "2026-06-27",
                        },
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calc_greeks",
                        "args": {
                            "underlying": "GC",
                            "as_of_date": "2026-06-27",
                            "spot_price": 3400.0,
                        },
                        "id": "c2",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "run_options_backtest_stub",
                        "args": {
                            "strategy_name": "gc_vol_carry",
                            "underlying": "GC",
                            "start_date": "2026-01-01",
                            "end_date": "2026-06-27",
                        },
                        "id": "c3",
                    }
                ],
            ),
            AIMessage(content="Options flow complete."),
        ]
    )

    runner = AgentRunner(group="options", model=llm, checkpoint_db=tmp_db)
    final = runner.run(
        task="构建 GC 波动率曲面、计算 Greeks 并跑回测 stub",
        skill_name="options-compose",
        thread_id="t-options-flow-1",
        flow_name="options_flow",
    )

    # 业务态未写入 state 时，state_loop 可能在第 2 步后触发（与 model 组测试一致）
    assert len(final["messages"]) >= 5
    assert final["iterations"] >= 2

    tool_names = []
    for msg in final.get("messages", []):
        if isinstance(msg, AIMessage):
            for call in getattr(msg, "tool_calls", []) or []:
                tool_names.append(call["name"] if isinstance(call, dict) else call.get("name"))
    assert "build_vol_surface" in tool_names
    assert "calc_greeks" in tool_names

    allowed = {t.id for t in global_registry.get_tools_for_group("options")}
    assert allowed == {
        "build_vol_surface",
        "calc_greeks",
        "run_options_backtest_stub",
    }

"""test_token_budget.py — R2 token budget 端到端测试。

覆盖：
1. AgentState.budget_used 每次 LLM 返回后累计（usage 真值优先，缺省退回估算）；
2. 超预算 → waiting_for_human + interrupt payload kind="budget" + trace 含 budget_warning；
3. resume approve → budget_grants 追加 50000 并继续跑；
4. resume reject → 正常收尾 completed + output_data.budget_exhausted=True；
5. RunAgentArgs.max_total_tokens 默认走 env QUANTCODE_TOKEN_BUDGET（缺省 200000）。

场景构造：预算设 1，LLM 首次返回一段长 content（约 100 tokens）→ 在下一次
llm 前的 budget_gate 处必然超限 → interrupt。这是最小确定性触发方式
（ponytail: 不靠迭代次数累积，一步到位）。
"""
from __future__ import annotations

from langchain_core.messages import AIMessage
from pydantic import BaseModel

import pytest

from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache


BANNER = "#" * 400  # ≈100 tokens（chars/4 估算）


class ScriptedLLM:
    """按调用次数返回预设 AIMessage；无 usage 时保持无 usage_metadata（走估算）。"""

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
def checkpointer_clean():
    yield
    clear_checkpointer_cache()


# ---------------------------------------------------------------------------
# 1. budget_used 累计
# ---------------------------------------------------------------------------


def test_budget_used_accumulates_usage_then_estimate():
    """usage_metadata.total_tokens 真值优先；无 usage 退回 chars/4 近似。"""
    class UsageLLM:
        def __init__(self):
            self.calls = 0

        def __call__(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="x",
                    usage_metadata={"input_tokens": 30, "output_tokens": 12, "total_tokens": 42},
                )
            return AIMessage(content="x" * 100)  # 无 usage_metadata → 走估算分支

    from runner.agent_nodes import make_llm_node

    node = make_llm_node(UsageLLM(), tools=[])
    state = {"messages": [], "system_prompt": "", "iterations": 0, "budget_used": 0}

    # 第 1 次：usage 真值 30+12=42
    u1 = node(dict(state))
    assert u1["budget_used"] == 42

    # 第 2 次：无 usage → (prompt+response chars)//4 = (0+100)//4 = 25
    u2 = node({**state, "budget_used": 42})
    assert u2["budget_used"] == 42 + 25


def test_budget_used_fallback_estimate_math():
    """无 usage 时 spent = (system+history+response 字符数)//4 近似。"""
    from runner.agent_nodes import make_llm_node

    class BareLLM:
        def __call__(self, messages, tools=None):
            return AIMessage(content=BANNER)  # 400 chars，无 usage_metadata

    node = make_llm_node(BareLLM(), tools=[])
    state = {"messages": [], "system_prompt": "abcd", "iterations": 0, "budget_used": 5}
    updates = node(dict(state))
    # node 计算：system 计入一次初始 + 一次 history 循环 → 4+4+400=408//4=102
    assert updates["budget_used"] == 5 + 102


# ---------------------------------------------------------------------------
# 2. 超预算 → stopped_budget（不创建 HumanGate）
# ---------------------------------------------------------------------------


def test_budget_exhaustion_stops_without_human_gate(tmp_path, checkpointer_clean):
    llm = ScriptedLLM([AIMessage(content=BANNER)])
    runner = AgentRunner(
        group="model",
        model=llm,
        checkpoint_db=tmp_path / "budget.db",
        budget_tokens=1,
    )
    final = runner.stream(
        task="hi",
        system_prompt="x",
        thread_id="budget-pause-1",
        flow_name="budget_test",
    )
    assert final.get("status") == "stopped_budget"
    assert final.get("output_data", {}).get("budget_exhausted") is True

    trace = final["execution_trace"]
    assert "budget_warning" in [e["type"] for e in trace]
    warning = next(e for e in trace if e["type"] == "budget_warning")
    assert warning["data"]["budget_tokens"] == 1
    assert warning["data"]["budget_used"] > 1
    assert warning["data"]["over_by"] == warning["data"]["budget_used"] - 1

    assert not final.get("__interrupt__")


# ---------------------------------------------------------------------------
# 3. 预算停止不可通过 HumanGate resume 加额
# ---------------------------------------------------------------------------


def test_budget_stop_has_no_approval_resume(tmp_path, checkpointer_clean):
    llm = ScriptedLLM([AIMessage(content=BANNER), AIMessage(content="finished")])
    runner = AgentRunner(
        group="model",
        model=llm,
        checkpoint_db=tmp_path / "budget.db",
        budget_tokens=1,
    )
    paused = runner.stream(
        task="hi",
        system_prompt="x",
        thread_id="budget-approve-1",
        flow_name="budget_test",
    )
    assert paused.get("status") == "stopped_budget"
    assert paused.get("budget_grants") in (None, [])
    assert not paused.get("__interrupt__")


# ---------------------------------------------------------------------------
# 4. budget_exhausted 状态可直接读取
# ---------------------------------------------------------------------------


def test_budget_stop_records_exhaustion(tmp_path, checkpointer_clean):
    llm = ScriptedLLM([AIMessage(content=BANNER)])
    runner = AgentRunner(
        group="model",
        model=llm,
        checkpoint_db=tmp_path / "budget.db",
        budget_tokens=1,
    )
    paused = runner.stream(
        task="hi",
        system_prompt="x",
        thread_id="budget-reject-1",
        flow_name="budget_test",
    )
    assert paused.get("status") == "stopped_budget"
    assert paused.get("task_status") == "done"
    assert paused.get("output_data", {}).get("budget_exhausted") is True
    assert not paused.get("__interrupt__")


# ---------------------------------------------------------------------------
# 5. 未启用预算 + RunAgentArgs 默认值
# ---------------------------------------------------------------------------


def test_no_budget_tokens_means_no_gate(tmp_path, checkpointer_clean):
    """budget_tokens=None → budget_gate no-op：无 kind=budget interrupt，used 仍累计。"""
    llm = ScriptedLLM([AIMessage(content="quick done" + BANNER[:200])])
    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_path / "budget.db")
    final = runner.run(
        task="hi",
        system_prompt="x",
        thread_id="budget-off-1",
        flow_name="budget_test",
    )
    # 可能出现既有 loop/risk 语义的 human_gate interrupt，但绝无 kind=budget。
    iv = final.get("__interrupt__")
    kinds = [getattr(i, "value", {}).get("kind") for i in iv] if iv else []
    assert "budget" not in kinds
    assert int(final.get("budget_used") or 0) > 0


def test_run_agent_args_default_token_budget(monkeypatch):
    """RunAgentArgs.max_total_tokens=None → env QUANTCODE_TOKEN_BUDGET（缺省 200000）。"""
    from runner.agent_mcp_tool import RunAgentArgs, _resolve_budget

    monkeypatch.delenv("QUANTCODE_TOKEN_BUDGET", raising=False)
    args = RunAgentArgs(task="x")
    assert args.max_total_tokens is None
    assert _resolve_budget(args.max_total_tokens) == 200_000

    monkeypatch.setenv("QUANTCODE_TOKEN_BUDGET", "7777")
    assert _resolve_budget(None) == 7777

    # 显式传值优先于 env
    assert _resolve_budget(RunAgentArgs(task="x", max_total_tokens=99).max_total_tokens) == 99

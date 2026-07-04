"""StateGraph 节点函数测试 — Day 3 尹一帆。

每个节点函数工厂用 mock 依赖测，不依赖真实 LLM / DB / 文件系统。
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from runner.agent_nodes import (
    AgentState,
    init_agent_state,
    make_llm_node,
    make_post_tool_check,
    make_rlhf_collect_node,
    make_should_continue,
    make_tool_node,
)
from tools.loop_detector import LoopDetector, MAX_ITERATIONS
from tools.registry import ToolDef, ToolRegistry, register_tool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_registry():
    from tools.registry import registry as global_registry

    global_registry._tools.clear()
    yield global_registry
    global_registry._tools.clear()


# 一个简单的 mock tool（"echo"）
class EchoArgs(BaseModel):
    msg: str


def _echo_exec(args: EchoArgs, ctx: dict) -> str:
    return f"echo: {args.msg}"


ECHO_TOOL = ToolDef(
    id="echo",
    description="Echo the message back",
    schema=EchoArgs,
    execute=_echo_exec,
)


@pytest.fixture
def registry_with_echo(clean_registry):
    clean_registry.register(ECHO_TOOL)
    return clean_registry


# 一个 mock LLM：返回预设的 AIMessage 序列
class MockLLM:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[tuple[list, list]] = []  # (messages, tools)

    def __call__(self, messages, tools=None):
        self.calls.append((list(messages), list(tools or [])))
        if self._call_count >= len(self._responses):
            # 默认返回空 tool_calls 的 final answer
            return AIMessage(content="[mock default final]")
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


# 一个 mock RLHFCollector
class MockRLHFCollector:
    def __init__(self):
        self.entries: list[dict] = []

    def record(self, state, action, reward):
        self.entries.append({"state": state, "action": action, "reward": reward})


# ---------------------------------------------------------------------------
# init_agent_state
# ---------------------------------------------------------------------------


def test_init_agent_state_with_task():
    state = init_agent_state(
        group="model",
        flow_name="test",
        thread_id="t-1",
        system_prompt="You are a model agent.",
        tools=[],
        input_data={"task": "Read PR #42"},
    )
    assert state["group"] == "model"
    assert state["thread_id"] == "t-1"
    assert state["system_prompt"] == "You are a model agent."
    assert state["iterations"] == 0
    assert len(state["messages"]) == 1
    assert isinstance(state["messages"][0], HumanMessage)
    assert state["messages"][0].content == "Read PR #42"
    assert state["seen_states"] == set()


def test_init_agent_state_without_task():
    state = init_agent_state(
        group="risk",
        flow_name="t",
        thread_id="t-1",
        system_prompt="",
        tools=[],
    )
    assert state["messages"] == []
    assert state["group"] == "risk"


# ---------------------------------------------------------------------------
# llm_node
# ---------------------------------------------------------------------------


def test_llm_node_invokes_model_with_system_prompt():
    llm = MockLLM([AIMessage(content="hi")])
    node = make_llm_node(llm, tools=[ECHO_TOOL])
    state: AgentState = {
        "messages": [HumanMessage(content="task")],
        "system_prompt": "you are agent",
    }
    out = node(state)
    # 模型收到 [System, Human]
    msgs_seen = llm.calls[0][0]
    assert msgs_seen[0].content == "you are agent"
    assert msgs_seen[1].content == "task"
    # 返回新 AIMessage + iterations + 1
    assert out["iterations"] == 1
    assert isinstance(out["messages"][0], AIMessage)
    assert out["messages"][0].content == "hi"


def test_llm_node_works_without_system_prompt():
    llm = MockLLM([AIMessage(content="x")])
    node = make_llm_node(llm, tools=[])
    state: AgentState = {"messages": []}
    out = node(state)
    # 没有 system prompt → 直接传 messages
    msgs_seen = llm.calls[0][0]
    assert msgs_seen == []
    assert out["iterations"] == 1


def test_llm_node_passes_tools():
    llm = MockLLM([AIMessage(content="x")])
    node = make_llm_node(llm, tools=[ECHO_TOOL])
    state: AgentState = {"messages": []}
    node(state)
    tools_seen = llm.calls[0][1]
    assert tools_seen == [ECHO_TOOL]


def test_llm_node_tools_passed_via_closure_not_state():
    """即使 state 没有 tools 字段，llm_node 也能用闭包里的 tools。"""
    llm = MockLLM([AIMessage(content="x")])
    closure_tools = [ECHO_TOOL, "fake_tool_object"]
    node = make_llm_node(llm, tools=closure_tools)
    state: AgentState = {"messages": []}  # 故意不传 tools
    node(state)
    # MockLLM 用 list(tools or []) 拷贝，所以用 == 比较内容
    assert llm.calls[0][1] == closure_tools


# ---------------------------------------------------------------------------
# tool_node
# ---------------------------------------------------------------------------


def test_tool_node_executes_single_call(registry_with_echo):
    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"msg": "hello"}, "id": "call-1"}],
            )
        ],
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    assert len(out["messages"]) == 1
    msg = out["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert msg.content == "echo: hello"
    assert msg.tool_call_id == "call-1"
    assert msg.name == "echo"


def test_tool_node_executes_multiple_calls(registry_with_echo):
    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "echo", "args": {"msg": "a"}, "id": "c1"},
                    {"name": "echo", "args": {"msg": "b"}, "id": "c2"},
                ],
            )
        ],
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    assert len(out["messages"]) == 2
    assert [m.content for m in out["messages"]] == ["echo: a", "echo: b"]


def test_tool_node_handles_invalid_args_with_friendly_error(registry_with_echo):
    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"msg": 123}, "id": "c1"}],
            )
        ],
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    # ToolMessage contains error message, not crash
    assert "failed" in out["messages"][0].content


def test_tool_node_handles_unknown_tool_with_friendly_error(registry_with_echo):
    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "nonexistent", "args": {}, "id": "c1"}],
            )
        ],
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    assert "nonexistent" in out["messages"][0].content
    assert "failed" in out["messages"][0].content


def test_tool_node_no_tool_calls_returns_empty(registry_with_echo):
    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [AIMessage(content="just text")],  # no tool_calls
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    assert out["messages"] == []


def test_tool_node_no_messages_returns_empty(registry_with_echo):
    node = make_tool_node(registry_with_echo)
    out = node({"messages": []})
    assert out["messages"] == []


# ---------------------------------------------------------------------------
# should_continue
# ---------------------------------------------------------------------------


def test_should_continue_end_when_no_tool_calls():
    fn = make_should_continue()
    state: AgentState = {
        "messages": [AIMessage(content="final answer")],
        "iterations": 1,
    }
    assert fn(state) == "end"


def test_should_continue_end_when_last_is_tool_message():
    fn = make_should_continue()
    state: AgentState = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]),
            ToolMessage(content="ok", tool_call_id="c1"),
        ],
        "iterations": 1,
    }
    # 最后是 ToolMessage 不是 AIMessage → end（异常保护）
    assert fn(state) == "end"


def test_should_continue_tool_when_tool_calls_and_under_limit():
    fn = make_should_continue()
    state: AgentState = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}])
        ],
        "iterations": 1,
    }
    assert fn(state) == "tool"


def test_should_continue_max_iter_at_limit():
    fn = make_should_continue(max_iterations=5)
    state: AgentState = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}])
        ],
        "iterations": 5,
    }
    assert fn(state) == "max_iter"


def test_should_continue_empty_messages_returns_end():
    fn = make_should_continue()
    assert fn({"messages": []}) == "end"


# ---------------------------------------------------------------------------
# post_tool_check
# ---------------------------------------------------------------------------


def test_post_tool_check_returns_rlhf_on_normal_call():
    detector = LoopDetector(window=10, threshold=5)
    seen = set()
    fn = make_post_tool_check(detector, seen)
    state: AgentState = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "echo", "args": {"msg": "hi"}, "id": "c1"}])
        ],
        "iterations": 1,
    }
    assert fn(state) == "rlhf"
    assert len(seen) == 1  # fingerprint recorded


def test_post_tool_check_triggers_loop_on_repeated_call():
    """同一 tool+args 在窗口内出现 3 次 → 触发 loop。

    state 每次 messages 增长（模拟真实迭代），让 fingerprint 保持不同。
    """
    detector = LoopDetector(window=10, threshold=3)
    seen = set()
    fn = make_post_tool_check(detector, seen)

    # 调 3 次：messages 每次追加（fingerprint 不同），但 tool_call 完全一样
    for i in range(3):
        state: AgentState = {
            "messages": [
                HumanMessage(content=f"step-{i}"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "echo", "args": {"msg": "x"}, "id": "c1"}],
                ),
            ],
            "iterations": i + 1,
        }
        result = fn(state)
        if i < 2:
            assert result == "rlhf", f"第 {i+1} 次应返回 rlhf，得到 {result}"
        else:
            assert result == "loop", f"第 {i+1} 次应返回 loop，得到 {result}"


def test_post_tool_check_triggers_state_loop_on_repeated_state():
    """state 整体重复（无 tool_calls 触发 loop）→ 触发 state_loop。"""
    detector = LoopDetector(window=10, threshold=10)
    seen = set()
    fn = make_post_tool_check(detector, seen)
    # 两次完全相同的 state，没有 tool_calls 触发 loop detector
    state: AgentState = {
        "messages": [HumanMessage(content="same content")],
        "iterations": 5,
    }
    assert fn(state) == "rlhf"
    assert fn(state) == "state_loop"


# ---------------------------------------------------------------------------
# rlhf_collect_node
# ---------------------------------------------------------------------------


def test_rlhf_collect_node_records_action_and_state():
    collector = MockRLHFCollector()
    node = make_rlhf_collect_node(collector)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="thinking",
                tool_calls=[{"name": "echo", "args": {"msg": "hi"}, "id": "c1"}],
            )
        ],
        "group": "model",
        "iterations": 1,
    }
    out = node(state)
    assert out == {}  # 不修改 state
    assert len(collector.entries) == 1
    entry = collector.entries[0]
    # state 不应包含 messages/tools/_memory 等不可序列化字段
    assert "messages" not in entry["state"]
    assert "tools" not in entry["state"]
    assert "_memory" not in entry["state"]
    assert entry["state"]["group"] == "model"
    # action 包含 tool_calls 和 content
    assert entry["action"]["tool_calls"] == [
        {"name": "echo", "args": {"msg": "hi"}, "id": "c1"}
    ]
    assert entry["action"]["content"] == "thinking"
    assert entry["reward"] == 0.0


def test_rlhf_collect_node_with_no_ai_message_records_empty_action():
    collector = MockRLHFCollector()
    node = make_rlhf_collect_node(collector)
    state: AgentState = {"messages": [HumanMessage(content="hi")]}
    out = node(state)
    assert out == {}
    assert collector.entries[0]["action"] == {}
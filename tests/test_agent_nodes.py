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
    # Day 3 评审修复：seen_states 已从 instance 移到 make_post_tool_check 闭包，
    # 不再进 init_agent_state 返回的 dict


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


# ---------------------------------------------------------------------------
# Day 3 评审修复（🟢#7）：tool_node 异常脱敏测试
# ---------------------------------------------------------------------------


def test_tool_node_sanitizes_api_key_in_exception(registry_with_echo):
    """🟢#7: 非 read_/list_ 工具抛含 API key 的异常时，ToolMessage.content 不应包含 key。

    模拟 SSH / API 凭据泄露场景：tool 抛 RuntimeError("failed: API_KEY=sk-real-secret-12345")，
    验证 tool_node 不会把这个 key 注入 LLM 上下文。
    """
    from pydantic import BaseModel

    class LeakyArgs(BaseModel):
        pass

    sensitive_msg = "API_KEY=sk-real-secret-12345"

    def _leaky_execute(args: LeakyArgs, ctx: dict) -> str:
        raise RuntimeError(f"connection failed: {sensitive_msg}")

    leaky_tool = ToolDef(
        id="api_client",
        description="Calls an external API (leaky in test)",
        schema=LeakyArgs,
        execute=_leaky_execute,
    )
    registry_with_echo.register(leaky_tool)

    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "api_client", "args": {}, "id": "c1"}],
            )
        ],
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    content = out["messages"][0].content
    # 关键断言：API key 不出现在 ToolMessage content 里
    assert sensitive_msg not in content, (
        f"敏感凭据泄漏到 LLM 上下文: {content!r}"
    )
    # 异常类名应保留（让 LLM 能识别失败类型）
    assert "RuntimeError" in content
    # 工具名应保留（让 LLM 知道是哪个 tool 失败）
    assert "api_client" in content


def test_tool_node_preserves_detail_for_read_like_tools(registry_with_echo):
    """🟢#7 白名单例外：read_/list_ 前缀工具可保留详细错误（一般不带凭据）。"""
    from pydantic import BaseModel

    class ReadArgs(BaseModel):
        path: str

    detail_msg = "PermissionError: file mode 0o600 expected"

    def _read_execute(args: ReadArgs, ctx: dict) -> str:
        raise PermissionError(detail_msg)

    read_tool = ToolDef(
        id="read_secret",
        description="A read-prefixed tool",
        schema=ReadArgs,
        execute=_read_execute,
    )
    registry_with_echo.register(read_tool)

    node = make_tool_node(registry_with_echo)
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_secret", "args": {"path": "/etc/x"}, "id": "c1"}],
            )
        ],
        "group": "model",
        "thread_id": "t-1",
    }
    out = node(state)
    content = out["messages"][0].content
    # read_ 前缀 → 详细异常信息保留
    assert detail_msg in content
    assert "PermissionError" in content


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
    """Day 3 评审修复：seen_states 不再从外部传入；由工厂闭包内部维护。"""
    detector = LoopDetector(window=10, threshold=5)
    fn = make_post_tool_check(detector)
    state: AgentState = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "echo", "args": {"msg": "hi"}, "id": "c1"}])
        ],
        "iterations": 1,
    }
    assert fn(state) == "rlhf"


def test_post_tool_check_triggers_loop_on_repeated_call():
    """同一 tool+args 在窗口内出现 3 次 → 触发 loop。

    Day 3 评审修复（采纳 PR #16 白名单 fingerprint）：只 hash 5 个特定业务字段
    （current_step / last_tool / tool_args / output_data / errors），测试需用
    字段之一（这里是 ``output_data``）来让 fingerprint 每轮不同，避免先触发
    state_loop。
    """
    detector = LoopDetector(window=10, threshold=3)
    fn = make_post_tool_check(detector)

    # 调 3 次：tool_call 完全一样（让 loop_detector 触发），但用 output_data
    # 保证 fingerprint 每轮不同（避免先触发 state_loop）
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
            "output_data": {"step": i},  # PR #16 白名单字段之一，每轮变化
        }
        result = fn(state)
        if i < 2:
            assert result == "rlhf", f"第 {i+1} 次应返回 rlhf，得到 {result}"
        else:
            assert result == "loop", f"第 {i+1} 次应返回 loop，得到 {result}"


def test_post_tool_check_triggers_state_loop_on_repeated_state():
    """state 整体重复（无 tool_calls 触发 loop）→ 触发 state_loop。

    Day 3 评审修复：messages 是噪音（已加进 _NOISY_STATE_KEYS），
    fingerprint 与 messages 长度无关 —— 即便 messages 累积、业务态不变，
    第二次进入仍会触发 state_loop。
    """
    detector = LoopDetector(window=10, threshold=10)
    fn = make_post_tool_check(detector)
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

# ---------------------------------------------------------------------------
# Day 4 修复:fingerprint 必须在每次 tool_call 后变化(否则第二次 tool 就 state_loop 终止 Agent)
# ---------------------------------------------------------------------------


def test_post_tool_check_fingerprint_changes_per_tool_call():
    """🟢Day 4 修复:post_tool_check 内部 fingerprint 必须在每次 tool_call 后变化。

    Day 3 旧实现用 compute_state_fingerprint hash 5 个字段(current_step/last_tool/...
    ),但 AgentState 里这些字段都不存在 → fingerprint 永远不变 → 第二次 tool 就
    触发 state_loop 把 Agent 终止。Day 4 改用 last_tool/tool_args/iterations 重新算
    fingerprint,确保每次 tool_call 后变化。
    """
    from runner.agent_nodes import make_post_tool_check
    from tools.loop_detector import LoopDetector

    fn = make_post_tool_check(LoopDetector())

    # 模拟连续 3 次 tool_call 不同的 tool
    state_v1 = {
        "messages": [
            HumanMessage(content="task"),
            AIMessage(content="", tool_calls=[
                {"name": "read_blackboard", "args": {"x": 1}, "id": "1"}
            ]),
        ],
        "iterations": 1,
    }
    state_v2 = {
        "messages": [
            HumanMessage(content="task"),
            AIMessage(content="", tool_calls=[
                {"name": "read_blackboard", "args": {"x": 1}, "id": "1"}
            ]),
            ToolMessage(content="ok", tool_call_id="1", name="read_blackboard"),
            AIMessage(content="", tool_calls=[
                {"name": "calc_risk", "args": {"y": 2}, "id": "2"}
            ]),
        ],
        "iterations": 2,
    }
    state_v3 = {
        "messages": state_v2["messages"] + [
            ToolMessage(content="ok", tool_call_id="2", name="calc_risk"),
            AIMessage(content="", tool_calls=[
                {"name": "check_gate", "args": {"z": 3}, "id": "3"}
            ]),
        ],
        "iterations": 3,
    }

    # 同一 post_tool_check 实例(同 seen_states set)
    r1 = fn(state_v1)
    r2 = fn(state_v2)
    r3 = fn(state_v3)

    # 3 次都返 "rlhf"(没触发 loop / state_loop)
    assert r1 == "rlhf", f"v1 应返 'rlhf', got {r1}"
    assert r2 == "rlhf", f"v2 应返 'rlhf', got {r2}"
    assert r3 == "rlhf", f"v3 应返 'rlhf', got {r3}"

    # 🟢严格验收:同样的 fingerprint 检查,如果 fingerprint 不变,第二次会触发 state_loop
    # 验证:跑一个用 "compute_state_fingerprint"(旧实现)的人,第二次应该返 "state_loop"
    from runner.routing.fingerprint import compute_state_fingerprint

    # 旧实现的 fingerprint:hash 5 个字段(都从 AgentState 拿不到)
    fp_v1 = compute_state_fingerprint(dict(state_v1))
    fp_v2 = compute_state_fingerprint(dict(state_v2))
    fp_v3 = compute_state_fingerprint(dict(state_v3))
    # 旧实现的 fingerprint 永远一样(因为字段都缺)
    assert fp_v1 == fp_v2 == fp_v3, (
        f"compute_state_fingerprint 对 AgentState 永远同值({fp_v1[:16]}...),"
        f"这就是 Day 3 触发 state_loop 的根本原因"
    )

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
from runner.routing.rlhf_logger import RLHF_PATH as _DEFAULT_RLHF_PATH
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


def test_tool_node_denies_model_call_outside_execution_allowlist(registry_with_echo):
    executed = False

    def _forbidden_execute(args: EchoArgs, ctx: dict) -> str:
        nonlocal executed
        executed = True
        return "must not execute"

    registry_with_echo.register(
        ToolDef(
            id="forbidden_write",
            description="A globally registered tool that is not allowed for this agent",
            schema=EchoArgs,
            execute=_forbidden_execute,
        )
    )
    node = make_tool_node(registry_with_echo, allowed_tool_ids={"echo"})
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "forbidden_write", "args": {"msg": "escape"}, "id": "c-denied"}
                ],
            )
        ],
        "group": "risk",
        "thread_id": "t-risk",
    }

    out = node(state)

    assert executed is False
    assert "denied by execution allowlist" in out["messages"][0].content
    assert out["errors"] == ["Tool 'forbidden_write' denied by execution allowlist."]


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


def test_rlhf_collect_node_writes_rlhf_log_to_file(tmp_path, monkeypatch):
    """Day 5: rlhf_collect_node 使用新格式写入 RLHF JSONL，不再用旧 RLHFCollector。

    验证节点写入了文件（测试用临时目录替换 RLHF_PATH）。"""
    import json
    rlhf_log_path = tmp_path / "rlhf_test.jsonl"

    # 替换 RLHF_PATH 的默认路径，让测试写入临时文件
    import runner.routing.rlhf_logger as rlogger_mod
    monkeypatch.setattr(rlogger_mod, "RLHF_PATH", rlhf_log_path)

    node = make_rlhf_collect_node(None)  # collector=None，走新格式
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

    # 文件被写入
    assert rlhf_log_path.exists()
    lines = rlhf_log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["action"]["tool_name"] == "echo"
    assert parsed["group"] == "model"
    assert "reward" not in parsed  # Day 5: no reward field
    assert "system_decision" in parsed
    assert "human_decision" in parsed
    assert "gate_purpose" in parsed
    assert "label" in parsed
    assert "risk_score" in parsed


def test_rlhf_collect_node_with_no_ai_message_skips_logging(tmp_path, monkeypatch):
    """没有 tool_calls 时，不写 RLHF 日志（避免空日志）。"""
    import runner.routing.rlhf_logger as rlogger_mod
    rlhf_log_path = tmp_path / "rlhf_test2.jsonl"
    monkeypatch.setattr(rlogger_mod, "RLHF_PATH", rlhf_log_path)

    node = make_rlhf_collect_node(None)
    state: AgentState = {"messages": [HumanMessage(content="hi")]}
    out = node(state)
    assert out == {}
    # 没有 tool_calls → 不写日志
    assert not rlhf_log_path.exists()

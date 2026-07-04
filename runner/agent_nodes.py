"""StateGraph 节点函数 — Day 3 尹一帆。

5 个节点函数（对应架构 §3.1 / §3.2）：

| 节点                 | 类型        | 职责                                                |
|----------------------|-------------|-----------------------------------------------------|
| ``llm_node``         | 普通 node   | 调 LLM，返回 AIMessage（带 tool_calls 或 final）    |
| ``tool_node``        | 普通 node   | 执行 tool_calls，返回 ToolMessage 列表              |
| ``rlhf_collect_node``| 普通 node   | 记录 (state, action, reward) 到 RLHFCollector       |
| ``should_continue``  | 条件边函数  | 路由: "tool" / "end" / "max_iter"                   |
| ``post_tool_check``  | 条件边函数  | 路由: "rlhf" / "loop" / "state_loop"                |

设计要点：
- 每个节点函数都是纯函数工厂（不持有状态），依赖通过闭包注入
- 依赖（model / tools / registry / rlhf_collector / loop_detector）由 ``AgentRunner`` 接线
- tools 通过 ``make_llm_node(model, tools)`` 闭包注入，**不放入 state**（ToolDef 不可 msgpack 序列化）
- 节点函数本身可单测（mock LLM + mock tool）
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from runner.langgraph_base import BaseFlowState
from tools.loop_detector import (
    MAX_ITERATIONS,
    LoopDetector,
    state_fingerprint,
)
from tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# AgentState：扩展 BaseFlowState 增加 ReAct 字段
# ---------------------------------------------------------------------------


class AgentState(BaseFlowState, total=False):
    """Agent 引擎的 state schema，继承 BaseFlowState。

    字段必须 msgpack 可序列化（LangGraph checkpointer 限制）：

    - messages      — LangChain BaseMessage 列表（**operator.add 累积**）
    - iterations    — 已执行步数（最后一次返回值覆盖）
    - system_prompt — SKILL.md 拼装出的系统提示（最后一次覆盖）

    **不放进 state 的字段**（通过闭包注入）：
    - tools         — ToolDef 列表（Pydantic 模型，msgpack 不支持）
    - seen_states   — 状态指纹检测（外部 set 更安全）
    """

    messages: Annotated[list[Any], operator.add]  # 累积所有 node 返回的新消息
    iterations: int
    system_prompt: str


# ---------------------------------------------------------------------------
# 工具：构造 LangChain-style 的 tool_call dict
# ---------------------------------------------------------------------------


def _to_tool_call_dict(call: Any) -> dict:
    """从 AIMessage.tool_calls[i]（TypedDict-like）抽取统一 dict。

    LangChain 的 ToolCall 是 TypedDict('name', 'args', 'id')，
    直接当 dict 用就行，做一层 normalize 防止属性访问缺失。
    """
    if isinstance(call, dict):
        return {
            "name": call.get("name", ""),
            "args": call.get("args", {}),
            "id": call.get("id", ""),
        }
    return {
        "name": getattr(call, "name", ""),
        "args": getattr(call, "args", {}),
        "id": getattr(call, "id", ""),
    }


# ---------------------------------------------------------------------------
# 节点函数工厂
# ---------------------------------------------------------------------------


def make_llm_node(
    model: Callable[..., AIMessage],
    tools: list[Any],
) -> Callable[[AgentState], dict]:
    """构造 ``llm_node``。

    Args:
        model: 可调用对象，签名 ``(messages, tools=...) -> AIMessage``。
               测试时传 MockLLM。
        tools: 当前可用 tool 列表（按组过滤后）。**通过闭包注入，不入 state**。
    """

    def llm_node(state: AgentState) -> dict:
        # 构造消息序列：system_prompt + 已有的 messages
        history = list(state.get("messages", []))
        if state.get("system_prompt"):
            history = [SystemMessage(content=state["system_prompt"])] + history

        # 调 LLM（带 tool 列表）
        response: AIMessage = model(history, tools=tools)

        return {
            "messages": [response],
            "iterations": state.get("iterations", 0) + 1,
        }

    return llm_node


def make_tool_node(
    registry: ToolRegistry,
) -> Callable[[AgentState], dict]:
    """构造 ``tool_node``：执行最近一个 AIMessage 里的所有 tool_calls。"""

    def tool_node(state: AgentState) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return {"messages": []}

        ctx = {
            "group": state.get("group", ""),
            "thread_id": state.get("thread_id", ""),
            "session_id": state.get("thread_id", ""),  # alias
        }
        ctx["_memory"] = state.get("_memory")  # MemoryService 透传

        results: list[ToolMessage] = []
        for call in tool_calls:
            c = _to_tool_call_dict(call)
            try:
                output = registry.call(c["name"], c["args"], ctx=ctx)
                content = output if isinstance(output, str) else str(output)
            except Exception as e:
                # 工具执行失败 → 返回错误 message，让 LLM 自己决定重试还是换方案
                content = f"Tool '{c['name']}' failed: {type(e).__name__}: {e}"
            results.append(
                ToolMessage(content=content, tool_call_id=c["id"], name=c["name"])
            )

        return {"messages": results}

    return tool_node


def make_should_continue(
    max_iterations: int = MAX_ITERATIONS,
) -> Callable[[AgentState], str]:
    """构造 ``should_continue`` 条件边函数。

    路由：
    - "end"      — LLM 没有 tool_calls（已给 final answer）
    - "max_iter" — 达到迭代上限
    - "tool"     — 继续执行 tool
    """

    def should_continue(state: AgentState) -> str:
        messages = state.get("messages", [])
        if not messages:
            return "end"
        last = messages[-1]
        # 不是 AIMessage（如 ToolMessage）→ 异常状态，强制结束
        if not isinstance(last, AIMessage):
            return "end"
        # 没有 tool_calls → LLM 已给出最终答案
        if not getattr(last, "tool_calls", None):
            return "end"
        # 迭代上限
        if state.get("iterations", 0) >= max_iterations:
            return "max_iter"
        return "tool"

    return should_continue


def make_post_tool_check(
    loop_detector: LoopDetector,
    seen_states: set[str],
) -> Callable[[AgentState], str]:
    """构造 ``post_tool_check`` 条件边函数。

    路由：
    - "loop"       — 死循环检测触发（同一 tool+args 反复调用）
    - "state_loop" — 状态指纹重复（绕圈）
    - "rlhf"       — 正常 → 进入 rlhf_collect_node → 回到 llm_node
    """

    def post_tool_check(state: AgentState) -> str:
        messages = state.get("messages", [])
        # 取最后一个 AIMessage（含 tool_calls 的那个）做循环检测
        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)),
            None,
        )
        if last_ai is not None:
            for call in getattr(last_ai, "tool_calls", []) or []:
                c = _to_tool_call_dict(call)
                if loop_detector.check(c["name"], c["args"]):
                    return "loop"

        # 状态指纹
        fp = state_fingerprint(dict(state))
        if fp in seen_states:
            return "state_loop"
        seen_states.add(fp)

        return "rlhf"

    return post_tool_check


def make_rlhf_collect_node(
    rlhf_collector: Any,  # RLHFCollector 类型（避免循环 import）
) -> Callable[[AgentState], dict]:
    """构造 ``rlhf_collect_node``。

    记录 (state, action, reward=0.0) 到 RLHFCollector。
    reward 默认 0；后续可接 TaskGate / 人工反馈。
    """

    def rlhf_collect_node(state: AgentState) -> dict:
        messages = state.get("messages", [])
        # 取最近一个 AIMessage（含 tool_calls 的）作为 action
        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)),
            None,
        )
        action = (
            {
                "tool_calls": [_to_tool_call_dict(c) for c in (last_ai.tool_calls or [])],
                "content": getattr(last_ai, "content", ""),
            }
            if last_ai is not None
            else {}
        )
        # 拷贝 state，去掉不可序列化的字段
        serializable_state = {
            k: v
            for k, v in state.items()
            if k not in ("messages", "tools", "seen_states", "_memory")
        }
        rlhf_collector.record(state=serializable_state, action=action, reward=0.0)
        return {}  # 不修改 state

    return rlhf_collect_node


# ---------------------------------------------------------------------------
# 便利：构造完整 AgentState 初始 dict（给 AgentRunner 用）
# ---------------------------------------------------------------------------


def init_agent_state(
    *,
    group: str,
    flow_name: str,
    thread_id: str,
    system_prompt: str,
    tools: list,
    input_data: dict | None = None,
) -> AgentState:
    """构造 AgentState 初始 dict，包含第一条 HumanMessage。"""
    user_msg = (input_data or {}).get("task", "")
    messages: list[Any] = []
    if user_msg:
        messages.append(HumanMessage(content=user_msg))
    return AgentState(
        group=group,
        flow_name=flow_name,
        thread_id=thread_id,
        input_data=input_data or {},
        messages=messages,
        iterations=0,
        tools=tools,
        system_prompt=system_prompt,
        seen_states=set(),
    )


__all__ = [
    "AgentState",
    "make_llm_node",
    "make_tool_node",
    "make_should_continue",
    "make_post_tool_check",
    "make_rlhf_collect_node",
    "init_agent_state",
]
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

import json
import operator
from typing import Annotated, Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from runner.human_gate import (
    build_interrupt_payload,
    make_gate_id,
    parse_resume_decision,
)
from runner.langgraph_base import BaseFlowState
from runner.routing.fingerprint import compute_state_fingerprint
from schemas.risk_profile import RiskThresholds
from tools.loop_detector import (
    MAX_ITERATIONS,
    LoopDetector,
)
from tools.registry import ToolRegistry

try:
    from langgraph.types import interrupt

    _INTERRUPT_AVAILABLE = True
except ImportError:  # pragma: no cover
    interrupt = None  # type: ignore[assignment]
    _INTERRUPT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Token 估算(Day 4):truncate_node 用
# ---------------------------------------------------------------------------

try:
    import tiktoken  # type: ignore

    _TIKTOKEN_AVAILABLE = True
except ImportError:  # pragma: no cover
    tiktoken = None  # type: ignore
    _TIKTOKEN_AVAILABLE = False


def _estimate_tokens(text: str, *, model: str = "gpt-4") -> int:
    """估算字符串的 token 数。

    优先级:
    1. tiktoken 可用 → 用对应 model 的 tokenizer 精确计数
    2. 不可用 → 退化为 ``len(text) // 2``(中英文保守估算;中文 1 字 ≈ 2 tokens,英文 1 词 ≈ 1.3 tokens)

    注意:``//2`` 仍可能偏低(纯英文时尤其如此),仅作为粗略保护。
    建议生产环境装 tiktoken(``pip install tiktoken``)。
    """
    if _TIKTOKEN_AVAILABLE:
        try:
            enc = tiktoken.encoding_for_model(model)
            return len(enc.encode(text))
        except (KeyError, ValueError):
            # 未知 model 名 → 退化为 cl100k_base
            try:
                enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text))
            except Exception:
                pass  # 退化到 len // 2
    return len(text) // 2

# ---------------------------------------------------------------------------
# AgentState：扩展 BaseFlowState 增加 ReAct 字段
# ---------------------------------------------------------------------------


class AgentState(BaseFlowState, total=False):
    """Agent 引擎的 state schema，继承 BaseFlowState。

    字段必须 msgpack 可序列化（LangGraph checkpointer 限制）：

    - messages      — LangChain BaseMessage 列表（**operator.add 累积**）
    - iterations    — 已执行步数（最后一次返回值覆盖）
    - system_prompt — SKILL.md 拼装出的系统提示（最后一次覆盖）
    - gate_decision — HumanGate 决策（Day 4:None / "approve" / "reject"，route_gate_node 写入）
    - gate_id       — HumanGate gate 标识（Day 4:route_gate_node 写入，msgpack 可序列化 str）
    - gate_check    — HumanGate check 原始 dict（Day 4:route_gate_node 写入，存 tool 返回值）
    - human_gate_payload — HumanGate interrupt payload（Day 4:route_gate_node 写入，HumanGateInterruptPayload 序列化）
    - _truncated    — truncate_node 标记（Day 4:True if truncated）

    **不放进 state 的字段**（通过闭包注入）：
    - tools         — ToolDef 列表（Pydantic 模型，msgpack 不支持）
    注：``seen_states`` 由 ``make_post_tool_check`` 闭包内部维护，
    不进 state、不进实例，确保跨任务隔离（Day 3 评审修复）。
    """

    messages: Annotated[list[Any], operator.add]  # 累积所有 node 返回的新消息
    iterations: int
    system_prompt: str
    # Day 4:HumanGate 决策/标识(必须显式定义,LangGraph TypedDict 不会自动存 schema 外字段)
    gate_decision: str | None
    gate_id: str
    gate_check: dict[str, Any]
    human_gate_payload: dict[str, Any]
    # Day 4:truncate_node 标记
    _truncated: bool


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
                # Day 3 评审修复（🟢#7）：异常脱敏，避免 SSH 凭据 / API key
                # 等敏感信息随异常原文进入 LLM 上下文。
                # 读类工具（read_/list_）一般不带凭据，可保留详细错误。
                if c["name"].startswith(("read_", "list_")):
                    # 读类工具一般不带凭据，保留详细错误
                    content = (
                        f"Tool '{c['name']}' failed: {type(e).__name__}: {e}. "
                        "请改用其他方案或向用户报告。"
                    )
                else:
                    # 其他工具（可能涉及凭据）只保留异常类名，避免敏感信息外泄
                    content = (
                        f"Tool '{c['name']}' failed: {type(e).__name__}. "
                        "请改用其他方案或向用户报告。"
                    )
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
    *,
    gate_tools: list[str] | None = None,
) -> Callable[[AgentState], str]:
    """构造 ``post_tool_check`` 条件边函数。

    路由（按优先级短路求值）:
    - "loop"       — 死循环检测触发（同一 tool+args 反复调用）
    - "state_loop" — 状态指纹重复（绕圈）
    - "gate"       — 最近一次 tool_call.name ∈ gate_tools（Day 4 新增）
    - "rlhf"       — 正常 → 进入 rlhf_collect_node → 回到 llm_node

    Day 3 评审修复：
        ``seen_states`` set 移到闭包内，每次 build 新建，
        避免跨任务指纹污染。原先 ``AgentRunner`` 实例级持有同一 set，
        任务 A 的指纹会污染任务 B。

    Day 4 新增：gate_tools 非空时,最近一次 tool_call.name 在 gate_tools 列表内
    才会返 "gate"(给 route_gate_node 用)。gate_tools 为空时永远不返 "gate",
    保持向后兼容。
    """

    seen_states: set[str] = set()
    gate_tools_set: set[str] = set(gate_tools) if gate_tools else set()

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

        # Day 4 修复:state fingerprint 不能再用 compute_state_fingerprint —
        # 它 hash 的字段(current_step / last_tool / tool_args / output_data / errors)
        # 在 AgentState 里都不存在,导致 fingerprint 永远不变,第二次 tool 就触发
        # state_loop 把 Agent 终止。
        # 这里用 AgentState 实际有的字段(last_tool + tool_args + iterations)做
        # fingerprint,确保每次 tool 后 fingerprint 变化,不会误判 state_loop。
        last_tool_name = ""
        last_tool_args = {}
        if last_ai is not None:
            for call in getattr(last_ai, "tool_calls", []) or []:
                c = _to_tool_call_dict(call)
                last_tool_name = c["name"]
                last_tool_args = c["args"]
                break
        fp_payload = json.dumps(
            {
                "last_tool": last_tool_name,
                "tool_args": last_tool_args,
                "iterations": state.get("iterations", 0),
            },
            sort_keys=True,
            default=str,
        )
        import hashlib
        fp = hashlib.sha256(fp_payload.encode("utf-8")).hexdigest()
        if fp in seen_states:
            return "state_loop"
        seen_states.add(fp)

        # Day 4:gate 路径(gate_tools 非空 + 最近 tool_call 在列表内)
        if gate_tools_set and last_ai is not None:
            for call in getattr(last_ai, "tool_calls", []) or []:
                c = _to_tool_call_dict(call)
                if c["name"] in gate_tools_set:
                    return "gate"

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
        # 注：``seen_states`` 已不再入 AgentState（Day 3 评审修复，由
        # make_post_tool_check 闭包持有），从过滤列表中移除。
        serializable_state = {
            k: v
            for k, v in state.items()
            if k not in ("messages", "tools", "_memory")
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
        # seen_states 由 make_post_tool_check 闭包持有，不入 state
    )


# ---------------------------------------------------------------------------
# 节点函数工厂:route_gate_node (Day 4 尹一帆)
# ---------------------------------------------------------------------------


def _last_tool_call(state: AgentState) -> dict | None:
    """从 state.messages 提取最近一次 tool_call 的 dict。

    扫描顺序:从后往前找最近的 AIMessage,取第一个 tool_call。
    如果没有 AIMessage 或没有 tool_calls,返回 None。
    """
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                return _to_tool_call_dict(tool_calls[0])
    return None


def _last_tool_message(state: AgentState) -> ToolMessage | None:
    """从 state.messages 提取最近一次 ToolMessage(对应最近一次 tool 执行结果)。"""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            return msg
    return None


def make_route_gate_node(
    gate_tools: list[str],
    thresholds: RiskThresholds | None = None,
) -> Callable[[AgentState], dict]:
    """构造 ``route_gate_node``:tool 后置 gate,仅当最近一次 tool_call.name ∈ gate_tools
    且对应 ToolMessage 返回值表示需要人审时,调 LangGraph interrupt。

    触发条件(全部满足才触发):
    1. 最近一次 tool_call.name ∈ gate_tools
    2. 最近一次 ToolMessage.content 是 JSON 且含 ``requires_human=True``
       (或纯文本含 "requires_human: True" 之类标记;主路径是 JSON)
    3. 当前 state 没有 gate_decision(还没人审批过)

    恢复后:
    - parse_resume_decision(Command(resume=...)) 解析出 decision 字符串
    - 返回 ``gate_decision`` 字段给后续 rlhf/node 看到

    复用 ``runner.human_gate`` 的 should_interrupt / build_interrupt_payload /
    parse_resume_decision,**几乎零新代码**。

    Args:
        gate_tools: 触发 gate 的 tool id 列表,如 ``["check_gate"]``。空列表等于不启用。
        thresholds: RiskThresholds 实例,None 时用默认值(Var=0.04 / DD=-0.15 / PosLim=0.8 / Corr=0.7)。

    关键依赖:
    - 调 LangGraph ``interrupt()``,**必须配合 SqliteSaver**;无 checkpointer 时是 no-op
    - 节点返回新 dict 含 ``gate_decision`` / ``human_gate_payload``,不入 _memory(memory 字段由 BaseFlowState 透传)
    """
    thresholds = thresholds or RiskThresholds()
    gate_tools_set = set(gate_tools)

    def route_gate_node(state: AgentState) -> dict:
        # 0. gate_tools 为空 / 已审批过 → 跳过
        if not gate_tools_set or state.get("gate_decision"):
            return {}

        # 1. 找最近一次 tool_call
        last_call = _last_tool_call(state)
        if last_call is None or last_call["name"] not in gate_tools_set:
            return {}

        # 2. 找对应 ToolMessage(可能不连续,如 agent 调了 check_gate 后没继续)
        last_tool_msg = _last_tool_message(state)
        if last_tool_msg is None:
            return {}

        # 3. 解析 ToolMessage.content,判断是否需要人审
        # 兼容 JSON 和 Python repr(tool_node 用 str(dict) 序列化为 repr)
        content_str = last_tool_msg.content
        content_obj: Any = None
        if isinstance(content_str, dict):
            content_obj = content_str
        elif isinstance(content_str, str):
            try:
                content_obj = json.loads(content_str)
            except (json.JSONDecodeError, TypeError):
                # 退化为 Python repr(单引号 dict)
                try:
                    import ast

                    content_obj = ast.literal_eval(content_str)
                except (ValueError, SyntaxError):
                    return {}  # 解析不了,跳过
        if not isinstance(content_obj, dict):
            return {}

        if not isinstance(content_obj, dict):
            return {}
        if not content_obj.get("requires_human", False):
            return {}

        # 4. 触发 interrupt
        gate_id = state.get("gate_id") or make_gate_id(state.get("thread_id", "agent"))
        reasons = content_obj.get("reasons", [])

        if not _INTERRUPT_AVAILABLE:
            # 没装 langgraph.types.interrupt,降级为"把 decision 设成 None,Agent 自己判断"
            return {"gate_id": gate_id, "gate_check": content_obj}

        # 调 LangGraph interrupt
        resume_payload = interrupt(
            build_interrupt_payload(
                gate_id=gate_id,
                risk_profile=content_obj.get("risk_profile", {}),
                reasons=reasons,
            )
        )
        decision = parse_resume_decision(resume_payload)

        return {
            "gate_id": gate_id,
            "gate_decision": decision,
            "gate_check": content_obj,
            "human_gate_payload": build_interrupt_payload(
                gate_id=gate_id,
                risk_profile=content_obj.get("risk_profile", {}),
                reasons=reasons,
                decision=decision,
            ),
        }

    return route_gate_node


# ---------------------------------------------------------------------------
# 节点函数工厂:truncate_node (Day 4 尹一帆 — 引擎 gap #2)
# ---------------------------------------------------------------------------


def _truncate_text_to_tokens(text: str, max_tokens: int, *, model: str) -> str:
    """把字符串截断到最多 max_tokens tokens。

    简单实现:按字符级硬截(逐字符减到阈值内),保留尾部 50 字符作为"省略提示"。
    没用 tiktoken 精确 token 切(精度低但简单)。
    """
    if _estimate_tokens(text, model=model) <= max_tokens:
        return text
    # 粗略截断:按 char 估算(每 2 字符 ≈ 1 token),保留尾部 50 字符
    approx_chars = max_tokens * 2
    if len(text) <= approx_chars:
        return text
    return text[: approx_chars - 50] + "\n\n[... truncated for token budget ...]"


def make_truncate_node(
    max_tokens: int = 4000,
    *,
    model_name: str = "gpt-4",
    head_preserve: int = 4,
    tail_preserve: int = 6,
) -> Callable[[AgentState], dict]:
    """构造 ``truncate_node``:tool 后置 token 裁剪。

    检查 ``state["messages"]`` 总 token 数,超 ``max_tokens`` 时,截断中段消息(头 N + 尾 M 保留)。
    截断后的 messages 列表作为整体返回(LangGraph ``operator.add`` reducer 追加,
    等效"替换"——LangGraph 后续会处理,实际行为是 messages 累积翻倍;
    接受这个 trade-off,后续可改 AgentState 的 messages reducer 为 replace_if_truncated)。

    Args:
        max_tokens: 总 messages 的 token 预算;超此值才裁剪
        model_name: tiktoken model 名(默认 gpt-4)
        head_preserve: 头 N 条消息不裁(系统提示 + 早期对话)
        tail_preserve: 尾 M 条消息不裁(最近上下文)

    注意:本节点不动 state["messages"] 的旧内容,只返回新的 truncated 列表。
    累积翻倍是已知限制,可后续通过自定义 reducer 优化。
    """
    def truncate_node(state: AgentState) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {}

        # 计算总 token
        total = 0
        for m in messages:
            content = getattr(m, "content", "") or ""
            if isinstance(content, str):
                total += _estimate_tokens(content, model=model_name)
            else:
                # 非字符串 content(罕见)用 repr 估算
                total += _estimate_tokens(repr(content), model=model_name)

        if total <= max_tokens:
            return {}

        # 头/尾保留,中间截断
        n = len(messages)
        if n <= head_preserve + tail_preserve:
            # 太短,不裁
            return {}

        head = messages[:head_preserve]
        middle = messages[head_preserve : n - tail_preserve]
        tail = messages[n - tail_preserve :]

        truncated_middle: list[Any] = []
        for m in middle:
            content = getattr(m, "content", "")
            if not isinstance(content, str):
                truncated_middle.append(m)
                continue
            mid_tokens = _estimate_tokens(content, model=model_name)
            # 中段单条也超阈值才截
            if mid_tokens > max_tokens // max(n, 1):
                # 用 max_tokens/2 留余量
                new_content = _truncate_text_to_tokens(
                    content, max_tokens // 2, model=model_name
                )
                # 复制消息,替换 content
                from copy import copy
                new_msg = copy(m)
                try:
                    new_msg.content = new_content
                except Exception:
                    pass  # 某些消息类型不可变,跳过
                truncated_middle.append(new_msg)
            else:
                truncated_middle.append(m)

        truncated = head + truncated_middle + tail
        # 标记已截断,让后续节点知道
        return {
            "messages": truncated,
            "_truncated": True,
        }

    return truncate_node


__all__ = [
    "AgentState",
    "make_llm_node",
    "make_tool_node",
    "make_should_continue",
    "make_post_tool_check",
    "make_rlhf_collect_node",
    "make_route_gate_node",
    "make_truncate_node",
    "_estimate_tokens",
    "init_agent_state",
]
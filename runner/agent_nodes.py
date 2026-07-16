"""StateGraph 节点函数 — Day 3 尹一帆 + Day 5 RLHF 重构。

节点函数（对应架构 §3.1 / §3.2）：

| 节点                    | 类型        | 职责                                                |
|-------------------------|-------------|-----------------------------------------------------|
| ``llm_node``            | 普通 node   | 调 LLM，返回 AIMessage（带 tool_calls 或 final）    |
| ``tool_node``           | 普通 node   | 执行 tool_calls，返回 ToolMessage 列表              |
| ``rlhf_collect_node``   | 普通 node   | 记录 RLHF 日志 — Day 5 重构：改用新格式 make_rlhf_entry() |
| ``make_routing_edge``   | 条件边函数  | llm 后轻量路由: "continue" / "end"                  |
| ``make_tool_routing_edge`` | 条件边   | tool 后路由: "rlhf" / "max_iter" / "human_gate" / "end" |

设计要点：
- 每个节点函数都是纯函数工厂（不持有状态），依赖通过闭包注入
- 依赖（model / tools / registry；rlhf_collector 已弃用仅保留兼容）由 ``AgentRunner`` 接线
- tools 通过 ``make_llm_node(model, tools)`` 闭包注入，**不放入 state**（ToolDef 不可 msgpack 序列化）
- 节点函数本身可单测（mock LLM + mock tool）
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from runner.langgraph_base import BaseFlowState
from runner.routing.fingerprint import compute_state_fingerprint
from runner.routing.router import RouteDecision, route_next_step
from runner.routing.guards import MAX_ITERATIONS as ROUTING_MAX_ITERATIONS
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
    - risk_metrics  — 风控指标（由 calc_risk_stub 写入，router.py 消费）
    - task_status   — 任务状态（"done" 触发 finish）
    - human_review_result — 人工审核结果（"proceed"/"abort"，由 request_human_review tool 写入）
    - task_goal     — 任务目标描述（取自 input_data.task）
    - _gate_purpose — Day 5: risk/loop/max_iter, 内部追踪 gate 来源
    - current_step  — LLM 本轮意图的完整工具批次（list[str]，用于 fingerprint）
    - last_tool     — 本轮实际执行的 tool 列表（list[str]，用于 fingerprint）
    - tool_args     — 本轮实际执行的 tool 参数列表（list[dict]，用于 fingerprint）
    - errors        — 工具执行错误信息（list[str]，operator.add 累积）
    - output_data   — 标准化产出（给 MCP / OpenCode 状态回流消费）
    - artifacts     — 产物路径列表（operator.add 累积）
    - gate          — OpenCode 可展示的 HumanGate payload

    **不放进 state 的字段**（通过闭包注入）：
    - tools         — ToolDef 列表（Pydantic 模型，msgpack 不支持）
     注：``seen_states`` 由 ``make_post_tool_check`` 闭包内部维护，
     不进 state、不进实例，确保跨任务隔离（Day 3 评审修复）。
    """

    messages: Annotated[list[Any], operator.add]  # 累积所有 node 返回的新消息
    iterations: int
    system_prompt: str
    risk_metrics: dict | None
    task_status: str | None
    human_review_result: str | None
    task_goal: str
    _gate_purpose: str | None  # Day 5: risk/loop/max_iter, 内部追踪 gate 来源
    current_step: list[str] | None
    last_tool: list[str] | None
    tool_args: list[dict[str, Any]] | None
    errors: list[str] | None
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add] | None
    gate: dict[str, Any] | None


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

        updates = {
            "messages": [response],
            "iterations": state.get("iterations", 0) + 1,
        }

        tc = getattr(response, "tool_calls", None)
        if tc:
            names = []
            for call in tc:
                if isinstance(call, dict):
                    names.append(call.get("name", ""))
                else:
                    names.append(getattr(call, "name", ""))
            updates["current_step"] = names

        return updates

    return llm_node


def make_tool_node(
    registry: ToolRegistry,
) -> Callable[[AgentState], dict]:
    """构造 ``tool_node``：执行最近一个 AIMessage 里的所有 tool_calls。

    tool 返回的是非 str 数据且是 dict 时，会尝试注入 state：
    - ``calc_risk_stub`` → ``risk_metrics``
    - ``task_done`` / ``mark_complete`` → ``task_status="done"``
    - ``request_human_review`` → ``human_review_result``
    """

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
        # 收集需要注入 state 的字段
        state_updates: dict[str, Any] = {}

        executed_tools: list[str] = []
        executed_args: list[dict[str, Any]] = []
        tool_errors: list[str] = []

        for call in tool_calls:
            c = _to_tool_call_dict(call)
            try:
                output = registry.call(c["name"], c["args"], ctx=ctx)
                content = output if isinstance(output, str) else str(output)
                # 注入逻辑：非 str 的 dict 输出 → 根据 tool name 写入 state
                if isinstance(output, dict):
                    state_updates.update(_extract_state_fields(c["name"], output))
            except Exception as e:
                # Pattern 5: request_human_review 内 interrupt() 会抛 GraphInterrupt。
                # 必须向上冒泡，否则人审 gate 会被吞成普通 tool error。
                try:
                    from langgraph.errors import GraphBubbleUp

                    if isinstance(e, GraphBubbleUp):
                        raise
                except ImportError:
                    if type(e).__name__ in ("GraphInterrupt", "GraphBubbleUp"):
                        raise
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
            executed_tools.append(c["name"])
            executed_args.append(c["args"])
            results.append(
                ToolMessage(content=content, tool_call_id=c["id"], name=c["name"])
            )

        if executed_tools:
            state_updates["last_tool"] = executed_tools
            state_updates["tool_args"] = executed_args
        if tool_errors:
            state_updates["errors"] = tool_errors

        state_updates["messages"] = results
        return state_updates

    return tool_node


def _extract_state_fields(tool_name: str, output: dict) -> dict[str, Any]:
    """从 tool 输出中提取需要注入 AgentState 的字段。

    当前注册的映射：
    - calc_risk_stub → risk_metrics（完整 dict，含阈值）+ risk_profile（测试场景支持）
    - calc_risk → risk_metrics（完整 dict，含阈值）
    - mark_task_done / task_done → task_status="done"
    - write_blackboard → task_status="done"（流程最后一步，写入完成后标记结束）
    - request_human_review → human_review_result（"proceed"/"abort"，由 _human_gate_node 最终裁决）
    """
    updates: dict[str, Any] = {}

    if tool_name == "calc_risk_stub":
        # 注入 risk_metrics
        updates["risk_metrics"] = output
        # 测试场景支持：自动构造简单的 risk_profile 让 HumanGate 能触发
        # 生产场景会通过 generate_risk_profile 工具覆盖此值
        updates["risk_profile"] = {
            "strategy_id": output.get("strategy_id"),
            "as_of_date": output.get("as_of_date"),
            "max_drawdown": output.get("max_drawdown"),
            "tail_risk_var_99": output.get("tail_risk_var_99"),
            "volatility": output.get("volatility"),
        }
    elif tool_name == "calc_risk":
        # 生产场景：只注入 risk_metrics，不自动生成 risk_profile
        updates["risk_metrics"] = output

    if tool_name in ("mark_task_done", "task_done", "mark_complete"):
        updates["task_status"] = "done"

    if tool_name == "write_blackboard":
        updates["task_status"] = "done"

    if tool_name in ("request_human_review", "human_review"):
        # Day 4 俞高磊：request_human_review 现在含 interrupt() 暂停，
        # 外部 resume 后返回 {"decision": "proceed"/"abort"}
        decision = output.get("decision", "abort")
        updates["human_review_result"] = decision
        # 同时注入 gate_purpose 标记这是 risk gate
        if "_gate_purpose" not in updates:
            updates["_gate_purpose"] = "risk"

    # Day 4 控制平面状态回流：标准字段透传给 AgentState/MCP。
    if "output_data" in output and isinstance(output.get("output_data"), dict):
        updates["output_data"] = output["output_data"]

    if "artifacts" in output:
        artifacts = output.get("artifacts") or []
        if isinstance(artifacts, str):
            artifacts = [artifacts]
        if isinstance(artifacts, list):
            updates["artifacts"] = [str(item) for item in artifacts]

    if "gate" in output and isinstance(output.get("gate"), dict):
        updates["gate"] = output["gate"]

    if "errors" in output:
        errors = output.get("errors") or []
        if isinstance(errors, str):
            errors = [errors]
        if isinstance(errors, list):
            updates["errors"] = [str(item) for item in errors]

    return updates


# ---------------------------------------------------------------------------
# build execution trace helper (shared by routing edges + rlhf node)
# ---------------------------------------------------------------------------


def _build_execution_trace(messages: list) -> list[dict[str, Any]]:
    """从 AIMessage + ToolMessage 对中构造 execution_trace。

    按 ``tool_call_id`` 精确配对，而非依赖位置顺序，
    避免 LangGraph ``operator.add`` 消息累积导致误配对。
    """
    # Collect all tool_calls from AIMessages → {call_id: info}
    pending: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in (getattr(msg, "tool_calls", None) or []):
                c = _to_tool_call_dict(tc)
                cid = c.get("id", "")
                if cid:
                    pending[cid] = {"tool": c.get("name", "unknown"), "args": c.get("args", {})}

    # Collect all ToolMessage results → {call_id: content}
    results: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            cid = getattr(msg, "tool_call_id", "")
            if cid:
                results[cid] = getattr(msg, "content", "")

    # Pair by call_id
    trace: list[dict[str, Any]] = []
    for cid, call in pending.items():
        content = results.get(cid, "")
        has_error = "failed" in content.lower() or "error" in content.lower()
        trace.append({
            "tool": call["tool"],
            "success": not has_error,
            "result": content if not has_error else "",
            "error": content if has_error else "",
        })
    return trace


# ---------------------------------------------------------------------------
# 条件边函数工厂
# ---------------------------------------------------------------------------


def _log_abort_rlhf(state: AgentState, system_decision: str) -> None:
    """Write an RLHF entry for abort decisions (ABORT_MAX_ITERATIONS)."""
    from runner.routing.rlhf_logger import make_rlhf_entry, log_rlhf_entry
    from runner.routing.fingerprint import compute_state_fingerprint
    entry = make_rlhf_entry(
        thread_id=state.get("thread_id", ""),
        group=state.get("group", ""),
        state_fingerprint=compute_state_fingerprint(dict(state)),
        system_decision=system_decision,
        iteration=state.get("iterations", 0),
        checkpoint_id=state.get("thread_id", ""),
    )
    log_rlhf_entry(entry)


def make_routing_edge(
    max_iterations: int = ROUTING_MAX_ITERATIONS,
) -> Callable[[AgentState], str]:
    """构造 ``llm`` 节点的条件边函数。

    在 LLM 生成 AIMessage 之后调用。如果 AIMessage 有 tool_calls → "continue"，
    否则 → "end"。

    返回 LangGraph 条件边的目标名（str）：
    - "continue"  — LLM 请求了 tool_calls，需要执行
    - "end"       — LLM 给出了最终答案（无 tool_calls）
    """

    def routing_edge(state: AgentState) -> str:
        messages = state.get("messages", [])
        if not messages:
            # print("[DEBUG routing_edge] no messages → end")
            return "end"

        if state.get("iterations", 0) >= max_iterations:
            # print(f"[DEBUG routing_edge] iterations={state.get('iterations', 0)} >= {max_iterations} → end")
            return "end"

        last = messages[-1]
        if not isinstance(last, AIMessage):
            # print(f"[DEBUG routing_edge] last is not AIMessage → end")
            return "end"

        if not getattr(last, "tool_calls", None):
            task_status = state.get("task_status")
            # print(f"[DEBUG routing_edge] no tool_calls, task_status={task_status!r}")
            if task_status == "done":
                return "end"
            return "continue"

        return "continue"

    return routing_edge


def make_tool_routing_edge(
    max_iterations: int = ROUTING_MAX_ITERATIONS,
    fingerprint_history: list[str] | None = None,
) -> Callable[[AgentState], str]:
    """构造 ``tool`` 节点的条件边函数（接入 ``route_next_step``）。

    在 tool_node 执行完 tool_calls 之后调用。汇总所有 AIMessage 的 tool_call
    历史作为路由输入，委托 ``route_next_step`` 做出决策：

    路由结果映射：
    - 死循环 → "human_gate"
    - max_iterations → "max_iter"
    - risk threshold → "human_gate"
    - finish → "end"
    - 正常 → "rlhf"（继续循环，回到 rlhf 或 llm 节点）

    ``fingerprint_history`` 由 ``AgentRunner.build()`` 创建并共享给
    ``make_rlhf_collect_node``，确保两处使用相同的指纹历史。
    如果调用方不传，在闭包内新建（单测兼容）。

    返回 LangGraph 条件边的目标名（str）。
    """
    if fingerprint_history is None:
        fingerprint_history = []

    def tool_routing_edge(state: AgentState) -> str:
        nonlocal fingerprint_history

        messages = state.get("messages", [])
        iterations = state.get("iterations", 0)

        # print(f"[DEBUG tool_routing_edge ENTRY] iterations={iterations}, messages_count={len(messages)}")

        if iterations >= max_iterations:
            # print(f"[DEBUG tool_routing_edge] iterations >= max_iterations → max_iter")
            return "max_iter"

        tool_call_history: list[str] = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                for tc in (getattr(msg, "tool_calls", None) or []):
                    c = _to_tool_call_dict(tc)
                    name = c.get("name", "")
                    if name:
                        tool_call_history.append(name)

        # print(f"[DEBUG tool_routing_edge] tool_call_history={tool_call_history}")

        fp = compute_state_fingerprint(dict(state))
        fingerprint_history.append(fp)

        routing_state = {
            "iteration_count": iterations,
            "tool_call_history": tool_call_history,
            "fingerprint_history": list(fingerprint_history),
            "risk_metrics": state.get("risk_metrics"),
            "human_review_result": state.get("human_review_result"),
            "task_status": state.get("task_status"),
            "execution_trace": _build_execution_trace(messages),
            "task_goal": state.get("task_goal", "") or state.get("input_data", {}).get("task", ""),
        }

        result = route_next_step(routing_state)
        # print(f"[DEBUG tool_routing_edge] iterations={iterations}, "
        #       f"tool_history={tool_call_history}, "
        #       f"fp_history_len={len(fingerprint_history)}, "
        #       f"decision={result.decision.value}, reason={result.reason!r}")
        # print(f"[DEBUG state fields] current_step={state.get('current_step')!r}, "
        #       f"last_tool={state.get('last_tool')!r}, "
        #       f"tool_args={state.get('tool_args')!r}")

        if result.decision == RouteDecision.ABORT_LOOP:
            return "human_gate"
        elif result.decision == RouteDecision.ABORT_MAX_ITERATIONS:
            # Write RLHF entry for max_iter abort before routing to END
            _log_abort_rlhf(state, "abort_max_iterations")
            return "max_iter"
        elif result.decision == RouteDecision.HUMAN_GATE:
            return "human_gate"
        elif result.decision == RouteDecision.FINISH:
            return "end"
        # CONTINUE → 继续执行
        return "rlhf"

    return tool_routing_edge


# ---------------------------------------------------------------------------
# Deprecated: legacy condition edge factories (retained for backward compat)
# ---------------------------------------------------------------------------


def make_should_continue(
    max_iterations: int = ROUTING_MAX_ITERATIONS,
) -> Callable[[AgentState], str]:
    """构造 ``should_continue`` 条件边函数。

    .. deprecated::
        Day 3 评审后由 ``make_routing_edge`` 取代。
        保留此函数以备回退和兼容性测试。

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
    loop_detector: Any,
) -> Callable[[AgentState], str]:
    """构造 ``post_tool_check`` 条件边函数。

    .. deprecated::
        Day 3 评审后由 ``make_tool_routing_edge`` 取代。
        保留此函数以备回退和兼容性测试。

    路由：
    - "loop"       — 死循环检测触发（同一 tool+args 反复调用）
    - "state_loop" — 状态指纹重复（绕圈）
    - "rlhf"       — 正常 → 进入 rlhf_collect_node → 回到 llm_node

    Day 3 评审修复：
        ``seen_states`` set 移到闭包内，每次 build 新建，
        避免跨任务指纹污染。原先 ``AgentRunner`` 实例级持有同一 set，
        任务 A 的指纹会污染任务 B。
    """

    seen_states: set[str] = set()

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
        fp = compute_state_fingerprint(dict(state))
        if fp in seen_states:
            return "state_loop"
        seen_states.add(fp)

        return "rlhf"

    return post_tool_check


# ---------------------------------------------------------------------------
# RLHF 收集节点
# ---------------------------------------------------------------------------


def make_rlhf_collect_node(
    rlhf_collector: Any,  # 保留兼容（可为 None），但不再写入旧格式
    fingerprint_history: list[str] | None = None,
) -> Callable[[AgentState], dict]:
    """构造 ``rlhf_collect_node``。

    Day 5 RLHF 重构：改用 ``make_rlhf_entry()`` + ``log_rlhf_entry()`` 新格式。
    重算路由决策获取 system_decision，记录 risk_features / risk_score / label。
    rlhf_collector 参数保留向后兼容但不再用于写日志。

    ``fingerprint_history`` 由 ``AgentRunner.build()`` 创建并共享给
    ``make_tool_routing_edge``，确保两处使用相同的指纹历史。
    如果调用方不传，在闭包内新建（单测兼容）。
    """
    if fingerprint_history is None:
        fingerprint_history = []

    def rlhf_collect_node(state: AgentState) -> dict:
        nonlocal fingerprint_history

        messages = state.get("messages", [])
        # 取最近一个 AIMessage（含 tool_calls 的）作为 action
        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)),
            None,
        )
        tool_calls = (
            [_to_tool_call_dict(c) for c in (last_ai.tool_calls or [])]
            if last_ai is not None
            else []
        )

        # 若无 tool 调用，跳过记录（无 action 可分析，避免写入空日志）
        if not tool_calls:
            return {}  # 不修改 state

        # ── Day 5: 用新格式写入 RLHF 日志 ──
        from runner.routing.rlhf_logger import make_rlhf_entry, log_rlhf_entry

        # 重建路由状态并重算 system_decision
        # NOTE：使用 AgentRunner.build() 共享的 fingerprint_history，
        # 而非 [compute_state_fingerprint(dict(state))] 单步快照。
        tool_call_history: list[str] = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                for tc in (getattr(msg, "tool_calls", None) or []):
                    c = _to_tool_call_dict(tc)
                    name = c.get("name", "")
                    if name:
                        tool_call_history.append(name)

        # 计算指纹并累加到共享历史
        fp = compute_state_fingerprint(dict(state))
        fingerprint_history.append(fp)

        routing_state = {
            "iteration_count": state.get("iterations", 0),
            "tool_call_history": tool_call_history,
            "fingerprint_history": list(fingerprint_history),
            "risk_metrics": state.get("risk_metrics"),
            "task_status": state.get("task_status"),
            "execution_trace": _build_execution_trace(messages),
            "task_goal": state.get("task_goal", "") or state.get("input_data", {}).get("task", ""),
        }
        result = route_next_step(routing_state)
        system_decision = result.decision.value  # RouteDecision→str

        # 提取 tool 信息 + 执行状态
        tool_name = tool_calls[0]["name"] if tool_calls else ""
        tool_args = tool_calls[0]["args"] if tool_calls else {}

        # 判断工具执行是否成功
        last_tool_result = ""
        success = True
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                last_tool_result = getattr(msg, "content", "")
                success = "failed" not in last_tool_result.lower() and "error" not in last_tool_result.lower()
                break

        entry = make_rlhf_entry(
            thread_id=state.get("thread_id", ""),
            group=state.get("group", ""),
            state_fingerprint=fp,
            tool_name=tool_name,
            tool_args=tool_args,
            success=success,
            summary=last_tool_result[:200] if last_tool_result else "",
            system_decision=system_decision,
            human_decision="",                 # continue 路径无人审，事后回填
            risk_features=state.get("risk_metrics"),
            checkpoint_id=state.get("thread_id", ""),
            iteration=state.get("iterations", 0),
        )
        log_rlhf_entry(entry)

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
        task_goal=user_msg,
        output_data=None,
        artifacts=[],
        errors=[],
        gate=None,
        # seen_states 由 make_post_tool_check 闭包持有，不入 state
    )



# ---------------------------------------------------------------------------
# Token 估算 + truncate 节点 — Day 4 尹一帆（Day 5 从 main 移植回 PR25 引擎）
# 注意：当前 truncate 用 operator.add reducer 会导致 messages 累积翻倍（已知限制），
# Week 2 配合自定义 reducer 优化。demo 场景不长，不触发。
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
    "make_routing_edge",
    "make_tool_routing_edge",
    "_build_execution_trace",
    "_log_abort_rlhf",
    "make_truncate_node",
    "_estimate_tokens",
    "init_agent_state",
]

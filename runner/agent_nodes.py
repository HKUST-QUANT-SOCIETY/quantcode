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
- 依赖（model / tools / registry）由 ``AgentRunner`` 接线
- tools 通过 ``make_llm_node(model, tools)`` 闭包注入，**不放入 state**（ToolDef 不可 msgpack 序列化）
- 节点函数本身可单测（mock LLM + mock tool）
"""
from __future__ import annotations

import operator
import os
import time
from typing import Annotated, Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from runner.langgraph_base import BaseFlowState
from runner.routing.fingerprint import compute_state_fingerprint
from runner.routing.router import RouteDecision, route_next_step
from runner.routing.guards import MAX_ITERATIONS as ROUTING_MAX_ITERATIONS
from runner.solution_workflow import (
    filter_tools_for_phase,
    sync_phase_from_blackboard,
    tool_allowed_in_phase,
    tool_denied_message,
)
from tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# AgentState：扩展 BaseFlowState 增加 ReAct 字段
# ---------------------------------------------------------------------------


def _msg_identity(msg: Any) -> Any:
    """给无 id 的消息派生稳定标识（供去重 diff）。

    - 有 ``id`` 属性（LangGraph add_messages 会赋 id）用 id
    - 否则 (类名, content, tool_call_id, tool_calls 指纹)：空 content 的
      AIMessage 各带不同 tool_calls，不能仅凭空 content 合并成一条
    """
    mid = getattr(msg, "id", None)
    if mid:
        return ("id", mid)
    tcs = tuple(
        (
            (c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")),
            (c.get("id", "") if isinstance(c, dict) else getattr(c, "id", "")),
        )
        for c in (getattr(msg, "tool_calls", None) or [])
    )
    return (
        "content",
        type(msg).__name__,
        str(getattr(msg, "content", "") or ""),
        str(getattr(msg, "tool_call_id", "") or ""),
        tcs,
    )


def merge_messages(current: list[Any] | None, update: list[Any] | None) -> list[Any]:
    """messages 通道的自定义 reducer（替代 operator.add）。

    翻倍根因：operator.add 把"节点返回的新消息"追加进累计值没问题，但
    truncate / 摘要类节点返回的是 **整个消息列表**，每个 superstep 都会把
    累计值原样再 add 一遍 → 长度每轮翻倍。

    修复（两层）：
    - 节点返回 ``_ReplaceMessages``（整体替换语义，truncate / rebuild 用）
      → 直接取该列表，不做合并
    - 正常节点返回普通 list（只带新消息）→ 按 ``_msg_identity`` 去重追加，
      行为与 operator.add 一致，且即使误传全量列表也不翻倍
    """
    if update is None:
        return list(current or [])
    if isinstance(update, _ReplaceMessages):
        return list(update)
    if current is None:
        return list(update)

    existing_keys = {_msg_identity(m) for m in current}
    merged = list(current)
    for m in update:
        key = _msg_identity(m)
        if key not in existing_keys:
            merged.append(m)
            existing_keys.add(key)
        else:
            # 同 id 消息重发 → 用新版本覆盖（truncate 改写 content 的场景）
            for i, old in enumerate(merged):
                if _msg_identity(old) == key:
                    merged[i] = m
                    break
    return merged


# P0-8 §4.4：context 占用阈值（占用比）
CONTEXT_SNAPSHOT_RATIO = 0.7
CONTEXT_REBUILD_RATIO = 0.9


def _context_token_limit() -> int:
    """上下文窗口上限（tokens）。env ``QUANTCODE_CONTEXT_TOKENS``，默认 128000。"""
    try:
        return int(os.environ.get("QUANTCODE_CONTEXT_TOKENS", "128000"))
    except ValueError:
        return 128000


def estimate_context_chars(state: dict[str, Any]) -> float:
    """估算当前 context 占用 tokens。

    公式：messages content 长度之和 + system_prompt 长度，每 4 字符 ≈ 1 token。
    # ponytail: 字符/4 近似 token，升级路径=tiktoken 实测
    """
    chars = len(state.get("system_prompt") or "")
    for m in state.get("messages") or []:
        content = getattr(m, "content", "")
        if not isinstance(content, str):
            content = repr(content)
        chars += len(content)
    return chars / 4.0


def context_usage_ratio(state: dict[str, Any]) -> float:
    """context 占用比 = 估算 tokens / 窗口上限。"""
    return estimate_context_chars(state) / max(_context_token_limit(), 1)


def make_checkpoint_event(
    *,
    thread_id: str,
    ratio: float,
    kind: str = "snapshot",
) -> dict[str, Any]:
    """构造一个 checkpoint_snapshot 事件 dict（往 execution_trace 追加用）。

    thread_id 是 state 里的 thread id（唯一执行流），与 checkpoint_id 解耦；
    ratio 为占用比（0-1+），kind 为 snapshot（>70% 快照）或 rebuild（>90% 重建）。
    """
    return {
        "event_type": "checkpoint_snapshot",
        "thread_id": thread_id,
        "kind": kind,
        "ratio": round(float(ratio), 4),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }


class AgentState(BaseFlowState, total=False):
    """Agent 引擎的 state schema，继承 BaseFlowState。

    字段必须 msgpack 可序列化（LangGraph checkpointer 限制）：

    - messages      — LangChain BaseMessage 列表（**merge_messages 去重合并**，
                      修复原 operator.add 每 superstep 翻倍的 bug）
    - iterations    — 已执行步数（最后一次返回值覆盖）
    - system_prompt — SKILL.md 拼装出的系统提示（最后一次覆盖）
    - risk_metrics  — 风控指标（由 calc_risk_stub 写入，router.py 消费）
    - risk_profile  — 风控画像（generate_risk_profile 写入；calc_risk_stub 测试场景下也注入，router.py 消费）
    - task_status   — 任务状态（"done" 触发 finish）
    - task_goal     — 任务目标描述（取自 input_data.task）
    - current_step  — LLM 本轮意图的完整工具批次（list[str]，用于 fingerprint）
    - last_tool     — 本轮实际执行的 tool 列表（list[str]，用于 fingerprint）
    - tool_args     — 本轮实际执行的 tool 参数列表（list[dict]，用于 fingerprint）
    - errors        — 工具执行错误信息（list[str]，operator.add 累积）
    - output_data   — 标准化产出（给 MCP / OpenCode 状态回流消费）
    - artifacts     — 产物路径列表（operator.add 累积）
    - gate          — OpenCode 可展示的 HumanGate payload
    - context_rebuilt — P0-8 §4.4: >90% 重建后 messages 已被压缩为摘要时置 true
    - checkpoint_snapshot — P0-8 §4.4: 快照/重建事件列表（operator.add 累积）

    **不放进 state 的字段**（通过闭包注入）：
    - tools         — ToolDef 列表（Pydantic 模型，msgpack 不支持）
     注：``seen_states`` 由 ``make_post_tool_check`` 闭包内部维护，
     不进 state、不进实例，确保跨任务隔离（Day 3 评审修复）。
    """

    task_id: str
    session_id: str | None
    actor_id: str | None
    role: str | None
    workspace_id: str | None
    workspace_path: str | None
    github_subject: str | None
    resource_scopes: list[str]
    # P0-8 §4.4: messages 改用自定义 reducer（去重合并），修复 truncate/摘要
    # 节点把整个列表再 add 一遍导致的翻倍 bug（原 Annotated[..., operator.add]）。
    messages: Annotated[list[Any], merge_messages]
    iterations: int
    system_prompt: str
    risk_metrics: dict | None
    risk_profile: dict | None
    task_status: str | None
    status: str | None
    task_goal: str
    current_step: list[str] | None
    last_tool: list[str] | None
    tool_args: list[dict[str, Any]] | None
    errors: list[str] | None
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add] | None
    gate: dict[str, Any] | None
    # P0-8 §4.4: >90% 重建后置 true（新字段，最后一个返回值覆盖，无 reducer）
    context_rebuilt: bool
    # P0-8 §4.4: checkpoint_snapshot 事件列表（operator.add 累积，快照/重建各一条，
    # 随 state/trace 流出；前端按未知类型降级渲染）
    checkpoint_snapshot: Annotated[list[dict[str, Any]], operator.add]
    # P-07 strict reuse: a successful capability catalog lookup is a
    # server-side prerequisite before any non-read tool may run.
    capability_catalog_checked: bool
    # R2 token budget：budget_tokens 限额（None=不限）；budget_used 每次该 agent
    # LLM 调用累计消耗（usage 真值优先，取不到 _estimate_tokens 近似）；
    # budget_grants 记录人审 approve 后的追加额（节点整体返回，最后值覆盖）。
    budget_tokens: int | None
    budget_used: int
    budget_grants: list[int] | None
    # P-01/F-06: Blackboard sqlite 路径透传（dataset 工具读同一 bb 文件；
    # None → backing 默认路径 .quantcode/blackboard.db）。
    _blackboard_db_path: str | None
    # P-10 方案先行：当前方案阶段（None=未启动工作流 / "draft" / "frozen" /
    # "superseded"）。draft 态由 make_tool_node/make_llm_node 做阶段限流
    # （tool 过滤，非 interrupt——不新增 HumanGate 触发点）。
    solution_phase: str | None
    # P-10 方案先行：当前 run 激活的 SolutionDoc id（solution 工具输出经
    # _extract_state_fields 注入；tool_node 据此从 Blackboard 回源 solution_phase）。
    solution_id: str | None
    # P-10 服务端任务分类：L2/L3 在 phase=None 时也必须维持方案限流。
    solution_required: bool


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

        # P-10 方案先行（组 allowlist 过滤段）：draft 态只把「方案类工具 +
        # 只读工具」白名单暴露给模型（可见性收窄）。phase 缺省/非 draft →
        # 原样返回，行为与改动前一致。
        visible_tools = filter_tools_for_phase(
            tools,
            state.get("solution_phase"),
            solution_required=bool(state.get("solution_required")),
        )

        # 调 LLM（带 tool 列表）
        response: AIMessage = model(history, tools=visible_tools)

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

        # R2 token budget：每次 LLM 返回后累计消耗。
        # usage_metadata 真值优先（input+output tokens）；
        # ponytail: 取不到时退回 _estimate_tokens(全文) 近似，升级路径=provider 统一回报 usage
        usage = getattr(response, "usage_metadata", None) or {}
        if usage.get("total_tokens"):
            spent = int(usage["total_tokens"])
        else:
            prompt_chars = len(state.get("system_prompt") or "")
            for m in history:
                content = getattr(m, "content", "")
                prompt_chars += len(content if isinstance(content, str) else repr(content))
            response_chars = len(str(getattr(response, "content", "") or ""))
            spent = (prompt_chars + response_chars) // 4
        updates["budget_used"] = int(state.get("budget_used") or 0) + spent

        return updates

    return llm_node


def make_tool_node(
    registry: ToolRegistry,
    allowed_tool_ids: set[str] | frozenset[str] | None = None,
) -> Callable[[AgentState], dict]:
    """构造 ``tool_node``：执行最近一个 AIMessage 里的所有 tool_calls。

    tool 返回的是非 str 数据且是 dict 时，会尝试注入 state：
    - ``calc_risk_stub`` → ``risk_metrics``
    - ``task_done`` / ``mark_complete`` → ``task_status="done"``
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
            "session_id": state.get("session_id") or state.get("thread_id", ""),
            "actor_id": state.get("actor_id"),
            "role": state.get("role"),
            "workspace_id": state.get("workspace_id"),
            "workspace_path": state.get("workspace_path"),
            "github_subject": state.get("github_subject"),
            "resource_scopes": state.get("resource_scopes") or [],
        }
        # Blackboard 路径透传（P-01/F-06：dataset 工具读同一 bb 文件；
        # engine 默认 None → backing 默认路径 .quantcode/blackboard.db）。
        if state.get("_blackboard_db_path"):
            ctx["blackboard_db_path"] = state["_blackboard_db_path"]
        ctx["_memory"] = state.get("_memory")  # MemoryService 透传

        # P-10 方案先行（组 allowlist 过滤段）：workflow 激活（state 已带
        # solution_phase/solution_id）时从 Blackboard 回源当前 SolutionDoc 状态
        # ——/solution 面板（AG-G）跨进程冻结后 run 侧同步解除限流。未激活 →
        # phase=None，不读 db，既有 run 行为与开销不变。
        solution_phase = sync_phase_from_blackboard(
            state.get("solution_phase"),
            state.get("solution_id"),
            ctx.get("blackboard_db_path"),
        )

        results: list[ToolMessage] = []
        # 收集需要注入 state 的字段
        state_updates: dict[str, Any] = {}

        # P-10：把回源后的阶段写回 state，供 make_llm_node 的可见工具面过滤
        # （draft 态只暴露方案类 + 只读工具；frozen 后解除）。
        if solution_phase is not None:
            state_updates["solution_phase"] = solution_phase

        executed_tools: list[str] = []
        executed_args: list[dict[str, Any]] = []
        tool_errors: list[str] = []

        try:
            from runner.config_loader import load_yaml
            strict_reuse = bool(load_yaml("capabilities", strict=True).get("strict_reuse", False))
        except Exception:
            # A malformed capability config must not silently disable the
            # safety gate.  Treat it as enabled and return a visible tool
            # error until the configuration is repaired.
            strict_reuse = True

        for call in tool_calls:
            c = _to_tool_call_dict(call)
            try:
                if allowed_tool_ids is not None and c["name"] not in allowed_tool_ids:
                    content = (
                        f"Tool '{c['name']}' failed: it is not available for the "
                        "authenticated session."
                    )
                    results.append(
                        ToolMessage(content=content, tool_call_id=c["id"], name=c["name"])
                    )
                    executed_tools.append(c["name"])
                    executed_args.append(c["args"])
                    continue
                # P-07 hard boundary: prompt text is not sufficient evidence
                # of reuse.  In strict mode the agent must successfully query
                # the maintained capability catalog before invoking a
                # write/side-effect tool.  Read-only and solution workflow
                # tools remain available so the agent can satisfy the gate.
                from runner.solution_workflow import SOLUTION_TOOLS, is_readonly_tool
                if (
                    strict_reuse
                    and c["name"] not in SOLUTION_TOOLS
                    and not is_readonly_tool(c["name"])
                    and not state.get("capability_catalog_checked")
                ):
                    content = (
                        "Strict reuse is enabled: call list_capabilities successfully "
                        "before invoking non-read tools."
                    )
                    results.append(
                        ToolMessage(content=content, tool_call_id=c["id"], name=c["name"])
                    )
                    executed_tools.append(c["name"])
                    executed_args.append(c["args"])
                    continue
                # P-10 阶段限流（tool 过滤，非 interrupt——不新增 HumanGate 触发点）：
                # draft 态写类工具 deny，返回可纠偏的 ToolMessage；不进
                # permission/enforce 链（避免无谓 interrupt 冒泡）。
                # phase 非 draft（None/frozen/superseded）时恒放行，行为不变。
                if not tool_allowed_in_phase(
                    c["name"],
                    solution_phase,
                    solution_required=bool(state.get("solution_required")),
                ):
                    content = tool_denied_message(c["name"])
                    results.append(
                        ToolMessage(content=content, tool_call_id=c["id"], name=c["name"])
                    )
                    executed_tools.append(c["name"])
                    executed_args.append(c["args"])
                    continue
                # G4-A1 权限钩子：yaml 配 deny → PermissionError 转 tool_result
                # error；ask 未批准 → LangGraph interrupt 冒泡（等 HumanGate
                # resume）。未配置 permission 的 tool → allow，行为与改动前一致。
                from runner.permission_engine import enforce

                enforce(c["name"], ctx.get("group", ""), ctx)
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
    """
    updates: dict[str, Any] = {}

    if tool_name == "calc_risk_stub":
        # 注入 risk_metrics
        updates["risk_metrics"] = output
        # 测试场景支持：自动构造简单的 risk_profile 供结果展示。
        updates["risk_profile"] = {
            "strategy_id": output.get("strategy_id"),
            "as_of_date": output.get("as_of_date"),
            "max_drawdown": output.get("max_drawdown"),
            "tail_risk_var_99": output.get("tail_risk_var_99"),
            "volatility": output.get("volatility"),
        }
    elif tool_name == "calc_risk":
        # 生产场景：只注入 risk_metrics，risk_profile 由 generate_risk_profile 生成
        updates["risk_metrics"] = output

    if tool_name == "generate_risk_profile":
        # 生产场景：generate_risk_profile 返回 {"risk_profile": {...}}。
        profile = output.get("risk_profile")
        if isinstance(profile, dict):
            updates["risk_profile"] = profile

    if tool_name in ("mark_task_done", "task_done", "mark_complete"):
        updates["task_status"] = "done"

    if tool_name == "write_blackboard":
        updates["task_status"] = "done"

    if tool_name == "list_capabilities" and isinstance(output.get("capabilities"), list):
        updates["capability_catalog_checked"] = True

    # Day 4 控制平面状态回流：标准字段透传给 AgentState/MCP。
    if "output_data" in output and isinstance(output.get("output_data"), dict):
        updates["output_data"] = output["output_data"]

    # P-10 方案先行：solution 工具输出携带 solution_id/solution_phase → 注入
    # state（激活工作流）；后续每轮 tool_node 据此从 Blackboard 回源阶段，
    # draft 态对写类工具做 deny（tool 过滤，非 interrupt）。
    if output.get("solution_id"):
        updates["solution_id"] = output["solution_id"]
        if output.get("solution_phase"):
            updates["solution_phase"] = output["solution_phase"]

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
        budget = budget_total(state)
        if budget is not None and int(state.get("budget_used") or 0) > budget:
            return "budget"
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
    - 死循环 → "end"
    - max_iterations → "max_iter"
    - risk threshold → no gate
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
            "risk_profile": state.get("risk_profile"),
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
            # Runtime loop failure; stop without a human gate.
            return "loop_stop"
        elif result.decision == RouteDecision.ABORT_MAX_ITERATIONS:
            # Write RLHF entry for max_iter abort before routing to END
            _log_abort_rlhf(state, "abort_max_iterations")
            return "max_iter"
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
    rlhf_collector: Any,  # 未使用（None 即可）；占位签名保持既有测试兼容
    fingerprint_history: list[str] | None = None,
) -> Callable[[AgentState], dict]:
    """构造 ``rlhf_collect_node``。

    Day 5 RLHF 重构：改用 ``make_rlhf_entry()`` + ``log_rlhf_entry()`` 新格式。
    重算路由决策获取 system_decision，记录 risk_features / risk_score / label。
    rlhf_collector 形参未使用（传 None 即可），保留只为既有测试签名兼容。

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
    budget_tokens: int | None = None,
    blackboard_db_path: str | None = None,
    solution_required: bool = False,
    actor_id: str | None = None,
    role: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    workspace_path: str | None = None,
    github_subject: str | None = None,
    resource_scopes: list[str] | None = None,
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
        task_id=str((input_data or {}).get("task_id") or thread_id),
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
        budget_tokens=budget_tokens,
        budget_used=0,
        _blackboard_db_path=str(blackboard_db_path) if blackboard_db_path else None,
        solution_required=solution_required,
        actor_id=actor_id,
        role=role,
        session_id=session_id,
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        github_subject=github_subject,
        resource_scopes=resource_scopes or [],
        # seen_states 由 make_post_tool_check 闭包持有，不入 state
    )



# ---------------------------------------------------------------------------
# Token 估算 + truncate 节点 — Day 4 尹一帆（Day 5 从 main 移植回 PR25 引擎）
# P0-8：messages reducer 已换成 merge_messages（去重合并），truncate 返回整个
# 列表不再翻倍；同 id 同内容重发会被去重，改写 content 的同 id 项按 id 覆盖。
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
        except (KeyError, ValueError, OSError):
            # 未知 model 名 → 退化为 cl100k_base
            try:
                enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text))
            except (KeyError, ValueError, OSError):
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
    截断后的 messages 列表作为整体返回;messages 通道用 ``merge_messages`` reducer,
    同 id 消息按 id 覆盖旧项（改写 content 的截断生效）,未裁掉的项去重后不翻倍。

    Args:
        max_tokens: 总 messages 的 token 预算;超此值才裁剪
        model_name: tiktoken model 名(默认 gpt-4)
        head_preserve: 头 N 条消息不裁(系统提示 + 早期对话)
        tail_preserve: 尾 M 条消息不裁(最近上下文)

    注意:本节点只改写中段消息的 content,不动消息条数;同 id 覆盖由 reducer 处理,
    不会再出现"累积翻倍"。
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
        # 标记已截断,让后续节点知道;_ReplaceMessages 让 reducer 整体替换,不翻倍
        return {
            "messages": _ReplaceMessages(truncated),
            "_truncated": True,
        }

    return truncate_node


# ---------------------------------------------------------------------------
# P0-8 §4.4: context >90% 重建节点 — 把旧 messages 压缩成一条 summary 消息
# ---------------------------------------------------------------------------


class _ReplaceMessages(list):
    """list 标记子类：节点用它返回 messages 表示"整体替换"（truncate / 摘要重建）。

    merge_messages 看到 _ReplaceMessages 直接取值，不再去重合并——
    这是 truncate 裁剪和 rebuild 压缩能真正生效、且不翻倍的关键。
    """


def _summarize_rebuild(
    reason: str,
    messages: list,
    task_goal: str | None,
) -> str:
    """生成重建摘要：工具名序列 + 最近 user input + 保留说明。"""
    tool_seq: list[str] = []
    recent_user_input = ""
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                c = _to_tool_call_dict(tc)
                if c.get("name"):
                    tool_seq.append(c["name"])
        elif isinstance(m, HumanMessage):
            recent_user_input = str(getattr(m, "content", "") or "")[:300]
    lines = [
        f"[context rebuilt: {reason}]",
        f"工具调用序列: {tool_seq}" if tool_seq else "无工具调用记录",
    ]
    if recent_user_input:
        lines.append(f"最近用户输入: {recent_user_input}")
    if task_goal:
        lines.append(f"任务目标: {str(task_goal)[:200]}")
    lines.append("早期对话与工具输出已压缩；最后 2 条消息保留原文。请基于以上摘要继续任务。")
    return "\n".join(lines)


def budget_total(state: dict[str, Any]) -> int | None:
    """当前有效预算 = budget_tokens + 已追加额之和（无 budget_tokens → None=不限）。"""
    base = state.get("budget_tokens")
    if not base:
        return None
    grants = state.get("budget_grants") or []
    return int(base) + sum(int(g) for g in grants)


def make_budget_check_node(
    *,
    grant_tokens: int = 50000,
) -> Callable[[AgentState], dict]:
    """构造 budget_gate 节点：超预算返回 stopped_budget，不创建 HumanGate。

    - 未超限 → 继续正常路由。
    - 超限 → 返回 stopped_budget 和 output_data.budget_exhausted=True，正常收尾。
    """
    def budget_gate_node(state: AgentState) -> dict:
        used = int(state.get("budget_used") or 0)
        budget = budget_total(state)
        over_by = used - int(budget or 0)
        if budget is None or over_by <= 0:
            return {}

        if budget is not None and over_by > 0:
            output = dict(state.get("output_data") or {})
            output["budget_exhausted"] = True
            output["budget_used"] = used
            output["budget_tokens"] = int(budget)
            return {
                "status": "stopped_budget",
                "task_status": "done",
                "budget_used": used,
                "budget_tokens": int(budget),
                "output_data": output,
            }
        return {}

    return budget_gate_node


def budget_warning_event(
    *,
    budget_used: int,
    budget_tokens: int,
    over_by: int,
) -> dict[str, Any]:
    """构造 budget_warning 事件（execution_trace 扩展类型，前端降级渲染）。"""
    return {
        "event_type": "budget_warning",
        "budget_used": budget_used,
        "budget_tokens": budget_tokens,
        "over_by": over_by,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }


def make_rebuild_context_node() -> Callable[[AgentState], dict]:
    """构造 ``rebuild_context`` 节点：context 用量 > CONTEXT_REBUILD_RATIO 时被路由触发。

    把旧 messages（除内联 SystemMessage 外）压缩成一条 AIMessage 摘要
    （工具名序列 + 最近 user input），保留最后 2 条消息原文；
    state 置 ``context_rebuilt=True``，并返回 ``checkpoint_snapshot``
    事件（kind=rebuild）随 state/trace 流出。
    """
    def rebuild_context_node(state: AgentState) -> dict:
        messages = list(state.get("messages") or [])
        summary = _summarize_rebuild(
            "over 90% context limit",
            messages,
            state.get("task_goal") or (state.get("input_data") or {}).get("task", ""),
        )
        # system 消息原样保留（节点机制里 system_prompt 不入 messages，这里兜底）
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        tail = [m for m in messages if not isinstance(m, SystemMessage)][-2:]
        rebuilt: list[Any] = list(system_msgs)
        rebuilt.append(AIMessage(content=summary))
        rebuilt.extend(tail)
        return {
            "messages": _ReplaceMessages(rebuilt),
            "context_rebuilt": True,
            "checkpoint_snapshot": [
                make_checkpoint_event(
                    thread_id=state.get("thread_id", ""),
                    ratio=context_usage_ratio(state),
                    kind="rebuild",
                )
            ],
        }

    return rebuild_context_node



__all__ = [
    "AgentState",
    "merge_messages",
    "CONTEXT_SNAPSHOT_RATIO",
    "CONTEXT_REBUILD_RATIO",
    "estimate_context_chars",
    "context_usage_ratio",
    "make_checkpoint_event",
    "make_rebuild_context_node",
    "budget_total",
    "budget_warning_event",
    "make_budget_check_node",
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

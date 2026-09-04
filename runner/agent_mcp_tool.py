"""run_agent tool — MCP ↔ AgentRunner 桥接 — Day 4 俞高磊 + Day 7 HumanGate。

把这个 tool 注册进 ToolRegistry 后，MCP server 即可通过 ``tools/call(name="run_agent")``
调起完整的 AgentRunner ReAct 循环。OpenCode compose agent 看到这个 tool 后可以
自主决定何时触发量化 agent。

Day 7 新增 start/resume 两阶段协议：
- start mode：无 decision → 启动 AgentRunner，若遇到 HumanGate interrupt 则返回
  ``waiting_for_human`` 状态给 OpenCode 展示。
- resume mode：传 thread_id + decision → 用 ``Command(resume=...)`` 恢复已暂停的
  checkpoint。
- MCP 跑始终使用稳定 checkpoint DB (``.quantcode/opencode-checkpoints.db``)。

设计要点：
- ``_meta=True`` 标记确保 run_agent 不出现在普通 tool list（LLM 不应递归调用自己的 runner）。
- 依赖通过 ctx 注入（group / _model），避免硬编码环境变量。
- 输入 schema：task（start 时必传）+ thread_id + decision + max_iterations。
- 输出结构化：status / iterations / thread_id / final_message / tool_calls / execution_trace。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.registry import ToolDef, registry


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# R2 token budget 默认值（RunAgentArgs.max_total_tokens 未传时用）
DEFAULT_TOKEN_BUDGET = 200_000

# These orchestration tools belong to the outer OpenCode controller. They may
# be listed by MCP for that controller, but must never be handed to the inner
# QuantCode Agent or a child Agent, which would allow recursive runs or
# cross-task registry control.
_INNER_AGENT_EXCLUDED_TOOLS = frozenset(
    {"run_agent", "spawn_subagent", "check_subagent", "kill_subagent", "list_subagents", "check_tool_stream"}
)


def _inner_agent_tool_ids(tool_ids: set[str] | frozenset[str] | None):
    if tool_ids is None:
        return None
    return frozenset(tool_ids) - _INNER_AGENT_EXCLUDED_TOOLS


def _resolve_budget(max_total_tokens: int | None) -> int | None:
    """args 显式值 > env QUANTCODE_TOKEN_BUDGET > DEFAULT_TOKEN_BUDGET。"""
    if max_total_tokens is not None:
        # 0 is the established test/CLI sentinel for disabling the optional
        # budget gate; positive values remain hard limits.
        return max_total_tokens if max_total_tokens > 0 else None
    try:
        return int(os.environ.get("QUANTCODE_TOKEN_BUDGET", DEFAULT_TOKEN_BUDGET))
    except ValueError:
        return DEFAULT_TOKEN_BUDGET


# ---------------------------------------------------------------------------
# Input Schema (Day 7: start/resume 两阶段)
# ---------------------------------------------------------------------------


class RunAgentArgs(BaseModel):
    """run_agent 的输入参数 — Day 7 新增 thread_id / decision 支持两阶段调用。"""

    task: str | None = Field(
        default=None,
        description="任务描述文本（自然语言）。start 模式时必传。",
    )
    group: str | None = Field(
        default=None,
        description="可选：要运行的组（model/risk/factor/fundamental/options/strategy）。"
        "不传则从 QUANTCODE_GROUP 环境变量读取。",
    )
    skill_name: str | None = Field(
        default=None,
        description="可选：要加载的 skill 名（如 'model-pr-submit'）。不传则用默认 system prompt。",
    )
    max_iterations: int = Field(
        default=50,
        description="最大 ReAct 迭代次数，超限后强制停止（默认 50）。",
    )
    # R2 token budget：None → env QUANTCODE_TOKEN_BUDGET（缺省 200000）
    max_total_tokens: int | None = Field(
        default=None,
        description="可选：本次 run 的总 token 预算。超限时返回 STOPPED_BUDGET（不创建 HumanGate）。"
        "不传则读环境变量 QUANTCODE_TOKEN_BUDGET（缺省 200000）。",
    )

    # ── Day 7: resume 协议字段 ──
    thread_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
        description="resume 模式时必传：要恢复的已暂停 thread_id。"
        "start 模式可选：指定则用该值作为 thread_id。",
    )
    decision: Literal["approve", "reject", "proceed", "abort"] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Human gate 决策。有值 → resume 模式；无值 → start 模式。"
        "推荐使用 approve/reject。proceed/abort 仅用于兼容内部路径。",
    )

    # ── attach_stream：start run 执行轨迹旁落到 JSONL 通道 ──
    attach_stream: bool = Field(
        default=False,
        description="start 模式可选：True 时把 execution_trace 事件逐条 append 到 "
        ".quantcode/streams/<thread_id>.jsonl，控制器用 check_tool_stream 按游标"
        "中途增量读取。False（默认）不建文件，行为不变。",
    )


# ── 任务→子 skill 路由（Day 5 修复） ──
# 当 skill_name 是通用编排器（如 "model"）时，根据 task 关键词
# 自动分派到执行器子 skill，避免内部 agent 加载编排器 prompt
# → 只输出"你应该调 run_agent"而不实际执行。
ORCHESTRATOR_DISPATCH: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "model": [
        (("pr", "submit", "pull request", "handoff"), "model-pr-submit"),
        (("lit review", "literature review", "paper", "survey", "arxiv"), "model-lit-review"),
    ],
    "risk": [
        (("pr", "risk", "verdict", "review"), "risk-ci"),
    ],
    "factor": [
        (("factor", "evaluation", "ic", "ir"), "factor-evaluation"),
    ],
    "options": [
        (("options", "vol", "greeks", "backtest", "gc", "期权"), "options-compose"),
    ],
    "strategy": [
        (("strategy", "signal", "组合", "动量", "pb-roe", "backtest"), "strategy-compose"),
    ],
    "fundamental": [
        (("估值", "研报", "公司", "pit", "dcf", "分析", "fundamental"), "fundamental-compose"),
    ],
}


def _resolve_skill_name(skill_name: str | None, group: str, task: str) -> str | None:
    """若 skill_name 是通用编排器，尝试匹配执行器子 skill。"""
    if skill_name is None or group not in ORCHESTRATOR_DISPATCH:
        return skill_name
    task_lower = task.lower()
    for patterns, sub_skill in ORCHESTRATOR_DISPATCH[group]:
        if any(p in task_lower for p in patterns):
            return sub_skill
    return skill_name


# ---------------------------------------------------------------------------
# MCP checkpoint DB（Day 7: 稳定持久化，确保 start→resume 可恢复同一线程）
# ---------------------------------------------------------------------------

def _mcp_checkpoint_db() -> Path:
    """返回 MCP run_agent 专用的稳定 checkpoint DB 路径。

    统一复用 runner.langgraph_base.CHECKPOINTS_DB，MCP run 与 OpenCode CLI
    共用同一 DB，这样通过 CLI 暂停的 gate 也可以通过 MCP resume。
    （原 .quantcode/opencode-checkpoints.db 硬编码已删除；旧 db 不迁移。）
    """
    from runner.langgraph_base import CHECKPOINTS_DB

    CHECKPOINTS_DB.parent.mkdir(parents=True, exist_ok=True)
    return CHECKPOINTS_DB


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _run_agent_execute(args: RunAgentArgs, ctx: dict) -> dict[str, Any]:
    """执行 run_agent — start 或 resume。

    **start mode** (``decision is None``):
    - 要求 ``task`` 存在。
    - 创建带 checkpoint DB 的 AgentRunner，跑 stream()。
    - 若返回 state 含 ``__interrupt__`` → 提取后返回 ``waiting_for_human``。
    - 否则返回正常 completed/stopped 结果。

    **resume mode** (``decision`` 有值):
    - 要求 ``thread_id`` 存在。
    - 调用 ``AgentRunner.resume(thread_id=..., decision=...)``。
    - 返回 completed/rejected 结果。
    """
    # 认证 session 决定 group。请求参数只能重复声明同一组，不能覆盖
    # roster 返回的 session group。没有认证 group 时，显式 group 只作为
    # 本地开发降级路径，正式 MCP 会话由 mcp_server 在调用前 fail-closed。
    session_group = str((ctx or {}).get("group") or "").strip()
    requested_group = str(args.group or "").strip()
    if session_group and requested_group and requested_group != session_group:
        return {
            "status": "error",
            "error": (
                f"group mismatch: authenticated session is '{session_group}', "
                f"request asked for '{requested_group}'"
            ),
        }
    if not session_group:
        # Production requests must carry a server-issued Session Context.
        # Explicit group values are accepted only for local development tests.
        dev_mode = bool((ctx or {}).get("_development_mode")) or (
            os.environ.get("QUANTCODE_ENV", "").strip().lower() in {"dev", "development", "test"}
            and os.environ.get("QUANTCODE_ALLOW_UNAUTH", "").strip() == "1"
        )
        if not dev_mode:
            return {"status": "error", "error": "AUTHENTICATION_REQUIRED: Session Context is required"}
    group = session_group or requested_group
    if not group:
        return {"status": "error", "error": "AUTHENTICATION_REQUIRED: Session Context is required (QUANTCODE_GROUP is only allowed in explicit development mode)"}

    # start mode 缺 task 是请求错误，与 model 是否配置无关 —— 必须在 model gate 前校验，
    # 否则无 API key 环境下会误报 "No LLM model configured"（PR25 遗留的环境依赖）。
    if args.decision is None and not args.task:
        return {
            "status": "error",
            "error": "task is required for start mode (no decision provided).",
        }

    model = ctx.get("_model")
    if model is None:
        try:
            from quantcode.mcp_server import _get_model
            model = _get_model()
        except Exception:
            model = None
    if model is None:
        return {
            "status": "error",
            "error": (
                "No LLM model configured. Set QUANTCODE_API_KEY "
                "(and optionally QUANTCODE_MODEL_PROVIDER / QUANTCODE_MODEL_NAME) "
                "environment variable."
            ),
        }

    from runner.agent_engine import AgentRunner

    checkpoint_db = _mcp_checkpoint_db()
    resolved_skill = _resolve_skill_name(args.skill_name, group, args.task or "")

    # ── resume mode ──
    if args.decision is not None:
        return _resume_mode(
            args, group, model, checkpoint_db, resolved_skill,
            allowed_tool_ids=_inner_agent_tool_ids(ctx.get("_allowed_tool_ids")),
            actor_id=ctx.get("actor_id"), role=ctx.get("role"),
            session_id=ctx.get("session_id"),
            workspace_id=ctx.get("workspace_id"),
            workspace_path=ctx.get("workspace_path"),
            github_subject=ctx.get("github_subject"),
            resource_scopes=ctx.get("resource_scopes"),
        )

    # ── start mode ──
    return _start_mode(
        args, group, model, checkpoint_db, resolved_skill,
        allowed_tool_ids=ctx.get("_allowed_tool_ids"),
        actor_id=ctx.get("actor_id"), role=ctx.get("role"),
        session_id=ctx.get("session_id"),
        workspace_id=ctx.get("workspace_id"),
        workspace_path=ctx.get("workspace_path"),
        github_subject=ctx.get("github_subject"),
        resource_scopes=ctx.get("resource_scopes"),
    )

def _read_pending_risk_reviews(db_path: Path | None = None) -> int:
    """risk 组启动时读取 PROJECT scope 的 ``shared.pending_risk_reviews`` 队列条数。

    P0-2 修复：session/key 一律走 :mod:`runner.blackboard_keys` 归一层
    （与 write_blackboard / trigger_risk_flow 写读两端一致），不再引用
    不存在的 ``tools.blackboard.blackboard_service``；读取失败记 warning
    并返回 0，不阻塞 risk 组正常流程。
    """
    try:
        import sqlite3

        from runner.blackboard import BlackboardService
        from runner.blackboard_keys import KEY_PENDING_RISK_REVIEWS, PROJECT_SESSION_ID
        from schemas import BlackboardScope, GroupName

        service = BlackboardService(
            db_path=db_path,
            session_id=PROJECT_SESSION_ID,
            requester_group=GroupName.RISK,
        )
        queue_entry = service.get_entry(
            BlackboardScope.PROJECT,
            None,
            KEY_PENDING_RISK_REVIEWS,
            requester_group=GroupName.RISK,
        )
        if queue_entry and isinstance(queue_entry.value, dict):
            reviews = queue_entry.value.get("reviews", {})
            if isinstance(reviews, dict):
                return len(reviews)
    except (ImportError, sqlite3.Error, ValueError) as exc:
        # 不再静默吞掉——记 warning 便于排障。
        logger.warning("risk 组读取 pending_risk_reviews 失败（忽略）: %s", exc)
    return 0


def _start_mode(
    args: RunAgentArgs,
    group: str,
    model: Any,
    checkpoint_db: Path,
    resolved_skill: str | None,
    *,
    allowed_tool_ids: set[str] | frozenset[str] | None = None,
    actor_id: str | None = None,
    role: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    workspace_path: str | None = None,
    github_subject: str | None = None,
    resource_scopes: list[str] | None = None,
) -> dict[str, Any]:
    """start 模式：启动 AgentRunner，捕获 interrupt → waiting_for_human。"""
    from runner.agent_engine import AgentRunner
    from runner.langgraph_base import make_thread_id
    import uuid

    if not args.task:
        return {
            "status": "error",
            "error": "task is required for start mode (no decision provided).",
        }
    from runner.task_classifier import classify_task

    classification = classify_task(args.task).model_dump(mode="json")

    # ★ 提前生成 thread_id：interrupt() 抛异常时 final_state 不可达，
    # 但异常恢复需要知道 thread_id 才能构建 config。
    thread_id = args.thread_id or (
        f"{make_thread_id(group, 'mcp_compose')}-{uuid.uuid4().hex[:8]}"
    )

    # Day 5 fix: risk 组启动时读取 pending_risk_reviews，接收 model→risk 跨组流触发
    task = args.task
    if group == "risk":
        review_count = _read_pending_risk_reviews()
        if review_count:
            task = f"{task}\n\n[Pending risk reviews from model group: {review_count} items]"

    runner = AgentRunner(
        group=group,
        model=model,
        max_iterations=args.max_iterations,
        checkpoint_db=checkpoint_db,
        budget_tokens=_resolve_budget(args.max_total_tokens),
        allowed_tool_ids=_inner_agent_tool_ids(allowed_tool_ids),
        actor_id=actor_id,
        role=role,
        session_id=session_id,
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        github_subject=github_subject,
        resource_scopes=resource_scopes,
    )

    # ── attach_stream：start run 事件通道（旁路，emit 失败静默不影响主流程） ──
    def _stream_call() -> dict[str, Any]:
        """包装 runner.stream()：拿到全量 trace 后逐条 emit 到通道。

        # ponytail: emit 在 stream() 全量返回后补齐（终态结构 100% 不变）；
        # 真·逐步中途可读需在 AgentRunner.stream() 循环内挂钩子（改 engine），
        # 窗口秒级，需要更低延迟时再升级。
        """
        from runner import stream_channel

        channel = stream_channel.get_or_open(thread_id)
        final_state = runner.stream(
            task=task,
            skill_name=resolved_skill,
            flow_name="mcp_compose",
            thread_id=thread_id,
            solution_required=bool(classification.get("solution_required")),
        )
        for ev in (final_state.get("execution_trace") or []):
            if isinstance(ev, dict):
                channel.emit(ev)
        return final_state

    final_state: dict[str, Any] = {}
    try:
        # 优先用 stream()；回退到 run()
        if hasattr(runner, "stream"):
            if args.attach_stream:
                final_state = _stream_call()
            else:
                final_state = runner.stream(
                    task=task,
                    skill_name=resolved_skill,
                    flow_name="mcp_compose",
                    thread_id=thread_id,
                    solution_required=bool(classification.get("solution_required")),
                )
        else:
            final_state = runner.run(
                task=task,
                skill_name=resolved_skill,
                flow_name="mcp_compose",
                thread_id=thread_id,
                solution_required=bool(classification.get("solution_required")),
            )

        # ── 检查是否有 pending HumanGate interrupt ──
        from runner.human_gate import extract_interrupt_payload, format_waiting_for_human

        interrupt = extract_interrupt_payload(final_state)
        if interrupt is not None:
            waiting = format_waiting_for_human(
                thread_id=final_state.get("thread_id", thread_id),
                interrupt_payload=interrupt,
            )
            waiting["task_classification"] = classification
            return waiting

        result = _format_result(final_state, group, actor_id=actor_id, role=role)
        result["task_classification"] = classification
        return result

    except Exception as e:
        # interrupt() 会在 LangGraph 内部抛 GraphInterrupt 异常；
        # 此时 final_state 未赋值，但我们已有提前生成的 thread_id。
        import traceback
        from runner.human_gate import extract_interrupt_payload, format_waiting_for_human

        tb = traceback.format_exc()

        # LangGraph 0.2+: GraphInterrupt
        if "GraphInterrupt" in tb or "Interrupt" in tb:
            # 通过 get_state() 获取 checkpoint 中的 interrupt
            try:
                app = runner.build(
                    skill_name=resolved_skill,
                    system_prompt="",
                )
                config = {"configurable": {"thread_id": thread_id}}
                snapshot = app.get_state(config)
                if snapshot and snapshot.interrupts:
                    interrupt_val = extract_interrupt_payload(
                        {"__interrupt__": list(snapshot.interrupts)}
                    )
                    if interrupt_val:
                        waiting = format_waiting_for_human(
                            thread_id=thread_id,
                            interrupt_payload=interrupt_val,
                        )
                        waiting["task_classification"] = classification
                        return waiting
            except Exception:
                pass

        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb[-500:],
        }


def _resume_mode(
    args: RunAgentArgs,
    group: str,
    model: Any,
    checkpoint_db: Path,
    resolved_skill: str | None,
    *,
    allowed_tool_ids: set[str] | frozenset[str] | None = None,
    actor_id: str | None = None,
    role: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    workspace_path: str | None = None,
    github_subject: str | None = None,
    resource_scopes: list[str] | None = None,
) -> dict[str, Any]:
    """resume 模式：用 Command(resume=...) 恢复已暂停的 gate。"""
    from runner.agent_engine import AgentRunner
    from runner.human_gate import normalize_external_decision

    if not args.thread_id:
        return {
            "status": "error",
            "error": "thread_id is required for resume mode.",
        }

    if role not in {"approver", "admin"}:
        return {
            "status": "error",
            "error": "PERMISSION_DENIED: only an approver or admin may resume a HumanGate",
        }

    decision = args.decision or "reject"
    normalized = normalize_external_decision(decision)

    runner = AgentRunner(
        group=group,
        model=model,
        max_iterations=args.max_iterations,
        checkpoint_db=checkpoint_db,
        budget_tokens=_resolve_budget(args.max_total_tokens),
        allowed_tool_ids=_inner_agent_tool_ids(allowed_tool_ids),
        actor_id=actor_id,
        role=role,
        session_id=session_id,
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        github_subject=github_subject,
        resource_scopes=resource_scopes,
    )

    try:
        # 优先用 stream() + resume() 组合：无 stream 则用 resume()
        # AgentRunner.resume() 内部用 Command(resume=...) 恢复中断点
        final_state = runner.resume(
            thread_id=args.thread_id,
            decision=decision,
            skill_name=resolved_skill,
            flow_name="mcp_compose",
        )

        result = _format_result(final_state, group, actor_id=actor_id, role=role)

        # 将 human_decision 注入结果
        from runner.human_gate import parse_resume_decision
        result["human_decision"] = normalized
        result["thread_id"] = args.thread_id

        # 检查状态：如果 human_gate routing 判为 abort → 显示 rejected
        human_result = final_state.get("human_review_result", "")
        if human_result == "abort":
            result["status"] = "rejected"
            result["final_message"] = final_state.get("output_data", {}).get(
                "message", "Rejected by human gate."
            ) if isinstance(final_state.get("output_data"), dict) else (
                "Rejected by human gate."
            )

        return result

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-500:],
        }


def _format_result(
    state: dict,
    group: str,
    *,
    actor_id: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """从 AgentState 提取结构化输出。"""
    messages = state.get("messages", [])

    # 提取 tool_calls：遍历 AIMessage.tool_calls + 对应的 ToolMessage
    tool_calls: list[dict] = []
    for i, msg in enumerate(messages):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                tc_result = ""
                # 找对应的 ToolMessage
                for j in range(i + 1, len(messages)):
                    tm = messages[j]
                    tm_tc_id = (
                        getattr(tm, "tool_call_id", "")
                        if hasattr(tm, "tool_call_id")
                        else ""
                    )
                    if tm_tc_id == tc_id:
                        tc_result = str(getattr(tm, "content", ""))[:500]
                        break
                tool_calls.append({
                    "tool": tc_name,
                    "args": tc_args,
                    "result": tc_result,
                })

    # 最后一条 AI 消息
    last_msg = messages[-1] if messages else None
    final_text = ""
    if last_msg is not None:
        final_text = str(getattr(last_msg, "content", "")) if hasattr(last_msg, "content") else ""

    result: dict[str, Any] = {
        "status": "completed" if state.get("task_status") == "done" else "stopped",
        "iterations": state.get("iterations", 0),
        "thread_id": state.get("thread_id", ""),
        "task_id": state.get("task_id") or state.get("thread_id", ""),
        "group": group,
        "actor_id": state.get("actor_id") or actor_id,
        "role": state.get("role") or role,
        "session_id": state.get("session_id"),
        "final_message": final_text,
        "tool_calls": tool_calls,
    }

    # Attach execution_trace if present（Task 3 stream() 产出）
    if "execution_trace" in state:
        result["execution_trace"] = state["execution_trace"]

    # Attach risk_metrics if present
    if state.get("risk_metrics"):
        result["risk_metrics"] = state["risk_metrics"]

    # Day4 状态回流标准字段
    if state.get("output_data") is not None:
        result["output_data"] = state.get("output_data")
    if state.get("artifacts") is not None:
        result["artifacts"] = list(state.get("artifacts") or [])
    if state.get("gate") is not None:
        result["gate"] = state.get("gate")
    if state.get("errors") is not None:
        result["errors"] = list(state.get("errors") or [])

    return result


# ---------------------------------------------------------------------------
# ToolDef
# ---------------------------------------------------------------------------

run_agent_tool = ToolDef(
    id="run_agent",
    description=(
        "Execute a full QuantCode agent run with the ReAct loop. "
        "The agent autonomously reasons about the task, calls the appropriate "
        "quant tools (read_pr, calc_risk, write_blackboard, etc.), and produces "
        "structured results. Use this for complex multi-step workflows that "
        "require tool orchestration across groups.\n\n"
        "Two-phase protocol: first call without decision to start a task. "
        "If the result status is 'waiting_for_human', display the gate info "
        "to the user, collect approve/reject, then call again with the same "
        "thread_id and decision='approve' or 'reject'."
    ),
    schema=RunAgentArgs,
    execute=_run_agent_execute,
)

# ★ 标记为 meta tool，MCP server 的 list_tools() 会过滤掉它，
# 避免 LLM 在 ReAct 循环中递归调用 run_agent。
run_agent_tool._meta = True  # type: ignore[attr-defined]

# 注册到全局 registry
registry.register(run_agent_tool)

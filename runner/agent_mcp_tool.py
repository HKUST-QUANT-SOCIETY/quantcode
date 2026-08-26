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

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.registry import ToolDef, registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    # ── Day 7: resume 协议字段 ──
    thread_id: str | None = Field(
        default=None,
        description="resume 模式时必传：要恢复的已暂停 thread_id。"
        "start 模式可选：指定则用该值作为 thread_id。",
    )
    decision: Literal["approve", "reject", "proceed", "abort"] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Human gate 决策。有值 → resume 模式；无值 → start 模式。"
        "推荐使用 approve/reject。proceed/abort 仅用于兼容内部路径。",
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
        (("pr", "risk", "gate", "review"), "risk-gate"),
    ],
    "factor": [
        (("factor", "autoeval", "ic", "ir"), "factor-autoeval"),
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
    if skill_name is None:
        # Risk no longer defaults to the legacy fixed RiskProfile pipeline.
        return "risk-gate" if group == "risk" else None
    if group not in ORCHESTRATOR_DISPATCH:
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

    MCP run 与 OpenCode CLI 共用同一 DB，这样通过 CLI 暂停的 gate
    也可以通过 MCP resume。
    """
    db_path = PROJECT_ROOT / ".quantcode" / "opencode-checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


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
    # 优先级：args.group > ctx["group"]（环境变量）> 报错
    group = args.group or ctx.get("group") or ""
    if not group:
        return {
            "status": "error",
            "error": (
                "No group configured. Either pass 'group' in run_agent args, or set "
                "QUANTCODE_GROUP environment variable "
                "(e.g., QUANTCODE_GROUP=model) in opencode.local.jsonc or your shell."
            ),
        }

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
                "(or STEPFUN_PLAN_API_KEY, or ANTHROPIC_API_KEY) "
                "environment variable."
            ),
        }

    from runner.agent_engine import AgentRunner

    checkpoint_db = _mcp_checkpoint_db()
    resolved_skill = _resolve_skill_name(args.skill_name, group, args.task or "")

    # ── resume mode ──
    if args.decision is not None:
        return _resume_mode(args, group, model, checkpoint_db, resolved_skill)

    # ── start mode ──
    return _start_mode(args, group, model, checkpoint_db, resolved_skill)


def _start_mode(
    args: RunAgentArgs,
    group: str,
    model: Any,
    checkpoint_db: Path,
    resolved_skill: str | None,
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

    # ★ 提前生成 thread_id：interrupt() 抛异常时 final_state 不可达，
    # 但异常恢复需要知道 thread_id 才能构建 config。
    thread_id = args.thread_id or (
        f"{make_thread_id(group, 'mcp_compose')}-{uuid.uuid4().hex[:8]}"
    )

    # Read the shared model -> risk queue and give the parent only bounded,
    # redacted handoff context. The child Scout will create its own evidence.
    task = args.task
    risk_parent_context_items: list[dict[str, Any]] = []
    risk_parent_context_required = False
    if group == "risk":
        try:
            from runner.blackboard import BlackboardService, DEFAULT_SESSION_ID
            from schemas import BlackboardScope, GroupName

            service = BlackboardService(
                session_id=DEFAULT_SESSION_ID,
                requester_group=GroupName.RISK,
            )
            queue_entry = service.get_entry(
                BlackboardScope.PROJECT,
                None,
                "shared.pending_risk_reviews",
                requester_group=GroupName.RISK,
            )
            if queue_entry and isinstance(queue_entry.value, dict):
                reviews = queue_entry.value.get("reviews", {})
                if reviews:
                    for review_id, review in sorted(reviews.items()):
                        if not isinstance(review, dict):
                            continue
                        if review.get("status", "pending") != "pending":
                            continue
                        risk_parent_context_required = True
                        context_ref = (
                            "handoff-"
                            + hashlib.sha256(str(review_id).encode("utf-8")).hexdigest()[:16]
                        )
                        content = review.get("context_snapshot")
                        if not isinstance(content, (dict, list, str, int, float, bool)):
                            content = {
                                key: review.get(key)
                                for key in ("model_name", "pr_url", "commit_sha", "from_group")
                            }
                        risk_parent_context_items.append(
                            {
                                "context_ref": context_ref,
                                "kind": "model-risk-handoff",
                                "locator": (
                                    "blackboard:project:shared.pending_risk_reviews:"
                                    f"{review_id}"
                                ),
                                "summary": (
                                    f"Redacted {review.get('from_group', 'upstream')} handoff "
                                    f"for {review.get('model_name') or review_id}"
                                )[:2048],
                                "content": content,
                                "redacted": True,
                            }
                        )
                    # Do not put even redacted handoff descriptors in the
                    # parent prompt: the child receives them through its
                    # in-memory, tool-gated session. This avoids prompt
                    # injection and accidental provider egress at the parent.
                    task = (
                        f"{task}\n\n[RISK_HANDOFF_AVAILABLE] "
                        f"{len(risk_parent_context_items)} bounded item(s); "
                        "spawn the Risk Scout child now."
                    )
        except Exception:
            pass  # 读取失败不影响正常流程

    runner = AgentRunner(
        group=group,
        model=model,
        max_iterations=args.max_iterations,
        checkpoint_db=checkpoint_db,
        allowed_tool_ids=(
            {"spawn_risk_scout"}
            if group == "risk" and resolved_skill in {"risk", "risk-gate"}
            else None
        ),
        tool_context={
            "risk_parent_context_items": risk_parent_context_items,
            "risk_parent_context_required": risk_parent_context_required,
            "risk_project_id": "quantcode",
            "risk_event_id": (
                "handoff-"
                + hashlib.sha256(
                    "|".join(
                        item["context_ref"] for item in risk_parent_context_items
                    ).encode("utf-8")
                ).hexdigest()[:16]
                if risk_parent_context_items
                else "runtime-" + hashlib.sha256(task.encode("utf-8")).hexdigest()[:16]
            ),
            "risk_parent_task_id": "T1",
            "risk_child_task_id": "T1.1",
        },
    )

    final_state: dict[str, Any] = {}
    try:
        # 优先用 stream()；回退到 run()
        if hasattr(runner, "stream"):
            final_state = runner.stream(
                task=task,
                skill_name=resolved_skill,
                flow_name="mcp_compose",
                thread_id=thread_id,
            )
        else:
            final_state = runner.run(
                task=task,
                skill_name=resolved_skill,
                flow_name="mcp_compose",
                thread_id=thread_id,
            )

        # ── 检查是否有 pending HumanGate interrupt ──
        from runner.human_gate import extract_interrupt_payload, format_waiting_for_human

        interrupt = extract_interrupt_payload(final_state)
        if interrupt is not None:
            return format_waiting_for_human(
                thread_id=final_state.get("thread_id", thread_id),
                interrupt_payload=interrupt,
            )

        return _format_result(final_state, group)

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
                        return format_waiting_for_human(
                            thread_id=thread_id,
                            interrupt_payload=interrupt_val,
                        )
            except Exception:
                pass

        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb[-500:],
        }


def _start_risk_gate_mode(
    args: RunAgentArgs,
    checkpoint_db: Path,
) -> dict[str, Any]:
    """
    DEPRECATED: risk-gate 专用 start 模式，已弃用。统一走 AgentRunner。

    历史遗留：此函数为 Day4 demo 稳定性临时加的特判路径，走确定性
    build_risk_agent pipeline 而非 ReAct。现已统一至 AgentRunner ReAct 路径。
    保留此函数仅为兼容性，实际已不再调用（agent_mcp_tool.py 已移除调用点）。
    """
    if not args.task:
        return {
            "status": "error",
            "error": "task is required for start mode (no decision provided).",
        }

    from runner.langgraph_base import make_thread_id
    import uuid
    thread_id = args.thread_id or (
        f"{make_thread_id('risk', 'mcp_compose')}-{uuid.uuid4().hex[:8]}"
    )

    # 将自然语言 task 映射为 risk:gate 的最小 input_data。
    task_lower = args.task.lower()
    scenario = "high_risk" if any(k in task_lower for k in (
        "high_risk", "high risk", "var99", "var 99", "max_drawdown", "position limit", "position_limit"
    )) else "normal"

    from scripts.run_risk_gate_tool import _fixture_model_spec
    from runner.risk_agent import build_risk_agent
    from runner.human_gate import extract_interrupt_payload, format_waiting_for_human

    app = build_risk_agent(checkpoint_db=checkpoint_db)
    input_data = {
        "scenario": scenario,
        "model_spec": _fixture_model_spec(),
        "pr_number": "303",
        "head_sha": f"mcp-{thread_id}",
        "pr_url": f"https://github.com/hkust-quant-society/quantcode/pull/303",
        "artifacts_root": str(PROJECT_ROOT / "artifacts" / "risk" / "opencode" / scenario),
        "dedupe_db_path": str(PROJECT_ROOT / ".quantcode" / "opencode-dedupe.sqlite"),
    }
    init_state = {
        "group": "risk",
        "flow_name": "risk:gate",
        "thread_id": thread_id,
        "input_data": input_data,
        "output_data": None,
        "artifacts": [],
        "errors": [],
    }
    final_state = app.invoke(init_state, config={"configurable": {"thread_id": thread_id}})
    interrupt = extract_interrupt_payload(final_state)
    if interrupt is not None:
        waiting = format_waiting_for_human(thread_id=thread_id, interrupt_payload=interrupt)
        waiting["execution_trace"] = [
            {
                "schema_version": "agent_trace.v1",
                "seq": 1,
                "type": "agent_start",
                "node": None,
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"task": args.task or ""},
            },
            {
                "schema_version": "agent_trace.v1",
                "seq": 2,
                "type": "risk_metrics",
                "node": "run_tool_pipeline",
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"metrics": final_state.get("risk_metrics", {})},
            },
            {
                "schema_version": "agent_trace.v1",
                "seq": 3,
                "type": "human_gate",
                "node": "human_review",
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"status": "waiting_for_human", "gate": waiting.get("gate", {})},
            },
        ]
        return waiting

    output = final_state.get("output_data") or {}
    return {
        "status": output.get("status", "completed"),
        "thread_id": thread_id,
        "output_data": output,
        "artifacts": final_state.get("artifacts", []),
        "risk_metrics": final_state.get("risk_metrics", {}),
        "execution_trace": [
            {
                "schema_version": "agent_trace.v1",
                "seq": 1,
                "type": "agent_start",
                "node": None,
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"task": args.task or ""},
            },
            {
                "schema_version": "agent_trace.v1",
                "seq": 2,
                "type": "risk_metrics",
                "node": "run_tool_pipeline",
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"metrics": final_state.get("risk_metrics", {})},
            },
            {
                "schema_version": "agent_trace.v1",
                "seq": 3,
                "type": "output_data",
                "node": "finalize_output",
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"output_data": output},
            },
            {
                "schema_version": "agent_trace.v1",
                "seq": 4,
                "type": "agent_end",
                "node": None,
                "thread_id": thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"status": output.get("status", "completed")},
            },
        ],
    }


def _resume_risk_gate_mode(
    args: RunAgentArgs,
    checkpoint_db: Path,
) -> dict[str, Any]:
    """
    DEPRECATED: risk-gate 专用 resume 模式，已弃用。统一走 AgentRunner。

    历史遗留：此函数为 Day4 demo 稳定性临时加的特判路径。
    现已统一至 _resume_mode 的 AgentRunner 路径。
    保留此函数仅为兼容性，实际已不再调用（agent_mcp_tool.py 已移除调用点）。
    """
    if not args.thread_id:
        return {
            "status": "error",
            "error": "thread_id is required for resume mode.",
        }

    from runner.human_gate import normalize_external_decision
    from runner.risk_agent import build_risk_agent, resume_risk_gate

    decision = normalize_external_decision(args.decision or "reject")
    risk_decision = "approve" if decision == "approve" else "reject"
    app = build_risk_agent(checkpoint_db=checkpoint_db)
    final_state = resume_risk_gate(app, args.thread_id, risk_decision)
    output = final_state.get("output_data") or {}
    status = output.get("status", "completed")
    artifacts = final_state.get("artifacts", [])
    return {
        "status": status,
        "thread_id": args.thread_id,
        "human_decision": decision,
        "output_data": output,
        "artifacts": artifacts,
        "risk_metrics": final_state.get("risk_metrics", {}),
        "execution_trace": [
            {
                "schema_version": "agent_trace.v1",
                "seq": 1,
                "type": "human_gate",
                "node": "human_review",
                "thread_id": args.thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"human_decision": decision, "status": status},
            },
            {
                "schema_version": "agent_trace.v1",
                "seq": 2,
                "type": "output_data",
                "node": "finalize_output",
                "thread_id": args.thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"output_data": output},
            },
            *[
                {
                    "schema_version": "agent_trace.v1",
                    "seq": i + 3,
                    "type": "artifact",
                    "node": "write_pr_comment",
                    "thread_id": args.thread_id,
                    "group": "risk",
                    "flow_name": "risk:gate",
                    "iteration": 0,
                    "data": {"path": str(path)},
                }
                for i, path in enumerate(artifacts)
            ],
            {
                "schema_version": "agent_trace.v1",
                "seq": len(artifacts) + 3,
                "type": "agent_end",
                "node": None,
                "thread_id": args.thread_id,
                "group": "risk",
                "flow_name": "risk:gate",
                "iteration": 0,
                "data": {"status": status},
            },
        ],
    }


def _resume_mode(
    args: RunAgentArgs,
    group: str,
    model: Any,
    checkpoint_db: Path,
    resolved_skill: str | None,
) -> dict[str, Any]:
    """resume 模式：用 Command(resume=...) 恢复已暂停的 gate。"""
    from runner.agent_engine import AgentRunner
    from runner.human_gate import normalize_external_decision

    if not args.thread_id:
        return {
            "status": "error",
            "error": "thread_id is required for resume mode.",
        }

    decision = args.decision or "reject"
    normalized = normalize_external_decision(decision)

    runner = AgentRunner(
        group=group,
        model=model,
        max_iterations=args.max_iterations,
        checkpoint_db=checkpoint_db,
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

        result = _format_result(final_state, group)

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


def _format_result(state: dict, group: str) -> dict[str, Any]:
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

    task_status = state.get("task_status")
    status = {"done": "completed", "abandoned": "error"}.get(
        task_status, "stopped"
    )
    result: dict[str, Any] = {
        "status": status,
        "iterations": state.get("iterations", 0),
        "thread_id": state.get("thread_id", ""),
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

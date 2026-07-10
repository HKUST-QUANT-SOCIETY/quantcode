"""AgentRunner — 自搭 StateGraph ReAct Agent 的入口 — Day 3 尹一帆 + Day 5 RLHF 重构。

按计划 §一研究点 1 决策：**自搭 StateGraph**，不绕道 create_react_agent。

AgentRunner 负责：
1. 加载 skill（业务 + 元）拼装 system prompt
2. 按组过滤 tool（load_group_config + get_tools_for_group）
3. 构造节点函数 + 条件边
4. 编译 StateGraph + 接 SqliteSaver
5. 提供 ``run()`` / ``stream()`` / ``resume()`` 三个执行入口

设计要点：
- 依赖全部通过构造器注入（registry / model；rlhf_collector 已弃用，仅保留兼容）
  便于测试时 mock，也便于 Day 4 替换 LLM / DB。
- 不修改 ``compose_executor.py``：ReAct 是动态创建的，绕过它的固定 DAG 注册。
- 复用 ``runner.langgraph_base`` 的 ``get_checkpointer`` + ``make_thread_id``。
- Day 5: RLHF 格式重构 — 删 reward_key/REWARD，改为 system_decision + human_decision
  + gate_purpose + risk_score + label。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from runner.agent_nodes import (
    AgentState,
    init_agent_state,
    make_llm_node,
    make_rlhf_collect_node,
    make_routing_edge,
    make_tool_node,
    make_tool_routing_edge,
    make_truncate_node,
)
from runner.langgraph_base import get_checkpointer, make_thread_id
from runner.routing.guards import MAX_ITERATIONS
from tools.loop_detector import LoopDetector
from tools.registry import ToolRegistry, registry as default_registry
from tools.skills.loader import load_skill

# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------


class AgentRunner:
    """ReAct Agent 引擎入口（自搭 StateGraph）。

    用法::

        runner = AgentRunner(group="model")
        app = runner.build(skill_name="model-pr-submit", meta_skills=["tdd"])
        result = app.invoke(init_state, config={"configurable": {"thread_id": tid}})

    或者一步到位::

        result = AgentRunner(group="model").run(
            task="Read PR #42",
            skill_name="model-pr-submit",
        )
    """

    def __init__(
        self,
        group: str,
        *,
        model: Callable[..., AIMessage] | None = None,
        registry: ToolRegistry | None = None,
        rlhf_collector: Any | None = None,  # Deprecated since Day 5 RLHF refactor (rlhf_collector.py deleted). Parameter retained for API compatibility, value is ignored.
        loop_detector: LoopDetector | None = None,
        max_iterations: int = MAX_ITERATIONS,
        checkpoint_db: str | Path | None = None,
        truncate_tokens: int | None = None,
    ) -> None:
        self.group = group
        self.model = model  # 可选：build 时若不传则用占位（mock 用）
        self.registry = registry or default_registry
        self.rlhf_collector = rlhf_collector
        self.loop_detector = loop_detector or LoopDetector()
        self.max_iterations = max_iterations
        self.checkpoint_db = Path(checkpoint_db) if checkpoint_db else None
        # Day 5: truncate_node 从 main 移植回来（可选）。传 truncate_tokens 时，
        # 在 tool 之后挂一个 token 裁剪节点，防止长任务 context 爆。
        self.truncate_tokens = truncate_tokens

    # ----- 构造 StateGraph -----
    def build(
        self,
        *,
        skill_name: str | None = None,
        meta_skills: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> Any:
        """构造并 compile StateGraph，返回 ``CompiledStateGraph``。

        Args:
            skill_name: 主 skill 名（业务或元）。
                - 业务：配合 ``group`` 查找 ``.opencode/groups/<group>/skills/<name>/SKILL.md``
                - 元：直接在 MimoCode ``.bundle/`` 下找
                - 传 None 则只用 ``system_prompt`` 参数
            meta_skills: 附加的元 skill 列表。
            system_prompt: 直接提供 system prompt 字符串（优先级高于 skill_name）。
                如果都提供，用 ``system_prompt`` 覆盖。

        Returns:
            编译后的 StateGraph app，调 ``.invoke()`` / ``.stream()``。
        """
        # Day 3 评审修复：每次 build 重置 LoopDetector 窗口
        self.loop_detector.reset()

        # Day 4 俞高磊：给 system_prompt 追加强制 tool-call 指令
        # 解决 StepFun 长 system_prompt 下不调 tool 的问题
        _tc_instruction = (
            "\n\n## RULES\n"
            "- Call tools. Do not describe them.\n"
        )

        # 1. 准备 system prompt
        if system_prompt is None and skill_name is not None:
            # 默认按业务 skill 加载；skill_name 不带冒号 → 业务；带冒号 → 元
            if ":" in skill_name or self._is_meta_skill(skill_name):
                system_prompt = load_skill(skill_name, meta_skills=meta_skills)
            else:
                system_prompt = load_skill(
                    skill_name, group=self.group, meta_skills=meta_skills
                )
        elif system_prompt is None:
            system_prompt = ""

        # ★ 追加 tool-call 指令（解决 StepFun 只输出文字不调 tool 的问题）
        system_prompt = system_prompt + _tc_instruction

        # 2. 按组过滤 tool
        tools = self.registry.get_tools_for_group(self.group)

        # 3. 构造节点工厂
        if self.model is None:
            raise ValueError(
                "AgentRunner.build(): 必须提供 model（生产用 LLM，测试用 MockLLM）"
            )
        llm_node = make_llm_node(self.model, tools=tools)  # tools 通过闭包注入
        tool_node = make_tool_node(self.registry)
        # Day 5 RLHF 重构：rlhf_collect_node 始终添加到图中（不再依赖 rlhf_collector 参数）。
        # rlhf_collector 仅用于向后兼容双写（可选）。
        # fingerprint_history 在 build 作用域内声明，tool_routing_edge 和
        # rlhf_collect_node 共享同一列表引用，确保路由重算与原始决策一致。
        fingerprint_history: list[str] = []
        rlhf_node = make_rlhf_collect_node(self.rlhf_collector, fingerprint_history)
        # Day 3 评审后：llm 用轻量路由（有无 tool_calls），tool 用 route_next_step
        llm_routing = make_routing_edge(max_iterations=self.max_iterations)
        tool_routing = make_tool_routing_edge(
            max_iterations=self.max_iterations,
            fingerprint_history=fingerprint_history,
        )
        # Day 5：可选 truncate 节点（从 main 移植回来）。tool 之后、路由之前裁剪 token。
        truncate_node = (
            make_truncate_node(max_tokens=self.truncate_tokens)
            if self.truncate_tokens
            else None
        )

        # human_gate 节点：区分 risk gate 和 loop gate — Day 4 俞高磊接入杨欣琳 HumanGate 接口
        # Day 7: risk gate 在此节点直接调 interrupt()（不再依赖 LLM 主动调
        # request_human_review tool），确保 routing → human_gate → interrupt 的
        # 链路对 LLM 行为 100% 可靠。
        def _human_gate_node(state: AgentState) -> dict:
            """Gate 节点——risk gate 在此调用 LangGraph interrupt() 暂停。

            - risk gate：若 human_review_result 尚不存在，立即 interrupt()。
              恢复时通过 Command(resume={"decision": ...}) 注入决定。
            - loop gate：测试阶段始终放行（proceed）。
            - 已有结果：直接标准化 proceed/abort。
            """
            human_result = state.get("human_review_result")
            gate_purpose = state.get("_gate_purpose", "")

            if human_result == "proceed":
                return {
                    "_gate_purpose": gate_purpose or "risk",
                    "human_review_result": "proceed",
                }
            elif human_result == "abort":
                return {
                    "_gate_purpose": gate_purpose or "risk",
                    "human_review_result": "abort",
                }
            elif gate_purpose == "loop":
                # Loop gate: 测试阶段始终放行
                return {
                    "_gate_purpose": "loop",
                    "human_review_result": "proceed",
                }
            else:
                # ★ risk gate 但还没有 human_review_result：
                # 在此节点直接调 interrupt()，等外部 Command(resume=...)
                from runner.human_gate import (
                    build_interrupt_payload,
                    make_gate_id,
                    parse_resume_decision,
                )
                from langgraph.types import interrupt as lg_interrupt

                thread_id = state.get("thread_id", "")
                risk_metrics = state.get("risk_metrics") or {}
                reasons = list(risk_metrics.get("breached_limits", []))
                if not reasons:
                    # 从阈值对比推算原因
                    from tools.risk_stub import VAR_99_LIMIT, MAX_DRAWDOWN_LIMIT, POSITION_LIMIT_LIMIT
                    var_val = risk_metrics.get("tail_risk_var_99", 0)
                    md_val = risk_metrics.get("max_drawdown", 0)
                    pos_val = risk_metrics.get("position_limit", 0)
                    if var_val and var_val > VAR_99_LIMIT:
                        reasons.append(f"tail_risk_var_99 ({var_val} > {VAR_99_LIMIT})")
                    if md_val and md_val > MAX_DRAWDOWN_LIMIT:
                        reasons.append(f"max_drawdown ({md_val} > {MAX_DRAWDOWN_LIMIT})")
                    if pos_val and pos_val > POSITION_LIMIT_LIMIT:
                        reasons.append(f"position_limit ({pos_val} > {POSITION_LIMIT_LIMIT})")

                gate_id = make_gate_id(thread_id)
                payload = build_interrupt_payload(
                    gate_id=gate_id,
                    risk_profile=risk_metrics,
                    reasons=reasons,
                    message=f"⏸️ HumanGate: risk thresholds exceeded ({', '.join(reasons[:3])})",
                )

                # ★ 真暂停：等待外部 Command(resume={"decision": ...})
                resume_value = lg_interrupt(payload)

                decision_raw = parse_resume_decision(resume_value) or "abort"
                # 归一化外部 approve/reject → 内部 proceed/abort
                from runner.human_gate import normalize_external_decision
                external = normalize_external_decision(decision_raw)
                internal = "proceed" if external == "approve" else "abort"

                return {
                    "_gate_purpose": "risk",
                    "human_review_result": internal,
                }

        def _human_gate_routing(state: AgentState) -> str:
            # 从 state 读人工审核结果（已归一化为 proceed/abort）
            decision = state.get("human_review_result", "abort")
            gate_purpose = state.get("_gate_purpose", "risk")

            # ── Day 5 RLHF 记录 ──
            # NOTE：这里写入的是 human_gate **路由决策点** 的记录
            # （system/human 共同决定 proceed/abort）。
            # rlhf_collect_node 随后写的另一条记录是 **每步执行决策点**
            # （system_decision=continue + human_decision=""）。
            # 两个不同的决策点，分开记录是正确的——前者反思 gate
            # 准确性（label=0/1），后者记录 step-level 行为轨迹。
            from runner.routing.rlhf_logger import make_rlhf_entry, log_rlhf_entry
            from runner.routing.fingerprint import compute_state_fingerprint

            system_decision = "human_gate" if gate_purpose == "risk" else "abort_loop"
            entry = make_rlhf_entry(
                thread_id=state.get("thread_id", ""),
                group=state.get("group", ""),
                state_fingerprint=compute_state_fingerprint(dict(state)),
                system_decision=system_decision,
                human_decision=decision,           # "proceed" or "abort" (already normalized)
                risk_features=state.get("risk_metrics"),
                checkpoint_id=state.get("thread_id", ""),
                iteration=state.get("iterations", 0),
            )
            log_rlhf_entry(entry)

            if decision == "proceed":
                return "continue"
            return "end"

        # 4. 构造 StateGraph
        workflow = StateGraph(AgentState)

        workflow.add_node("llm", llm_node)
        workflow.add_node("tool", tool_node)
        workflow.add_node("human_gate", _human_gate_node)
        workflow.add_node("rlhf", rlhf_node)   # Day 5: rlhf 节点始终存在
        if truncate_node is not None:
            workflow.add_node("truncate", truncate_node)

        workflow.set_entry_point("llm")
        # llm 之后：有 tool_calls → tool，否则 → end
        workflow.add_conditional_edges(
            "llm",
            llm_routing,
            {"continue": "tool", "end": END},
        )
        # Day 5：有 truncate 时 tool → truncate → 路由；否则 tool 直接路由。
        # 路由源（tool_routing 条件边挂在这个节点上）
        routing_source = "tool"
        if truncate_node is not None:
            workflow.add_edge("tool", "truncate")
            routing_source = "truncate"
        # tool（或 truncate）之后：route_next_step 综合判断
        workflow.add_conditional_edges(
            routing_source,
            tool_routing,
            {
                "rlhf": "rlhf",
                "max_iter": END,
                "end": END,
                "human_gate": "human_gate",
            },
        )
        # human_gate 之后：条件边
        workflow.add_conditional_edges(
            "human_gate",
            _human_gate_routing,
            {
                "continue": "rlhf",       # 审核通过 → rlhf node → 回工作流
                "end": END,                # 审核拒绝 → 终止
            },
        )
        workflow.add_edge("rlhf", "llm")

        # 5. compile + 接 checkpointer
        # Day 4 俞高磊：interrupt 通过 request_human_review tool 内的
        # langgraph.types.interrupt() 实现（杨欣琳 HumanGate 接口），
        # 不需要全局 interrupt_before——避免 loop gate 也被误暂停。
        checkpointer = get_checkpointer(self.checkpoint_db) if self.checkpoint_db else None
        app = workflow.compile(checkpointer=checkpointer)
        return app

    # ----- 执行入口 -----
    def run(
        self,
        task: str,
        *,
        skill_name: str | None = None,
        meta_skills: list[str] | None = None,
        system_prompt: str | None = None,
        thread_id: str | None = None,
        flow_name: str = "agent",
        resume: bool = False,
    ) -> dict:
        """跑一个任务，返回最终 state。

        Args:
            task: 用户任务文本（放进 HumanMessage）。
            skill_name: 主 skill 名。
            meta_skills: 附加元 skill 列表。
            system_prompt: 直接覆盖 skill 的 system prompt。
            thread_id: 显式指定则用固定值；默认自动生成（**含 uuid 后缀**，全局唯一）。
            flow_name: 用于 make_thread_id。
            resume: True 则从已有 thread_id 的 checkpoint 恢复。

        Returns:
            最终 state dict（含 messages / iterations / output_data 等）。

        Note:
            默认 thread_id 生成时会追加 ``uuid.uuid4().hex[:8]`` 作为后缀，
            确保同秒同 group+flow_name 不碰撞（避免 checkpoint 互相覆盖）。
            如果 caller 显式传 ``thread_id``，则原样使用，不追加。
        """
        thread_id = self._generate_thread_id(thread_id, flow_name)
        if system_prompt is None and skill_name is not None:
            if ":" in skill_name or self._is_meta_skill(skill_name):
                system_prompt = load_skill(skill_name, meta_skills=meta_skills)
            else:
                system_prompt = load_skill(
                    skill_name, group=self.group, meta_skills=meta_skills
                )
        elif system_prompt is None:
            system_prompt = ""

        app = self.build(
            skill_name=skill_name,
            meta_skills=meta_skills,
            system_prompt=system_prompt,
        )

        config = {"configurable": {"thread_id": thread_id}}

        if resume:
            # 恢复模式：init_state 为 None，LangGraph 从 checkpoint 加载
            final = app.invoke(None, config=config)
        else:
            init_state = init_agent_state(
                group=self.group,
                flow_name=flow_name,
                thread_id=thread_id,
                system_prompt=system_prompt,
                tools=[],  # tools 已通过闭包注入 llm_node，不入 state
                input_data={"task": task},
            )
            final = app.invoke(init_state, config=config)

        return final

    # ----- stream()：带 execution_trace 的执行入口 -----
    def stream(
        self,
        task: str,
        *,
        skill_name: str | None = None,
        meta_skills: list[str] | None = None,
        system_prompt: str | None = None,
        thread_id: str | None = None,
        flow_name: str = "agent",
        resume: bool = False,
    ) -> dict:
        """Run agent via LangGraph app.stream() and return node-level execution_trace.

        Day4 control-plane requirement: use the graph streaming API, not post-hoc
        message reconstruction, so OpenCode/MCP can consume node-level status:
        thought/tool_call/tool_result/risk_metrics/human_gate/output_data/artifact.
        """
        thread_id = self._generate_thread_id(thread_id, flow_name)
        meta_skills = meta_skills or []

        # Resolve prompt once to avoid double-loading skill.
        if system_prompt is None and skill_name is not None:
            if ":" in skill_name or self._is_meta_skill(skill_name):
                system_prompt = load_skill(skill_name, meta_skills=meta_skills)
            else:
                system_prompt = load_skill(skill_name, group=self.group, meta_skills=meta_skills)
        elif system_prompt is None:
            system_prompt = ""

        trace: list[dict] = []
        seq = 0

        def emit(event_type: str, *, node: str | None = None, iteration: int | None = None, data: dict | None = None) -> None:
            nonlocal seq
            seq += 1
            trace.append({
                "schema_version": "agent_trace.v1",
                "seq": seq,
                "type": event_type,
                "node": node,
                "thread_id": thread_id,
                "group": self.group,
                "flow_name": flow_name,
                "iteration": iteration,
                "data": data or {},
            })

        emit("agent_start", data={"task": task})
        if skill_name:
            emit("skill_loaded", data={
                "skill_name": skill_name,
                "summary": system_prompt[:500],
            })

        app = self.build(
            skill_name=skill_name,
            meta_skills=meta_skills,
            system_prompt=system_prompt,
        )
        config = {"configurable": {"thread_id": thread_id}}

        if resume:
            init_state: dict | None = None
        else:
            init_state = init_agent_state(
                group=self.group,
                flow_name=flow_name,
                thread_id=thread_id,
                system_prompt=system_prompt,
                tools=[],
                input_data={"task": task},
            )

        final_state: dict[str, Any] = {}

        try:
            # LangGraph returns chunks like {"llm": {...}}, {"tool": {...}},
            # {"__interrupt__": (...)} in this installed version.
            for chunk in app.stream(init_state, config=config):
                if not isinstance(chunk, dict):
                    continue
                # Pending interrupt chunk.
                if "__interrupt__" in chunk:
                    from runner.human_gate import extract_interrupt_payload, format_waiting_for_human
                    interrupt_payload = extract_interrupt_payload(chunk)
                    if interrupt_payload:
                        waiting = format_waiting_for_human(
                            thread_id=thread_id,
                            interrupt_payload=interrupt_payload,
                        )
                        emit("human_gate", node="human_gate", data={
                            "status": "waiting_for_human",
                            "gate": waiting.get("gate", {}),
                        })
                        final_state.update(waiting)
                        final_state["__interrupt__"] = chunk.get("__interrupt__")
                    continue

                for node_name, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    final_state.update(update)
                    iteration = update.get("iterations") or final_state.get("iterations")
                    emit("node_update", node=node_name, iteration=iteration, data={
                        "keys": sorted(update.keys()),
                    })
                    self._append_trace_from_update(
                        update,
                        trace_emit=emit,
                        node_name=node_name,
                        iteration=iteration,
                    )
        except Exception as exc:
            emit("error", data={"error": f"{type(exc).__name__}: {exc}"})
            raise

        # If checkpointing is enabled, recover full final state from app.get_state()
        # because stream(update) chunks only contain per-node deltas.
        try:
            snapshot = app.get_state(config)
            values = getattr(snapshot, "values", None)
            if isinstance(values, dict):
                final_state.update(values)
        except Exception:
            pass

        # If an interrupt exists in recovered state, surface it consistently.
        from runner.human_gate import extract_interrupt_payload, format_waiting_for_human
        interrupt_payload = extract_interrupt_payload(final_state)
        if interrupt_payload:
            waiting = format_waiting_for_human(
                thread_id=thread_id,
                interrupt_payload=interrupt_payload,
            )
            final_state.update(waiting)
            # Avoid duplicate if chunk already emitted it.
            if not any(e["type"] == "human_gate" and e["data"].get("status") == "waiting_for_human" for e in trace):
                emit("human_gate", node="human_gate", data={
                    "status": "waiting_for_human",
                    "gate": waiting.get("gate", {}),
                })

        status = (
            "waiting_for_human" if final_state.get("status") == "waiting_for_human"
            else "completed" if final_state.get("task_status") == "done"
            else "stopped"
        )
        emit("agent_end", data={
            "status": status,
            "iterations": final_state.get("iterations", 0),
        })

        final_state["thread_id"] = thread_id
        final_state["execution_trace"] = trace
        return final_state

    # ----- human-gate resume 入口 (Day 7 OpenCode integration) -----
    def resume(
        self,
        *,
        thread_id: str,
        decision: str,
        skill_name: str | None = None,
        meta_skills: list[str] | None = None,
        system_prompt: str | None = None,
        flow_name: str = "agent",
    ) -> dict:
        """Resume a paused AgentRunner run after a human gate interrupt.

        Uses ``Command(resume=...)`` to inject the human decision into the
        LangGraph checkpoint so the graph continues from the interrupt point.

        Args:
            thread_id: The exact thread_id of the paused run.
            decision: External decision — ``"approve"`` / ``"reject"``
                (also accepts legacy ``"proceed"`` / ``"abort"``).
                Mapped internally:
                - approve/proceed → ``{"decision": "proceed"}``
                - reject/abort    → ``{"decision": "abort"}``

        Returns:
            Final state dict after resume.
        """
        from runner.human_gate import to_react_resume_payload

        resume_payload = to_react_resume_payload(decision)

        app = self.build(
            skill_name=skill_name,
            meta_skills=meta_skills,
            system_prompt=system_prompt or "",
        )
        config = {"configurable": {"thread_id": thread_id}}
        final = app.invoke(Command(resume=resume_payload), config=config)
        return final

    @staticmethod
    def _append_trace_from_update(
        update: dict,
        *,
        trace_emit: Callable[..., None],
        node_name: str,
        iteration: int | None = None,
    ) -> None:
        """Append node-specific trace events from a LangGraph streamed update."""
        messages = update.get("messages") or []
        if not isinstance(messages, list):
            messages = [messages]

        for msg in messages:
            cls_name = type(msg).__name__
            if cls_name == "AIMessage":
                content = str(getattr(msg, "content", ""))
                if content.strip():
                    trace_emit(
                        "llm_thought",
                        node=node_name,
                        iteration=iteration,
                        data={"content": content[:1000]},
                    )
                for tc in (getattr(msg, "tool_calls", None) or []):
                    tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                    trace_emit(
                        "tool_call",
                        node=node_name,
                        iteration=iteration,
                        data={"tool": tc_name, "args": tc_args, "tool_call_id": tc_id},
                    )
            elif cls_name == "ToolMessage":
                result_text = str(getattr(msg, "content", ""))
                trace_emit(
                    "tool_result",
                    node=node_name,
                    iteration=iteration,
                    data={
                        "tool": getattr(msg, "name", ""),
                        "tool_call_id": getattr(msg, "tool_call_id", ""),
                        "result": result_text[:1000],
                        "is_error": "error" in result_text.lower() or "failed" in result_text.lower(),
                    },
                )

        if update.get("risk_metrics"):
            trace_emit("risk_metrics", node=node_name, iteration=iteration, data={
                "metrics": update["risk_metrics"],
            })

        if update.get("output_data"):
            trace_emit("output_data", node=node_name, iteration=iteration, data={
                "output_data": update["output_data"],
            })

        artifacts = update.get("artifacts") or []
        if isinstance(artifacts, str):
            artifacts = [artifacts]
        if isinstance(artifacts, list):
            for artifact in artifacts:
                trace_emit("artifact", node=node_name, iteration=iteration, data={
                    "path": str(artifact),
                })

        if update.get("gate"):
            trace_emit("human_gate", node=node_name, iteration=iteration, data={
                "gate": update["gate"],
            })

    @staticmethod
    def _extract_trace_from_messages(
        messages: list, risk_metrics: dict | None = None
    ) -> list[dict]:
        """从消息历史中后处理提取执行追踪事件。

        遍历 LangChain 消息列表（HumanMessage → AIMessage → ToolMessage），
        重建 agent 的推理步骤：用户输入 → LLM 思考 → tool 调用 → tool 结果。
        """
        trace: list[dict] = []

        for msg in messages:
            cls_name = type(msg).__name__

            if cls_name == "HumanMessage":
                content = str(getattr(msg, "content", ""))
                trace.append({
                    "type": "user_input",
                    "content": content[:500],
                })
            elif cls_name == "AIMessage":
                tool_calls = getattr(msg, "tool_calls", None) or []
                for tc in tool_calls:
                    tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    trace.append({
                        "type": "tool_call",
                        "tool": tc_name,
                        "args": tc_args,
                    })
                content = str(getattr(msg, "content", ""))
                if content.strip():
                    trace.append({
                        "type": "llm_thought",
                        "content": content[:1000],
                    })
            elif cls_name == "ToolMessage":
                result_text = str(getattr(msg, "content", ""))
                trace.append({
                    "type": "tool_result",
                    "tool": getattr(msg, "name", ""),
                    "result": result_text[:500],
                    "is_error": "error" in result_text.lower() or "failed" in result_text.lower(),
                })

        if risk_metrics:
            trace.append({
                "type": "risk_metrics",
                "metrics": (
                    dict(risk_metrics)
                    if isinstance(risk_metrics, dict)
                    else str(risk_metrics)[:500]
                ),
            })

        return trace

    # ----- 内部工具 -----
    def _generate_thread_id(self, thread_id: str | None, flow_name: str) -> str:
        """生成 thread_id：caller 显式传 → 原样返回；否则 ``make_thread_id`` + uuid 后缀。

        uuid 后缀确保同秒同 group+flow_name 不会碰撞（Day 3 review 决策 #6 修复点）。
        """
        if thread_id is not None:
            return thread_id
        base = make_thread_id(self.group, flow_name)
        return f"{base}-{uuid.uuid4().hex[:8]}"

    def _is_meta_skill(self, skill_name: str) -> bool:
        """判断 skill_name 是否是元 skill（来自 MimoCode .bundle/）。"""
        from tools.skills.loader import _find_meta_skill

        return _find_meta_skill(skill_name) is not None


__all__ = ["AgentRunner"]

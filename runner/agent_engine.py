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

from runner.agent_nodes import (
    AgentState,
    init_agent_state,
    make_llm_node,
    make_rlhf_collect_node,
    make_routing_edge,
    make_tool_node,
    make_tool_routing_edge,
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
    ) -> None:
        self.group = group
        self.model = model  # 可选：build 时若不传则用占位（mock 用）
        self.registry = registry or default_registry
        self.rlhf_collector = rlhf_collector
        self.loop_detector = loop_detector or LoopDetector()
        self.max_iterations = max_iterations
        self.checkpoint_db = Path(checkpoint_db) if checkpoint_db else None

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

        # human_gate 节点：区分 risk gate 和 loop gate
        def _human_gate_node(state: AgentState) -> dict:
            """Determine gate purpose and set human_review_result.

            Gate来源判断:
              - risk_metrics 超过阈值 → risk gate（来自 calc_risk_stub 触发 HUMAN_GATE）
              - 否则 → loop gate（ABORT_LOOP via system guard）
                测试阶段始终放行（proceed），安全网不误杀任务。

            human_review_result 值规则:
              - "proceed" → 继续执行
              - "abort" → 终止
              - 空/未知 → 保守默认为 "abort"
            """
            from runner.routing.router import _risk_exceeds_threshold

            risk = state.get("risk_metrics") or {}
            is_risk_gate = _risk_exceeds_threshold(risk) if risk else False

            human_result = state.get("human_review_result")
            if is_risk_gate:
                # Risk gate: "proceed" → proceed, anything else → abort (conservative)
                normalized = "proceed" if human_result == "proceed" else "abort"
                return {
                    "_gate_purpose": "risk",
                    "human_review_result": normalized,
                }
            else:
                # Loop gate: 测试阶段始终放行
                return {
                    "_gate_purpose": "loop",
                    "human_review_result": "proceed",
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

        workflow.set_entry_point("llm")
        # llm 之后：有 tool_calls → tool，否则 → end
        workflow.add_conditional_edges(
            "llm",
            llm_routing,
            {"continue": "tool", "end": END},
        )
        # tool 之后：route_next_step 综合判断
        workflow.add_conditional_edges(
            "tool",
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

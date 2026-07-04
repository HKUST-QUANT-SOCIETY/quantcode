"""AgentRunner — 自搭 StateGraph ReAct Agent 的入口 — Day 3 尹一帆。

按计划 §一研究点 1 决策：**自搭 StateGraph**，不绕道 create_react_agent。

AgentRunner 负责：
1. 加载 skill（业务 + 元）拼装 system prompt
2. 按组过滤 tool（load_group_config + get_tools_for_group）
3. 构造 5 个节点函数 + 2 个条件边
4. 编译 StateGraph + 接 SqliteSaver
5. 提供 ``run()`` / ``stream()`` / ``resume()`` 三个执行入口

设计要点：
- 依赖全部通过构造器注入（registry / model / rlhf_collector / loop_detector）
  便于测试时 mock，也便于 Day 4 替换 LLM / DB。
- 不修改 ``compose_executor.py``：ReAct 是动态创建的，绕过它的固定 DAG 注册。
- 复用 ``runner.langgraph_base`` 的 ``get_checkpointer`` + ``make_thread_id``。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph

from runner.agent_nodes import (
    AgentState,
    init_agent_state,
    make_llm_node,
    make_post_tool_check,
    make_rlhf_collect_node,
    make_should_continue,
    make_tool_node,
)
from runner.langgraph_base import get_checkpointer, make_thread_id
from tools.loop_detector import LoopDetector, MAX_ITERATIONS, state_fingerprint
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
        rlhf_collector: Any | None = None,
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
        # 状态指纹检测用：跨 build 调用共享（每个 build 单独 set）
        self._seen_states: set[str] = set()

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
        rlhf_node = (
            make_rlhf_collect_node(self.rlhf_collector)
            if self.rlhf_collector is not None
            else None
        )
        should_continue = make_should_continue(max_iterations=self.max_iterations)
        post_tool_check = make_post_tool_check(self.loop_detector, self._seen_states)

        # 4. 构造 StateGraph
        workflow = StateGraph(AgentState)

        workflow.add_node("llm", llm_node)
        workflow.add_node("tool", tool_node)
        if rlhf_node is not None:
            workflow.add_node("rlhf", rlhf_node)

        workflow.set_entry_point("llm")
        workflow.add_conditional_edges(
            "llm",
            should_continue,
            {"tool": "tool", "end": END, "max_iter": END},
        )
        # post_tool_check 的 rlhf 路径：有 rlhf_node 就走它，没有就直接回 llm
        rlhf_target = "rlhf" if rlhf_node is not None else "llm"
        workflow.add_conditional_edges(
            "tool",
            post_tool_check,
            {
                "rlhf": rlhf_target,
                "loop": END,
                "state_loop": END,
            },
        )
        if rlhf_node is not None:
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

    def stream(
        self,
        task: str,
        *,
        skill_name: str | None = None,
        meta_skills: list[str] | None = None,
        system_prompt: str | None = None,
        thread_id: str | None = None,
        flow_name: str = "agent",
    ) -> Iterator[dict]:
        """流式跑任务，每次返回一个 chunk。"""
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
        init_state = init_agent_state(
            group=self.group,
            flow_name=flow_name,
            thread_id=thread_id,
            system_prompt=system_prompt,
            tools=[],  # tools 已通过闭包注入 llm_node，不入 state
            input_data={"task": task},
        )
        config = {"configurable": {"thread_id": thread_id}}
        yield from app.stream(init_state, config=config)

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
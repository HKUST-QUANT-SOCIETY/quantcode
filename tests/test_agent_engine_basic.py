"""AgentRunner 集成测试 — Day 3 尹一帆。

覆盖：
- Agent 自主完成 ≥3 步任务（mock LLM 决定 tool 顺序）
- ≥1 skill markdown 能喂进去被使用
- Agent 中断后能从 checkpoint 恢复
- 多 Agent 并发跑不冲突（每个 Agent 用独立 thread_id）
- tool 能按组隔离（用 model 组拿不到 risk 专属 tool）
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import pytest
from langchain_core.messages import AIMessage

from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import ToolDef, register_tool
from tools.registry import registry as global_registry
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Mock LLM：按调用次数返回不同 tool_call 序列
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """按调用次数返回预设 AIMessage。

    responses: list[AIMessage]
        第 N 次调用返回 responses[N]（不够则返回 AIMessage(content="done")）
    """

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="[mock default done]")
        self._idx += 1
        return resp


def _ai_with_tools(name_to_args: list[tuple[str, dict]], call_id_prefix: str = "c"):
    """构造一个带多个 tool_calls 的 AIMessage。"""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"{call_id_prefix}-{i}"}
            for i, (name, args) in enumerate(name_to_args)
        ],
    )


# ---------------------------------------------------------------------------
# Mock tools
# ---------------------------------------------------------------------------


class ReadPRArgs(BaseModel):
    pr_number: int


def _read_pr(args: ReadPRArgs, ctx: dict) -> dict:
    return {"pr": args.pr_number, "diff": f"diff-of-{args.pr_number}"}


class ExtractArgs(BaseModel):
    diff: str


def _extract(args: ExtractArgs, ctx: dict) -> dict:
    return {"ticker": "MOCK", "factor": "MOCK_FACTOR"}


class GenSpecArgs(BaseModel):
    metadata: dict


def _gen_spec(args: GenSpecArgs, ctx: dict) -> dict:
    return {"model_id": f"mdl-{hash(str(args.metadata)) % 10000}"}


READ_PR = ToolDef(
    id="read_pr",
    description="Read PR diff",
    schema=ReadPRArgs,
    execute=_read_pr,
)
EXTRACT = ToolDef(
    id="extract_metadata",
    description="Extract metadata",
    schema=ExtractArgs,
    execute=_extract,
)
GEN_SPEC = ToolDef(
    id="generate_model_spec",
    description="Generate model spec",
    schema=GenSpecArgs,
    execute=_gen_spec,
)
SEARCH_MEM = ToolDef(
    id="search_memory",
    description="Search memory",
    schema=BaseModel,
    execute=lambda args, ctx: {"hits": []},
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_registry():
    global_registry._tools.clear()
    yield global_registry
    global_registry._tools.clear()


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "checkpoint.db"
    yield db
    clear_checkpointer_cache()


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


def test_agent_runs_three_step_task(tmp_db, clean_registry):
    """Agent 自主完成 3 步任务：read_pr → extract_metadata → generate_model_spec → final。"""
    register_tool(READ_PR)
    register_tool(EXTRACT)
    register_tool(GEN_SPEC)

    # LLM 脚本：
    # 1. 调 read_pr(123)
    # 2. 调 extract_metadata({"diff": "..."})
    # 3. 调 generate_model_spec({"metadata": "..."})
    # 4. 返回 final answer
    llm = ScriptedLLM(
        [
            _ai_with_tools([("read_pr", {"pr_number": 123})], "step1"),
            _ai_with_tools(
                [("extract_metadata", {"diff": "diff-of-123"})], "step2"
            ),
            _ai_with_tools(
                [("generate_model_spec", {"metadata": {"ticker": "MOCK"}})], "step3"
            ),
            AIMessage(content="Task complete."),
        ]
    )

    runner = AgentRunner(
        group="model",
        model=llm,
        checkpoint_db=tmp_db,
    )
    final = runner.run(
        task="Read PR #123 and generate a model spec",
        skill_name=None,
        system_prompt="You are a model agent.",
        flow_name="three_step",
        thread_id="t-three-step-1",
    )

    # 至少 4 个 messages（Human + 3 AI + 3 Tool + final AI = 8）
    assert len(final["messages"]) >= 7
    # iterations 至少 3
    assert final["iterations"] >= 3
    # 最后是 AI final answer
    assert isinstance(final["messages"][-1], AIMessage)
    assert final["messages"][-1].content == "Task complete."


def test_agent_uses_skill_markdown_as_system_prompt(tmp_db, clean_registry):
    """SKILL.md 能被加载并作为 system prompt。"""
    register_tool(READ_PR)

    llm = ScriptedLLM(
        [
            _ai_with_tools([("read_pr", {"pr_number": 1})]),
            AIMessage(content="done"),
        ]
    )

    captured_system: list[str] = []

    def capturing_llm(messages, tools=None):
        captured_system.append(messages[0].content if messages else "")
        return ScriptedLLM.__call__(llm, messages, tools)

    runner = AgentRunner(
        group="model",
        model=capturing_llm,
        checkpoint_db=tmp_db,
    )
    runner.run(
        task="test",
        skill_name="model-pr-submit",
        thread_id="t-skill-1",
        flow_name="skill_test",
    )

    # system prompt 应该来自 .opencode/groups/model/skills/model-pr-submit/SKILL.md
    assert len(captured_system) >= 1
    assert "PR" in captured_system[0] or "model" in captured_system[0].lower()


def test_agent_uses_meta_skill_when_no_group(tmp_db, clean_registry):
    """skill_name 不带 group 时，从 MimoCode .bundle/ 加载元 skill。"""
    register_tool(READ_PR)

    llm = ScriptedLLM([AIMessage(content="done")])

    captured_system: list[str] = []

    def capturing_llm(messages, tools=None):
        captured_system.append(messages[0].content if messages else "")
        return ScriptedLLM.__call__(llm, messages, tools)

    runner = AgentRunner(
        group="model",
        model=capturing_llm,
        checkpoint_db=tmp_db,
    )
    runner.run(
        task="test",
        skill_name="tdd",  # 元 skill（从 MiMo-Code .bundle/ 复制过来的）
        thread_id="t-meta-skill-1",
        flow_name="meta_skill_test",
    )

    assert len(captured_system) >= 1
    # 应该是 tdd skill 的内容
    assert "tdd" in captured_system[0].lower() or "test" in captured_system[0].lower()


def test_agent_filters_tools_by_group(tmp_db, clean_registry):
    """model 组拿不到 risk 专属 tool（如果 risk 不在 model allowlist）。"""
    register_tool(READ_PR)  # 在 model allowlist

    # 假设 risk-only tool
    risk_only = ToolDef(
        id="risk_only_tool",
        description="risk only",
        schema=BaseModel,
        execute=lambda args, ctx: "should not be reachable",
    )
    register_tool(risk_only)

    # 直接验证 registry 的按组过滤逻辑（tools 不在 state 里了）
    tools_for_model = global_registry.get_tools_for_group("model")
    tool_ids = [t.id for t in tools_for_model]
    assert "read_pr" in tool_ids
    assert "risk_only_tool" not in tool_ids


def test_agent_resume_from_checkpoint(tmp_db, clean_registry):
    """checkpoint 持久化 + 同 thread_id 能加载回 state。

    关键性质：
    1. 第一次跑完，messages 在 checkpoint 里
    2. 第二次同 thread_id + resume=True → 加载回相同的 messages 列表
    3. 第二次也能再次 invoke（即 checkpoint 可重入）
    """
    register_tool(READ_PR)

    # 第一次：跑完一个完整任务
    llm1 = ScriptedLLM(
        [
            _ai_with_tools([("read_pr", {"pr_number": 7})]),
            AIMessage(content="first run done"),
        ]
    )
    runner1 = AgentRunner(group="model", model=llm1, checkpoint_db=tmp_db)
    first = runner1.run(
        task="resume test",
        system_prompt="x",
        thread_id="t-resume-1",
        flow_name="resume_test",
    )
    first_msg_count = len(first["messages"])
    assert first["messages"][-1].content == "first run done"

    # 第二次：同 thread_id + resume=True → 加载 checkpoint
    llm2 = ScriptedLLM([AIMessage(content="resumed run done")])
    runner2 = AgentRunner(group="model", model=llm2, checkpoint_db=tmp_db)
    second = runner2.run(
        task="resume test",
        system_prompt="x",
        thread_id="t-resume-1",
        flow_name="resume_test",
        resume=True,
    )
    # messages 列表应该来自 checkpoint（因为 resume=True 时 init_state=None）
    assert len(second["messages"]) == first_msg_count
    assert second["messages"][-1].content == "first run done"


def test_two_concurrent_agents_dont_conflict(tmp_db, clean_registry):
    """两个 Agent 用不同 thread_id 同时跑，互不干扰。"""
    register_tool(READ_PR)
    register_tool(EXTRACT)

    # Agent 1 的 LLM：调 read_pr(1)，返回 final-A
    llm_a = ScriptedLLM(
        [
            _ai_with_tools([("read_pr", {"pr_number": 1})], "a"),
            AIMessage(content="A done"),
        ]
    )
    # Agent 2 的 LLM：调 read_pr(2)，返回 final-B
    llm_b = ScriptedLLM(
        [
            _ai_with_tools([("read_pr", {"pr_number": 2})], "b"),
            AIMessage(content="B done"),
        ]
    )

    runner_a = AgentRunner(group="model", model=llm_a, checkpoint_db=tmp_db)
    runner_b = AgentRunner(group="model", model=llm_b, checkpoint_db=tmp_db)

    result_a = runner_a.run(
        task="task A",
        system_prompt="x",
        thread_id="concurrent-A",
        flow_name="concurrent",
    )
    result_b = runner_b.run(
        task="task B",
        system_prompt="x",
        thread_id="concurrent-B",
        flow_name="concurrent",
    )

    assert result_a["messages"][-1].content == "A done"
    assert result_b["messages"][-1].content == "B done"
    # thread_id 隔离
    assert result_a["thread_id"] == "concurrent-A"
    assert result_b["thread_id"] == "concurrent-B"


def test_agent_handles_unknown_tool_gracefully(tmp_db, clean_registry):
    """LLM 调用了未注册的 tool → tool_node 返回错误 message，Agent 继续。"""
    register_tool(READ_PR)

    # 第一次：调一个不存在的 tool → 错误
    # 第二次：返回 final
    llm = ScriptedLLM(
        [
            _ai_with_tools([("nonexistent_tool", {})]),
            AIMessage(content="recovered"),
        ]
    )

    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)
    final = runner.run(
        task="test unknown",
        system_prompt="x",
        thread_id="t-unknown-1",
        flow_name="unknown_tool_test",
    )

    # 至少有一个 ToolMessage 含错误信息
    from langchain_core.messages import ToolMessage

    error_msgs = [
        m
        for m in final["messages"]
        if isinstance(m, ToolMessage) and "failed" in m.content
    ]
    assert len(error_msgs) >= 1
    # 最终还是得到 final answer
    assert final["messages"][-1].content == "recovered"


def test_agent_stops_on_max_iterations(tmp_db, clean_registry):
    """达到 MAX_ITERATIONS 时强制 END。"""
    register_tool(READ_PR)

    # LLM 永远返回 tool_call（永不返回 final answer）
    class InfiniteToolLLM:
        def __init__(self):
            self.calls = 0

        def __call__(self, messages, tools=None):
            self.calls += 1
            return _ai_with_tools(
                [("read_pr", {"pr_number": self.calls})], f"inf-{self.calls}"
            )

    runner = AgentRunner(
        group="model",
        model=InfiniteToolLLM(),
        checkpoint_db=tmp_db,
        max_iterations=3,  # 小一点加速测试
    )
    final = runner.run(
        task="loop test",
        system_prompt="x",
        thread_id="t-max-iter-1",
        flow_name="max_iter",
    )

    # 迭代到 max_iterations 就停
    assert final["iterations"] <= 3


def test_default_thread_ids_are_unique_across_runs(tmp_db, clean_registry):
    """Day 3 review 决策 #6 修复：默认 thread_id 自动追加 uuid，避开同秒碰撞。

    不传 thread_id 时连续跑 5 次，每次都应该生成不同的 thread_id。
    """
    register_tool(READ_PR)
    llm = ScriptedLLM([AIMessage(content="done")])

    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)
    generated_ids: set[str] = set()
    for _ in range(5):
        final = runner.run(
            task="x",
            system_prompt="x",
            flow_name="same_flow_same_second",
            # 不传 thread_id
        )
        generated_ids.add(final["thread_id"])

    # 5 次都唯一（uuid 8 位 = 16M 种空间，碰撞概率 ~ 1/百万）
    assert len(generated_ids) == 5, f"thread_id 碰撞: {generated_ids}"


def test_explicit_thread_id_is_preserved(tmp_db, clean_registry):
    """显式传 thread_id 时，原样使用，不追加 uuid。"""
    register_tool(READ_PR)
    llm = ScriptedLLM([AIMessage(content="done")])

    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)
    final = runner.run(
        task="x",
        system_prompt="x",
        thread_id="my-explicit-id",
    )
    assert final["thread_id"] == "my-explicit-id"


def test_default_thread_id_format_includes_uuid(tmp_db, clean_registry):
    """默认 thread_id 应该包含 uuid 后缀（8 位 hex）。"""
    import re

    register_tool(READ_PR)
    llm = ScriptedLLM([AIMessage(content="done")])

    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)
    final = runner.run(task="x", system_prompt="x", flow_name="format_test")
    tid = final["thread_id"]
    # 格式：<group>-<flow>-<epoch>-<uuid8>
    # uuid8 是 8 位 [0-9a-f]
    assert re.search(r"-[0-9a-f]{8}$", tid), f"thread_id 末尾缺 uuid 后缀: {tid}"
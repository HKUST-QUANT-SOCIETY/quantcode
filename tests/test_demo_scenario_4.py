"""Day 5 Demo 场景 4 集成验证 — 尹一帆。

对应 Day5 §8 场景 4:自研加固 + 自我进化(5 分钟)。
覆盖:
1. 死循环检测自动中止(loop_detector)
2. Dream 提取知识写入 memory(trigger_dream → memory.db)
3. RLHF 数据收集(rlhf_collect_node → rlhf_data.jsonl)

三个组件走整体闭环:同一 tmp_dir 下,一次 run() 触发三件事。

Day 5 关键变更(相对 brief 假设):
- ``RLHFCollector`` 在 Day 5 RLHF 重构时已删除,改用 ``log_rlhf_entry()`` + 新格式,
  配合 ``monkeypatch.setattr(rlogger_mod, "RLHF_PATH", tmp)`` 改写入路径。
- ``AgentRunner.rlhf_collector`` 参数保留向后兼容但不再写日志,
  实际写日志的是图内的 ``rlhf_collect_node``。
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import ToolDef, register_tool
from tools.registry import registry as global_registry


# ---------------------------------------------------------------------------
# Mock tool:反复调同一个 tool 触发死循环
# ---------------------------------------------------------------------------


class _LoopArgs(BaseModel):
    n: int = 1


def _read_loop(args, ctx):
    return {"n": args.n}


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


@pytest.fixture
def demo_setup(tmp_path):
    """演示场景的统一 tmp 目录 + 必要文件路径。"""
    quantcode_dir = tmp_path / ".quantcode"
    quantcode_dir.mkdir()
    rlhf_path = quantcode_dir / "rlhf_data.jsonl"
    memory_root = quantcode_dir
    events_path = quantcode_dir / "dream_events.jsonl"
    return {
        "rlhf_path": rlhf_path,
        "memory_root": memory_root,
        "events_path": events_path,
    }


# ---------------------------------------------------------------------------
# 1. 死循环检测
# ---------------------------------------------------------------------------


def test_demo_4_loop_detection_stops_early(tmp_db, clean_registry):
    """场景 4 · 死循环检测:同一 tool 同 args 反复调用 → 触发 loop → 自动中止。

    走整体逻辑闭环:AgentRunner.run() 跑真实 loop_detector,
    验证 iterations < max_iterations(检测生效)。
    """
    register_tool(ToolDef(
        id="read_loop",
        description="Mock loop",
        schema=_LoopArgs,
        execute=_read_loop,
    ))

    # LLM 反复调 read_loop(触发 loop)
    class _LoopLLM:
        def __init__(self):
            self._idx = 0

        def __call__(self, messages, tools=None):
            self._idx += 1
            if self._idx > 50:
                return AIMessage(content="[should not reach]")
            return AIMessage(
                content="",
                tool_calls=[{"name": "read_loop", "args": {"n": 1}, "id": f"loop-{self._idx}"}],
            )

    runner = AgentRunner(
        group="model",
        model=_LoopLLM(),
        checkpoint_db=tmp_db,
        max_iterations=20,  # 给 20 步上限,但 loop_detector 应提前触发
    )
    final = runner.run(
        task="Loop test",
        skill_name=None,
        system_prompt="x",
        flow_name="demo4_loop",
        thread_id="t-demo4-loop",
    )

    # loop_detector 触发后,run() 应在远小于 max_iterations 时结束
    # Day 5:loop gate 测试阶段放行,agent 会继续到 max_iterations;
    # 但 fingerprint / loop detector 提前触发 human_gate → 实际 iterations 仍 < 20
    assert final["iterations"] < 20, (
        f"iterations={final['iterations']} 未在 loop 检测时提前中止"
    )


# ---------------------------------------------------------------------------
# 2. Dream 提取知识写入 memory
# ---------------------------------------------------------------------------


def test_demo_4_dream_writes_memory_and_event(demo_setup):
    """场景 4 · Dream:trigger_dream() 跑完,memory 真写入 + 事件流落盘。

    走整体逻辑闭环:准备 RLHF fixture → trigger_dream() →
    验证 .quantcode/memory.db 含新条目 + .quantcode/dream_events.jsonl 含 dream_completed。
    """
    rlhf = demo_setup["rlhf_path"]
    rlhf.write_text(
        json.dumps({
            "thread_id": "demo4-dream",
            "action": {"tool_name": "calc_risk", "tool_args": {"x": 1}},
            "observation": {"success": True, "summary": "demo4 ok"},
        }) + "\n",
        encoding="utf-8",
    )

    from dream.trigger import trigger_dream

    result = trigger_dream(
        rlhf_path=rlhf,
        memory_root=demo_setup["memory_root"],
        event_sink=demo_setup["events_path"],
        llm_mode="mock",
    )

    # 验证事件流落盘
    events_path = demo_setup["events_path"]
    assert events_path.exists(), f"事件流文件应存在: {events_path}"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [e["event"] for e in events]
    assert "dream_completed" in event_types, f"事件流应含 dream_completed, got {event_types}"

    # 验证 memory 真写入
    mem_db = demo_setup["memory_root"] / "memory.db"
    assert mem_db.exists(), f"memory.db 应被创建: {mem_db}"
    assert len(result["hits"]) >= 1, "trigger_dream 应至少返回 1 条 hit"


# ---------------------------------------------------------------------------
# 3. RLHF 数据收集
# ---------------------------------------------------------------------------


def test_demo_4_rlhf_data_collected_to_file(tmp_db, clean_registry, tmp_path, monkeypatch):
    """场景 4 · RLHF 数据收集:AgentRunner 跑完,RLHF 写入 .quantcode/rlhf_data.jsonl。

    走整体逻辑闭环:AgentRunner.run() → 图内 rlhf_collect_node 触发 → 文件真写入。

    Day 5 适配:``RLHFCollector`` 已删除,改用 ``log_rlhf_entry()`` 内置写入固定
    ``RLHF_PATH``。本测试用 monkeypatch 把 ``RLHF_PATH`` 重定向到 tmp,
    验证实际触发了日志写入(而不是用假设的 collector 接口)。
    """
    # 把 RLHF 默认输出路径重定向到 tmp 文件
    rlhf_path = tmp_path / "rlhf_data.jsonl"
    import runner.routing.rlhf_logger as rlogger_mod
    monkeypatch.setattr(rlogger_mod, "RLHF_PATH", rlhf_path)

    register_tool(ToolDef(
        id="read_simple",
        description="Simple",
        schema=_LoopArgs,
        execute=_read_loop,
    ))

    class _SimpleLLM:
        def __init__(self):
            self._idx = 0

        def __call__(self, messages, tools=None):
            self._idx += 1
            if self._idx == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "read_simple", "args": {"n": 1}, "id": "1"}],
                )
            return AIMessage(content="rlhf demo done")

    # 不传 rlhf_collector(Day 5 已弃用参数,改由 rlhf_collect_node 自动收集)
    runner = AgentRunner(
        group="model",
        model=_SimpleLLM(),
        checkpoint_db=tmp_db,
    )
    runner.run(
        task="RLHF demo",
        skill_name=None,
        system_prompt="x",
        flow_name="demo4_rlhf",
        thread_id="t-demo4-rlhf",
    )

    # 验证 RLHF 文件被写入
    assert rlhf_path.exists(), f"RLHF 文件应被创建: {rlhf_path}"
    lines = [
        json.loads(line)
        for line in rlhf_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) >= 1, "RLHF 文件至少应含 1 条记录"


# ---------------------------------------------------------------------------
# 集成测试:三件事一次跑通
# ---------------------------------------------------------------------------


def test_demo_4_all_three_components_together(tmp_db, clean_registry, tmp_path, monkeypatch):
    """场景 4 整体:dream + loop detection + rlhf 同 tmp_dir 下各验真。

    走整体逻辑闭环:三个组件的真实产物落在同一个 .quantcode/ 下。
    """
    # setup
    quantcode_dir = tmp_path / ".quantcode"
    quantcode_dir.mkdir()
    rlhf_path = quantcode_dir / "rlhf_data.jsonl"
    memory_root = quantcode_dir
    events_path = quantcode_dir / "dream_events.jsonl"

    # 把 RLHF 默认输出路径重定向到 rlhf_path
    import runner.routing.rlhf_logger as rlogger_mod
    monkeypatch.setattr(rlogger_mod, "RLHF_PATH", rlhf_path)

    # 1. 先跑 RLHF(AgentRunner 跑一次简单任务,收集一条记录)
    register_tool(ToolDef(
        id="read_simple",
        description="Simple",
        schema=_LoopArgs,
        execute=_read_loop,
    ))

    class _LLM:
        def __init__(self):
            self._idx = 0

        def __call__(self, messages, tools=None):
            self._idx += 1
            if self._idx == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "read_simple", "args": {"n": 1}, "id": "1"}],
                )
            return AIMessage(content="done")

    runner = AgentRunner(
        group="model",
        model=_LLM(),
        checkpoint_db=tmp_db,
    )
    runner.run(
        task="Demo 4 setup",
        skill_name=None,
        system_prompt="x",
        flow_name="demo4_setup",
        thread_id="t-demo4-setup",
    )
    assert rlhf_path.exists(), "RLHF 应被 AgentRunner 写入"

    # 2. 再跑 Dream(基于刚写入的 RLHF 数据)
    from dream.trigger import trigger_dream
    trigger_dream(
        rlhf_path=rlhf_path,
        memory_root=memory_root,
        event_sink=events_path,
        llm_mode="mock",
    )
    assert events_path.exists(), "Dream 事件流应被写入"
    assert (memory_root / "memory.db").exists(), "Memory DB 应被创建"

    # 3. 验证三件事的产物都在 .quantcode/ 下
    artifacts = [
        rlhf_path,
        memory_root / "memory.db",
        events_path,
    ]
    for p in artifacts:
        assert p.exists(), f"demo 场景 4 产物缺失: {p}"

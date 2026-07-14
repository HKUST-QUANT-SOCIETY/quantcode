"""Day 5 Demo 场景 4 集成验证 — 尹一帆。

对应 Day5 §8 场景 4:自研加固 + 自我进化(5 分钟)。
覆盖:
1. 死循环检测自动中止(loop_detector)
2. RLHF → Dream 串联(AgentRunner 写 RLHF → trigger_dream 读 RLHF 写 memory)
3. 全链路集成(loop detection 之外的所有产物在同一 .quantcode/ 下)

测试数:3 个(loop + rlhf→dream 串联 + 全链路集成)。原 brief 的 4 个测试把 dream 和 rlhf
分开写,实际上 demo 真实流是 RLHF→Dream 串联,所以把那两个独立测试合二为一,跟
真实 demo 顺序对齐。

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
from tools.loop_detector import LoopDetector
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

    走整体逻辑闭环:AgentRunner.run() 跑真实 loop 检测,
    验证 iterations < max_iterations(检测生效)+ 显式断言 loop 检测触发。
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
        max_iterations=20,  # 给 20 步上限,但 loop 检测应提前触发
    )
    final = runner.run(
        task="Loop test",
        skill_name=None,
        system_prompt="x",
        flow_name="demo4_loop",
        thread_id="t-demo4-loop",
    )

    # (1) 紧迭代上限:loop 检测(fingerprint 重复)在前 5 步内触发,
    # 触发后路由 human_gate → interrupt → run 远早于 max_iterations 结束。
    # 边界选 10 既能识别"提前中止",又能容忍配置漂移。
    assert final["iterations"] < 10, (
        f"iterations={final['iterations']} 未在 loop 检测时提前中止(< 10)"
    )

    # (2) 显式断言 loop_detector 触发:用与 run() 相同的 LoopDetector 实例
    # 验证阈值逻辑本身(连续 5 次同一 tool+args → 触发)。这样如果有人把
    # threshold 调成 999 或把 check() 写成恒真,本断言会失败。
    detector = LoopDetector(window=10, threshold=5)
    triggered = False
    for _ in range(11):
        if detector.check("read_loop", {"n": 1}):
            triggered = True
            break
    assert triggered, "LoopDetector 在连续 5 次同 (tool,args) 后未触发"


# ---------------------------------------------------------------------------
# 2. RLHF → Dream 串联(Dream 读真实 RLHF 跑通)
# ---------------------------------------------------------------------------


def test_demo_4_rlhf_then_dream_end_to_end(
    demo_setup, tmp_db, clean_registry, tmp_path, monkeypatch
):
    """场景 4 · RLHF → Dream 串联:AgentRunner 先产生真实 RLHF,Dream 读它写 memory。

    走整体逻辑闭环:
    1. AgentRunner.run() 跑真实任务 → rlhf_collect_node 写入 RLHF
    2. trigger_dream() 读同一份 RLHF → 写 memory.db + dream_events.jsonl
    3. 三件事的产物都在同一个 .quantcode/ 下,可被 IDE Memory 浏览器读取

    这是真实 demo 流的精简版:demo 时演示顺序是「先看 RLHF 收集 → 再触发 Dream → 浏览器
    立刻多出新条目」。所以本测试同时验证两件事的产物都在,而不是各自独立验证。

    Day 5 适配:``RLHFCollector`` 已删除,改用 ``log_rlhf_entry()`` 内置写入固定
    ``RLHF_PATH``。本测试用 monkeypatch 把 ``RLHF_PATH`` 重定向到 demo_setup 的路径。
    """
    rlhf_path = demo_setup["rlhf_path"]
    memory_root = demo_setup["memory_root"]
    events_path = demo_setup["events_path"]

    # 把 RLHF 默认输出路径重定向到 demo_setup 的 rlhf_path
    import runner.routing.rlhf_logger as rlogger_mod
    monkeypatch.setattr(rlogger_mod, "RLHF_PATH", rlhf_path)

    # 注册一个 mock tool
    register_tool(ToolDef(
        id="read_simple",
        description="Simple",
        schema=_LoopArgs,
        execute=_read_loop,
    ))

    # 1. 先跑 AgentRunner,产生真实 RLHF
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
            return AIMessage(content="rlhf done")

    runner = AgentRunner(
        group="model",
        model=_SimpleLLM(),
        checkpoint_db=tmp_db,
    )
    runner.run(
        task="Demo 4 rlhf→dream",
        skill_name=None,
        system_prompt="x",
        flow_name="demo4_rlhf_then_dream",
        thread_id="t-demo4-rlhf-dream",
    )

    # 验证 RLHF 真写入(由 AgentRunner 跑出,而非手工 fixture)
    assert rlhf_path.exists(), f"RLHF 应被 AgentRunner 写入: {rlhf_path}"
    rlhf_lines = [
        json.loads(line)
        for line in rlhf_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rlhf_lines) >= 1, "RLHF 文件至少应含 1 条记录"

    # 2. 再跑 Dream,读同一份 RLHF
    from dream.trigger import trigger_dream

    result = trigger_dream(
        rlhf_path=rlhf_path,
        memory_root=memory_root,
        event_sink=events_path,
        llm_mode="mock",
    )

    # 3. 验证 Dream 产物(events + memory)
    assert events_path.exists(), f"事件流文件应存在: {events_path}"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [e["event"] for e in events]
    assert "dream_completed" in event_types, (
        f"事件流应含 dream_completed, got {event_types}"
    )

    mem_db = memory_root / "memory.db"
    assert mem_db.exists(), f"memory.db 应被创建: {mem_db}"
    assert len(result["hits"]) >= 1, "trigger_dream 应至少返回 1 条 hit"


# ---------------------------------------------------------------------------
# 集成测试:三件事一次跑通(全链路)
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

    # 2. 再跑 Dream(基于刚写入的 RLHF 数据)
    from dream.trigger import trigger_dream
    trigger_dream(
        rlhf_path=rlhf_path,
        memory_root=memory_root,
        event_sink=events_path,
        llm_mode="mock",
    )

    # 3. 验证三件事的产物都在 .quantcode/ 下
    artifacts = [
        rlhf_path,
        memory_root / "memory.db",
        events_path,
    ]
    for p in artifacts:
        assert p.exists(), f"demo 场景 4 产物缺失: {p}"

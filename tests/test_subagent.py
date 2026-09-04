"""test_subagent.py — P-04 并行 subagent 端到端测试（spawn/check/kill/任务树/预算）。

覆盖（ROADMAP R3 Q2 三件事 + 预算门）：
1. spawn 一个 factor 子任务（ScriptedLLM 风格，参照 test_agent_engine_basic）
   → check_subagent 轮询到终态取 output_data；
2. spawn 死循环子任务 → kill_subagent <1s 返回且 trace 记 abort（subagent_aborted）；
3. 任务树：list_subagents 返回父子关系（parent_thread_id 链）+ MAX_TREE_DEPTH 拒绝超深 spawn；
4. 预算耗尽的子任务按 Wave1 budget gate 暂停（waiting_for_human，不 kill）；
5. group 校验/工具注册边界（越权 group fail-closed、_meta 通道可见）。

隔离策略：tmp checkpoint DB（经 ctx["_checkpoint_db"]）+ 测试内 fresh SubagentRegistry
（不污染全局 parallel_registry）+ registry._tools 清理。
"""
from __future__ import annotations

import importlib
import time

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import ToolDef, registry as global_registry


# ---------------------------------------------------------------------------
# ScriptedLLM / mock tools（参照 tests/test_agent_engine_basic.py）
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """按调用次数返回预设 AIMessage；不够则 'done'。"""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="done")
        self._idx += 1
        return resp


class InfiniteSameToolLLM:
    """永远要求调用同一 tool、每次 args 递增（真死循环子任务用）。

    - args.n 递增 → tool_args 进 fingerprint → 指纹不重复，绕开 loop gate
      interrupt（否则 2 步后 state_loop → waiting_for_human，与 kill 竞态）。
    - sleep 压慢步速，稳定 kill 命中窗口（cancel flag 在两次 LLM 之间置位）。
    """

    def __init__(self, sleep: float = 0.15):
        self.calls = 0
        self.sleep = sleep

    def __call__(self, messages, tools=None):
        self.calls += 1
        time.sleep(self.sleep)
        return AIMessage(content="", tool_calls=[
            {"name": "spin_tool", "args": {"n": self.calls}, "id": f"spin-{self.calls}"}
        ])


def _ai(name: str, cid: str, args: dict | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": cid}])


class SpinArgs(BaseModel):
    n: int = 1


class FinishArgs(BaseModel):
    pass


def _register_mock_tools() -> None:
    global_registry._tools["spin_tool"] = ToolDef(
        id="spin_tool", description="circular", schema=SpinArgs,
        execute=lambda args, ctx: {"spun": args.n},
    )
    global_registry._tools["task_done"] = ToolDef(
        id="task_done", description="finish", schema=FinishArgs,
        execute=lambda args, ctx: {"task_status": "done", "output_data": {"finished": True}},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sub_tools():
    """mock 单步 tool + 清理。"""
    _register_mock_tools()
    yield
    for tid in ("spin_tool", "task_done"):
        global_registry._tools.pop(tid, None)


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "subagent-checkpoints.db"
    yield str(db)
    clear_checkpointer_cache()


@pytest.fixture
def reg(monkeypatch):
    """fresh SubagentRegistry 并顶替全局单例（工具层 executes 每次调用时动态
    import``runner.parallel_registry.parallel_registry``，monkeypatch 恢复原物）。"""
    import runner.parallel_registry as pr

    fresh = pr.SubagentRegistry()
    monkeypatch.setattr(pr, "parallel_registry", fresh)
    yield fresh


@pytest.fixture
def subagent_tools():
    """subagent 四工具注册 + 结束清理（其它测试可能清空 registry）。"""
    import tools.subagent._register as sr

    importlib.reload(sr)
    yield sr
    for tid in ("spawn_subagent", "check_subagent", "kill_subagent", "list_subagents"):
        global_registry._tools.pop(tid, None)


def _ctx(tmp_db: str, model, **kw) -> dict:
    ctx = {"group": "factor", "thread_id": kw.pop("thread_id", "parent-t1"), "_model": model,
           "_checkpoint_db": tmp_db}
    ctx.update(kw)
    return ctx


# ---------------------------------------------------------------------------
# 1. spawn factor 子任务 → 轮询完成取 output_data
# ---------------------------------------------------------------------------


def test_spawn_factor_subtask_completes_with_output_data(
    reg, sub_tools, tmp_db, subagent_tools
):
    """spawn factor 子任务（gen_schema 工具步 + 收尾步）→ check(wait) 取 output_data。

    gen_schema 是 factor 真版 tool（无 API key 自动降级规则版，确定性输出），
    第二步 task_done 注入 task_status=done → completed。
    """
    import tools.factor._register  # noqa: F401  注册 match_main/gen_schema/quant_evaluator

    model = ScriptedLLM([
        _ai("gen_schema", "s1", {"idea": "PB-ROE factor", "match_result": {"fields": ["pb"]}}),
        _ai("task_done", "s2"),
    ])
    spawn = subagent_tools._spawn_subagent_execute(
        subagent_tools.SpawnSubagentArgs(
            task="generate FactorSpec for PB-ROE factor", group="factor",
        ),
        _ctx(tmp_db, model, allowed_groups=["factor", "model"]),
    )
    assert spawn["status"] == "running", spawn
    assert spawn["group"] == "factor"
    assert spawn["subagent_id"].startswith("sub-")
    assert spawn["parent_thread_id"] == "parent-t1"

    final = subagent_tools._check_subagent_execute(
        subagent_tools.CheckSubagentArgs(subagent_id=spawn["subagent_id"], wait_s=15),
        {},
    )
    assert final["status"] == "completed", final
    assert final["output_data"] == {"finished": True}
    assert final["budget_used"] > 0
    assert "runner" not in final and "cancel_event" not in final  # 内部字段不外泄


def test_spawn_via_tooldef_registry_route(reg, sub_tools, tmp_db, subagent_tools):
    """经 registry.call 走 ToolDef 路径（真实 MCP tools/call 同路）。"""
    import tools.factor._register  # noqa: F401

    model = ScriptedLLM([_ai("task_done", "s1")])
    global_registry._tools["spawn_subagent"].execute(
        subagent_tools.SpawnSubagentArgs(task="quick done", group="factor"),
        _ctx(tmp_db, model),
    )
    # 注册链幂等：四工具可查
    assert "spawn_subagent" in global_registry.list_ids()
    assert "list_subagents" in global_registry.list_ids()


# ---------------------------------------------------------------------------
# 2. 死循环子任务 → kill <1s 且 trace 记 abort
# ---------------------------------------------------------------------------


def test_kill_infinite_loop_subagent_under_1s_with_abort_trace(
    reg, sub_tools, tmp_db, subagent_tools
):
    """死循环子任务 spawn → kill：<1s 返回，trace 记 abort（subagent_aborted）。

    时机：固定短窗后 kill（InfiniteSameToolLLM 自带 sleep 压慢步速）。
    不能轮询 budget_used 等首步再杀：CI 抖动下可能已跑满 5 次同 tool 连调
    （tool-frequency loop gate interrupt → waiting_for_human），那测的就是
    gate 而不是 kill 了。
    """
    spawn = subagent_tools._spawn_subagent_execute(
        subagent_tools.SpawnSubagentArgs(task="spin forever", group="factor"),
        _ctx(tmp_db, InfiniteSameToolLLM()),
    )
    subagent_id = spawn["subagent_id"]
    # 0.35s ≈ 2 步 < 5 连（gate 阈值），kill 必然命中下一步 LLM 前的 cancel check
    time.sleep(0.35)

    t0 = time.time()
    killed = subagent_tools._kill_subagent_execute(
        subagent_tools.KillSubagentArgs(subagent_id=subagent_id, reason="test kill"),
        {},
    )
    elapsed = time.time() - t0
    assert elapsed < 1.0, f"kill took {elapsed:.3f}s"
    assert killed["stop_requested"] is True
    assert killed["status"] == "aborted", killed
    assert killed["kill_reason"] == "test kill"
    trace = killed["trace"] or []
    abort_events = [e for e in trace if e.get("type") == "subagent_aborted"]
    assert abort_events, f"trace 缺 abort 记录: {trace[:5]}"
    assert abort_events[0]["thread_id"] == killed["thread_id"]

    # kill 幂等：再 kill 返回同一终态
    again = subagent_tools._kill_subagent_execute(
        subagent_tools.KillSubagentArgs(subagent_id=subagent_id, reason="again"), {}
    )
    assert again["status"] == "aborted"


def test_check_and_kill_unknown_id_return_error(subagent_tools):
    """未知 subagent_id → check/kill 返回 error dict（不抛异常，MCP isError 通道友好）。"""
    chk = subagent_tools._check_subagent_execute(
        subagent_tools.CheckSubagentArgs(subagent_id="sub-nope"), {}
    )
    assert chk["status"] == "error"
    kil = subagent_tools._kill_subagent_execute(
        subagent_tools.KillSubagentArgs(subagent_id="sub-nope"), {}
    )
    assert kil["status"] == "error"


# ---------------------------------------------------------------------------
# 3. 任务树：list_subagents 父子关系 + MAX_TREE_DEPTH
# ---------------------------------------------------------------------------


def test_task_tree_list_children_parent_child_relation(
    reg, sub_tools, tmp_db, subagent_tools
):
    """同 parent spawn 两个子任务 → list_subagents 返回两条 children；别家 parent 查不到。"""
    model = ScriptedLLM([_ai("task_done", "s1")])
    for _ in range(2):
        subagent_tools._spawn_subagent_execute(
            subagent_tools.SpawnSubagentArgs(task="child", group="factor"),
            _ctx(tmp_db, ScriptedLLM([_ai("task_done", "s1")]), thread_id="tree-parent-9"),
        )
        time.sleep(0.05)

    listed = subagent_tools._list_subagents_execute(
        subagent_tools.ListSubagentsArgs(parent_thread_id="tree-parent-9"), {}
    )
    assert listed["count"] == 2
    assert listed["parent_thread_id"] == "tree-parent-9"
    assert all(c["parent_thread_id"] == "tree-parent-9" for c in listed["children"])
    assert listed["max_tree_depth"] == 4

    other = subagent_tools._list_subagents_execute(
        subagent_tools.ListSubagentsArgs(parent_thread_id="unrelated"), {}
    )
    assert other["count"] == 0

    # 子完成后再查，状态同步为终态
    final = subagent_tools._check_subagent_execute(
        subagent_tools.CheckSubagentArgs(
            subagent_id=listed["children"][0]["subagent_id"], wait_s=15
        ),
        {},
    )
    assert final["status"] == "completed"


def test_spawn_rejects_group_outside_allowed_set(reg, sub_tools, tmp_db, subagent_tools):
    """子 group 必须在父允许集：越权 → fail-closed error，未产生 registry 条目。"""
    out = subagent_tools._spawn_subagent_execute(
        subagent_tools.SpawnSubagentArgs(task="x", group="risk"),
        _ctx(tmp_db, ScriptedLLM([]), allowed_groups=["factor"]),
    )
    assert out["status"] == "error"
    assert "not permitted" in out["error"]

    out2 = subagent_tools._spawn_subagent_execute(
        subagent_tools.SpawnSubagentArgs(task="x", group="not-a-group"),
        _ctx(tmp_db, ScriptedLLM([])),
    )
    assert out2["status"] == "error"
    assert "invalid group" in out2["error"]


def test_spawn_depth_guard_blocks_beyond_max_tree_depth(reg, sub_tools, tmp_db):
    """嵌套超 MAX_TREE_DEPTH=4 的 spawn 被拒。"""
    from runner.parallel_registry import MAX_TREE_DEPTH

    model = ScriptedLLM([AIMessage(content="leaf")])
    # 造一条深度 4 的链：p0 → s1 → s2 → s3 → s4（s4 是第 4 层，允许）
    parent = ""
    tid = "chain-root-0"
    ids = []
    for i in range(MAX_TREE_DEPTH):
        entry = reg.create_subagent(
            f"chain {i}", "factor", parent_thread_id=tid if i else "",
            model=model, checkpoint_db=tmp_db,
        )
        ids.append(entry["subagent_id"])
        # 立即标记终态以免线程续跑干扰（叶子上 ScriptedLLM 无 tool 可调，会自然 stopped）
        # 等它结束最稳妥：无 tool_calls 的 LLM → 第一次 LLM 后路由 end
        reg.kill(ids[-1], reason="chain setup")
        tid = entry["thread_id"]
    # 第 5 层（超限）应被拒
    import pytest

    with pytest.raises(ValueError, match="MAX_TREE_DEPTH"):
        reg.create_subagent(
            "too deep", "factor", parent_thread_id=tid,
            model=model, checkpoint_db=tmp_db,
        )


# ---------------------------------------------------------------------------
# 4. 预算耗尽 → stopped_budget（不 kill）
# ---------------------------------------------------------------------------


BANNER = "#" * 400  # ≈100 tokens（chars/4 估算）


def test_budget_exhausted_subagent_stops_not_killed(reg, sub_tools, tmp_db):
    """v5：预算耗尽是运行时停止状态，不创建 HumanGate。"""
    llm = ScriptedLLM([AIMessage(content=BANNER)])
    entry = reg.create_subagent(
        "banner task", "factor",
        budget_tokens=1, model=llm, checkpoint_db=tmp_db,
    )
    deadline = time.time() + 15
    snap = entry
    while time.time() < deadline:
        snap = reg.get_status(entry["subagent_id"])
        if snap["status"] in ("stopped_budget", "error", "aborted"):
            break
        time.sleep(0.05)
    assert snap["status"] == "stopped_budget", snap
    assert snap["output_data"] is not None
    assert snap["budget_used"] > 1

    # 预算停止 ≠ kill：kill 一个已 stopped 的子任务不会覆盖成 aborted
    killed = reg.kill(entry["subagent_id"], reason="should not flip")
    assert killed["status"] == "stopped_budget"
    assert killed["stop_requested"] is True  # 标记存在，但状态保持暂停


# ---------------------------------------------------------------------------
# 5. 注册边界：_meta 通道可见 + 不进 group allowlist
# ---------------------------------------------------------------------------


def test_subagent_tools_meta_channel_visible_to_all_groups(monkeypatch, subagent_tools):
    """四工具经 _meta 通道对 6 组 tools/list 可见（控制器视角），且不在 factor allowlist。"""
    from quantcode import mcp_server

    import tools.factor._register  # noqa: F401

    for group in ("model", "risk", "factor", "fundamental", "strategy", "options"):
        monkeypatch.setenv("QUANTCODE_GROUP", group)
        importlib.reload(mcp_server)
        names = {t["name"] for t in mcp_server.list_tools()["tools"]}
        for tid in ("spawn_subagent", "check_subagent", "kill_subagent", "list_subagents"):
            assert tid in names, f"group={group} 缺 {tid}: {names}"

    # 不在 factor allowlist（子 agent 的 ReAct 循环看不到自己的 spawn 工具）
    factor_tools = global_registry.get_tools_for_group("factor")
    assert "spawn_subagent" not in {t.id for t in factor_tools}


def test_spawn_without_model_returns_error(sub_tools, subagent_tools):
    """ctx 无 _model 且 mcp_server 无 key → error dict（不抛、不产生条目）。"""
    out = subagent_tools._spawn_subagent_execute(
        subagent_tools.SpawnSubagentArgs(task="x", group="factor"),
        {"group": "factor", "thread_id": "p-x"},
    )
    assert out["status"] == "error"
    assert "model" in out["error"].lower()

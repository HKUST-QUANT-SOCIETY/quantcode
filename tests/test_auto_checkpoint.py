"""P0-8 §4.4 自动快照/重建测试 — context >70% 快照、>90% 重建 + reducer 翻倍修复。

覆盖（任务验收四点）：
(a) >70% → execution_trace 出现 checkpoint_snapshot 事件（kind=snapshot）
(b) >90% → messages 收缩成摘要 + context_rebuilt=True + kind=rebuild 事件
(c) merge_messages reducer 单测：旧 operator.add 会翻倍的序列，新实现长度正确
(d) truncate + reducer 组合不产生重复
"""
from __future__ import annotations

import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

import runner.agent_nodes as an
from runner.agent_nodes import (
    AgentState,
    CONTEXT_REBUILD_RATIO,
    CONTEXT_SNAPSHOT_RATIO,
    _ReplaceMessages,
    context_usage_ratio,
    estimate_context_chars,
    make_rebuild_context_node,
    make_truncate_node,
    merge_messages,
)
from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import ToolDef, registry as global_registry


# ---------------------------------------------------------------------------
# fixtures / helper
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_env():
    """每个用例固定 env，避免相互污染。"""
    old = os.environ.pop("QUANTCODE_CONTEXT_TOKENS", None)
    yield
    if old is None:
        os.environ.pop("QUANTCODE_CONTEXT_TOKENS", None)
    else:
        os.environ["QUANTCODE_CONTEXT_TOKENS"] = old
    clear_checkpointer_cache()


class EchoArgs(BaseModel):
    msg: str


def _scripted_llm(tool_script: list[AIMessage]):
    idx = {"n": 0}

    def llm(messages, tools=None):
        if idx["n"] < len(tool_script):
            r = tool_script[idx["n"]]
            idx["n"] += 1
            return r
        return AIMessage(content="[done]")

    return llm


# ---------------------------------------------------------------------------
# (c) merge_messages reducer 单测 — 旧实现翻倍的序列，新实现长度正确
# ---------------------------------------------------------------------------


def test_merge_messages_no_duplication_on_full_list_readd():
    """旧 operator.add 翻倍场景：节点把累计列表整个 add 回去。

    旧实现: [a,b] + [a,b] → 4 条；新实现去重 → 2 条。
    """
    a = HumanMessage(content="hi")
    b = AIMessage(content="yo")
    merged = merge_messages([], [a, b])
    assert len(merged) == 2
    # 旧实现翻倍的序列：再 add 一次同全量列表
    merged = merge_messages(merged, [a, b])
    assert len(merged) == 2, f"全量重发应去重不翻倍, 实际 {len(merged)}"


def test_merge_messages_distinguishes_tool_call_only_aimessages():
    """空 content + 不同 tool_calls 的 AIMessage 不能被当成同一条。"""
    a = AIMessage(content="", tool_calls=[{"name": "t1", "args": {}, "id": "c0"}])
    b = AIMessage(content="", tool_calls=[{"name": "t2", "args": {}, "id": "c1"}])
    merged = merge_messages([a], [b])
    assert len(merged) == 2


def test_merge_messages_append_path_matches_operator_add():
    """正常追加路径（只带新消息）行为与 operator.add 完全一致。"""
    import operator

    h = HumanMessage(content="task")
    a = AIMessage(content="think")
    t = ToolMessage(content="res", tool_call_id="1", name="t")
    op_add = operator.add([h], [a]) + [t]
    custom = merge_messages(merge_messages(None, [h]), [a])
    custom = merge_messages(custom, [t])
    assert len(custom) == 3
    assert [type(x) for x in custom] == [type(x) for x in op_add]


def test_replace_messages_replaces_whole_list():
    """_ReplaceMessages 语义 = 整体替换（truncate/rebuild 用），不翻倍。"""
    current = [HumanMessage(content="old1"), AIMessage(content="old2")]
    replacement = _ReplaceMessages([AIMessage(content="new")])
    merged = merge_messages(current, replacement)
    assert len(merged) == 1
    assert merged[0].content == "new"


# ---------------------------------------------------------------------------
# (a)(b) 引擎级：>70% 快照 + >90% 重建
# ---------------------------------------------------------------------------


def _run_over_context(tmp_path, *, tool_return_1_2: str, tool_return_3plus: str):
    """跑一个能先后触发 >70% / >90% 的 mock 任务，返回 stream() 最终 state。

    echo 每次返回 ~2200 chars，QUANTCODE_CONTEXT_TOKENS=800：
    每步增量 ≈ (2200+30)/4 ≈ 557 tokens；system+A human ~80。
    第 1 步末 ≈ 0.9 首检 → checkpoint_gate 先快照（此时未 rebuild），
    第 2 步末重建条件成立 → rebuild → 继续 → 第 3 步 [done] 结束。
    """
    os.environ["QUANTCODE_CONTEXT_TOKENS"] = "1200"
    sizes = {"n": 0}

    def _echo(args, ctx):
        sizes["n"] += 1
        return tool_return_1_2 if sizes["n"] <= 2 else tool_return_3plus

    names = ["ac1", "ac2", "ac3", "ac4", "ac5", "ac6"]
    for nm in names:
        global_registry._tools[nm] = ToolDef(
            id=nm, description="echo", schema=EchoArgs, execute=_echo
        )
    try:
        script = [
            AIMessage(
                content="",
                tool_calls=[{"name": names[i], "args": {"msg": f"m{i}"}, "id": str(i)}],
            )
            for i in range(5)
        ] + [AIMessage(content="[done]")]
        from runner.agent_engine import AgentRunner

        runner = AgentRunner(
            group="factor",
            model=_scripted_llm(script),
            checkpoint_db=tmp_path / "cp.db",
        )
        return runner.stream(
            task="auto checkpoint e2e",
            system_prompt="sys" ,
            thread_id="t-auto-ckpt-1",
            flow_name="ac_e2e",
        )
    finally:
        for nm in names:
            global_registry._tools.pop(nm, None)


def test_engine_snapshot_event_fires_over_70pct(tmp_path):
    """(a) 超过 CONTEXT_SNAPSHOT_RATIO → trace 有 checkpoint_snapshot(kind=snapshot)。"""
    final = _run_over_context(tmp_path, tool_return_1_2="y" * 2400, tool_return_3plus="ok")
    trace_types = [e["type"] for e in final["execution_trace"]]
    assert "checkpoint_snapshot" in trace_types
    snap = next(
        e for e in final["execution_trace"] if e["type"] == "checkpoint_snapshot"
    )
    assert snap["data"]["kind"] == "snapshot"
    assert snap["data"]["ratio"] > CONTEXT_SNAPSHOT_RATIO
    assert snap["thread_id"] == "t-auto-ckpt-1"
    assert snap["data"]["time"]


def test_engine_rebuild_over_90pct_shrinks_messages(tmp_path):
    """(b) >90% → messages 收缩 + context_rebuilt + kind=rebuild 事件。"""
    final = _run_over_context(
        tmp_path,
        tool_return_1_2="x" * 2200,
        tool_return_3plus="ok",
    )
    assert final.get("context_rebuilt") is True
    msgs = final["messages"]
    # 契约：重建触发后 messages 被压缩（每步 2200+ chars 的 tool 结果不再原样堆积），
    # 单条消息内容总和远小于"不重建"时的体量（2 个 2200-char 工具结果 ≈ 4400+）。
    total_chars = sum(len(str(getattr(m, "content", "") or "")) for m in msgs)
    assert total_chars < 4200, f"重建后总字符应收缩, got {total_chars}"
    summary_candidates = [
        m for m in msgs if isinstance(m, AIMessage) and "[context rebuilt" in m.content
    ]
    assert summary_candidates, f"应有摘要消息, got {[type(m).__name__ for m in msgs]}"
    assert "工具调用序列" in summary_candidates[0].content
    # 事件链：先 snapshot 后 rebuild
    kinds = [
        e["data"]["kind"]
        for e in final["execution_trace"]
        if e["type"] == "checkpoint_snapshot"
    ]
    assert "rebuild" in kinds
    assert "snapshot" in kinds
    # 每条事件带 thread_id + ratio + time
    rebuild = kinds.index("rebuild")
    ev = next(
        e
        for e in final["execution_trace"]
        if e["type"] == "checkpoint_snapshot" and e["data"]["kind"] == "rebuild"
    )
    assert ev["data"]["thread_id"] == "t-auto-ckpt-1"
    assert ev["data"]["ratio"] > 0


def test_engine_no_duplicate_checkpoint_events(tmp_path):
    """checkpoint_snapshot 通道不滚雪球：snapshot 事件全程只 1 条。"""
    final = _run_over_context(tmp_path, tool_return_1_2="x" * 2400, tool_return_3plus="ok")
    state_events = final.get("checkpoint_snapshot") or []
    snap_events = [e for e in state_events if e.get("kind") == "snapshot"]
    assert len(snap_events) == 1, f"snapshot 事件应只 1 条, got {len(snap_events)}"
    # 事件按时间/序单调出现，无 (snapshot,rebuild) 同批重复
    kinds = [e.get("kind") for e in state_events]
    assert kinds.count("snapshot") == 1
    assert final.get("context_rebuilt") is True


# ---------------------------------------------------------------------------
# (d) truncate + reducer 组合不产生重复
# ---------------------------------------------------------------------------


def test_truncate_with_merge_reducer_no_duplicates(tmp_path):
    """truncate 节点返回整体列表 → merge_messages 整体替换，长度等于 head+middle+tail。"""
    os.environ["QUANTCODE_CONTEXT_TOKENS"] = "128000"
    node = make_truncate_node(max_tokens=100, head_preserve=2, tail_preserve=2)
    msgs = (
        [HumanMessage(content="t"), AIMessage(content="", tool_calls=[{"name": "e", "args": {}, "id": "1"}])]
        + [ToolMessage(content="a" * 900, tool_call_id=str(i), name="e") for i in range(4)]
        + [AIMessage(content="final")]
    )
    first = node({"messages": list(msgs)})
    assert first.get("_truncated") is True
    truncated = first["messages"]
    assert len(truncated) == len(msgs)
    # 再把整个 truncated 列表作为 update 反复合并（模拟 superstep 全量重发）
    state = list(msgs)
    out = state
    for _ in range(3):
        out = merge_messages(out, _ReplaceMessages(truncated))
    assert len(out) == len(truncated), f"组合不翻倍, got {len(out)}"
    # 没有任何内容重复计数
    assert all(isinstance(m, (HumanMessage, AIMessage, ToolMessage)) for m in out)


def test_engine_truncate_e2e_messages_stay_bounded(tmp_path):
    """AgentRunner(truncate_tokens=N) 端到端：messages 不再翻倍，最终被摘要重建。"""
    os.environ["QUANTCODE_CONTEXT_TOKENS"] = "400"
    long_content = "a" * 2000

    def _echo(args, ctx):
        return long_content

    names = ["te1", "te2", "te3", "te4", "te5", "te6"]
    for nm in names:
        global_registry._tools[nm] = ToolDef(
            id=nm, description="echo", schema=EchoArgs, execute=_echo
        )
    try:
        from runner.agent_engine import AgentRunner

        script = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": names[i], "args": {"msg": f"m{i}"}, "id": str(i)}
                ],
            )
            for i in range(5)
        ] + [AIMessage(content="[done]")]
        runner = AgentRunner(
            group="factor",
            model=_scripted_llm(script),
            truncate_tokens=200,
            checkpoint_db=tmp_path / "cp.db",
        )
        final = runner.stream(
            task="truncate + rebuild",
            system_prompt="sys",
            thread_id="t-trunc-e2e-1",
            flow_name="trunc_e2e",
        )
        # 消息列表收缩（摘要+尾部），而不是原始消息 ×N 翻倍
        assert len(final["messages"]) <= 6
        assert final.get("context_rebuilt") is True
        # 没有重复的 snapshot 事件
        snap_events = [
            e for e in (final.get("checkpoint_snapshot") or []) if e.get("kind") == "snapshot"
        ]
        assert len(snap_events) <= 1
    finally:
        for nm in names:
            global_registry._tools.pop(nm, None)


# ---------------------------------------------------------------------------
# 阈值与估算函数单测
# ---------------------------------------------------------------------------


def test_estimate_context_chars_formula():
    """# ponytail: 字符/4 近似 token — 400 chars → 100 tokens。"""
    state = {"messages": [HumanMessage(content="a" * 300)], "system_prompt": "b" * 100}
    assert estimate_context_chars(state) == 100.0


def test_context_usage_ratio_env_override():
    os.environ["QUANTCODE_CONTEXT_TOKENS"] = "400"
    state = {"messages": [HumanMessage(content="a" * 400)], "system_prompt": ""}
    # 400/4 = 100 tokens / 400 = 0.25
    assert context_usage_ratio(state) == 0.25
    os.environ["QUANTCODE_CONTEXT_TOKENS"] = "bogus"  # 非 int → 默认 128000
    assert context_usage_ratio(state) < 0.9


def test_threshold_constants():
    assert CONTEXT_SNAPSHOT_RATIO == 0.7
    assert CONTEXT_REBUILD_RATIO == 0.9


def test_checkpoint_schema_has_event_field():
    """AgentState 契约：checkpoint_snapshot 是 operator.add 通道（事件随 state 流出）。"""
    assert "checkpoint_snapshot" in AgentState.__annotations__
    assert "context_rebuilt" in AgentState.__annotations__
    assert "messages" in AgentState.__annotations__


def test_rebuild_node_direct_call():
    """rebuild 节点直调：保留 system 消息 + 最后 2 条，替换其余为摘要。"""
    node = make_rebuild_context_node()
    state = {
        "messages": [
            HumanMessage(content="user task"),
            AIMessage(content="", tool_calls=[{"name": "t1", "args": {}, "id": "1"}]),
            ToolMessage(content="r1", tool_call_id="1", name="t1"),
            AIMessage(content="second round"),
            AIMessage(content="tail 1"),
            AIMessage(content="tail 2"),
        ],
        "thread_id": "tid-9",
        "task_goal": "user task",
     }
    out = node(state)
    assert out["context_rebuilt"] is True
    rebuilt = out["messages"]
    assert len(rebuilt) == 3  # summary + tail2（无内联 SystemMessage）
    assert isinstance(rebuilt[0], AIMessage)
    assert "[context rebuilt" in rebuilt[0].content
    assert rebuilt[1].content == "tail 1"
    assert rebuilt[2].content == "tail 2"
    # rebuild 事件
    ev = out["checkpoint_snapshot"][0]
    assert ev["kind"] == "rebuild"
    assert ev["thread_id"] == "tid-9"
"""test_stream_channel.py — attach_stream 事件通道（runner/stream_channel.py）。

覆盖：
- 游标语义：emit 5 条 → cursor=0 读全部/再读空；cursor=2 读 3 条；next_cursor 续读不重不丢
- 文件缺失 → exists=False 空返回
- _meta 注册：check_tool_stream 经 mcp list_tools 可见（_meta 通道）
- attach_stream=true 的 start run：run 结束后通道事件与 execution_trace 对齐、终态结构不变
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

import runner.stream_channel as sc
from runner.agent_mcp_tool import RunAgentArgs, _run_agent_execute
from tools.registry import ToolDef, register_tool
from tools.registry import registry as global_registry


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def streams_dir(tmp_path, monkeypatch):
    """把 STREAMS_DIR 重定向到 tmp（测试不污染 .quantcode/）。"""
    d = tmp_path / "streams"
    monkeypatch.setattr(sc, "STREAMS_DIR", d)
    return d


@pytest.fixture
def clean_registry():
    global_registry._tools.clear()
    yield global_registry
    global_registry._tools.clear()


@pytest.fixture
def tmp_db(tmp_path):
    """checkpoint DB 指向 tmp，避免落 .quantcode/checkpoints.db。"""
    from runner.langgraph_base import clear_checkpointer_cache

    db = tmp_path / "stream-checkpoints.db"
    yield db
    clear_checkpointer_cache()


@pytest.fixture
def run_ids(tmp_path):
    """唯一 run_id 前缀。

    坑：_run_agent_execute 统一走共享 .quantcode/checkpoints.db（不读 ctx注入），
    固定 thread_id 会在重跑时 resume 上次遗留的暂停 checkpoint。带 uuid 后缀
    隔离每次会话。
    """
    import uuid

    return f"attach-{uuid.uuid4().hex[:8]}"


class ScriptedLLM:
    """按调用次数返回预设 AIMessage（test_agent_engine_basic 同款）。"""

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
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"{call_id_prefix}-{i}"}
            for i, (name, args) in enumerate(name_to_args)
        ],
    )


class EchoArgs(BaseModel):
    text: str


def _echo(args: EchoArgs, ctx: dict) -> dict:
    return {"echo": args.text}


# ---------------------------------------------------------------------------
# 游标语义
# ---------------------------------------------------------------------------


def test_cursor_semantics_full_then_empty(streams_dir):
    """emit 5 条 → cursor0 读全部（next_cursor=5）→ 再读空（不重复）。"""
    ch = sc.open_stream("cur-full")
    for i in range(5):
        ch.emit({"seq": i})

    r0 = sc.read_from("cur-full", 0)
    assert r0["exists"] is True
    assert [e["seq"] for e in r0["events"]] == [0, 1, 2, 3, 4]
    assert r0["next_cursor"] == 5

    # 用 next_cursor 再读 → 空、不重复
    r1 = sc.read_from("cur-full", r0["next_cursor"])
    assert r1["events"] == []
    assert r1["next_cursor"] == 5

    # 追加后再读 → 只拿到新事件
    ch.emit({"seq": 5})
    r2 = sc.read_from("cur-full", r1["next_cursor"])
    assert [e["seq"] for e in r2["events"]] == [5]
    assert r2["next_cursor"] == 6


def test_cursor_midway_read(streams_dir):
    """cursor=2 → 从第 3 条读到末尾（3 条），next_cursor=5。"""
    ch = sc.open_stream("cur-mid")
    for i in range(5):
        ch.emit({"seq": i})

    r = sc.read_from("cur-mid", 2)
    assert [e["seq"] for e in r["events"]] == [2, 3, 4]
    assert r["next_cursor"] == 5
    assert r["exists"] is True


def test_read_missing_file_returns_exists_false(streams_dir):
    """文件缺失 → exists=False 空返回（不抛错）。"""
    r = sc.read_from("never-opened", 0)
    assert r == {"events": [], "next_cursor": 0, "exists": False, "has_more": False, "damaged_lines": 0}


@pytest.mark.parametrize("run_id", ["../secret", "/tmp/secret", "nested/path", ""])
def test_run_id_cannot_escape_stream_directory(streams_dir, run_id):
    """stream ids are opaque filenames and cannot read or write outside STREAMS_DIR."""
    with pytest.raises(ValueError):
        sc.open_stream(run_id)
    with pytest.raises(ValueError):
        sc.read_from(run_id, 0)


def test_emit_lines_are_jsonl(streams_dir):
    """文件形态：每行一条合法 JSON（JSONL）。"""
    ch = sc.open_stream("jsonl-form")
    ch.emit({"a": 1})
    ch.emit({"b": "中文"})
    lines = (streams_dir / "jsonl-form.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": "中文"}


def test_open_stream_preserves_existing_file(streams_dir):
    """Reopening after a worker restart must preserve the durable cursor."""
    ch = sc.open_stream("reopen")
    ch.emit({"old": True})
    sc.open_stream("reopen")
    r = sc.read_from("reopen", 0)
    assert r["events"] == [{"old": True}]
    assert r["next_cursor"] == 1


def test_get_or_open_registry_reuses_channel(streams_dir):
    """进程内 registry：同 run_id 复用 → 不会二次清空已 emit 的事件。"""
    ch1 = sc.get_or_open("reg-1")
    ch1.emit({"n": 1})
    ch2 = sc.get_or_open("reg-1")
    assert ch1 is ch2
    r = sc.read_from("reg-1", 0)
    assert [e["n"] for e in r["events"]] == [1]


# ---------------------------------------------------------------------------
# check_tool_stream 注册（_meta 可见）
# ---------------------------------------------------------------------------


def test_check_tool_stream_registered_as_meta(streams_dir, clean_registry):
    """check_tool_stream 已注册且 _meta=True（list_tools 附加 meta tool 通道可见）。

    坑：先行测试会清空全局 registry（clean_registry 语义），import 兜不住 —
    直接重注册 ToolDef（幂等），再断言。
    """
    from tools.stream._register import check_tool_stream_tool

    register_tool(check_tool_stream_tool)
    tool = global_registry.get("check_tool_stream")
    assert getattr(tool, "_meta", False) is True

    # 与 mcp_server.list_tools 的 meta 过滤逻辑一致：_meta tool 会出现在 list_all 里
    meta_ids = [t.id for t in global_registry.list_all() if getattr(t, "_meta", False)]
    assert "check_tool_stream" in meta_ids


def test_check_tool_stream_execute_reads_channel(streams_dir):
    """execute 直调：返回 read_from 结构（events/next_cursor/exists）。"""
    import tools.stream._register as reg_mod

    ch = sc.open_stream("exec-1")
    ch.emit({"x": 1})

    out = reg_mod.check_tool_stream_tool.execute(
        reg_mod.CheckToolStreamArgs(run_id="exec-1", cursor=0), ctx={}
    )
    assert out == {"events": [{"x": 1}], "next_cursor": 1, "exists": True, "has_more": False, "damaged_lines": 0}

    out0 = reg_mod.check_tool_stream_tool.execute(
        reg_mod.CheckToolStreamArgs(run_id="ghost", cursor=0), ctx={}
    )
    assert out0["exists"] is False and out0["events"] == []


# ---------------------------------------------------------------------------
# attach_stream=true 的 start run（端到端，ScriptedLLM 确定性）
# ---------------------------------------------------------------------------


def _register_echo_and_mark_done() -> None:
    """注册确定性工具：echo_tool + 内置 mark_task_done（task_status=done → completed）。

    注意脚本必须先 tool_call 再收尾：若 LLM 直接吐无 tool_calls 的 final 且
    task_status 未 done，llm routing 会 continue → tool 空转 → 连续相同 state
    fingerprint 触发 state_loop → human_gate（test_agent_engine_basic 的 PR #16
    注释同款路由语义），拿不到 completed。
    坑：schema 不能用裸 BaseModel（pydantic 拒事实例化 → tool 报错 → task_status
    永不注入）——直接复用 tools/common 的内置工具。
    """
    from tools.common.mark_task_done import mark_task_done_tool

    register_tool(ToolDef(id="echo_tool", description="echo", schema=EchoArgs, execute=_echo))
    register_tool(mark_task_done_tool)


def _scripted_llm(*steps: AIMessage):
    """按序返回预设 AIMessage，越界重复最后一条。"""

    class _L:
        def __init__(self, seq):
            self._seq = list(seq)
            self._i = 0

        def __call__(self, messages, tools=None):
            r = self._seq[min(self._i, len(self._seq) - 1)]
            self._i += 1
            return r

    return _L(steps)


def _ai_tools(name: str, args: dict, cid: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])


def test_attach_stream_start_run_channel_matches_trace(streams_dir, tmp_db, clean_registry, run_ids):
    """attach_stream=true：run 结束后通道逐行 = execution_trace；终态结构不变。"""
    _register_echo_and_mark_done()

    llm = _scripted_llm(
        _ai_tools("echo_tool", {"text": "hello"}, "s1"),
        _ai_tools("mark_task_done", {}, "s2"),
        AIMessage(content="Task done."),
    )

    # ponytail: max_total_tokens 必传 0 — _run_agent_execute 默认 200k budget，
    # ScriptedLLM 的字符估算消耗会超限触发 budget gate（waiting_for_human）。
    result = _run_agent_execute(
        RunAgentArgs(
            task="echo test",
            group="model",
            thread_id=run_ids,
            attach_stream=True,
            max_total_tokens=0,
        ),
        ctx={"group": "model", "_model": llm, "_checkpoint_db": tmp_db},
    )

    # 终态结构完全不变（向后兼容）
    assert result["status"] == "completed"
    assert result["thread_id"] == run_ids
    assert "execution_trace" in result
    assert len(result["execution_trace"]) >= 5

    # 通道内容与 execution_trace 逐行对齐
    r = sc.read_from(run_ids, 0)
    assert r["exists"] is True
    assert len(r["events"]) == len(result["execution_trace"])
    types = [e["type"] for e in r["events"]]
    assert "agent_start" in types
    assert "tool_call" in types and "tool_result" in types
    assert "agent_end" in types

    # 事件 schema 不变：trace 每条含 thread_id/type/seq（agent_trace.v1）
    ev0 = r["events"][0]
    assert ev0["type"] == "agent_start"
    assert ev0["thread_id"] == run_ids

    # 游标续读：从末尾再读为空
    r2 = sc.read_from(run_ids, r["next_cursor"])
    assert r2["events"] == []


def test_attach_stream_false_writes_no_channel(streams_dir, tmp_db, clean_registry, run_ids):
    """attach_stream=False（默认）：不创建通道文件，行为不变。"""
    _register_echo_and_mark_done()

    llm = _scripted_llm(
        _ai_tools("mark_task_done", {}, "s1"),
        AIMessage(content="done"),
    )
    result = _run_agent_execute(
        RunAgentArgs(task="no attach", group="model", thread_id=f"{run_ids}-na", max_total_tokens=0),
        ctx={"group": "model", "_model": llm, "_checkpoint_db": tmp_db},
    )
    assert result["status"] == "completed"
    assert "execution_trace" in result
    assert sc.stream_exists(f"{run_ids}-na") is False
    r = sc.read_from(f"{run_ids}-na", 0)
    assert r["exists"] is False and r["events"] == []


def test_attach_stream_read_while_events_accumulate(streams_dir, tmp_db, clean_registry, run_ids):
    """中途可读语义：run 产出事件后，旧游标读取仍稳定，新游标拿到增量。

    本测试验证完成后的分段消费语义：
    先模拟"读到一半"的控制器状态（只消费第 1 条），再从
    cursor=1 续读拿到剩余全部事件（不重不丢）。
    """
    _register_echo_and_mark_done()

    llm = _scripted_llm(
        _ai_tools("echo_tool", {"text": "x"}, "s1"),
        _ai_tools("mark_task_done", {}, "s2"),
        AIMessage(content="done"),
    )
    result = _run_agent_execute(
        RunAgentArgs(
            task="echo test",
            group="model",
            thread_id=f"{run_ids}-b",
            attach_stream=True,
            max_total_tokens=0,
        ),
        ctx={"group": "model", "_model": llm, "_checkpoint_db": tmp_db},
    )
    assert result["status"] == "completed"

    # 控制器首轮只消费第 1 条（agent_start）
    first = sc.read_from(f"{run_ids}-b", 0)
    assert first["events"][0]["type"] == "agent_start"
    # 分批拉剩余：从 cursor=1（跳过首条）续读到末尾
    rest = sc.read_from(f"{run_ids}-b", 1)
    consumed = first["events"][:1] + rest["events"]
    assert len(consumed) == len(result["execution_trace"])
    assert [e["type"] for e in consumed][-1] == "agent_end"


# ---------------------------------------------------------------------------
# wait_s 轮询（check_tool_stream 阻塞语义）
# ---------------------------------------------------------------------------


def test_check_tool_stream_wait_s_returns_on_new_events(streams_dir):
    """wait_s>0：事件已在 → 立即返回；无事件 → 超时返回 exists=True 空事件。"""
    import time as _time

    import tools.stream._register as reg_mod

    ch = sc.open_stream("wait-1")
    ch.emit({"x": 1})
    t0 = _time.time()
    out = reg_mod.check_tool_stream_tool.execute(
        reg_mod.CheckToolStreamArgs(run_id="wait-1", cursor=0, wait_s=5), ctx={}
    )
    assert out["events"] == [{"x": 1}]
    assert _time.time() - t0 < 1  # 有新事件不等待

    # cursor 已到末尾 + 无新事件 → wait_s 到期返回（空事件）
    t0 = _time.time()
    out2 = reg_mod.check_tool_stream_tool.execute(
        reg_mod.CheckToolStreamArgs(run_id="wait-1", cursor=1, wait_s=1), ctx={}
    )
    assert out2["events"] == [] and out2["exists"] is True
    assert _time.time() - t0 >= 0.5


def test_partial_append_is_not_consumed(streams_dir):
    channel = sc.open_stream("partial")
    channel.emit({"first": 1})
    with channel.path.open("ab") as output:
        output.write(b'{"second":')
    result = sc.read_from("partial")
    assert result == {"events": [{"first": 1}], "next_cursor": 1, "exists": True, "has_more": False, "damaged_lines": 0}
    with channel.path.open("ab") as output:
        output.write(b'2}\n')
    assert sc.read_from("partial", result["next_cursor"])["events"] == [{"second": 2}]


def test_events_visible_before_model_returns(streams_dir, tmp_db, clean_registry, run_ids):
    _register_echo_and_mark_done()
    called = []

    def model(messages, tools=None):
        events = sc.read_from(run_ids)["events"]
        assert events[0]["type"] == "agent_start"
        assert not any(event["type"] == "agent_end" for event in events)
        called.append(True)
        return _ai_tools("mark_task_done", {}, "live-done")

    result = _run_agent_execute(
        RunAgentArgs(task="inspect", group="model", thread_id=run_ids,
                     attach_stream=True, max_total_tokens=0),
        ctx={"group": "model", "_model": model, "_checkpoint_db": tmp_db},
    )
    assert result["status"] == "completed"
    assert called
    assert sc.read_from(run_ids)["events"] == result["execution_trace"]


def test_stream_survives_fresh_process(streams_dir):
    import subprocess
    import sys

    sc.open_stream("restart").emit({"before": True})
    script = """
import sys
from pathlib import Path
from runner import stream_channel as sc
sc.STREAMS_DIR = Path(sys.argv[1])
sc.get_or_open("restart").emit({"after": True})
"""
    subprocess.run([sys.executable, "-c", script, str(streams_dir)], check=True)
    assert sc.read_from("restart")["events"] == [{"before": True}, {"after": True}]


@pytest.mark.parametrize("field", ["actor_id", "group", "workspace_id", "workspace_path"])
def test_authenticated_stream_requires_owner_scope(streams_dir, monkeypatch, field):
    from types import SimpleNamespace
    import runner.langgraph_base as base
    from tools.stream._register import CheckToolStreamArgs, _check_tool_stream_execute

    ctx = dict(actor_id="owner", group="factor", workspace_id="work",
               workspace_path="/work", role="analyst")
    values = dict(ctx)
    saver = SimpleNamespace(get_tuple=lambda config: SimpleNamespace(
        checkpoint={"channel_values": values}))
    monkeypatch.setattr(base, "get_checkpointer", lambda path: saver)
    sc.open_stream("private").emit({"secret": True})
    args = CheckToolStreamArgs(run_id="private")
    assert _check_tool_stream_execute(args, ctx)["events"] == [{"secret": True}]
    ctx[field] = "another"
    with pytest.raises(PermissionError, match="scope"):
        _check_tool_stream_execute(args, ctx)

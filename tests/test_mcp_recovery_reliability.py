"""F-02 ordinary recovery reliability through the public MCP run_agent seam."""
from __future__ import annotations

import json
import sqlite3
import threading

from langchain_core.messages import AIMessage
import pytest

from quantcode import mcp_server
from runner import agent_engine, agent_mcp_tool, stream_channel
from runner.agent_mcp_tool import run_agent_tool
from runner.langgraph_base import clear_checkpointer_cache, get_checkpointer
from runner.tool_receipts import ToolOutcomeUnknown, execute_once
from tools.common.mark_task_done import mark_task_done_tool
from tools.registry import registry


def _payload(response: dict) -> dict:
    assert response["isError"] is False, response
    return json.loads(response["content"][0]["text"])


class _CrashThenBlockRecoveryModel:
    """First call fails; the first recovery blocks until the test releases it."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()
        self.recovery_entered = threading.Event()
        self.release_recovery = threading.Event()

    def __call__(self, messages, tools=None):  # noqa: ANN001, ANN202
        with self._lock:
            self.calls += 1
            call_no = self.calls
        if call_no == 1:
            raise RuntimeError("simulated model process failure")
        if call_no == 2:
            self.recovery_entered.set()
            if not self.release_recovery.wait(timeout=5):
                raise TimeoutError("test did not release recovery")
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "mark_task_done",
                    "args": {"summary": "recovered once"},
                    "id": "finish-after-recovery",
                }],
            )
        raise AssertionError("a rejected duplicate recovery called the model")


def test_mcp_run_agent_rejects_concurrent_and_completed_duplicate_recovery(
    monkeypatch, tmp_path
):
    checkpoint_db = tmp_path / "checkpoints.db"
    model = _CrashThenBlockRecoveryModel()
    context = {
        "session_id": "creator-session",
        "actor_id": "creator",
        "group": "factor",
        "role": "analyst",
        "workspace_id": "workspace-factor",
        "workspace_path": str(tmp_path / "workspace"),
        "github_subject": "github-creator",
        "resource_scopes": ["reports:write"],
    }
    monkeypatch.setattr(agent_mcp_tool, "_mcp_checkpoint_db", lambda: checkpoint_db)
    monkeypatch.setattr(mcp_server, "_get_mcp_group", lambda: "factor")
    monkeypatch.setattr(mcp_server, "_session_context_for_call", lambda _group: context)
    monkeypatch.setattr(mcp_server, "_get_model", lambda: model)
    monkeypatch.setattr(
        mcp_server,
        "_tools_for_session",
        lambda _group, _role=None: [run_agent_tool, mark_task_done_tool],
    )
    monkeypatch.setitem(registry._tools, "run_agent", run_agent_tool)
    monkeypatch.setitem(registry._tools, "mark_task_done", mark_task_done_tool)
    monkeypatch.setattr(agent_engine, "record_run", lambda **_kwargs: None)
    monkeypatch.setattr(stream_channel, "STREAMS_DIR", tmp_path / "streams")
    monkeypatch.setenv("QUANTCODE_EVIDENCE_DIR", str(tmp_path / "evidence"))

    thread_id = "mcp-ordinary-recovery"
    started = _payload(mcp_server.call_tool("run_agent", {
        "task": "查看状态",
        "thread_id": thread_id,
        "max_total_tokens": 0,
    }))
    assert started["status"] == "error"
    assert "simulated model process failure" in started["error"]

    saver = get_checkpointer(checkpoint_db)
    before = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    assert before is not None
    checkpoint_id = before.config["configurable"]["checkpoint_id"]
    request = {
        "resume": True,
        "thread_id": thread_id,
        "expected_checkpoint_id": checkpoint_id,
        "max_total_tokens": 0,
    }

    admitted: dict = {}

    def recover() -> None:
        admitted.update(_payload(mcp_server.call_tool("run_agent", request)))

    first = threading.Thread(target=recover)
    first.start()
    assert model.recovery_entered.wait(timeout=5), "first recovery did not enter model"
    try:
        concurrent = _payload(mcp_server.call_tool("run_agent", request))
    finally:
        model.release_recovery.set()
        first.join(timeout=5)

    assert not first.is_alive()
    assert admitted["status"] == "completed"
    assert concurrent["status"] == "error"
    assert "RUN_BUSY" in concurrent["error"]

    latest = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    assert latest is not None
    duplicate = _payload(mcp_server.call_tool("run_agent", {
        **request,
        "expected_checkpoint_id": latest.config["configurable"]["checkpoint_id"],
    }))
    assert duplicate["status"] == "error"
    assert "completed task cannot be resumed" in duplicate["error"]
    assert model.calls == 2

    clear_checkpointer_cache()


@pytest.mark.parametrize("receipt_state", ["unknown", "corrupt_completed"])
def test_mcp_run_agent_blocks_unknown_or_corrupt_tool_result_before_execution(
    monkeypatch, tmp_path, receipt_state
):
    checkpoint_db = tmp_path / f"{receipt_state}-checkpoints.db"

    class _FailOnceModel:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, messages, tools=None):  # noqa: ANN001, ANN202
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("create recoverable checkpoint")
            raise AssertionError("unsafe receipt reached model execution")

    model = _FailOnceModel()
    context = {
        "session_id": "creator-session",
        "actor_id": "creator",
        "group": "factor",
        "role": "analyst",
        "workspace_id": "workspace-factor",
        "workspace_path": str(tmp_path / "workspace"),
        "github_subject": "github-creator",
        "resource_scopes": ["reports:write"],
    }
    monkeypatch.setattr(agent_mcp_tool, "_mcp_checkpoint_db", lambda: checkpoint_db)
    monkeypatch.setattr(mcp_server, "_get_mcp_group", lambda: "factor")
    monkeypatch.setattr(mcp_server, "_session_context_for_call", lambda _group: context)
    monkeypatch.setattr(mcp_server, "_get_model", lambda: model)
    monkeypatch.setattr(
        mcp_server,
        "_tools_for_session",
        lambda _group, _role=None: [run_agent_tool, mark_task_done_tool],
    )
    monkeypatch.setitem(registry._tools, "run_agent", run_agent_tool)
    monkeypatch.setitem(registry._tools, "mark_task_done", mark_task_done_tool)
    monkeypatch.setattr(agent_engine, "record_run", lambda **_kwargs: None)
    monkeypatch.setattr(stream_channel, "STREAMS_DIR", tmp_path / "streams")
    monkeypatch.setenv("QUANTCODE_EVIDENCE_DIR", str(tmp_path / "evidence"))

    thread_id = f"mcp-receipt-{receipt_state}"
    started = _payload(mcp_server.call_tool("run_agent", {
        "task": "查看状态",
        "thread_id": thread_id,
        "max_total_tokens": 0,
    }))
    assert started["status"] == "error"

    saver = get_checkpointer(checkpoint_db)
    latest = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    assert latest is not None
    receipt_db = checkpoint_db.with_suffix(".tool-receipts.db")
    call = {"id": "external-call-1", "name": "write_report", "args": {"id": "r1"}}
    receipt_context = {**context, "thread_id": thread_id}
    if receipt_state == "unknown":
        with pytest.raises(ToolOutcomeUnknown):
            execute_once(
                receipt_db,
                call,
                receipt_context,
                lambda: (_ for _ in ()).throw(RuntimeError("lost external result")),
            )
    else:
        execute_once(receipt_db, call, receipt_context, lambda: {"external_id": "r1"})
        with sqlite3.connect(receipt_db) as connection:
            connection.execute(
                "UPDATE tool_receipts SET result=? WHERE thread=? AND call_id=?",
                (b"corrupt-result", thread_id, call["id"]),
            )

    resumed = _payload(mcp_server.call_tool("run_agent", {
        "resume": True,
        "thread_id": thread_id,
        "expected_checkpoint_id": latest.config["configurable"]["checkpoint_id"],
        "max_total_tokens": 0,
    }))

    assert resumed["status"] == "error"
    assert "未确认的工具执行结果" in resumed["error"]
    assert "不能自动恢复" in resumed["error"]
    assert model.calls == 1

    clear_checkpointer_cache()

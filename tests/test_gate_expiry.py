"""F-03 approval expiry tests through the MCP run_agent boundary."""
from __future__ import annotations

from types import SimpleNamespace

from runner import agent_engine, agent_mcp_tool
from runner.agent_mcp_tool import RunAgentArgs, _run_agent_execute


def test_expired_gate_cannot_be_approved_or_resume_execution(monkeypatch, tmp_path):
    gate = {
        "kind": "permission",
        "gate_id": "hg-expired-1",
        "message": "approval required",
        "reasons": ["restricted write"],
        "expires_at": "2000-01-01T00:00:00+00:00",
    }
    latest = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "cp-expired-1"}},
        pending_writes=[("task-1", "__interrupt__", [SimpleNamespace(value=gate)])],
    )

    class _Checkpointer:
        def get_tuple(self, config):
            return latest

    resume_calls: list[tuple[str, str | None]] = []

    class _AgentRunner:
        def __init__(self, **kwargs):
            pass

        def resume(self, *, thread_id, decision, **kwargs):
            resume_calls.append((thread_id, decision))
            return {"messages": [], "thread_id": thread_id, "task_status": "done"}

    monkeypatch.setattr(
        agent_mcp_tool,
        "_mcp_checkpoint_db",
        lambda: tmp_path / "checkpoint.db",
    )
    monkeypatch.setattr(
        "runner.langgraph_base.get_checkpointer",
        lambda database: _Checkpointer(),
    )
    monkeypatch.setattr(agent_engine, "AgentRunner", _AgentRunner)

    result = _run_agent_execute(
        RunAgentArgs(
            thread_id="expired-gate-task",
            decision="approve",
            expected_gate_id="hg-expired-1",
            expected_checkpoint_id="cp-expired-1",
        ),
        ctx={
            "group": "factor",
            "actor_id": "factor-approver",
            "role": "approver",
            "session_id": "review-session",
            "_model": object(),
        },
    )

    assert result["status"] == "error"
    assert "expired" in result["error"].lower()
    assert resume_calls == []


def test_direct_agent_runner_cannot_bypass_expired_gate(monkeypatch, tmp_path):
    gate = {
        "kind": "merge",
        "gate_id": "hg-expired-direct",
        "message": "merge approval required",
        "reasons": ["shared write"],
        "expires_at": "2000-01-01T00:00:00+00:00",
    }

    class _App:
        def get_state(self, config):
            return SimpleNamespace(
                values={
                    "group": "factor",
                    "__interrupt__": [SimpleNamespace(value=gate)],
                },
                interrupts=(SimpleNamespace(value=gate),),
            )

    runner = agent_engine.AgentRunner(
        group="factor",
        model=lambda *args: None,
        checkpoint_db=tmp_path / "checkpoint.db",
    )
    monkeypatch.setattr(runner, "build", lambda **kwargs: _App())
    monkeypatch.setattr(
        runner,
        "stream",
        lambda **kwargs: {"task_status": "done", "messages": []},
    )

    try:
        runner.resume(thread_id="expired-direct-task", decision="approve")
    except PermissionError as exc:
        assert "expired" in str(exc).lower()
    else:
        raise AssertionError("expired Gate reached the direct resume execution path")

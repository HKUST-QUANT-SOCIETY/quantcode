"""F-03 approval decisions stay bound to a live pending HumanGate."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading

import pytest
import yaml

from quantcode.gateway import IdentityGateway, handler
from schemas.session_context import SessionContext
from runner import agent_engine, agent_mcp_tool
from runner.agent_engine import AgentRunner
from runner.agent_mcp_tool import RunAgentArgs, _run_agent_execute
from runner.human_gate import build_interrupt_payload


def _session(*, actor: str, role: str, session_id: str, workspace: Path) -> SessionContext:
    now = datetime.now(timezone.utc)
    return SessionContext(
        session_id=session_id,
        actor_id=actor,
        group="factor",
        role=role,
        workspace_id=f"workspace-{actor}",
        workspace_path=str(workspace / actor),
        github_subject=f"github-{actor}",
        resource_scopes=["reports:write"],
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.fixture
def cross_person_gateway(tmp_path):
    creator = _session(
        actor="creator",
        role="analyst",
        session_id="creator-session",
        workspace=tmp_path,
    )
    reviewer = _session(
        actor="reviewer",
        role="approver",
        session_id="reviewer-session",
        workspace=tmp_path,
    )
    bindings = []
    for fingerprint, context in (
        ("SHA256:creator", creator),
        ("SHA256:reviewer", reviewer),
    ):
        bindings.append({
            "fingerprint": fingerprint,
            "actor_id": context.actor_id,
            "group": context.group,
            "role": context.role,
            "workspace_id": context.workspace_id,
            "workspace_path": context.workspace_path,
            "github_subject": context.github_subject,
            "resource_scopes": context.resource_scopes,
        })
    roster = tmp_path / "roster.yaml"
    roster.write_text(yaml.safe_dump({"bindings": bindings}), encoding="utf-8")
    gateway = IdentityGateway(roster=roster, database=tmp_path / "gateway.db")
    tokens = {"creator": "creator-token", "reviewer": "reviewer-token"}
    with sqlite3.connect(gateway.database) as connection:
        for name, fingerprint, context in (
            ("creator", "SHA256:creator", creator),
            ("reviewer", "SHA256:reviewer", reviewer),
        ):
            connection.execute(
                "INSERT INTO identity_sessions VALUES(?,?,?)",
                (
                    hashlib.sha256(tokens[name].encode()).hexdigest(),
                    fingerprint,
                    context.model_dump_json(),
                ),
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(gateway))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    session_file = tmp_path / "reviewer-session.json"
    session_file.write_text(
        json.dumps({
            "gateway": f"http://127.0.0.1:{server.server_address[1]}",
            "token": tokens["reviewer"],
        }),
        encoding="utf-8",
    )
    session_file.chmod(0o600)
    try:
        yield {
            "gateway": gateway,
            "creator": creator,
            "reviewer": reviewer,
            "tokens": tokens,
            "session_file": session_file,
        }
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_direct_approval_requires_a_pending_gate(monkeypatch, tmp_path):
    class _App:
        def get_state(self, config):
            return SimpleNamespace(
                values={"group": "factor", "task_status": "running"},
                interrupts=(),
                tasks=(),
            )

    runner = AgentRunner(
        group="factor",
        model=lambda *args: None,
        checkpoint_db=tmp_path / "checkpoint.db",
    )
    monkeypatch.setattr(runner, "build", lambda **kwargs: _App())
    monkeypatch.setattr(
        runner,
        "stream",
        lambda **kwargs: pytest.fail("approval without a pending Gate reached execution"),
    )

    with pytest.raises(PermissionError, match="pending HumanGate"):
        runner.resume(thread_id="ordinary-checkpoint", decision="approve")


def test_cross_person_approval_rejects_revoked_creator(
    monkeypatch,
    tmp_path,
    cross_person_gateway,
):
    creator = cross_person_gateway["creator"]
    reviewer = cross_person_gateway["reviewer"]
    gate = build_interrupt_payload(
        gate_id="hg-revoked-creator",
        kind="permission",
        resource="reports:write",
        reasons=["restricted write"],
    )
    saved = {
        **creator.model_dump(mode="json"),
        "__interrupt__": [SimpleNamespace(value=gate)],
    }

    class _App:
        def get_state(self, config):
            return SimpleNamespace(values=saved, interrupts=(), tasks=())

    runner = AgentRunner(
        group="factor",
        model=lambda *args: None,
        checkpoint_db=tmp_path / "checkpoint.db",
        actor_id=reviewer.actor_id,
        role=reviewer.role,
        session_id=reviewer.session_id,
        workspace_id=reviewer.workspace_id,
        workspace_path=reviewer.workspace_path,
        github_subject=reviewer.github_subject,
        resource_scopes=reviewer.resource_scopes,
    )
    monkeypatch.setattr(runner, "build", lambda **kwargs: _App())
    monkeypatch.setattr(
        runner,
        "stream",
        lambda **kwargs: pytest.fail("revoked creator reached execution"),
    )
    monkeypatch.setenv(
        "QUANTCODE_IDENTITY_SESSION_FILE",
        str(cross_person_gateway["session_file"]),
    )
    assert cross_person_gateway["gateway"].validate_checkpoint(
        cross_person_gateway["tokens"]["reviewer"],
        saved,
    ) == {"valid": True}
    cross_person_gateway["gateway"].logout(cross_person_gateway["tokens"]["creator"])

    with pytest.raises(PermissionError, match="creator authorization is no longer valid"):
        runner.resume(thread_id="revoked-creator-task", decision="approve")


def test_cross_person_approval_rejects_creator_removed_from_live_roster(
    monkeypatch,
    tmp_path,
    cross_person_gateway,
):
    creator = cross_person_gateway["creator"]
    reviewer = cross_person_gateway["reviewer"]
    gate = build_interrupt_payload(
        gate_id="hg-roster-revoked-creator",
        kind="permission",
        resource="reports:write",
        reasons=["restricted write"],
    )
    saved = {
        **creator.model_dump(mode="json"),
        "__interrupt__": [SimpleNamespace(value=gate)],
    }

    class _App:
        def get_state(self, config):
            return SimpleNamespace(values=saved, interrupts=(), tasks=())

    runner = AgentRunner(
        group="factor",
        model=lambda *args: None,
        checkpoint_db=tmp_path / "checkpoint.db",
        actor_id=reviewer.actor_id,
        role=reviewer.role,
        session_id=reviewer.session_id,
        workspace_id=reviewer.workspace_id,
        workspace_path=reviewer.workspace_path,
        github_subject=reviewer.github_subject,
        resource_scopes=reviewer.resource_scopes,
    )
    monkeypatch.setattr(runner, "build", lambda **kwargs: _App())
    monkeypatch.setattr(
        runner,
        "stream",
        lambda **kwargs: pytest.fail("roster-revoked creator reached execution"),
    )
    monkeypatch.setenv(
        "QUANTCODE_IDENTITY_SESSION_FILE",
        str(cross_person_gateway["session_file"]),
    )
    assert cross_person_gateway["gateway"].validate_checkpoint(
        cross_person_gateway["tokens"]["reviewer"],
        saved,
    ) == {"valid": True}

    roster_data = yaml.safe_load(
        cross_person_gateway["gateway"].roster.read_text(encoding="utf-8")
    )
    roster_data["bindings"] = [
        item for item in roster_data["bindings"]
        if item["actor_id"] != creator.actor_id
    ]
    cross_person_gateway["gateway"].roster.write_text(
        yaml.safe_dump(roster_data),
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="creator authorization is no longer valid"):
        runner.resume(thread_id="roster-revoked-creator-task", decision="approve")


def test_cross_person_approval_rejects_expired_creator_session(
    monkeypatch,
    tmp_path,
    cross_person_gateway,
):
    creator = cross_person_gateway["creator"]
    reviewer = cross_person_gateway["reviewer"]
    gate = build_interrupt_payload(
        gate_id="hg-expired-creator-session",
        kind="permission",
        resource="reports:write",
        reasons=["restricted write"],
    )
    saved = {
        **creator.model_dump(mode="json"),
        "__interrupt__": [SimpleNamespace(value=gate)],
    }

    class _App:
        def get_state(self, config):
            return SimpleNamespace(values=saved, interrupts=(), tasks=())

    runner = AgentRunner(
        group="factor",
        model=lambda *args: None,
        checkpoint_db=tmp_path / "checkpoint.db",
        actor_id=reviewer.actor_id,
        role=reviewer.role,
        session_id=reviewer.session_id,
        workspace_id=reviewer.workspace_id,
        workspace_path=reviewer.workspace_path,
        github_subject=reviewer.github_subject,
        resource_scopes=reviewer.resource_scopes,
    )
    monkeypatch.setattr(runner, "build", lambda **kwargs: _App())
    monkeypatch.setattr(
        runner,
        "stream",
        lambda **kwargs: pytest.fail("expired creator session reached execution"),
    )
    monkeypatch.setenv(
        "QUANTCODE_IDENTITY_SESSION_FILE",
        str(cross_person_gateway["session_file"]),
    )
    assert cross_person_gateway["gateway"].validate_checkpoint(
        cross_person_gateway["tokens"]["reviewer"],
        saved,
    ) == {"valid": True}
    expired = creator.model_copy(
        update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    with sqlite3.connect(cross_person_gateway["gateway"].database) as connection:
        connection.execute(
            "UPDATE identity_sessions SET context=? WHERE json_extract(context, '$.session_id')=?",
            (expired.model_dump_json(), creator.session_id),
        )

    with pytest.raises(PermissionError, match="creator authorization is no longer valid"):
        runner.resume(thread_id="expired-creator-task", decision="approve")


def test_cross_person_approval_rejects_creator_permission_change(
    monkeypatch,
    tmp_path,
    cross_person_gateway,
):
    creator = cross_person_gateway["creator"]
    reviewer = cross_person_gateway["reviewer"]
    gate = build_interrupt_payload(
        gate_id="hg-revoked-creator-scope",
        kind="permission",
        resource="reports:write",
        reasons=["restricted write"],
    )
    saved = {
        **creator.model_dump(mode="json"),
        "__interrupt__": [SimpleNamespace(value=gate)],
    }

    class _App:
        def get_state(self, config):
            return SimpleNamespace(values=saved, interrupts=(), tasks=())

    runner = AgentRunner(
        group="factor",
        model=lambda *args: None,
        checkpoint_db=tmp_path / "checkpoint.db",
        actor_id=reviewer.actor_id,
        role=reviewer.role,
        session_id=reviewer.session_id,
        workspace_id=reviewer.workspace_id,
        workspace_path=reviewer.workspace_path,
        github_subject=reviewer.github_subject,
        resource_scopes=reviewer.resource_scopes,
    )
    monkeypatch.setattr(runner, "build", lambda **kwargs: _App())
    monkeypatch.setattr(
        runner,
        "stream",
        lambda **kwargs: pytest.fail("revoked creator permission reached execution"),
    )
    monkeypatch.setenv(
        "QUANTCODE_IDENTITY_SESSION_FILE",
        str(cross_person_gateway["session_file"]),
    )
    assert cross_person_gateway["gateway"].validate_checkpoint(
        cross_person_gateway["tokens"]["reviewer"],
        saved,
    ) == {"valid": True}
    roster_data = yaml.safe_load(
        cross_person_gateway["gateway"].roster.read_text(encoding="utf-8")
    )
    creator_entry = next(
        item for item in roster_data["bindings"] if item["actor_id"] == creator.actor_id
    )
    creator_entry["resource_scopes"] = []
    cross_person_gateway["gateway"].roster.write_text(
        yaml.safe_dump(roster_data),
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="creator authorization is no longer valid"):
        runner.resume(thread_id="revoked-creator-scope-task", decision="approve")


@pytest.mark.parametrize(
    ("expected_gate_id", "expected_checkpoint_id", "error"),
    [
        ("hg-stale", "cp-current", "Gate changed or resolved"),
        ("hg-current", "cp-stale", "checkpoint changed"),
    ],
)
def test_mcp_approval_rejects_stale_gate_or_checkpoint(
    monkeypatch,
    tmp_path,
    expected_gate_id,
    expected_checkpoint_id,
    error,
):
    gate = build_interrupt_payload(
        gate_id="hg-current",
        kind="permission",
        resource="reports:write",
        reasons=["restricted write"],
    )
    latest = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "cp-current"}},
        pending_writes=[("task-1", "__interrupt__", [SimpleNamespace(value=gate)])],
    )

    class _Checkpointer:
        def get_tuple(self, config):
            return latest

    resume_calls: list[str] = []

    class _AgentRunner:
        def __init__(self, **kwargs):
            pass

        def resume(self, *, thread_id, **kwargs):
            resume_calls.append(thread_id)
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
            thread_id="stale-approval-task",
            decision="approve",
            expected_gate_id=expected_gate_id,
            expected_checkpoint_id=expected_checkpoint_id,
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
    assert error in result["error"]
    assert resume_calls == []


def test_concurrent_approve_and_reject_admit_only_one_decision(monkeypatch, tmp_path):
    gate = build_interrupt_payload(
        gate_id="hg-race",
        kind="permission",
        resource="reports:write",
        reasons=["restricted write"],
    )
    latest = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "cp-race"}},
        pending_writes=[("task-1", "__interrupt__", [SimpleNamespace(value=gate)])],
    )

    class _Checkpointer:
        def get_tuple(self, config):
            return latest

    entered = threading.Event()
    release = threading.Event()
    decisions: list[str] = []

    class _AgentRunner:
        def __init__(self, **kwargs):
            pass

        def resume(self, *, thread_id, decision, **kwargs):
            decisions.append(decision)
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release the admitted decision")
            return {"messages": [], "thread_id": thread_id, "task_status": "done"}

    checkpoint_db = tmp_path / "checkpoint.db"
    monkeypatch.setattr(agent_mcp_tool, "_mcp_checkpoint_db", lambda: checkpoint_db)
    monkeypatch.setattr(
        "runner.langgraph_base.get_checkpointer",
        lambda database: _Checkpointer(),
    )
    monkeypatch.setattr(agent_engine, "AgentRunner", _AgentRunner)
    context = {
        "group": "factor",
        "actor_id": "factor-approver",
        "role": "approver",
        "session_id": "review-session",
        "_model": object(),
    }

    def decide(decision: str):
        return _run_agent_execute(
            RunAgentArgs(
                thread_id="approval-race-task",
                decision=decision,
                expected_gate_id="hg-race",
                expected_checkpoint_id="cp-race",
            ),
            context,
        )

    approved: dict = {}

    def approve():
        approved.update(decide("approve"))

    first = threading.Thread(target=approve)
    first.start()
    assert entered.wait(timeout=5), "approve did not enter the decision boundary"
    try:
        rejected = decide("reject")
    finally:
        release.set()
        first.join(timeout=5)

    assert not first.is_alive()
    assert approved["status"] == "completed"
    assert rejected["status"] == "error"
    assert "RUN_BUSY" in rejected["error"]
    assert decisions == ["approve"]

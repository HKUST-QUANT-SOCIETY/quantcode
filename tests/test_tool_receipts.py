import sqlite3

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import GraphInterrupt

from runner.receipt_reconciliation import ReconcileReceipt, reconcile
from runner.tool_receipts import ToolOutcomeUnknown, execute_once, receipt_reviews, unresolved_receipts


@pytest.fixture
def operation(tmp_path):
    database = tmp_path / "checkpoints.tool-receipts.db"
    call = {"id": "call-1", "name": "write_report", "args": {"report": "report-1"}}
    context = {"thread_id": "task-1", "actor_id": "writer", "role": "analyst", "group": "factor"}
    return database, call, context


def test_completed_result_replays_without_repeating_side_effect(operation, tmp_path):
    database, call, context = operation
    artifact = tmp_path / "report.txt"

    def execute():
        with artifact.open("a") as output:
            output.write("written\n")
        return {"artifact": str(artifact), "value": 0}

    first = execute_once(database, call, context, execute)
    assert execute_once(database, call, context, execute) == first
    assert artifact.read_text() == "written\n"
    assert unresolved_receipts(database, "task-1") == []


def test_crash_after_side_effect_blocks_replay(operation, tmp_path):
    database, call, context = operation
    artifact = tmp_path / "report.txt"

    def crash():
        artifact.write_text("external operation succeeded")
        raise RuntimeError("lost reply")

    with pytest.raises(ToolOutcomeUnknown):
        execute_once(database, call, context, crash)
    with pytest.raises(ToolOutcomeUnknown):
        execute_once(database, call, context, lambda: artifact.unlink())
    assert artifact.is_file()
    assert unresolved_receipts(database, "task-1")[0]["receipt_status"] == "STARTED"


@pytest.mark.parametrize("change", [{"actor_id": "other"}, {"role": "admin"}, {"resource_scopes": ["extra"]}])
def test_receipt_cannot_replay_under_changed_identity(operation, change):
    database, call, context = operation
    execute_once(database, call, context, lambda: "original")
    with pytest.raises(ToolOutcomeUnknown):
        execute_once(database, call, {**context, **change}, lambda: "replacement")


def test_corrupt_result_is_not_permission_to_retry(operation):
    database, call, context = operation
    execute_once(database, call, context, lambda: "original")
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE tool_receipts SET result=?", (b"not-msgpack",))
    assert unresolved_receipts(database, "task-1")[0]["receipt_status"] == "UNREADABLE_RESULT"
    with pytest.raises(ToolOutcomeUnknown):
        execute_once(database, call, context, lambda: "replacement")


def test_interrupt_before_mutation_preserves_resume(operation):
    database, call, context = operation

    def interrupt():
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        execute_once(database, call, context, interrupt)
    assert unresolved_receipts(database, "task-1") == []
    assert execute_once(database, call, context, lambda: "approved") == "approved"


@pytest.mark.parametrize("decision", ["confirmed_completed", "confirmed_not_executed"])
def test_review_is_audited_and_never_starts_execution(operation, tmp_path, monkeypatch, decision):
    database, call, context = operation
    checkpoint_db = tmp_path / "checkpoints.db"
    kind, payload = JsonPlusSerializer().dumps_typed({"channel_values": context})
    with sqlite3.connect(checkpoint_db) as conn:
        conn.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, type TEXT, checkpoint BLOB)")
        conn.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?)", ("task-1", "", "cp-1", kind, payload))

    def lost():
        raise RuntimeError("unknown external result")

    with pytest.raises(ToolOutcomeUnknown):
        execute_once(database, call, context, lost)
    digest = unresolved_receipts(database, "task-1")[0]["digest"]
    import runner.evidence as evidence
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path / "evidence")
    request = ReconcileReceipt(
        thread_id="task-1", checkpoint_id="cp-1", call_id="call-1", expected_digest=digest,
        decision=decision, evidence_ref="artifact://external-receipt", note="Checked the external operation log",
        **({"result": {"original": True}} if decision == "confirmed_completed" else {}),
    )
    reviewer = {"actor_id": "lead", "role": "approver", "group": "factor", "session_id": "review-session"}
    with pytest.raises(PermissionError):
        reconcile(request, {**reviewer, "group": "model"}, checkpoint_db)
    with pytest.raises(ValueError, match="checkpoint changed"):
        reconcile(request.model_copy(update={"checkpoint_id": "cp-0"}), reviewer, checkpoint_db)
    result = reconcile(request, reviewer, checkpoint_db)
    assert result["execution_started"] is False
    assert receipt_reviews(database, "task-1")[0]["reviewer"] == "lead"
    assert unresolved_receipts(database, "task-1") == []
    executed = []

    def run():
        executed.append(True)
        return {"retried": True}

    replay = execute_once(database, call, context, run)
    assert replay == ({"original": True} if decision == "confirmed_completed" else {"retried": True})
    assert executed == ([] if decision == "confirmed_completed" else [True])

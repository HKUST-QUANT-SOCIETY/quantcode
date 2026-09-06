"""F-02 receipt reconciliation through the real Gateway HTTP endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from http.server import ThreadingHTTPServer
import sqlite3
import threading

import httpx
import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
import yaml

from quantcode.gateway import IdentityGateway, handler
from runner.evidence import verify_chain
from runner.tool_receipts import (
    ToolOutcomeUnknown,
    execute_once,
    receipt_reviews,
    unresolved_receipts,
)
from schemas.session_context import SessionContext


@pytest.mark.parametrize(
    ("decision", "verified_result", "expected", "write_count"),
    [
        (
            "confirmed_completed",
            {"external_id": "already-written"},
            {"external_id": "already-written"},
            0,
        ),
        (
            "confirmed_not_executed",
            None,
            {"external_id": "retried-once"},
            1,
        ),
    ],
)
def test_gateway_receipt_reconciliation_controls_next_execution_end_to_end(
    monkeypatch, tmp_path, decision, verified_result, expected, write_count
):
    now = datetime.now(timezone.utc)
    reviewer = SessionContext(
        session_id="reviewer-session",
        actor_id="reviewer",
        group="factor",
        role="approver",
        workspace_id="workspace-factor",
        workspace_path=str(tmp_path / "workspace"),
        github_subject="github-reviewer",
        resource_scopes=["receipts:review"],
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    roster = tmp_path / "roster.yaml"
    roster.write_text(yaml.safe_dump({"bindings": [{
        "fingerprint": "SHA256:reviewer",
        "actor_id": reviewer.actor_id,
        "group": reviewer.group,
        "role": reviewer.role,
        "workspace_id": reviewer.workspace_id,
        "workspace_path": reviewer.workspace_path,
        "github_subject": reviewer.github_subject,
        "resource_scopes": reviewer.resource_scopes,
    }]}), encoding="utf-8")
    gateway = IdentityGateway(roster=roster, database=tmp_path / "gateway.db")
    token = "reviewer-token"
    with sqlite3.connect(gateway.database) as connection:
        connection.execute(
            "INSERT INTO identity_sessions VALUES(?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                "SHA256:reviewer",
                reviewer.model_dump_json(),
            ),
        )

    checkpoint_db = tmp_path / "checkpoints.db"
    thread_id = f"receipt-review-{decision}"
    checkpoint_id = "cp-review-1"
    creator_context = {
        "thread_id": thread_id,
        "session_id": "creator-session",
        "actor_id": "creator",
        "group": "factor",
        "role": "analyst",
        "workspace_id": "workspace-factor",
        "workspace_path": str(tmp_path / "workspace"),
        "github_subject": "github-creator",
        "resource_scopes": ["reports:write"],
    }
    kind, checkpoint = JsonPlusSerializer().dumps_typed(
        {"channel_values": creator_context}
    )
    with sqlite3.connect(checkpoint_db) as connection:
        connection.execute(
            "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, "
            "checkpoint_id TEXT, type TEXT, checkpoint BLOB)"
        )
        connection.execute(
            "INSERT INTO checkpoints VALUES (?,?,?,?,?)",
            (thread_id, "", checkpoint_id, kind, checkpoint),
        )

    receipt_db = checkpoint_db.with_suffix(".tool-receipts.db")
    call = {
        "id": "external-call-1",
        "name": "write_report",
        "args": {"report": "report-1"},
    }
    if decision == "confirmed_completed":
        execute_once(
            receipt_db,
            call,
            creator_context,
            lambda: {"external_id": "result-lost-from-receipt"},
        )
        with sqlite3.connect(receipt_db) as connection:
            connection.execute(
                "UPDATE tool_receipts SET result=? WHERE thread=? AND call_id=?",
                (b"corrupt-result", thread_id, call["id"]),
            )
    else:
        with pytest.raises(ToolOutcomeUnknown):
            execute_once(
                receipt_db,
                call,
                creator_context,
                lambda: (_ for _ in ()).throw(RuntimeError("external outcome unknown")),
            )
    digest = unresolved_receipts(receipt_db, thread_id)[0]["digest"]

    import runner.evidence as evidence
    import runner.langgraph_base as langgraph_base

    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(evidence, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(langgraph_base, "CHECKPOINTS_DB", checkpoint_db)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(gateway))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        payload = {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "call_id": call["id"],
            "expected_digest": digest,
            "decision": decision,
            "evidence_ref": "artifact://external-system/audit-1",
            "note": "Compared the external system audit record with the call id.",
        }
        if verified_result is not None:
            payload["result"] = verified_result
        with httpx.Client(
            base_url=f"http://127.0.0.1:{server.server_address[1]}",
            timeout=10,
            trust_env=False,
        ) as client:
            response = client.post(
                "/receipts/reconcile",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_started"] is False
    assert body["review"]["status"] == (
        "COMPLETED" if decision == "confirmed_completed" else "RETRY_ALLOWED"
    )
    reviews = receipt_reviews(receipt_db, thread_id)
    assert reviews[0]["reviewer"] == reviewer.actor_id
    assert reviews[0]["evidence_ref"] == payload["evidence_ref"]
    events = verify_chain(thread_id, evidence_dir)
    assert events[-1].payload["receipt_review_intent"]["decision"] == decision

    writes: list[str] = []

    def external_write() -> dict:
        writes.append("write_report")
        return {"external_id": "retried-once"}

    result = execute_once(receipt_db, call, creator_context, external_write)
    assert result == expected
    assert len(writes) == write_count
    assert unresolved_receipts(receipt_db, thread_id) == []

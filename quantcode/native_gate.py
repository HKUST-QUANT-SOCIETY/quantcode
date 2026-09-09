"""Cross-member authorization projection, never a task runner or execution log.

Only the native host may publish requests with its private roster bearer. The
gateway stores exact immutable requests and reviewer decisions; native EventTable
admission, current tool revalidation and component receipts still control execution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING

from schemas.evidence_chain import AuditEvent, canonical_json, make_audit_event, sha256_hex
from schemas.human_gate import HumanGate, HumanGateDecision, HumanGateStatus
from schemas.native_gate import (
    NativeGateCancel, NativeGateDecision, NativeGateList, NativeGatePublish, NativeGateRead,
)
from schemas.session_context import SessionContext

if TYPE_CHECKING:
    from quantcode.gateway import IdentityGateway


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> int:
    return _millis(datetime.now(timezone.utc))


def _millis(value: datetime) -> int:
    return (value - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)


def _connection(gateway: IdentityGateway) -> sqlite3.Connection:
    conn = sqlite3.connect(gateway.database, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS native_gates ("
                 "gate_id TEXT PRIMARY KEY, record_digest TEXT NOT NULL, "
                 "owner_session TEXT NOT NULL, owner_actor TEXT NOT NULL, owner_group TEXT NOT NULL, "
                 "owner_token_hash TEXT NOT NULL, owner_json TEXT NOT NULL, request_json TEXT NOT NULL, "
                 "gate_json TEXT NOT NULL, decision_json TEXT, reviewer_token_hash TEXT, "
                 "reviewer_json TEXT, cancelled_at INTEGER, evidence_json TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS native_gate_owner ON native_gates(owner_session)")
    conn.execute("CREATE INDEX IF NOT EXISTS native_gate_group ON native_gates(owner_group)")
    return conn


def _session(gateway: IdentityGateway, token: str, expected: str) -> SessionContext:
    context = gateway.session(token)
    if context.session_id != expected:
        raise PermissionError("session changed; reconnect before reviewing")
    return context


def _live_owner(gateway: IdentityGateway, row: sqlite3.Row) -> SessionContext:
    context = gateway.session_digest(row["owner_token_hash"])
    if context.model_dump(mode="json") != json.loads(row["owner_json"]):
        raise PermissionError("request creator authorization changed")
    return context


def _authorize(gateway: IdentityGateway, token: str, context: SessionContext, row: sqlite3.Row):
    if context.session_id == row["owner_session"]:
        if _digest(token) != row["owner_token_hash"]:
            raise PermissionError("request creator session mismatch")
        _live_owner(gateway, row)
        return
    # Reuse the existing same-group reviewer / live creator / exact scope check.
    gateway.validate_checkpoint(token, json.loads(row["owner_json"]))


def _record(row: sqlite3.Row) -> tuple[dict, HumanGate, list[AuditEvent]]:
    request = json.loads(row["request_json"])
    owner = json.loads(row["owner_json"])
    if sha256_hex(canonical_json({"owner": owner, "request": request})) != row["record_digest"]:
        raise ValueError("native gate request digest mismatch")
    gate = HumanGate.model_validate_json(row["gate_json"])
    chain = [AuditEvent.model_validate(value) for value in json.loads(row["evidence_json"])]
    previous = None
    for index, event in enumerate(chain, start=1):
        expected = make_audit_event(seq=index, kind=event.kind, payload=event.payload,
                                    prev_hash=previous, at=event.at)
        if expected != event:
            raise ValueError("native gate evidence chain mismatch")
        previous = event.entry_hash
    if not chain or gate.gate_id != row["gate_id"]:
        raise ValueError("native gate evidence is missing")
    if (gate.kind, gate.resource, gate.actor, _millis(gate.expires_at) if gate.expires_at else None) != (
        request["kind"], request["resource"], owner["actor_id"], request["expires_at"]
    ):
        raise ValueError("native gate authorization projection mismatch")
    gate_events = [event for event in chain if event.kind == "human_gate"]
    if not gate_events or gate_events[-1].payload != gate.model_dump(mode="json"):
        raise ValueError("native gate state is not backed by its evidence")
    if row["decision_json"]:
        decision = json.loads(row["decision_json"])
        if gate.decision is None or (
            decision["decision"], decision["reviewer"], decision["note"], decision["record_digest"],
            decision["operation_digest"], decision["receipt_digest"],
        ) != (
            str(gate.decision.action), gate.decision.decided_by, gate.decision.reason, row["record_digest"],
            request["operation_digest"], gate_events[-1].entry_hash,
        ):
            raise ValueError("native gate decision evidence mismatch")
        if gate.status != (HumanGateStatus.APPROVED if decision["decision"] == "approve" else HumanGateStatus.REJECTED):
            raise ValueError("native gate status differs from its decision")
    elif gate.decision is not None or gate.status != HumanGateStatus.PENDING:
        raise ValueError("native gate decision is missing")
    if row["cancelled_at"] is not None and not any(
        event.kind == "output_data" and event.payload.get("event") == "native_gate.cancelled" and
        event.payload.get("gate_id") == row["gate_id"] and event.payload.get("record_digest") == row["record_digest"] and
        event.payload.get("timestamp") == row["cancelled_at"] for event in chain
    ):
        raise ValueError("native gate cancellation evidence is missing")
    return request, gate, chain


def _own_decision(context: SessionContext, row: sqlite3.Row) -> bool:
    if context.role not in {"approver", "admin"} or not row["decision_json"] or not row["reviewer_json"]:
        return False
    reviewer = SessionContext.model_validate_json(row["reviewer_json"])
    decision = json.loads(row["decision_json"])
    if decision.get("reviewer") != reviewer.actor_id or decision.get("reviewer_session_id") != reviewer.session_id:
        raise ValueError("native gate reviewer differs from its recorded decision")
    fields = ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject", "identity_source")
    return all(getattr(context, field) == getattr(reviewer, field) for field in fields) and \
        set(context.resource_scopes) == set(reviewer.resource_scopes) and \
        set(context.authorized_groups or [context.group]) == set(reviewer.authorized_groups or [reviewer.group])


def _view(gateway: IdentityGateway, row: sqlite3.Row, *, historical_receipt: bool = False) -> dict:
    request, gate, _ = _record(row)
    owner_live = True
    try:
        owner = _live_owner(gateway, row)
    except PermissionError:
        if not historical_receipt:
            raise
        owner = SessionContext.model_validate_json(row["owner_json"])
        owner_live = False
    decision = json.loads(row["decision_json"]) if row["decision_json"] else None
    status = "cancelled" if row["cancelled_at"] is not None else (
        "expired" if request["expires_at"] <= _now() else str(gate.status))
    valid = owner_live and status in {"pending", "approved", "rejected"}
    if decision:
        try:
            reviewer = gateway.session_digest(row["reviewer_token_hash"])
            if reviewer.model_dump(mode="json") != json.loads(row["reviewer_json"]):
                raise PermissionError("reviewer authorization changed")
            if reviewer.role not in {"approver", "admin"} or (
                reviewer.role != "admin" and reviewer.group != owner.group
            ):
                raise PermissionError("reviewer no longer authorized")
        except PermissionError:
            valid = False
    return {
        "gate_id": row["gate_id"], "record_digest": row["record_digest"], "request": request,
        "owner": {field: getattr(owner, field) for field in (
            "session_id", "actor_id", "group", "role", "workspace_id", "resource_scopes")},
        "status": status, "valid": valid, "decision": decision,
    }


def publish(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeGatePublish.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    if not _now() < value.expires_at <= min(_now() + 600_000, _millis(context.expires_at)):
        raise ValueError("gate expiry must be within ten minutes and the creator session")
    def invalid_constant(_value: str):
        raise ValueError("non-finite tool arguments are not JSON")

    arguments = json.loads(value.arguments_json, parse_constant=invalid_constant)
    if not isinstance(arguments, dict) or _digest(value.arguments_json) != value.arguments_digest:
        raise ValueError("exact tool argument digest required")
    if not value.description.strip() or not value.resource.strip():
        raise ValueError("gate description and resource are required")
    request = {"version": 1, **value.model_dump(exclude={"expected_session_id"}, exclude_none=True)}
    owner = context.model_dump(mode="json")
    record_digest = sha256_hex(canonical_json({"owner": owner, "request": request}))
    gate_id = sha256_hex(canonical_json([context.session_id, value.session_id, value.request_id]))
    gate = HumanGate(gate_id=gate_id, status=HumanGateStatus.PENDING, kind=value.kind,
                     resource=value.resource, actor=context.actor_id,
                     expires_at=datetime.fromtimestamp(value.expires_at / 1000, timezone.utc),
                     evidence={"engine": "quantcode", "record_digest": record_digest,
                               "operation_digest": value.operation_digest})
    event = make_audit_event(seq=1, kind="human_gate", payload=gate.model_dump(mode="json"))
    conn = _connection(gateway)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM native_gates WHERE gate_id=?", (gate_id,)).fetchone()
            if previous:
                if previous["record_digest"] != record_digest or previous["owner_token_hash"] != _digest(token):
                    raise ValueError("native request id was reused with different content")
            else:
                conn.execute("INSERT INTO native_gates (gate_id,record_digest,owner_session,owner_actor,owner_group,"
                             "owner_token_hash,owner_json,request_json,gate_json,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?)", (
                                 gate_id, record_digest, context.session_id, context.actor_id, context.group,
                                 _digest(token), canonical_json(owner), canonical_json(request), gate.model_dump_json(),
                                 canonical_json([event.model_dump(mode="json")]),
                             ))
        return read(gateway, token, {"expected_session_id": context.session_id, "gate_id": gate_id})
    finally:
        conn.close()


def read(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeGateRead.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    conn = _connection(gateway)
    try:
        row = conn.execute("SELECT * FROM native_gates WHERE gate_id=?", (value.gate_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError("native gate not found")
    # Re-login can inspect the current reviewer's own committed receipt even
    # after its creator left. This read never revives the original authority.
    _record(row)
    historical_receipt = _own_decision(context, row)
    if not historical_receipt:
        _authorize(gateway, token, context, row)
    result = _view(gateway, row, historical_receipt=historical_receipt)
    if context.session_id != row["owner_session"]:
        from runner.admin_scope import audited_read_result
        audited_read_result("native_gate.receipt.read", {**context.model_dump(mode="json"),
                            "evidence_dir": str(gateway.database.parent / "evidence")}, result)
    _session(gateway, token, value.expected_session_id)
    return result


def list_gates(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeGateList.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    if value.cursor and int(value.cursor) >= 2**63:
        raise ValueError("invalid native gate cursor")
    clauses = ["rowid < ?"]
    args: list = [int(value.cursor) if value.cursor else 2**63 - 1]
    if context.role == "approver":
        clauses.append("owner_group = ?")
        args.append(context.group)
    elif context.role != "admin":
        clauses.append("owner_session = ?")
        args.append(context.session_id)
    conn = _connection(gateway)
    try:
        rows = conn.execute("SELECT rowid AS cursor,* FROM native_gates WHERE " + " AND ".join(clauses) +
                            " ORDER BY rowid DESC LIMIT ?", [*args, value.limit + 1]).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows[:value.limit]:
        try:
            _authorize(gateway, token, context, row)
            view = _view(gateway, row)
            if view["valid"] and view["status"] == "pending":
                result.append(view)
        except PermissionError:
            # A stale creator must never turn into an approval candidate.
            continue
    _session(gateway, token, value.expected_session_id)
    return {"gates": result, "next_cursor": str(rows[value.limit - 1]["cursor"]) if len(rows) > value.limit else None}


def decide(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeGateDecision.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    if context.role not in {"approver", "admin"} or not value.note.strip():
        raise PermissionError("authenticated approver and explicit note required")
    # All authority calls precede the write transaction. session_digest may
    # revoke a stale login using its own connection; nesting that write under
    # this SQLite reservation would deadlock. Read/use validates both again.
    view = read(gateway, token, value.model_dump(include={"expected_session_id", "gate_id"}))
    if view["record_digest"] != value.expected_digest or view["request"]["operation_digest"] != value.operation_digest:
        raise ValueError("native gate version changed")
    if context.role != "admin" and context.group != view["owner"]["group"]:
        raise PermissionError("same-group approver required")
    conn = _connection(gateway)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM native_gates WHERE gate_id=?", (value.gate_id,)).fetchone()
            if not row or row["record_digest"] != value.expected_digest:
                raise ValueError("native gate version changed")
            request, gate, chain = _record(row)
            if row["cancelled_at"] is not None or request["expires_at"] <= _now():
                raise ValueError("native gate expired or cancelled")
            if row["decision_json"]:
                previous = json.loads(row["decision_json"])
                if (previous["decision"], previous["reviewer_session_id"], previous["note"]) != (
                    value.decision, context.session_id, value.note.strip()
                ):
                    raise ValueError("native gate already has a different decision")
            else:
                gate.status = HumanGateStatus.APPROVED if value.decision == "approve" else HumanGateStatus.REJECTED
                gate.decision = HumanGateDecision(action=value.decision, decided_by=context.actor_id, reason=value.note.strip())
                event = make_audit_event(seq=len(chain) + 1, kind="human_gate", payload=gate.model_dump(mode="json"),
                                         prev_hash=chain[-1].entry_hash)
                decision = {"decision": value.decision, "reviewer": context.actor_id,
                            "reviewer_session_id": context.session_id, "note": value.note.strip(),
                            "timestamp": _millis(event.at), "operation_digest": value.operation_digest,
                            "record_digest": value.expected_digest, "receipt_digest": event.entry_hash}
                conn.execute("UPDATE native_gates SET gate_json=?,decision_json=?,reviewer_token_hash=?,reviewer_json=?,"
                             "evidence_json=? WHERE gate_id=?", (
                                 gate.model_dump_json(), canonical_json(decision), _digest(token), context.model_dump_json(),
                                 canonical_json([item.model_dump(mode="json") for item in [*chain, event]]), value.gate_id,
                             ))
        return read(gateway, token, {"expected_session_id": context.session_id, "gate_id": value.gate_id})
    finally:
        conn.close()


def cancel(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeGateCancel.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    view = read(gateway, token, value.model_dump(include={"expected_session_id", "gate_id"}))
    if view["record_digest"] != value.expected_digest or view["owner"]["session_id"] != context.session_id:
        raise PermissionError("only the original owner may cancel this exact gate")
    conn = _connection(gateway)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM native_gates WHERE gate_id=?", (value.gate_id,)).fetchone()
            if not row or row["record_digest"] != value.expected_digest or row["owner_token_hash"] != _digest(token):
                raise PermissionError("native gate owner or version changed")
            if row["cancelled_at"] is None:
                _, gate, chain = _record(row)
                if gate.status not in {HumanGateStatus.PENDING, HumanGateStatus.APPROVED}:
                    raise ValueError("rejected gates cannot be cancelled")
                timestamp = _now()
                event = make_audit_event(seq=len(chain) + 1, kind="output_data", payload={
                    "event": "native_gate.cancelled", "gate_id": value.gate_id,
                    "record_digest": value.expected_digest, "actor": context.actor_id,
                    "session_id": context.session_id, "timestamp": timestamp,
                }, prev_hash=chain[-1].entry_hash)
                conn.execute("UPDATE native_gates SET cancelled_at=?,evidence_json=? WHERE gate_id=?", (
                    timestamp, canonical_json([item.model_dump(mode="json") for item in [*chain, event]]), value.gate_id,
                ))
        return read(gateway, token, {"expected_session_id": context.session_id, "gate_id": value.gate_id})
    finally:
        conn.close()

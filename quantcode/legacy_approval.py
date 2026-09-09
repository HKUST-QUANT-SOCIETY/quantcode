"""Exact legacy checkpoint approvals through the existing gateway Gate store."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

import httpx
from quantcode.identity_login import _session_record
from schemas.evidence_chain import canonical_json, sha256_hex
from schemas.native_gate import NativeGatePublish
from schemas.session_context import SessionContext


def _context(record: dict) -> dict:
    # Capture the host schema before loading archived packages. The archived
    # executor may have an older schemas.session_context; it is never the
    # authority for today's gateway identity fields.
    with httpx.Client(base_url=record["gateway"], timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.get("/session", headers={"Authorization": f"Bearer {record['token']}"})
        if response.status_code != 200:
            raise PermissionError("legacy approval session expired or was revoked")
        return SessionContext.model_validate(response.json()).model_dump(mode="json")


def _request(endpoint: str, payload: dict, context: dict, identity_file: Path, *, optional: bool = False) -> dict | None:
    if endpoint not in {"publish", "read"}:
        raise ValueError("unsupported legacy approval operation")
    credential = identity_file.read_bytes()
    record = _session_record(identity_file)
    if _context(record) != context:
        raise PermissionError("legacy approval identity changed")
    with httpx.Client(base_url=record["gateway"], timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.post("/native-gates/" + endpoint, headers={"Authorization": f"Bearer {record['token']}"},
                               json={**payload, "expected_session_id": context["session_id"]})
    if identity_file.read_bytes() != credential or _context(record) != context:
        raise PermissionError("legacy approval identity changed")
    # The existing gateway maps absent keys to 400. Optional preview records
    # no grant in this case; only a full, validated View can admit execution.
    if optional and endpoint == "read" and response.status_code in {400, 404}:
        return None
    if response.status_code != 200:
        raise PermissionError("legacy approval is unavailable, expired or no longer authorized")
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("invalid legacy approval response")
    return result


def approval_request(binding: dict, detail: dict, recovery: dict, context: dict) -> dict:
    gate = detail["gate"]
    solution = None
    if binding["solution"].get("id"):
        from runner.solution_workflow import SolutionStore
        document = SolutionStore(blackboard_db_path=binding["solution"].get("blackboard_db_path")).get(binding["solution"]["id"])
        if document is None:
            raise ValueError("original Gate solution is unavailable")
        solution = {"id": document.id, "version": document.version, "doc_hash": document.doc_hash,
                    "status": str(document.status.value), "file_impact": document.file_impact}
    arguments = {"engine": "legacy-python", "thread_id": binding["thread_id"], "checkpoint_id": binding["checkpoint_id"],
                 "checkpoint_digest": binding["checkpoint_digest"], "owner_digest": binding["owner_digest"],
                 "executor_version": recovery["executor_version"], "provenance_digest": recovery["provenance_digest"],
                 "runtime_digest": recovery["runtime_digest"], "legacy_gate": gate,
                 "pending_tool_calls": binding["pending_tool_calls"], "solution": solution}
    arguments_json = canonical_json(arguments)
    now = int(time.time() * 1000)
    # Stable IDs let a refreshed owner preview read its existing request
    # without a second local approval store. A new expiry window permits a
    # fresh request; expired gateway decisions never carry into that window.
    window = now // 600_000
    request_id = sha256_hex(canonical_json([binding["checkpoint_digest"], recovery["provenance_digest"], gate["gate_id"], window]))
    expires = min((window + 1) * 600_000, int(datetime.fromisoformat(context["expires_at"]).timestamp() * 1000))
    payload = {"expected_session_id": context["session_id"], "request_id": request_id,
               "root_session_id": binding["thread_id"], "session_id": binding["thread_id"],
               "message_id": binding["checkpoint_id"], "call_id": gate["gate_id"], "server": "quantcode-legacy",
               "tool": str(gate.get("resource") or "legacy_checkpoint_resume"), "kind": gate["kind"],
               "resource": str(gate.get("resource") or binding["thread_id"]), "resource_version": binding["checkpoint_id"],
               "operation_digest": sha256_hex(arguments_json), "catalog_digest": recovery["provenance_digest"],
               "arguments_json": arguments_json, "arguments_digest": sha256_hex(arguments_json),
               "description": "恢复原任务中的精确旧操作；实际参数、资源、检查点和执行器摘要见请求内容。",
               "expires_at": expires}
    return NativeGatePublish.model_validate(payload).model_dump(exclude={"expected_session_id"}, exclude_none=True)


def publish_approval(binding: dict, detail: dict, recovery: dict, context: dict, identity_file: Path) -> dict:
    if not recovery["gate_available"]:
        raise PermissionError("legacy checkpoint cannot request approval in its current state")
    request = approval_request(binding, detail, recovery, context)
    result = _request("publish", request, context, identity_file)
    if result is None:
        raise ValueError("legacy approval publication returned no record")
    _matches(result, request, context)
    return result


def preview_approval(binding: dict, detail: dict, recovery: dict, context: dict, identity_file: Path) -> dict | None:
    request = approval_request(binding, detail, recovery, context)
    gate_id = sha256_hex(canonical_json([context["session_id"], binding["thread_id"], request["request_id"]]))
    result = _request("read", {"gate_id": gate_id}, context, identity_file, optional=True)
    if result is not None:
        _matches(result, request, context)
    return result


def _matches(view: dict, request: dict, context: dict) -> None:
    if view.get("owner", {}).get("session_id") != context["session_id"] or \
            any(view.get("request", {}).get(key) != value for key, value in request.items()):
        raise PermissionError("legacy approval does not match this owner and exact operation")


def verified_approval(gate_id: str, binding: dict, detail: dict, recovery: dict, context: dict, identity_file: Path) -> dict:
    request = approval_request(binding, detail, recovery, context)
    result = _request("read", {"gate_id": gate_id}, context, identity_file)
    if result is None:
        raise PermissionError("legacy approval is unavailable")
    _matches(result, request, context)
    decision = result.get("decision")
    if result.get("valid") is not True or result.get("status") not in {"approved", "rejected"} or not isinstance(decision, dict) or \
            decision.get("decision") not in {"approve", "reject"} or not decision.get("reviewer") or \
            decision.get("operation_digest") != request["operation_digest"] or decision.get("record_digest") != result.get("record_digest"):
        raise PermissionError("legacy operation requires a current exact reviewer decision")
    return result

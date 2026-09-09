"""Reconcile-only authority checks; no executor, retry queue or budget grant."""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from quantcode.identity import _load_entries, session_fields
from schemas.evidence_chain import canonical_json, sha256_hex
from schemas.native_review import NativeReviewAuthorize

if TYPE_CHECKING:
    from quantcode.gateway import IdentityGateway


def authorize(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeReviewAuthorize.model_validate(payload)
    context = gateway.session(token)
    if context.session_id != value.expected_session_id:
        raise PermissionError("reviewer session changed")
    owner = value.owner.model_dump(mode="json")
    owner["resource_scopes"] = sorted(set(owner["resource_scopes"]))

    def owner_projection(fields: dict) -> dict:
        return {**{field: fields.get(field) for field in owner if field != "resource_scopes"},
                "resource_scopes": sorted(set(fields.get("resource_scopes") or []))}

    def live_owner() -> None:
        # A task survives login expiry. Check the authoritative roster rather
        # than requiring the original, possibly expired bearer session.
        for entry in _load_entries(gateway.roster):
            if owner["group"] not in (entry.get("groups") or [entry["group"]]):
                continue
            if owner_projection(session_fields(entry, owner["group"])) == owner:
                return
        raise PermissionError("original task owner permissions changed or were revoked")

    live_owner()
    own = owner_projection(context.model_dump(mode="json")) == owner
    privileged = context.role == "admin" or context.role == "approver" and context.group == value.owner.group
    if not privileged and not (value.scope.kind == "read" and own):
        raise PermissionError("same-group approver or admin required for reconciliation")
    if value.scope.kind != "read" and (not value.scope.note.strip() or not value.scope.evidence_ref.strip()):
        raise ValueError("reconciliation evidence and note are required")

    from runner.admin_scope import audited_read_result
    from runner.evidence import append_event

    audit_id = f"native-review-{uuid4().hex}"
    scope = value.scope.model_dump(mode="json")
    # This records authorization to inspect/reconcile, never that the host has
    # applied a decision. Only its existing native event log proves application.
    append_event(audit_id, "tool_result", {
        "tool": "native_review.authorize", "status": "authorized",
        "actor_id": context.actor_id, "session_id": context.session_id,
        "role": context.role, "group": context.group,
        "task_session_id": value.session_id, "root_session_id": value.root_session_id,
        "owner_digest": sha256_hex(canonical_json(owner)), "scope": scope,
    }, gateway.memory_root / ".quantcode" / "evidence", required=True)
    result = {"authorized": True, "authorization_id": audit_id,
              "reviewer_session_id": context.session_id, "reviewer": context.actor_id,
              "session_id": value.session_id, "root_session_id": value.root_session_id}
    if not own:
        audited_read_result("native_review.authorize", {
            **context.model_dump(mode="json"),
            "evidence_dir": str(gateway.memory_root / ".quantcode" / "evidence"),
        }, result)
    if gateway.session(token) != context:
        raise PermissionError("reviewer authorization changed")
    live_owner()
    return result

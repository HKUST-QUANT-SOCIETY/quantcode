"""Admin-only management operations, separate from the Agent Tool Catalog."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from schemas.admin_deploy import AdminDeployRequest, AdminDeployResult, AdminDeployStatus


def submit_deploy(
    request: AdminDeployRequest,
    *,
    session_role: str,
    actor_id: str = "admin",
    evidence_dir: str | Path | None = None,
) -> AdminDeployResult:
    """Submit through the management plane.

    The current repository has no production queue contract, so the honest
    result is STAGING.  No production topology or credential is returned.
    """
    if session_role != "admin":
        raise PermissionError("admin only")
    payload = request.model_dump(mode="json")
    record_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    from runner.evidence import EVIDENCE_DIR, append_event

    append_event(
        f"admin-deploy-{record_hash[:16]}",
        "output_data",
        {"actor_id": actor_id, "artifact_ref": request.artifact_ref,
         "target": request.target, "status": "STAGING", "record_hash": record_hash},
        evidence_dir or EVIDENCE_DIR,
        required=True,
    )
    return AdminDeployResult(
        status=AdminDeployStatus.STAGING,
        artifact_ref=request.artifact_ref,
        record_hash=record_hash,
    )


__all__ = ["submit_deploy"]

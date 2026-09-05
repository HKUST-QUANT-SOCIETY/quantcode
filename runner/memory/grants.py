"""Explicit, revocable project Memory grants; group membership is never a grant."""
from datetime import datetime, timezone
from pathlib import Path
import re

import yaml

from runner.langgraph_base import PROJECT_ROOT


def project_read_grants(ctx: dict, path: Path | None = None) -> list[str]:
    """Require both a roster-issued scope and a current project ACL entry."""
    if not ctx.get("actor_id") or ctx.get("role") not in {"analyst", "approver", "admin"}:
        return []
    path = path or PROJECT_ROOT / "configs" / "project_grants.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("grants"), list):
        raise ValueError("invalid project Memory grant configuration")
    scopes = ctx.get("resource_scopes") or []
    admitted = set()
    now = datetime.now(timezone.utc)
    for grant in data["grants"]:
        if not isinstance(grant, dict):
            raise ValueError("invalid project Memory grant entry")
        project = grant.get("project_id")
        if not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", project):
            raise ValueError("invalid project Memory identifier")
        if grant.get("actor_id") != ctx["actor_id"] or grant.get("enabled") is not True:
            continue
        expiry = datetime.fromisoformat(str(grant.get("expires_at") or "").replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("project grant expiry requires timezone")
        if expiry <= now:
            continue
        if f"memory:project:{project}:read" in scopes:
            admitted.add(project)
    return sorted(admitted)

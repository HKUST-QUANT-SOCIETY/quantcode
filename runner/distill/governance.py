"""Governance for Dream/Distill candidates (P-07).

Candidates are never silently promoted.  A reviewer with an authenticated
``approver`` or ``admin`` role must record one of ``promote``, ``reject`` or
``supersede``.  Promotion only publishes a candidate whose human-edited draft
no longer contains TODO checkboxes, then records an append-only audit event.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from schemas.groups import GROUP_IDS
from typing import Any, Literal

CandidateAction = Literal["promote", "reject", "supersede", "revoke"]
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VALID_GROUPS = frozenset(GROUP_IDS)
_LOCK = threading.Lock()


def _index_path(candidates_dir: str | Path) -> Path:
    return Path(candidates_dir) / "index.json"


def _load_index(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"candidates": []}
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        raise ValueError("invalid candidate index")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _audit(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def review_candidate(
    candidate_name: str,
    action: CandidateAction,
    *,
    reviewer_id: str,
    reviewer_role: str,
    reviewer_group: str | None = None,
    superseded_by: str | None = None,
    candidates_dir: str | Path,
    publish_root: str | Path | None = None,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Publish through a recoverable intent; loaders require committed approval."""
    if reviewer_role not in {"approver", "admin"} or not reviewer_id.strip():
        raise PermissionError("candidate review requires an authenticated reviewer")
    if not _NAME_RE.fullmatch(candidate_name):
        raise ValueError("invalid candidate name")
    if action not in {"promote", "reject", "supersede", "revoke"}:
        raise ValueError("unsupported candidate action")
    root = Path(candidates_dir).resolve()
    index_path = _index_path(root)
    audit_path = root / "review_audit.jsonl"
    from runner.execution_lock import execution_lock

    with _LOCK, execution_lock(index_path, "candidate-governance"):
        index = _load_index(index_path)
        item = next((c for c in index["candidates"] if isinstance(c, dict) and c.get("name") == candidate_name), None)
        if item is None:
            raise KeyError(f"candidate {candidate_name!r} not found")
        group = item.get("group")
        if group not in _VALID_GROUPS:
            raise ValueError("invalid candidate group")
        if reviewer_role != "admin" and reviewer_group != group:
            raise PermissionError("candidate belongs to another group")
        current = item.get("status") or "draft"
        allowed = {"promote": {"draft", "publishing"}, "reject": {"draft"},
                   "supersede": {"draft", "promoted"}, "revoke": {"promoted", "publishing"}}
        if current not in allowed[action]:
            raise ValueError(f"candidate is already {current}")
        if action == "supersede":
            if not superseded_by:
                raise ValueError("superseded_by is required")
            target = next((c for c in index["candidates"] if c.get("name") == superseded_by), None)
            if target and target.get("group") != group:
                raise PermissionError("replacement belongs to another group")
            if not target or target is item:
                raise ValueError("replacement must be a different candidate in the same group")
            if current == "promoted" and target.get("status") != "promoted":
                raise ValueError("a published skill requires a published replacement")
        now = datetime.now(UTC).isoformat()
        event = {"candidate": candidate_name, "action": action, "group": group,
                 "reviewer_id": reviewer_id, "reviewer_role": reviewer_role,
                 "reviewer_group": reviewer_group, "at": now, "superseded_by": superseded_by}
        if action == "promote":
            source = Path(str(item.get("skill_md_path") or "")).resolve()
            if not source.is_relative_to(root):
                raise ValueError("candidate draft must be inside candidates_dir")
            content = source.read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode()).hexdigest()
            if expected_digest and digest != expected_digest:
                raise ValueError("candidate changed since preview; reload before promotion")
            if re.search(r"^- \[ \]", content, flags=re.MULTILINE):
                raise ValueError("candidate draft still contains unfinished review items")
            published = Path(publish_root or root.parent.parent / ".opencode").resolve() / "groups" / group / "skills" / candidate_name / "SKILL.md"
            published_content = re.sub(r"(?m)^(status:\s*)draft\s*$", r"\1accepted", content, count=1)
            published_digest = hashlib.sha256(published_content.encode()).hexdigest()
            if current == "draft":
                if published.exists():
                    raise ValueError("published skill already exists; refusing to overwrite it")
                _audit(audit_path, {**event, "action": "promote_intent", "draft_sha256": digest})
                item.update(status="publishing", published_skill_path=str(published),
                            draft_sha256=digest, published_sha256=published_digest,
                            publication_reviewer=reviewer_id)
                _atomic_write(index_path, index)
            elif item.get("draft_sha256") != digest or item.get("published_skill_path") != str(published):
                raise ValueError("pending publication changed; revoke it before creating a new candidate")
            published.parent.mkdir(parents=True, exist_ok=True)
            marker = published.parent / ".governance.json"
            _atomic_write(marker, {"index_path": str(index_path), "candidate": candidate_name})
            if published.exists():
                if hashlib.sha256(published.read_bytes()).hexdigest() != published_digest:
                    raise ValueError("pending publication content differs; refusing to overwrite")
            else:
                fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=published.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(published_content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    # Atomic, non-overwriting install. A crash leaves either no
                    # Skill or the full Skill; publishing status keeps it inactive.
                    os.link(temporary, published)
                finally:
                    os.unlink(temporary)
        status = {"promote": "promoted", "reject": "rejected", "supersede": "superseded", "revoke": "revoked"}[action]
        # A durable decision precedes the atomic activation/deactivation point.
        _audit(audit_path, {**event, "status": status})
        item.update(status=status, reviewed_at=now, reviewer_id=reviewer_id,
                    reviewer_role=reviewer_role, reviewer_group=reviewer_group)
        if superseded_by:
            item["superseded_by"] = superseded_by
        index["updated_at"] = now
        _atomic_write(index_path, index)
        return dict(item)


def read_governed_skill(path: str | Path) -> str:
    """Read approved content, rejecting pending/revoked/expired/modified skills."""
    path = Path(path).resolve()
    marker = path.parent / ".governance.json"
    content = path.read_text(encoding="utf-8")
    if marker.exists():
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        index_path = Path(metadata["index_path"])
    else:
        # Pre-marker publications must not bypass revocation. Resolve only the
        # canonical adjacent candidate index; ordinary checked-in skills have
        # no matching publication and remain unaffected.
        workspace = next((parent.parent for parent in path.parents if parent.name == ".opencode"), None)
        if workspace is None:
            return content
        index_path = workspace / ".quantcode" / "distill_candidates" / "index.json"
        legacy = _load_index(index_path)
        match = next((item for item in legacy["candidates"]
                      if item.get("published_skill_path") and Path(item["published_skill_path"]).resolve() == path), None)
        if match is None:
            return content
        metadata = {"candidate": match["name"]}
    index = _load_index(index_path)
    item = next((item for item in index["candidates"] if item.get("name") == metadata["candidate"]), None)
    if not item or item.get("status") != "promoted":
        raise PermissionError("skill publication is not active")
    if Path(item.get("published_skill_path", "")).resolve() != path:
        raise PermissionError("skill publication path differs from approval")
    if hashlib.sha256(content.encode()).hexdigest() != item.get("published_sha256"):
        raise PermissionError("published skill changed since approval")
    source = Path(item["skill_md_path"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != item.get("draft_sha256"):
        raise PermissionError("candidate source changed since approval")
    if item.get("expires_at"):
        expiry = datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(UTC):
            raise PermissionError("skill approval expired")
    return content


__all__ = ["CandidateAction", "review_candidate"]


def list_candidates(ctx: dict, *, candidates_dir: str | Path) -> dict:
    role = ctx.get("role")
    if role not in {"approver", "admin"} or not ctx.get("actor_id"):
        raise PermissionError("candidate review requires an authenticated approver or admin")
    root = Path(candidates_dir).resolve()
    index = _load_index(root / "index.json")
    result = []
    for item in index["candidates"]:
        if not isinstance(item, dict):
            raise ValueError("invalid candidate record")
        if role != "admin" and item.get("group") != ctx.get("group"):
            continue
        row = {key: item.get(key) for key in ("name", "group", "status", "reviewed_at", "reviewer_id", "superseded_by")}
        source = Path(str(item.get("skill_md_path") or "")).resolve()
        try:
            source.relative_to(root)
        except ValueError:
            raise ValueError("candidate draft is outside candidate storage")
        if source.is_file():
            content = source.read_text(encoding="utf-8")
            row.update(content=content, digest=hashlib.sha256(content.encode()).hexdigest())
        else:
            row["error"] = "candidate draft file is missing"
        if item.get("status") == "promoted" and item.get("published_skill_path"):
            try:
                read_governed_skill(item["published_skill_path"])
            except (OSError, ValueError, PermissionError) as exc:
                row["error"] = f"Published skill inactive: {exc}"
        result.append(row)
    payload = {"candidates": result}
    if role == "admin":
        from runner.admin_scope import audited_read_result
        return audited_read_result("list_distill_candidates", ctx, payload)
    return payload

"""Governance for Dream/Distill candidates (P-07).

Candidates are never silently promoted.  A reviewer with an authenticated
``approver`` or ``admin`` role must record one of ``promote``, ``reject`` or
``supersede``.  Promotion only publishes a candidate whose human-edited draft
no longer contains TODO checkboxes, then records an append-only audit event.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CandidateAction = Literal["promote", "reject", "supersede"]
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VALID_GROUPS = frozenset({"fundamental", "factor", "model", "risk", "strategy", "options"})
_LOCK = threading.Lock()


def _index_path(candidates_dir: str | Path) -> Path:
    return Path(candidates_dir) / "index.json"


def _load_index(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        return {"candidates": []}
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
) -> dict[str, Any]:
    """Record a candidate decision and optionally publish a reviewed skill.

    ``promote`` is intentionally strict: the candidate must be in ``draft``
    state, belong to the reviewer's group (unless admin), and contain no
    unfinished ``- [ ]`` checklist items.  The published file is copied to the
    canonical group skill directory only after the index and audit decision are
    prepared under the process lock.
    """
    if reviewer_role not in {"approver", "admin"}:
        raise PermissionError("candidate review requires approver or admin role")
    if not reviewer_id.strip():
        raise PermissionError("candidate review requires reviewer_id")
    if not _NAME_RE.fullmatch(candidate_name):
        raise ValueError("invalid candidate name")
    if action not in {"promote", "reject", "supersede"}:
        raise ValueError("unsupported candidate action")
    if action == "supersede" and not superseded_by:
        raise ValueError("supersede requires superseded_by")

    root = Path(candidates_dir)
    index_path = _index_path(root)
    audit_path = root / "review_audit.jsonl"
    with _LOCK:
        index = _load_index(index_path)
        candidates = index["candidates"]
        item = next((c for c in candidates if isinstance(c, dict) and c.get("name") == candidate_name), None)
        if item is None:
            raise KeyError(f"candidate {candidate_name!r} not found")
        group = str(item.get("group") or "").strip()
        if group not in _VALID_GROUPS:
            raise ValueError(f"candidate belongs to invalid group {group!r}")
        if reviewer_role != "admin" and (not reviewer_group or reviewer_group != group):
            raise PermissionError("candidate belongs to another group")
        current = str(item.get("status") or "draft")
        if current != "draft":
            raise ValueError(f"candidate is already {current}")
        if action == "supersede":
            target = next(
                (c for c in candidates if isinstance(c, dict) and c.get("name") == superseded_by),
                None,
            )
            if target is None:
                raise ValueError(f"superseded_by candidate {superseded_by!r} not found")

        source = Path(str(item.get("skill_md_path") or ""))
        if action == "promote":
            if not source.is_file():
                raise FileNotFoundError(f"candidate draft not found: {source}")
            try:
                source.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("candidate draft must remain inside candidates_dir") from exc
            content = source.read_text(encoding="utf-8")
            if re.search(r"^- \[ \]", content, flags=re.MULTILINE):
                raise ValueError("candidate draft still contains unfinished review items")
            if publish_root is None:
                publish_root = root.parent.parent / ".opencode"
            # The draft remains an immutable review artifact.  The canonical
            # published skill must not retain ``status: draft`` in its
            # frontmatter, otherwise loaders and humans cannot distinguish a
            # reviewed capability from a pending candidate.
            published_content = re.sub(
                r"(?m)^(status:\s*)draft\s*$",
                r"\1accepted",
                content,
                count=1,
            )
            published = Path(publish_root) / "groups" / group / "skills" / candidate_name / "SKILL.md"
            published.parent.mkdir(parents=True, exist_ok=True)
            published.write_text(published_content, encoding="utf-8")
            item["published_skill_path"] = published.as_posix()

        now = datetime.now(UTC).isoformat()
        item["status"] = {"promote": "promoted", "reject": "rejected", "supersede": "superseded"}[action]
        item["reviewed_at"] = now
        item["reviewer_id"] = reviewer_id
        item["reviewer_role"] = reviewer_role
        if reviewer_group:
            item["reviewer_group"] = reviewer_group
        if superseded_by:
            item["superseded_by"] = superseded_by
        index["updated_at"] = now
        _atomic_write(index_path, index)
        _audit(audit_path, {
            "candidate": candidate_name,
            "action": action,
            "status": item["status"],
            "group": group,
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "reviewer_group": reviewer_group,
            "superseded_by": superseded_by,
            "at": now,
        })
        return dict(item)


__all__ = ["CandidateAction", "review_candidate"]

"""Native successful tool names -> existing deterministic Distill draft store.

No model, prompt, tool arguments, results or filesystem source paths are
accepted. Dedicated list/review actions use the existing governance queue and
an exact preview digest; they are not model tools. The fixed host invocation
supplies a gateway login; group and owner come from that live identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt
from quantcode.identity_login import _session_record, read_session_file
from runner.distill.governance import (
    candidate_publish_root, candidate_storage, list_candidates, review_candidate, _load_index,
)
from runner.dream_consumer import distill_new_runs

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: Identifier
    tool: Identifier


class DistillInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Identifier
    session_id: Identifier
    root_session_id: Identifier
    source_revision: StrictInt = Field(ge=0, le=9_007_199_254_740_991)
    tools: list[ToolCall] = Field(max_length=2000)


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_name: Identifier
    action: Literal["promote", "reject", "supersede", "revoke"]
    superseded_by: Identifier | None = None
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def handle(action: str, expected_login: str, payload: dict) -> dict:
    if os.environ.get("OPENCODE_CHANNEL") != "quantcode" or os.environ.get("QUANTCODE_UNIFIED_RUNTIME") != "1":
        raise PermissionError("native knowledge adapter is disabled")
    models = {"distill": DistillInput, "list": ListInput, "review": ReviewInput}
    if action not in models:
        raise ValueError("unsupported native knowledge action")
    value = models[action].model_validate(payload)
    if isinstance(value, DistillInput) and len({item.call_id for item in value.tools}) != len(value.tools):
        raise ValueError("duplicate native tool call id")
    session = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    if not session.is_absolute() or session.resolve() != session:
        raise PermissionError("native knowledge requires a canonical private identity file")
    credential = _session_record(session)
    context = read_session_file(session)
    if context["session_id"] != expected_login or context["identity_source"] != "ssh_roster":
        raise PermissionError("native knowledge login changed")
    if datetime.fromisoformat(context["expires_at"].replace("Z", "+00:00")) <= datetime.now(UTC):
        raise PermissionError("native knowledge login expired")
    if context.get("authorized_groups") and context["group"] not in context["authorized_groups"]:
        raise PermissionError("native knowledge group is no longer authorized")
    owner = {field: context.get(field) for field in (
        "actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject",
    )}
    owner["resource_scopes"] = sorted(set(context.get("resource_scopes") or []))
    root = candidate_storage()

    def revalidate() -> None:
        if session.resolve() != session or _session_record(session) != credential or read_session_file(session) != context or _session_record(session) != credential:
            raise PermissionError("native knowledge identity changed")
        if candidate_storage() != root:
            raise PermissionError("native knowledge store changed")

    if action == "list":
        revalidate()
        result = list_candidates(context, candidates_dir=root)
        revalidate()
        return result
    if isinstance(value, ReviewInput):
        revalidate()
        item = review_candidate(
            value.candidate_name, value.action,
            reviewer_id=context["actor_id"], reviewer_role=context["role"], reviewer_group=context["group"],
            candidates_dir=root, publish_root=candidate_publish_root() if value.action == "promote" else None,
            expected_digest=value.expected_digest, superseded_by=value.superseded_by,
            before_commit=revalidate,
        )
        revalidate()
        return {"ok": True, "candidate": {key: item.get(key) for key in (
            "name", "group", "status", "reviewed_at", "reviewer_id", "superseded_by",
        )}}
    if not isinstance(value, DistillInput):
        raise ValueError("unsupported native knowledge payload")

    source = {**value.model_dump(mode="json"), "owner": owner}
    # Candidate events add native event revisions without adding a tool call.
    # Do not re-ingest the same actual sequence because of that projection.
    source["input_digest"] = _digest({key: item for key, item in source.items() if key != "source_revision"})
    run_id = "native-" + _digest([value.source_id, value.session_id])
    records = [{"thread_id": run_id, "group": context["group"],
                "action": {"tool_name": item.tool, "tool_args": {}},
                "observation": {"success": True, "summary": ""}} for item in value.tools]
    revalidate()
    distill_new_runs(
        [{"run_id": run_id, "_records": records}], candidates_dir=root,
        native_source=source, before_commit=revalidate,
    )
    index = _load_index(root / "index.json")
    cursor_key = hashlib.sha256(json.dumps([value.source_id, value.session_id], separators=(",", ":")).encode()).hexdigest()
    stored = index["native_sources"][cursor_key]
    if stored["owner"] != owner or stored["input_digest"] != source["input_digest"]:
        raise PermissionError("native knowledge source changed before disclosure")
    candidates = []
    for item in index["candidates"]:
        if item.get("name") not in stored["candidate_names"]:
            continue
        path = Path(item["skill_md_path"])
        if not path.is_absolute() or path.resolve() != path or path.parent != root or not path.is_file():
            raise PermissionError("native candidate draft is outside host storage")
        candidates.append({"name": item["name"], "group": item["group"], "status": item.get("status") or "draft",
                           "digest": hashlib.sha256(path.read_bytes()).hexdigest(), "tool_sequence": item["tool_sequence"]})
    revalidate()
    return {"source_id": value.source_id, "session_id": value.session_id,
            "source_revision": stored["source_revision"], "input_digest": stored["input_digest"],
            "observed_at": stored["observed_at"], "candidates": candidates}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["distill", "list", "review"], required=True)
    parser.add_argument("--login", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("native knowledge payload too large")
        result = handle(args.action, args.login, json.loads(raw))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # Validation messages can contain input fields; only expose a class.
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

"""Host adapter for native-session SolutionDocs; no model or Agent loop.

The native HTTP/tool boundary authenticates session ownership before invoking
this fixed program. Gateway identity is rechecked here. Documents use the
existing SolutionStore/Blackboard schema in host-private, owner/task-scoped
storage. Only the UI route may select the review action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

from pydantic import BaseModel, ConfigDict, Field
from quantcode.identity_login import read_session_file
from runner.execution_lock import execution_lock
from runner.solution_workflow import (
    SolutionStore, SolutionWorkflowError, compute_doc_hash, review_solution, start_solution,
)
from runner.task_classifier import classify_task
from schemas.solution_doc import SolutionStatus


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=100_000)
    file_count: int = Field(default=0, ge=0)
    cross_repo: bool = False
    shared_write: bool = False


class ProposalInput(TaskInput):
    goal: str = Field(min_length=1, max_length=100_000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=200)
    file_impact: list[str] = Field(default_factory=list, max_length=500)
    expected_hash: str | None = None
    expected_version: int | None = None


class ReviewInput(TaskInput):
    expected_hash: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    decision: str
    note: str = Field(min_length=1, max_length=10000)


def file_path(value: str) -> str:
    item = PurePosixPath(value)
    if not value.strip() or "\\" in value or ":" in value or "\x00" in value or item.is_absolute() or ".." in item.parts:
        raise ValueError("file impact must name workspace-relative files")
    if any(char in value for char in "*?[]") or item.as_posix() == ".":
        raise ValueError("file impact cannot be a wildcard or entire directory")
    if any(part in {".git", ".quantcode", ".ssh"} for part in item.parts):
        raise PermissionError("control and credential paths are outside ordinary solution edits")
    return item.as_posix()


def owner_key(context: dict) -> str:
    fields = ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject")
    owner = {key: context.get(key) for key in fields}
    owner["resource_scopes"] = sorted(context.get("resource_scopes") or [])
    return hashlib.sha256(json.dumps(owner, sort_keys=True).encode()).hexdigest()


def handle(action: str, native_session: str, expected_login: str, payload: dict) -> dict:
    if not re.fullmatch(r"ses[a-zA-Z0-9_-]{1,125}", native_session):
        raise ValueError("invalid native session")
    identity_file = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    context = read_session_file(identity_file)
    if context["session_id"] != expected_login:
        raise PermissionError("identity changed; reconnect")
    root = Path(os.environ["QUANTCODE_SERVICE_STATE_DIR"])
    if not root.is_absolute():
        raise ValueError("host service state root must be absolute")
    directory = root / "solutions" / owner_key(context) / native_session
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.resolve() != directory or directory.stat().st_mode & 0o077:
        raise PermissionError("solution state must be private and cannot be symlinked")
    store = SolutionStore(blackboard_db_path=directory / "blackboard.db", artifacts_dir=directory / "artifacts")
    data = (ProposalInput if action == "propose" else ReviewInput if action == "review" else TaskInput).model_validate(payload)
    classification = classify_task(data.task, file_count=data.file_count, cross_repo=data.cross_repo, shared_write=data.shared_write)
    # New user intent gets a new document binding. An earlier frozen plan must
    # not authorize a later, expanded request just because the session ID matches.
    doc_id = "native-" + hashlib.sha256(data.task.encode()).hexdigest()[:40]
    # UI polling and tool admission can read the same plan concurrently.
    # Reads wait briefly for a consistent snapshot; competing writes still fail.
    with execution_lock(directory / "blackboard.db", doc_id, wait_seconds=5 if action == "status" else 0):
        current = store.get(doc_id)
        if action == "propose":
            assert isinstance(data, ProposalInput)
            files = list(dict.fromkeys(file_path(value) for value in data.file_impact))
            if current is None:
                if data.expected_hash is not None or data.expected_version is not None:
                    raise SolutionWorkflowError("方案已不存在，请重新加载")
                current = start_solution(data.goal, doc_id=doc_id, acceptance_criteria=data.acceptance_criteria,
                                         file_impact=files, store=store)
            else:
                if data.expected_hash != current.doc_hash or data.expected_version != current.version:
                    raise SolutionWorkflowError("方案已变化，请重新加载后修改")
                revised = current.model_copy(update={"goal": data.goal, "acceptance_criteria": data.acceptance_criteria,
                    "file_impact": files, "status": SolutionStatus.DRAFT, "trivial_exempt": False,
                    "needs_human": False, "version": current.version + 1})
                revised = revised.model_copy(update={"doc_hash": compute_doc_hash(revised)})
                current = store.save(revised)
        elif action == "review":
            assert isinstance(data, ReviewInput)
            current = review_solution(doc_id, expected_hash=data.expected_hash, expected_version=data.expected_version,
                reviewer=context["actor_id"], decision=data.decision, note=data.note,
                store=store, evidence_dir=directory / "evidence")
        elif action != "status":
            raise ValueError("unsupported solution operation")
        after = read_session_file(identity_file)
        if after["session_id"] != expected_login or owner_key(after) != owner_key(context):
            raise PermissionError("identity changed while accessing the solution")
        return {"engine": "quantcode", "session_id": native_session,
                "classification": classification.model_dump(mode="json"),
                "solution": current.model_dump(mode="json") if current else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["status", "propose", "review"], required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--login", required=True)
    args = parser.parse_args()
    try:
        result = handle(args.action, args.session, args.login, json.load(sys.stdin))
    except (ValueError, PermissionError, SolutionWorkflowError) as error:
        result = {"error": str(error)}
    except Exception:
        result = {"error": "组织方案服务暂不可用，请检查宿主配置。"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

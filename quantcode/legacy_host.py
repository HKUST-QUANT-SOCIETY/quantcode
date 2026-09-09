"""Legacy checkpoint queries, exact-source recovery and provenance enrollment.

HTTP callers select list/detail/resume only and cannot supply a new task,
execution source, database, model endpoint or key. Recovery exchanges framed
model requests with the host Provider, retaining the original Python graph.
Provenance enrollment is a separate host-terminal command, never an HTTP tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from quantcode.identity_login import read_session_file
from runner.execution_lock import execution_lock
from runner.run_history import get_history, list_history, legacy_checkpoint_binding
from runner.langgraph_base import CHECKPOINTS_DB
from quantcode.legacy_contract import RuntimeDefinition


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: StrictInt = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1024)
    organization: bool = False
    reports_only: bool = False
    group_filter: str | None = None


class DetailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    checkpoint_id: str | None = Field(default=None, max_length=128)
    trace_cursor: StrictInt = Field(default=0, ge=0)
    organization: bool = False


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    checkpoint_id: str = Field(min_length=1, max_length=128)
    checkpoint_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    executor_version: str = Field(min_length=1, max_length=128)
    provenance_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: str | None = Field(default=None, pattern=r"^(approve|reject)$")
    expected_gate_id: str | None = Field(default=None, min_length=1, max_length=256)
    approval_gate_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RequestApprovalInput(ResumeInput):
    expected_gate_id: str = Field(min_length=1, max_length=256)


class Enrollment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    checkpoint_id: str = Field(min_length=1, max_length=128)
    checkpoint_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    executor_version: str = Field(min_length=1, max_length=128)
    owner_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_root: str
    source_files: dict[str, str] = Field(min_length=1, max_length=5000)
    dependencies: dict[str, str] = Field(min_length=1, max_length=1000)
    python_version: str = Field(min_length=1, max_length=100)
    runtime: RuntimeDefinition
    note: str = Field(min_length=1, max_length=10000)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _private(path: Path, *, missing: bool = False) -> bytes | None:
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise PermissionError("legacy service requires canonical host-private files")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        if missing:
            return None
        raise
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if os.name != "posix" or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 8_000_000:
            raise PermissionError("legacy service file must be private and owned by the host account")
        raw = file.read(8_000_001)
        after = os.fstat(file.fileno())
        linked = path.lstat()
        if linked.st_ino != info.st_ino or linked.st_dev != info.st_dev or linked.st_mtime_ns != after.st_mtime_ns or \
                info.st_mtime_ns != after.st_mtime_ns or info.st_ctime_ns != after.st_ctime_ns or info.st_size != after.st_size or len(raw) > 8_000_000:
            raise PermissionError("legacy service file changed during read")
        return raw


def _manifest() -> Path:
    return Path(os.environ.get("QUANTCODE_LEGACY_PROVENANCE_FILE", str(CHECKPOINTS_DB.parent / "legacy-provenance.json")))


def _database() -> Path:
    path = Path(os.environ.get("QUANTCODE_LEGACY_CHECKPOINTS_DB", str(CHECKPOINTS_DB)))
    if not path.is_absolute() or path.is_symlink() or path.parent.resolve() != path.parent:
        raise PermissionError("legacy checkpoint store must be a canonical host path")
    if path.exists():
        info = path.stat()
        if os.name != "posix" or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise PermissionError("legacy checkpoint store must be owned by the host account")
    return path


def _sources(entry: dict) -> None:
    root = Path(entry["source_root"])
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("archived executor source root is unavailable")
    required = {"runner/agent_engine.py", "runner/agent_nodes.py", "runner/agent_mcp_tool.py", "runner/langgraph_base.py",
                "runner/permission_engine.py", "runner/tool_receipts.py", "runner/human_gate.py", "tools/registry.py",
                "runner/metrics.py", "runner/evidence.py", "runner/blackboard.py", "runner/solution_workflow.py",
                "runner/stream_channel.py", "tools/loop_detector.py", "quantcode/mcp_server.py", "configs/permissions.yaml"}
    if not required <= set(entry["source_files"]):
        raise ValueError("executor provenance must include the runner, state, checkpoint, permission and receipt sources")
    for relative, digest in entry["source_files"].items():
        parts = relative.split("/")
        if not relative or "\\" in relative or any(part in {"", ".", ".."} for part in parts) or Path(relative).is_absolute() or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid archived executor source declaration")
        source = root / relative
        if not source.resolve().is_relative_to(root) or source.is_symlink() or _digest(source.read_bytes()) != digest:
            raise ValueError("archived executor source changed")


def _dependencies(entry: dict) -> None:
    import importlib.metadata
    import platform
    required = {"langgraph", "langgraph-checkpoint", "langgraph-checkpoint-sqlite", "langchain-core", "pydantic"}
    dependencies = entry.get("dependencies", {})
    if entry.get("python_version") != platform.python_version() or not required <= set(dependencies):
        raise ValueError("archived executor Python/dependency versions have not been registered for this host")
    for name, version in dependencies.items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise ValueError("archived executor dependency is not installed") from error
        if installed != version:
            raise ValueError("archived executor dependency version changed")


def _entry(binding: dict) -> tuple[dict | None, str]:
    raw = _private(_manifest(), missing=True)
    if raw is None:
        return None, "missing"
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or set(manifest) != {"version", "entries"} or manifest["version"] != 1 or not isinstance(manifest["entries"], list):
        raise ValueError("invalid legacy provenance registry")
    entries = [entry for entry in manifest["entries"] if entry.get("thread_id") == binding["thread_id"] and entry.get("checkpoint_id") == binding["checkpoint_id"]]
    if not entries:
        return None, "missing"
    if len(entries) != 1:
        raise ValueError("duplicate legacy provenance registration")
    entry = entries[0]
    if entry.get("checkpoint_digest") != binding["checkpoint_digest"] or entry.get("owner_digest") != binding["owner_digest"]:
        return entry, "changed"
    try:
        _sources(entry)
    except (OSError, ValueError, KeyError):
        return entry, "changed"
    return entry, "registered"


def _recovery(binding: dict, detail: dict, context: dict, decision: str | None = None) -> dict:
    try:
        entry, provenance = _entry(binding)
    except (OSError, ValueError, KeyError, PermissionError, TypeError):
        entry, provenance = None, "changed"
    blockers = []
    if binding["checkpoint_id"] != binding["latest_checkpoint_id"]:
        blockers.append({"code": "historical_checkpoint", "message": "所选检查点不是当前最新版本，只能查看。"})
    if not binding["owned"]:
        blockers.append({"code": "different_owner", "message": "Admin 可审阅此记录，恢复仍需原任务归属授权。"})
    if provenance != "registered":
        blockers.append({"code": "executor_provenance_" + provenance, "message": "旧记录缺少匹配的执行器来源登记，不能猜测代码版本后重跑。"})
    # The current gateway authenticates the SSH key. Like native Owner, task
    # ownership survives relogin; the original session ID remains audit data.
    owner = binding["owner"]
    if not binding["owner_complete"]:
        blockers.append({"code": "original_owner_incomplete", "message": "旧检查点缺少完整任务归属字段，不能猜补身份后恢复。"})
    elif any(owner.get(field) != context.get(field) for field in ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject")) or \
            set(owner["resource_scopes"]) != set(context["resource_scopes"]):
        blockers.append({"code": "original_owner_changed", "message": "原任务归属或资源授权与当前网关身份不一致，不能恢复。"})
    if entry:
        try:
            _dependencies(entry)
            if Path(entry["source_root"]).is_relative_to(Path(context["workspace_path"]).resolve()):
                raise ValueError("archived source is writable by the task")
            if f".opencode/groups/{context['group']}/tool_allowlist.yaml" not in entry["source_files"]:
                raise ValueError("group tool policy is not part of the registered archive")
        except Exception:
            blockers.append({"code": "executor_host_incompatible", "message": "归档执行器的依赖版本未登记或与宿主不符，或源码仍位于任务可写目录。"})
        try:
            RuntimeDefinition.model_validate(entry.get("runtime"))
        except ValueError:
            blockers.append({"code": "executor_runtime_missing", "message": "旧执行器缺少有效的原始构造参数、图拓扑或待执行节点登记，不能用当前默认值猜测恢复。"})
    from quantcode.legacy_usage import usage_state
    try:
        usage = usage_state(_database(), binding["thread_id"], binding["owner_digest"])
        if usage["unconfirmed_requests"]:
            blockers.append({"code": "model_usage_unknown", "message": "旧任务存在未结算模型请求，需核实原请求用量后恢复。"})
    except Exception:
        usage = None
        blockers.append({"code": "model_usage_unreadable", "message": "旧任务用量账本不可读，不能重新发起模型请求。"})
    # Both the preview and decision admission use these same host conditions.
    # A pending Gate never makes ordinary continuation approve it implicitly.
    gate = detail.get("gate")
    gate_available = bool(not blockers and detail.get("pending_approval") and isinstance(gate, dict) and gate.get("gate_id")
                          and detail.get("status") != "completed"
                          and not detail.get("unresolved_operations") and not detail.get("receipt_review_error")
                          and not detail.get("recovery_block_reason"))
    if not detail.get("can_resume") and not (decision and gate_available):
        blockers.append({"code": "legacy_recovery_guard", "message": detail.get("recovery_block_reason") or "原检查点已完成、待审批或不满足当前身份和恢复条件。"})
    return {"available": not blockers, "gate_available": gate_available, "provenance": provenance, "checkpoint_digest": binding["checkpoint_digest"],
            "owner_digest": binding["owner_digest"], "latest_checkpoint_id": binding["latest_checkpoint_id"],
            "serializer_version": binding["serializer_version"], "executor_version": entry.get("executor_version") if entry else None,
            "runtime_digest": _digest(json.dumps(entry["runtime"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()) if entry and entry.get("runtime") else None,
            "provenance_digest": _digest(json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()) if entry else None,
            "blockers": blockers, "usage": usage}


def handle(action: str, expected_login: str, payload: dict) -> dict:
    session = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    private = _private(session)
    context = read_session_file(session)
    if context["session_id"] != expected_login:
        raise PermissionError("legacy history identity changed")
    database = _database()
    if action == "list":
        value = ListInput.model_validate(payload)
        result = list_history(context, db_path=database, **value.model_dump())
        result["runs"] = [{**run, "engine": "legacy-python", "read_only": True} for run in result["runs"]]
        result["engine"] = "legacy-python"
    elif action in {"detail", "resume", "request-approval"}:
        value = ({"resume": ResumeInput, "request-approval": RequestApprovalInput}.get(action, DetailInput)).model_validate(payload)
        if isinstance(value, ResumeInput) and value.decision is not None:
            raise PermissionError("legacy recovery cannot accept a client decision; submit the exact operation to the reviewer queue")
        if action == "request-approval" and value.approval_gate_id is not None:
            raise ValueError("approval publication cannot consume a decision")
        organization = value.organization if isinstance(value, DetailInput) else False
        binding = legacy_checkpoint_binding(context, thread_id=value.thread_id, checkpoint_id=value.checkpoint_id,
                                            db_path=database, organization=organization)
        result = get_history(context, thread_id=value.thread_id, checkpoint_id=binding["checkpoint_id"],
                             trace_cursor=value.trace_cursor if isinstance(value, DetailInput) else 0,
                             db_path=database, organization=organization)
        after = legacy_checkpoint_binding(context, thread_id=value.thread_id, checkpoint_id=binding["checkpoint_id"],
                                          db_path=database, organization=organization)
        if after != binding:
            raise ValueError("legacy checkpoint changed during preview; reload history")
        recovery = _recovery(binding, result, context, "approved-record" if isinstance(value, ResumeInput) and value.approval_gate_id else None)
        if action in {"resume", "request-approval"}:
            if value.checkpoint_digest != binding["checkpoint_digest"] or value.executor_version != recovery["executor_version"] or value.provenance_digest != recovery["provenance_digest"]:
                raise ValueError("legacy recovery preview changed; reload the exact checkpoint and executor registration")
            if value.expected_gate_id is not None and value.expected_gate_id != (result.get("gate") or {}).get("gate_id"):
                raise ValueError("legacy Gate changed before recovery")
            if action == "request-approval":
                from quantcode.legacy_approval import publish_approval
                with execution_lock(database, value.thread_id):
                    if legacy_checkpoint_binding(context, thread_id=value.thread_id, db_path=database) != binding:
                        raise ValueError("legacy checkpoint changed before approval request")
                    return publish_approval(binding, result, recovery, context, session)
            if value.approval_gate_id and (not value.expected_gate_id or not result.get("pending_approval")):
                raise ValueError("an approval receipt must select the exact pending legacy Gate")
            if recovery["available"]:
                from quantcode.legacy_executor import resume_checkpoint
                entry, provenance = _entry(binding)
                if provenance != "registered" or entry is None:
                    raise ValueError("legacy executor registration changed")
                # Never release the old writer lock between the last exact
                # checkpoint check and the archived graph's first operation.
                with execution_lock(database, value.thread_id):
                    if legacy_checkpoint_binding(context, thread_id=value.thread_id, db_path=database) != binding:
                        raise ValueError("legacy checkpoint changed before recovery")
                    from quantcode.legacy_approval import verified_approval
                    approval_check = (lambda: verified_approval(value.approval_gate_id, binding, result, recovery, context, session)) if value.approval_gate_id else None
                    if approval_check:
                        approval_check()
                    return resume_checkpoint(value, binding, recovery, entry, context, database, private,
                                             lambda proof: _record_continuation(entry, binding, context, database, proof), approval_check)
            result = {"engine": "legacy-python", "thread_id": value.thread_id, "checkpoint_id": value.checkpoint_id,
                      "resumed": False, "read_only": True, "recovery": recovery, "status": "blocked"}
        else:
            if recovery["gate_available"]:
                from quantcode.legacy_approval import preview_approval
                try:
                    recovery["approval"] = preview_approval(binding, result, recovery, context, session)
                except (ValueError, PermissionError, httpx.HTTPError):
                    recovery["approval_error"] = "审批记录暂不可读；恢复前必须重新核验网关中的精确决定。"
            result.update(engine="legacy-python", can_resume=recovery["available"], read_only=True, recovery=recovery,
                          recovery_block_reason="；".join(item["message"] for item in recovery["blockers"]))
    else:
        raise ValueError("unsupported legacy history action")
    if _private(session) != private or read_session_file(session) != context or _private(session) != private:
        raise PermissionError("legacy history identity changed before disclosure")
    return result


def _commit_manifest(destination: Path, document: dict, previous: bytes | None) -> bytes:
    content = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    if len(content) > 8_000_000 or _private(destination, missing=True) != previous:
        raise ValueError("legacy provenance registry changed or exceeded its size limit")
    fd, temporary = tempfile.mkstemp(prefix=".legacy-provenance-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
        parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return content


def _record_continuation(entry: dict, before: dict, context: dict, database: Path, proof: dict) -> dict:
    """Append proven continuation provenance; never relabel an old record."""
    # This is a host-owned completion receipt, not a new execution grant. The
    # original writer lock is still held and admission fixed the owner/source.
    # Revocation must stop execution but must not erase the facts it produced.
    owner_context = {**context, **before["owner"]}
    latest = legacy_checkpoint_binding(owner_context, thread_id=before["thread_id"], db_path=database)
    if latest["owner_digest"] != before["owner_digest"]:
        raise PermissionError("archived executor changed the original checkpoint owner")
    if latest["checkpoint_digest"] == before["checkpoint_digest"]:
        return latest
    destination = _manifest()
    with execution_lock(destination, "legacy-provenance"):
        raw = _private(destination)
        document = json.loads(raw)
        original = [item for item in document["entries"] if item.get("thread_id") == before["thread_id"] and item.get("checkpoint_id") == before["checkpoint_id"]]
        if len(original) != 1 or original[0] != entry:
            raise ValueError("original executor provenance changed during recovery")
        if any(item.get("thread_id") == latest["thread_id"] and item.get("checkpoint_id") == latest["checkpoint_id"] for item in document["entries"]):
            raise ValueError("continuation checkpoint already has a provenance record")
        runtime = RuntimeDefinition.model_validate({**entry["runtime"], **proof}).model_dump()
        if set(proof) != {"next_nodes", "pending_tasks"}:
            raise ValueError("continuation may update pending execution only, not the registered graph")
        document["entries"].append({**entry, "checkpoint_id": latest["checkpoint_id"], "runtime": runtime,
                                    "checkpoint_digest": latest["checkpoint_digest"],
                                    "parent_checkpoint_id": before["checkpoint_id"],
                                    "parent_checkpoint_digest": before["checkpoint_digest"],
                                    "executed_by": context["actor_id"], "execution_login_id": context["session_id"],
                                    "recorded_at": datetime.now(timezone.utc).isoformat(), "record_source": "verified_legacy_continuation"})
        _commit_manifest(destination, document, raw)
    return latest


def enroll(source: Path, expected: str) -> dict:
    """Host-terminal action: record reviewed archived source, never synthesize it."""
    identity_file = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    credential = _private(identity_file)
    context = read_session_file(identity_file)
    if context["role"] != "admin":
        raise PermissionError("legacy provenance enrollment requires a host administrator")
    data = Enrollment.model_validate_json(_private(source))
    _sources(data.model_dump())
    _dependencies(data.model_dump())
    destination = _manifest()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = destination.parent.stat()
    if destination.parent.resolve() != destination.parent or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("legacy provenance directory must be host-private")
    with execution_lock(destination, "legacy-provenance"):
        raw = _private(destination, missing=True)
        if ("absent" if raw is None else _digest(raw)) != expected:
            raise ValueError("legacy provenance registry changed")
        binding = legacy_checkpoint_binding(context, thread_id=data.thread_id, checkpoint_id=data.checkpoint_id,
                                            db_path=_database(), organization=True)
        if data.checkpoint_digest != binding["checkpoint_digest"] or data.owner_digest != binding["owner_digest"]:
            raise ValueError("legacy checkpoint or owner changed before enrollment")
        entry = {**data.model_dump(), "reviewer": context["actor_id"],
                 "reviewer_session_id": context["session_id"], "recorded_at": datetime.now(timezone.utc).isoformat()}
        document = json.loads(raw) if raw is not None else {"version": 1, "entries": []}
        if any(item.get("thread_id") == data.thread_id and item.get("checkpoint_id") == data.checkpoint_id for item in document["entries"]):
            raise ValueError("this exact checkpoint already has a provenance registration; registrations cannot be overwritten")
        document["entries"].append(entry)
        if _private(identity_file) != credential or read_session_file(identity_file) != context:
            raise PermissionError("administrator identity changed before enrollment")
        _sources(entry)
        content = _commit_manifest(destination, document, raw)
        return {"registered": True, "digest": _digest(content), "thread_id": data.thread_id, "checkpoint_id": data.checkpoint_id}


def usage_action(action: str, source: Path) -> dict:
    from quantcode.legacy_usage import UsageRead, UsageReview, read_usage, review_usage
    session = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    credential = _private(session)
    context = read_session_file(session)
    def reauthorize():
        if _private(session) != credential or read_session_file(session) != context or _private(session) != credential:
            raise PermissionError("legacy usage reviewer identity changed")
    raw = _private(source)
    if action == "usage-read":
        result = read_usage(UsageRead.model_validate_json(raw), context, _database())
    else:
        result = review_usage(UsageReview.model_validate_json(raw), context, _database(), reauthorize)
    reauthorize()
    return result


def main() -> None:
    output = sys.stdout
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["list", "detail", "resume", "request-approval", "enroll", "usage-read", "usage-review"], required=True)
    parser.add_argument("--login")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--expected")
    args = parser.parse_args()
    try:
        if args.action == "enroll":
            if args.source is None or not re.fullmatch(r"absent|[a-f0-9]{64}", args.expected or ""):
                raise ValueError("enrollment requires a private source declaration and expected registry digest")
            result = enroll(args.source, args.expected)
        elif args.action in {"usage-read", "usage-review"}:
            if args.source is None or args.login is not None or args.expected is not None:
                raise ValueError("usage inspection/review requires a private source declaration on the host terminal")
            result = usage_action(args.action, args.source)
        else:
            if not args.login or args.source is not None or args.expected is not None:
                raise ValueError("history requires a current login and accepts no enrollment arguments")
            raw = sys.stdin.buffer.readline(16385) if args.action == "resume" else sys.stdin.buffer.read(16385)
            if len(raw) > 16384:
                raise ValueError("legacy history request is too large")
            result = handle(args.action, args.login, json.loads(raw))
    except PermissionError as error:
        result = {"error": str(error), "kind": "denied"}
    except ValueError as error:
        result = {"error": str(error), "kind": "invalid"}
    except Exception:
        result = {"error": "旧任务历史服务暂不可用；不会创建新的任务或检查点。", "kind": "unavailable"}
    if args.action == "resume":
        result = {"type": "result", "result": result}
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True, file=output)


if __name__ == "__main__":
    main()

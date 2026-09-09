"""write_blackboard tool — 持久化 key→value 到 BlackboardService。

Day 3 评审后改造（leader 指令 2）：
- tools/model/ 内的 mock 实现不再完善；底座（ToolDef/Registry/MCP）保持
- 真持久化交给从 PR #18 (shawchen5242) cherry-pick 的 runner/blackboard.py
- 写入 PROJECT scope：跨组可见 handoff。GROUP 私有持久化由需要私有状态的
  group tool 另行显式写入，model handoff 不再无条件双写。

写入流程：
1. 用 ctx 里的 thread_id 当 session_id，group 当 requester_group
2. 构造 BlackboardService（默认 db_path = .quantcode/blackboard.db）
3. 调 write_value 写 PROJECT scope（cross-group 共享）
4. 返回 BlackboardEntry.model_dump()

注：BlackboardEntry.written_by_task_id 受 schemas.compose_task 的 TASK_ID_PATTERN
约束（``^T\\d+(\\.\\d+){0,4}$``）。ReAct loop 暂无真正的 task_id：ctx 未提供时
写 ``T0.<thread_hash>``（T0 = 未分配任务的诚实占位，可追溯到 thread，不冒充
真实 ComposeTask 署名；接入 ComposeTask 后由 tool 注入真正的 task_id）。
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re
import stat

import httpx
from pydantic import BaseModel, ConfigDict, Field

from runner.blackboard import BlackboardService
from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
from schemas import BlackboardEntry, BlackboardScope, GroupName, WritePolicy
from tools.registry import ToolDef
from tools.utils.dedupe import dedupe_within


class WriteBlackboardArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Native tasks must use an explicit canonical shared.model_entries.<id> key")
    value: dict
    expected_version: int | None = Field(default=None, ge=0, strict=True,
        description="Native tasks must supply the approved current version; 0 requires the key to be absent")


def native_blackboard_path() -> Path:
    """A shared organization service store is explicit; never use a user's DB."""
    configured = os.environ.get("QUANTCODE_SHARED_BLACKBOARD_DB", "")
    if not configured:
        raise PermissionError("shared Blackboard service is not configured")
    path = Path(configured)
    if not path.is_absolute() or path.parent.resolve() != path.parent or path.is_symlink():
        raise PermissionError("shared Blackboard requires a canonical host-owned path")
    if os.name != "posix":
        raise PermissionError("shared Blackboard host file ACL verification is unavailable on this platform")
    parent = path.parent.stat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077 or parent.st_uid != os.getuid():
        raise PermissionError("shared Blackboard directory must be private to its service account")
    if not path.is_file():
        raise PermissionError("shared Blackboard must be initialized by its service administrator")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
        raise PermissionError("shared Blackboard file must be owned by its service account")
    return path


def _native_approval(args: WriteBlackboardArgs, ctx: dict) -> dict:
    """Read current gateway approval; transport identifiers alone are no grant."""
    from quantcode.identity_login import _session_record, read_session_file

    native = ctx.get("_native_call")
    if not isinstance(native, dict) or ctx.get("group") != "model" or ctx.get("role") not in {"analyst", "approver", "admin"}:
        raise PermissionError("native Blackboard write requires the model group's authenticated session")
    if not re.fullmatch(r"shared\.model_entries\.[A-Za-z0-9_.-]+", args.key) or make_read_key(args.key) != args.key:
        raise PermissionError("native Blackboard writes require an explicit shared.model_entries key")
    if args.expected_version is None:
        raise ValueError("native Blackboard writes require expected_version")
    if not native.get("gate_id") or not native.get("operation_digest"):
        raise PermissionError("native Blackboard write requires an exact gateway approval")
    path = Path(os.environ.get("QUANTCODE_IDENTITY_SESSION_FILE", ""))
    current = read_session_file(path)
    identity_fields = ("session_id", "actor_id", "group", "role", "workspace_id", "resource_scopes")
    for field in identity_fields:
        a, b = current.get(field), ctx.get(field)
        changed = set(a or []) != set(b or []) if field == "resource_scopes" else a != b
        if changed:
            raise PermissionError("native Blackboard identity changed")
    if current["session_id"] != native["login_session_id"]:
        raise PermissionError("native Blackboard login binding changed")
    record = _session_record(path)
    with httpx.Client(base_url=record["gateway"], timeout=15, follow_redirects=False, trust_env=False) as client:
        response = client.post("/native-gates/read", json={"expected_session_id": current["session_id"], "gate_id": native["gate_id"]},
                               headers={"Authorization": f"Bearer {record['token']}"})
    if response.status_code != 200:
        raise PermissionError("gateway could not validate the native Blackboard approval")
    gate = response.json()
    if not isinstance(gate, dict) or gate.get("valid") is not True or gate.get("status") != "approved":
        raise PermissionError("native Blackboard approval is pending, expired or revoked")
    request = gate.get("request") or {}
    expected = {"version": 1, "root_session_id": native["root_session_id"], "session_id": native["native_session_id"],
                "message_id": native["message_id"], "call_id": native["call_id"], "server": native["server"],
                "tool": "write_blackboard", "kind": "merge", "resource": "blackboard:project:" + args.key,
                "resource_version": str(args.expected_version), "operation_digest": native["operation_digest"],
                "catalog_digest": native["catalog_digest"], "arguments_json": native["arguments_json"],
                "arguments_digest": native["arguments_digest"]}
    if not isinstance(request, dict) or any(type(request.get(field)) is not type(value) or request[field] != value for field, value in expected.items()):
        raise PermissionError("gateway approval does not match this exact Blackboard operation")
    owner = gate.get("owner") or {}
    if not isinstance(owner, dict):
        raise PermissionError("gateway approval owner is invalid")
    for field in identity_fields:
        a, b = owner.get(field), current.get(field)
        changed = set(a or []) != set(b or []) if field == "resource_scopes" else a != b
        if changed:
            raise PermissionError("gateway approval belongs to a different identity")
    decision = gate.get("decision") or {}
    if not isinstance(decision, dict) or gate.get("gate_id") != native["gate_id"] or decision.get("decision") != "approve" or \
            decision.get("operation_digest") != native["operation_digest"] or decision.get("record_digest") != gate.get("record_digest"):
        raise PermissionError("gateway approval receipt does not match the operation")
    if not isinstance(decision.get("receipt_digest"), str) or not re.fullmatch(r"[a-f0-9]{64}", decision["receipt_digest"]):
        raise PermissionError("gateway approval receipt is missing")
    # A credential switch during the gateway request invalidates its result.
    if _session_record(path) != record or read_session_file(path) != current:
        raise PermissionError("native Blackboard identity changed while validating approval")
    return gate


def _synthesize_task_id(thread_id: str) -> str:
    """thread_id 无对应 ComposeTask 时的诚实占位 task_id（audit #18）。

    TASK_ID_PATTERN 只接受 ``^T\\d+(\\.\\d+){0,4}$``，无法表达"缺失"；
    因此统一用 ``T0.<digits8>`` 前缀：``T0`` 明确表示"未分配任务"（0 号任务
    即无任务），digits8 是 thread_id 的稳定 8 位数字摘要——可追溯到 thread，
    且不会被误读成真实 ComposeTask 署名（真实 task 从 T1 起）。
    """
    import hashlib

    hex_digest = hashlib.sha1(thread_id.encode("utf-8")).hexdigest()
    digits_only = "".join(ch for ch in hex_digest if ch.isdigit())
    segment = (digits_only + "0" * 8)[:8]
    return f"T0.{segment}"


def write_blackboard_execute(args: WriteBlackboardArgs, ctx: dict) -> dict:
    """写一个 dict 值到 blackboard 的 PROJECT scope。

    读自 ctx：
    - ``thread_id`` (或 ``session_id``) — 用于占位 task_id 派生与 dedupe
    - ``group`` — 写者所在 group
    - ``task_id`` — 真实 task_id（可选；缺失时用 T0.<thread_hash> 占位）
    - ``blackboard_db_path`` — 可选覆盖默认 db 路径

    构造 BlackboardService，调 ``write_value``：
    - session 固定 ``PROJECT_SESSION_ID``（跨组共享条目归一层，P0-2）
    - PROJECT scope：key 经 ``make_read_key`` 归一（裸名补 ``shared.model_entries.``
      前缀，幂等），跨组可读

    返回：
        ``{"project_entry": {...}}``，即 BlackboardEntry 的 dict 形式
        （含 scope/key/value/version/created_at 等）。
    """
    native = ctx.get("_native_call")
    gate = _native_approval(args, ctx) if native is not None else None
    thread_id = (
        ctx.get("thread_id")
        or ctx.get("session_id")
        or "default-thread"
    )
    raw_group = ctx.get("group") or "model"
    group: GroupName = GroupName(raw_group)

    # Preserve the legacy schema without pretending a native session is a
    # ComposeTask. Full digest identity avoids the old 8-digit collision.
    operation = (json.dumps([ctx.get("actor_id"), ctx.get("workspace_id"), native["native_session_id"],
                            native["call_id"], native["arguments_digest"], native["gate_id"]], separators=(",", ":"))
                 if native is not None else None)
    task_id = f"T0.{int(hashlib.sha256(operation.encode()).hexdigest(), 16)}" if operation is not None \
        else str(ctx.get("task_id") or "") or _synthesize_task_id(thread_id)

    # Native models cannot select a database. Use the same server-owned store
    # as the organization's existing Blackboard readers.
    db_path_str = ctx.get("blackboard_db_path") if native is None else None
    db_path = native_blackboard_path() if native is not None else Path(db_path_str) if db_path_str else None

    service = BlackboardService(
        db_path=db_path,
        session_id=PROJECT_SESSION_ID,
        requester_group=group,
    )

    def revalidate() -> None:
        current = _native_approval(args, ctx)
        if current["record_digest"] != gate["record_digest"] or current["decision"]["receipt_digest"] != gate["decision"]["receipt_digest"]:
            raise PermissionError("native Blackboard approval changed before commit")

    project_entry: BlackboardEntry = service.write_value(
        scope=BlackboardScope.PROJECT,
        key=make_read_key(args.key),
        value=args.value,
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id=task_id,
        written_by_group=group,
        expected_version=args.expected_version,
        validate_before_write=revalidate if native is not None else None,
    )
    result = {
        "project_entry": project_entry.model_dump(mode="json"),
    }
    if native is not None:
        result["native_operation"] = {"native_session_id": native["native_session_id"], "root_session_id": native["root_session_id"],
                                      "message_id": native["message_id"], "call_id": native["call_id"],
                                      "gate_id": native["gate_id"], "operation_digest": native["operation_digest"],
                                      "arguments_digest": native["arguments_digest"], "resource": gate["request"]["resource"],
                                      "previous_version": args.expected_version, "version": project_entry.version,
                                      "approval_receipt": gate["decision"]["receipt_digest"]}
    return result


# 去重窗口 300 秒，scope 仅在 ``write_blackboard_execute`` 这一个函数内。
# 防短时间重复写入（同一 key 在 5 分钟内只首次真正落盘，后续返回上一次结果）。
_legacy_write_blackboard = dedupe_within(
    seconds=300,
    key=lambda args, ctx: f"{ctx.get('thread_id', 'default')}::{args.key}",
)(write_blackboard_execute)


def write_blackboard_wrapped_execute(args: WriteBlackboardArgs, ctx: dict) -> dict:
    if "_native_call" in ctx:
        # Native call identity/receipts own replay. The version CAS means the
        # same already-committed call cannot produce another shared write.
        return write_blackboard_execute(args, ctx)
    return _legacy_write_blackboard(args, ctx)


write_blackboard_tool = ToolDef(
    id="write_blackboard",
    description=(
        "Write a shared model entry through BlackboardService. Native tasks supply an explicit "
        "shared.model_entries key and expected_version (0 for a new key); the host must obtain "
        "approval for this exact key, value and version. Read the current version with read_blackboard."
    ),
    schema=WriteBlackboardArgs,
    execute=write_blackboard_wrapped_execute,
)

__all__ = [
    "write_blackboard_tool",
    "WriteBlackboardArgs",
    "write_blackboard_execute",
]

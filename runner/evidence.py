"""Evidence chain runner — 逐环 append / 重放校验 / 报告构建（SPEC §2.2 + §3）。

写：``runner/agent_engine.py`` 的 run/stream/resume 完成钩子 try/except ImportError
调 ``append_event``，追加 AuditEvent JSONL 到 ``.quantcode/evidence/<run_id>.jsonl``
（metrics 风格：写失败静默 best-effort）。
读：``verify_chain``（重放校验，篡改抛 EvidenceChainError）/ ``build_report``
（校验链 → EvidenceReport）——这两者不得静默。

ArtifactRef 绑定（G2-A6）：ARTIFACT 环 payload 含 path/sha256/bytes，
verify/build 时对磁盘文件重算 sha256，不一致即 EvidenceChainError。
路径按 ``artifacts_root``（默认项目根）解析，相对/绝对路径皆可。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from schemas.evidence_chain import (
    ArtifactRef,
    AuditEvent,
    AuditEventKind,
    DecisionRecord,
    EvidenceReport,
    canonical_json,
    compute_entry_hash,
    make_audit_event,
    report_hash_of,
    sha256_hex,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = PROJECT_ROOT / ".quantcode" / "evidence"


class EvidenceChainError(Exception):
    """审计链校验失败（任何一环被篡改 / 顺序错乱 / 衔接断裂 / 工件失绑）。"""


def evidence_path(run_id: str, artifacts_dir: str | Path = EVIDENCE_DIR) -> Path:
    return Path(artifacts_dir) / f"{run_id}.jsonl"


def _load_events(
    run_id: str, artifacts_dir: str | Path = EVIDENCE_DIR
) -> list[AuditEvent]:
    """读回整条链；文件缺失/坏行静默跳过（坏行只可能来自外部篡改，
    会被 verify 的衔接断裂捕获——不在这里抛）。"""
    try:
        lines = evidence_path(run_id, artifacts_dir).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[AuditEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(AuditEvent.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue
    return events


def append_event(
    run_id: str,
    kind: str | AuditEventKind,
    payload: dict[str, Any],
    artifacts_dir: str | Path = EVIDENCE_DIR,
) -> None:
    """追加一环到 ``.quantcode/evidence/<run_id>.jsonl``，环哈希衔接前环。

    metrics 风格：任何 I/O / 序列化失败都静默，绝不影响主流程（best-effort）。
    """
    try:
        events = _load_events(run_id, artifacts_dir)
        event = make_audit_event(
            seq=(events[-1].seq + 1) if events else 1,
            kind=kind,
            payload=dict(payload or {}),
            prev_hash=events[-1].entry_hash if events else None,
            at=datetime.now(timezone.utc),
        )
        path = evidence_path(run_id, artifacts_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"
            )
    except Exception:  # ponytail: 审计日志 best-effort，缺环优于砸主流程
        pass


def _hash_file(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _resolve(root: Path, path_str: str) -> Path:
    candidate = Path(path_str)
    return candidate if candidate.is_absolute() else root / candidate


def verify_chain(
    run_id: str,
    artifacts_dir: str | Path = EVIDENCE_DIR,
    *,
    artifacts_root: str | Path | None = None,
) -> list[AuditEvent]:
    """重放校验整条链（G2-A1/A2/A3b/A6）：逐环重算 payload_hash / entry_hash、
    首环 prev_hash=None、逐环衔接、seq 严格递增；ARTIFACT 环绑定的磁盘文件
    sha256 重算一致。任何异常抛 ``EvidenceChainError``——校验路径绝不静默。
    """
    events = _load_events(run_id, artifacts_dir)
    if not events:
        raise EvidenceChainError(f"run_id={run_id!s}: 审计链为空或不存在")

    prev_hash: str | None = None
    prev_seq = 0
    root = Path(artifacts_root) if artifacts_root is not None else PROJECT_ROOT
    for event in events:
        if event.seq != prev_seq + 1:
            raise EvidenceChainError(
                f"seq 断裂: 期望 {prev_seq + 1}, 实际 {event.seq} (run_id={run_id!s})"
            )
        if event.prev_hash != prev_hash:
            raise EvidenceChainError(
                f"seq={event.seq}: prev_hash 不匹配 (run_id={run_id!s})"
            )
        if event.payload_hash != sha256_hex(canonical_json(event.payload)):
            raise EvidenceChainError(
                f"seq={event.seq}: payload_hash 被篡改 (run_id={run_id!s})"
            )
        expected = compute_entry_hash(
            event.seq, event.kind, event.at, event.payload_hash, event.prev_hash
        )
        if event.entry_hash != expected:
            raise EvidenceChainError(
                f"seq={event.seq}: entry_hash 不匹配 (run_id={run_id!s})"
            )
        if event.kind == AuditEventKind.ARTIFACT:
            path_str = event.payload.get("path")
            file_hash = event.payload.get("sha256")
            if not isinstance(path_str, str) or not isinstance(file_hash, str):
                raise EvidenceChainError(
                    f"seq={event.seq}: ARTIFACT 环缺少 path/sha256 (run_id={run_id!s})"
                )
            try:
                digest, _size = _hash_file(_resolve(root, path_str))
            except OSError as exc:
                raise EvidenceChainError(
                    f"seq={event.seq}: 工件不可读 {path_str!s}: {exc} (run_id={run_id!s})"
                ) from exc
            if digest != file_hash:
                raise EvidenceChainError(
                    f"seq={event.seq}: 工件 sha256 与磁盘文件不一致 (G2-A6, run_id={run_id!s})"
                )
        prev_hash = event.entry_hash
        prev_seq = event.seq
    return events


def build_report(
    run_id: str,
    artifacts_dir: str | Path = EVIDENCE_DIR,
    *,
    artifacts_root: str | Path | None = None,
) -> EvidenceReport:
    """校验链 → 组装 ArtifactRef[] 与 DecisionRecord → EvidenceReport。

    - DecisionRecord 仅当链含 kind=human_gate 且 payload.decision.action
      ∈{approve,reject} 的环，且与该 payload 的 HumanGate 字段逐字一致
      （G2-A4/A5），decided_at 取该环 at；不一致 ValidationError（模型校验），
      payload 不完整抛 EvidenceChainError。
    - report_hash 不含 generated_at/report_id —— 同一事件流两次 build 相等
      （G2-A3 重放确定性）。
    """
    events = verify_chain(run_id, artifacts_dir, artifacts_root=artifacts_root)
    root = Path(artifacts_root) if artifacts_root is not None else PROJECT_ROOT

    artifacts: list[ArtifactRef] = []
    for event in events:
        if event.kind != AuditEventKind.ARTIFACT:
            continue
        try:
            path_str = event.payload["path"]
            file_hash = event.payload["sha256"]
            size = event.payload["bytes"]
            if not isinstance(path_str, str) or not isinstance(file_hash, str):
                raise KeyError("path/sha256 须为字符串")
        except KeyError as exc:
            raise EvidenceChainError(
                f"seq={event.seq}: ARTIFACT 环 payload 缺 path/sha256/bytes: {exc}"
            ) from exc
        artifacts.append(
            ArtifactRef(path=path_str, sha256=file_hash, bytes=int(size))
        )
        try:
            _digest, size_on_disk = _hash_file(_resolve(root, path_str))
        except OSError as exc:
            raise EvidenceChainError(
                f"seq={event.seq}: 工件不可读 {path_str!s}: {exc}"
            ) from exc
        if size_on_disk != int(size):
            raise EvidenceChainError(
                f"seq={event.seq}: 工件 bytes 与磁盘不一致 (G2-A6)"
            )

    decision: DecisionRecord | None = None
    gate_entry = next(
        (
            e
            for e in events
            if e.kind == AuditEventKind.HUMAN_GATE
            and isinstance(e.payload.get("decision"), dict)
            and e.payload["decision"].get("action") in ("approve", "reject")
        ),
        None,
    )
    if gate_entry is not None:
        payload_decision = gate_entry.payload["decision"]
        try:
            decision = DecisionRecord(
                gate_id=str(gate_entry.payload["gate_id"]),
                action=payload_decision["action"],
                decided_by=str(payload_decision["decided_by"]),
                decided_at=gate_entry.at,
                reason=payload_decision.get("reason"),
            )
        except (ValidationError, KeyError, TypeError) as exc:
            raise EvidenceChainError(
                f"seq={gate_entry.seq}: human_gate 判决 payload 不完整: {exc}"
            ) from exc

    report = EvidenceReport(
        report_id=f"ev_{run_id}",
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        chain=events,
        artifacts=artifacts,
        decision=decision,
        report_hash="0" * 64,
    )
    return report.model_copy(update={"report_hash": report_hash_of(report)})


__all__ = [
    "EVIDENCE_DIR",
    "EvidenceChainError",
    "append_event",
    "build_report",
    "evidence_path",
    "verify_chain",
]
"""Evidence chain schemas — SPEC governance §2.2（[新增] 审计指纹链契约）。

指纹链：run_id → AuditEvent[]（逐环 prev_hash/entry_hash 衔接）→ ArtifactRef[]
→ DecisionRecord（与 HumanGateDecision 逐字段一致）→ 报告级 report_hash。

- canonical_json：sorted keys + ensure_ascii=False + 紧凑分隔符（全链路唯一规范化）。
- entry_hash = sha256(seq|kind|at|payload_hash|prev_hash)，at 取 isoformat。
- 全部 extra="forbid"；Pydantic 为单一真相源（JSON Schema 工件按需另出）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.human_gate import HumanGateDecisionAction


class AuditEventKind(StrEnum):
    """审计环类型（SPEC §2.2 六类）。"""

    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    RISK_GATE = "risk_gate"
    HUMAN_GATE = "human_gate"
    ARTIFACT = "artifact"
    OUTPUT_DATA = "output_data"


def canonical_json(payload: Any) -> str:
    """链内唯一 JSON 规范化：sorted keys + ensure_ascii=False + 紧凑分隔符。"""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_entry_hash(
    seq: int,
    kind: str,
    at: datetime,
    payload_hash: str,
    prev_hash: str | None,
) -> str:
    """单环指纹：sha256(f"{seq}|{kind}|{at}|{payload_hash}|{prev_hash}")。"""
    return sha256_hex(f"{seq}|{kind}|{at.isoformat()}|{payload_hash}|{prev_hash}")


class AuditEvent(BaseModel):
    """审计环（append-only 哈希链的一环；payload 参与重放校验）。"""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    kind: AuditEventKind
    at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = Field(min_length=64, max_length=64)
    prev_hash: str | None = Field(default=None, min_length=64, max_length=64)
    entry_hash: str = Field(min_length=64, max_length=64)


def make_audit_event(
    *,
    seq: int,
    kind: str | AuditEventKind,
    payload: dict[str, Any],
    prev_hash: str | None = None,
    at: datetime | None = None,
) -> AuditEvent:
    """从 payload 现算 payload_hash / entry_hash 并构造一环（append 路径专用）。"""
    if at is None:
        at = datetime.now(timezone.utc)
    payload_hash = sha256_hex(canonical_json(payload))
    return AuditEvent(
        seq=seq,
        kind=kind,  # type: ignore[arg-type]
        at=at,
        payload=payload,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        entry_hash=compute_entry_hash(seq, kind, at, payload_hash, prev_hash),
    )


class ArtifactRef(BaseModel):
    """工件引用（sha256 与磁盘文件绑定，G2-A6）。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    bytes: int = Field(ge=0)


class DecisionRecord(BaseModel):
    """人工决策署名（SPEC §2.2：须与链上 HumanGateDecision 逐字段一致，G2-A4/A5）。"""

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    action: HumanGateDecisionAction
    decided_by: str = Field(min_length=1)
    decided_at: datetime
    reason: str | None = Field(default=None, max_length=2048)


class EvidenceReport(BaseModel):
    """evidence chain 报告（SPEC §2.2 终点契约）。"""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generated_at: datetime
    chain: list[AuditEvent] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    decision: DecisionRecord | None = None
    report_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _decision_matches_human_gate_entry(self) -> "EvidenceReport":
        """G2-A4/A5：DecisionRecord 存在 ⇔ 链含 approved/rejected 判决的
        human_gate 环，且 gate_id/action/decided_by/reason 与其 payload 逐字一致。"""
        if self.decision is None:
            return self
        for event in self.chain:
            if event.kind != AuditEventKind.HUMAN_GATE:
                continue
            payload_decision = event.payload.get("decision")
            if not isinstance(payload_decision, dict):
                continue
            if payload_decision.get("action") not in ("approve", "reject"):
                continue
            if (
                event.payload.get("gate_id") == self.decision.gate_id
                and payload_decision.get("action") == self.decision.action
                and payload_decision.get("decided_by") == self.decision.decided_by
                and payload_decision.get("reason") == self.decision.reason
            ):
                return self
        raise ValueError(
            "DecisionRecord 必须与链中 approved/rejected 判决的 human_gate 环的 "
            "HumanGate 字段逐字一致（G2-A4/A5）"
        )


def report_hash_of(report: EvidenceReport) -> str:
    """报告指纹：sha256(canonical_json({run_id, chain, artifacts, decision}))。

    不含 generated_at / report_id —— 同一事件流两次 build 的 report_hash 相等
    （G2-A3 重放确定性）。
    """
    basis = {
        "run_id": report.run_id,
        "chain": [
            {"seq": e.seq, "kind": str(e.kind), "entry_hash": e.entry_hash}
            for e in report.chain
        ],
        "artifacts": [a.model_dump(mode="json") for a in report.artifacts],
        "decision": (
            report.decision.model_dump(mode="json") if report.decision else None
        ),
    }
    return sha256_hex(canonical_json(basis))


__all__ = [
    "AuditEvent",
    "AuditEventKind",
    "ArtifactRef",
    "DecisionRecord",
    "EvidenceReport",
    "canonical_json",
    "compute_entry_hash",
    "make_audit_event",
    "report_hash_of",
    "sha256_hex",
]
"""G2-A1..A7 — evidence chain 断言（SPEC governance §4/§6）。

测试名与 SPEC §4/§6 一一对应：
- test_tampered_entry_fails_verification          (G2-A1)
- test_appended_unknown_entry_fails               (G2-A2)
- test_report_replay_deterministic                (G2-A3)
- test_reordered_entries_fail                     (G2-A3b)
- test_decision_requires_human_gate_entry         (G2-A4)
- test_decision_matches_human_gate_payload        (G2-A5)
- test_artifact_sha256_binding                    (G2-A6)
- test_existing_human_gate_contract_unchanged     (G2-A7)
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from runner import evidence as ev
from schemas.evidence_chain import (
    AuditEvent,
    AuditEventKind,
    ArtifactRef,
    DecisionRecord,
    EvidenceReport,
    make_audit_event,
)
from schemas.human_gate import HumanGateDecision, HumanGateDecisionAction


@pytest.fixture()
def evidence_dir(tmp_path: Path) -> Path:
    return tmp_path / "evidence"


def _seed_three_events(run_id: str, evidence_dir: Path) -> None:
    ev.append_event(run_id, AuditEventKind.TOOL_CALL, {"tool": "t1"}, evidence_dir)
    ev.append_event(run_id, AuditEventKind.TOOL_RESULT, {"ok": True}, evidence_dir)
    ev.append_event(
        run_id, AuditEventKind.HUMAN_GATE, {"gate_id": "hg_1", "status": "pending"},
        evidence_dir,
    )


def _read_lines(run_id: str, evidence_dir: Path) -> list[dict]:
    lines = ev.evidence_path(run_id, evidence_dir).read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def _rewrite(run_id: str, evidence_dir: Path, events: list[dict]) -> None:
    ev.evidence_path(run_id, evidence_dir).write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# G2-A1: 篡改环内 payload_hash → verify_chain 抛 EvidenceChainError
# ---------------------------------------------------------------------------

def test_tampered_entry_fails_verification(evidence_dir: Path):
    run_id = "run_a1"
    _seed_three_events(run_id, evidence_dir)
    events = ev.verify_chain(run_id, evidence_dir)
    assert [e.seq for e in events] == [1, 2, 3]

    lines = _read_lines(run_id, evidence_dir)
    lines[1]["payload_hash"] = hashlib.sha256(b"tampered").hexdigest()
    _rewrite(run_id, evidence_dir, lines)

    with pytest.raises(ev.EvidenceChainError):
        ev.verify_chain(run_id, evidence_dir)


# ---------------------------------------------------------------------------
# G2-A2: 链尾插入未登记事件 → 末环 entry_hash 不匹配 → verify 失败
# ---------------------------------------------------------------------------

def test_appended_unknown_entry_fails(evidence_dir: Path):
    run_id = "run_a2"
    _seed_three_events(run_id, evidence_dir)

    # 未登记事件：绕过 append_event 直接改写 JSONL——攻击者复制末环并
    # 伪造 seq/kind，但不知道链哈希算法（重放后末环 entry_hash 不匹配）。
    lines = _read_lines(run_id, evidence_dir)
    forged = dict(lines[-1], seq=lines[-1]["seq"] + 1, kind="output_data")
    _rewrite(run_id, evidence_dir, lines + [forged])

    with pytest.raises(ev.EvidenceChainError):
        ev.verify_chain(run_id, evidence_dir)


# ---------------------------------------------------------------------------
# G2-A3: 同一事件流两次 build_report → report_hash 相等且与审计日志重算链一致
# ---------------------------------------------------------------------------

def test_report_replay_deterministic(evidence_dir: Path):
    run_id = "run_a3"
    _seed_three_events(run_id, evidence_dir)

    report1 = ev.build_report(run_id, evidence_dir)
    report2 = ev.build_report(run_id, evidence_dir)
    assert report1.report_hash == report2.report_hash
    assert report1.generated_at != report2.generated_at  # 时间不同但指纹一致

    # 与审计日志重算链一致：报告里的链逐环哈希与磁盘 JSONL 重放相等
    events = ev.verify_chain(run_id, evidence_dir)
    assert [e.entry_hash for e in report1.chain] == [e.entry_hash for e in events]


# ---------------------------------------------------------------------------
# G2-A3b: 交换两环顺序 → verify 失败
# ---------------------------------------------------------------------------

def test_reordered_entries_fail(evidence_dir: Path):
    run_id = "run_a3b"
    _seed_three_events(run_id, evidence_dir)

    lines = _read_lines(run_id, evidence_dir)
    lines[1], lines[2] = lines[2], lines[1]
    _rewrite(run_id, evidence_dir, lines)

    with pytest.raises(ev.EvidenceChainError):
        ev.verify_chain(run_id, evidence_dir)


# ---------------------------------------------------------------------------
# G2-A4: DecisionRecord 仅当链含 approved/rejected human_gate 环；否则构造即
# ValidationError
# ---------------------------------------------------------------------------

def test_decision_requires_human_gate_entry(evidence_dir: Path):
    run_id = "run_a4"
    # 链只有 tool 环，无 human_gate 判决
    ev.append_event(run_id, AuditEventKind.TOOL_CALL, {"tool": "t"}, evidence_dir)
    events = ev.verify_chain(run_id, evidence_dir)

    decision = DecisionRecord(
        gate_id="hg_x",
        action=HumanGateDecisionAction.APPROVE,
        decided_by="risk-lead",
        decided_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValidationError):
        EvidenceReport(
            report_id="r", run_id=run_id,
            generated_at=datetime.now(timezone.utc),
            chain=events, artifacts=[], decision=decision,
            report_hash="a" * 64,
        )
    # build_report 对无判决链不造 DecisionRecord
    report = ev.build_report(run_id, evidence_dir)
    assert report.decision is None
    assert not report.artifacts


# ---------------------------------------------------------------------------
# G2-A5: DecisionRecord 与 HumanGateDecision 逐字段一致，不等抛 ValidationError
# ---------------------------------------------------------------------------

def _seed_human_gate_with_decision(
    run_id: str, evidence_dir: Path, decided_by: str = "risk-lead",
) -> None:
    ev.append_event(run_id, AuditEventKind.TOOL_CALL, {"tool": "t1"}, evidence_dir)
    ev.append_event(
        run_id, AuditEventKind.HUMAN_GATE,
        {
            "gate_id": "hg_gate1",
            "status": "approved",
            "decision": {
                "action": "approve",
                "decided_by": decided_by,
                "reason": "within policy",
            },
        },
        evidence_dir,
    )


def test_decision_matches_human_gate_payload(evidence_dir: Path):
    run_id = "run_a5"
    _seed_human_gate_with_decision(run_id, evidence_dir)

    report = ev.build_report(run_id, evidence_dir)
    assert report.decision is not None
    # 与 HumanGateDecision 逐字段一致（G2-A5）
    human_decision = HumanGateDecision(
        action=HumanGateDecisionAction.APPROVE,
        decided_by="risk-lead",
        reason="within policy",
    )
    assert report.decision.action == human_decision.action
    assert report.decision.decided_by == human_decision.decided_by
    assert report.decision.reason == human_decision.reason

    # 不一致（decided_by 不同）→ 构造即 ValidationError
    mismatched = DecisionRecord(
        gate_id="hg_gate1",
        action=HumanGateDecisionAction.APPROVE,
        decided_by="someone-else",
        decided_at=datetime.now(timezone.utc),
        reason="within policy",
    )
    with pytest.raises(ValidationError):
        EvidenceReport(
            report_id="r", run_id=run_id,
            generated_at=datetime.now(timezone.utc),
            chain=report.chain, artifacts=[], decision=mismatched,
            report_hash="a" * 64,
        )


# ---------------------------------------------------------------------------
# G2-A6: ArtifactRef.sha256 与磁盘文件重算一致；替换文件后 verify 失败
# ---------------------------------------------------------------------------

def test_artifact_sha256_binding(evidence_dir: Path, tmp_path: Path):
    run_id = "run_a6"
    artifact_file = tmp_path / "artifacts" / "out.csv"
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_text("col\n1\n", encoding="utf-8")
    digest = hashlib.sha256(artifact_file.read_bytes()).hexdigest()

    ev.append_event(run_id, AuditEventKind.TOOL_CALL, {"tool": "t1"}, evidence_dir)
    ev.append_event(
        run_id, AuditEventKind.ARTIFACT,
        {"path": str(artifact_file), "sha256": digest, "bytes": artifact_file.stat().st_size},
        evidence_dir,
    )

    report = ev.build_report(run_id, evidence_dir)
    assert report.artifacts == [
        ArtifactRef(path=str(artifact_file), sha256=digest, bytes=artifact_file.stat().st_size)
    ]

    # 替换磁盘文件 → verify 失败
    artifact_file.write_text("col\n2\n", encoding="utf-8")
    with pytest.raises(ev.EvidenceChainError):
        ev.verify_chain(run_id, evidence_dir)
    with pytest.raises(ev.EvidenceChainError):
        ev.build_report(run_id, evidence_dir)


# ---------------------------------------------------------------------------
# G2-A7: 现状回归护栏 — HumanGate 契约防漂移（快照断言，等价重放
# tests/test_human_gate.py 既有断言语义）
# ---------------------------------------------------------------------------

def test_existing_human_gate_contract_unchanged():
    from runner.human_gate import normalize_external_decision, should_interrupt
    from schemas.human_gate import HumanGate, HumanGateStatus
    from schemas.risk_profile import RiskProfile, RiskThresholds

    # should_interrupt 对 approved/rejected 恒 False（既有 test_should_not_interrupt_*）
    high_risk = RiskProfile(
        strategy_id="demo",
        as_of_date="2024-03-15",
        max_drawdown=0.20,
        position_limit=0.10,
        correlation_with_existing=0.20,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.02,
    )
    assert should_interrupt(high_risk, RiskThresholds()) is True  # 未决闸会拦
    for status in (HumanGateStatus.APPROVED, HumanGateStatus.REJECTED):
        gate = HumanGate(
            gate_id="hg_test_1",
            status=status,
            decision=HumanGateDecision(
                action=HumanGateDecisionAction.APPROVE,
                decided_by="risk-lead",
            ),
        )
        assert should_interrupt(high_risk, RiskThresholds(), gate=gate) is False

    # normalize_external_decision fail-closed（既有 TestNormalizeExternalDecision 语义）
    assert normalize_external_decision("garbage") == "reject"
    assert normalize_external_decision("approve") == "approve"
    assert normalize_external_decision("reject") == "reject"
    assert normalize_external_decision(None) == "reject"

    # 契约快照：HumanGateDecision/DecisionRecord 字段集合不漂移
    assert set(HumanGateDecision.model_fields) == {"action", "decided_by", "reason"}
    assert {"action", "decided_by", "reason"} <= set(DecisionRecord.model_fields)
    with pytest.raises(ValidationError):
        HumanGateDecision(
            action=HumanGateDecisionAction.APPROVE,
            decided_by="x",
            unexpected_field=1,  # type: ignore[arg-type]
        )
    # AuditEventKind 覆盖 SPEC §2.2 六类
    assert {k.value for k in AuditEventKind} == {
        "tool_call", "tool_result", "risk_gate", "human_gate", "artifact", "output_data",
    }


# ---------------------------------------------------------------------------
# 补充：append_event 逐环衔接 + 写失败静默（best-effort 契约）
# ---------------------------------------------------------------------------

def test_append_event_links_hashes_and_silent_on_failure(evidence_dir: Path):
    run_id = "run_link"
    _seed_three_events(run_id, evidence_dir)
    events = ev.verify_chain(run_id, evidence_dir)
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[0].prev_hash is None
    assert events[1].prev_hash == events[0].entry_hash
    assert events[2].prev_hash == events[1].entry_hash

    # evidence 路径为目录（不可写文件）→ append 静默不抛
    bad_dir = evidence_dir / "run_bad.jsonl"
    bad_dir.mkdir()
    # make_audit_event 校验非法 kind 也被吞
    ev.append_event(run_id, "not-a-kind", {}, bad_dir)  # type: ignore[arg-type]

    # make_audit_event 直接构造非法 kind 必须抛（模型层不静默）
    with pytest.raises(ValidationError):
        make_audit_event(seq=1, kind="bogus", payload={})


# ---------------------------------------------------------------------------
# 集成：AgentRunner.stream() evidence 钩子 → .quantcode/evidence/<thread_id>.jsonl
# （P1 修复回归：钩子签名错位曾导致生产永远静默零环）
# ---------------------------------------------------------------------------

class _ScriptedLLM:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):  # noqa: ANN001
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            from langchain_core.messages import AIMessage

            resp = AIMessage(content="done")
        self._idx += 1
        return resp


def _echo_execute(args, ctx):  # noqa: ANN001
    return {"echo": args.text}


def test_stream_run_writes_evidence_chain(tmp_path, monkeypatch):
    """完整构造一次带 evidence 钩子的 stream run：
    trace 的 tool_call/tool_result/output_data + human_gate interrupt 逐环落到
    QUANTCODE_EVIDENCE_DIR/<thread_id>.jsonl，且能通过 verify_chain 重放校验。"""
    import os

    from langchain_core.messages import AIMessage
    from pydantic import BaseModel
    from tools.registry import ToolDef, register_tool
    from tools.registry import registry as global_registry

    class EchoArgs(BaseModel):
        text: str

    def _echo(_args, _ctx):
        return {"echo": "hi"}

    class ProduceArgs(BaseModel):
        ok: bool = True

    # 真实落盘的 artifact 文件（G2-A6 sha256 绑定要求磁盘可读）
    artifact_file = tmp_path / "artifacts" / "out.txt"
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_text("payload\n", encoding="utf-8")

    def _produce(_args, _ctx):
        return {
            "output_data": {"ok": True},
            "artifacts": [str(artifact_file)],
            "task_status": "done",
        }

    saved = dict(global_registry._tools)
    global_registry._tools.clear()
    register_tool(ToolDef(id="echo_tool", description="echo", schema=EchoArgs, execute=_echo))
    register_tool(ToolDef(id="produce_output", description="produce", schema=ProduceArgs, execute=_produce))

    def _ai_with_tools(calls):
        return AIMessage(
            content="",
            tool_calls=[
                {"name": name, "args": args, "id": f"c-{i}"}
                for i, (name, args) in enumerate(calls)
            ],
        )

    llm = _ScriptedLLM([
        _ai_with_tools([("echo_tool", {"text": "hi"})]),
        _ai_with_tools([("produce_output", {"ok": True})]),
    ])

    evidence_target = tmp_path / "evidence"
    monkeypatch.setenv("QUANTCODE_EVIDENCE_DIR", str(evidence_target))

    checkpoint_db = tmp_path / "ev-checkpoints.sqlite"
    try:
        from runner.agent_engine import AgentRunner

        runner = AgentRunner(group="model", model=llm, checkpoint_db=checkpoint_db)
        thread_id = "ev-stream-integration"
        result = runner.stream(
            task="evidence integration",
            system_prompt="x",
            thread_id=thread_id,
            flow_name="trace_test",
        )
    finally:
        global_registry._tools.clear()
        global_registry._tools.update(saved)

    assert result.get("output_data") == {"ok": True}
    chain_path = ev.evidence_path(thread_id, evidence_target)
    assert chain_path.is_file(), f"evidence chain missing: {chain_path}"
    lines = [l for l in chain_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 1

    kinds = [e.kind for e in ev.verify_chain(thread_id, evidence_target)]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert "artifact" in kinds
    assert "human_gate" in kinds  # __interrupt__ 分支的 hook（P2#14）
    assert kinds.count("output_data") >= 1
    # artifact 环按 G2-A6 绑定真实文件
    artifact_event = next(e for e in ev.verify_chain(thread_id, evidence_target) if e.kind == AuditEventKind.ARTIFACT)
    assert artifact_event.payload["path"] == str(artifact_file)
    assert artifact_event.payload["sha256"] == hashlib.sha256(artifact_file.read_bytes()).hexdigest()
"""HumanGate v5 tests: only merge and permission are valid."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from runner.human_gate import (
    build_interrupt_payload,
    extract_interrupt_payload,
    format_waiting_for_human,
    make_gate_id,
    normalize_external_decision,
    parse_resume_decision,
    to_react_resume_payload,
)
from schemas.human_gate import (
    HumanGate,
    HumanGateDecision,
    HumanGateDecisionAction,
    HumanGateInterruptPayload,
    HumanGateStatus,
)


def test_human_gate_schema_valid() -> None:
    gate = HumanGate(
        gate_id="hg_test_1",
        kind="merge",
        resource="factor:demo",
        status=HumanGateStatus.APPROVED,
        decision=HumanGateDecision(
            action=HumanGateDecisionAction.APPROVE,
            decided_by="factor-lead",
        ),
    )
    assert gate.kind == "merge"


@pytest.mark.parametrize("kind", ["risk", "budget", "deploy", "ci"])
def test_non_whitelisted_gate_kind_is_rejected(kind: str) -> None:
    with pytest.raises(ValidationError):
        HumanGate(gate_id="hg_bad", kind=kind, status=HumanGateStatus.PENDING)  # type: ignore[arg-type]


def test_make_gate_id_uses_uuid_suffix() -> None:
    gate_id = make_gate_id("factor:merge:demo")
    assert gate_id.startswith("hg_factor_merge_demo_")
    assert len(gate_id.split("_")[-1]) == 12


@pytest.mark.parametrize(
    ("value", "external", "internal"),
    [
        ("approve", "approve", "proceed"),
        ("proceed", "approve", "proceed"),
        ("reject", "reject", "abort"),
        ("abort", "reject", "abort"),
        ("garbage", "reject", "abort"),
    ],
)
def test_decision_normalization(value: str, external: str, internal: str) -> None:
    assert normalize_external_decision(value) == external
    assert to_react_resume_payload(value) == {"decision": internal}


def test_build_interrupt_payload_merge() -> None:
    payload = build_interrupt_payload(
        gate_id="g1",
        kind="merge",
        resource="factor:demo",
        actor="alice",
        evidence={"artifact": "factor-report.json"},
        reasons=["shared write"],
    )
    assert HumanGateInterruptPayload.model_validate(payload).kind == "merge"


def test_extract_and_format_interrupt() -> None:
    payload = build_interrupt_payload(
        gate_id="g2",
        kind="permission",
        resource="memory:risk/private",
        reasons=["cross-group restricted resource"],
    )
    interrupt = Mock(value=payload)
    assert extract_interrupt_payload({"__interrupt__": [interrupt]}) == payload
    result = format_waiting_for_human(thread_id="t2", interrupt_payload=payload)
    assert result["status"] == "waiting_for_human"
    assert result["gate"]["kind"] == "permission"
    assert result["gate"]["resource"] == "memory:risk/private"


def test_waiting_gate_preserves_expiry_for_reviewer() -> None:
    expiry = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    payload = build_interrupt_payload(
        gate_id="g-expiring",
        kind="permission",
        resource="memory:risk/private",
        reasons=["cross-group restricted resource"],
        expires_at=expiry,
    )

    result = format_waiting_for_human(
        thread_id="t-expiring",
        interrupt_payload=payload,
    )

    assert result["gate"]["expires_at"] == "2030-01-02T03:04:05+00:00"


def test_new_gate_gets_server_policy_expiry(monkeypatch, tmp_path) -> None:
    from runner.config_loader import load_yaml

    (tmp_path / "human_gate.yaml").write_text("ttl_seconds: 120\n", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    load_yaml.cache_clear()
    before = datetime.now(timezone.utc)
    try:
        payload = build_interrupt_payload(
            gate_id="g-policy-expiry",
            kind="merge",
            resource="factor:pb_roe",
            reasons=["shared write"],
        )
    finally:
        load_yaml.cache_clear()
    after = datetime.now(timezone.utc)

    expires_at = datetime.fromisoformat(payload["expires_at"])
    assert before + timedelta(seconds=120) <= expires_at
    assert expires_at <= after + timedelta(seconds=120)
    assert expires_at.utcoffset() == timedelta(0)


def test_extract_empty_and_parse_resume() -> None:
    assert extract_interrupt_payload({}) is None
    assert parse_resume_decision({"decision": "proceed"}) == "proceed"
    assert parse_resume_decision("proceed") is None

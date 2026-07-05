"""HumanGate runner — 根据 RiskProfile 与阈值决定是否暂停 workflow。"""
from __future__ import annotations

from schemas.human_gate import HumanGate, HumanGateStatus
from schemas.risk_profile import RiskProfile, RiskThresholds

_RESOLVED_STATUSES = {
    HumanGateStatus.APPROVED,
    HumanGateStatus.REJECTED,
}


def should_interrupt(
    profile: RiskProfile,
    thresholds: RiskThresholds,
    gate: HumanGate | None = None,
) -> bool:
    """检查是否需要触发 HumanGate（暂停 workflow 等待人工审批）。

    已 approved/rejected 的 gate 不再 interrupt；否则逐项比较阈值。
    """
    if gate is not None and gate.status in _RESOLVED_STATUSES:
        return False

    if profile.max_drawdown > thresholds.max_drawdown:
        return True

    if (
        profile.tail_risk_var_99 is not None
        and profile.tail_risk_var_99 > thresholds.tail_risk_var_99
    ):
        return True

    if profile.position_limit > thresholds.position_limit_usage:
        return True

    if abs(profile.correlation_with_existing) > thresholds.correlation_limit:
        return True

    return False

"""HumanGate runner — 根据风控状态决定是否暂停 workflow。

Owner: T2 风控 / 杨欣琳
"""
from __future__ import annotations

from typing import Any

from schemas.human_gate import HumanGate, HumanGateStatus, HumanGateTrigger

_RESOLVED_STATUSES = {
    HumanGateStatus.APPROVED,
    HumanGateStatus.REJECTED,
    HumanGateStatus.CANCELLED,
    HumanGateStatus.TIMED_OUT,
}


def _get_metric(state: dict[str, Any], gate_config: HumanGate, key: str) -> float | None:
    if key in state:
        return state[key]
    if gate_config.observed_values is not None:
        return getattr(gate_config.observed_values, key, None)
    return None


def _build_trigger_expression(gate_config: HumanGate) -> str | None:
    """从 gate_config.trigger + risk_thresholds 推导 eval 表达式。"""
    thresholds = gate_config.risk_thresholds

    match gate_config.trigger:
        case HumanGateTrigger.MAX_DRAWDOWN_EXCEEDED:
            if thresholds.max_drawdown is None:
                return None
            limit = thresholds.max_drawdown
            return (
                f"_metric('max_drawdown') is not None "
                f"and _metric('max_drawdown') > {limit}"
            )
        case HumanGateTrigger.POSITION_LIMIT_EXCEEDED:
            if thresholds.position_limit is None:
                return None
            limit = thresholds.position_limit
            return (
                f"_metric('position_limit') is not None "
                f"and _metric('position_limit') > {limit}"
            )
        case HumanGateTrigger.CORRELATION_EXCEEDED:
            if thresholds.correlation_with_existing is None:
                return None
            limit = thresholds.correlation_with_existing
            return (
                f"_metric('correlation_with_existing') is not None "
                f"and abs(_metric('correlation_with_existing')) > {limit}"
            )
        case HumanGateTrigger.VAR_EXCEEDED:
            if thresholds.tail_risk_var_99 is None:
                return None
            limit = thresholds.tail_risk_var_99
            return (
                f"_metric('tail_risk_var_99') is not None "
                f"and abs(_metric('tail_risk_var_99')) > abs({limit})"
            )
        case HumanGateTrigger.MISSING_RISK_PROFILE:
            return "not state.get('risk_profile')"
        case HumanGateTrigger.RISK_GATE_UNCERTAIN:
            return "state.get('risk_gate_uncertain', False)"
        case HumanGateTrigger.MANUAL_REQUEST:
            return "state.get('manual_request', False)"
        case HumanGateTrigger.WORKFLOW_FAILURE:
            return "state.get('workflow_failure', False)"
        case _:
            return None


def should_interrupt(state: dict[str, Any], gate_config: HumanGate) -> bool:
    """检查是否需要触发 HumanGate（暂停 workflow 等待人工审批）。

    根据 gate_config.trigger 与 risk_thresholds 构造条件表达式，
    在受限命名空间内 eval；已决议的 gate 不再 interrupt。
    """
    if gate_config.status in _RESOLVED_STATUSES:
        return False

    expr = _build_trigger_expression(gate_config)
    if expr is None:
        return False

    def _metric(key: str) -> float | None:
        return _get_metric(state, gate_config, key)

    namespace = {
        "state": state,
        "_metric": _metric,
        "abs": abs,
    }
    return bool(eval(expr, {"__builtins__": {}}, namespace))

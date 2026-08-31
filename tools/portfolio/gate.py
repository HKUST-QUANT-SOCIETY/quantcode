"""check_portfolio_gate — 组合阈值裁决 + HumanGate interrupt payload 构造（确定性）。"""
from __future__ import annotations

from typing import Any

from schemas.portfolio import PortfolioGateVerdict, RebalancePlan

# 代码兜底默认（configs/portfolio.yaml 同源：max_single_weight/commission/
# stamp_tax/rebalance_min_turnover/max_turnover_gate/max_drawdown_proxy）
DEFAULT_MAX_SINGLE_WEIGHT = 0.10
DEFAULT_MAX_TURNOVER = 0.50
DEFAULT_MAX_DRAWDOWN_PROXY = 0.20


def _yaml_defaults() -> dict[str, float]:
    """从 configs/portfolio.yaml 读默认阈值（缺键用代码兜底）。"""
    from runner.config_loader import load_yaml

    cfg = load_yaml("portfolio")
    return {
        "max_single_weight": float(cfg.get("max_single_weight", DEFAULT_MAX_SINGLE_WEIGHT)),
        "max_turnover": float(cfg.get("max_turnover_gate", DEFAULT_MAX_TURNOVER)),
        "max_drawdown_proxy": float(cfg.get("max_drawdown_proxy", DEFAULT_MAX_DRAWDOWN_PROXY)),
    }


def maybe_interrupt(payload: dict[str, Any]) -> dict[str, Any] | None:
    """在 LangGraph 上下文内用 interrupt() 真暂停（与 request_human_review 同路）。

    GraphInterrupt 是 BaseException 子类 → 向 tool_node 冒泡（tool_node 对
    GraphBubbleUp re-raise），LangGraph 暂停等 Command(resume=...)。
    resume 后 interrupt() 返回 resume payload（{"decision": ...}）。
    不在 graph 内（MCP 直调/单测直调）→ RuntimeError，返回 None 不中断。
    """
    try:
        from langgraph.types import interrupt

        return interrupt(payload)
    except RuntimeError:
        return None


def max_drawdown_proxy_impl(equity_curve: list[float]) -> float:
    """组合回撤代理：max(peak - equity) / peak。空/单点 → 0.0。"""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    dd = 0.0
    for v in equity_curve[1:]:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return float(dd)


def check_portfolio_gate_impl(
    plan: RebalancePlan | dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
    equity_curve: list[float] | None = None,
    thread_id: str = "",
) -> PortfolioGateVerdict:
    """裁决 + requires_human 时经 runner.human_gate.build_interrupt_payload(kind 风格) 组 payload。

    thresholds 键（键名 LLM 可给摘要，缺省用默认）：
    - max_single_weight     单资产权重上限（目标权重里逐个查，含 plan.to_w）
    - max_turnover          换手上限
    - max_drawdown_proxy    回撤代理上限（仅当提供 equity_curve）
    """
    if isinstance(plan, dict):
        plan = RebalancePlan(**plan)
    defaults = _yaml_defaults()
    t = thresholds or {}
    max_single = float(t.get("max_single_weight", defaults["max_single_weight"]))
    max_turnover = float(t.get("max_turnover", defaults["max_turnover"]))
    max_dd = float(t.get("max_drawdown_proxy", defaults["max_drawdown_proxy"]))

    breached: list[str] = []
    reasons: list[str] = []

    goal_weights: dict[str, float] = {}
    for tr in plan.trades:
        goal_weights[tr["asset"]] = float(tr["to_w"])
    if weights:
        goal_weights.update(weights)

    worst_asset, worst_w = "", 0.0
    for a, w in sorted(goal_weights.items()):
        if w > worst_w:
            worst_asset, worst_w = a, w
    if worst_w > max_single:
        breached.append("single_weight")
        reasons.append(f"single weight {worst_w:.4f} of '{worst_asset}' > max_single_weight {max_single}")

    if plan.turnover > max_turnover:
        breached.append("turnover")
        reasons.append(f"turnover {plan.turnover:.4f} > max_turnover {max_turnover}")

    if equity_curve is not None:
        dd = max_drawdown_proxy_impl(equity_curve)
        if dd > max_dd:
            breached.append("drawdown_proxy")
            reasons.append(f"drawdown proxy {dd:.4f} > max_drawdown_proxy {max_dd}")

    requires_human = bool(breached)
    payload: dict[str, Any] | None = None
    if requires_human:
        from runner.human_gate import build_interrupt_payload, make_gate_id

        payload = build_interrupt_payload(
            gate_id=make_gate_id(thread_id or "portfolio"),
            risk_profile={
                "kind": "portfolio",
                "breached": breached,
                "turnover": plan.turnover,
                "fee_total": plan.fee_total,
                "max_single_weight_seen": round(worst_w, 6),
                "thresholds": {
                    "max_single_weight": max_single,
                    "max_turnover": max_turnover,
                    "max_drawdown_proxy": max_dd,
                },
            },
            reasons=reasons,
            message=f"⏸️ HumanGate: portfolio thresholds exceeded ({', '.join(breached)})",
        )
        # LangGraph 上下文内 → interrupt() 抛 GraphInterrupt 冒泡暂停；resume 后
        # 本行返回 resume payload → 归一为 decision dict（供 _extract_state_fields
        # 写 human_review_result，镜像 request_human_review 契约）。
        # 进程外直调（测试/MCP 单步）→ interrupt 抛 RuntimeError → 返回带 payload
        # 的 verdict（requires_human=True，由调用方决定下一步）。
        resumed = maybe_interrupt(payload)
        if resumed is not None:
            from runner.human_gate import normalize_external_decision, parse_resume_decision

            raw = parse_resume_decision(resumed)
            external = normalize_external_decision(raw) if raw else "reject"
            return {
                "decision": "proceed" if external == "approve" else "abort",
                "external_decision": external,
                "gate_id": payload.get("gate_id", ""),
                "breached": breached,
                "reasons": reasons,
                "reviewed_by": "human",
            }
    return PortfolioGateVerdict(
        thresholds={"max_single_weight": max_single, "max_turnover": max_turnover, "max_drawdown_proxy": max_dd},
        breached=breached,
        requires_human=requires_human,
        reasons=reasons,
        interrupt_payload=payload,
    )
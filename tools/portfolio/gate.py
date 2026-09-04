"""portfolio_verdict — 组合阈值裁决（确定性）。

v0.2 收窄（F-03 / governance G2-A8）：组合越限 = gate 判定 **fail**——
breached / reasons 随裁决返回，由报告平台承接，不再构造 HumanGate
interrupt payload、不再暂停等审批（组合产出不 gate，只有写操作进
生产面才 gate）。``runner.human_gate`` 的 interrupt 机制保留给写操作
触发点（merge / permission / deploy / budget）复用。
"""
from __future__ import annotations

from typing import Any

from schemas.portfolio import PortfolioVerdict, RebalancePlan

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


def portfolio_verdict_impl(
    plan: RebalancePlan | dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
    equity_curve: list[float] | None = None,
) -> PortfolioVerdict:
    """裁决组合计划是否越过阈值；越限 → 裁决 fail（不再触发人审暂停）。

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

    # v0.2 收窄：越限 → 裁决 fail（breached/reasons 承载失败语义），不再构造
    # interrupt payload、不再经 maybe_interrupt() 暂停等 resume。
    return PortfolioVerdict(
        thresholds={"max_single_weight": max_single, "max_turnover": max_turnover, "max_drawdown_proxy": max_dd},
        breached=breached,
        verdict="fail" if breached else "pass",
        reasons=reasons,
    )

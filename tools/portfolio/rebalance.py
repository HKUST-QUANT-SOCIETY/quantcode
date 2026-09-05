"""rebalance_plan — 当前权重 → 目标权重的调仓计划（确定性）。"""
from __future__ import annotations

from typing import Any

from schemas.portfolio import RebalancePlan, TargetPortfolio

# double-sided commission + sell stamp tax（configs/portfolio.yaml 同源默认）
DEFAULT_COMMISSION = 0.0003
DEFAULT_STAMP_TAX = 0.0005


def _yaml_costs() -> tuple[float, float]:
    """从 configs/portfolio.yaml 读成本默认（缺键用代码兜底）。"""
    from runner.config_loader import load_yaml

    cfg = load_yaml("portfolio")
    return (
        float(cfg.get("commission", DEFAULT_COMMISSION)),
        float(cfg.get("stamp_tax", DEFAULT_STAMP_TAX)),
    )


def rebalance_plan_impl(
    current: dict[str, float],
    target: dict[str, float],
    max_single_weight: float | None = None,
    rebalance_min_turnover: float | None = None,
    commission: float | None = None,
    stamp_tax: float | None = None,
    thresholds: dict[str, Any] | None = None,
) -> RebalancePlan:
    """构建 RebalancePlan。

    成本模型（ponytail 简化）：双边佣金 0.0003 + 卖出印花税 0.0005，
    按换手金额绝对值计，不区分买卖方向对佣金的归属。

    delta 绝对值 < rebalance_min_turnover / len(assets) 的资产不动（不进 trades）。
    """
    if thresholds:
        # tool 层传来的覆盖值（LLM 只需给 thresholds dict）
        max_single_weight = thresholds.get("max_single_weight", max_single_weight)
        rebalance_min_turnover = thresholds.get("rebalance_min_turnover", rebalance_min_turnover)
        commission = thresholds.get("commission", commission)
        stamp_tax = thresholds.get("stamp_tax", stamp_tax)

    comm = DEFAULT_COMMISSION if commission is None else float(commission)
    stamp = DEFAULT_STAMP_TAX if stamp_tax is None else float(stamp_tax)
    if commission is None and stamp_tax is None and not thresholds:
        # 单源：入参未给成本时读 configs/portfolio.yaml（tmp 覆盖 QUANTCODE_CONFIG_DIR 即生效）
        comm, stamp = _yaml_costs()
    min_turnover = 0.05 if rebalance_min_turnover is None else float(rebalance_min_turnover)

    assets = sorted(set(current) | set(target))
    n = max(len(assets), 1)
    skip = min_turnover / n if min_turnover > 0 else 0.0

    trades: list[dict[str, Any]] = []
    turnover = 0.0
    fee_total = 0.0
    for a in assets:
        from_w = float(current.get(a, 0.0))
        to_w = float(target.get(a, 0.0))
        delta = to_w - from_w
        if abs(delta) < skip:
            continue
        cost = abs(delta) * comm + (abs(delta) * stamp if delta < 0 else 0.0)
        trades.append({
            "asset": a,
            "from_w": round(from_w, 6),
            "to_w": round(to_w, 6),
            "est_cost": round(cost, 8),
            "side": "buy" if delta > 0 else "sell",
            "max_single_weight": max_single_weight if max_single_weight is not None else 0.10,
        })
        turnover += abs(delta)
        fee_total += cost
    return RebalancePlan(
        trades=trades,
        turnover=round(turnover, 6),
        fee_total=round(fee_total, 8),
    )
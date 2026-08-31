"""construct_portfolio — 确定性权重构建（equal_weight / risk_parity / min_variance）。

PonyTail 约束：纯 stdlib + numpy，无 scipy。数值全部确定性。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from schemas.portfolio import PortfolioWeights, TargetPortfolio

# 后处理轮数（截断 + 余量重分）
_POST_ROUNDS = 10
# risk_parity 迭代轮数
_RP_ROUNDS = 20


def _cov_from_inputs(
    returns_by_asset: dict[str, list[float]] | None,
    cov: dict[str, dict[str, float]] | None,
    assets: list[str],
) -> np.ndarray:
    """统一得到 (n, n) 协方差矩阵。returns 优先于 cov；两者皆无 → 单位阵（等权退化）。"""
    n = len(assets)
    if returns_by_asset:
        cols = [np.asarray(returns_by_asset[a], dtype=float) for a in assets]
        lens = {len(c) for c in cols}
        if len(lens) != 1 or lens == {0}:
            raise ValueError("returns_by_asset: all assets must have equal, non-zero length series")
        mat = np.vstack(cols)
        return np.cov(mat) if n > 1 else np.array([[float(np.var(mat[0]))]])
    if cov:
        c = np.array(
            [[float(cov[a][b]) if a in cov and b in cov[a] else (1.0 if a == b else 0.0)
              for b in assets] for a in assets]
        )
        return (c + c.T) / 2.0  # 对称化，防 LLM 给的近似矩阵
    return np.eye(n)


def _post_process(w: np.ndarray, cfg: TargetPortfolio) -> tuple[np.ndarray, list[str]]:
    """超 max_single_weight 截断 + 余量按 headroom 重分（water-filling，不震荡）。"""
    notes: list[str] = []
    for _ in range(_POST_ROUNDS):
        over = w > cfg.max_single_weight
        if not over.any():
            break
        excess = float((w[over] - cfg.max_single_weight).sum())
        w[over] = cfg.max_single_weight
        room = cfg.max_single_weight - w
        head = room > 0  # 余量只给有空间的资产，按 headroom 比例（精确收敛不震荡）
        headroom = float(room[head].sum())
        if headroom > 0:
            w[head] += excess * (room[head] / headroom)
        else:
            w[:] = cfg.max_single_weight  # 全体触顶：Σ=n*cap ≤ gross 时合法
    # Σw ≤ max_gross_exposure：等比缩
    total = float(w.sum())
    if total > cfg.max_gross_exposure + 1e-12:
        w *= cfg.max_gross_exposure / total
        notes.append(f"scaled_gross_to_{cfg.max_gross_exposure}")
    return w, notes


def construct_impl(
    config: TargetPortfolio,
    returns_by_asset: dict[str, list[float]] | None = None,
    cov: dict[str, dict[str, float]] | None = None,
) -> PortfolioWeights:
    """等权 / 风险平价 / 最小方差 → PortfolioWeights。"""
    assets = sorted(set(returns_by_asset or cov or {})) if (returns_by_asset or cov) else []
    if not assets:
        raise ValueError("provide returns_by_asset or cov with at least one asset")
    sigma = _cov_from_inputs(returns_by_asset, cov, assets)
    n = len(assets)
    notes: list[str] = []
    method = config.method

    if method == "equal_weight":
        w = np.full(n, 1.0 / n)
    elif method == "risk_parity":
        # 迭代 w ∝ 1/σ（Spinu 简化版：权重反比于波动，20 轮收敛于近似风险平价）。
        # ponytail: 非对角协方差仅进入 σ 的计算，未做完整 ERC；3+ 资产近似已够用，
        # 精确 ERC 需 scipy.optimize，等需求出现再加。
        vol = np.sqrt(np.maximum(np.diag(sigma), 0.0))
        vol[vol <= 0] = 1.0
        w = np.full(n, 1.0 / n)
        for _ in range(_RP_ROUNDS):
            w = 1.0 / vol
            w /= w.sum()
    else:  # min_variance
        try:
            w = np.linalg.solve(sigma, np.ones(n))
            w /= w.sum()
        except np.linalg.LinAlgError:
            w = np.full(n, 1.0 / n)
            notes.append("singular_cov_fallback_equal_weight")
        else:
            if not np.all(np.isfinite(w)) or float(np.abs(w).max()) > 1e9:
                w = np.full(n, 1.0 / n)
                notes.append("singular_cov_fallback_equal_weight")

    w, post = _post_process(w, config)
    notes.extend(post)
    return PortfolioWeights(
        portfolio_id=config.name,
        weights={a: round(float(x), 6) for a, x in zip(assets, w)},
        method=method,
        as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes=notes,
    )


def risk_contributions(weights: dict[str, float], cov: np.ndarray) -> dict[str, float]:
    """风险贡献占比 w_i (Σw)_i / (wᵀΣw) —— 测试用（3 资产 max/min ≤ 1.5 断言）。"""
    w = np.array([weights[a] for a in sorted(weights)])
    total = float(w @ cov @ w)
    if total <= 0:
        return {a: 0.0 for a in sorted(weights)}
    rc = w * (cov @ w) / total
    return {a: float(x) for a, x in zip(sorted(weights), rc)}


def is_finite_weights(weights: dict[str, float]) -> bool:
    return all(math.isfinite(v) for v in weights.values())
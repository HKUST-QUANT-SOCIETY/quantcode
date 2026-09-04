"""真实数据因子评估流（FactorPanel → FactorReport 兼容 dict → 验收）。

与 flows/factor_evaluation_adapter.py（mock AutoEval API 路径）互补：本流不依赖外部
AutoEval 服务，直接对 Blackboard ``shared.datasets.panel/*`` 的 FactorPanel
契约数据算真实统计（纯 numpy；scipy 不在运行依赖里，rank 自实现）。

统计口径（engine="panel_real_v1"）：
- 收益代理：**代理收益 = 次日因子值变化率**（因子动量）。qs-cold staging
  无 A 股收益表（SPEC §5，tools/market/backing.load_returns 返回 no_source），
  真行情接入前用代理并显著标注 —— 这是口径决策，留给 R3 域替换为
  StockDailyBar.Return（替换点：build_returns_from_panel）。
- rank IC：逐截面 Spearman（纯 numpy 平均秩后 Pearson）。
- 换手率：top decile 资产集合相邻评估日 Jaccard 距离均值，按 21 交易日
  窗口折算月度口径。
- 分层：因子值 5 分位，各层代理收益均值 + 多空差。

产出 dict 与 schemas/factor.py FactorReport 字段兼容，verdict 判定走
runner/acceptance.factor_thresholds()（configs/acceptance.factor.yaml 单源），
并调用 run_acceptance("factor:evaluation", report) 做验收复核（只调用不改）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from schemas.factor import FactorVerdict
from tools.utils.paths import safe_filename_component

TRADING_DAYS_PER_MONTH = 21
ENGINE = "panel_real_v1"
N_LAYERS = 5


# ---------------------------------------------------------------------------
# numpy 基元（scipy 不在依赖里）
# ---------------------------------------------------------------------------


def _rankdata(a: np.ndarray) -> np.ndarray:
    """平均秩 rankdata（并列取均秩），scipy.stats.rankdata 的最小等价实现。"""
    order = np.argsort(a, kind="mergesort")
    sorted_a = a[order]
    ranks = np.empty(a.shape[0], dtype=float)
    i = 0
    n = a.shape[0]
    while i < n:
        j = i
        while j + 1 < n and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    sx, sy = x.std(), y.std()
    if x.shape[0] < 2 or sx == 0 or sy == 0:
        return float("nan")
    return float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy))


# ---------------------------------------------------------------------------
# 核心统计
# ---------------------------------------------------------------------------


def rank_ic_per_date(values: np.ndarray, returns: np.ndarray) -> np.ndarray:
    """逐日截面 Spearman rank IC（长度 = len(dates)；样本 <2 或截面常数 → NaN）。"""
    rank_v = np.apply_along_axis(_rankdata, 1, values)
    rank_r = np.apply_along_axis(_rankdata, 1, returns)
    out = np.full(values.shape[0], np.nan)
    for k in range(values.shape[0]):
        mask = ~(np.isnan(rank_v[k]) | np.isnan(rank_r[k]))
        if mask.sum() < 2:
            continue
        out[k] = _pearson(rank_v[k][mask], rank_r[k][mask])
    return out


def ic_metrics(ics: np.ndarray) -> dict[str, float] | None:
    """ic_mean / ic_std / ir / t_stat；有效样本 <2 时 None。"""
    valid = ics[~np.isnan(ics)]
    if valid.shape[0] < 2:
        return None
    ic_mean = float(valid.mean())
    ic_std = float(valid.std())
    ir = ic_mean / ic_std if ic_std > 0 else 0.0
    t_stat = ic_mean / (ic_std / math.sqrt(valid.shape[0])) if ic_std > 0 else 0.0
    return {"ic_mean": ic_mean, "ic_std": ic_std, "ir": ir, "t_stat": t_stat}


def turnover_monthly(values: np.ndarray) -> float | None:
    """top decile 相邻评估日 Jaccard 距离均值 × 21 / 相邻评估间隔天数。

    评估间隔天数取面板相邻日期差的中位数（交易日近似）；样本不足 → None。
    """
    n_dates, n_assets = values.shape
    if n_dates < 2:
        return None
    k = max(1, n_assets // 10)
    sets: list[frozenset[int]] = []
    kept: list[int] = []
    for t in range(n_dates):
        row = values[t]
        if np.all(np.isnan(row)):
            continue
        sets.append(frozenset(np.argsort(-row)[:k].tolist()))
        kept.append(t)
    spans = [b - a for a, b in zip(kept, kept[1:])]
    if not spans:
        return None
    span_days = float(np.median(spans))
    jac = [1.0 - len(a & b) / len(a | b) for a, b in zip(sets, sets[1:]) if a | b]
    if not jac:
        return None
    per_day = float(np.mean(jac)) / span_days
    return per_day * TRADING_DAYS_PER_MONTH


def layered_returns(values: np.ndarray, returns: np.ndarray) -> list[float] | None:
    """因子值 5 分位分层代理收益均值（低→高 Q1..Q5）；样本不足 → None。"""
    n_dates, n_assets = values.shape
    sums = np.zeros(N_LAYERS)
    counts = np.zeros(N_LAYERS, dtype=int)
    for t in range(n_dates):
        v, r = values[t], returns[t]
        mask = ~(np.isnan(v) | np.isnan(r))
        vm, rm = v[mask], r[mask]
        if vm.shape[0] < N_LAYERS:
            continue
        edges = np.quantile(vm, [i / N_LAYERS for i in range(1, N_LAYERS)])
        idx = np.searchsorted(edges, vm, side="left")
        sums += np.bincount(idx, weights=rm, minlength=N_LAYERS)
        counts += np.bincount(idx, minlength=N_LAYERS)
    if counts.min() == 0:
        return None
    return [float(sums[i] / counts[i]) for i in range(N_LAYERS)]


# ---------------------------------------------------------------------------
# 代理收益（次日因子值变化率）
# ---------------------------------------------------------------------------


def proxy_returns(values: np.ndarray) -> np.ndarray:
    """代理收益 = 次日因子值变化率，对齐到 T-1 行（T0 行 NaN，不做前视）。

    ponytail: 真行情接入前用因子动量作代理收益并显著标注——这是口径决策，
    留给 R3 域替换（build_returns_from_panel 是唯一替换点）。
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        step = values[1:] / values[:-1] - 1.0
    return np.vstack([np.full(values.shape[1], np.nan), step])


def build_returns_from_panel(values: np.ndarray) -> np.ndarray:
    """收益装配单点：R3 域接入真实行情（StockDailyBar.Return / ReturnsDataset）后只改这里。"""
    return proxy_returns(values)


# ---------------------------------------------------------------------------
# 主入口：FactorPanel → FactorReport 兼容 dict + acceptance
# ---------------------------------------------------------------------------


def evaluate_factor_panel(panel: Any) -> dict[str, Any]:
    """FactorPanel（契约对象）→ ``{"report", "acceptance", "artifacts", ...}``。

    report 为 FactorReport 兼容 dict（额外带 engine / proxy_return_warning /
    layer_mean_proxy_returns / n_ic_observations 扩展键，schemas.factor 侧
    只消费核心字段的调用方不受影响）。数据不足以算统计时返回 error 对象。
    """
    factor_name = getattr(panel, "factor_id", None) or "unknown"
    dates = list(getattr(panel, "dates"))
    values = np.asarray(getattr(panel, "values"), dtype=float)
    if values.ndim != 2 or values.shape[0] != len(dates):
        return {
            "error": "invalid_panel_shape",
            "detail": f"values shape {values.shape} vs len(dates) {len(dates)}",
        }
    if values.shape[0] < 3 or values.shape[1] < 2:
        return {
            "error": "panel_too_small",
            "detail": f"need >=3 dates x >=2 assets, got {values.shape}",
        }

    returns = build_returns_from_panel(values)
    ics = rank_ic_per_date(values, returns)
    m = ic_metrics(ics)
    if m is None:
        return {
            "error": "not_enough_ic_observations",
            "detail": "fewer than 2 cross-sections produced a valid rank IC",
        }

    n_obs = ics[~np.isnan(ics)].shape[0]
    turnover = turnover_monthly(values)
    layers = layered_returns(values, returns)
    if turnover is None or layers is None:
        return {
            "error": "not_enough_observations_for_turnover_or_layering",
            "detail": f"turnover={turnover}, layers={layers}",
        }

    verdict, fail_reasons = _verdict_from_thresholds(
        ic_mean=m["ic_mean"], ir=m["ir"],
        turnover_monthly=turnover, t_stat=m["t_stat"],
    )
    long_short = layers[-1] - layers[0]

    report: dict[str, Any] = {
        "factor_name": factor_name,
        "factor_version": getattr(panel, "factor_version", None),
        "evaluation_period": {
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
        },
        "universe": "panel",
        "ic_metrics": {"ic_method": "spearman", **m},
        "turnover": {"monthly": turnover},
        "decay": {"ic_1d": m["ic_mean"], "ic_3d": None, "ic_5d": None,
                  "ic_10d": None, "ic_20d": None},
        "layered_backtest": {
            "top_decile_annual_return": None,
            "bottom_decile_annual_return": None,
            "long_short_annual_return": long_short,
            "long_short_sharpe": None,
        },
        "verdict": verdict,
        "fail_reasons": fail_reasons,
        "eval_run_id": f"{factor_name}-{ENGINE}",
        # ---- FactorReport 之外的扩展字段（诚实标注，见模块 docstring）----
        "engine": ENGINE,
        "proxy_return_warning": (
            "代理收益=次日因子值变化率（因子动量），非真实行情收益；"
            "结论仅供管线联调，不得用于入池决策"
            "（R3 域接入 StockDailyBar.Return 后经 build_returns_from_panel 替换）"
        ),
        "layer_mean_proxy_returns": {str(i): layers[i] for i in range(N_LAYERS)},
        "n_ic_observations": int(n_obs),
    }

    from runner.acceptance import run_acceptance

    result = run_acceptance("factor:evaluation", report)
    acceptance = {
        "verdict": result.verdict,
        "checks": [
            {"name": c.name, "passed": c.passed, "message": c.message}
            for c in result.checks
        ],
    }

    artifact = _write_artifact(factor_name, report, acceptance)
    return {
        "report": report,
        "acceptance": acceptance,
        "artifacts": [artifact],
        "engine": ENGINE,
        "proxy_return_warning": report["proxy_return_warning"],
    }


# ---------------------------------------------------------------------------
# verdict（阈值单源 configs/acceptance.factor.yaml）+ 工件
# ---------------------------------------------------------------------------


def _verdict_from_thresholds(
    *, ic_mean: float, ir: float, turnover_monthly: float, t_stat: float
) -> tuple[str, list[str]]:
    """阈值走 runner.acceptance.factor_thresholds()（yaml 优先/代码默认兜底）。"""
    from runner.acceptance import factor_thresholds

    t = factor_thresholds()
    fails: list[str] = []
    if abs(ic_mean) < t["ic_abs_min"]:
        fails.append(f"|ic_mean| {abs(ic_mean):.4f} < {t['ic_abs_min']}")
    if ir < t["ir_min"]:
        fails.append(f"ir {ir:.4f} < {t['ir_min']}")
    if turnover_monthly > t["turnover_monthly_max"]:
        fails.append(
            f"turnover_monthly {turnover_monthly:.4f} > {t['turnover_monthly_max']}"
        )
    if t_stat < t["t_stat_min"]:
        fails.append(f"t_stat {t_stat:.4f} < {t['t_stat_min']}")
    if fails:
        return FactorVerdict.FAIL.value, fails
    return FactorVerdict.PASS.value, []


def _write_artifact(
    factor_name: str, report: dict[str, Any], acceptance: dict[str, Any]
) -> str:
    out = {"report": report, "acceptance": acceptance}
    path = Path("artifacts") / "factor" / f"{safe_filename_component(factor_name)}-report-real.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path.as_posix()


__all__ = [
    "ENGINE",
    "build_returns_from_panel",
    "evaluate_factor_panel",
    "ic_metrics",
    "layered_returns",
    "proxy_returns",
    "rank_ic_per_date",
    "turnover_monthly",
]

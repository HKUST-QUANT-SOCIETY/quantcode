"""calc_risk 真值化测试 — calc_risk_from_returns 手算对照 + 诚实标记。

手算基准序列 r = [0.01, -0.02, 0.03, -0.01, 0.02, 0.01]（n=6，按时间原序）：

- tail_risk_var_99：排序后 [-0.02, -0.01, 0.01, 0.01, 0.02, 0.03]，
  1% 分位数 pos=(6-1)*0.01=0.05，线性插值 -0.02*0.95 + (-0.01)*0.05 = -0.0195，
  VaR99 = -(-0.0195) = 0.0195（损失幅度，正数）
- max_drawdown：净值 1.01 → 0.9898 → 1.019494 → 1.00929906 → 1.0294850412 → 1.039779891612
  峰值回撤：第2步 (1.01-0.9898)/1.01 = 0.02；第4步 (1.019494-1.00929906)/1.019494 = 0.01
  → max_drawdown = 0.02
- sharpe = mean/std*sqrt(252)；volatility = std*sqrt(252)
  mean = 0.04/6 = 1/150；Σ(x-mean)² = 13/7500；样本方差 = 13/37500（n-1）
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from schemas.risk_profile import RiskProfile
from tools.risk.risk_tools import calc_risk, generate_risk_profile
from tools.risk.statistics_stub import calc_risk_from_returns

RETURNS = [0.01, -0.02, 0.03, -0.01, 0.02, 0.01]


def _sample_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. calc_risk_from_returns 纯函数手算对照
# ---------------------------------------------------------------------------


def test_var_99_matches_hand_computed_quantile():
    computed = calc_risk_from_returns(RETURNS)
    # 线性插值 1% 分位数 = -0.02*0.95 + (-0.01)*0.05 = -0.0195 → 损失幅度 0.0195
    assert computed["tail_risk_var_99"] == pytest.approx(0.0195, abs=1e-9)


def test_max_drawdown_matches_hand_computed_peak_drawdown():
    computed = calc_risk_from_returns(RETURNS)
    assert computed["max_drawdown"] == pytest.approx(0.02, abs=1e-9)


def test_sharpe_and_volatility_match_spec_formula():
    computed = calc_risk_from_returns(RETURNS)
    # 用测试侧独立原语重推 spec 公式（mean/std*sqrt(252)，std 为样本标准差 n-1）
    mean = sum(RETURNS) / len(RETURNS)
    variance = sum((x - mean) ** 2 for x in RETURNS) / (len(RETURNS) - 1)
    std = variance**0.5
    assert computed["sharpe"] == pytest.approx(mean / std * math.sqrt(252), abs=1e-9)
    assert computed["volatility"] == pytest.approx(std * math.sqrt(252), abs=1e-9)


def test_max_drawdown_respects_time_order_not_sorted_order():
    # 时间序 [0.5, -0.1, -0.1]：净值 1.5 → 1.35 → 1.215，回撤 = 1 - 1.215/1.5 = 0.19
    # 若错误地按排序序累计会得到 0.10 —— 断言 0.19 防止排序实现回归
    computed = calc_risk_from_returns([0.5, -0.1, -0.1])
    assert computed["max_drawdown"] == pytest.approx(0.19, abs=1e-9)


def test_constant_returns_zero_std_gives_zero_sharpe_and_vol():
    computed = calc_risk_from_returns([0.01, 0.01, 0.01])
    assert computed["sharpe"] == 0.0
    assert computed["volatility"] == 0.0
    assert computed["max_drawdown"] == 0.0


def test_rejects_invalid_returns():
    with pytest.raises(ValueError):
        calc_risk_from_returns([])  # 空
    with pytest.raises(ValueError):
        calc_risk_from_returns([0.01])  # 少于 2 个
    with pytest.raises(ValueError):
        calc_risk_from_returns([0.01, -1.0])  # 简单收益率 <= -1 会使净值非正
    with pytest.raises(ValueError):
        calc_risk_from_returns([0.01, "0.02"])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# 2. calc_risk returns 路径 + 无 returns 诚实标记
# ---------------------------------------------------------------------------


def test_calc_risk_without_returns_keeps_stub_and_marks_stub():
    model_spec = _sample_model_spec()
    metrics = calc_risk(model_spec, scenario="normal")

    # 现 stub 行为保持不变
    assert metrics["max_drawdown"] == 0.08
    assert metrics["tail_risk_var_99"] == 0.025
    # 诚实标记：RiskProfile extra=forbid，标记放现有字段 analyst_notes，后缀 _is_stub
    assert "_is_stub" in metrics["analyst_notes"]
    assert metrics["analyst_notes"].endswith("_is_stub")


def test_calc_risk_with_returns_overrides_computed_metrics():
    model_spec = _sample_model_spec()
    metrics = calc_risk(model_spec, scenario="normal", returns=RETURNS)

    expected = calc_risk_from_returns(RETURNS)
    assert metrics["max_drawdown"] == pytest.approx(expected["max_drawdown"], abs=1e-12)
    assert metrics["tail_risk_var_99"] == pytest.approx(expected["tail_risk_var_99"], abs=1e-12)
    assert metrics["volatility"] == pytest.approx(expected["volatility"], abs=1e-12)
    assert metrics["strategy_id"] == "pb_roe_ranker"
    # 诚实标注：真值来源 + 哪些字段仍是 stub
    assert "computed from" in metrics["analyst_notes"]
    assert "sharpe=" in metrics["analyst_notes"]
    assert metrics["analyst_notes"].endswith("_is_stub")


def test_calc_risk_returns_path_flows_into_risk_profile():
    """returns 路径输出仍能构造 RiskProfile（extra=forbid 不炸），标记落 analyst_notes。"""
    model_spec = _sample_model_spec()
    metrics = calc_risk(model_spec, scenario="normal", returns=RETURNS)

    profile = generate_risk_profile(model_spec, metrics)
    assert isinstance(profile, RiskProfile)
    assert profile.max_drawdown == pytest.approx(0.02, abs=1e-9)
    assert profile.analyst_notes is not None
    assert "_is_stub" in profile.analyst_notes

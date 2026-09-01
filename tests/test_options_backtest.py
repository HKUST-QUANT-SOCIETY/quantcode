"""tests/test_options_backtest.py — options_v1 引擎验收（对齐 test_backtest_engine 风格）。

覆盖：
- 手算对照：单 call 腿 5 日，每日 option 价 = BS 公式手工（erf 正态 CDF），
  逐日净值/累计 PnL 断言 1e-9（quantity=1 张，乘数 100 内置）
- 到期结算：ITM call 按内在价值入现金；OTM call 归零（legs_closed）
- theta 衰减方向：平价不动，BS 重定价净值逐日下降（净值为正衰减）
- put 方向：标的下跌逐日净值上升
- 参数注入：params 覆盖优先；configs/options_backtest.yaml 交付默认值
- 空数据/非法腿 error 对象
- wrapper（registry 调用路径）：旧签名兼容 + engine 标注 + schema 校验

手算时序约定（与引擎一致，注释独立推导非复用引擎代码）：
- t0 收盘建仓付 premium×100 + commission；到期日 t 结算内在价值（×100）入现金
- V(t) = BS(S[t], K, tau/365, r=0, vol=0.2)，tau = 到期日 - t（固定到期日，非滚动 offset）
"""
from __future__ import annotations

import importlib
import math
from datetime import date

import pytest

from schemas.options import OptionsBacktestReport
from tools.options.backtest_engine import (
    DEFAULT_PARAMS,
    ENGINE_VERSION,
    load_params,
    run_options_backtest,
)

EPS = 1e-9
D0 = date(2026, 1, 1)


def _approx(a: float, b: float, tol: float = EPS) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


def _n(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call(s: float, k: float, t_years: float, sigma: float = 0.2, r: float = 0.0) -> float:
    """独立参照实现（手算基准）：d1/d2 直接按定义展开。"""
    if t_years <= 0:
        return max(s - k, 0.0)
    sq = math.sqrt(t_years)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sq)
    d2 = d1 - sigma * sq
    return s * _n(d1) - k * math.exp(-r * t_years) * _n(d2)


def _legs_call(k: float, expiry_t: int, days: int, qty: int = 1) -> list[list[dict]]:
    """每天重列同一固定到期日腿（day t 给 expiry_offset_days = expiry_t - t）。"""
    return [
        [{"leg_type": "call", "strike": k, "expiry_offset_days": expiry_t - t, "quantity": qty}]
        if t < expiry_t
        else []
        for t in range(days)
    ]


# ---------------------------------------------------------------------------
# 手算对照：单 call 腿 5 日（价 100→101→102→101→103，到期日 t=6）
# ---------------------------------------------------------------------------

MAIN_PRICES = [100.0, 101.0, 102.0, 101.0, 103.0]
# 手算锚点：V(t) = BS(S[t], 100, (6-t)/365, 0, 0.2)；cash = 1e5 - V0*100 - 1
V_MAIN = [1.0229569471761195, 1.522032000729368, 2.195106611674902, 1.3337598010313485, 3.0128742152604104]
NAV_MAIN = [99999.0, 100048.9075053553, 100116.2149664499, 100030.0802853855, 100197.9917268084]


def test_hand_calculated_pnl_1e9():
    out = run_options_backtest(MAIN_PRICES, _legs_call(100.0, 6, 5), start_date=D0)
    assert out["engine"] == ENGINE_VERSION == "options_v1"
    assert len(out["net_value"]) == 5
    cap = DEFAULT_PARAMS["initial_capital"]
    for i, nav_expect in enumerate(NAV_MAIN):
        assert _approx(out["net_value"][i], nav_expect / cap, 1e-9), f"nav[{i}]"
    assert _approx(out["total_pnl"], NAV_MAIN[4] - cap, 1e-9)
    # 逐日 PnL = 精确期权市值差 ×100×qty（净值为 10 位舍入，差分对照用精确锚点）
    assert _approx(out["daily_pnl"][0], -1.0, 1e-9)
    diffs = [(V_MAIN[i] - V_MAIN[i - 1]) * 100 for i in range(1, 5)]
    # t3 (101) 例外：V3 < V2，差分 -86.1347
    assert _approx(out["daily_pnl"][1], diffs[0], 1e-7)
    assert _approx(out["daily_pnl"][3], diffs[2], 1e-7)
    # 佣金：t0 建仓 1 次，固定到期日同腿重列不重复计费
    assert _approx(out["fee_total"], 1.0, 1e-9)
    assert out["trade_count"] == 4
    assert out["legs_closed"] == 0  # 到期日 t=6 在窗口外
    # 独立锚点抽查：V(t1) 与 t1 净值
    assert _approx(_bs_call(101.0, 100.0, 5 / 365.0), V_MAIN[1], 1e-12)
    assert _approx(out["net_value"][1], 100048.9075053553 / cap, 1e-9)
    # 指标一致性
    assert out["sharpe"] is not None and 0 <= out["max_drawdown"] <= 1


def test_expiry_itm_call_settles_intrinsic():
    prices = [100.0, 101.0, 102.0, 103.0, 104.0]  # 到期日 t=3, 结算价 103 → 内在 3.0×100
    out = run_options_backtest(prices, _legs_call(100.0, 3, 5), start_date=D0)
    assert out["legs_closed"] == 1
    cap = DEFAULT_PARAMS["initial_capital"]
    cash = cap - _bs_call(100.0, 100.0, 3 / 365.0) * 100 - 1.0
    nav_expect = [
        cash + 100 * _bs_call(100.0, 100.0, 3 / 365.0),
        cash + 100 * _bs_call(101.0, 100.0, 2 / 365.0),
        cash + 100 * _bs_call(102.0, 100.0, 1 / 365.0),
        cash + 300.0,  # 到期：内在价值 max(103-100,0)×100
        cash + 300.0,
    ]
    for i, want in enumerate(nav_expect):
        assert _approx(out["net_value"][i], want / cap, 1e-9), f"nav[{i}]"
    assert _approx(out["total_pnl"], 226.6650297121, 1e-7)
    # 到期后期权市值为 0（value 不再计入）
    assert _approx(out["net_value"][3], out["net_value"][4], 1e-12)


def test_expiry_otm_call_worthless():
    prices = [100.0, 99.5, 99.0, 98.5, 98.0]
    out = run_options_backtest(prices, _legs_call(100.0, 3, 5), start_date=D0)
    assert out["legs_closed"] == 1
    cap = DEFAULT_PARAMS["initial_capital"]
    V = [_bs_call(prices[i], 100.0, (3 - i) / 365.0) for i in range(3)]
    cash = cap - V[0] * 100 - 1.0
    nav_expect = [cash + 100 * V[0], cash + 100 * V[1], cash + 100 * V[2], cash, cash]
    for i, want in enumerate(nav_expect):
        assert _approx(out["net_value"][i], want / cap, 1e-9), f"nav[{i}]"
    assert out["total_pnl"] < 0  # 权利金全损


def test_theta_decay_direction_net_decreasing():
    """平价不动：BS 逐日重定价内含时间价值衰减 → 净值逐日下降。"""
    out = run_options_backtest(
        [100.0] * 5, _legs_call(100.0, 4, 5), start_date=D0
    )
    net = out["net_value"]
    assert len(net) == 5
    for i in range(1, 5):
        assert net[i] < net[i - 1], f"expected decay at t{i}: {net}"
    assert out["legs_closed"] == 1
    # 手算锚点：V(4d)=0.8352484775 → V(3d)=0.7233497029，日衰减 0.1119×100/1e5
    cap = DEFAULT_PARAMS["initial_capital"]
    assert _approx(net[0] - net[1], (0.8352484775 - 0.7233497029) * 100 / cap, 1e-9)
    assert out["total_pnl"] < 0


def test_put_leg_direction_up_when_spot_falls():
    """put 腿：标的下跌逐日盯市净值上升（方向对照；到期结算内在 3.0×100）。"""
    out = run_options_backtest(
        [100.0, 99.0, 98.0, 97.0],
        [
            [{"leg_type": "put", "strike": 100.0, "expiry_offset_days": 3 - t, "quantity": 1}]
            if t < 3
            else []
            for t in range(4)
        ],
        start_date=D0,
    )
    net = out["net_value"]
    assert net[1] > net[0] and net[2] > net[1]
    assert out["legs_closed"] == 1
    # 精确手算（nav0 = cap - 建仓费，因 cash+value 抵消 premium）：
    # nav0 = cap - 1；nav3 = cap - 建仓费 - V0*100 + 内在 300
    cap = DEFAULT_PARAMS["initial_capital"]
    from tools.options.build_vol_surface import _bs_price

    v0 = _bs_price(100.0, 100.0, 3 / 365.0, 0.0, 0.2, False)
    assert _approx(net[0], (cap - 1.0) / cap, 1e-9)
    assert _approx(net[3], (cap - 1.0 - v0 * 100 + 300.0) / cap, 1e-9)  # 结算内在 3.0×100


# ---------------------------------------------------------------------------
# 参数注入与空数据
# ---------------------------------------------------------------------------

def test_params_override_and_config_default():
    # t0 建 ATM call（tau=1/365），t1 到期结算内在 max(11-10,0)×100=100 入现金
    out = run_options_backtest(
        [10.0, 11.0],
        [[{"leg_type": "call", "strike": 10.0, "expiry_offset_days": 1, "quantity": 1}], []],
        params={"initial_capital": 50000.0, "commission": 2.0},
    )
    v0 = _bs_call(10.0, 10.0, 1 / 365.0)
    assert _approx(out["total_pnl"], -v0 * 100 - 2.0 + 100.0, 1e-9)
    assert out["params_used"]["initial_capital"] == 50000.0
    assert _approx(out["fee_total"], 2.0, 1e-9)
    # load_params 读 configs/options_backtest.yaml 交付默认
    p = load_params()
    assert p["initial_capital"] == 100000.0
    assert p["commission"] == 1.0
    assert p["implied_vol"] == 0.20
    assert p["risk_free_rate"] == 0.0


def test_empty_data_error_object():
    with pytest.raises(ValueError, match="underlying_prices must be non-empty"):
        run_options_backtest([], [])
    with pytest.raises(ValueError, match="positions length"):
        run_options_backtest([100.0], [])
    with pytest.raises(ValueError, match="leg_type"):
        run_options_backtest(
            [100.0, 101.0],
            [[{"leg_type": "warrant", "strike": 100.0, "expiry_offset_days": 1, "quantity": 1}], []],
        )
    with pytest.raises(ValueError, match="quantity"):
        run_options_backtest(
            [100.0, 101.0],
            [[{"leg_type": "call", "strike": 100.0, "expiry_offset_days": 1, "quantity": 0}], []],
        )
    with pytest.raises(ValueError, match="strike"):
        run_options_backtest(
            [100.0, 101.0],
            [[{"leg_type": "call", "strike": 0.0, "expiry_offset_days": 1, "quantity": 1}], []],
        )
    with pytest.raises(ValueError, match="must be > 0"):
        run_options_backtest([100.0, -1.0], [[], []])


# ---------------------------------------------------------------------------
# 工具层（wrapper）联动：旧签名 + engine 标注 + schema 校验
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_registered():
    import tools.options._register  # noqa: F401

    importlib.reload(tools.options._register)
    yield


def test_wrapper_old_signature_engine_mark():
    from tools.registry import registry

    args = {
        "strategy_name": "gc_vol_carry",
        "underlying": "GC",
        "start_date": "2026-01-01",
        "end_date": "2026-06-27",
    }
    raw = registry.call("run_options_backtest_stub", args)
    assert raw["engine"] == "options_v1"
    assert raw["strategy_name"] == "gc_vol_carry"
    assert raw["underlying"] == "GC"
    assert "stub" not in str(raw["notes"])
    assert 0 <= raw["max_drawdown"] <= 1
    assert isinstance(raw["net_value"], list) and len(raw["net_value"]) >= 2
    report = OptionsBacktestReport.model_validate(raw)
    assert report.engine == "options_v1"
    # 确定性：同参重跑结果一致（合成价格 + 纯函数引擎）
    raw2 = registry.call("run_options_backtest_stub", args)
    assert raw2["total_pnl"] == raw["total_pnl"]
    assert raw2["net_value"] == raw["net_value"]


def test_wrapper_explicit_prices_and_positions():
    from tools.registry import registry

    raw = registry.call(
        "run_options_backtest_stub",
        {
            "strategy_name": "gc_call_5d",
            "underlying": "GC",
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "underlying_prices": MAIN_PRICES,
            "positions": _legs_call(100.0, 6, 5),
        },
    )
    assert raw["engine"] == "options_v1"
    assert raw["trade_count"] == 4
    cap = DEFAULT_PARAMS["initial_capital"]
    assert _approx(raw["total_pnl"], NAV_MAIN[4] - cap, 1e-9)
    report = OptionsBacktestReport.model_validate(raw)
    assert report.legs_closed == 0


def test_wrapper_empty_period_zero_report():
    """零长度区间：wrapper 如实渲染 0 结果 + engine 标注（空输入报错路径在引擎层覆盖）。"""
    from tools.registry import registry

    raw = registry.call(
        "run_options_backtest_stub",
        {
            "strategy_name": "gc_vol_carry",
            "underlying": "GC",
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )
    assert raw["total_pnl"] == 0.0
    assert raw["engine"] == "options_v1"
    assert "empty period" in str(raw["notes"])
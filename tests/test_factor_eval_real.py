"""panel_real_v1 真实数据因子评估流断言（flows/factor_eval_real.py + 工具）。

fixture：合成 FactorPanel，30 交易日 × 10 资产，植入已知 rank 结构：
- 前瞻 fixture：资产 a 的代理收益（次日变化率）= g_a 严格递增，因子值幂增长
  保序 → 每个截面 rank IC = 1（仅 t=15 一次受控相邻倒挂，使 ic_std>0）；
- 换手与分层用手算对照；
- 面板 key 缺失 / 契约戳不对 → error 对象；
- verdict 与 configs/acceptance.factor.yaml 阈值联动。

代理收益口径 = 次日因子值变化率（因子动量），非真实行情收益。
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

import tools.factor._register as _factor_register  # noqa: F401
from schemas.data_contracts import CONTRACT_PANEL, FactorPanel
from tools.registry import registry

from flows.factor_eval_real import (
    ENGINE,
    ic_metrics,
    layered_returns,
    proxy_returns,
    rank_ic_per_date,
    turnover_monthly,
)

ASSET_COUNT = 10
DATE_COUNT = 30
TRADING_DAYS_PER_MONTH = 21


@pytest.fixture(autouse=True)
def _ensure_registered():
    # 全量 pytest 时其他测试文件会 registry._tools.clear() 清空全局单例；
    # reload 注册链（幂等）保证 eval_from_panel 已注册。
    importlib.reload(_factor_register)
    yield


def _assets() -> list[str]:
    return [f"{600000 + i}.SH" for i in range(ASSET_COUNT)]


def _dates() -> list[date]:
    # 30 个连续日历日当测试"交易日"（评估流只用相邻日差，不需要真交易日历）
    d0 = date(2026, 7, 6)
    return [d0 + timedelta(days=i) for i in range(DATE_COUNT)]


def _growth_grid() -> np.ndarray:
    """g[a] = 0.01*(a+1)：截面严格递增的"次日变化率"。"""
    return np.array([0.01 * (a + 1) for a in range(ASSET_COUNT)])


def _perfect_panel() -> FactorPanel:
    """因子完全前瞻 fixture：value[t,a] 按 g_a 复利累积。

    值幂增长保序（asset a 增速恒高于 b<a），故每个截面：
    因子值排序 == 次日变化率排序 → rank IC = 1。
    t=15 处对资产 8/9 的增长率做一次相邻倒挂 → 单截面 IC 略低于 1
    （其余全为 1），ic_mean ≈ 0.999，ic_std>0，t_stat / ir 巨大。
    """
    g = _growth_grid()
    values = np.empty((DATE_COUNT, ASSET_COUNT))
    values[0] = 1.0
    for t in range(1, DATE_COUNT):
        gt = g.copy()
        if t == 15:
            gt[8], gt[9] = gt[9], gt[8]
        values[t] = values[t - 1] * (1.0 + gt)
    return FactorPanel(
        factor_id="perfect_lead",
        factor_version="v1",
        data_snapshot_id="snap-test",
        dates=_dates(),
        assets=_assets(),
        values=values.tolist(),
        source_path="synthetic",
    )


# ---------------------------------------------------------------------------
# 统计核
# ---------------------------------------------------------------------------


def test_perfect_lead_ic_close_to_one():
    panel = _perfect_panel()
    values = np.asarray(panel.values, dtype=float)
    returns = proxy_returns(values)
    ics = rank_ic_per_date(values, returns)
    m = ic_metrics(ics)
    assert m is not None
    assert m["ic_mean"] > 0.95
    assert m["ic_std"] > 0  # t=15 的受控倒挂保证非退化
    assert m["ir"] > m["ic_mean"] * 10  # std 极小 → ir 巨大
    assert m["t_stat"] > 2.0


def test_rank_ic_direct_matrix():
    """直接构造矩阵对照：值恒为列号+1（保序），收益同序、仅一行相邻倒挂。"""
    values = np.tile(np.arange(1, ASSET_COUNT + 1, dtype=float), (DATE_COUNT, 1))
    returns = values - 1.0  # 任何严格递增截面都行
    returns[7, [4, 5]] = returns[7, [5, 4]]  # 一次受控倒挂
    ics = rank_ic_per_date(values, returns)
    valid = ics[~np.isnan(ics)]
    assert valid.shape[0] == DATE_COUNT
    assert valid.mean() > 0.95
    assert valid[7] < 1.0 and np.all(np.delete(valid, 7) == 1.0)


def test_proxy_returns_alignment_and_no_lookahead():
    """代理收益 = 次日变化率对齐到 T-1 行（T0 行 NaN）。行 1 的收益由行 0→1
    的变化算出，不使用行 1 之后的任何数据（无前视）。"""
    values = np.array([[100.0, 100.0], [200.0, 200.0], [400.0, 400.0]])
    rets = proxy_returns(values)
    assert np.isnan(rets[0]).all()
    assert rets[1] == pytest.approx([1.0, 1.0])
    assert rets[2] == pytest.approx([1.0, 1.0])


def test_turnover_hand_computed():
    """换手手算对照：top decile = 1 资产，在资产 0/1 间每 5 天轮换。

    相邻对共 29 个（30 日），切换发生在 t=5,10,15,20,25 → 5 个 Jaccard=1。
    连续日期 → 跨度中位数 1 → 月度换手 = (5/29)*21。
    """
    values = np.ones((DATE_COUNT, ASSET_COUNT))
    max_asset = 0
    for t in range(DATE_COUNT):
        if t > 0 and t % 5 == 0:
            max_asset = 0 if max_asset else 1
        values[t, max_asset] = 100.0
    got = turnover_monthly(values)
    expected = (5.0 / 29.0) * TRADING_DAYS_PER_MONTH
    assert got == pytest.approx(expected)


def test_layer_monotonicity():
    """5 分层单调性：完美前瞻 panel 下，代理收益按资产序号严格递增 →
    分层均值收益 Q1<Q2<...<Q5。"""
    values = np.asarray(_perfect_panel().values, dtype=float)
    returns = proxy_returns(values)
    layers = layered_returns(values, returns)
    assert layers is not None
    diffs = [b - a for a, b in zip(layers, layers[1:])]
    assert all(d > 0 for d in diffs), layers
    assert layers[-1] > layers[0]


# ---------------------------------------------------------------------------
# 工具路径：Blackboard 读写 + 错误对象
# ---------------------------------------------------------------------------


def _write_and_key(tmp_path: Path, panel: FactorPanel) -> tuple[Path, str]:
    from tools.market import backing

    db = tmp_path / "blackboard.db"
    written = backing.write_panel_to_blackboard(
        panel, blackboard_db_path=db, written_by_task_id="T1", written_by_group="factor"
    )
    return db, written["blackboard_key"]


def test_missing_panel_key_returns_error_object(tmp_path):
    from tools.factor.eval_from_panel import eval_from_panel_impl

    result = eval_from_panel_impl(
        "shared.datasets.panel/no_such_factor", blackboard_db_path=tmp_path / "bb.db"
    )
    assert result.get("error") == "panel_not_found"
    assert result["panel_key"] == "shared.datasets.panel/no_such_factor"


def test_bad_contract_stamp_returns_error_object(tmp_path):
    """无 _contract 戳的 payload → 契约校验失败 → 明确 error 对象（不崩溃）。"""
    from runner.blackboard import BlackboardService
    from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
    from schemas import BlackboardScope, GroupName, WritePolicy
    from tools.factor.eval_from_panel import eval_from_panel_impl

    db = tmp_path / "blackboard.db"
    _, key = _write_and_key(tmp_path, _perfect_panel())
    payload = FactorPanel.model_validate(
        {"factor_id": "x", "factor_version": "v", "data_snapshot_id": "s",
         "dates": [date(2026, 1, 1).isoformat(), date(2026, 1, 2).isoformat()],
         "assets": ["600000.SH"],
         "values": [[1.0], [2.0]], "source_path": "x"}
    )
    raw = payload.model_dump(mode="json")
    raw.pop("_contract", None)
    service = BlackboardService(
        db_path=db, session_id=PROJECT_SESSION_ID, requester_group=GroupName("factor")
    )
    service.write_value(
        scope=BlackboardScope.PROJECT,
        key=make_read_key(key),
        value=raw,
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T1",
        written_by_group=GroupName("factor"),
    )
    result = eval_from_panel_impl(key, blackboard_db_path=db)
    assert result.get("error") == "panel_contract_invalid"
    assert result["panel_key"] == key


def test_tool_real_data_end_to_end(tmp_path):
    """fixture panel → Blackboard → eval_from_panel → FactorReport 兼容 dict
    （engine=panel_real_v1），核心字段可反序列化为 schemas.factor.FactorReport。"""
    from schemas.factor import FactorReport
    from tools.factor.eval_from_panel import eval_from_panel_impl

    db, key = _write_and_key(tmp_path, _perfect_panel())
    result = eval_from_panel_impl(key, blackboard_db_path=db)
    assert "error" not in result, result
    assert result["engine"] == "panel_real_v1"
    report = result["summary"]
    assert report["engine"] == "panel_real_v1"
    assert report["ic_metrics"]["ic_mean"] > 0.95
    assert "proxy_return_warning" in report and report["proxy_return_warning"]
    # FactorReport 兼容：schema 声明字段可反序列化（扩展字段在 schema 之外）
    fr = FactorReport.model_validate(
        {k: v for k, v in report.items() if k in FactorReport.model_fields}
    )
    assert fr.factor_name == "perfect_lead"
    assert fr.evaluation_period.start == date(2026, 7, 6)
    assert fr.ic_metrics.ic_mean > 0.95


def test_verdict_linked_to_acceptance_thresholds(tmp_path):
    """verdict 联动阈值：ic 达标但 t_stat=0 (<2.0) → fail；全达标 → pass；
    run_acceptance("factor:evaluation") 与本判定同源。"""
    from flows.factor_eval_real import _verdict_from_thresholds
    from runner.acceptance import factor_thresholds, run_acceptance

    t = factor_thresholds()
    verdict, reasons = _verdict_from_thresholds(
        ic_mean=0.5, ir=3.0, turnover_monthly=0.1, t_stat=0.0
    )
    assert verdict == "fail"
    assert any("t_stat" in r for r in reasons)

    verdict_ok, reasons_ok = _verdict_from_thresholds(
        ic_mean=t["ic_abs_min"], ir=t["ir_min"],
        turnover_monthly=t["turnover_monthly_max"], t_stat=t["t_stat_min"],
    )
    assert verdict_ok == "pass" and reasons_ok == []
    payload = {"ic_metrics": {"ic_mean": t["ic_abs_min"], "ir": t["ir_min"],
                              "t_stat": t["t_stat_min"]},
               "turnover": {"monthly": t["turnover_monthly_max"]}}
    assert run_acceptance("factor:evaluation", payload).verdict == "pass"


def test_tool_registered_and_callable_via_registry(tmp_path):
    """registry.call('eval_from_panel') 全链：Blackboard → 真实统计 → 工件落盘。"""
    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = registry.call(
        "eval_from_panel",
        {"panel_key": key, "blackboard_db_path": str(db)},
        ctx={},
    )
    assert "error" not in out, out
    assert out["engine"] == "panel_real_v1"
    # summary 不含大矩阵（SPEC §2.3）
    assert "values" not in out["summary"]
    artifact = Path(out["artifacts"][0])
    assert artifact.exists()
    assert artifact.name == "perfect_lead-report-real.json"
    text = artifact.read_text(encoding="utf-8")
    assert "panel_real_v1" in text


def test_date_range_trim(tmp_path):
    """date_range 参数裁剪面板后再评估。"""
    from tools.factor.eval_from_panel import eval_from_panel_impl

    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = eval_from_panel_impl(
        key, date_range=["2026-07-06", "2026-07-15"], blackboard_db_path=db
    )
    assert "error" not in out, out
    assert out["summary"]["evaluation_period"]["end"] == "2026-07-15"


def test_engine_marker_constant():
    assert ENGINE == "panel_real_v1"
    assert CONTRACT_PANEL == "FactorPanel/v1"
"""eval_factor_panel 全链断言（tools/factor/eval_from_panel.py 任务签名版）。

fixture：合成因子动量 IR 序列（与 tests/test_factor_eval_real.py 同一套
perfect-lead 构造）：资产 a 的代理收益（次日变化率）g_a = 0.01*(a+1) 严格
递增，因子值幂增长保序 → 每个截面 rank IC ≈ 1（t=15 受控倒挂保证 ic_std>0
→ ir/t_stat 巨大）。换手/verdict 与 configs/acceptance.factor.yaml 联动。

覆盖：
- 合成 IR 序列统计核：ic_mean / ir / turnover 数量级对照；
- dataset 合成 + Blackboard 写入 + eval_factor_panel 全链（impl 与 registry.call）；
- acceptance pass（完美前瞻）/ fail（ic_abs_threshold 抬高 / 阈值联动）；
- 裸 factor id 的 dataset_key 归一（/ 决定是否展开 shared.datasets.panel/）；
- 契约转换 API：FactorPanel/ReturnsDataset 的 to_frame/to_records/from_records
  往返 + summary（DataFrame/records 等价表示，零 pandas 依赖）。
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

import tools.factor._register as _factor_register  # noqa: F401
from schemas.data_contracts import CONTRACT_PANEL, FactorPanel, ReturnsDataset
from tools.registry import registry

ASSET_COUNT = 10
DATE_COUNT = 30
TRADING_DAYS_PER_MONTH = 21
D0 = date(2026, 7, 6)


@pytest.fixture(autouse=True)
def _ensure_registered():
    # 全量 pytest 时其他测试文件会 registry._tools.clear() 清空全局单例；
    # reload 注册链（幂等）保证 eval_factor_panel / eval_from_panel 已注册。
    importlib.reload(_factor_register)
    yield


# ---------------------------------------------------------------------------
# 合成 IR fixture：perfect-lead 因子动量面板
# ---------------------------------------------------------------------------


def _perfect_panel(factor_id: str = "perfect_lead") -> FactorPanel:
    """代理收益 g_a = 0.01*(a+1) 严格递增，值幂增长保序 → 截面 rank IC ≈ 1。

    t=15 对资产 8/9 做一次相邻倒挂 → ic_std>0，ir/t_stat 非退化。
    """
    g = np.array([0.01 * (a + 1) for a in range(ASSET_COUNT)])
    values = np.empty((DATE_COUNT, ASSET_COUNT))
    values[0] = 1.0
    for t in range(1, DATE_COUNT):
        gt = g.copy()
        if t == 15:
            gt[8], gt[9] = gt[9], gt[8]
        values[t] = values[t - 1] * (1.0 + gt)
    return FactorPanel(
        factor_id=factor_id,
        factor_version="v1",
        data_snapshot_id="snap-test",
        dates=[D0 + timedelta(days=i) for i in range(DATE_COUNT)],
        assets=[f"{600000 + i}.SH" for i in range(ASSET_COUNT)],
        values=values.tolist(),
        source_path="synthetic",
    )


def _write_and_key(tmp_path, panel: FactorPanel) -> tuple:
    from tools.market import backing

    db = tmp_path / "blackboard.db"
    written = backing.write_panel_to_blackboard(
        panel, blackboard_db_path=db, written_by_task_id="T1", written_by_group="factor"
    )
    return db, written["blackboard_key"]


# ---------------------------------------------------------------------------
# 合成 IR 序列：IC/IR/turnover 统计核
# ---------------------------------------------------------------------------


def test_synthetic_ir_series_shape_and_magnitude():
    """合成序列逐日 rank IC：除 t=0（NaN 代理收益）与 t=15（受控倒挂）外全 1，
    IR 数量级远超 ic_mean（截面完全前瞻 → ic_std 极小）。"""
    from flows.factor_eval_real import ic_metrics, proxy_returns, rank_ic_per_date

    values = np.asarray(_perfect_panel().values, dtype=float)
    ics = rank_ic_per_date(values, proxy_returns(values))
    valid = ics[~np.isnan(ics)]
    assert valid.shape[0] == DATE_COUNT - 1  # T0 行代理收益全 NaN → 无 IC
    assert valid.mean() > 0.95
    assert np.all(np.delete(valid, 14) == 1.0) and valid[14] < 1.0  # t=15 受控倒挂
    m = ic_metrics(ics)
    assert m["ir"] > 10 * m["ic_mean"]
    assert m["t_stat"] > 2.0


def test_synthetic_turnover_low_for_perfect_lead():
    """perfect-lead 排序恒定（top decile k=1 资产，仅 t=0 起始行例外 1 次）
    → 相邻 Jaccard 仅 1/N 对切换 → 月度换手 < 0.1。

    手算对照：29 个相邻对里 1 个 Jaccard=1 → per_day = 1/29，
    连续日期 span=1 → 月度换手 = (1/29)*21 ≈ 0.724？否——k=10//10=1，
    切换发生在 t=0→t=1（初值全 1.0 并列），其余 28 对集合相同。
    mean(jac) = 1/29，×21 = 0.7241。
    """
    from flows.factor_eval_real import TRADING_DAYS_PER_MONTH, turnover_monthly

    values = np.asarray(_perfect_panel().values, dtype=float)
    got = turnover_monthly(values)
    expected = (1.0 / (DATE_COUNT - 1)) * TRADING_DAYS_PER_MONTH
    assert got == pytest.approx(expected)
    assert got < 0.8  # configs/acceptance.factor.yaml turnover_monthly_max


# ---------------------------------------------------------------------------
# 全链：合成 dataset → Blackboard → eval_factor_panel
# ---------------------------------------------------------------------------


def test_eval_factor_panel_end_to_end_pass(tmp_path):
    """完美前瞻 dataset → IR 达标 + 换手达标 + acceptance pass 全链。"""
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = eval_factor_panel_impl(key, blackboard_db_path=str(db))
    assert "error" not in out, out
    assert out["dataset_key"] == key
    assert out["factor_id"] == "perfect_lead"
    assert out["engine"] == "panel_real_v1"
    assert out["ic"]["ic_mean"] > 0.95
    assert out["ic"]["ir"] > 5.0
    assert 0.0 <= out["turnover_monthly"] <= 0.8  # yaml turnover_monthly_max
    assert out["verdict"] == "pass"
    assert out["acceptance"]["verdict"] == "pass"
    assert all(c["passed"] for c in out["acceptance"]["checks"])
    assert out["proxy_return_warning"]
    # SPEC §2.3：返回值带 key+摘要，大矩阵不进返回值
    assert "values" not in out["summary"]
    assert Path(out["artifacts"][0]).exists()


def test_eval_factor_panel_bare_id_expanded(tmp_path):
    """dataset_key 传裸 factor id → 归一为 shared.datasets.panel/<id>。"""
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    db, _ = _write_and_key(tmp_path, _perfect_panel())
    out = eval_factor_panel_impl(
        "perfect_lead", ic_abs_threshold=0.03, blackboard_db_path=str(db)
    )
    assert "error" not in out, out
    assert out["dataset_key"] == "shared.datasets.panel/perfect_lead"


def test_eval_factor_panel_full_key_passthrough(tmp_path):
    """完整 key（含 /）原样透传，不二次拼接。"""
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = eval_factor_panel_impl(key, blackboard_db_path=str(db))
    assert out["dataset_key"] == key == "shared.datasets.panel/perfect_lead"


def test_eval_factor_panel_threshold_fail(tmp_path):
    """ic_abs_threshold 抬到超过实际 ic_mean → fail_reasons + acceptance 叠加 check。"""
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = eval_factor_panel_impl(
        key, ic_abs_threshold=0.9999, blackboard_db_path=str(db)
    )
    assert "error" not in out, out
    # 受控倒挂使 ic_mean ≈ 0.9996 < 0.9999
    assert out["ic"]["ic_mean"] < 0.9999
    assert out["verdict"] == "fail"
    assert any("0.9999" in r for r in out["fail_reasons"])
    extra = [c for c in out["acceptance"]["checks"] if c["name"] == "ic_abs_threshold"]
    assert extra and extra[0]["passed"] is False
    assert out["acceptance"]["verdict"] == "fail"


def test_eval_factor_panel_default_threshold_matches_yaml(tmp_path):
    """默认 ic_abs_threshold=0.03 == configs/acceptance.factor.yaml ic_abs_min；pass 场景不叠加。"""
    from runner.acceptance import factor_thresholds
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    assert factor_thresholds()["ic_abs_min"] == 0.03
    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = eval_factor_panel_impl(key, blackboard_db_path=str(db))
    assert "error" not in out, out
    assert "ic_abs_threshold" not in out["acceptance"]["verdict"] or out["verdict"] == "pass"
    assert not [c for c in out["acceptance"]["checks"] if c["name"] == "ic_abs_threshold"]


def test_eval_factor_panel_verdict_linked_to_engine_thresholds(tmp_path):
    """engine verdict 与 runner.acceptance.factor_thresholds() 同源：构造卡阈值输入复核。"""
    from flows.factor_eval_real import _verdict_from_thresholds
    from runner.acceptance import factor_thresholds

    t = factor_thresholds()
    verdict, reasons = _verdict_from_thresholds(
        ic_mean=t["ic_abs_min"] - 1e-6, ir=10.0,
        turnover_monthly=0.1, t_stat=10.0,
    )
    assert verdict == "fail"
    assert any("ic_mean" in r for r in reasons)

    verdict_ok, reasons_ok = _verdict_from_thresholds(
        ic_mean=t["ic_abs_min"], ir=t["ir_min"],
        turnover_monthly=t["turnover_monthly_max"], t_stat=t["t_stat_min"],
    )
    assert verdict_ok == "pass" and reasons_ok == []


def test_eval_factor_panel_missing_dataset(tmp_path):
    """不存在的 dataset → panel_not_found error 对象（不抛崩溃）。"""
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    out = eval_factor_panel_impl(
        "shared.datasets.panel/no_such", blackboard_db_path=str(tmp_path / "bb.db")
    )
    assert out.get("error") == "panel_not_found"
    assert out["dataset_key"] == "shared.datasets.panel/no_such"


def test_eval_factor_panel_registered_and_callable(tmp_path):
    """registry 全链：register 链 reload 后 registry.call('eval_factor_panel') 可走通。"""
    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = registry.call(
        "eval_factor_panel",
        {"dataset_key": key, "blackboard_db_path": str(db)},
        ctx={},
    )
    assert "error" not in out, out
    assert out["verdict"] == "pass"
    assert out["acceptance"]["verdict"] == "pass"


def test_allowlist_contains_eval_factor_panel():
    """factor 组 allowlist 必须含 eval_factor_panel（防幽灵 id，P1-6 教训）。"""
    from tools.registry import GROUPS_DIR

    text = (GROUPS_DIR / "factor" / "tool_allowlist.yaml").read_text(encoding="utf-8")
    assert "eval_factor_panel" in text
    assert "eval_factor_panel" in registry.list_ids()


# ---------------------------------------------------------------------------
# 契约转换 API：to_frame / to_records / from_records / summarize
# ---------------------------------------------------------------------------


def _small_panel() -> FactorPanel:
    return FactorPanel(
        factor_id="GTJA191_M019",
        factor_version="v1.2",
        data_snapshot_id="snap-20260816",
        dates=[date(2024, 1, 2), date(2024, 1, 3)],
        assets=["600519.SH", "000001.SZ"],
        values=[[1.0, 2.0], [3.0, float("nan")]],
        source_path="synthetic",
    )


def test_factor_panel_to_frame_and_records():
    p = _small_panel()
    frame = p.to_frame()
    assert frame["dates"] == ["2024-01-02", "2024-01-03"]
    assert frame["assets"] == ["600519.SH", "000001.SZ"]
    assert frame["values"][0] == [1.0, 2.0]
    assert frame["values"][1][0] == 3.0
    assert math_isnan(frame["values"][1][1])  # NaN 原样保留（白名单口径）

    recs = p.to_records()
    assert len(recs) == 4
    assert recs[0] == {"date": date(2024, 1, 2), "asset": "600519.SH", "value": 1.0}
    assert recs[3]["asset"] == "000001.SZ" and math_isnan(recs[3]["value"])


def test_factor_panel_records_roundtrip_preserves_nan():
    p = _small_panel()
    p2 = FactorPanel.from_records(
        p.to_records(),
        factor_id=p.factor_id, factor_version=p.factor_version,
        data_snapshot_id=p.data_snapshot_id, source_path=p.source_path,
    )
    assert p2.dates == p.dates and p2.assets == p.assets
    assert math_isnan(p2.values[1][1])
    assert p2.values[0] == [1.0, 2.0]


def math_isnan(v) -> bool:
    return isinstance(v, float) and v != v


def test_factor_panel_from_records_sorts_and_validates():
    """乱序 records → dates 严格升序（不变量①）；非法 asset 被契约拒绝。"""
    import math

    p2 = FactorPanel.from_records(
        [
            {"date": "2024-01-03", "asset": "600519.SH", "value": 3.0},
            {"date": "2024-01-02", "asset": "600519.SH", "value": 1.0},
            {"date": "2024-01-02", "asset": "000001.SZ", "value": 2.0},
        ],
        factor_id="f", factor_version="v", data_snapshot_id="s", source_path="x",
    )
    assert p2.dates == [date(2024, 1, 2), date(2024, 1, 3)]
    assert p2.values[0] == [1.0, 2.0]
    assert math.isnan(p2.values[1][1])  # 缺失组合填 NaN

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FactorPanel.from_records(
            [{"date": "2024-01-02", "asset": "600519", "value": 1.0}],
            factor_id="f", factor_version="v", data_snapshot_id="s", source_path="x",
        )
    with pytest.raises(ValueError):
        FactorPanel.from_records([], factor_id="f", factor_version="v",
                                 data_snapshot_id="s", source_path="x")


def test_returns_dataset_frame_records_roundtrip():
    ds = ReturnsDataset(
        name="r1",
        dates=[date(2024, 1, 2), date(2024, 1, 3)],
        returns={"600519.SH": [0.01, float("nan")], "000001.SZ": [0.02, 0.03]},
    )
    frame = ds.to_frame()
    assert set(frame) == {"600519.SH", "000001.SZ"}
    ds2 = ReturnsDataset.from_records(ds.to_records(), name="r1")
    assert ds2.dates == ds.dates
    assert ds2.to_frame()["000001.SZ"] == [0.02, 0.03]
    # NaN 白名单往返（dict → records → dict）
    assert math_isnan(ds2.to_frame()["600519.SH"][1])

    # 矩阵口径 returns
    ds3 = ReturnsDataset(name="r3", dates=[date(2024, 1, 2), date(2024, 1, 3)],
                         returns=[[0.1, 0.2], [0.3, 0.4]])
    assert ds3.to_frame()["asset_1"] == [0.2, 0.4]
    ds4 = ReturnsDataset.from_records(ds3.to_records(), name="r3")
    assert ds4.to_frame() == ds3.to_frame()

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReturnsDataset.from_records(
            [{"date": "2024-01-02", "asset": "600519.SH", "return": float("inf")}],
            name="bad",
        )


def test_factor_panel_summary_includes_cells():
    p = _small_panel()
    s = p.summary()
    assert s["n_cells"] == 4 and s["n_dates"] == 2 and s["n_assets"] == 2
    assert s["date_start"] == "2024-01-02"
    assert CONTRACT_PANEL == "FactorPanel/v1"


def test_eval_summary_uses_panel_summary_shape(tmp_path):
    """全链 summary 里体现 panel 摘要 shape（n_dates/n_assets 来自合成 dataset）。"""
    from tools.factor.eval_from_panel import eval_factor_panel_impl

    db, key = _write_and_key(tmp_path, _perfect_panel())
    out = eval_factor_panel_impl(key, blackboard_db_path=str(db))
    assert "error" not in out, out
    assert out["summary"]["evaluation_period"]["start"] == "2026-07-06"
    assert out["summary"]["evaluation_period"]["end"] == str(D0 + timedelta(days=DATE_COUNT - 1))
    assert out["summary"]["engine"] == "panel_real_v1"
    assert out["acceptance"]["verdict"] == "pass"
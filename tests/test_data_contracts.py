"""D1-A1/A2/A3/A8/A11/A12 — FactorPanel/TargetReturnView 契约断言（specs/data/SPEC.md §4）。"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from pydantic import ValidationError

from schemas.data_contracts import (
    CONTRACT_PANEL,
    FactorPanel,
    ReturnsDataset,
    TargetReturnView,
)


def _panel_kwargs(**overrides):
    kwargs = {
        "factor_id": "GTJA191_M019",
        "factor_version": "v1.2",
        "data_snapshot_id": "snap-20260816",
        "dates": [date(2024, 1, 2), date(2024, 1, 3)],
        "assets": ["600519.SH", "000001.SZ"],
        "values": [[1.0, 2.0], [3.0, 4.0]],
        "source_path": "/srv/quant/data/migration-staging/20260814/delivery_pool_all_maxcard",
    }
    kwargs.update(overrides)
    return kwargs


# D1-A1: FactorPanel(dates=[d, d]) 重复日期抛 ValidationError
def test_panel_rejects_duplicate_dates():
    with pytest.raises(ValidationError):
        FactorPanel(**_panel_kwargs(dates=[date(2024, 1, 2), date(2024, 1, 2)]))


# D1-A2: dates 降序抛 ValidationError
def test_panel_rejects_unsorted_dates():
    with pytest.raises(ValidationError):
        FactorPanel(**_panel_kwargs(dates=[date(2024, 1, 3), date(2024, 1, 2)]))


# D1-A3: asset="000001"（缺后缀）抛 ValidationError；"600519.SH" 通过
def test_panel_asset_format_a_share():
    with pytest.raises(ValidationError):
        FactorPanel(**_panel_kwargs(assets=["000001"]))
    panel = FactorPanel(**_panel_kwargs())
    assert "600519.SH" in panel.assets
    assert "871981.BJ" not in panel.assets or panel.assets.count("871981.BJ") == 0


# D1-A8: 返回值经 FactorPanel.model_validate() 通过且 _contract=="FactorPanel/v1"
def test_panel_output_matches_pydantic_contract():
    raw = FactorPanel(**_panel_kwargs(values=np.zeros((2, 2), dtype="float32")))
    payload = raw.model_dump(mode="json")
    assert payload["_contract"] == CONTRACT_PANEL == "FactorPanel/v1"

    validated = FactorPanel.model_validate(payload)
    assert validated.factor_id == "GTJA191_M019"
    assert validated.contract == "FactorPanel/v1"
    # 缺 _contract 戳的 Blackboard 载荷同样可被 model_validate 接受（戳有默认值），
    # 但错误戳 / 未知版本必须拒绝（写入侧强校验在 tools/market/backing.py）。
    bad = dict(payload)
    bad["_contract"] = "FactorPanel/v99"
    with pytest.raises(ValidationError):
        FactorPanel.model_validate(bad)


# 附属：ReturnsDataset 不变量（NaN 白名单 / 禁 inf / dates 严格升序）
def test_returns_dataset_nan_whitelist_and_inf_rejected():
    ds = ReturnsDataset(
        name="demo",
        dates=[date(2024, 1, 2), date(2024, 1, 3)],
        returns={"600519.SH": [0.01, float("nan")]},
    )
    assert ds.dates == [date(2024, 1, 2), date(2024, 1, 3)]

    with pytest.raises(ValidationError):
        ReturnsDataset(
            name="bad",
            dates=[date(2024, 1, 2), date(2024, 1, 3)],
            returns={"600519.SH": [0.01, float("inf")]},
        )
    with pytest.raises(ValidationError):
        ReturnsDataset(
            name="bad",
            dates=[date(2024, 1, 2), date(2024, 1, 2)],  # duplicate dates
            returns={"600519.SH": [0.01, 0.02]},
        )


# D1-A11: target_return 视图 Horizon 枚举——{1,5,10,20} 合法通过，3 抛 ValidationError
def test_target_return_horizon_enum():
    for h in (1, 5, 10, 20):
        view = TargetReturnView(horizon=h, adjusted="hfq")
        assert view.horizon == h
        assert view.alignment == "t+1->t+2"
        assert view.contract == "TargetReturnView/v1"

    with pytest.raises(ValidationError):
        TargetReturnView(horizon=3, adjusted="hfq")


# D1-A12: 复权标记必填——缺 adjusted 抛 ValidationError，adjusted="hfq"（后复权）通过
def test_target_return_adjusted_marker_required():
    with pytest.raises(ValidationError):
        TargetReturnView(horizon=5)

    view = TargetReturnView(horizon=5, adjusted="hfq")
    assert view.adjusted == "hfq"
    # 非后复权标记同样拒绝（SPEC §2.5：禁止未复权字段）。
    with pytest.raises(ValidationError):
        TargetReturnView(horizon=5, adjusted="none")
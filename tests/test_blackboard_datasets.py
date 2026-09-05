"""D1-A9/A10 — Blackboard shared.datasets.* 契约读写断言（specs/data/SPEC.md §4）。"""
from __future__ import annotations

import importlib
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from runner.blackboard import BlackboardService
from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
from schemas import BlackboardScope
from tools.market import backing
from tools.market import _register as _market_register  # noqa: F401  # 注册四工具
from tools.registry import registry

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "qs_cold_sample"
AS_OF = datetime(2026, 1, 1)


@pytest.fixture(autouse=True)
def _ensure_registered():
    # 全量 pytest 时其他测试文件会 registry._tools.clear() 清空全局单例；
    # 与 tests/test_allowlist_consistency.py 同款防御：reload 注册链（幂等）。
    importlib.reload(_market_register)
    yield


def _make_panel():
    return FactorPanelFixture()


def FactorPanelFixture():
    from schemas.data_contracts import FactorPanel

    return FactorPanel(
        factor_id="demo",
        factor_version="v1",
        data_snapshot_id="snap-test",
        dates=[date(2024, 1, 2), date(2024, 1, 3)],
        assets=["600519.SH"],
        values=[[1.0], [2.0]],
        source_path=str(FIXTURE_ROOT),
    )


# D1-A9: 写 shared.datasets.panel/demo 后 get_entry 读回同一契约对象
def test_dataset_roundtrip_project_scope(tmp_path):
    db = tmp_path / "blackboard.db"
    written = backing.write_panel_to_blackboard(
        _make_panel(),
        blackboard_db_path=db,
        written_by_task_id="T1",
        written_by_group="model",
    )
    assert written["blackboard_key"] == make_read_key("shared.datasets.panel/demo")

    service = BlackboardService(db_path=db, session_id=PROJECT_SESSION_ID)
    entry = service.get_entry(
        BlackboardScope.PROJECT, None, "shared.datasets.panel/demo"
    )
    assert entry is not None
    assert entry.value["_contract"] == "FactorPanel/v1"

    panel = backing.read_panel_from_blackboard("shared.datasets.panel/demo", blackboard_db_path=db)
    original = _make_panel()
    assert panel == original  # model_validate 读回同一契约对象
    assert panel.dates == original.dates
    assert panel.values == original.values


# D1-A10: 向 panel namespace 写入无 _contract 或版本不匹配的 dict，写入口抛 ValidationError
def test_dataset_entry_version_stamp_enforced():
    payload_no_stamp = _make_panel().model_dump(mode="json")
    payload_no_stamp.pop("_contract", None)
    with pytest.raises(ValidationError):
        backing.validate_dataset_payload(payload_no_stamp)

    payload_bad_version = _make_panel().model_dump(mode="json")
    payload_bad_version["_contract"] = "FactorPanel/v2"
    with pytest.raises(ValidationError):
        backing.validate_dataset_payload(payload_bad_version)

    # 匹配戳通过并 model_validate 成功
    ok = backing.validate_dataset_payload(
        {**_make_panel().model_dump(mode="json"), "_contract": "FactorPanel/v1"}
    )
    assert ok.contract == "FactorPanel/v1"


# 附属：registry.call("load_factor_panel") 全链路写 Blackboard 后按 key 读回
def test_load_factor_panel_writes_blackboard_key(tmp_path, monkeypatch):
    monkeypatch.setenv("QS_DATA_STAGING_ROOT", str(FIXTURE_ROOT))
    db = tmp_path / "bb.db"
    result = registry.call(
        "load_factor_panel",
        {
            "factor_id": "GTJA191_M019",
            "year_start": 2024,
            "year_end": 2025,
            "as_of": AS_OF,
            "blackboard_db_path": str(db),
        },
        {"group": "model", "task_id": "T1"},
    )
    assert "error" not in result
    assert result["blackboard_key"] == "shared.datasets.panel/GTJA191_M019"

    panel = backing.read_panel_from_blackboard(
        "shared.datasets.panel/GTJA191_M019", blackboard_db_path=db
    )
    assert panel._contract if hasattr(panel, "_contract") else panel.contract == "FactorPanel/v1"
    assert panel.factor_id == "GTJA191_M019"
    assert panel.meta["removed"]["count"] == 2
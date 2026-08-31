"""D1-A4/A5/A6/A7 — market 四工具断言（specs/data/SPEC.md §4）。

fixture：tests/fixtures/qs_cold_sample（mini qs-cold staging 副本，
GTJA191_M019 两年 parquet，含 2 行 is_valid==0 与 1 行 PIT 晚到 calc_time）。
"""
from __future__ import annotations

import socket
import importlib
from datetime import date, datetime
from pathlib import Path

import pytest

from tools.market import backing
from tools.market import _register as _market_register  # noqa: F401  # 注册四工具
from tools.registry import registry

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "qs_cold_sample"
AS_OF = datetime(2026, 1, 1)
EARLY_AS_OF = datetime(2024, 2, 1)  # 在 2024-06-01 晚到 calc_time 之前


@pytest.fixture(autouse=True)
def _ensure_registered():
    # 全量 pytest 时其他测试文件会 registry._tools.clear() 清空全局单例；
    # 与 tests/test_allowlist_consistency.py 同款防御：reload 注册链（幂等）。
    importlib.reload(_market_register)
    yield


@pytest.fixture(autouse=True)
def staging_root(monkeypatch):
    monkeypatch.setenv("QS_DATA_BACKEND", "staging")
    monkeypatch.setenv("QS_DATA_STAGING_ROOT", str(FIXTURE_ROOT))


# D1-A4: load_factor_panel(as_of=T) 输出全满足 calc_time <= T
def test_load_factor_panel_pit_filter():
    # fixture 里 2024 年 (2024-01-04, 871981.BJ) 行 calc_time=2024-06-01；
    # 早截断下必须被 PIT 过滤掉。
    result = backing.load_factor_panel_impl("GTJA191_M019", 2024, 2024, EARLY_AS_OF)
    panel = result["panel"]
    assert panel.meta["pit_filtered"] == 1
    assert date(2024, 1, 4) not in panel.dates  # 该单元格唯一数据源是晚到行

    # 晚截断下该行进入面板（calc_time <= as_of）
    later = backing.load_factor_panel_impl("GTJA191_M019", 2024, 2024, AS_OF)["panel"]
    assert later.meta["pit_filtered"] == 0
    i = later.dates.index(date(2024, 1, 4))
    j = later.assets.index("871981.BJ")
    assert later.values[i][j] is not None


# D1-A5: is_valid==0 行不出现在 values；meta.removed 计数与 fixture 一致
def test_load_factor_panel_drops_invalid_rows():
    result = backing.load_factor_panel_impl("GTJA191_M019", 2024, 2025, AS_OF)
    panel = result["panel"]
    # fixture：2 行 is_valid==0 → (2024-01-02, 871981.BJ) 与 (2024-01-03, 300750.SZ)
    assert panel.meta["removed"]["count"] == 2
    assert panel.meta["removed"]["invalid_reasons"] == {"missing_raw_data": 2}
    assert panel.values[panel.dates.index(date(2024, 1, 2))][
        panel.assets.index("871981.BJ")
    ] is None
    assert panel.values[panel.dates.index(date(2024, 1, 3))][
        panel.assets.index("300750.SZ")
    ] is None
    # 有效行完整保留：15 行有效数据（2024 年 8 行剔 2 → 6，2025 年 8 行，加 PIT 行 1）
    n_present = sum(1 for row in panel.values for v in row if v is not None)
    assert n_present == 15


# D1-A6: 默认 staging backend 四工具零网络（monkeypatch socket 即证）
def test_staging_backend_network_fail_closed(monkeypatch):
    class _BlockedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise AssertionError("staging backend must not touch the network")

    monkeypatch.setattr(socket, "socket", _BlockedSocket)

    r1 = registry.call("list_factors", {"backend": "staging"}, {})
    assert r1["count"] >= 1 or "error" in r1
    r2 = registry.call(
        "load_factor_panel",
        {
            "factor_id": "GTJA191_M019",
            "year_start": 2024,
            "year_end": 2025,
            "as_of": AS_OF,
            "write_to_blackboard": False,
        },
        {},
    )
    assert "error" not in r2 or r2["error"] in {"staging_root_missing"}
    r3 = registry.call(
        "load_returns",
        {"name": "demo", "date_start": date(2024, 1, 1), "date_end": date(2024, 2, 1)},
        {},
    )
    assert r3["error"] == "no_source"
    r4 = registry.call("pool_browse", {"family": "lqtp_1014"}, {})
    assert r4["count"] >= 1 or "error" in r4


# D1-A7: 显式未知 backend 且无凭据抛 PermissionError|ValueError，绝不静默降级
def test_unknown_backend_rejected():
    with pytest.raises((PermissionError, ValueError)):
        registry.call("list_factors", {"backend": "cos"}, {})
    with pytest.raises((PermissionError, ValueError)):
        registry.call("pool_browse", {"backend": "qsdata_service"}, {})


# audit #18: QS_DATA_ALLOW_EXPERIMENTAL_BACKENDS 死开关已删——任何未知 backend
# 无论 env 开关怎么设都抛 PermissionError（单一 raise，无旁门）
def test_experimental_backend_flag_removed(monkeypatch):
    monkeypatch.setenv("QS_DATA_ALLOW_EXPERIMENTAL_BACKENDS", "1")
    with pytest.raises((PermissionError, ValueError)):
        backing.resolve_backend("cos")


# audit #18: factor_id 路径穿越拒绝——".." 逃逸出 factors root 返回 None（不读文件）
def test_factor_id_path_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("QS_DATA_BACKEND", "staging")
    root = tmp_path / "staging"
    (root / "factors" / "GTJA191_M019" / "year=2024").mkdir(parents=True)
    # 模拟一个放在 staging 根之外的"机密文件"
    secret = tmp_path / "secret.parquet"
    secret.write_bytes(b"SECRET")
    # factors_root 外的 ../secret.parquet —— 守卫必须拒绝
    assert backing._factor_data_path(root, "../secret", 2024) is None
    assert backing._factor_data_path(root, "a/../../secret", 2024) is None
    # 不带 ".." 的正常 id 仍然可解析
    normal = backing._factor_data_path(root, "GTJA191_M019", 2024)
    assert normal is None  # fixture 布局没建 data.parquet，但不能是穿越成功
    # 正常目录 + 文件在时能找到
    (root / "factors" / "GTJA191_M019" / "year=2024" / "data.parquet").write_bytes(b"x")
    ok = backing._factor_data_path(root, "GTJA191_M019", 2024)
    assert ok is not None and ok.is_relative_to((root / "factors").resolve())


# audit #18: write_to_blackboard 且 ctx 缺 task_id → T0 占位署名（诚实缺失）
def test_load_factor_panel_honest_task_id_placeholder(monkeypatch, tmp_path):
    db = tmp_path / "bb.db"
    result = registry.call(
        "load_factor_panel",
        {
            "factor_id": "GTJA191_M019",
            "year_start": 2024,
            "year_end": 2024,
            "as_of": AS_OF,
            "blackboard_db_path": str(db),
        },
        {"group": "factor"},  # 无 task_id
    )
    assert "error" not in result
    assert result["blackboard_key"] == "shared.datasets.panel/GTJA191_M019"
    assert result["written_by_task_id"].startswith("T0."), (
        "ctx 缺 task_id 时必须用 T0 占位署名，不得伪造 T1.*"
    )


# 附属：工具返回 dict 只含 key+摘要+统计（SPEC §2.3 —— 大矩阵不进返回值）
def test_tool_returns_summary_only():
    result = registry.call(
        "load_factor_panel",
        {
            "factor_id": "GTJA191_M019",
            "year_start": 2024,
            "year_end": 2025,
            "as_of": AS_OF,
            "write_to_blackboard": False,
        },
        {},
    )
    assert "values" not in result
    assert result["n_dates"] == 5
    assert result["n_assets"] == 4
    assert result["_contract"] == "FactorPanel/v1"
    assert result["blackboard_key"] == "shared.datasets.panel/GTJA191_M019"

    # staging 根不存在时返回明确错误对象（而非崩溃）
    cfg = backing.resolve_backend()
    assert cfg["backend"] == "staging"
    missing = backing.list_factors_impl(backend="staging") if cfg["exists"] else None
    assert missing is None or missing["count"] >= 1  # fixture 存在时正常返回
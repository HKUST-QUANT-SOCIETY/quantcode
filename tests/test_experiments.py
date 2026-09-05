"""AB 实验三工具 e2e（ROADMAP A3 + FUNCTIONAL P-05）。

fixture：合成两个 FactorPanel key（Blackboard 写入），植入已知指标序：
- base  panel：ic 均值略低 + 每 5 日 top-1 在两资产间轮换（高换手）；
- chall panel：ic 均值略高（单次受控倒挂）+ 无轮换（低换手）。
→ challenger 在 ic_mean/ir/t_stat/turnover 全部更优 → verdict=challenger。

覆盖：
- run_ab_experiment 端到端逐指标 delta / verdict
- oos 违规（窗口越界）→ fail_reasons 标 oos_discipline、verdict 强制 tie
- 排行榜 index.json 顺序（最新在前 = 追加序）与 leaderboard_k 截断
- 缺 key / 坏 key → KeyError（get_experiment）/ ValueError（评估侧）
- yaml 单源（enforce_oos=false 时不判 oos_discipline）
"""
from __future__ import annotations

import importlib
import json
from datetime import date, timedelta

import numpy as np
import pytest

import tools.experiments._register as _exp_register  # noqa: F401
from schemas.data_contracts import FactorPanel
from tools.market.backing import write_panel_to_blackboard
from tools.registry import registry

ASSET_COUNT = 10
DATE_COUNT = 30
D0 = date(2026, 7, 6)


@pytest.fixture(autouse=True)
def _ensure_registered(tmp_path, monkeypatch):
    # 全量 pytest 时其他测试文件会 registry._tools.clear() 清空全局单例；
    # register_tool 覆盖式幂等，reload 即恢复。
    importlib.reload(_exp_register)
    monkeypatch.setattr(_exp_register, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    yield


def _dates() -> list[date]:
    return [D0 + timedelta(days=i) for i in range(DATE_COUNT)]


def _assets() -> list[str]:
    return [f"{600000 + i}.SH" for i in range(ASSET_COUNT)]


def _panel(factor_id: str, *, inversions: tuple[int, ...], rotate: bool) -> FactorPanel:
    """base：g=0.01*(a+1)，两次受控倒挂 + 每 5 日 top-1 轮换（高换手、低 IC）；
    chall：单次倒挂、无轮换（高 IC、低换手）。"""
    g = np.array([0.01 * (a + 1) for a in range(ASSET_COUNT)])
    values = np.empty((DATE_COUNT, ASSET_COUNT))
    values[0] = 1.0
    for t in range(1, DATE_COUNT):
        gt = g.copy()
        if t in inversions:
            gt[8], gt[9] = gt[9], gt[8]
        values[t] = values[t - 1] * (1.0 + gt)
        if rotate and t % 5 == 0:
            values[t, 0] = values[t, ASSET_COUNT - 1] * 1.5
    return FactorPanel(
        factor_id=factor_id,
        factor_version="v1",
        data_snapshot_id="snap-test",
        dates=_dates(),
        assets=_assets(),
        values=values.tolist(),
        source_path="synthetic",
    )


def _write_two_panels(tmp_path):
    db = tmp_path / "bb.db"
    for panel in (
        _panel("exp_base", inversions=(10, 20), rotate=True),
        _panel("exp_chall", inversions=(15,), rotate=False),
    ):
        write_panel_to_blackboard(
            panel, blackboard_db_path=db, written_by_task_id="T1",
            written_by_group="factor",
        )
    return db


# ---------------------------------------------------------------------------
# run_ab_experiment 端到端
# ---------------------------------------------------------------------------


def test_run_ab_e2e_metrics_and_verdict(tmp_path):
    """challenger 全指标更优 → 逐指标 delta 可复核、verdict=challenger。"""
    db = _write_two_panels(tmp_path)
    out = registry.call(
        "run_ab_experiment",
        {
            "baseline_id": "panel:shared.datasets.panel/exp_base",
            "challenger_id": "panel:shared.datasets.panel/exp_chall",
            "dataset_key": "shared.datasets.panel/exp_base",
            "blackboard_db_path": str(db),
        },
        {},
    )
    assert out["verdict"] == "challenger"
    assert out["fail_reasons"] == []
    assert out["baseline_id"] == "panel:shared.datasets.panel/exp_base"
    assert out["challenger_id"] == "panel:shared.datasets.panel/exp_chall"
    assert out["dataset_snapshot_hash"]  # 64 hex
    assert len(out["dataset_snapshot_hash"]) == 64
    by_metric = {m["metric"]: m for m in out["metrics"]}
    assert set(by_metric) == {"ic_mean", "ir", "t_stat", "turnover"}
    for name in ("ic_mean", "ir", "t_stat"):
        m = by_metric[name]
        assert m["better"] == "challenger"
        assert m["chall"] > m["base"]
        assert m["delta"] == m["chall"] - m["base"]
    # turnover：chall 无轮换 → 低换手 → delta<0 仍判 challenger 更优
    t = by_metric["turnover"]
    assert t["better"] == "challenger" and t["delta"] < 0
    # 归档落盘且与返回一致
    artifact = out["artifacts"][0]
    assert artifact.startswith("artifacts/experiments/")
    loaded = json.loads(open(artifact, encoding="utf-8").read())
    assert loaded["exp_id"] == out["exp_id"]


def test_run_ab_bare_ids_resolve_to_panel_keys(tmp_path):
    """裸 id（无 panel:/algorithm: 前缀）→ shared.datasets.panel/<id> 两侧。
    两个合成 panel 的指标序已由 fixture 植入 → challenger 胜。"""
    db = _write_two_panels(tmp_path)
    out = run_ab(
        "exp_base", "exp_chall", "shared.datasets.panel/exp_base",
        blackboard_db_path=str(db),
    )
    by_metric = {m["metric"]: m for m in out["metrics"]}
    assert all(m["better"] == "challenger" for m in by_metric.values())
    assert out["verdict"] == "challenger"


def test_run_ab_swapped_sides_gives_baseline(tmp_path):
    """交换基线/挑战者 → 全指标 baseline 更优 → verdict=baseline。"""
    db = _write_two_panels(tmp_path)
    out = run_ab(
        "panel:shared.datasets.panel/exp_chall",
        "panel:shared.datasets.panel/exp_base",
        "shared.datasets.panel/exp_chall",
        blackboard_db_path=str(db),
    )
    assert out["verdict"] == "baseline"


def run_ab(*args, **kw):
    from tools.experiments._register import run_ab_experiment

    return run_ab_experiment(*args, **kw)


# ---------------------------------------------------------------------------
# OOS 纪律
# ---------------------------------------------------------------------------


def test_oos_violation_marks_fail_reason_and_tie(tmp_path):
    """oos_range 晚于面板窗口 → 两侧评估窗口均 ⊄ OOS → fail_reasons 标
    oos_discipline，verdict 强制 tie（不得写成 challenger 胜出）。"""
    db = _write_two_panels(tmp_path)
    out = registry.call(
        "run_ab_experiment",
        {
            "baseline_id": "exp_base",
            "challenger_id": "exp_chall",
            "dataset_key": "shared.datasets.panel/exp_base",
            "oos_start": "2026-08-01",
            "oos_end": "2026-09-30",
            "blackboard_db_path": str(db),
        },
        {},
    )
    assert out["verdict"] == "tie"
    assert len(out["fail_reasons"]) == 2
    assert all(r.startswith("oos_discipline:") for r in out["fail_reasons"])
    assert out["oos_range"] == {"start": "2026-08-01", "end": "2026-09-30"}


def test_oos_inside_window_passes(tmp_path):
    """oos_range 覆盖整个面板 → 校验通过，无 fail_reasons。"""
    db = _write_two_panels(tmp_path)
    out = run_ab(
        "exp_base", "exp_chall", "shared.datasets.panel/exp_base",
        oos_range={"start": "2026-07-01", "end": "2026-08-31"},
        blackboard_db_path=str(db),
    )
    assert out["fail_reasons"] == []
    assert out["verdict"] == "challenger"


def test_enforce_oos_false_disables_check(tmp_path, monkeypatch):
    """configs 单源：enforce_oos=false → 越界不判 oos_discipline（单源验证）。"""
    import yaml

    from runner.config_loader import load_yaml

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "experiments.yaml").write_text(
        yaml.safe_dump({"experiments": {"enforce_oos": False, "leaderboard_k": 5}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(cfg_dir))
    load_yaml.cache_clear()
    try:
        db = _write_two_panels(tmp_path)
        out = run_ab(
            "exp_base", "exp_chall", "shared.datasets.panel/exp_base",
            oos_range={"start": "2026-08-01", "end": "2026-09-30"},
            blackboard_db_path=str(db),
        )
        assert out["fail_reasons"] == []
        assert out["verdict"] == "challenger"
    finally:
        load_yaml.cache_clear()


# ---------------------------------------------------------------------------
# 排行榜 / 单份查询
# ---------------------------------------------------------------------------


def test_index_ranking_order_and_leaderboard_k(tmp_path, monkeypatch):
    """连续两次实验：排行榜按追加序保留最新条目；leaderboard_k 截断生效。"""
    import yaml

    from runner.config_loader import load_yaml

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "experiments.yaml").write_text(
        yaml.safe_dump({"experiments": {"enforce_oos": True, "leaderboard_k": 1}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(cfg_dir))
    load_yaml.cache_clear()
    try:
        db = _write_two_panels(tmp_path)
        first = registry.call(
            "run_ab_experiment",
            {"baseline_id": "exp_base", "challenger_id": "exp_chall",
             "dataset_key": "shared.datasets.panel/exp_base",
             "blackboard_db_path": str(db)},
            {},
        )
        second = registry.call(
            "run_ab_experiment",
            {"baseline_id": "exp_chall", "challenger_id": "exp_base",
             "dataset_key": "shared.datasets.panel/exp_base",
             "blackboard_db_path": str(db)},
            {},
        )
        listing = registry.call("list_experiments", {}, {})
        assert listing["total"] >= 1
        # leaderboard_k=1 → 只保留最新一条（second）
        assert len(listing["experiments"]) == 1
        assert listing["experiments"][0]["exp_id"] == second["exp_id"]
        assert listing["experiments"][0]["exp_id"] != first["exp_id"]
        entry = listing["experiments"][0]
        assert entry["baseline_id"] == "exp_chall" and entry["challenger_id"] == "exp_base"
        # 第二次实验角色互换（base/chall 反转）→ challenge 输在全部指标
        assert entry["verdict"] == "baseline"
        assert entry["artifact"] and entry["entry_hash"]
    finally:
        load_yaml.cache_clear()


def test_list_experiments_empty_when_no_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    listing = registry.call("list_experiments", {}, {})
    assert listing == {"experiments": [], "total": 0}


def test_get_experiment_roundtrip_and_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _write_two_panels(tmp_path)
    out = registry.call(
        "run_ab_experiment",
        {"baseline_id": "exp_base", "challenger_id": "exp_chall",
         "dataset_key": "shared.datasets.panel/exp_base",
         "blackboard_db_path": str(db)},
        {},
    )
    got = registry.call("get_experiment", {"exp_id": out["exp_id"]}, {})
    assert got["report"]["verdict"] == "challenger"
    assert got["report"] == out
    with pytest.raises(KeyError, match="no_such_exp"):
        registry.call("get_experiment", {"exp_id": "no_such_exp"}, {})


def test_get_experiment_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(KeyError, match=r"\.\./secret"):
        registry.call("get_experiment", {"exp_id": "../secret"}, {})


# ---------------------------------------------------------------------------
# 错误路径 + 注册
# ---------------------------------------------------------------------------


def test_missing_dataset_key_errors(tmp_path):
    """侧 panel key 缺失 → 评估侧抛 ValueError（side 信息在消息里）。"""
    db = _write_two_panels(tmp_path)
    with pytest.raises(ValueError, match="side 'no_such_factor' evaluation failed"):
        registry.call(
            "run_ab_experiment",
            {"baseline_id": "exp_base", "challenger_id": "no_such_factor",
             "dataset_key": "shared.datasets.panel/exp_base",
             "blackboard_db_path": str(db)},
            {},
        )


def test_three_tools_registered_as_meta():
    # 先行测试会清空全局 registry；import 兜不住（sys.modules 缓存）→
    # reload mcp_server 重跑 _meta 标记块（幂等覆盖式注册，同 test_stream_channel 防御）。
    import quantcode.mcp_server as _mcp

    importlib.reload(_mcp)
    for tool_id in ("run_ab_experiment", "list_experiments", "get_experiment"):
        tool = registry.get(tool_id)
        assert getattr(tool, "_meta", False) is True

"""algorithms.yaml 注册表三工具 e2e（ROADMAP Q3 A3 算法注册表首例）。

覆盖：
- configs/algorithms.yaml 两个条目可见（list_algorithms）
- describe_algorithm 返回 entry 全量；未知 id 报 KeyError
- run_algorithm e2e：tmp Blackboard 写 FactorPanel → demo 评分器出等权 rank top_n
- 无效注册表条目被跳过
"""
from __future__ import annotations

import importlib
from datetime import date

import pytest

import tools.algorithms._register as _algo_register  # noqa: F401
from schemas.data_contracts import FactorPanel
from tools.market.backing import write_panel_to_blackboard
from tools.registry import registry


@pytest.fixture(autouse=True)
def _ensure_registered():
    # 全量 pytest 时其他测试文件会 registry._tools.clear() 清空全局单例；
    # register_tool 覆盖式幂等，reload 即恢复。
    importlib.reload(_algo_register)
    yield


def _demo_panel() -> FactorPanel:
    return FactorPanel(
        factor_id="algo_reg_demo",
        factor_version="v1",
        data_snapshot_id="snap-test",
        dates=[date(2024, 1, 2), date(2024, 1, 3)],
        assets=["600519.SH", "000858.SZ", "601318.SH", "300750.SZ", "002594.SZ"],
        values=[[1.0, 2.0, 3.0, 5.0, 0.5], [0.9, 2.1, 2.8, 4.8, 0.4]],
        source_path="fixtures/qs_cold_sample",
    )


def test_list_algorithms_returns_two_entries():
    result = registry.call("list_algorithms", {})
    ids = [a["id"] for a in result["algorithms"]]
    assert "equal_weight_composite_ranker" in ids
    assert "pb_roe_ranker" in ids
    assert all(a["description"] for a in result["algorithms"])


def test_describe_algorithm_returns_entry_point():
    result = registry.call(
        "describe_algorithm", {"algorithm_id": "pb_roe_ranker"}
    )
    entry = result["entry"]
    assert entry["entry_point"] == "tools.algorithms.score_demo:run_score_demo"


def test_describe_algorithm_unknown_id_errors():
    with pytest.raises(KeyError, match="no_such_algo"):
        registry.call("describe_algorithm", {"algorithm_id": "no_such_algo"})


def test_run_algorithm_demo_scorer_e2e(tmp_path):
    """tmp Blackboard 写 panel → run_algorithm(dataset_key) → 等权 composite top_n。"""
    db = tmp_path / "bb.db"
    write_panel_to_blackboard(
        _demo_panel(),
        blackboard_db_path=db,
        written_by_task_id="T1",
        written_by_group="model",
    )
    result = registry.call(
        "run_algorithm",
        {
            "algorithm_id": "equal_weight_composite_ranker",
            "dataset_key": "shared.datasets.panel/algo_reg_demo",
            "top_n": 2,
            "blackboard_db_path": str(db),
        },
        {"group": "factor", "task_id": "T1"},
    )
    assert result["algorithm_id"] == "equal_weight_composite_ranker"
    assert result["universe_size"] == 5
    assert result["as_of"] == str(date(2024, 1, 3))
    top = result["top_assets"]
    assert len(top) == 2
    # 最新截面 002594=0.4 最低 → 逆序 rank 第一；300750=4.8 次高
    assert top[0]["asset"] == "002594.SZ"
    assert top[1]["asset"] == "300750.SZ"
    scores = [s["score"] for s in result["scores"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)  # 归一 0~1


def test_run_algorithm_via_second_entry_same_scorer(tmp_path):
    """pb_roe_ranker 指向同一 demo scorer（注释映射占位），跑通即证明 entry_point 机制。"""
    db = tmp_path / "bb.db"
    write_panel_to_blackboard(
        _demo_panel(),
        blackboard_db_path=db,
        written_by_task_id="T1",
        written_by_group="model",
    )
    result = registry.call(
        "run_algorithm",
        {
            "algorithm_id": "pb_roe_ranker",
            "dataset_key": "shared.datasets.panel/algo_reg_demo",
            "top_n": 1,
            "blackboard_db_path": str(db),
        },
        {},
    )
    assert result["algorithm_id"] == "pb_roe_ranker"
    assert result["top_assets"][0]["asset"] == "002594.SZ"


def test_invalid_registry_entries_skipped(tmp_path, monkeypatch):
    """yaml 无效 entry（缺键）按 warning 跳过，不炸列表。"""
    (tmp_path / "algorithms.yaml").write_text(
        "signal_algorithms:\n"
        "  - id: no_entry_point\n"
        "    description: broken entry\n"
        "  - id: valid_one\n"
        "    entry_point: \"tools.algorithms.score_demo:run_score_demo\"\n"
        "    description: valid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    from runner.config_loader import load_yaml

    load_yaml.cache_clear()
    try:
        entries = _algo_register._entries()
        assert [e["id"] for e in entries] == ["valid_one"]
    finally:
        load_yaml.cache_clear()
"""config_loader + acceptance yaml 单源测试（架构决策 3「配置不喂 LLM」）。

覆盖：
- load_yaml 正常读 / 缺文件空 dict / 坏 YAML 空 dict / 顶层非 dict 空 dict
- QUANTCODE_CONFIG_DIR 覆盖 + cache_clear
- yaml 覆盖生效（tmp yaml 改阈值 → run_acceptance verdict 变化）
- 缺文件回退代码默认（warning 不抛错），行为与历史硬编码一致
"""
from __future__ import annotations

from pathlib import Path

import pytest

from runner import acceptance
from runner.config_loader import load_yaml


@pytest.fixture()
def config_dir_env(tmp_path, monkeypatch):
    """QUANTCODE_CONFIG_DIR 指向空 tmp 目录，并清 config_loader 缓存。"""
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    load_yaml.cache_clear()
    yield tmp_path
    load_yaml.cache_clear()


def _passing_factor_payload() -> dict:
    return {
        "ic_metrics": {"ic_mean": 0.05, "ir": 0.7, "t_stat": 2.5},
        "turnover": {"monthly": 0.5},
    }


def test_load_yaml_reads_file(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    load_yaml.cache_clear()
    (tmp_path / "demo.yaml").write_text("a: 1\nb: [x, y]\n", encoding="utf-8")
    assert load_yaml("demo") == {"a": 1, "b": ["x", "y"]}
    load_yaml.cache_clear()


def test_load_yaml_missing_file_returns_empty(config_dir_env):
    assert load_yaml("no_such_config") == {}


def test_load_yaml_bad_yaml_returns_empty(config_dir_env):
    (config_dir_env / "broken.yaml").write_text("a: [1, 2\n", encoding="utf-8")
    assert load_yaml("broken") == {}


def test_load_yaml_strict_rejects_bad_yaml(config_dir_env):
    (config_dir_env / "broken.yaml").write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="解析失败"):
        load_yaml("broken", strict=True)


def test_load_yaml_non_dict_returns_empty(config_dir_env):
    (config_dir_env / "scalar.yaml").write_text("just a string\n", encoding="utf-8")
    assert load_yaml("scalar") == {}


def test_yaml_override_changes_verdict(config_dir_env):
    """tmp yaml 抬高 t_stat_min → 原 pass 的 payload 变 fail（yaml 单源生效）。"""
    (config_dir_env / "acceptance.factor.yaml").write_text(
        "ic_abs_min: 0.03\nir_min: 0.5\nturnover_monthly_max: 0.8\nt_stat_min: 99.0\n",
        encoding="utf-8",
    )
    assert acceptance.factor_thresholds()["t_stat_min"] == 99.0
    result = acceptance.run_acceptance("factor-eval", _passing_factor_payload())
    assert result.verdict == "fail"
    assert any(c.name == "t_stat" and not c.passed for c in result.checks)


def test_missing_yaml_falls_back_to_code_defaults(config_dir_env):
    """configs/ 目录为空 → 回退代码默认，行为与历史硬编码一致。"""
    result = acceptance.run_acceptance("factor-eval", _passing_factor_payload())
    assert result.verdict == "pass"
    assert acceptance.factor_thresholds() == acceptance._FACTOR_DEFAULTS


def test_missing_yaml_warns_once(config_dir_env):
    import logging

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    h = _Capture()
    logging.getLogger("runner.config_loader").addHandler(h)
    try:
        from runner.config_loader import load_yaml_checked

        load_yaml_checked("acceptance.factor", ("ic_abs_min", "ir_min", "turnover_monthly_max", "t_stat_min"))
    finally:
        logging.getLogger("runner.config_loader").removeHandler(h)
    assert any(r.levelno == logging.WARNING and "不存在" in r.getMessage() for r in records)


def test_risk_yaml_override_risk_ci(config_dir_env):
    (config_dir_env / "acceptance.risk.yaml").write_text(
        "max_drawdown: 0.05\nposition_limit: 0.30\ncorrelation_limit: 0.60\n",
        encoding="utf-8",
    )
    payload = {
        "max_drawdown": 0.12,  # 历史默认 0.20 下 pass，收紧后 fail
        "position_limit": 0.20,
        "correlation_with_existing": 0.30,
        "tail_risk_var_99": -0.05,
    }
    assert acceptance.run_acceptance("risk-evaluation", payload).verdict == "fail"


def test_acceptance_yaml_shipped_values_match_history():
    """仓库自带 yaml 的数值 = 历史硬编码（行为零变化的直接证明）。"""
    load_yaml.cache_clear()
    f = acceptance.factor_thresholds()
    assert (f["ic_abs_min"], f["ir_min"], f["turnover_monthly_max"], f["t_stat_min"]) == (
        0.03, 0.5, 0.8, 2.0,
    )
    r = acceptance.risk_thresholds()
    assert (r["max_drawdown"], r["position_limit"], r["correlation_limit"]) == (
        0.15, 0.8, 0.6,
    )


def test_config_dir_override_env(config_dir_env):
    from runner.config_loader import config_dir

    assert config_dir() == Path(config_dir_env)

"""Risk Scope Subagent planning without executing pull-request code."""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from schemas.risk_gate_artifact import PRBinding, RiskApplicability
from scripts.ci import plan_risk_gate as planner_module
from scripts.ci.plan_risk_gate import plan


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / ".review-ci" / "risk_gate_catalog.yaml"


def test_capability_compiler_git_subprocess_does_not_inherit_provider_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_env: dict[str, str] = {}

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b"")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-git")
    monkeypatch.setattr(planner_module.subprocess, "run", fake_run)
    planner_module._run_git(tmp_path, "status", "--porcelain")
    assert "DEEPSEEK_API_KEY" not in captured_env
    assert captured_env["GIT_CONFIG_GLOBAL"] == "/dev/null"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "risk-planner@example.invalid")
    _git(repo, "config", "user.name", "Risk Planner Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _binding(base: str, head: str) -> PRBinding:
    return PRBinding(
        repository="HKUST-QUANT-SOCIETY/quantcode",
        pr_number=99,
        base_sha=base,
        head_sha=head,
    )


def test_docs_only_change_is_not_applicable_without_llm_call(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("documentation only\n", encoding="utf-8")
    _git(repo, "add", "docs/guide.md")
    _git(repo, "commit", "-m", "docs")
    head = _git(repo, "rev-parse", "HEAD")

    def forbidden_model_call(*args: Any, **kwargs: Any) -> dict:
        raise AssertionError("docs-only prefilter must not spend a provider call")

    result = plan(
        repo=repo,
        base=base,
        head=head,
        binding=_binding(base, head),
        catalog_path=CATALOG,
        planner_model="fake-planner",
        base_url="https://api.deepseek.com",
        model_call=forbidden_model_call,
    )

    assert result.applicability == RiskApplicability.NOT_APPLICABLE
    assert result.binding.head_sha == head


def test_unfamiliar_code_path_is_classified_by_subagent_not_a_fixed_path_list(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    research = repo / "new_team" / "alpha_lab"
    research.mkdir(parents=True)
    (research / "candidate.py").write_text("def signal(frame):\n    return frame\n", encoding="utf-8")
    _git(repo, "add", "new_team/alpha_lab/candidate.py")
    _git(repo, "commit", "-m", "new alpha surface")
    head = _git(repo, "rev-parse", "HEAD")
    called = False

    def fake_model_call(prompt: str, **kwargs: Any) -> dict:
        nonlocal called
        called = True
        assert "new_team/alpha_lab/candidate.py" in prompt
        return {
            "applicability": "not_evaluable",
            "subjects": [
                {
                    "kind": "strategy",
                    "identifier": "candidate",
                    "changed_files": ["new_team/alpha_lab/candidate.py"],
                }
            ],
            "risk_policy_id": "quant-risk-v1",
            "rationale": "The new strategy-like code has no executable backtest manifest.",
            "missing_requirements": ["BacktestManifest and immutable data binding"],
        }

    result = plan(
        repo=repo,
        base=base,
        head=head,
        binding=_binding(base, head),
        catalog_path=CATALOG,
        planner_model="fake-planner",
        base_url="https://api.deepseek.com",
        model_call=fake_model_call,
    )

    assert called is True
    assert result.applicability == RiskApplicability.NOT_EVALUABLE


def test_strategy_code_without_manifest_is_not_evaluable(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    strategy = repo / "tools" / "strategy"
    strategy.mkdir(parents=True)
    (strategy / "alpha.py").write_text("def signal(close):\n    return close > 0\n", encoding="utf-8")
    _git(repo, "add", "tools/strategy/alpha.py")
    _git(repo, "commit", "-m", "strategy")
    head = _git(repo, "rev-parse", "HEAD")

    def fake_model_call(prompt: str, **kwargs: Any) -> dict:
        assert "tools/strategy/alpha.py" in prompt
        assert "BacktestManifest" in prompt
        return {
            "applicability": "not_evaluable",
            "subjects": [
                {
                    "kind": "strategy",
                    "identifier": "alpha",
                    "changed_files": ["tools/strategy/alpha.py"],
                }
            ],
            "data_requests": [],
            "adapter_id": None,
            "window": None,
            "execution_policy": None,
            "benchmark": None,
            "risk_policy_id": "quant-risk-v1",
            "rationale": "The strategy has no declared executable backtest contract.",
            "missing_requirements": ["BacktestManifest with adapter, data, OOS window, and cost policy"],
        }

    result = plan(
        repo=repo,
        base=base,
        head=head,
        binding=_binding(base, head),
        catalog_path=CATALOG,
        planner_model="fake-planner",
        base_url="https://api.deepseek.com",
        model_call=fake_model_call,
    )

    assert result.applicability == RiskApplicability.NOT_EVALUABLE
    assert result.missing_requirements
    assert result.adapter is None


def test_evaluable_proposal_resolves_only_catalog_adapter(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    strategy = repo / "strategies"
    strategy.mkdir()
    (strategy / "backtest_manifest.json").write_text('{"adapter_id":"single-asset-backtrader-v1"}\n')
    _git(repo, "add", "strategies/backtest_manifest.json")
    _git(repo, "commit", "-m", "manifest")
    head = _git(repo, "rev-parse", "HEAD")

    def fake_model_call(prompt: str, **kwargs: Any) -> dict:
        return {
            "applicability": "evaluable",
            "subjects": [
                {
                    "kind": "strategy",
                    "identifier": "dual-ma-rb",
                    "changed_files": ["strategies/backtest_manifest.json"],
                    "backtest_manifest_path": "strategies/backtest_manifest.json",
                }
            ],
            "data_requests": [
                {
                    "logical_dataset": "cta-benchmark-rb-1m",
                    "fields": ["timestamp", "open", "high", "low", "close", "volume"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "symbols": ["rb"],
                    "purpose": "OOS strategy risk evaluation",
                    "require_immutable_snapshot": True,
                }
            ],
            "adapter_id": "single-asset-backtrader-v1",
            "adapter_parameters": {
                "strategy_name": "dual_ma",
                "strategy_version": "1.0",
                "short_window": 20,
                "long_window": 100,
                "position_size": 1.0,
            },
            "window": {
                "train_start": "2018-01-01",
                "train_end": "2019-06-30",
                "validation_start": "2019-07-01",
                "validation_end": "2019-12-31",
                "oos_start": "2020-01-01",
                "oos_end": "2020-12-31",
            },
            "execution_policy": {
                "policy_id": "cta-1m-v1",
                "observation_time": "bar close",
                "signal_time": "after bar close",
                "fill_time": "next bar open",
                "lag_bars": 1,
                "commission_bps": 1.0,
                "slippage_bps": 1.0,
                "stamp_duty_bps": 0.0,
                "enforce_suspension": True,
                "enforce_price_limits": True,
                "enforce_t_plus_one": False,
            },
            "benchmark": None,
            "risk_policy_id": "quant-risk-v1",
            "rationale": "Manifest and approved real-data adapter are present.",
            "missing_requirements": [],
        }

    result = plan(
        repo=repo,
        base=base,
        head=head,
        binding=_binding(base, head),
        catalog_path=CATALOG,
        planner_model="fake-planner",
        base_url="https://api.deepseek.com",
        model_call=fake_model_call,
    )

    assert result.applicability == RiskApplicability.EVALUABLE
    assert result.adapter is not None
    assert result.adapter.adapter_id == "single-asset-backtrader-v1"
    assert result.window and result.window.oos_start == date(2020, 1, 1)


def test_unknown_adapter_from_model_is_rejected(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    path = repo / "backtest_manifest.json"
    path.write_text("{}\n")
    _git(repo, "add", path.name)
    _git(repo, "commit", "-m", "manifest")
    head = _git(repo, "rev-parse", "HEAD")

    def fake_model_call(*args: Any, **kwargs: Any) -> dict:
        return {
            "applicability": "evaluable",
            "subjects": [{"kind": "model", "identifier": "x", "changed_files": [path.name]}],
            "data_requests": [
                {
                    "logical_dataset": "cta-benchmark-rb-1m",
                    "fields": ["close"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "purpose": "test",
                }
            ],
            "adapter_id": "arbitrary-shell",
            "adapter_parameters": {"strategy_name": "malicious"},
            "window": {"oos_start": "2020-01-01", "oos_end": "2020-12-31"},
            "execution_policy": {
                "policy_id": "x",
                "observation_time": "close",
                "signal_time": "close",
                "fill_time": "next open",
                "lag_bars": 1,
                "commission_bps": 1,
                "slippage_bps": 1,
                "stamp_duty_bps": 0,
            },
            "benchmark": None,
            "risk_policy_id": "quant-risk-v1",
            "rationale": "malicious adapter proposal",
            "missing_requirements": [],
        }

    with pytest.raises(ValueError, match="unknown adapter"):
        plan(
            repo=repo,
            base=base,
            head=head,
            binding=_binding(base, head),
            catalog_path=CATALOG,
            planner_model="fake-planner",
            base_url="https://api.deepseek.com",
            model_call=fake_model_call,
        )


def test_planner_cannot_invent_changed_files_or_dataset_fields(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    path = repo / "backtest_manifest.json"
    path.write_text("{}\n")
    _git(repo, "add", path.name)
    _git(repo, "commit", "-m", "manifest")
    head = _git(repo, "rev-parse", "HEAD")

    def invented_file(*args: Any, **kwargs: Any) -> dict:
        return {
            "applicability": "not_evaluable",
            "subjects": [
                {"kind": "model", "identifier": "x", "changed_files": ["not-in-the-pr.py"]}
            ],
            "risk_policy_id": "quant-risk-v1",
            "rationale": "invented binding",
            "missing_requirements": ["manifest"],
        }

    with pytest.raises(ValueError, match="invented changed files"):
        plan(
            repo=repo,
            base=base,
            head=head,
            binding=_binding(base, head),
            catalog_path=CATALOG,
            planner_model="fake-planner",
            base_url="https://api.deepseek.com",
            model_call=invented_file,
        )


def test_known_but_unavailable_materializer_is_not_evaluable(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    path = repo / "portfolio_backtest_manifest.json"
    path.write_text("{}\n")
    _git(repo, "add", path.name)
    _git(repo, "commit", "-m", "portfolio manifest")
    head = _git(repo, "rev-parse", "HEAD")

    def fake_model_call(*args: Any, **kwargs: Any) -> dict:
        return {
            "applicability": "evaluable",
            "subjects": [
                {
                    "kind": "portfolio",
                    "identifier": "ashare-book",
                    "changed_files": [path.name],
                    "backtest_manifest_path": path.name,
                }
            ],
            "data_requests": [
                {
                    "logical_dataset": "ashare-stock-daily-bar",
                    "fields": ["TradeDate", "Symbol", "Close", "IsSuspend"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "universe": "CSI1000",
                    "purpose": "OOS portfolio risk",
                }
            ],
            "adapter_id": "portfolio-backtest-v1",
            "adapter_parameters": {"holdings_artifact": "holdings.parquet"},
            "window": {"oos_start": "2024-01-01", "oos_end": "2024-12-31"},
            "execution_policy": {
                "policy_id": "ashare-daily-v1",
                "observation_time": "close",
                "signal_time": "after close",
                "fill_time": "next trading day open",
                "lag_bars": 1,
                "commission_bps": 3,
                "slippage_bps": 5,
                "stamp_duty_bps": 5,
            },
            "benchmark": "000852.SH",
            "risk_policy_id": "quant-risk-v1",
            "rationale": "The manifest declares a portfolio backtest.",
            "missing_requirements": [],
        }

    result = plan(
        repo=repo,
        base=base,
        head=head,
        binding=_binding(base, head),
        catalog_path=CATALOG,
        planner_model="fake-planner",
        base_url="https://api.deepseek.com",
        model_call=fake_model_call,
    )

    assert result.applicability == RiskApplicability.NOT_EVALUABLE
    assert any("materializer" in item for item in result.missing_requirements)

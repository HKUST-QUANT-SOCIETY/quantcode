"""Tests for write_pr_comment dedupe."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.risk.risk_tools import (
    calc_risk,
    clear_write_pr_comment_dedupe_cache,
    generate_risk_profile,
    write_pr_comment,
)


@pytest.fixture(autouse=True)
def reset_dedupe_cache():
    clear_write_pr_comment_dedupe_cache()
    yield
    clear_write_pr_comment_dedupe_cache()


def _sample_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _profile(scenario: str = "normal"):
    model_spec = _sample_model_spec()
    pr_url = "https://github.com/hkust-quant-society/quantcode/pull/42"
    return generate_risk_profile(
        model_spec,
        calc_risk(model_spec, scenario),
        pr_url=pr_url,
    )


def test_write_pr_comment_dedupes_same_pr_url_head_sha_profile(tmp_path, monkeypatch):
    profile = _profile("normal")
    pr_url = profile.pr_url
    assert pr_url is not None
    dedupe_db = tmp_path / "dedupe.sqlite"
    artifacts_root = tmp_path / "artifacts"
    write_calls: list[str] = []
    original_write_text = Path.write_text

    def counting_write_text(self, *args, **kwargs):
        write_calls.append(str(self))
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", counting_write_text)

    first = write_pr_comment(
        profile,
        pr_number="42",
        head_sha="abcdef1234567890",
        pr_url=pr_url,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db,
    )
    second = write_pr_comment(
        profile,
        pr_number="42",
        head_sha="abcdef1234567890",
        pr_url=pr_url,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db,
    )

    assert first == second
    assert write_calls == [str(artifacts_root / "pr-42-abcdef1.json")]
    with sqlite3.connect(dedupe_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM dedupe_log").fetchone()[0] == 1


def test_write_pr_comment_dedupe_allows_different_head_sha(tmp_path):
    profile = _profile("normal")
    pr_url = profile.pr_url
    assert pr_url is not None
    dedupe_db = tmp_path / "dedupe.sqlite"
    artifacts_root = tmp_path / "artifacts"

    first = write_pr_comment(
        profile,
        pr_number="42",
        head_sha="abcdef1234567890",
        pr_url=pr_url,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db,
    )
    second = write_pr_comment(
        profile,
        pr_number="42",
        head_sha="deadbeef1234567890",
        pr_url=pr_url,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db,
    )

    assert first["comment_id"] != second["comment_id"]
    assert len(list(artifacts_root.glob("*.json"))) == 2


def test_write_pr_comment_dedupe_allows_different_profile(tmp_path, monkeypatch):
    normal = _profile("normal")
    high_risk = _profile("high_risk")
    pr_url = normal.pr_url
    assert pr_url is not None
    dedupe_db = tmp_path / "dedupe.sqlite"
    artifacts_root = tmp_path / "artifacts"
    write_calls: list[str] = []
    original_write_text = Path.write_text

    def counting_write_text(self, *args, **kwargs):
        write_calls.append(str(self))
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", counting_write_text)

    write_pr_comment(
        normal,
        pr_number="42",
        head_sha="abcdef1234567890",
        pr_url=pr_url,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db,
    )
    second = write_pr_comment(
        high_risk,
        pr_number="42",
        head_sha="abcdef1234567890",
        pr_url=pr_url,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db,
    )

    assert len(write_calls) == 2
    payload = json.loads(Path(second["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["risk_profile"]["max_drawdown"] == high_risk.max_drawdown

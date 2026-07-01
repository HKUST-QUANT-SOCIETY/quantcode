"""Tests for the @dedupe_within side-effect guard."""
from __future__ import annotations

import sqlite3
import time

import pytest

from tools.utils.dedupe import dedupe_within


def test_dedupe_returns_cached_result_within_window(tmp_path):
    calls: list[str] = []
    db_path = tmp_path / "dedupe.sqlite"

    @dedupe_within(seconds=300, key=lambda msg: msg, db_path=db_path)
    def send_comment(msg: str) -> dict[str, int]:
        calls.append(msg)
        return {"call": len(calls)}

    assert send_comment("hello") == {"call": 1}
    assert send_comment("hello") == {"call": 1}
    assert calls == ["hello"]


def test_dedupe_keeps_different_keys_separate(tmp_path):
    calls: list[str] = []
    db_path = tmp_path / "dedupe.sqlite"

    @dedupe_within(seconds=300, key=lambda msg: msg, db_path=db_path)
    def send_comment(msg: str) -> int:
        calls.append(msg)
        return len(calls)

    assert send_comment("a") == 1
    assert send_comment("b") == 2
    assert send_comment("a") == 1
    assert calls == ["a", "b"]


def test_dedupe_expires_after_window(tmp_path):
    calls: list[str] = []
    db_path = tmp_path / "dedupe.sqlite"

    @dedupe_within(seconds=300, key="same-key", db_path=db_path)
    def send_comment() -> int:
        calls.append("called")
        return len(calls)

    assert send_comment() == 1
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE dedupe_log SET first_call_at = ?",
            (time.time() - 301,),
        )

    assert send_comment() == 2
    assert calls == ["called", "called"]


def test_dedupe_does_not_cache_exceptions(tmp_path):
    calls: list[str] = []
    db_path = tmp_path / "dedupe.sqlite"

    @dedupe_within(seconds=300, key="same-key", db_path=db_path)
    def flaky() -> str:
        calls.append("called")
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        return "ok"

    with pytest.raises(RuntimeError, match="temporary failure"):
        flaky()
    assert flaky() == "ok"
    assert calls == ["called", "called"]


def test_dedupe_rejects_negative_window():
    with pytest.raises(ValueError, match="seconds"):
        dedupe_within(seconds=-1, key="bad")

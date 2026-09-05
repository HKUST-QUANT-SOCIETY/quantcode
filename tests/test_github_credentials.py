from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import quantcode.github_credentials as credentials


def test_windows_file_provider_fails_closed_with_actionable_message(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("not-a-real-token", encoding="utf-8")
    monkeypatch.setattr(credentials.os, "name", "nt")
    with pytest.raises(PermissionError, match="OS keyring"):
        credentials._private_text(secret)


def test_keyring_provider_is_subject_scoped(monkeypatch):
    calls = []
    fake_keyring = SimpleNamespace(
        get_password=lambda service, subject: calls.append((service, subject)) or "fixture-token"
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setenv("QUANTCODE_GITHUB_KEYRING_SERVICE", "quantcode-github")
    monkeypatch.delenv("QUANTCODE_GITHUB_CREDENTIALS_FILE", raising=False)

    token = credentials.subject_token({"github_subject": "Fixture-User"})
    assert token == "fixture-token"
    assert calls == [("quantcode-github", "fixture-user")]


def test_keyring_provider_rejects_whitespace_token(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda service, subject: "bad token"),
    )
    monkeypatch.setenv("QUANTCODE_GITHUB_KEYRING_SERVICE", "quantcode-github")
    with pytest.raises(ValueError, match="invalid GitHub credential"):
        credentials.subject_token({"github_subject": "fixture-user"})

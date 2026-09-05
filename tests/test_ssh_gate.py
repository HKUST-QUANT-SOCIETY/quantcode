"""SSH research/development boundary tests for v5."""
from __future__ import annotations

import json

import pytest

from runner.permission_engine import check_ssh, enforce_ssh, reset_cache
from runner.server_ssh import classify_ssh_action, ssh_status


SSH_CFG = [
    {"name": "srv-a", "host": "10.1.1.11", "user": "quant", "env": "prod",
     "key_path": "/tmp/id_a", "mainline_dir": "/srv/prod"},
    {"name": "srv-dev", "host": "10.1.1.12", "user": "quant", "env": "dev",
     "key_path": "/tmp/id_dev", "mainline_dir": "/srv/dev"},
]


@pytest.fixture(autouse=True)
def ssh_cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", json.dumps(SSH_CFG))
    permission_file = tmp_path / "permissions.yaml"
    permission_file.write_text("permissions: {}\n", encoding="utf-8")
    monkeypatch.setenv("QUANTCODE_PERMISSIONS_FILE", str(permission_file))
    reset_cache()
    yield
    reset_cache()


@pytest.mark.parametrize(
    ("action", "target", "expected"),
    [
        ("read", "prod", "read"),
        ("read_mainline_file", "srv-a", "read"),
        ("write_file", "srv-dev", "dev_write"),
        ("write_file", "srv-a", "prod_write"),
        ("deploy", "prod", "prod_write"),
    ],
)
def test_classify_ssh_action(action, target, expected):
    assert classify_ssh_action(action, target) == expected


def test_read_and_development_write_are_allowed():
    assert check_ssh("read", "prod", {})["decision"] == "allow"
    assert enforce_ssh("write_file", "srv-dev", {})["decision"] == "allow"


def test_production_shell_write_is_denied_even_when_human_approved():
    with pytest.raises(PermissionError, match="production SSH writes"):
        check_ssh("write_file", "srv-a", {"human_approved": True, "role": "admin"})
    with pytest.raises(PermissionError, match="production SSH writes"):
        enforce_ssh("deploy", "prod", {"human_approved": True})


def test_ssh_status_is_read_only(monkeypatch, tmp_path):
    bindings = tmp_path / "authorized_groups.yaml"
    bindings.write_text(
        "bindings:\n  - fingerprint: SHA256:abc123\n    group: factor\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("quantcode.identity.DEFAULT_BINDINGS_PATH", bindings)
    status = ssh_status()
    assert status["configured"] is True
    assert status["group_bindings_ready"] is True
    assert {server["name"] for server in status["servers"]} == {"srv-a", "srv-dev"}

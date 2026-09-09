import hashlib
import json

import pytest

from scripts.bootstrap_test_v1_model import bootstrap


def fixture(tmp_path):
    config = tmp_path / "config" / "opencode.json"
    config.parent.mkdir(mode=0o700)
    config.write_text(json.dumps({"mcp": {"quantcode": {"enabled": True, "command": ["trusted-python"]}}}))
    auth = tmp_path / "data" / "auth.json"
    auth.parent.mkdir(mode=0o700)
    return config, auth, hashlib.sha256(config.read_bytes()).hexdigest()


def test_bootstrap_preserves_mcp_and_writes_only_member_proxy_token(tmp_path):
    config, auth, expected = fixture(tmp_path)
    token = "qcv1_" + "a" * 43
    bootstrap(config, auth, expected, token)
    settings, credentials = json.loads(config.read_text()), json.loads(auth.read_text())
    assert settings["mcp"]["quantcode"]["command"] == ["trusted-python"]
    assert settings["model"] == "organization-qwen/qwen3.7-flash"
    assert token not in config.read_text()
    assert credentials["organization-qwen"]["key"] == token
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (config, auth))
    with pytest.raises((ValueError, FileExistsError)):
        bootstrap(config, auth, hashlib.sha256(config.read_bytes()).hexdigest(), token)


def test_changed_config_and_upstream_key_cannot_be_bootstrapped(tmp_path):
    config, auth, expected = fixture(tmp_path)
    with pytest.raises(ValueError, match="member proxy"):
        bootstrap(config, auth, expected, "sk-" + "a" * 43)
    config.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        bootstrap(config, auth, expected, "qcv1_" + "a" * 43)
    assert not auth.exists()


def test_existing_auth_is_never_overwritten(tmp_path):
    config, auth, expected = fixture(tmp_path)
    auth.write_text("existing")
    with pytest.raises(FileExistsError):
        bootstrap(config, auth, expected, "qcv1_" + "a" * 43)
    assert auth.read_text() == "existing"

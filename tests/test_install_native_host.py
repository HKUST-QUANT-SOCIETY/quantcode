"""Personal native-host preparation; fixtures only, no services or accounts."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.install_native_host import enrolled_member, host_environment, render_unit, write_new
from quantcode.identity import fingerprint_of_public_key


def member_inputs():
    algorithm = b"ssh-ed25519"
    blob = len(algorithm).to_bytes(4, "big") + algorithm + (32).to_bytes(4, "big") + b"x" * 32
    key = "ssh-ed25519 " + base64.b64encode(blob).decode()
    fingerprint = fingerprint_of_public_key(key)
    entry = {"actor_id": "researcher", "public_key": key, "fingerprint": fingerprint,
             "group": "factor", "role": "analyst", "workspace_id": "workspace-researcher",
             "workspace_path": "/srv/quant/users/researcher"}
    registry = {"accounts": {"researcher": {"username": "qc-researcher", "uid": 1234, "gid": 1234,
                "workspace_path": entry["workspace_path"], "fingerprints": [fingerprint]}}}
    user = SimpleNamespace(pw_name="qc-researcher", pw_uid=1234, pw_gid=1234, pw_dir=entry["workspace_path"])
    return {"status": "APPROVED", "bindings": [entry]}, registry, user, fingerprint


def plan_fixture():
    roster, registry, user, fingerprint = member_inputs()
    return {"release": "native-1", "port": 6096, "gateway": "http://127.0.0.1:4097",
            "source": {"binary_name": "opencode"},
            "member": enrolled_member(roster, registry, "researcher", fingerprint, user, [1234]),
            "paths": {"release": "/opt/quantcode/native-hosts/researcher/native-1",
                      "state": "/var/lib/quantcode-native/researcher/native-1"}}


def test_host_requires_the_original_enrolled_user_and_exact_key():
    roster, registry, user, fingerprint = member_inputs()
    assert enrolled_member(roster, registry, "researcher", fingerprint, user, [1234])["uid"] == 1234
    with pytest.raises(PermissionError, match="enrollment"):
        enrolled_member(roster, registry, "researcher", fingerprint, user, [1234, 27])
    with pytest.raises(PermissionError, match="enrollment"):
        enrolled_member(roster, registry, "researcher", "SHA256:unregistered", user, [1234])
    with pytest.raises(PermissionError, match="enrollment"):
        enrolled_member(roster, registry, "researcher", fingerprint,
                        SimpleNamespace(**{**vars(user), "pw_uid": 0}), [1234])


def test_changed_roster_workspace_cannot_adopt_an_existing_linux_account():
    roster, registry, user, fingerprint = member_inputs()
    roster["bindings"][0]["workspace_path"] = "/srv/quant/users/another"
    with pytest.raises(PermissionError, match="workspace changed"):
        enrolled_member(roster, registry, "researcher", fingerprint, user, [1234])


def test_review_required_and_duplicate_key_are_rejected():
    roster, registry, user, fingerprint = member_inputs()
    with pytest.raises(ValueError, match="approved actor"):
        enrolled_member({**roster, "status": "REVIEW_REQUIRED"}, registry, "researcher", fingerprint, user, [1234])
    roster["bindings"].append(dict(roster["bindings"][0]))
    with pytest.raises(ValueError, match="one exact registered"):
        enrolled_member(roster, registry, "researcher", fingerprint, user, [1234])


def test_source_public_key_must_match_the_roster_fingerprint():
    roster, registry, user, fingerprint = member_inputs()
    encoded = roster["bindings"][0]["public_key"].split()[1]
    changed = bytearray(base64.b64decode(encoded))
    changed[-1] ^= 1
    roster["bindings"][0]["public_key"] = "ssh-ed25519 " + base64.b64encode(changed).decode()
    with pytest.raises(ValueError, match="fingerprint"):
        enrolled_member(roster, registry, "researcher", fingerprint, user, [1234])


def test_unit_runs_existing_cli_as_enrolled_user_without_inline_password():
    plan = plan_fixture()
    unit = render_unit(plan)
    assert "User=qc-researcher" in unit
    assert "WorkingDirectory=/srv/quant/users/researcher\n" in unit
    assert "serve --hostname 127.0.0.1 --port 6096 --no-mdns" in unit
    assert "EnvironmentFile=/opt/quantcode/native-hosts/researcher/native-1/host.env\n" in unit
    assert "EnvironmentFile=/opt/quantcode/native-hosts/researcher/native-1/access.env\n" in unit
    assert "OPENCODE_SERVER_PASSWORD=" not in unit
    assert "Restart=no" in unit and "KillMode=control-group" in unit
    assert "mcp_server" not in unit


def test_fresh_control_storage_is_separate_from_workspace_and_model_credentials():
    plan = plan_fixture()
    environment = host_environment(plan)
    workspace = Path(plan["member"]["workspace_path"])
    assert environment["OPENCODE_CHANNEL"] == "quantcode"
    assert environment["QUANTCODE_UNIFIED_RUNTIME"] == "1"
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "QUANTCODE_IDENTITY_SESSION_FILE"):
        assert not Path(environment[key]).is_relative_to(workspace)
    assert "QUANTCODE_API_KEY" not in environment
    assert "OPENCODE_SERVER_PASSWORD" not in environment
    assert "OPENCODE_SERVER_PASSWORD" not in json.dumps(plan)


def test_private_file_creation_never_overwrites_a_previous_credential(tmp_path):
    file = tmp_path / "access.env"
    write_new(file, b"fixture-original", 0o600, uid=os.getuid(), gid=os.getgid())
    with pytest.raises(FileExistsError):
        write_new(file, b"replacement", 0o600, uid=os.getuid(), gid=os.getgid())
    assert file.read_bytes() == b"fixture-original"
    assert file.stat().st_mode & 0o777 == 0o600

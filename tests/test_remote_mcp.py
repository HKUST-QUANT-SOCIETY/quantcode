import json
import os
from pathlib import Path
import sys

import pytest

from quantcode.mcp_host import ssh_command
from quantcode.remote_mcp import private_directory, read_header, sandbox_command, validate_binding


def test_header_keeps_following_mcp_frame_on_the_pipe():
    read, write = os.pipe()
    header = {"version": 1, "token": "a" * 64, "session_id": "b" * 32}
    try:
        os.write(write, json.dumps(header).encode() + b'\n{"jsonrpc":"2.0","id":1}\n')
        assert read_header(read) == header
        assert os.read(read, 4096) == b'{"jsonrpc":"2.0","id":1}\n'
    finally:
        os.close(read)
        os.close(write)


@pytest.mark.parametrize("header", [
    {}, {"version": 1, "token": "bad", "session_id": "b" * 32},
    {"version": 1, "token": "a" * 64, "session_id": "b" * 32, "actor_id": "admin"},
    {"version": 1, "token": "a" * 64, "session_id": "b" * 32, "gateway": "http://elsewhere"},
])
def test_identity_header_rejects_untrusted_overrides(header):
    read, write = os.pipe()
    try:
        os.write(write, json.dumps(header).encode() + b"\n")
        with pytest.raises(ValueError):
            read_header(read)
    finally:
        os.close(read)
        os.close(write)


def test_missing_and_oversized_header_are_bounded():
    read, write = os.pipe()
    try:
        with pytest.raises(TimeoutError):
            read_header(read, timeout=0.01)
        os.write(write, b"x" * 4096)
        with pytest.raises(ValueError, match="large"):
            read_header(read)
    finally:
        os.close(read)
        os.close(write)


@pytest.mark.parametrize("field,value", [("actor_id", "someone-else"), ("workspace_id", "shared"),
                                        ("workspace_path", "/root"), ("session_id", "wrong")])
def test_gateway_identity_must_match_unix_enrollment(field, value):
    context = {"actor_id": "person", "workspace_id": "research", "workspace_path": "/srv/quant/users/person", "session_id": "expected"}
    enrollment = {**context, "uid": 1234, "username": "qc-person"}
    validate_binding(context, enrollment, uid=1234, username="qc-person", home=context["workspace_path"], session_id="expected")
    with pytest.raises(PermissionError):
        validate_binding({**context, field: value}, enrollment, uid=1234, username="qc-person",
                         home=context["workspace_path"], session_id="expected")
    with pytest.raises(PermissionError):
        validate_binding(context, enrollment, uid=0, username="root", home="/root", session_id="expected")


def test_private_state_rejects_symlinks_and_shared_permissions(tmp_path):
    state = tmp_path / "state"
    private_directory(state, os.getuid(), create=True)
    link = tmp_path / "alias"
    link.symlink_to(state)
    with pytest.raises(PermissionError):
        private_directory(link, os.getuid())
    state.chmod(0o755)
    with pytest.raises(PermissionError):
        private_directory(state, os.getuid())


def test_remote_command_uses_fixed_entrypoint_and_never_forwards_agent(tmp_path):
    public = tmp_path / "key.pub"
    public.write_text("ssh-ed25519 public-fixture")
    command = ssh_command("qs-gpu", "person", public)
    assert command[-3:] == ["qc-person", "qs-gpu", "/opt/quantcode/ops/remote-mcp"]
    assert "ForwardAgent=no" in command and "StrictHostKeyChecking=yes" in command
    for host in ("-oProxyCommand=unsafe", "user@server", "server; command", "server\ncommand"):
        with pytest.raises(ValueError):
            ssh_command(host, "person", public)
    with pytest.raises(ValueError):
        ssh_command("qs-gpu", "person;command", public)


def test_sandbox_runs_production_mcp_with_bounded_lifetime_and_private_state():
    root = Path("/opt/quantcode/runtime/revision")
    command = sandbox_command(root, Path("/srv/quant/users/person"), Path("/run/user/1234/session/identity.json"), "unit", 60)
    assert "--property=RuntimeMaxSec=60" in command
    assert "--property=NoNewPrivileges=yes" in command
    assert "--property=BindPaths=/srv/quant/users/person/.quantcode:/opt/quantcode/runtime/revision/.quantcode" in command
    assert "QUANTCODE_ENV=production" in command
    assert "QUANTCODE_ALLOW_UNAUTH=1" not in command


@pytest.mark.skipif(sys.platform == "win32", reason="SSH stdio uses POSIX process signals")
def test_local_relay_preserves_protocol_frames(tmp_path):
    import subprocess

    root = Path(__file__).resolve().parents[1]
    echo = "import sys; header=sys.stdin.buffer.readline(); sys.stdout.buffer.write(sys.stdin.buffer.read())"
    call = "from quantcode.mcp_host import relay; import sys; raise SystemExit(relay([sys.executable, '-c', sys.argv[1]], {'version':1}))"
    result = subprocess.run([sys.executable, "-c", call, echo], cwd=root, input=b'{"jsonrpc":"2.0","id":1}\n', capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout == b'{"jsonrpc":"2.0","id":1}\n'

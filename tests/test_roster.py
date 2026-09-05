"""F-01 survey admission and actual OpenSSH proof-of-possession regressions."""
import subprocess

import pytest
import yaml

from quantcode.identity import load_bindings, resolve_identity
from quantcode.identity_challenge import ChallengeStore, authenticate, IdentityChallengeError
from quantcode.roster import compile_records, normalize_public_key


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "fixture-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
    return path


def record(key, row=2, email="researcher@example.test", group="因子挖掘组"):
    return {"row": row, "name": "Test Researcher", "email": email, "group": group,
            "public_key": key.with_suffix(".pub").read_text()}


def test_duplicate_submissions_share_actor_and_do_not_grant_github_scope(key):
    result = compile_records([record(key), record(key, row=3)], "/srv/research")
    assert result["summary"] == {"submissions": 2, "people": 1, "candidate_bindings": 1,
                                 "pending_people": 0, "rejected_rows": 0}
    entry = result["bindings"][0]
    assert entry["group"] == "factor"
    assert entry["role"] == "analyst"
    assert entry["resource_scopes"] == ["memory:factor"]
    assert "github_subject" not in entry
    assert entry["workspace_path"].startswith("/srv/research/member-")


def test_ambiguous_groups_never_become_admin(key):
    result = compile_records([record(key, group="基建组/因子组")], "/srv/research")
    assert result["bindings"] == []
    assert result["people"][0]["issues"] == ["group_confirmation_required"]


def test_shared_key_across_people_blocks_both(key):
    result = compile_records([record(key), record(key, row=3, email="other@example.test")], "/srv/research")
    assert result["bindings"] == []
    assert result["summary"]["pending_people"] == 2


def test_group_conflicts_do_not_use_last_submission(key):
    result = compile_records([record(key), record(key, row=3, group="风控组")], "/srv/research")
    assert result["bindings"] == []


def test_bare_key_recovery_and_malformed_key_rejection(key):
    public = key.with_suffix(".pub").read_text()
    assert normalize_public_key(public.split()[1]) == normalize_public_key(public)
    for bad in ["SHA256:abc", "ssh-ed25519 YWJj", "-----BEGIN PRIVATE KEY-----", "ssh-rsa " + public.split()[1]]:
        with pytest.raises(ValueError):
            normalize_public_key(bad)


def test_candidate_cannot_be_used_as_active_roster(key, tmp_path):
    candidate = compile_records([record(key)], "/srv/research")
    path = tmp_path / "candidate.yaml"
    path.write_text(yaml.safe_dump(candidate))
    with pytest.raises(ValueError, match="requires review"):
        load_bindings(path)


def test_reviewed_roster_authenticates_real_signature_and_rejects_replay(key, tmp_path):
    candidate = compile_records([record(key)], "/srv/research")
    roster = tmp_path / "authorized.yaml"
    # This activates a generated test identity only, never the personnel workbook.
    roster.write_text(yaml.safe_dump({"bindings": candidate["bindings"]}))
    entry = candidate["bindings"][0]
    store = ChallengeStore()
    challenge = store.issue(entry["fingerprint"])
    message = tmp_path / "challenge"
    message.write_text(challenge["nonce"])
    subprocess.run(["ssh-keygen", "-Y", "sign", "-n", "quantcode", "-f", str(key), str(message)],
                   check=True, capture_output=True)
    args = dict(challenge_id=challenge["challenge_id"], public_key=entry["public_key"],
                signature=message.with_suffix(".sig").read_text(), roster_path=roster)
    session = authenticate(store, **args)
    assert session.actor_id == entry["actor_id"]
    assert session.group == "factor"
    assert session.role == "analyst"
    assert session.identity_source == "ssh_roster"
    assert resolve_identity(entry["fingerprint"], roster)["actor_id"] == session.actor_id
    with pytest.raises(IdentityChallengeError, match="already used"):
        authenticate(store, **args)


def test_production_stdio_uses_reviewed_roster_and_rejects_group_override(key, tmp_path):
    import json
    import os
    from pathlib import Path
    import sys

    result = compile_records([record(key)], "/srv/research")
    roster = tmp_path / "authorized.yaml"
    roster.write_text(yaml.safe_dump({"bindings": result["bindings"]}))
    entry = result["bindings"][0]
    root = Path(__file__).resolve().parents[1]
    env = {name: value for name, value in os.environ.items() if not name.startswith("QUANTCODE_")}
    env.update(QUANTCODE_ENV="production", QUANTCODE_SSH_FINGERPRINT=entry["fingerprint"], PYTHONPATH=str(root))
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "session_context", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_agent", "arguments": {"task": "fixture", "group": "risk"}}},
    ]
    command = "from quantcode import identity; import runpy,sys; identity.DEFAULT_BINDINGS_PATH=sys.argv[1]; runpy.run_module('quantcode.mcp_server',run_name='__main__')"
    process = subprocess.run([sys.executable, "-c", command, str(roster)],
                             input="".join(json.dumps(item) + "\n" for item in messages),
                             capture_output=True, text=True, cwd=root, env=env, timeout=30)
    assert process.returncode == 0, process.stderr[-1000:]
    responses = {item["id"]: item for item in map(json.loads, process.stdout.splitlines())}
    context = json.loads(responses[2]["result"]["content"][0]["text"])
    assert context["actor_id"] == entry["actor_id"]
    assert context["group"] == "factor"
    assert context["identity_source"] == "ssh_roster"
    assert "group mismatch" in responses[3]["result"]["content"][0]["text"]


def test_production_context_rejects_roster_read_failure(monkeypatch):
    from quantcode import mcp_server

    monkeypatch.setenv("QUANTCODE_ENV", "production")
    monkeypatch.setattr(mcp_server, "_SESSION_CONTEXT", None)
    monkeypatch.setattr(mcp_server, "_get_ssh_fingerprint", lambda: "SHA256:fixture")
    def unavailable(*args):
        raise OSError("roster unavailable")
    monkeypatch.setattr("quantcode.identity.resolve_identity", unavailable)
    with pytest.raises(RuntimeError, match="roster could not be loaded"):
        mcp_server._session_context_for_call("factor")

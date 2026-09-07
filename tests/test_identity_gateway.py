"""Real OpenSSH agent signatures against an isolated gateway/roster database."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from quantcode.gateway import IdentityGateway
from quantcode.identity import fingerprint_of_public_key
from schemas.session_context import SessionContext


@pytest.fixture
def gateway_login(tmp_path, monkeypatch):
    key = tmp_path / "test-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True)
    public_key = key.with_suffix(".pub").read_text().strip()
    entry = {
        "fingerprint": fingerprint_of_public_key(public_key), "actor_id": "fixture-actor",
        "role": "analyst", "group": "factor", "workspace_id": "fixture-workspace",
        "workspace_path": str(tmp_path), "github_subject": "fixture-subject", "resource_scopes": ["repo:fixture"],
    }
    roster = tmp_path / "roster.yaml"
    roster.write_text(yaml.safe_dump({"bindings": [entry]}))
    gateway = IdentityGateway(roster=roster, database=tmp_path / "gateway.db")
    # Short socket path avoids macOS's Unix-domain path length limit. This is a
    # separate test agent; never load test keys into the user's existing agent.
    with tempfile.TemporaryDirectory(prefix="qc-agent-", dir="/tmp") as directory:
        socket = Path(directory) / "socket"
        agent = subprocess.Popen(["ssh-agent", "-D", "-a", str(socket)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not socket.exists():
                if agent.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("isolated SSH agent did not start")
                time.sleep(0.01)
            env = {**os.environ, "SSH_AUTH_SOCK": str(socket)}
            subprocess.run(["ssh-add", str(key)], env=env, check=True, capture_output=True)
            monkeypatch.setenv("SSH_AUTH_SOCK", str(socket))

            def login():
                challenge = gateway.issue(public_key)
                signed = subprocess.run(
                    ["ssh-keygen", "-Y", "sign", "-U", "-f", str(key.with_suffix(".pub")), "-n", "quantcode"],
                    input=challenge["nonce"], text=True, env=env, capture_output=True, check=True, timeout=10,
                )
                payload = {"challenge_id": challenge["challenge_id"], "public_key": public_key, "signature": signed.stdout}
                return gateway.verify(payload), payload

            yield gateway, login, roster, entry
        finally:
            agent.terminate()
            agent.wait(timeout=5)


@pytest.fixture
def host_gateway(gateway_login):
    from quantcode.gateway import handler

    gateway, _, roster, entry = gateway_login
    roster.write_text(yaml.safe_dump({"bindings": [{**entry, "group": "model", "groups": ["model", "factor"]}]}))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(gateway))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield gateway, f"http://127.0.0.1:{server.server_port}", roster.parent / "test-key.pub", roster.parent / "host-session.json"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_host_lists_live_groups_signs_selected_group_and_revokes_on_logout(host_gateway):
    from quantcode.identity_login import describe_identity, login, logout

    gateway, url, key, session_file = host_gateway
    identity = describe_identity(gateway=url, public_key=key, session_file=session_file)
    assert identity == {"group": "model", "groups": ["model", "factor"], "session": None}
    assert not gateway.challenges._items
    context = login(gateway=url, public_key=key, session_file=session_file, group="factor")
    assert context["group"] == "factor"
    token = json.loads(session_file.read_text())["token"]
    described = describe_identity(gateway=url, public_key=key, session_file=session_file)
    assert described["session"]["session_id"] == context["session_id"]
    assert token not in json.dumps(described)
    login(gateway=url, public_key=key, session_file=session_file, group="model")
    with pytest.raises(PermissionError):
        gateway.session(token)
    replacement = json.loads(session_file.read_text())["token"]
    logout(session_file)
    assert not session_file.exists()
    with pytest.raises(PermissionError):
        gateway.session(replacement)
    logout(session_file)


def test_host_logout_does_not_claim_success_when_gateway_is_unreachable(tmp_path):
    import httpx
    from quantcode.identity_login import logout

    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps({"gateway": "http://127.0.0.1:1", "token": "unrevoked-fixture"}))
    session_file.chmod(0o600)
    with pytest.raises(httpx.TransportError):
        logout(session_file)
    assert session_file.exists()


def test_real_host_http_login_mcp_logout(host_gateway):
    import sys

    bun = shutil.which("bun")
    if bun is None:
        pytest.skip("Bun is required for the real host HTTP integration")
    _, url, key, session_file = host_gateway
    root = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("QUANTCODE_")}
    env.update(QUANTCODE_IDENTITY_INTEGRATION="1", QUANTCODE_HOST_PYTHON=sys.executable,
               QUANTCODE_BACKEND_ROOT=str(root), QUANTCODE_PUBLIC_KEY_FILE=str(key),
               QUANTCODE_IDENTITY_SESSION_FILE=str(session_file), QUANTCODE_GATEWAY_URL=url)
    result = subprocess.run([bun, "test", "--timeout", "45000", "test/server/quantcode-identity.integration.test.ts"],
                            cwd=root / "frontend/packages/opencode", env=env, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr[-6000:]
    assert not session_file.exists()


def test_shared_memory_is_live_across_actors_and_rejects_scope_overrides(gateway_login, tmp_path, monkeypatch):
    import httpx
    from quantcode.gateway import handler
    from quantcode import mcp_server
    from runner.memory.service import MemoryService

    gateway, first_login, roster, entry = gateway_login
    memory_root = tmp_path / "authority"
    gateway.memory_root = memory_root
    store = MemoryService(memory_root / ".quantcode/memory.db", root=memory_root, requester_group="factor")
    store.write(scope="groups", scope_id="factor", key="canonical", body="sharedword maintained factor reference")
    store.write(scope="global", key="public", body="sharedword public contract")
    store.write(scope="sessions", scope_id="private", key="runtime", body="sharedword runtime must stay private")
    MemoryService(store.db_path, root=memory_root, requester_group="model").write(
        scope="groups", scope_id="model", key="secret", body="sharedword private model reference")
    second_key = tmp_path / "second-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(second_key)], check=True, capture_output=True)
    public = second_key.with_suffix(".pub").read_text()
    second_entry = {**entry, "actor_id": "second-actor", "fingerprint": fingerprint_of_public_key(public), "groups": ["factor", "model"]}
    roster.write_text(yaml.safe_dump({"bindings": [entry, second_entry]}))
    first, _ = first_login()
    challenge = gateway.issue(public)
    signature = subprocess.run(["ssh-keygen", "-Y", "sign", "-n", "quantcode", "-f", str(second_key)],
                               input=challenge["nonce"], text=True, capture_output=True, check=True).stdout
    second = gateway.verify({"challenge_id": challenge["challenge_id"], "public_key": public, "signature": signature})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(gateway))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client:
            for signed in (first, second):
                headers = {"Authorization": f"Bearer {signed['token']}"}
                payload = {"query": "sharedword", "expected_session_id": signed["session"]["session_id"]}
                response = client.post("/memory/search", json=payload, headers=headers)
                assert response.status_code == 200
                hits = response.json()["hits"]
                assert {hit["scope"] for hit in hits} == {"groups", "global"}
                assert {hit["scope_id"] for hit in hits} == {"factor", ""}
                assert all(str(memory_root) not in hit["path"] for hit in hits)
                for override in ({"group": "model"}, {"role": "admin"}, {"memory_root": str(tmp_path)}, {"limit": 51}):
                    rejected = client.post("/memory/search", json={**payload, **override}, headers=headers)
                    assert rejected.status_code == 400
            # The real MCP path must use the authority, not its private local DB.
            session_file = tmp_path / "session.json"
            session_file.write_text(json.dumps({"gateway": str(client.base_url), "token": second["token"]}))
            session_file.chmod(0o600)
            monkeypatch.setenv("QUANTCODE_IDENTITY_SESSION_FILE", str(session_file))
            monkeypatch.setenv("QUANTCODE_SHARED_MEMORY", "gateway")
            monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path / "empty-private-runtime")
            result = mcp_server._search_memory_execute(mcp_server.SearchMemoryArgs(query="sharedword"), second["session"])
            assert result["status"] == "CONNECTED" and len(result["hits"]) == 2
            store.write(scope="groups", scope_id="factor", key="new", body="newsharedword live update")
            live = mcp_server._search_memory_execute(mcp_server.SearchMemoryArgs(query="newsharedword"), second["session"])
            assert len(live["hits"]) == 1
            gateway.logout(second["token"])
            with pytest.raises(PermissionError, match="AUTHENTICATION_REQUIRED"):
                mcp_server._search_memory_execute(mcp_server.SearchMemoryArgs(query="sharedword"), second["session"])
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_shared_memory_admin_read_requires_authority_audit(gateway_login, tmp_path, monkeypatch):
    from runner.memory.service import MemoryService
    from runner import evidence

    gateway, login, roster, entry = gateway_login
    root = tmp_path / "authority"
    gateway.memory_root = root
    roster.write_text(yaml.safe_dump({"bindings": [{**entry, "role": "admin"}]}))
    session, _ = login()
    store = MemoryService(root / ".quantcode/memory.db", root=root, requester_group="model")
    store.write(scope="groups", scope_id="model", key="secret", body="auditword model knowledge")
    payload = {"query": "auditword", "expected_session_id": session["session"]["session_id"]}
    result = gateway.search_memory(session["token"], payload)
    assert result["hits"][0]["scope_id"] == "model"
    logs = list((root / ".quantcode/evidence").glob("admin-read-*.jsonl"))
    assert len(logs) == 1 and "auditword" not in logs[0].read_text()

    def unavailable(*args, **kwargs):
        raise OSError("audit unavailable")

    monkeypatch.setattr(evidence, "append_event", unavailable)
    with pytest.raises(OSError):
        gateway.search_memory(session["token"], payload)


def test_real_agent_login_persists_only_token_hash_and_rejects_replay(gateway_login):
    gateway, login, roster, entry = gateway_login
    result, payload = login()
    token = result["token"]
    assert gateway.session(token).actor_id == entry["actor_id"]
    restarted = IdentityGateway(roster=roster, database=gateway.database)
    assert restarted.session(token).session_id == result["session"]["session_id"]
    with sqlite3.connect(gateway.database) as conn:
        row = conn.execute("SELECT token_hash,context FROM identity_sessions").fetchone()
    assert row[0] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row[1]
    assert gateway.database.stat().st_mode & 0o777 == 0o600
    with pytest.raises(PermissionError, match="already used"):
        gateway.verify(payload)


@pytest.mark.parametrize("change", [{"role": "admin"}, {"group": "model"}, {"resource_scopes": []}, {"workspace_path": "/different-workspace"}])
def test_roster_change_revokes_existing_session_permanently(gateway_login, change):
    gateway, login, roster, entry = gateway_login
    result, _ = login()
    roster.write_text(yaml.safe_dump({"bindings": [{**entry, **change}]}))
    with pytest.raises(PermissionError):
        gateway.session(result["token"])
    roster.write_text(yaml.safe_dump({"bindings": [entry]}))
    with pytest.raises(PermissionError, match="revoked"):
        gateway.session(result["token"])


def test_logout_and_expiration_reject_stored_credentials(gateway_login):
    gateway, login, _, _ = gateway_login
    first, _ = login()
    gateway.logout(first["token"])
    with pytest.raises(PermissionError):
        gateway.session(first["token"])
    second, _ = login()
    context = gateway.session(second["token"])
    expired = context.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    with sqlite3.connect(gateway.database) as conn:
        conn.execute("UPDATE identity_sessions SET context=?", (expired.model_dump_json(),))
    with pytest.raises(PermissionError, match="expired"):
        gateway.session(second["token"])


def test_review_required_roster_never_issues_challenge(gateway_login):
    gateway, _, roster, entry = gateway_login
    roster.write_text(yaml.safe_dump({"status": "REVIEW_REQUIRED", "bindings": [entry]}))
    with pytest.raises(ValueError, match="review before activation"):
        gateway.issue(roster.parent.joinpath("test-key.pub").read_text())


def test_multigroup_gateway_issues_selected_group_and_revalidates_membership(gateway_login):
    gateway, login, roster, entry = gateway_login
    multi = {**entry, "group": "model", "groups": ["model", "factor"],
             "resource_scopes": ["memory:model", "memory:factor"]}
    roster.write_text(yaml.safe_dump({"bindings": [multi]}))
    public_key = Path(roster.parent / "test-key.pub").read_text()
    challenge = gateway.issue(public_key, requested_group="factor")
    assert challenge["groups"] == ["model", "factor"]
    signed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-n", "quantcode", "-f", str(roster.parent / "test-key" )],
        input=challenge["nonce"], text=True, capture_output=True, check=True,
    )
    result = gateway.verify({"challenge_id": challenge["challenge_id"], "public_key": public_key,
                             "signature": signed.stdout, "group": "factor"})
    assert result["session"]["group"] == "factor"
    assert result["groups"] == ["model", "factor"]
    assert gateway.session(result["token"]).group == "factor"


def _signed_group_payload(gateway, roster, group):
    public_key = (roster.parent / "test-key.pub").read_text()
    challenge = gateway.issue(public_key, requested_group=group)
    signed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-n", "quantcode", "-f", str(roster.parent / "test-key")],
        input=challenge["nonce"], text=True, capture_output=True, check=True, timeout=10,
    )
    return {"challenge_id": challenge["challenge_id"], "public_key": public_key,
            "signature": signed.stdout, "group": group}


def test_challenge_cannot_change_to_another_authorized_group(gateway_login):
    gateway, _, roster, entry = gateway_login
    roster.write_text(yaml.safe_dump({"bindings": [{**entry, "groups": ["factor", "model"]}]}))
    payload = _signed_group_payload(gateway, roster, "factor")
    with pytest.raises(PermissionError, match="group"):
        gateway.verify({**payload, "group": "model"})
    with pytest.raises(PermissionError, match="already used"):
        gateway.verify(payload)


def test_multigroup_session_has_only_selected_group_memory_scope(gateway_login):
    gateway, _, roster, entry = gateway_login
    multi = {**entry, "group": "model", "groups": ["model", "factor"],
             "resource_scopes": ["memory:model", "memory:factor", "repo:fixture", "memory:project:shared:read"]}
    roster.write_text(yaml.safe_dump({"bindings": [multi]}))
    result = gateway.verify(_signed_group_payload(gateway, roster, "factor"))
    session = gateway.session(result["token"])
    assert session.group == "factor"
    assert session.resource_scopes == ["memory:factor", "repo:fixture", "memory:project:shared:read"]


def test_removing_secondary_membership_revokes_primary_session(gateway_login):
    gateway, _, roster, entry = gateway_login
    roster.write_text(yaml.safe_dump({"bindings": [{**entry, "groups": ["factor", "model"]}]}))
    result = gateway.verify(_signed_group_payload(gateway, roster, "factor"))
    roster.write_text(yaml.safe_dump({"bindings": [entry]}))
    with pytest.raises(PermissionError):
        gateway.session(result["token"])
    roster.write_text(yaml.safe_dump({"bindings": [{**entry, "groups": ["factor", "model"]}]}))
    with pytest.raises(PermissionError, match="revoked"):
        gateway.session(result["token"])


def test_production_mcp_uses_live_multigroup_gateway_context(gateway_login, tmp_path):
    import json
    import sys
    import threading
    from http.server import ThreadingHTTPServer
    from quantcode.gateway import handler

    gateway, _, roster, entry = gateway_login
    multi = {**entry, "group": "model", "groups": ["model", "factor"],
             "resource_scopes": ["memory:model", "memory:factor"]}
    roster.write_text(yaml.safe_dump({"bindings": [multi]}))
    login = gateway.verify(_signed_group_payload(gateway, roster, "factor"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(gateway))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    session_file = tmp_path / "host-session.json"
    session_file.write_text(json.dumps({"gateway": f"http://127.0.0.1:{server.server_port}", "token": login["token"]}))
    session_file.chmod(0o600)
    root = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("QUANTCODE_")}
    env.update(QUANTCODE_ENV="production", QUANTCODE_IDENTITY_SESSION_FILE=str(session_file), PYTHONPATH=str(root))
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "session_context", "arguments": {}}}
    wrong_group = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "run_agent", "arguments": {"task": "read only", "group": "model"}}}
    try:
        result = subprocess.run([sys.executable, "-m", "quantcode.mcp_server"], cwd=root, env=env,
                                input=json.dumps(request) + "\n" + json.dumps(wrong_group) + "\n",
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr[-1000:]
        responses = [json.loads(line)["result"] for line in result.stdout.splitlines()]
        context = json.loads(responses[0]["content"][0]["text"])
        assert context["session_id"] == login["session"]["session_id"]
        assert context["group"] == "factor"
        assert context["authorized_groups"] == ["model", "factor"]
        assert context["resource_scopes"] == ["memory:factor"]
        rejected = json.loads(responses[1]["content"][0]["text"])
        assert rejected["status"] == "error" and "group mismatch" in rejected["error"]
        assert login["token"] not in result.stdout + result.stderr

        roster.write_text(yaml.safe_dump({"bindings": [{**multi, "groups": ["model"]}]}))
        revoked = subprocess.run([sys.executable, "-m", "quantcode.mcp_server"], cwd=root, env=env,
                                 input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=30)
        assert revoked.returncode != 0
        assert "AUTHENTICATION_REQUIRED" in revoked.stderr
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("reviewer_role,reviewer_group", [("approver", "factor"), ("admin", "agent")])
def test_checkpoint_revalidation_requires_live_creator_and_same_group_approver(gateway_login, tmp_path, reviewer_role, reviewer_group):
    gateway, login, roster, creator_entry = gateway_login
    creator, _ = login()

    approver_key = tmp_path / "approver-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(approver_key)],
        check=True,
        capture_output=True,
    )
    approver_entry = {
        **creator_entry,
        "fingerprint": fingerprint_of_public_key(approver_key.with_suffix(".pub").read_text().strip()),
        "actor_id": "fixture-approver",
        "role": reviewer_role,
        "group": reviewer_group,
    }
    roster.write_text(yaml.safe_dump({"bindings": [creator_entry, approver_entry]}))
    now = datetime.now(timezone.utc)
    approver_context = SessionContext(
        session_id="approver-session",
        actor_id=approver_entry["actor_id"],
        role=approver_entry["role"],
        group=approver_entry["group"],
        workspace_id=approver_entry["workspace_id"],
        workspace_path=approver_entry["workspace_path"],
        github_subject=approver_entry["github_subject"],
        resource_scopes=approver_entry["resource_scopes"],
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    approver_token = "fixture-approver-token"
    with sqlite3.connect(gateway.database) as conn:
        conn.execute(
            "INSERT INTO identity_sessions VALUES(?,?,?)",
            (
                hashlib.sha256(approver_token.encode()).hexdigest(),
                approver_entry["fingerprint"],
                approver_context.model_dump_json(),
            ),
        )

    assert gateway.validate_checkpoint(approver_token, creator["session"]) == {"valid": True}
    with pytest.raises(PermissionError):
        gateway.validate_checkpoint(approver_token, {**creator["session"], "group": "model"})
    gateway.logout(creator["token"])
    with pytest.raises(PermissionError, match="creator session expired or revoked"):
        gateway.validate_checkpoint(approver_token, creator["session"])

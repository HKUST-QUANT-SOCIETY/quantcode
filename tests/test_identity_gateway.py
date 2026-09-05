"""Real OpenSSH agent signatures against an isolated gateway/roster database."""
import hashlib
import os
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from quantcode.gateway import IdentityGateway
from quantcode.identity import fingerprint_of_public_key

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="isolated Unix-domain ssh-agent fixture is not available on Windows",
)


@pytest.fixture
def gateway_login(tmp_path):
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

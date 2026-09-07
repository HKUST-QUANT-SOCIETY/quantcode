"""Host-only SSH agent login; reads a public key, never its private counterpart."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse

import httpx


def _public_key(gateway: str, public_key: Path) -> str:
    parsed = urlparse(gateway)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise ValueError("identity gateway requires HTTPS or loopback HTTP")
    key = public_key.read_text(encoding="utf-8").strip()
    if "PRIVATE KEY" in key or len(key.split()) < 2:
        raise ValueError("public SSH key required")
    return key


def describe_identity(*, gateway: str, public_key: Path, session_file: Path) -> dict:
    key = _public_key(gateway, public_key)
    with httpx.Client(base_url=gateway, timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.post("/auth/identity", json={"public_key": key})
        response.raise_for_status()
        identity = response.json()
    session = None
    if session_file.exists():
        try:
            if _session_record(session_file)["gateway"].rstrip("/") == gateway.rstrip("/"):
                session = _session_summary(read_session_file(session_file))
        except PermissionError:
            pass  # An expired/revoked session must render the login form.
    return {"group": identity["group"], "groups": identity["groups"], "session": session}


def logout(session_file: Path) -> None:
    if not session_file.exists():
        return
    record = _session_record(session_file)
    with httpx.Client(base_url=record["gateway"], timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.post("/auth/logout", json={}, headers={"Authorization": f"Bearer {record['token']}"})
        response.raise_for_status()
        if response.json().get("ok") is not True:
            raise PermissionError("gateway did not confirm logout")
    session_file.unlink(missing_ok=True)


def login(*, gateway: str, public_key: Path, session_file: Path, group: str | None = None) -> dict:
    key = _public_key(gateway, public_key)
    with httpx.Client(base_url=gateway, timeout=15, follow_redirects=False, trust_env=False) as client:
        challenge_payload = {"public_key": key}
        if group:
            challenge_payload["group"] = group
        response = client.post("/auth/challenge", json=challenge_payload)
        response.raise_for_status()
        challenge = response.json()
        # Replacing the credential file must not leave the previous token live.
        logout(session_file)
        with tempfile.TemporaryDirectory(prefix="quantcode-sign-") as folder:
            root = Path(folder)
            # -U forces the key in the SSH agent; only the public key is supplied.
            pub = root / "identity.pub"
            pub.write_text(key, encoding="utf-8")
            nonce = root / "challenge"
            nonce.write_text(challenge["nonce"], encoding="utf-8")
            subprocess.run(["ssh-keygen", "-Y", "sign", "-U", "-f", str(pub), "-n", "quantcode", str(nonce)],
                           check=True, capture_output=True, timeout=30)
            signature = (root / "challenge.sig").read_text(encoding="utf-8")
        verify_payload = {"challenge_id": challenge["challenge_id"], "public_key": key, "signature": signature}
        if group:
            verify_payload["group"] = group
        response = client.post("/auth/verify", json=verify_payload)
        response.raise_for_status()
        result = response.json()
    session_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".identity-", dir=session_file.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump({"gateway": gateway, "token": result["token"]}, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, session_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return result["session"]


def _session_summary(session: dict) -> dict:
    return {"session_id": session["session_id"], "actor_id": session["actor_id"],
            "group": session["group"], "groups": session.get("authorized_groups") or [session["group"]],
            "expires_at": session["expires_at"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:4097")
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--session-file", type=Path, default=Path(".quantcode/identity-session.json"))
    parser.add_argument("--group", default=None, help="选择 roster 已授权的业务组；不传使用主组")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true", help="Read approved groups and the live host session without signing")
    mode.add_argument("--logout", action="store_true", help="Revoke the gateway credential and remove the host session file")
    args = parser.parse_args()
    if args.logout:
        logout(args.session_file)
        print(json.dumps({"status": "disconnected"}))
        return
    if args.public_key is None:
        parser.error("--public-key is required for login or inspection")
    if args.inspect:
        print(json.dumps(describe_identity(gateway=args.gateway, public_key=args.public_key, session_file=args.session_file)))
        return
    session = login(gateway=args.gateway, public_key=args.public_key, session_file=args.session_file, group=args.group)
    print(json.dumps(_session_summary(session)))


def _session_record(path: Path) -> dict:
    stat = path.stat()
    if stat.st_mode & 0o077 or stat.st_uid != os.getuid():
        raise PermissionError("identity session file must be readable only by its owner")
    record = json.loads(path.read_text(encoding="utf-8"))
    parsed = urlparse(record["gateway"])
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise PermissionError("invalid identity gateway transport")
    return record


def read_session_file(path: Path) -> dict:
    """Host-side session lookup; never trust cached context without the gateway."""
    from schemas.session_context import SessionContext

    record = _session_record(path)
    with httpx.Client(base_url=record["gateway"], timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.get("/session", headers={"Authorization": f"Bearer {record['token']}"})
        if response.status_code != 200:
            raise PermissionError("gateway session unavailable, expired or revoked")
        return SessionContext.model_validate(response.json()).model_dump(mode="json")


def validate_checkpoint_identity(path: Path, saved: dict) -> None:
    record = _session_record(path)
    fields = ("session_id", "actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject", "resource_scopes")
    with httpx.Client(base_url=record["gateway"], timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.post("/session/validate-checkpoint",
                               headers={"Authorization": f"Bearer {record['token']}"},
                               json={field: saved.get(field) for field in fields})
        if response.status_code != 200 or response.json().get("valid") is not True:
            raise PermissionError("task creator authorization is no longer valid; creator must start a new task")


if __name__ == "__main__":
    main()

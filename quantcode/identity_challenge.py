"""One-time SSH signature challenge for desktop identity login."""
from __future__ import annotations

import secrets
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quantcode.identity import fingerprint_of_public_key, resolve_identity
from schemas.session_context import SessionContext


class IdentityChallengeError(PermissionError):
    pass


class ChallengeStore:
    """In-memory, one-time challenges. A server deployment can swap the store."""

    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[str, str, float]] = {}

    def issue(self, fingerprint: str) -> dict[str, str | int]:
        now = time.monotonic()
        self._items = {key: value for key, value in self._items.items() if value[2] > now}
        if len(self._items) >= 1000:
            raise IdentityChallengeError("too many outstanding challenges")
        challenge_id = uuid.uuid4().hex
        nonce = secrets.token_urlsafe(32)
        self._items[challenge_id] = (fingerprint, nonce, time.monotonic() + self.ttl_seconds)
        return {"challenge_id": challenge_id, "nonce": nonce, "ttl_seconds": self.ttl_seconds}

    def consume(self, challenge_id: str, fingerprint: str) -> str:
        item = self._items.pop(challenge_id, None)
        if item is None:
            raise IdentityChallengeError("challenge not found or already used")
        expected, nonce, expires = item
        if time.monotonic() > expires:
            raise IdentityChallengeError("challenge expired")
        if not secrets.compare_digest(expected, fingerprint):
            raise IdentityChallengeError("challenge fingerprint mismatch")
        return nonce


def verify_ssh_signature(public_key: str, signature: str, message: str) -> None:
    """Verify an OpenSSH armored signature without handling private keys."""
    with tempfile.TemporaryDirectory(prefix="quantcode-ssh-verify-") as temp:
        root = Path(temp)
        allowed = root / "allowed_signers"
        sig = root / "signature"
        allowed.write_text(f"quantcode {public_key.strip()}\n", encoding="utf-8")
        sig.write_text(signature, encoding="utf-8")
        try:
            subprocess.run(
                [
                    "ssh-keygen", "-Y", "verify", "-f", str(allowed),
                    "-I", "quantcode", "-n", "quantcode", "-s", str(sig),
                ],
                input=message,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise IdentityChallengeError("SSH signature verification failed") from exc


def authenticate(
    store: ChallengeStore,
    *,
    challenge_id: str,
    public_key: str,
    signature: str,
    roster_path: str | Path | None = None,
    session_ttl_minutes: int = 60,
) -> SessionContext:
    """Verify proof of key possession and return the server-owned Session Context."""
    fingerprint = fingerprint_of_public_key(public_key)
    nonce = store.consume(challenge_id, fingerprint)
    verify_ssh_signature(public_key, signature, nonce)
    entry = resolve_identity(fingerprint, roster_path)
    required = ("actor_id", "group", "role", "workspace_id", "workspace_path")
    if entry is None or any(not entry.get(key) for key in required):
        raise IdentityChallengeError("roster entry is missing required Session Context fields")
    now = datetime.now(timezone.utc)
    return SessionContext(
        session_id=uuid.uuid4().hex,
        actor_id=entry["actor_id"],
        group=entry["group"],
        role=entry["role"],
        workspace_id=entry["workspace_id"],
        workspace_path=entry["workspace_path"],
        github_subject=entry.get("github_subject"),
        resource_scopes=entry.get("resource_scopes", []),
        issued_at=now,
        expires_at=now + timedelta(minutes=session_ttl_minutes),
    )


__all__ = [
    "IdentityChallengeError",
    "ChallengeStore",
    "verify_ssh_signature",
    "authenticate",
]

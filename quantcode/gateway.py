"""Local identity gateway. Remote exposure requires an authenticated TLS proxy.

Run: python -m quantcode.gateway --roster /absolute/approved-roster.yaml
Bearer credentials are random, stored only as hashes, and never logged. Every
session read revalidates the current roster so revoked keys fail immediately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from quantcode.identity import fingerprint_of_public_key, resolve_identity
from quantcode.identity_challenge import ChallengeStore, authenticate
from schemas.session_context import SessionContext


class IdentityGateway:
    def __init__(self, *, roster: Path, database: Path):
        self.roster = roster.resolve()
        self.database = database.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.challenges = ChallengeStore()
        self.lock = threading.Lock()
        with sqlite3.connect(self.database) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS identity_sessions (token_hash TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, context TEXT NOT NULL)")
        self.database.chmod(0o600)

    def issue(self, public_key: str) -> dict:
        fingerprint = fingerprint_of_public_key(public_key)
        if not resolve_identity(fingerprint, self.roster):
            raise PermissionError("identity is not in the approved roster")
        with self.lock:
            return self.challenges.issue(fingerprint)

    def verify(self, payload: dict) -> dict:
        with self.lock:
            context = authenticate(self.challenges, challenge_id=payload["challenge_id"],
                                   public_key=payload["public_key"], signature=payload["signature"],
                                   roster_path=self.roster)
        token = secrets.token_urlsafe(48)
        fingerprint = fingerprint_of_public_key(payload["public_key"])
        with sqlite3.connect(self.database) as conn:
            conn.execute("INSERT INTO identity_sessions VALUES(?,?,?)", (
                hashlib.sha256(token.encode()).hexdigest(), fingerprint, context.model_dump_json()))
        return {"token": token, "session": context.model_dump(mode="json")}

    def session(self, token: str) -> SessionContext:
        if not token or len(token) > 512:
            raise PermissionError("authenticated session required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        return self.session_digest(digest)

    def session_digest(self, digest: str) -> SessionContext:
        """Internal lookup for scheduled work; never exposed as authentication."""
        with sqlite3.connect(self.database) as conn:
            row = conn.execute("SELECT fingerprint,context FROM identity_sessions WHERE token_hash=?", (digest,)).fetchone()
        if row is None:
            raise PermissionError("session expired or revoked")
        context = SessionContext.model_validate_json(row[1])
        entry = resolve_identity(row[0], self.roster)
        if context.expires_at <= datetime.now(timezone.utc) or entry is None:
            self.revoke_digest(digest)
            raise PermissionError("session expired or revoked")
        # A changed role/group/workspace requires a new login, never an in-place
        # privilege change to an existing immutable session.
        for field in ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject"):
            if entry.get(field) != getattr(context, field):
                self.revoke_digest(digest)
                raise PermissionError("roster changed; sign in again")
        if set(entry.get("resource_scopes") or []) != set(context.resource_scopes):
            self.revoke_digest(digest)
            raise PermissionError("permissions changed; sign in again")
        return context

    def logout(self, token: str) -> None:
        self.revoke_digest(hashlib.sha256(token.encode()).hexdigest())

    def revoke_digest(self, digest: str) -> None:
        with sqlite3.connect(self.database) as conn:
            conn.execute("DELETE FROM identity_sessions WHERE token_hash=?", (digest,))

    def validate_checkpoint(self, token: str, saved: dict) -> dict:
        """Validate the creator's still-live session without exposing its identity record."""
        reviewer = self.session(token)
        if reviewer.role not in {"approver", "admin"} or reviewer.group != saved.get("group"):
            raise PermissionError("same-group approver required")
        with sqlite3.connect(self.database) as conn:
            row = conn.execute(
                "SELECT fingerprint,context FROM identity_sessions WHERE json_extract(context, '$.session_id')=?",
                (saved.get("session_id"),),
            ).fetchone()
        if row is None:
            raise PermissionError("task creator session expired or revoked")
        creator = SessionContext.model_validate_json(row[1])
        entry = resolve_identity(row[0], self.roster)
        if entry is None or creator.expires_at <= datetime.now(timezone.utc):
            raise PermissionError("task creator session expired or revoked")
        fields = ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject")
        if any(saved.get(field) != getattr(creator, field) or entry.get(field) != getattr(creator, field)
               for field in fields):
            raise PermissionError("task creator authorization changed")
        if (set(saved.get("resource_scopes") or []) != set(creator.resource_scopes)
                or set(entry.get("resource_scopes") or []) != set(creator.resource_scopes)):
            raise PermissionError("task creator permissions changed")
        return {"valid": True}


def handler(gateway: IdentityGateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "QuantCodeGateway"

        def log_message(self, format, *args):
            # Request bodies, bearer tokens, and signatures never enter logs.
            return

        def reply(self, status: int, value: dict):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def token(self):
            auth = self.headers.get("Authorization", "")
            return auth[7:] if auth.startswith("Bearer ") else ""

        def do_GET(self):
            try:
                if self.path == "/github-sync":
                    from runner.github_worker import read_status
                    context = gateway.session(self.token())
                    return self.reply(200, read_status(gateway.database, context.model_dump(mode="json")))
                if self.path == "/deployments":
                    from runner.admin_operations import list_deployments
                    context = gateway.session(self.token())
                    return self.reply(200, list_deployments(session_role=context.role, actor_id=context.actor_id,
                        database=gateway.database.parent / "deployments.db"))
                if self.path == "/session":
                    return self.reply(200, gateway.session(self.token()).model_dump(mode="json"))
                return self.reply(404, {"error": "not found"})
            except PermissionError as exc:
                self.reply(401, {"error": str(exc)})
            except Exception:
                self.reply(503, {"error": "identity service unavailable"})

        def do_POST(self):
            try:
                # Browser pages cannot use this loopback service as a signing
                # oracle. Desktop host calls it without an Origin header.
                if self.headers.get("Origin"):
                    return self.reply(403, {"error": "host identity bridge required"})
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 16384:
                    return self.reply(400, {"error": "invalid request size"})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("object payload required")
                if self.path == "/session/validate-checkpoint":
                    return self.reply(200, gateway.validate_checkpoint(self.token(), payload))
                if self.path == "/receipts/reconcile":
                    from runner.receipt_reconciliation import ReconcileReceipt, reconcile
                    from runner.langgraph_base import CHECKPOINTS_DB
                    context = gateway.session(self.token())
                    return self.reply(200, reconcile(ReconcileReceipt.model_validate(payload), context.model_dump(mode="json"), CHECKPOINTS_DB))
                if self.path in {"/deployments", "/deployments/cancel"}:
                    from runner.admin_operations import submit_deploy, cancel_deployment
                    from schemas.admin_deploy import AdminDeployRequest
                    context = gateway.session(self.token())
                    options = {"session_role": context.role, "actor_id": context.actor_id,
                               "database": gateway.database.parent / "deployments.db"}
                    if self.path == "/deployments/cancel":
                        return self.reply(200, cancel_deployment(payload["deployment_id"], **options))
                    result = submit_deploy(AdminDeployRequest.model_validate(payload), **options)
                    return self.reply(200, result.model_dump(mode="json"))
                if self.path == "/auth/challenge":
                    return self.reply(200, gateway.issue(payload["public_key"]))
                if self.path == "/auth/verify":
                    return self.reply(200, gateway.verify(payload))
                if self.path == "/auth/logout":
                    gateway.logout(self.token())
                    return self.reply(200, {"ok": True})
                return self.reply(404, {"error": "not found"})
            except PermissionError as exc:
                self.reply(401, {"error": str(exc)})
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error": "invalid identity request"})
            except Exception:
                self.reply(503, {"error": "identity service unavailable"})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path(".quantcode/identity-gateway.db"))
    parser.add_argument("--port", type=int, default=4097)
    parser.add_argument("--github-sync-interval", type=int, default=60,
                        help="Seconds between GitHub sync cycles; 0 disables the worker, otherwise at least 60")
    args = parser.parse_args()
    if args.github_sync_interval != 0 and args.github_sync_interval < 60:
        parser.error("GitHub sync interval must be 0 or at least 60 seconds")
    gateway = IdentityGateway(roster=args.roster, database=args.database)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(gateway))
    stop = threading.Event()
    if args.github_sync_interval:
        from runner.github_worker import serve
        threading.Thread(target=serve, args=(gateway, stop, args.github_sync_interval),
                         name="quantcode-github-sync", daemon=True).start()
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()

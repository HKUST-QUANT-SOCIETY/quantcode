"""Desktop stdio entrypoint; optionally relay MCP over an authenticated SSH channel."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading

from quantcode.identity_login import _session_record, read_session_file


def ssh_command(host: str, actor: str, public_key: Path) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
        raise ValueError("remote MCP requires a configured SSH host name")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,28}", actor):
        raise ValueError("invalid research actor")
    if not public_key.is_absolute() or not public_key.is_file():
        raise ValueError("remote MCP requires an absolute public key file")
    if "PRIVATE KEY" in public_key.read_text(encoding="utf-8"):
        raise ValueError("private keys must remain in the local SSH agent")
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
            "-i", str(public_key), "-l", f"qc-{actor}", host, "/opt/quantcode/ops/remote-mcp"]


def relay(command: list[str], envelope: dict) -> int:
    child = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert child.stdin is not None
    previous = {}

    def stop(signum, _frame):
        child.terminate()

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, stop)
    try:
        child.stdin.write(json.dumps(envelope).encode() + b"\n")
        child.stdin.flush()

        def forward():
            try:
                while chunk := sys.stdin.buffer.read1(65536):
                    child.stdin.write(chunk)
                    child.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                try:
                    child.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

        threading.Thread(target=forward, name="quantcode-ssh-input", daemon=True).start()
        return child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    host = os.environ.get("QUANTCODE_REMOTE_SSH_HOST", "").strip()
    if not host:
        from quantcode.mcp_server import main as serve
        serve()
        return 0
    try:
        path = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
        context = read_session_file(path)
        record = _session_record(path)
        # Detect replacement between lookup and credential read without printing
        # either record. The remote endpoint revalidates the same session again.
        if read_session_file(path)["session_id"] != context["session_id"]:
            raise PermissionError("identity changed; reconnect")
        command = ssh_command(host, context["actor_id"], Path(os.environ["QUANTCODE_PUBLIC_KEY_FILE"]))
        return relay(command, {"version": 1, "token": record["token"], "session_id": context["session_id"]})
    except Exception as exc:
        print(f"Remote MCP unavailable ({type(exc).__name__}); check host identity and SSH configuration", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

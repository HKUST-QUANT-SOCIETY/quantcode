"""Verify an enrolled SSH MCP with a disposable, locally signed gateway session."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantcode.identity_login import logout, read_session_file  # noqa: E402
from quantcode.mcp_host import ssh_command  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--revoke", action="store_true", help="Revoke this test session and verify the live MCP rejects further calls")
    args = parser.parse_args()
    session = read_session_file(args.session_file)
    ssh = ssh_command(args.host, session["actor_id"], args.public_key)

    def remote(command: str) -> str:
        result = subprocess.run([*ssh[:-1], command], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError("remote status inspection failed")
        return result.stdout

    def units() -> set[str]:
        return {item["unit"] for item in json.loads(remote("systemctl --user list-units --output=json 'quantcode-mcp-*'"))}

    before = units()
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "QUANTCODE_REMOTE_SSH_HOST": args.host,
           "QUANTCODE_PUBLIC_KEY_FILE": str(args.public_key), "QUANTCODE_IDENTITY_SESSION_FILE": str(args.session_file.resolve())}
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([sys.executable, "-m", "quantcode.mcp_host"], cwd=root, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
        assert process.stdin is not None and process.stdout is not None
        service = ""
        try:
            def call(identifier: int, method: str, params: dict) -> dict:
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}).encode() + b"\n")
                process.stdin.flush()
                if not select.select([process.stdout], [], [], 30)[0]:
                    raise TimeoutError("remote MCP response timed out")
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError("remote MCP stopped before replying")
                response = json.loads(line)
                if response.get("id") != identifier:
                    raise RuntimeError("remote MCP response id mismatch")
                return response

            identity = call(1, "tools/call", {"name": "session_context", "arguments": {}})
            context = json.loads(identity["result"]["content"][0]["text"])
            for field in ("session_id", "actor_id", "group", "workspace_path"):
                assert context[field] == session[field]
            available = call(2, "tools/list", {})["result"]["tools"]
            assert any(tool["name"] == "run_agent" for tool in available)
            active = units() - before
            assert len(active) == 1
            service = active.pop()
            assert service.startswith("quantcode-mcp-") and service.endswith(".service")
            properties = dict(line.split("=", 1) for line in remote(
                f"systemctl --user show {service} -p ActiveState -p MainPID -p NoNewPrivileges -p ProtectSystem -p PrivateUsers -p MemoryMax -p TasksMax"
            ).splitlines() if "=" in line)
            assert properties["ActiveState"] == "active" and int(properties["MainPID"]) > 0
            assert properties["NoNewPrivileges"] == "yes" and properties["ProtectSystem"] == "strict"
            assert properties["PrivateUsers"] == "yes" and properties["MemoryMax"] == "2147483648"
            assert properties["TasksMax"] == "128"
            if args.revoke:
                logout(args.session_file)
                rejected = call(3, "tools/call", {"name": "session_context", "arguments": {}})
                assert "AUTHENTICATION_REQUIRED" in json.dumps(rejected)
            process.stdin.close()
            assert process.wait(timeout=20) == 0
            deadline = time.monotonic() + 10
            while service in units():
                if time.monotonic() >= deadline:
                    raise RuntimeError("remote MCP service survived closed transport")
                time.sleep(0.1)
            print(json.dumps({"status": "PASS", "scope": "SSH MCP identity, tool discovery and lifecycle",
                "actor_id": session["actor_id"], "group": session["group"], "tool_count": len(available),
                "systemd_limits_verified": True, "revocation_verified": args.revoke, "service_cleaned_up": True}))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if service:
                remote(f"systemctl --user stop {service} 2>/dev/null || true")


if __name__ == "__main__":
    main()

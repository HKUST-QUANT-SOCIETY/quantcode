"""Isolated desktop UI review using the real QuantCode gateway HTTP contracts.

`plan` is read-only. `serve` explicitly creates a NEW private fixture directory,
an isolated SSH agent and a loopback-only gateway on a new port. It never starts
the desktop/backend, modifies a real roster, or attaches to an existing service.
Every seeded task/artifact is marked UI FIXTURE and is not execution evidence.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
ACTORS = (("ui-fixture-admin", "infra", "admin"), ("ui-fixture-analyst", "factor", "analyst"))


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _json(path: Path, value) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("choose a new unprivileged port between 1024 and 65535")
    return port


def _available(port: int) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def _artifacts(session_id: str) -> tuple[list[dict], dict[str, bytes]]:
    artifacts, content = [], {}
    for index in range(35):
        key = _hash(f"{session_id}:ui-fixture:{index}".encode())
        raw = (f"# UI FIXTURE report {index + 1}\n\nSynthetic layout content. No business calculation or model ran.\n" +
               ("fixture report line for multi-chunk preview\n" * 4000 if index == 0 else "fixture row\n")).encode()
        ref = {"id": "artifact_" + key, "kind": "report", "name": f"UI-FIXTURE-report-{index + 1:02}.md",
               "mime": "text/markdown", "source": "metadata", "source_event_id": "evt_ui_fixture_" + key,
               "source_event_seq": index + 1, "message_id": "msg_ui_fixture_" + key,
               "call_id": "call_ui_fixture_" + key, "result_digest": _hash(raw)}
        if index == 34:
            ref.update(capture_status="unavailable", unavailable_reason="original_not_captured", ref="unavailable:" + key)
        else:
            ref.update(capture_status="available", sha256=_hash(raw), bytes=len(raw), ref="snapshot:" + _hash(raw))
            if index != 33:  # A truthful, intentionally undelivered UI state.
                content[ref["id"]] = raw
        artifacts.append(ref)
    return sorted(artifacts, key=lambda item: item["id"]), content


def serve(args) -> None:
    if os.name != "posix":
        raise RuntimeError("this isolated review helper requires POSIX private-file and SSH-agent support")
    if args.backend_port == args.app_port or args.gateway_port in {args.backend_port, args.app_port}:
        raise ValueError("gateway, backend and frontend need separate new ports")
    _available(args.backend_port)
    _available(args.app_port)
    destination = args.directory.expanduser().resolve()
    if not args.directory.is_absolute() or destination.exists() or destination.is_relative_to(ROOT):
        raise ValueError("fixture directory must be a new absolute directory outside the repository")
    python = Path(sys.executable).absolute()
    bun = shutil.which("bun")
    if not bun:
        raise RuntimeError("Bun is required for the separately launched desktop UI")
    os.umask(0o077)
    destination.mkdir(mode=0o700)
    control = destination / "control"
    control.mkdir(mode=0o700)
    # Import the existing implementation only when the operator explicitly
    # selects serve. No service or dependency import occurs in plan mode.
    sys.path.insert(0, str(ROOT))
    import httpx
    from quantcode.gateway import IdentityGateway, handler
    from quantcode.identity import fingerprint_of_public_key
    from schemas.evidence_chain import canonical_json
    from schemas.native_tasks import CHUNK_BYTES

    records = []
    keys = {}
    for actor, group, role in ACTORS:
        workspace = destination / actor
        workspace.mkdir(mode=0o700)
        desktop = control / f"{actor}-desktop"
        desktop.mkdir(mode=0o700)
        for name in ("home", "data", "config", "cache", "state", "tmp"):
            (desktop / name).mkdir(mode=0o700)
        _write(workspace / "UI-FIXTURE.md", "# UI REVIEW FIXTURE\n\nThis workspace contains no real research data.\n")
        key = control / actor
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "QUANTCODE-UI-REVIEW-FIXTURE", "-f", str(key)],
                       check=True, capture_output=True, timeout=15)
        keys[actor] = key
        records.append({"fingerprint": fingerprint_of_public_key(key.with_suffix(".pub").read_text()),
                        "actor_id": actor, "group": group, "role": role,
                        "workspace_id": "ui-fixture-" + actor, "workspace_path": str(workspace),
                        "resource_scopes": [], "note": "UI REVIEW FIXTURE ONLY — NOT A REAL MEMBER"})
    roster = control / "fixture-roster.json"
    _json(roster, {"bindings": records})  # JSON is valid YAML for the real roster reader.
    _json(destination / "UI-REVIEW-FIXTURE.json", {"kind": "quantcode-desktop-ui-review", "created_at": time.time(),
          "execution_evidence": False, "real_members": False, "repository": str(ROOT), "actors": [actor for actor, _, _ in ACTORS]})
    gateway = IdentityGateway(roster=roster, database=control / "gateway.db")
    server = ThreadingHTTPServer(("127.0.0.1", args.gateway_port), handler(gateway))
    url = f"http://127.0.0.1:{server.server_port}"
    stopping = threading.Event()
    previous = {number: signal.signal(number, lambda _number, _frame: stopping.set()) for number in (signal.SIGINT, signal.SIGTERM)}
    worker = threading.Thread(target=server.serve_forever, name="quantcode-ui-fixture-gateway", daemon=True)
    worker.start()
    agent = None
    tokens = []
    # macOS SSH socket paths have a short fixed bound. Never use or add a key
    # to the developer's already running SSH agent.
    agent_directory = Path(tempfile.mkdtemp(prefix="qc-ui-agent-", dir="/tmp"))
    try:
        agent_socket = agent_directory / "socket"
        agent = subprocess.Popen(["ssh-agent", "-D", "-a", str(agent_socket)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while not agent_socket.exists():
            if agent.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("isolated fixture SSH agent did not become ready")
            time.sleep(0.02)
        environment = {"PATH": os.defpath, "SSH_AUTH_SOCK": str(agent_socket)}
        for key in keys.values():
            subprocess.run(["ssh-add", str(key)], env=environment, check=True, capture_output=True, timeout=10)
        with httpx.Client(base_url=url, timeout=20, trust_env=False, follow_redirects=False) as client:
            def post(route: str, payload: dict, token: str | None = None):
                response = client.post(route, json=payload, headers={"Authorization": "Bearer " + token} if token else {})
                if response.status_code != 200:
                    raise RuntimeError(f"fixture gateway {route} returned HTTP {response.status_code}")
                return response.json()

            seeded = []
            for actor_index, (actor, group, _role) in enumerate(ACTORS):
                key = keys[actor]
                public = key.with_suffix(".pub").read_text().strip()
                challenge = post("/auth/challenge", {"public_key": public})
                signature = subprocess.run(["ssh-keygen", "-Y", "sign", "-U", "-f", str(key.with_suffix(".pub")), "-n", "quantcode"],
                                           input=challenge["nonce"], text=True, env=environment, check=True,
                                           capture_output=True, timeout=10).stdout
                authenticated = post("/auth/verify", {"public_key": public, "challenge_id": challenge["challenge_id"], "signature": signature})
                token = authenticated["token"]
                tokens.append(token)
                login = authenticated["session"]["session_id"]
                _json(control / f"{actor}-session.json", {"gateway": url, "token": token})
                source_id = "ui-fixture-" + uuid4().hex
                root_id = "ses_ui_fixture_" + uuid4().hex
                statuses = ["completed", "paused", "running", "waiting_for_human", "stopped_budget", "error", "unknown", "cancelled"]
                for index in range(actor_index, args.task_count, 2):
                    ordinal = index // 2
                    session_id = root_id if ordinal == 0 else "ses_ui_fixture_" + uuid4().hex
                    refs, contents = _artifacts(session_id) if ordinal == 0 else ([], {})
                    now = int(time.time() * 1000)
                    task = {"source_id": source_id, "session_id": session_id,
                            "root_session_id": root_id if ordinal == 1 else session_id,
                            **({"parent_session_id": root_id} if ordinal == 1 else {}),
                            "source_revision": 1000, "title": f"[UI FIXTURE · 无执行] {group} 桌面排版样例 {ordinal + 1:03}",
                            "status": statuses[ordinal % len(statuses)], "created_at": now - 3600000, "updated_at": now,
                            "tokens_input": 1200 + ordinal, "tokens_output": 350 + ordinal, "cost": None,
                            "reserved_tokens": 2000 if ordinal % 8 == 6 else 0,
                            "unconfirmed_requests": 1 if ordinal % 8 == 6 else 0,
                            "artifact_count": len(refs), "artifacts": refs[:32],
                            "artifact_manifest_hash": _hash(canonical_json(refs).encode())}
                    post("/native-tasks/publish", {"expected_session_id": login, "task": task}, token)
                    for ref in refs:
                        binding = {"expected_session_id": login, "source_id": source_id, "session_id": session_id,
                                   "source_revision": 1000, "artifact": ref}
                        post("/native-tasks/artifacts/publish", binding, token)
                    for ref in refs:
                        if ref["id"] not in contents:
                            continue
                        content = contents[ref["id"]]
                        for offset in range(0, len(content), CHUNK_BYTES):
                            chunk = content[offset:offset + CHUNK_BYTES]
                            post("/native-tasks/artifacts/publish", {"expected_session_id": login, "source_id": source_id,
                                 "session_id": session_id, "source_revision": 1000, "artifact": ref, "offset": offset,
                                 "content": base64.b64encode(chunk).decode(), "encoding": "base64", "chunk_sha256": _hash(chunk)}, token)
                    seeded.append({"task": task, "artifacts": refs, "fixture_only": True})
                settings = {"QUANTCODE_HOST_PYTHON": str(python), "QUANTCODE_BACKEND_ROOT": str(ROOT),
                            "QUANTCODE_PUBLIC_KEY_FILE": str(key.with_suffix(".pub")), "QUANTCODE_IDENTITY_SESSION_FILE": str(control / f"{actor}-session.json"),
                            "QUANTCODE_GATEWAY_URL": url, "QUANTCODE_ROSTER_FILE": str(roster), "QUANTCODE_UNIFIED_RUNTIME": "1",
                            "QUANTCODE_BACKEND_PORT": str(args.backend_port), "QUANTCODE_APP_PORT": str(args.app_port)}
                _write(control / f"{actor}.env", "# UI REVIEW FIXTURE ONLY; no real member or model credentials.\n" +
                       "".join(f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in settings.items()))
            _json(destination / "fixture-native-projections.json", {"fixture_only": True, "native_execution_evidence": False, "records": seeded})
        _json(control / "processes.json", {"fixture_only": True, "gateway_pid": os.getpid(), "gateway_url": url, "ssh_agent_pid": agent.pid})
        desktop = control / "ui-fixture-admin-desktop"
        clean = {"PATH": str(Path(bun).parent) + os.pathsep + os.defpath, "HOME": str(desktop / "home"),
                 "TMPDIR": str(desktop / "tmp"), "XDG_CONFIG_HOME": str(desktop / "config"),
                 "XDG_DATA_HOME": str(desktop / "data"), "XDG_CACHE_HOME": str(desktop / "cache"),
                 "XDG_STATE_HOME": str(desktop / "state"), "SSH_AUTH_SOCK": str(agent_socket),
                 "QUANTCODE_HOST_ENV_FILE": str(control / "ui-fixture-admin.env"),
                 "OPENCODE_CONFIG_CONTENT": '{"mcp":{},"provider":{},"formatter":false,"lsp":false}'}
        command = shlex.join(["env", "-i", *[f"{key}={value}" for key, value in clean.items()],
                              bun, "run", "--cwd", str(ROOT / "frontend"), "dev:quantcode"])
        _write(destination / "launch-ui-command.txt", command + "\n")
        print(f"UI FIXTURE gateway: {url}\nTasks: {len(seeded)} (synthetic; no Agent/model ran)\n"
              f"Private fixture directory: {destination}\n"
              "Gateway/SSH agent are new processes owned by this command. No existing service was restarted.\n"
              "Run this separate command for the UI; it starts a NEW backend and frontend:\n" + command, flush=True)
        while not stopping.wait(1):
            if agent.poll() is not None:
                raise RuntimeError("fixture SSH agent exited")
    finally:
        for token in tokens:
            gateway.logout(token)
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        if agent and agent.poll() is None:
            agent.terminate()
            try:
                agent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent.kill()
                agent.wait(timeout=5)
        shutil.rmtree(agent_directory)
        for number, previous_handler in previous.items():
            signal.signal(number, previous_handler)
        # Fixture evidence remains for review; it is never merged into real
        # task history. Only this process's fixture bearer sessions are revoked.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("plan", help="print the isolation and fixture contract without starting anything")
    start = sub.add_parser("serve", help="explicitly start a NEW local fixture gateway and isolated SSH agent")
    start.add_argument("--directory", type=Path, required=True)
    start.add_argument("--backend-port", type=_port, required=True)
    start.add_argument("--app-port", type=_port, required=True)
    start.add_argument("--gateway-port", type=_port, default=0, help="new gateway port; omitted selects an unused ephemeral port")
    start.add_argument("--task-count", type=int, default=104)
    args = parser.parse_args()
    if args.action == "plan":
        print(json.dumps({"fixture_only": True, "starts_service": False, "actors": ACTORS,
              "gateway": "actual quantcode.gateway.IdentityGateway + handler; loopback new port",
              "seed": "real /auth/challenge, /auth/verify, /native-tasks/publish and /native-tasks/artifacts/publish",
              "isolated": ["roster", "keys", "SSH agent", "gateway database", "XDG data/config/cache/state"],
              "does_not_cover": ["real members", "GitHub credentials", "model execution", "native task execution", "Server C deployment"]}, ensure_ascii=False, indent=2))
        return
    if not 2 <= args.task_count <= 200:
        parser.error("UI fixture task count must be between 2 and 200")
    serve(args)


if __name__ == "__main__":
    main()

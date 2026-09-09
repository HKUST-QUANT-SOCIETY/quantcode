"""Eight isolated QuantCode members exercising the native gateway contract.

The gateway, SSH agent, roster, workspaces, sessions and native task index are
real implementations. The model/domain result is deterministic fixture data;
this keeps the test repeatable while still exercising ownership, artifacts,
revocation and cross-group boundaries over HTTP.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading

import httpx
import pytest

from quantcode.gateway import IdentityGateway, handler
from quantcode.identity_login import login, read_session_file, logout
from quantcode.roster import fingerprint_of_public_key
from runner.memory.service import MemoryService


GROUPS = ("fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact(session_id: str, group: str) -> tuple[dict, bytes]:
    content = f"# {group} deterministic research result\n\nTask {session_id} completed.\n".encode()
    digest = _sha(content)
    artifact_id = "artifact_" + _sha(f"{session_id}:{group}".encode())
    return ({
        "id": artifact_id, "kind": "report", "name": f"{group}-result.md", "mime": "text/markdown",
        "bytes": len(content), "sha256": digest, "ref": "snapshot:" + digest, "source": "metadata",
        "capture_status": "available", "source_event_id": "event-" + digest,
        "source_event_seq": 1, "message_id": "msg-" + digest, "call_id": "call-" + digest,
        "result_digest": digest,
    }, content)


@pytest.fixture(scope="module")
def eight_members(tmp_path_factory):
    root = tmp_path_factory.mktemp("eight-member-native-e2e")
    control = root / "control"
    control.mkdir(mode=0o700)
    roster_entries = []
    keys: dict[str, Path] = {}
    sessions: dict[str, Path] = {}
    workspaces: dict[str, Path] = {}
    contexts: dict[str, dict] = {}
    tokens: dict[str, str] = {}
    tasks: dict[str, dict] = {}
    for group in GROUPS:
        actor = f"e2e-{group}-member"
        workspace = root / actor
        workspace.mkdir(mode=0o700)
        workspaces[group] = workspace
        key = control / actor
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True)
        keys[group] = key
        public = key.with_suffix(".pub").read_text().strip()
        roster_entries.append({
            "fingerprint": fingerprint_of_public_key(public), "actor_id": actor, "role": "analyst",
            "group": group, "groups": [group], "workspace_id": f"workspace-{group}",
            "workspace_path": str(workspace), "github_subject": f"{actor}-github", "resource_scopes": [f"repo:{group}"],
        })
        sessions[group] = control / f"{group}.session.json"
    roster = control / "roster.json"
    roster.write_text(json.dumps({"bindings": roster_entries}), encoding="utf-8")
    roster.chmod(0o600)
    gateway = IdentityGateway(roster=roster, database=control / "gateway.db", memory_root=control / "memory-authority")
    memory_db = control / "memory-authority" / ".quantcode" / "memory.db"
    for group in GROUPS:
        MemoryService(memory_db, root=control / "memory-authority", requester_group=group).write(
            scope="groups", scope_id=group, key="e2e-capability", body=f"{group} canonical fixture capability")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    agent_dir = Path(tempfile.mkdtemp(prefix="qc-eight-agent-", dir="/tmp"))
    socket = agent_dir / "socket"
    agent = subprocess.Popen(["ssh-agent", "-D", "-a", str(socket)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        deadline = time.monotonic() + 5
        while not socket.exists():
            if agent.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("isolated eight-member SSH agent did not start")
            time.sleep(0.02)
        agent_env = {"SSH_AUTH_SOCK": str(socket), "PATH": "/usr/bin:/bin"}
        for key in keys.values():
            subprocess.run(["ssh-add", str(key)], env=agent_env, check=True, capture_output=True)
        previous_agent_socket = os.environ.get("SSH_AUTH_SOCK")
        os.environ["SSH_AUTH_SOCK"] = str(socket)
        base_url = f"http://127.0.0.1:{server.server_port}"
        for group in GROUPS:
            login(gateway=base_url, public_key=keys[group].with_suffix(".pub"), session_file=sessions[group])
            record = json.loads(sessions[group].read_text())
            tokens[group] = record["token"]
            contexts[group] = read_session_file(sessions[group])
        with httpx.Client(base_url=base_url, trust_env=False) as client:
            # Seed real task records so isolation checks never depend on test
            # execution order or merely reject a nonexistent task.
            for group in GROUPS:
                context = contexts[group]
                task = {
                    "source_id": f"e2e-boundary-{group}", "session_id": context["session_id"],
                    "root_session_id": context["session_id"], "source_revision": 1,
                    "title": f"{group} private boundary fixture", "status": "completed",
                    "created_at": 1, "updated_at": 2, "model": "fixture-model", "agent": "fixture",
                    "tokens_input": 0, "tokens_output": 0, "cost": None, "reserved_tokens": 0,
                    "unconfirmed_requests": 0, "artifact_count": 0, "artifacts": [],
                    "artifact_manifest_hash": _sha(b"[]"),
                }
                response = client.post("/native-tasks/publish", headers={"Authorization": f"Bearer {tokens[group]}"},
                                       json={"expected_session_id": context["session_id"], "task": task})
                assert response.status_code == 200, response.text
                tasks[group] = task
            yield {"gateway": gateway, "base_url": base_url, "client": client,
                   "keys": keys, "sessions": sessions, "workspaces": workspaces, "agent_env": agent_env,
                   "contexts": contexts, "tasks": tasks}
    finally:
        if "previous_agent_socket" in locals():
            if previous_agent_socket is None:
                os.environ.pop("SSH_AUTH_SOCK", None)
            else:
                os.environ["SSH_AUTH_SOCK"] = previous_agent_socket
        for session in sessions.values():
            try:
                logout(session)
            except Exception:
                pass
        agent.terminate()
        agent.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        import shutil
        shutil.rmtree(agent_dir, ignore_errors=True)


@pytest.mark.parametrize("group", GROUPS)
def test_each_group_completes_login_task_artifact_and_logout(eight_members, group):
    client: httpx.Client = eight_members["client"]
    session_file = eight_members["sessions"][group]
    login(gateway=eight_members["base_url"], public_key=eight_members["keys"][group].with_suffix(".pub"), session_file=session_file)
    token = json.loads(session_file.read_text())["token"]
    headers = {"Authorization": f"Bearer {token}"}
    context = read_session_file(session_file)
    session_id = context["session_id"]
    assert context["actor_id"] == f"e2e-{group}-member"
    assert context["group"] == group
    assert context["workspace_path"] == str(eight_members["workspaces"][group])
    workspace = eight_members["workspaces"][group]
    input_file = workspace / "task-input.md"
    input_file.write_text(f"{group} member research input\n", encoding="utf-8")
    assert input_file.read_text(encoding="utf-8").startswith(group)
    memory = client.post("/memory/search", headers=headers, json={
        "query": "canonical fixture capability", "expected_session_id": session_id,
    })
    assert memory.status_code == 200, memory.text
    assert any(hit["scope"] == "groups" and hit["scope_id"] == group for hit in memory.json()["hits"])

    source_id = f"e2e-source-{group}"
    artifact, content = _artifact(session_id, group)
    task = {
        "source_id": source_id, "session_id": session_id, "root_session_id": session_id,
        "source_revision": 1, "title": f"{group} deterministic research task", "status": "completed",
        "created_at": 1, "updated_at": 2, "model": "fixture-model", "agent": "quantcode-native",
        "tokens_input": 12, "tokens_output": 8, "cost": None, "reserved_tokens": 0,
        "unconfirmed_requests": 0, "artifact_count": 1, "artifacts": [artifact],
        "artifact_manifest_hash": _sha(json.dumps([artifact], sort_keys=True, separators=(",", ":")).encode()),
    }
    published = client.post("/native-tasks/publish", headers=headers, json={"expected_session_id": session_id, "task": task})
    assert published.status_code == 200, published.text
    pushed = client.post("/native-tasks/artifacts/publish", headers=headers, json={
        "expected_session_id": session_id, "source_id": source_id, "session_id": session_id,
        "source_revision": 1, "artifact": artifact, "offset": 0,
        "content": base64.b64encode(content).decode(), "encoding": "base64", "chunk_sha256": _sha(content),
    })
    assert pushed.status_code == 200, pushed.text
    read = client.post("/native-tasks/read", headers=headers, json={
        "expected_session_id": session_id, "source_id": source_id, "session_id": session_id,
    })
    assert read.status_code == 200, read.text
    assert read.json()["task"]["group"] == group
    assert read.json()["artifacts"][0]["delivery_status"] == "available"
    assert read.json()["artifacts"][0]["sha256"] == _sha(content)
    downloaded = client.post("/native-tasks/artifacts/read", headers=headers, json={
        "expected_session_id": session_id, "source_id": source_id, "session_id": session_id,
        "source_revision": 1, "artifact_id": artifact["id"], "offset": 0,
    })
    assert downloaded.status_code == 200, downloaded.text
    actual = base64.b64decode(downloaded.json()["content"], validate=True)
    assert actual == content
    assert _sha(actual) == downloaded.json()["chunk_sha256"]

    logout(session_file)
    assert client.get("/session", headers=headers).status_code == 401


@pytest.mark.parametrize("reader_group", GROUPS)
def test_members_cannot_read_each_others_native_task(eight_members, reader_group):
    client: httpx.Client = eight_members["client"]
    session_file = eight_members["sessions"][reader_group]
    login(gateway=eight_members["base_url"], public_key=eight_members["keys"][reader_group].with_suffix(".pub"), session_file=session_file)
    context = read_session_file(session_file)
    token = json.loads(session_file.read_text())["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/session", headers=headers).status_code == 200
    for owner_group, task in eight_members["tasks"].items():
        response = client.post("/native-tasks/read", headers=headers, json={
            "expected_session_id": context["session_id"], "source_id": task["source_id"], "session_id": task["session_id"],
        })
        if owner_group == reader_group:
            assert response.status_code == 200, response.text
            assert response.json()["task"]["title"] == task["title"]
        else:
            assert response.status_code == 401, response.text
            assert response.json()["error"] == "current roster identity cannot read this task"
            assert task["title"] not in response.text
    # The rejection must come from task ownership, not a revoked login.
    assert client.get("/session", headers=headers).status_code == 200
    logout(session_file)

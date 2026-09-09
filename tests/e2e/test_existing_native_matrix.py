import base64
from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

import verify_existing_native_matrix as matrix


@pytest.mark.parametrize("owner_after_fails", [False, True])
def test_pair_uses_latest_identical_urls_and_verifies_live_reader_after_each_denial(owner_after_fails):
    owner_task = {"source_id": "source-owner", "session_id": "session-owner", "source_revision": 3}
    reader_task = {"source_id": "source-reader", "session_id": "session-reader", "source_revision": 5}
    content = b'{"qa":true}'
    digest = hashlib.sha256(content).hexdigest()
    artifact = {"id": "artifact-real", "sha256": digest}
    calls = []

    def handle(request):
        group = request.url.host
        calls.append((group, request.url.raw_path.decode()))
        task = owner_task if "source-owner" in request.url.path else reader_task
        expected_group = "owner" if task is owner_task else "reader"
        if group != expected_group:
            return httpx.Response(403, json={"error": "forbidden"})
        if "/artifacts/" in request.url.path:
            if owner_after_fails and sum(host == "owner" and "/artifacts/" in target for host, target in calls) == 2:
                return httpx.Response(400, json={"error": "owner resource no longer readable"})
            if request.url.params.get("source_revision") != "23":
                return httpx.Response(400, json={"error": "stale revision"})
            return httpx.Response(200, json={"source_revision": 23, "offset": 0, "artifact": artifact,
                "content": base64.b64encode(content).decode(), "encoding": "base64", "chunk_sha256": digest, "next_offset": None})
        return httpx.Response(200, json={"task": {**task, "actor_id": "sim-" + group,
            "source_revision": 23, "status": "completed", "title": "private " + group}})

    with httpx.Client(base_url="http://owner", transport=httpx.MockTransport(handle)) as owner_client, \
            httpx.Client(base_url="http://reader", transport=httpx.MockTransport(handle)) as reader_client:
        owner = SimpleNamespace(client=owner_client, secrets=[], member={"group": "owner", "actor_id": "sim-owner"})
        reader = SimpleNamespace(client=reader_client, secrets=[], member={"group": "reader", "actor_id": "sim-reader"})
        checks = []
        if owner_after_fails:
            with pytest.raises(AssertionError, match="Owner artifact read failed"):
                matrix.verify_pair(reader, owner, reader_task, owner_task, artifact, checks)
        else:
            matrix.verify_pair(reader, owner, reader_task, owner_task, artifact, checks)
    assert len(checks) == 2 and checks[0]["status"] == "passed"
    assert checks[1]["status"] == ("failed" if owner_after_fails else "passed")
    assert owner_task["source_revision"] == 3
    artifact_calls = [target for _, target in calls if "/artifacts/" in target]
    assert len(artifact_calls) == 3 and len(set(artifact_calls)) == 1
    assert artifact_calls[0].endswith("?source_revision=23&offset=0")
    for check in checks:
        assert [request["role"] for request in check["requests"]] == [
            "owner_before", "reader_cross", "reader_own_after", "owner_after"]
        final = 400 if owner_after_fails and check["resource"] == "artifact" else 200
        assert [request["http_status"] for request in check["requests"]] == [200, 403, 200, final]


def test_main_logs_out_all_eight_members_and_saves_failure_on_matrix_error(tmp_path, monkeypatch):
    members = []
    lifecycle = []
    for index, group in enumerate(matrix.GROUPS):
        credential = tmp_path / f"{group}.env"
        credential.write_text("OPENCODE_SERVER_PASSWORD=disposable\n")
        members.append({"group": group, "actor_id": "sim-" + group, "username": "qc-sim-" + group,
            "workspace": "/srv/quantcode-qa/" + group, "fingerprint": str(index),
            "native_base_url": f"http://127.0.0.1:{7701 + index}", "native_username": "quantcode",
            "native_password_file": str(credential)})
        lifecycle.append({"group": group, "status": "passed", "task": {"source_id": "source-" + group,
            "session_id": "session-" + group, "source_revision": 1}, "artifact": {"id": "artifact-" + group}})
    manifest = tmp_path / "manifest.json"
    source = tmp_path / "lifecycle.json"
    output = tmp_path / "verified.json"
    manifest.write_text(json.dumps({"purpose": "isolated-eight-group-e2e", "members": members}))
    source.write_text(json.dumps({"members": lifecycle}))
    clients = []
    events = []
    client_class = httpx.Client

    def client(**kwargs):
        def handle(request):
            events.append((request.url.port, request.method, request.url.path))
            if request.url.path.endswith("/identity/logout"):
                return httpx.Response(200, json={})
            if request.url.path.endswith("/identities"):
                return httpx.Response(200, json={"session": None})
            return httpx.Response(400, json={"error": "authentication required"})
        result = client_class(**kwargs, transport=httpx.MockTransport(handle))
        clients.append(result)
        return result

    def fail_pair(*args):
        raise AssertionError("injected owner failure")

    monkeypatch.setattr(matrix, "signing_agent", lambda members: nullcontext({}))
    monkeypatch.setattr(matrix.httpx, "Client", client)
    monkeypatch.setattr(matrix.Member, "login", lambda self: setattr(self, "logged_in", True))
    monkeypatch.setattr(matrix, "verify_pair", fail_pair)
    monkeypatch.setattr("sys.argv", ["matrix", "--manifest", str(manifest), "--lifecycle-report", str(source), "--output", str(output)])
    assert matrix.main() == 1
    report = json.loads(output.read_text())
    assert report["error"] == "injected owner failure" and report["status"] == "failed"
    assert len(report["logout"]) == 8 and all(record["status"] == "passed" for record in report["logout"])
    assert all(client.is_closed for client in clients)
    assert sum(method == "POST" and path.endswith("/identity/logout") for _, method, path in events) == 8
    assert report["model_requests"] == 0
    with pytest.raises(AssertionError, match="overwrite"):
        matrix.main()

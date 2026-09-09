"""Real loopback HTTP admission and transport checks without a live model key."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import socket
import threading

import httpx
import pytest

from quantcode.model_gateway import MODEL, UPSTREAM, ModelGateway, load_credentials


KEY = "unit-upstream-credential"
TOKENS = {actor: (actor + "-unit-token-").ljust(48, "x") for actor in ("one", "two", "three")}


@contextmanager
def gateway(handler, **limits):
    members = {hashlib.sha256(token.encode()).hexdigest(): actor for actor, token in TOKENS.items()}
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as upstream:
        server = ModelGateway(0, api_key=KEY, members=members, upstream=upstream, **limits)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False, timeout=10) as client:
                yield client, server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def headers(actor="one"):
    return {"Authorization": "Bearer " + TOKENS[actor]}


def payload(**changes):
    return {"model": MODEL, "messages": [{"role": "user", "content": "A synthetic request"}], **changes}


def credentials(tmp_path):
    key = tmp_path / "dashscope-api-key"
    key.write_text(KEY + "\n")
    key.chmod(0o400)
    mapping = tmp_path / "member-tokens.json"
    mapping.write_text(json.dumps({"token_sha256": {actor: hashlib.sha256(token.encode()).hexdigest() for actor, token in TOKENS.items()}}))
    mapping.chmod(0o400)
    return key, mapping


def test_load_private_systemd_credentials_with_member_hashes(tmp_path, monkeypatch):
    credentials(tmp_path)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    key, members = load_credentials()
    assert key == KEY
    assert members[hashlib.sha256(TOKENS["two"].encode()).hexdigest()] == "two"
    assert all(token not in members for token in TOKENS.values())


@pytest.mark.parametrize("mode", ["public", "symlink", "duplicate", "plaintext"])
def test_invalid_credential_configuration_fails_closed(tmp_path, mode):
    key, mapping = credentials(tmp_path)
    if mode == "public":
        key.chmod(0o644)
    elif mode == "symlink":
        original = tmp_path / "original"
        key.rename(original)
        key.symlink_to(original)
    else:
        mapping.chmod(0o600)
        digest = hashlib.sha256(TOKENS["one"].encode()).hexdigest()
        mapping.write_text(json.dumps({"token_sha256": {"one": digest, "two": digest}} if mode == "duplicate" else {"tokens": TOKENS}))
    with pytest.raises((ValueError, OSError)) as caught:
        load_credentials(tmp_path)
    assert KEY not in str(caught.value)
    assert all(token not in str(caught.value) for token in TOKENS.values())


def test_models_authentication_and_fixed_routes_do_not_call_upstream():
    calls = []
    with gateway(lambda request: calls.append(request)) as (client, _):
        health = client.get("/health")
        assert health.status_code == 200 and health.json() == {"status": "ok"}
        assert health.headers["connection"] == "close"
        assert client.get("/v1/models").status_code == 401
        assert client.get("/v1/models", headers={"Authorization": "Bearer " + "z" * 48}).status_code == 401
        response = client.get("/v1/models", headers=headers())
        assert response.status_code == 200
        assert [model["id"] for model in response.json()["data"]] == [MODEL]
        assert response.headers["connection"] == "close"
        assert client.get("/v1/models?upstream=other", headers=headers()).status_code == 404
        assert client.post("/v1/embeddings", headers=headers(), json=payload()).status_code == 404
        assert client.put("/v1/models", headers=headers(), json={}).status_code == 501
    assert calls == []


def test_chat_forwards_only_to_fixed_upstream_and_caps_default_output():
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "actual upstream output"}}]},
                              headers={"Set-Cookie": "must-not-forward"})

    with gateway(upstream) as (client, _):
        response = client.post("/v1/chat/completions", headers={**headers(), "X-Private": "must-not-forward"}, json=payload())
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "actual upstream output"
    assert response.headers["connection"] == "close"
    assert "set-cookie" not in response.headers
    assert str(calls[0].url) == UPSTREAM
    assert calls[0].headers["authorization"] == "Bearer " + KEY
    assert "x-private" not in calls[0].headers
    assert json.loads(calls[0].content)["max_tokens"] == 4096
    assert TOKENS["one"].encode() not in calls[0].content


@pytest.mark.parametrize("changes", [
    {"model": "another-model"}, {"stream": "true"}, {"messages": []}, {"max_tokens": True},
    {"max_tokens": 0}, {"max_tokens": 4097}, {"max_completion_tokens": 10000}, {"n": 2}, {"best_of": 3},
])
def test_invalid_or_unbounded_completion_parameters_do_not_reach_upstream(changes):
    calls = []
    with gateway(lambda request: calls.append(request)) as (client, _):
        response = client.post("/v1/chat/completions", headers=headers(), json=payload(**changes))
    assert response.status_code == 400
    assert not calls


def test_body_size_content_type_and_duplicate_length_are_rejected():
    calls = []
    with gateway(lambda request: calls.append(request), max_request_bytes=256) as (client, server):
        assert client.post("/v1/chat/completions", headers=headers(), json=payload(extra="x" * 300)).status_code == 413
        assert client.post("/v1/chat/completions", headers=headers(), content=b"{}").status_code == 415
        assert client.post("/v1/chat/completions", headers={**headers(), "Content-Type": "application/json"}, content=b'{"max_tokens": NaN}').status_code == 400
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as connection:
            request = ("POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer " + TOKENS["one"] +
                       "\r\nContent-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}")
            connection.sendall(request.encode())
            assert b" 400 " in connection.recv(4096).split(b"\r\n", 1)[0]
    assert calls == []


def test_sse_first_event_is_forwarded_before_upstream_finishes():
    released = threading.Event()

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"data: first\n\n"
            assert released.wait(5), "gateway buffered the first SSE event"
            yield b"data: [DONE]\n\n"

    try:
        with gateway(lambda request: httpx.Response(200, stream=Stream())) as (client, _):
            with client.stream("POST", "/v1/chat/completions", headers=headers(), json=payload(stream=True, max_tokens=32)) as response:
                assert response.headers["content-type"] == "text/event-stream"
                chunks = response.iter_bytes()
                assert next(chunks) == b"data: first\n\n"
                released.set()
                assert b"".join(chunks) == b"data: [DONE]\n\n"
    finally:
        released.set()


def test_concurrency_is_bounded_per_member_and_globally_then_released():
    entered = [threading.Event(), threading.Event()]
    released = threading.Event()
    calls = []
    lock = threading.Lock()

    def upstream(request):
        with lock:
            index = len(calls)
            calls.append(request)
        if index < 2:
            entered[index].set()
            assert released.wait(5)
        return httpx.Response(200, json={"choices": []})

    try:
        with gateway(upstream, max_concurrency=2, per_member_concurrency=1) as (client, _), ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(client.post, "/v1/chat/completions", headers=headers("one"), json=payload())
            assert entered[0].wait(5)
            busy = client.post("/v1/chat/completions", headers=headers("one"), json=payload())
            assert busy.status_code == 429 and busy.headers["retry-after"] == "1"
            two = pool.submit(client.post, "/v1/chat/completions", headers=headers("two"), json=payload())
            assert entered[1].wait(5)
            assert client.post("/v1/chat/completions", headers=headers("three"), json=payload()).status_code == 429
            released.set()
            assert one.result().status_code == two.result().status_code == 200
            assert client.post("/v1/chat/completions", headers=headers("three"), json=payload()).status_code == 200
    finally:
        released.set()


def test_default_member_limit_allows_main_and_auxiliary_requests_together():
    entered = [threading.Event(), threading.Event()]
    released = threading.Event()
    lock = threading.Lock()
    calls = []

    def upstream(request):
        with lock:
            index = len(calls)
            calls.append(request)
        entered[index].set()
        assert released.wait(5)
        return httpx.Response(200, json={"choices": []})

    try:
        with gateway(upstream) as (client, _), ThreadPoolExecutor(max_workers=2) as pool:
            main = pool.submit(client.post, "/v1/chat/completions", headers=headers(), json=payload())
            assert entered[0].wait(5)
            auxiliary = pool.submit(client.post, "/v1/chat/completions", headers=headers(), json=payload(max_tokens=64))
            assert entered[1].wait(5)
            assert client.post("/v1/chat/completions", headers=headers(), json=payload()).status_code == 429
            released.set()
            assert main.result().status_code == auxiliary.result().status_code == 200
    finally:
        released.set()


@pytest.mark.parametrize("failure", ["redirect", "unauthorized", "transport"])
def test_upstream_errors_do_not_follow_redirects_or_disclose_credentials(failure, capsys):
    calls = []

    def upstream(request):
        calls.append(request)
        if failure == "transport":
            raise httpx.ReadTimeout(KEY)
        return httpx.Response(302 if failure == "redirect" else 401,
                              headers={"Location": "https://untrusted.example"}, text=KEY)

    with gateway(upstream) as (client, server):
        response = client.post("/v1/chat/completions", headers=headers(), json=payload())
        assert not server._active
    assert len(calls) == 1
    assert response.status_code == 502
    assert KEY not in response.text and "location" not in response.headers
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err
    assert all(token not in captured.out + captured.err for token in TOKENS.values())

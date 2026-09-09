"""Loopback Qwen gateway with systemd credentials and per-member admission.

LoadCredential names: dashscope-api-key and member-tokens.json. The latter is
{"token_sha256": {"actor-id": "64 lowercase hex characters"}}. Credential
changes take effect on restart. Keys and request/response contents are not logged.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import stat
import threading

import httpx


UPSTREAM = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3.7-flash"


def reject_constant(value):
    raise ValueError("non-finite JSON is not permitted")


def load_credentials(directory: Path | None = None) -> tuple[str, dict[str, str]]:
    configured = directory or os.environ.get("CREDENTIALS_DIRECTORY")
    if not configured or not Path(configured).is_absolute():
        raise ValueError("an absolute systemd credentials directory is required")
    with os.fdopen(os.open(Path(configured) / "dashscope-api-key", os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
            raise ValueError("upstream credential must be a private bounded regular file")
        key = source.read(4097).decode("ascii").strip()
    if not key or len(key) > 4096 or any(not 33 <= ord(char) <= 126 for char in key):
        raise ValueError("invalid upstream credential")
    with os.fdopen(os.open(Path(configured) / "member-tokens.json", os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 131072:
            raise ValueError("member credentials must be a private bounded regular file")
        try:
            config = json.loads(source.read(131073))
        except (ValueError, UnicodeError):
            raise ValueError("invalid member credential configuration") from None
    if not isinstance(config, dict) or set(config) != {"token_sha256"}:
        raise ValueError("member credential configuration requires token_sha256")
    members = config["token_sha256"]
    if not isinstance(members, dict) or not 1 <= len(members) <= 512:
        raise ValueError("member credential configuration must contain 1 to 512 members")
    by_digest = {}
    for actor, digest in members.items():
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 128 or any(ord(char) < 32 for char in actor):
            raise ValueError("invalid member identifier")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in by_digest:
            raise ValueError("member token digests must be unique SHA-256 values")
        by_digest[digest] = actor
    return key, by_digest


class ModelGateway(ThreadingHTTPServer):
    request_queue_size = 64

    def __init__(self, port: int, *, api_key: str, members: dict[str, str], upstream: httpx.Client,
                 max_concurrency: int = 4, per_member_concurrency: int = 2,
                 max_tokens: int = 4096, max_request_bytes: int = 2_000_000):
        if not 1 <= per_member_concurrency <= max_concurrency <= 64 or not 1 <= max_tokens <= 8192 or not 128 <= max_request_bytes <= 2_000_000:
            raise ValueError("invalid gateway limits")
        self.api_key, self.members, self.upstream = api_key, dict(members), upstream
        self.max_concurrency, self.per_member_concurrency = max_concurrency, per_member_concurrency
        self.max_tokens, self.max_request_bytes = max_tokens, max_request_bytes
        self._admission_lock = threading.Lock()
        self._active: dict[str, int] = {}
        self._workers = threading.BoundedSemaphore(max(16, max_concurrency * 4))
        super().__init__(("127.0.0.1", port), ModelHandler)

    def process_request(self, request, client_address):
        if not self._workers.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._workers.release()

    def handle_error(self, request, client_address):
        pass

    def acquire(self, actor: str) -> bool:
        with self._admission_lock:
            if sum(self._active.values()) >= self.max_concurrency or self._active.get(actor, 0) >= self.per_member_concurrency:
                return False
            self._active[actor] = self._active.get(actor, 0) + 1
            return True

    def release(self, actor: str) -> None:
        with self._admission_lock:
            count = self._active[actor] - 1
            if count:
                self._active[actor] = count
            else:
                del self._active[actor]


class ModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: ModelGateway

    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def log_message(self, *args):
        pass

    def reply(self, status, message):
        data = json.dumps(message).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if status == 429:
            self.send_header("Retry-After", "1")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"error": "request not supported"})

    def actor(self):
        values = self.headers.get_all("Authorization", [])
        if len(values) != 1:
            return None
        scheme, _, token = values[0].partition(" ")
        if scheme.lower() != "bearer" or not re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", token):
            return None
        return self.server.members.get(hashlib.sha256(token.encode()).hexdigest())

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"status": "ok"})
        if self.actor() is None:
            return self.reply(401, {"error": "member authentication required"})
        if self.path != "/v1/models":
            return self.reply(404, {"error": "route not permitted"})
        self.reply(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "qwen"}]})

    def do_POST(self):
        actor = self.actor()
        if actor is None:
            return self.reply(401, {"error": "member authentication required"})
        if self.path != "/v1/chat/completions":
            return self.reply(404, {"error": "route not permitted"})
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            return self.reply(400, {"error": "one bounded Content-Length is required"})
        length = int(lengths[0])
        if not 0 < length <= self.server.max_request_bytes:
            return self.reply(413, {"error": "request size exceeds the gateway limit"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "application/json is required"})
        try:
            content = self.rfile.read(length)
            if len(content) != length:
                raise ValueError()
            payload = json.loads(content, parse_constant=reject_constant)
            if not isinstance(payload, dict) or payload.get("model") != MODEL:
                raise ValueError()
            if not isinstance(payload.get("messages"), list) or not payload["messages"]:
                raise ValueError()
            if type(payload.get("stream", False)) is not bool:
                raise ValueError()
            if any(type(payload.get(name, 1)) is not int or payload.get(name, 1) != 1 for name in ("n", "best_of")):
                raise ValueError()
            for name in ("max_tokens", "max_completion_tokens"):
                if name in payload and (type(payload[name]) is not int or not 1 <= payload[name] <= self.server.max_tokens):
                    raise ValueError()
            if "max_tokens" not in payload and "max_completion_tokens" not in payload:
                payload["max_tokens"] = self.server.max_tokens
        except (ValueError, TypeError, UnicodeError, OSError, RecursionError):
            return self.reply(400, {"error": "invalid request for the authorized model or gateway limits"})
        if not self.server.acquire(actor):
            return self.reply(429, {"error": "member or gateway concurrency limit reached"})
        sent = False
        try:
            with self.server.upstream.stream("POST", UPSTREAM, json=payload,
                    headers={"Authorization": "Bearer " + self.server.api_key}, follow_redirects=False) as response:
                if response.status_code != 200:
                    status = response.status_code if 400 <= response.status_code < 500 and response.status_code not in (401, 403) else 502
                    return self.reply(status, {"error": "authorized upstream request failed"})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if payload.get("stream") else "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                sent = True
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 16_000_000:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (httpx.HTTPError, OSError):
            if not sent:
                self.reply(502, {"error": "authorized upstream transport unavailable"})
            self.close_connection = True
        finally:
            self.server.release(actor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=6201)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--per-member-concurrency", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-request-bytes", type=int, default=2_000_000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        key, members = load_credentials()
    except (OSError, ValueError, UnicodeError):
        parser.error("private systemd model gateway credentials are unavailable or invalid")
    with httpx.Client(timeout=httpx.Timeout(180, connect=15, write=30, pool=5),
                      limits=httpx.Limits(max_connections=args.max_concurrency, max_keepalive_connections=args.max_concurrency),
                      trust_env=False, follow_redirects=False) as upstream:
        with ModelGateway(args.port, api_key=key, members=members, upstream=upstream,
                          max_concurrency=args.max_concurrency, per_member_concurrency=args.per_member_concurrency,
                          max_tokens=args.max_tokens, max_request_bytes=args.max_request_bytes) as server:
            print(f"QuantCode model gateway ready on 127.0.0.1:{server.server_port}; model={MODEL}", flush=True)
            server.serve_forever()


if __name__ == "__main__":
    main()

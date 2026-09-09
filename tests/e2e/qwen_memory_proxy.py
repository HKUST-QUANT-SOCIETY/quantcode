"""QA-only loopback transport: the real Qwen key stays in process memory.

Run on the staging server with its QA virtualenv; enter the upstream key at
the hidden prompt. Only a random local access token is written to access-file.
"""
from __future__ import annotations

import argparse
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets

import httpx


UPSTREAM = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.7-flash"


def serve(key: str, port: int, access_file: Path) -> None:
    token = secrets.token_urlsafe(32)
    upstream = httpx.Client(timeout=httpx.Timeout(180, connect=15), trust_env=False, follow_redirects=False)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(data)

        def admitted(self):
            return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if not self.admitted():
                return self.reply(401, {"error": "staging proxy authentication required"})
            if self.path != "/v1/models":
                return self.reply(404, {"error": "route not permitted"})
            self.reply(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "qwen"}]})

        def do_POST(self):
            if not self.admitted():
                return self.reply(401, {"error": "staging proxy authentication required"})
            if self.path != "/v1/chat/completions":
                return self.reply(404, {"error": "route not permitted"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2_000_000:
                    return self.reply(400, {"error": "invalid request size"})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or payload.get("model") != MODEL:
                    return self.reply(400, {"error": "only the authorized QA model is permitted"})
                if type(payload.get("stream", False)) is not bool:
                    return self.reply(400, {"error": "invalid stream flag"})
            except (ValueError, TypeError):
                return self.reply(400, {"error": "invalid JSON request"})
            try:
                with upstream.stream("POST", UPSTREAM + "/chat/completions", json=payload,
                                     headers={"Authorization": "Bearer " + key}) as response:
                    if response.status_code != 200:
                        return self.reply(response.status_code, {"error": "authorized upstream request failed"})
                    self.send_response(200)
                    self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    for chunk in response.iter_bytes():
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (httpx.HTTPError, BrokenPipeError, ConnectionResetError):
                # Headers or SSE may already be sent. Close without logging
                # request bodies, bearer headers, or upstream exception text.
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    access_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(access_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump({"base_url": f"http://127.0.0.1:{server.server_port}/v1", "token": token, "model": MODEL}, output)
    print(f"QA Qwen proxy ready on 127.0.0.1:{server.server_port}; access file: {access_file}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        upstream.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=6200)
    parser.add_argument("--access-file", type=Path, required=True)
    args = parser.parse_args()
    api_key = getpass.getpass("Authorized Qwen API key (memory only): ").strip()
    if not api_key:
        parser.error("An upstream key is required")
    serve(api_key, args.port, args.access_file)

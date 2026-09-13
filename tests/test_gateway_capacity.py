from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
import threading

import httpx

from quantcode.gateway import GatewayHTTPServer


def test_control_plane_rejects_excess_workers_and_reuses_released_capacity():
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            entered.set()
            assert release.wait(5)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = GatewayHTTPServer(("127.0.0.1", 0), Handler, max_workers=1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False, timeout=5) as client, ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.get, "/")
            assert entered.wait(3)
            assert client.get("/").status_code == 503
            release.set()
            assert first.result().status_code == 200
            assert client.get("/").status_code == 200
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

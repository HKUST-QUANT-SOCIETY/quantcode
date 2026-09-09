"""Optional Admin-only handoff to the external production deploy service.

The service is deliberately absent by default.  A configured endpoint receives
the already hashed artifact reference and returns a small status envelope; no
production credentials are passed through the Agent or stored in evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import error, request


def _token() -> str | None:
    filename = os.environ.get("QUANTCODE_DEPLOY_TOKEN_FILE", "").strip()
    if not filename:
        return None
    path = Path(filename)
    if not path.is_absolute():
        raise ValueError("deploy token file must be absolute")
    try:
        info = path.stat()
    except OSError as exc:
        raise PermissionError("deploy token file is unavailable") from exc
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise PermissionError("deploy token file must be absolute, owner-only and user-owned")
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def submit(payload: dict, *, timeout: float = 10.0) -> dict | None:
    """Submit a deployment request when ``QUANTCODE_DEPLOY_URL`` is configured."""
    endpoint = os.environ.get("QUANTCODE_DEPLOY_URL", "").strip()
    if not endpoint:
        return None
    if not endpoint.startswith("https://") and not endpoint.startswith("http://127.0.0.1") and not endpoint.startswith("http://localhost"):
        raise ValueError("QUANTCODE_DEPLOY_URL must use HTTPS or loopback HTTP")
    headers = {"Content-Type": "application/json"}
    try:
        token = _token()
    except (OSError, PermissionError, ValueError) as exc:
        return {"status": "FAILED", "error": str(exc)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(endpoint.rstrip("/") + "/deployments", data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"status": "FAILED", "error": f"production deploy service unavailable ({type(exc).__name__})"}
    if not isinstance(body, dict):
        return {"status": "FAILED", "error": "production deploy service returned invalid response"}
    return body

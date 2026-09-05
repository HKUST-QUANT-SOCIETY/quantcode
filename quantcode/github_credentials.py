"""Host-owned GitHub credential lookup keyed by authenticated roster subject.

The mapping holds secret-file references, not bearer values. Authorization still
requires GitHub /user and team/repository checks at each consuming boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


def _private_text(path: Path) -> str:
    if os.name == "nt":
        raise PermissionError(
            "GitHub credential files are not supported on Windows; configure the OS keyring provider"
        )
    info = path.stat()
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise PermissionError("GitHub credential files must be owned by the service user and private")
    return path.read_text(encoding="utf-8")


def _valid_token(token: object) -> str:
    value = str(token or "").strip()
    if not value or any(char.isspace() for char in value):
        raise ValueError("invalid GitHub credential")
    return value


def subject_token(ctx: dict) -> str | None:
    subject = str(ctx.get("github_subject") or "")
    if not subject:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", subject):
        raise PermissionError("invalid authenticated GitHub subject")
    keyring_service = os.environ.get("QUANTCODE_GITHUB_KEYRING_SERVICE")
    if keyring_service:
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError(
                "GitHub keyring provider requires the quantcode[github] optional dependency"
            ) from exc
        token = keyring.get_password(keyring_service, subject.lower())
        return _valid_token(token) if token is not None else None

    filename = os.environ.get("QUANTCODE_GITHUB_CREDENTIALS_FILE")
    if not filename:
        return None
    path = Path(filename)
    if not path.is_absolute():
        raise ValueError("GitHub credential mapping requires an absolute path")
    data = json.loads(_private_text(path))
    if not isinstance(data, dict) or not isinstance(data.get("subjects"), dict):
        raise ValueError("invalid GitHub credential mapping")
    entry = data["subjects"].get(subject.lower())
    if entry is None:
        return None
    if not isinstance(entry, dict) or set(entry) != {"token_file"}:
        raise ValueError("GitHub credential entry requires only token_file")
    token_path = Path(entry["token_file"])
    if not token_path.is_absolute():
        raise ValueError("GitHub token file requires an absolute path")
    return _valid_token(_private_text(token_path))

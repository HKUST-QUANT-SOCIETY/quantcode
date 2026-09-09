"""Host-owned GitHub credential lookup keyed by authenticated roster subject.

The mapping holds secret-file references, not bearer values. Authorization still
requires GitHub /user and team/repository checks at each consuming boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat


def _credential_directory(path: Path) -> os.stat_result:
    """A readable legacy directory is safe when only its owner can write it.

    Credential bytes remain in private files. Requiring 0700 here would reject
    existing 0755 .quantcode directories without protecting additional bytes.
    """
    if os.name != "posix" or not path.is_absolute() or path.resolve() != path:
        raise PermissionError("GitHub credential directory must be a canonical host path")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise PermissionError("GitHub credential directory must be host-owned and not writable by others")
    return info


def _private_text(path: Path, max_bytes: int = 262144) -> str:
    directory = _credential_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077
                or info.st_uid != os.getuid() or info.st_size > max_bytes):
            raise PermissionError("GitHub credential files must be private regular files owned by the host")
        raw = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
        linked = path.lstat()
        parent = _credential_directory(path.parent)
        if (len(raw) > max_bytes or stat.S_ISLNK(linked.st_mode)
                or (parent.st_dev, parent.st_ino) != (directory.st_dev, directory.st_ino)
                or (linked.st_dev, linked.st_ino) != (info.st_dev, info.st_ino)
                or (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink) !=
                   (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)
                or (linked.st_size, linked.st_mtime_ns, linked.st_ctime_ns) !=
                   (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise PermissionError("GitHub credential changed during read")
        return raw.decode("utf-8")


def subject_token(ctx: dict) -> str | None:
    subject = str(ctx.get("github_subject") or "")
    if not subject:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", subject):
        raise PermissionError("invalid authenticated GitHub subject")
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
    token = _private_text(token_path, 16384).strip()
    if not token or any(char.isspace() for char in token):
        raise ValueError("invalid GitHub credential")
    return token

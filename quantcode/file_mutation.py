"""Fixed, descriptor-relative file operations for the native editing tools.

The host has already checked the roster, session, plan and exact target. This
helper closes Node's missing openat boundary: every directory is opened without
following links and replacements create a new inode. No code, command, source
module or interpreter arguments are accepted in the request.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import sys
import uuid
from contextlib import ExitStack

MAX_BYTES = 32 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 10_000


class MutationDenied(Exception):
    pass


def _components(value: str) -> list[str]:
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise MutationDenied("invalid_path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MutationDenied("invalid_path")
    return parts


def _directory(name: str, stack: ExitStack, parent: int | None = None) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    stack.callback(os.close, fd)
    return fd


def _snapshot(parent: int, name: str) -> tuple[dict, bytes]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    except FileNotFoundError:
        return {"exists": False}, b""
    with os.fdopen(fd, "rb") as file:
        before = os.fstat(file.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
            raise MutationDenied("invalid_file")
        content = file.read(MAX_BYTES + 1)
        after = os.fstat(file.fileno())
        linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
        if len(content) > MAX_BYTES or any(getattr(before, field) != getattr(after, field) or
                                         getattr(linked, field) != getattr(after, field) for field in fields):
            raise MutationDenied("stale")
        return {"exists": True, "sha256": hashlib.sha256(content).hexdigest(),
                "device": str(before.st_dev), "inode": str(before.st_ino),
                "modified": str(before.st_mtime_ns), "changed": str(before.st_ctime_ns),
                "mode": stat.S_IMODE(before.st_mode)}, content


def _directory_snapshot(info: os.stat_result) -> dict:
    return {"device": str(info.st_dev), "inode": str(info.st_ino),
            "modified": str(info.st_mtime_ns), "changed": str(info.st_ctime_ns)}


def _list_directory(directory: int, parts: list[str], denied: list[list[str]], expected: dict) -> dict:
    if os.scandir not in os.supports_fd or os.stat not in os.supports_dir_fd:
        raise MutationDenied("unsupported_platform")
    before = _directory_snapshot(os.fstat(directory))
    if before != expected:
        raise MutationDenied("stale")
    entries = []
    with os.scandir(directory) as children:
        for index, child in enumerate(children):
            if index >= MAX_DIRECTORY_ENTRIES:
                raise MutationDenied("directory_too_large")
            # scandir(fd) and stat(dir_fd=fd) are native on macOS and Linux;
            # /dev/fd re-opening is neither required nor portable for folders.
            components = [*parts, child.name]
            if any(components[:len(item)] == item for item in denied):
                continue
            info = os.stat(child.name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                continue
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                continue
            if any(0xD800 <= ord(char) <= 0xDFFF for char in child.name):
                raise MutationDenied("invalid_path")
            entries.append({"name": child.name, "type": "directory" if stat.S_ISDIR(info.st_mode) else "file",
                            **_directory_snapshot(info), "links": str(info.st_nlink)})
    # Child metadata may change without changing its parent's timestamps.
    for item in entries:
        info = os.stat(item["name"], dir_fd=directory, follow_symlinks=False)
        kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else None
        if (kind != item["type"] or str(info.st_nlink) != item["links"] or
                _directory_snapshot(info) != {key: item[key] for key in before}):
            raise MutationDenied("stale")
    if _directory_snapshot(os.fstat(directory)) != before:
        raise MutationDenied("stale")
    return {"directory": before, "entries": entries}


def _apply(request: dict) -> dict:
    if os.name != "posix" or os.open not in os.supports_dir_fd or os.rename not in os.supports_dir_fd:
        raise MutationDenied("unsupported_platform")
    required = {"version", "action", "root", "relative", "root_device", "root_inode", "denied"}
    if not isinstance(request, dict) or set(request) - required - {"expected", "content", "executable", "expected_directory"} or not required <= set(request):
        raise MutationDenied("invalid_request")
    if request["version"] != 1 or request["action"] not in {"read", "write", "delete", "mkdir_git", "list"}:
        raise MutationDenied("invalid_request")
    if request["action"] == "list":
        if set(request) != required | {"expected_directory"} or not isinstance(request["expected_directory"], dict):
            raise MutationDenied("invalid_request")
    elif "expected_directory" in request:
        raise MutationDenied("invalid_request")
    if "executable" in request and (request["action"] != "write" or type(request["executable"]) is not bool):
        raise MutationDenied("invalid_request")
    if not isinstance(request["root"], str) or not request["root"].startswith("/") or request["root"] == "/":
        raise MutationDenied("invalid_path")
    root_parts = _components(request["root"][1:])
    parts = [] if request["action"] == "list" and request["relative"] == "" else _components(request["relative"])
    if not isinstance(request["denied"], list):
        raise MutationDenied("invalid_request")
    denied_paths = []
    for item in request["denied"]:
        denied = _components(item)
        denied_paths.append(denied)
        if parts[:len(denied)] == denied:
            raise MutationDenied("private_path")
    writing = request["action"] not in {"read", "list"}
    if writing and request["action"] != "mkdir_git" and not isinstance(request.get("expected"), dict):
        raise MutationDenied("invalid_request")
    if request["action"] == "mkdir_git" and (parts != [".git"] or set(request) != required):
        raise MutationDenied("invalid_request")
    content = base64.b64decode(request.get("content", ""), validate=True) if request["action"] == "write" else b""
    if len(content) > MAX_BYTES:
        raise MutationDenied("file_too_large")

    with ExitStack() as stack:
        root = _directory("/", stack)
        for part in root_parts:
            root = _directory(part, stack, root)
        root_info = os.fstat(root)
        if (str(root_info.st_dev), str(root_info.st_ino)) != (request["root_device"], request["root_inode"]):
            raise MutationDenied("workspace_changed")
        if request["action"] == "list":
            directory = root
            for part in parts:
                directory = _directory(part, stack, directory)
            return _list_directory(directory, parts, denied_paths, request["expected_directory"])
        parent = root
        for part in parts[:-1]:
            try:
                parent = _directory(part, stack, parent)
            except FileNotFoundError:
                if request["action"] == "read":
                    return {"snapshot": {"exists": False}, "content": ""}
                if request["action"] != "write" or request["expected"].get("exists") is not False:
                    raise MutationDenied("stale")
                try:
                    os.mkdir(part, 0o777, dir_fd=parent)
                    os.fsync(parent)
                except FileExistsError:
                    pass
                # Another process may have substituted this entry. NOFOLLOW
                # checks the actual opened directory, not its earlier lstat.
                parent = _directory(part, stack, parent)
        name = parts[-1]
        if request["action"] == "mkdir_git":
            # A fixed host-only operation, not arbitrary directory creation.
            # mkdirat is exclusive; an existing repository is never replaced.
            os.mkdir(name, 0o700, dir_fd=parent)
            created = _directory(name, stack, parent)
            info = os.fstat(created)
            os.fsync(parent)
            return {"directory": {"device": str(info.st_dev), "inode": str(info.st_ino)}}
        snapshot, previous = _snapshot(parent, name)
        if request["action"] == "read":
            return {"snapshot": snapshot, "content": base64.b64encode(previous).decode("ascii")}
        if snapshot != request["expected"]:
            raise MutationDenied("stale")
        if request["action"] == "delete":
            if not snapshot["exists"]:
                raise MutationDenied("stale")
            # unlinkat removes only this admitted directory entry. It never
            # follows a substituted leaf symlink into another directory.
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)
            return {"snapshot": {"exists": False}, "content": ""}

        temporary = ".quantcode-edit-" + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)
                mask = os.umask(0)
                os.umask(mask)
                # Preserve executable bits, but never transfer setuid/setgid.
                mode = (snapshot["mode"] & 0o777) if snapshot["exists"] else (0o666 & ~mask)
                if request.get("executable") is True:
                    mode |= (mode & 0o444) >> 2
                elif request.get("executable") is False:
                    mode &= ~0o111
                os.fchmod(file.fileno(), mode)
                file.flush()
                os.fsync(file.fileno())
                current, _ = _snapshot(parent, name)
                if current != request["expected"]:
                    raise MutationDenied("stale")
                # An atomic directory-entry replacement cannot truncate a
                # hardlinked or symlink-substituted destination inode. Existing
                # targets are not a filesystem CAS against unrelated editors:
                # a non-cooperating writer can still race this final comparison.
                if snapshot["exists"]:
                    writable = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
                    os.close(writable)
                    os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                else:
                    # Creation is exclusive even when another editor creates
                    # the destination after the absent-file preview.
                    os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    os.unlink(temporary, dir_fd=parent)
                os.fsync(parent)
            result, actual = _snapshot(parent, name)
            if actual != content:
                raise MutationDenied("stale")
            return {"snapshot": result, "content": ""}
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES * 2 + 1)
        if len(raw) > MAX_BYTES * 2:
            raise MutationDenied("file_too_large")
        result = _apply(json.loads(raw))
        print(json.dumps({"ok": True, **result}))
    except MutationDenied as error:
        print(json.dumps({"ok": False, "code": str(error)}))
    except (OSError, ValueError, TypeError, KeyError):
        # Neither paths nor file content belong in interpreter error output.
        print(json.dumps({"ok": False, "code": "filesystem_denied"}))


if __name__ == "__main__":
    main()

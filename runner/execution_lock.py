"""Process-safe single-writer admission for local MCP run execution.

The OS releases the lock on process exit. Never unlink lock files: waiters and
new callers must agree on the same file identity. Checkpoints remain durable.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
from typing import BinaryIO


def _acquire(handle: BinaryIO, *, blocking: bool) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(handle.fileno(), mode, 1)
        except OSError as exc:
            raise RuntimeError("RUN_BUSY: this task is already executing") from exc
        return

    import fcntl

    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(handle.fileno(), flags)
    except BlockingIOError as exc:
        raise RuntimeError("RUN_BUSY: this task is already executing") from exc


def _release(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def execution_lock(db_path: Path, thread_id: str, *, blocking: bool = False):
    directory = Path(db_path).parent / "run-locks"
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{Path(db_path).resolve()}:{thread_id}".encode()).hexdigest()
    with (directory / f"{key}.lock").open("a+b") as handle:
        _acquire(handle, blocking=blocking)
        try:
            yield
        finally:
            _release(handle)

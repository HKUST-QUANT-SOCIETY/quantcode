"""Process-safe single-writer admission for local MCP run execution.

The OS releases the lock on process exit. Never unlink lock files: waiters and
new callers must agree on the same inode. Checkpoints remain the durable state.
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path


@contextmanager
def execution_lock(db_path: Path, thread_id: str):
    import fcntl

    directory = Path(db_path).parent / "run-locks"
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{Path(db_path).resolve()}:{thread_id}".encode()).hexdigest()
    with (directory / f"{key}.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("RUN_BUSY: this task is already executing") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

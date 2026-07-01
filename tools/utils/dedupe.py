"""SQLite-backed dedupe decorator for side-effecting tools."""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from pathlib import Path
import pickle
import sqlite3
import time
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


KeyBuilder = str | Callable[..., str]


def _default_db_path() -> Path:
    return Path.cwd() / ".quantcode" / "dedupe.sqlite"


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dedupe_log (
            cache_key TEXT PRIMARY KEY,
            fn_name TEXT NOT NULL,
            first_call_at REAL NOT NULL,
            result BLOB NOT NULL
        )
        """
    )


def _resolve_key(key: KeyBuilder, args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    if callable(key):
        return str(key(*args, **kwargs))
    return str(key)


def dedupe_within(
    seconds: int,
    key: KeyBuilder,
    *,
    db_path: str | Path | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Return cached result for repeated side-effect calls within ``seconds``.

    The cache key is scoped by function name plus the user-provided key, so two
    tools can safely use the same user key without colliding.
    """
    if seconds < 0:
        raise ValueError("seconds must be >= 0")

    path = Path(db_path) if db_path is not None else _default_db_path()

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        fn_name = f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            user_key = _resolve_key(key, args, kwargs)
            cache_key = f"{fn_name}:{user_key}"
            now = time.time()

            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            try:
                _ensure_table(conn)
                row = conn.execute(
                    """
                    SELECT first_call_at, result
                    FROM dedupe_log
                    WHERE cache_key = ?
                    """,
                    (cache_key,),
                ).fetchone()
                if row is not None:
                    first_call_at, cached = row
                    if now - float(first_call_at) <= seconds:
                        return pickle.loads(cached)

                result = fn(*args, **kwargs)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dedupe_log
                        (cache_key, fn_name, first_call_at, result)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cache_key, fn_name, now, pickle.dumps(result)),
                )
                conn.commit()
                return result
            finally:
                conn.close()

        return wrapper

    return decorator

"""Small path helpers shared by artifact-producing adapters."""
from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath


def explicit_dev_environment() -> bool:
    """Whether caller explicitly opted into local development/test behavior."""
    return os.environ.get("QUANTCODE_ENV", "").strip().lower() in {
        "dev",
        "development",
        "test",
    }


def resolve_input_path(
    value: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    allow_external_in_dev: bool = True,
) -> Path:
    """Resolve an input path and reject checkout escapes in production.

    Relative paths are rooted at ``root``. Symlinks and ``..`` are resolved
    before the containment check. External paths remain available for
    explicit test/development fixtures, but callers cannot opt into that
    behavior by setting an arbitrary tool argument.
    """
    raw = os.fspath(value)
    if "\x00" in raw:
        raise ValueError("path must not contain NUL bytes")
    # ``Path`` follows the host OS. Normalize Windows separators before the
    # containment check so a request such as ``..\\secrets`` is not treated
    # as a harmless filename when evaluated on macOS/Linux. Drive/UNC paths
    # are rejected in production even when this process is not Windows.
    windows = PureWindowsPath(raw)
    if windows.is_absolute() or windows.drive:
        if allow_external_in_dev and explicit_dev_environment():
            return Path(raw).expanduser().resolve()
        raise ValueError("path must remain inside the approved QuantCode checkout")
    normalized_raw = raw.replace("\\", "/")
    root_path = Path(root).expanduser().resolve()
    candidate = Path(normalized_raw).expanduser()
    resolved = (candidate if candidate.is_absolute() else root_path / candidate).resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError:
        if allow_external_in_dev and explicit_dev_environment():
            return resolved
        raise ValueError("path must remain inside the approved QuantCode checkout")
    return resolved


def safe_filename_component(
    value: object,
    *,
    fallback: str = "artifact",
    max_length: int = 96,
) -> str:
    """Return a deterministic single filename component.

    User- or component-supplied identifiers may contain POSIX or Windows
    separators.  Replace every non-word character except ``.``/``-`` with an
    underscore, then remove leading dots so the result cannot become a hidden
    path or ``..`` component.
    """
    text = str(value or "").strip().replace("\\", "_")
    slug = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).lstrip(".")
    return (slug[:max_length] or fallback)


__all__ = ["safe_filename_component", "explicit_dev_environment", "resolve_input_path"]

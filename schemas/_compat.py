"""Small cross-runtime typing/enum compatibility surface for shared schemas."""
from __future__ import annotations

from enum import Enum
from typing import Any

try:  # Python 3.11+
    from enum import StrEnum as StrEnum
except ImportError:  # pragma: no cover - exercised by the pinned 3.10 executor
    class StrEnum(str, Enum):
        """Backport subset sufficient for Pydantic string enums."""

try:  # Python 3.11+
    from typing import Self as Self
except ImportError:  # pragma: no cover - exercised by the pinned 3.10 executor
    try:
        from typing_extensions import Self as Self
    except ImportError:  # annotations are postponed; runtime fallback is sufficient
        Self = Any

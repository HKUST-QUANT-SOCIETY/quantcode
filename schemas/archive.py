"""QuantCode archive schemas — demo / run snapshot packs.

Owner: 刘炽

``artifacts/`` is a working scratchpad (gitignored).
``archives/`` holds immutable demo packs for review and handoff.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ArchiveSource(StrEnum):
    DEMO = "demo"
    AGENT = "agent"
    ACCEPTANCE = "acceptance"
    MANUAL = "manual"


class ArchiveManifest(BaseModel):
    """Metadata for one archive pack under ``archives/<archive_id>/``."""

    model_config = ConfigDict(extra="forbid")

    archive_id: str = Field(min_length=1, max_length=256)
    group: str = Field(min_length=1, description="strategy / fundamental / options / ...")
    created_at: datetime
    thread_id: str | None = None
    task: str | None = None
    artifact_paths: list[str] = Field(
        default_factory=list,
        description="Paths relative to archive root (under artifacts/)",
    )
    schemas: list[str] = Field(default_factory=list)
    acceptance: dict | None = None
    source: ArchiveSource = ArchiveSource.DEMO
    notes: str | None = None
    missing_sources: list[str] = Field(
        default_factory=list,
        description="Original repo-relative paths that were listed but not found",
    )


class ArchivePackResult(BaseModel):
    """Return payload from packing helpers / CLI."""

    model_config = ConfigDict(extra="forbid")

    archive_id: str
    archive_dir: str
    manifest_path: str
    manifest: ArchiveManifest
    file_count: int = Field(ge=0)


__all__ = [
    "ArchiveSource",
    "ArchiveManifest",
    "ArchivePackResult",
]

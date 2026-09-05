"""GitGraph v5 data contract."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GitSyncStatus(StrEnum):
    CONNECTED = "CONNECTED"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ERROR = "ERROR"
    NO_CHANGE = "NO_CHANGE"
    UNAVAILABLE = "UNAVAILABLE"


class GitGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1)
    visibility_source: str = Field(min_length=1)
    default_branch: str | None = None
    branches: list[dict[str, Any]] = Field(default_factory=list)
    heads: list[dict[str, Any]] = Field(default_factory=list)
    commit_nodes: list[dict[str, Any]] = Field(default_factory=list)
    parent_edges: list[dict[str, Any]] = Field(default_factory=list)
    latest_commit: dict[str, Any] | None = None
    dependency_files: list[dict[str, Any]] = Field(default_factory=list)
    dependency_changes: list[dict[str, Any]] = Field(default_factory=list)
    package_changes: list[dict[str, Any]] = Field(default_factory=list)
    activity: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    commit_window_per_branch: int = Field(default=30, ge=1)
    dependency_scope: str = Field(default="recursive-v1", min_length=1)
    archived: bool = False
    observed_at: datetime
    sync_status: GitSyncStatus


class GitGraphSyncResult(BaseModel):
    """Top-level result returned by the GitGraph tool and background worker."""

    model_config = ConfigDict(extra="forbid")

    repos: list[GitGraph] = Field(default_factory=list)
    visibility_source: str = Field(min_length=1)
    sync_status: GitSyncStatus
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    errors: list[str] = Field(default_factory=list)


__all__ = ["GitSyncStatus", "GitGraph", "GitGraphSyncResult"]

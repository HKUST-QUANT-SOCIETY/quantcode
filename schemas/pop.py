"""Repo/package Pop v5 data contract."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PopType(StrEnum):
    REPO_COMMIT = "repo_commit"
    BRANCH = "branch"
    PACKAGE = "package"


class Pop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pop_id: str = Field(min_length=1)
    type: PopType
    repo_or_package: str = Field(min_length=1)
    repository: str | None = None
    change_summary: str = Field(min_length=1)
    old_value: Any = None
    new_value: Any = None
    observed_at: datetime
    source: str = Field(min_length=1)
    visibility_context: str = Field(min_length=1)
    dedupe_key: str = Field(min_length=1)
    read_status: str = "unread"
    ack_status: str = "pending"
    link: str | None = None


__all__ = ["PopType", "Pop"]

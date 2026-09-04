"""Shared envelope for canonical component adapters (v5 F-06/F-08)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComponentResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MOCK = "MOCK"
    PROXY = "PROXY"
    STAGING = "STAGING"
    UNKNOWN = "UNKNOWN"


class ComponentCallResult(BaseModel):
    """Adapter output; environment and source are never inferred by the UI."""

    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1)
    component_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    result_status: ComponentResultStatus
    source: str = Field(min_length=1)
    observed_at: datetime
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    output_data: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    external_link: str | None = None


__all__ = ["ComponentResultStatus", "ComponentCallResult"]

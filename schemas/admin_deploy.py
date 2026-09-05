"""Admin management-plane deployment contracts."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AdminDeployStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    STAGING = "STAGING"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"


class AdminDeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1)
    target: str = Field(min_length=1)
    manifest: dict = Field(default_factory=dict)
    request_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AdminDeployResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AdminDeployStatus
    artifact_ref: str
    record_hash: str | None = None
    deployment_id: str | None = None
    error: str | None = None


__all__ = ["AdminDeployStatus", "AdminDeployRequest", "AdminDeployResult"]

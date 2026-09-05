"""Server-issued identity context for a QuantCode session."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from schemas.groups import GroupId


class SessionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    group: GroupId
    role: Literal["analyst", "approver", "admin"]
    workspace_id: str = Field(min_length=1)
    workspace_path: str = Field(min_length=1)
    github_subject: str | None = None
    resource_scopes: list[str] = Field(default_factory=list)
    issued_at: datetime
    expires_at: datetime
    identity_source: Literal["ssh_roster"] = "ssh_roster"


__all__ = ["SessionContext"]

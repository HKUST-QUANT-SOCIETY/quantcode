"""Host-to-authority projection of an exact native merge/permission request."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

OpaqueID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class NativeGatePublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    request_id: OpaqueID
    root_session_id: OpaqueID
    session_id: OpaqueID
    message_id: OpaqueID
    call_id: OpaqueID
    server: str = Field(min_length=1, max_length=256)
    tool: str = Field(min_length=1, max_length=256)
    kind: Literal["merge", "permission"]
    resource: str = Field(min_length=1, max_length=2048)
    resource_version: str | None = Field(default=None, min_length=1, max_length=256)
    operation_digest: Digest
    catalog_digest: Digest
    arguments_json: str = Field(min_length=2, max_length=8192)
    arguments_digest: Digest
    description: str = Field(min_length=1, max_length=4096)
    expires_at: StrictInt


class NativeGateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    gate_id: Digest


class NativeGateDecision(NativeGateRead):
    expected_digest: Digest
    operation_digest: Digest
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2048)


class NativeGateCancel(NativeGateRead):
    expected_digest: Digest


class NativeGateList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 50
    cursor: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")

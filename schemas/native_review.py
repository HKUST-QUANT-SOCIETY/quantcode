"""Host-only authorization for reconciliation of existing native receipts."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.groups import GroupId
from schemas.native_gate import Digest, OpaqueID


class NativeReviewOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1, max_length=2048)
    group: GroupId
    role: Literal["analyst", "approver", "admin"]
    workspace_id: str = Field(min_length=1, max_length=2048)
    workspace_path: str = Field(min_length=1, max_length=4096)
    github_subject: str | None = Field(default=None, max_length=2048)
    resource_scopes: list[str] = Field(max_length=256)


class ReadScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["read"]
    resource: Literal["write_receipts", "budget", "execution_lock"]


class MutationScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_digest: Digest
    input_digest: Digest
    evidence_ref: str = Field(min_length=1, max_length=2000)
    note: str = Field(min_length=1, max_length=4000)


class WriteScope(MutationScope):
    kind: Literal["write_receipt"]
    source_session_id: OpaqueID
    message_id: str = Field(min_length=1, max_length=1024)
    call_id: str = Field(min_length=1, max_length=1024)
    expected_receipt_digest: Digest
    decision: Literal["confirmed_completed", "confirmed_not_executed"]


class UsageScope(MutationScope):
    kind: Literal["usage"]
    source_session_id: OpaqueID
    request_id: OpaqueID
    request_stopped: Literal[True]
    decision: Literal["usage_confirmed", "confirmed_not_executed"]


class LockScope(MutationScope):
    kind: Literal["execution_lock", "budget_lock"]
    processes_stopped: Literal[True]


class NativeReviewAuthorize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    session_id: OpaqueID
    root_session_id: OpaqueID
    owner: NativeReviewOwner
    scope: Annotated[ReadScope | WriteScope | UsageScope | LockScope, Field(discriminator="kind")]

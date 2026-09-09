"""Small native-session index records, with ownership supplied by the gateway."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, field_validator, model_validator

from schemas.native_gate import OpaqueID

NonNegativeInt = Annotated[StrictInt, Field(ge=0, le=9_007_199_254_740_991)]
Timestamp = NonNegativeInt
Cost = Annotated[FiniteFloat, Field(strict=True, ge=0)]
TaskStatus = Literal[
    "queued", "running", "completed", "cancelled", "error", "waiting_for_human",
    "stopped_budget", "paused", "unknown",
]
ArtifactKind = Literal["artifact", "report"]
ArtifactSource = Literal["attachment", "metadata"]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ArtifactID = Annotated[str, Field(pattern=r"^artifact_[a-f0-9]{64}$")]
CHUNK_BYTES = 64 * 1024


class NativeArtifact(BaseModel):
    """Immutable tool-result provenance; paths and inline content are excluded."""

    model_config = ConfigDict(extra="forbid")

    id: ArtifactID
    kind: ArtifactKind
    name: str | None = Field(default=None, min_length=1, max_length=256)
    mime: str = Field(min_length=1, max_length=256)
    bytes: NonNegativeInt | None = None
    sha256: Hash | None = None
    ref: str = Field(pattern=r"^(snapshot|unavailable):[a-f0-9]{64}$")
    source: ArtifactSource
    capture_status: Literal["available", "unavailable"]
    unavailable_reason: Literal["original_not_captured", "capture_failed", "invalid_content"] | None = None
    source_event_id: str = Field(min_length=1, max_length=256)
    source_event_seq: NonNegativeInt
    message_id: OpaqueID
    call_id: str = Field(min_length=1, max_length=512)
    result_digest: Hash

    @field_validator("name")
    @classmethod
    def plain_name(cls, value: str | None) -> str | None:
        if value is not None and (value in {".", ".."} or any(
            char in "/\\" or ord(char) < 32 or ord(char) == 127 for char in value
        )):
            raise ValueError("artifact names cannot contain paths or control characters")
        return value

    @model_validator(mode="after")
    def captured_bytes(self) -> NativeArtifact:
        if self.capture_status == "available":
            if self.bytes is None or self.sha256 is None or self.ref != f"snapshot:{self.sha256}" or self.unavailable_reason:
                raise ValueError("captured artifact requires an exact content hash and size")
        elif (self.bytes is not None or self.sha256 is not None or not self.unavailable_reason
              or self.ref != f"unavailable:{self.id.removeprefix('artifact_')}"):
            raise ValueError("unavailable artifact cannot claim captured content")
        return self


class NativeSolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=256)
    document_hash: str = Field(min_length=1, max_length=256)
    version: StrictInt = Field(gt=0)
    status: Literal["draft", "frozen", "superseded"]


class NativeKnowledgeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    group: str = Field(min_length=1, max_length=128)
    status: Literal["draft", "publishing", "promoted", "rejected", "superseded", "revoked"]
    digest: Hash
    tool_sequence: list[str] = Field(max_length=2000)


class NativeKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: OpaqueID
    session_id: OpaqueID
    source_revision: NonNegativeInt
    input_digest: Hash
    observed_at: str = Field(min_length=1, max_length=128)
    candidates: list[NativeKnowledgeCandidate] = Field(max_length=2000)


class NativeTaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: OpaqueID
    session_id: OpaqueID
    root_session_id: OpaqueID
    parent_session_id: OpaqueID | None = None
    source_revision: NonNegativeInt
    title: str = Field(min_length=1, max_length=1024)
    read_only: bool | None = None
    status: TaskStatus
    created_at: Timestamp
    updated_at: Timestamp
    model: str | None = Field(default=None, min_length=1, max_length=512)
    agent: str | None = Field(default=None, min_length=1, max_length=256)
    tokens_input: NonNegativeInt
    tokens_output: NonNegativeInt
    cost: Cost | None
    reserved_tokens: NonNegativeInt = 0
    unconfirmed_requests: NonNegativeInt = 0
    artifact_count: NonNegativeInt = 0
    artifacts: list[NativeArtifact] = Field(default_factory=list, max_length=32)
    artifact_manifest_hash: Hash
    solution: NativeSolution | None = None
    knowledge: NativeKnowledge | None = None
    last_error: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def valid_tree(self) -> NativeTaskSummary:
        if self.updated_at < self.created_at:
            raise ValueError("task update precedes task creation")
        if self.parent_session_id == self.session_id:
            raise ValueError("task cannot be its own parent")
        if (self.root_session_id == self.session_id) != (self.parent_session_id is None):
            raise ValueError("root task and parent relationship disagree")
        if not self.title.strip():
            raise ValueError("task title is required")
        if self.knowledge and (self.knowledge.source_id != self.source_id or self.knowledge.session_id != self.session_id
                               or self.knowledge.source_revision > self.source_revision):
            raise ValueError("knowledge candidate relation does not match the source task")
        if len(self.artifacts) > self.artifact_count or len({item.id for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("task artifact page disagrees with its manifest")
        if any(item.source_event_seq > self.source_revision for item in self.artifacts):
            raise ValueError("artifact event follows task revision")
        return self


class NativeTaskPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    task: NativeTaskSummary


class NativeTaskRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    source_id: OpaqueID
    session_id: OpaqueID


class NativeTaskList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_session_id: OpaqueID
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 50
    cursor: str | None = Field(default=None, min_length=1, max_length=1024)
    source_id: OpaqueID | None = None
    root_session_id: OpaqueID | None = None


class NativeArtifactQuery(NativeTaskRead):
    source_revision: NonNegativeInt


class NativeArtifactList(NativeArtifactQuery):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 32
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class NativeArtifactRead(NativeArtifactQuery):
    artifact_id: ArtifactID
    offset: NonNegativeInt = 0

    @field_validator("offset")
    @classmethod
    def aligned_offset(cls, value: int) -> int:
        if value % CHUNK_BYTES:
            raise ValueError("artifact chunk offset must be aligned")
        return value


class NativeArtifactPublish(NativeArtifactQuery):
    artifact: NativeArtifact
    offset: NonNegativeInt | None = None
    content: str | None = Field(default=None, max_length=4 * ((CHUNK_BYTES + 2) // 3))
    encoding: Literal["base64"] | None = None
    chunk_sha256: Hash | None = None

    @model_validator(mode="after")
    def valid_chunk(self) -> NativeArtifactPublish:
        fields = (self.offset, self.content, self.encoding, self.chunk_sha256)
        if all(item is None for item in fields):
            return self
        if any(item is None for item in fields) or self.artifact.capture_status != "available":
            raise ValueError("artifact chunks require captured content and complete chunk metadata")
        import base64
        import hashlib
        try:
            data = base64.b64decode(self.content, validate=True)
        except (ValueError, TypeError):
            raise ValueError("artifact base64 content is invalid") from None
        if base64.b64encode(data).decode("ascii") != self.content:
            raise ValueError("artifact content must use canonical base64")
        size = self.artifact.bytes
        if (self.offset % CHUNK_BYTES or self.offset > size or (self.offset == size and size != 0)
                or len(data) != min(CHUNK_BYTES, size - self.offset)):
            raise ValueError("artifact chunk offset or length disagrees with the original bytes")
        if hashlib.sha256(data).hexdigest() != self.chunk_sha256:
            raise ValueError("artifact chunk digest mismatch")
        return self

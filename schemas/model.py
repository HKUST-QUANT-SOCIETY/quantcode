"""QuantCode business schemas for the model group."""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelType(StrEnum):
    """Model family used for PR metadata and risk handoff."""

    LINEAR = "linear"
    TREE = "tree"
    BOOSTING = "boosting"
    NEURAL_NET = "neural_net"
    ENSEMBLE = "ensemble"
    OTHER = "other"


class ModelRiskMetadata(BaseModel):
    """Risk-relevant metadata supplied by the model group before risk review."""

    model_config = ConfigDict(
        extra="forbid",
        protected_namespaces=(),
        validate_assignment=True,
    )

    universe: str | None = Field(default=None, max_length=128)
    benchmark: str | None = Field(default=None, max_length=128)
    expected_holding_period_days: int | None = Field(default=None, ge=1)
    max_position_pct: float | None = Field(default=None, ge=0, le=1)
    uses_leverage: bool = False
    leverage_limit: float | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def _leverage_limit_matches_flag(self) -> "ModelRiskMetadata":
        if self.uses_leverage and self.leverage_limit is None:
            raise ValueError("leverage_limit is required when uses_leverage=True")
        if not self.uses_leverage and self.leverage_limit is not None:
            raise ValueError("leverage_limit requires uses_leverage=True")
        return self


class ModelSpec(BaseModel):
    """Model group PR metadata contract.

    This payload is embedded in the PR description and handed to risk-gate as
    the model group's structured claim about code, data range, dependencies,
    hyperparameters, and risk-relevant intent.
    """

    model_config = ConfigDict(
        extra="forbid",
        protected_namespaces=(),
        validate_assignment=True,
    )

    model_name: str = Field(min_length=1, max_length=128)
    model_type: ModelType
    owner: str | None = Field(default=None, max_length=64)
    code_path: str = Field(min_length=1, max_length=256)
    training_data_start: date
    training_data_end: date
    as_of_date: date
    hyperparameters: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )
    feature_dependencies: list[str] = Field(default_factory=list)
    operator_dependencies: list[str] = Field(default_factory=list)
    risk_metadata: ModelRiskMetadata = Field(default_factory=ModelRiskMetadata)
    pr_url: str | None = Field(default=None, max_length=512)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")

    @model_validator(mode="after")
    def _date_ordering(self) -> "ModelSpec":
        if self.training_data_start > self.training_data_end:
            raise ValueError("training_data_start must be <= training_data_end")
        if self.training_data_end > self.as_of_date:
            raise ValueError("training_data_end must be <= as_of_date")
        return self

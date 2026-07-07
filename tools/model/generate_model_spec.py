"""generate_model_spec tool — 校验并标准化 ModelSpec。"""
from __future__ import annotations

from pydantic import BaseModel

from schemas.model import ModelSpec
from tools.registry import ToolDef


class GenerateModelSpecArgs(BaseModel):
    metadata: dict


def generate_model_spec_execute(args: GenerateModelSpecArgs, ctx: dict) -> dict:
    """Validate metadata against the Day 1 ModelSpec Pydantic schema."""
    return ModelSpec.model_validate(args.metadata).model_dump(mode="json")


generate_model_spec_tool = ToolDef(
    id="generate_model_spec",
    description=(
        "Validate and normalize extracted metadata as schemas.model.ModelSpec. "
        "Returns the ModelSpec as a JSON-serializable dict."
    ),
    schema=GenerateModelSpecArgs,
    execute=generate_model_spec_execute,
)

__all__ = [
    "generate_model_spec_tool",
    "GenerateModelSpecArgs",
    "generate_model_spec_execute",
]

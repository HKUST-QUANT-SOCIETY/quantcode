"""extract_metadata tool — 从 PR markdown 中抽取 ModelSpec JSON。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

from tools.registry import ToolDef


class ExtractMetadataArgs(BaseModel):
    pr: dict[str, Any] | None = None
    body: str | None = None
    pr_path: str | None = None

    @model_validator(mode="after")
    def _has_source(self) -> "ExtractMetadataArgs":
        if (
            self.pr is None
            and self.body is None
            and self.pr_path is None
        ):
            raise ValueError("extract_metadata requires pr, body, or pr_path")
        return self


def _find_pr_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else None


def _body_from_args(args: ExtractMetadataArgs) -> tuple[str, str | None, str | None]:
    if args.pr:
        return (
            str(args.pr.get("body", "")),
            args.pr.get("pr_url"),
            args.pr.get("head_sha"),
        )
    if args.body is not None:
        return args.body, None, None
    if args.pr_path is not None:
        body = Path(args.pr_path).read_text(encoding="utf-8")
        return body, None, None
    raise ValueError("extract_metadata requires pr, body, or pr_path")


def _extract_first_json_object(text: str, *, marker: str = "ModelSpec") -> dict[str, Any]:
    start_at = text.lower().find(marker.lower())
    if start_at < 0:
        start_at = 0
    decoder = json.JSONDecoder()
    start = text.find("{", start_at)
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if not isinstance(obj, dict):
            raise ValueError("ModelSpec JSON block must be an object")
        return obj
    raise ValueError("Could not find a ModelSpec JSON object in the PR body")


def extract_metadata_execute(args: ExtractMetadataArgs, ctx: dict) -> dict:
    """Extract the first ModelSpec JSON object from PR markdown/text."""
    body, pr_url, head_sha = _body_from_args(args)
    metadata = _extract_first_json_object(body)
    detected_pr_url = pr_url or _find_pr_url(body)
    if detected_pr_url and not metadata.get("pr_url"):
        metadata["pr_url"] = detected_pr_url
    if head_sha and not metadata.get("commit_sha"):
        metadata["commit_sha"] = head_sha
    return metadata


extract_metadata_tool = ToolDef(
    id="extract_metadata",
    description=(
        "Extract ModelSpec metadata from PR markdown/read_pr output. "
        "Accepts {pr}, {body}, or {pr_path}; returns a ModelSpec-shaped dict."
    ),
    schema=ExtractMetadataArgs,
    execute=extract_metadata_execute,
)

__all__ = ["extract_metadata_tool", "ExtractMetadataArgs", "extract_metadata_execute"]

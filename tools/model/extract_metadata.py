"""extract_metadata tool — 从 PR diff 抽取 ticker / factor 元数据（mock 实现）。"""
from __future__ import annotations

from pydantic import BaseModel

from tools.registry import ToolDef


class ExtractMetadataArgs(BaseModel):
    diff: str


def extract_metadata_execute(args: ExtractMetadataArgs, ctx: dict) -> dict:
    """Mock 解析：从 diff 文本里按 ``TICKER:`` / ``FACTOR:`` 行提取元数据。

    实际实现将由 parser 子模块替换（Day 4）。
    """
    ticker = "UNKNOWN"
    factor_name = "unknown_factor"
    factor_type = "alpha"
    date_range = {"start": "2020-01-01", "end": "2024-12-31"}

    for line in args.diff.splitlines():
        stripped = line.strip()
        if stripped.startswith("TICKER:"):
            ticker = stripped.split(":", 1)[1].strip() or ticker
        elif stripped.startswith("FACTOR_NAME:"):
            factor_name = stripped.split(":", 1)[1].strip() or factor_name
        elif stripped.startswith("FACTOR_TYPE:"):
            factor_type = stripped.split(":", 1)[1].strip() or factor_type
        elif stripped.startswith("DATE_RANGE:"):
            value = stripped.split(":", 1)[1].strip()
            # 约定格式："YYYY-MM-DD..YYYY-MM-DD"
            if ".." in value:
                start, end = value.split("..", 1)
                date_range = {"start": start.strip(), "end": end.strip()}

    return {
        "ticker": ticker,
        "factor_name": factor_name,
        "factor_type": factor_type,
        "date_range": date_range,
    }


extract_metadata_tool = ToolDef(
    id="extract_metadata",
    description=(
        "Extract ticker / factor metadata from a PR diff. "
        "Returns {ticker, factor_name, factor_type, date_range}."
    ),
    schema=ExtractMetadataArgs,
    execute=extract_metadata_execute,
)

__all__ = ["extract_metadata_tool", "ExtractMetadataArgs", "extract_metadata_execute"]
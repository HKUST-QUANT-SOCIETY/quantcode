"""gen_schema stub tool — Day 4 尹一帆。

固定返回:给定因子想法 idea + match_main 输出,生成 FactorSpec dict。
后续 Lead 接真 LLM 时,只替换 _gen_schema_execute 函数体,schema / registry 不动。

字段契约见 docs/Day4/factor_tool_schema_proposal.md:
- idea:冗余字段(LLM 决策时更直观,不需要从 match_result 倒推)
- match_result:match_main tool 的完整输出 dict
- extra_context:可选透传
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef


class GenSchemaArgs(BaseModel):
    """gen_schema tool 的入参 schema。"""

    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048, description="因子想法描述(冗余字段,与 match_main 保持一致)")
    match_result: dict[str, Any] = Field(description="match_main tool 的完整输出")
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description="透传字段:Lead 接真 LLM 时可塞入额外上下文",
    )


def _gen_schema_execute(args: GenSchemaArgs, ctx: dict) -> dict[str, Any]:
    """stub: 固定返回 FactorSpec dict,后续接真 LLM 时替换此函数体。"""
    safe_name = args.idea.strip().replace(" ", "_").lower()[:32] or "unnamed_factor"
    return {
        "name": safe_name,
        "formula": "pb * roe",  # stub 硬编码
        "fields": args.match_result.get("suggested_fields", []),
        "rebalance": "quarterly",
    }


gen_schema_tool = ToolDef(
    id="gen_schema",
    description=(
        "Given a factor idea and the match_main result, generate a FactorSpec dict. "
        "Use this after match_main has confirmed compatibility."
    ),
    schema=GenSchemaArgs,
    execute=_gen_schema_execute,
)


__all__ = ["GenSchemaArgs", "gen_schema_tool"]

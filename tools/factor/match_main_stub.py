"""match_main stub tool — Day 4 尹一帆。

固定返回:给定因子想法 idea,返回主线匹配结果(兼容性 / 建议字段 / 备注)。
后续 Lead 接真 LLM 时,只替换 _match_main_execute 函数体,schema / registry 不动。

字段契约见 docs/Day4/factor_tool_schema_proposal.md:
- idea:必填,因子想法文本
- extra_context:可选透传(已有因子 / 主线签名 / 历史),stub 阶段不读
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef


class MatchMainArgs(BaseModel):
    """match_main tool 的入参 schema。"""

    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048, description="因子想法描述,如 'PB-ROE 因子,季度再平衡'")
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description="透传字段:Lead 接真 LLM 时可塞入已有因子列表 / 主线函数签名 / 历史等",
    )


def _match_main_execute(args: MatchMainArgs, ctx: dict) -> dict[str, Any]:
    """stub: 固定返回,后续接真 LLM 时替换此函数体。"""
    return {
        "compatible": True,
        "suggested_fields": ["pb", "roe", "quarterly_rebalance"],
        "notes": "Day 4 stub: 固定返回,Lead 接真 LLM 时替换此函数",
    }


match_main_tool = ToolDef(
    id="match_main",
    description=(
        "Given a factor idea (text), return matching mainline fields and a "
        "compatibility verdict. Use this as the first step before generating a FactorSpec."
    ),
    schema=MatchMainArgs,
    execute=_match_main_execute,
)


__all__ = ["MatchMainArgs", "match_main_tool"]

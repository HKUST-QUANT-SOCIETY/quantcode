"""autoeval stub tool — Day 4 尹一帆。

固定返回:给定 FactorSpec,返回 AutoEval 报告(ic / ir / t_stat / turnover 等)。
execute 直接 import 共享常量 flows.factor_autoeval.MOCK_AUTOEVAL_PAYLOAD_V1,
避免双维护(Lead 接真 AutoEval API 时只替换 flows.factor_autoeval._mock_autoeval_result,
本 stub 自动跟新)。

为什么 stub 不直接调 flows.factor_autoeval.call_autoeval_api(state):
- 那个函数签名是 (state: FactorFlowState) -> dict,接 state 不是 (args, ctx)
- ToolDef.execute 签名是 (args, ToolDef 校验后) -> Any,ctx 是 dict
- 签名不匹配,stub 阶段用共享常量解耦
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef

# 共享常量:与 flows/factor_autoeval.py 同步,避免双维护
from flows.factor_autoeval import MOCK_AUTOEVAL_PAYLOAD_V1


class AutoevalArgs(BaseModel):
    """autoeval tool 的入参 schema。

    注意:Day 4 阶段不加 extra_context(等 Lead 接真 AutoEval API 时如有需求再补)。
    理由:autoeval 是固定流程,字段稳定,过度预留反而可能让 schema 跟实际需求脱节。
    """

    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any] = Field(description="gen_schema 生成的 FactorSpec 序列化")


def _autoeval_execute(args: AutoevalArgs, ctx: dict) -> dict[str, Any]:
    """stub: 直接返回 MOCK_AUTOEVAL_PAYLOAD_V1 共享常量。

    Lead 接真 AutoEval API 时只需替换此函数体,调 autoeval_client.submit(args.spec) 即可,
    schema 不变,registry 不变,AgentRunner 不变。
    """
    return dict(MOCK_AUTOEVAL_PAYLOAD_V1)


autoeval_tool = ToolDef(
    id="autoeval",
    description=(
        "Submit a FactorSpec to AutoEval and return metrics (ic / ir / t_stat / turnover / etc). "
        "Use this after gen_schema has produced a valid FactorSpec."
    ),
    schema=AutoevalArgs,
    execute=_autoeval_execute,
)


__all__ = ["AutoevalArgs", "autoeval_tool"]

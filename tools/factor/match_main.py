"""match_main tool — Day 5 Lead 真LLM实现。

用LLM分析因子idea，推断需要的字段和兼容性。
保持与stub相同的schema，只替换_execute函数体。
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
    """真LLM实现：分析因子idea，推断需要的字段和兼容性。"""
    from runner.llm_provider import create_deepseek_llm

    # 构造prompt分析因子idea
    prompt = f"""分析以下因子想法，推断需要的数据字段和兼容性：

因子想法：{args.idea}

请分析：
1. 这个因子是否可以实现（compatible: true/false）
2. 需要哪些数据字段（suggested_fields: 如 ["pb", "roe", "market_cap"]）
3. 实现说明（notes）

常见金融字段参考：
- 估值类：pb, pe, ps, pcf, ev_ebitda
- 盈利类：roe, roa, gross_margin, net_margin
- 成长类：revenue_growth, earnings_growth, eps_growth
- 质量类：asset_turnover, inventory_turnover, debt_to_equity
- 动量类：return_1m, return_3m, return_6m, return_12m
- 波动类：volatility_20d, volatility_60d, beta
- 再平衡：quarterly_rebalance, monthly_rebalance, annual_rebalance

请以JSON格式返回：
{{
  "compatible": true/false,
  "suggested_fields": ["field1", "field2", ...],
  "notes": "简要说明"
}}"""

    try:
        llm = create_deepseek_llm()
        # 调用LLM
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=prompt)]
        response = llm.invoke(messages)

        # 解析LLM响应
        import json
        content = response.content if hasattr(response, 'content') else str(response)

        # 尝试从markdown代码块中提取JSON
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()

        result = json.loads(json_str)

        # 验证必需字段
        if "compatible" not in result:
            result["compatible"] = True
        if "suggested_fields" not in result:
            result["suggested_fields"] = []
        if "notes" not in result:
            result["notes"] = "LLM分析完成"

        return result

    except Exception as e:
        # 降级：返回兼容但空字段列表
        return {
            "compatible": True,
            "suggested_fields": [],
            "notes": f"LLM分析失败，降级返回: {str(e)}",
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

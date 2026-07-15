"""gen_schema tool — Day 5 Lead 真LLM实现。

用LLM根据因子idea和match_result动态生成FactorSpec。
保持与stub相同的schema，只替换_execute函数体。
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
    """真LLM实现：根据因子idea和match结果生成FactorSpec。"""
    import json
    import os

    # 简化实现：使用HTTP直接调用DeepSeek API（避免langchain_openai依赖）
    try:
        import requests

        # 从环境变量或config.json读取API配置
        api_key = os.environ.get('DEEPSEEK_API_KEY')
        base_url = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')
        model = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')

        if not api_key:
            # 尝试从config.json读取
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            config_path = os.path.join(project_root, 'config.json')

            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                api_key = config['llm']['api_key']
                base_url = config['llm'].get('base_url', base_url)
                model = config['llm'].get('model', model)

        if not api_key or api_key.startswith('sk-your-'):
            raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY env var or create config.json")

        # 构造prompt
        prompt = f"""根据因子想法和字段建议，生成完整的FactorSpec配置。

因子想法：{args.idea}

match_main分析结果：
- 兼容性：{args.match_result.get('compatible')}
- 建议字段：{args.match_result.get('suggested_fields', [])}
- 说明：{args.match_result.get('notes', '')}

请生成FactorSpec，包含：
1. name：因子名称（小写字母+下划线，如pb_roe_quarterly）
2. formula：计算公式（如 "pb * roe" 或 "momentum_20d / volatility_20d"）
3. fields：需要的数据字段列表（从suggested_fields选取）
4. rebalance：再平衡频率（quarterly/monthly/annual）
5. universe：股票池（默认"csi300"）
6. date_range：回测日期范围（默认{{"start": "2020-01-01", "end": "2023-12-31"}}）

请以JSON格式返回：
{{
  "name": "因子名称",
  "formula": "计算公式",
  "fields": ["field1", "field2"],
  "rebalance": "quarterly",
  "universe": "csi300",
  "date_range": {{"start": "2020-01-01", "end": "2023-12-31"}}
}}"""

        # 调用DeepSeek API
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
            },
            timeout=30,
        )

        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']

        # 解析JSON
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()

        spec = json.loads(json_str)

        # 验证必需字段
        required = ['name', 'formula', 'fields', 'rebalance']
        for field in required:
            if field not in spec:
                raise ValueError(f"Missing required field: {field}")

        # 设置默认值
        if 'universe' not in spec:
            spec['universe'] = 'csi300'
        if 'date_range' not in spec:
            spec['date_range'] = {'start': '2020-01-01', 'end': '2023-12-31'}

        return spec

    except Exception as e:
        # 降级：使用简单规则生成
        safe_name = args.idea.strip().replace(" ", "_").lower()[:32] or "unnamed_factor"

        # 从suggested_fields推断公式
        fields = args.match_result.get('suggested_fields', [])
        if len(fields) >= 2:
            formula = f"{fields[0]} * {fields[1]}"
        elif len(fields) == 1:
            formula = fields[0]
        else:
            formula = "value"

        return {
            "name": safe_name,
            "formula": formula,
            "fields": fields,
            "rebalance": "quarterly",
            "universe": "csi300",
            "date_range": {"start": "2020-01-01", "end": "2023-12-31"},
            "_fallback": True,
            "_error": str(e),
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

"""gen_schema tool — Day 5 Lead 真LLM实现 + FactorSpec 契约闭环。

用LLM根据因子idea和match_result动态生成FactorSpec。

契约保证（修 FactorSpec 契约）：
- schemas.factor.FactorSpec 是 extra="forbid"，必填字段为
  name / formula / operators(min 1 且唯一) / estimated_runtime_seconds(int>0) / date_range；
  forward_return_horizon 只允许 Literal[1,3,5,10,20]（默认 5）。
- 因此本 tool 的输出 **只含 FactorSpec 认识的字段**：
  旧版降级输出里的 ``_fallback``/``_error``/``fields``/``rebalance`` 键会让下游
  ``FactorSpec(**output)``（flows/factor_autoeval.validate_factor_spec 等）直接炸
  ValidationError，已移除；降级事实通过 logging.warning + 本 docstring 诚实标注，
  不再以非法键混进契约数据。
- 降级路径：operators 从 formula 粗提取（无 token 时用 ["mean"]）、
  estimated_runtime_seconds=60（schema 要求 int 且 >0）、
  forward_return_horizon=5（schema 允许字面量）、date_range 用默认窗口。
- LLM 路径：prompt 增加上述字段要求；解析后先用 pydantic 校验，
  ValidationError 时按 e.errors() 逐字段补默认值并重试，
  最终 FactorSpec(**output) 恒过（仍失败则回退规则版，规则版确定性可验证）。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from schemas.factor import FactorSpec
from tools.registry import ToolDef

logger = logging.getLogger(__name__)

# FactorSpec 允许的 forward_return_horizon 字面量（与 schemas.factor 保持一致）
_ALLOWED_HORIZONS = (1, 3, 5, 10, 20)
_DEFAULT_DATE_RANGE = {"start": "2020-01-01", "end": "2023-12-31"}
_DEFAULT_RUNTIME_SECONDS = 60  # schema 要求 int 且 >0
_DEFAULT_HORIZON = 5
_DEFAULT_UNIVERSE = "csi300"


class GenSchemaArgs(BaseModel):
    """gen_schema tool 的入参 schema。"""

    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048, description="因子想法描述(冗余字段,与 match_main 保持一致)")
    match_result: dict[str, Any] = Field(description="match_main tool 的完整输出")
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description="透传字段:Lead 接真 LLM 时可塞入额外上下文",
    )


def _safe_name(idea: str) -> str:
    return idea.strip().replace(" ", "_").lower()[:32] or "unnamed_factor"


def _rule_formula(match_result: dict[str, Any]) -> str:
    """从 suggested_fields 推导一个最小 formula。"""
    fields = match_result.get("suggested_fields", [])
    if len(fields) >= 2:
        return f"{fields[0]} * {fields[1]}"
    if len(fields) == 1:
        return str(fields[0])
    return "value"


def _coarse_operators(formula: str) -> list[str]:
    """从 formula 粗提取 operators（去重保序）；提取不到时用 ["mean"]。

    FactorSpec.operators 要求 min_length=1 且 strip 后唯一。
    """
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula or ""):
        if token not in tokens:
            tokens.append(token)
    return tokens or ["mean"]


def _rule_based_spec(args: GenSchemaArgs) -> dict[str, Any]:
    """降级路径：规则生成，保证 FactorSpec(**output) 通过。"""
    formula = _rule_formula(args.match_result)
    return {
        "name": _safe_name(args.idea),
        "formula": formula,
        "operators": _coarse_operators(formula),
        "estimated_runtime_seconds": _DEFAULT_RUNTIME_SECONDS,
        "date_range": dict(_DEFAULT_DATE_RANGE),
        "universe": _DEFAULT_UNIVERSE,
        "forward_return_horizon": _DEFAULT_HORIZON,
    }


def _patch_field(out: dict[str, Any], loc: tuple, args: GenSchemaArgs) -> None:
    """按 ValidationError 的单个 loc 补默认值。"""
    field = loc[0] if loc else None
    if field == "name":
        out["name"] = _safe_name(args.idea)
    elif field == "formula":
        out["formula"] = _rule_formula(args.match_result)
    elif field == "operators":
        out["operators"] = _coarse_operators(str(out.get("formula", "")))
    elif field == "estimated_runtime_seconds":
        out["estimated_runtime_seconds"] = _DEFAULT_RUNTIME_SECONDS
    elif field == "date_range":
        out["date_range"] = dict(_DEFAULT_DATE_RANGE)
    elif field == "forward_return_horizon":
        raw = out.get("forward_return_horizon")
        # LLM 可能返回 "3" 这类数字字符串，先尝试按字面量收编
        if isinstance(raw, str) and raw.strip().isdigit() and int(raw) in _ALLOWED_HORIZONS:
            out["forward_return_horizon"] = int(raw)
        else:
            out["forward_return_horizon"] = _DEFAULT_HORIZON
    elif field == "universe":
        out["universe"] = _DEFAULT_UNIVERSE
    elif field == "domain":
        out["domain"] = "equity"
    elif field == "frequency":
        out["frequency"] = "daily"
    elif field == "benchmark":
        out["benchmark"] = "HS300"
    elif field == "campaign_id":
        out.pop("campaign_id", None)  # Optional 字段，非法时直接去掉走 schema 默认
    else:
        key = field if isinstance(field, str) else None
        if key is not None:
            out.pop(key, None)  # 其他未知/非法键：丢弃走 schema 默认


def _validate_or_patch(spec: dict[str, Any], args: GenSchemaArgs) -> dict[str, Any]:
    """解析后用 pydantic 校验；ValidationError 时逐字段补默认值，保证恒过。"""
    # extra="forbid"：先丢掉 FactorSpec 不认识的键（如旧版 fields/rebalance）
    out = {k: v for k, v in spec.items() if k in FactorSpec.model_fields}
    for _ in range(3):
        try:
            FactorSpec(**out)
            return out
        except ValidationError as exc:
            seen: set[tuple] = set()
            for error in exc.errors():
                loc = tuple(error.get("loc", ()))
                if loc in seen:
                    continue
                seen.add(loc)
                _patch_field(out, loc, args)
    # 理论不可达（patch 均为确定性合法值）；保险起见回退规则版
    logger.warning("gen_schema: LLM spec still invalid after patching; using rule-based fallback")
    return _rule_based_spec(args)


def _llm_spec(args: GenSchemaArgs, api_key: str, base_url: str, model: str) -> dict[str, Any]:
    """真 LLM 路径：调用 API 并返回 FactorSpec 契约合法的 dict。"""
    import requests

    prompt = f"""根据因子想法和字段建议，生成 FactorSpec 配置。

因子想法：{args.idea}

match_main分析结果：
- 兼容性：{args.match_result.get('compatible')}
- 建议字段：{args.match_result.get('suggested_fields', [])}
- 说明：{args.match_result.get('notes', '')}

请生成FactorSpec，包含（字段名必须与 FactorSpec 契约一致）：
1. name：因子名称（小写字母+下划线，如 pb_roe_quarterly）
2. formula：计算公式（如 "pb * roe" 或 "momentum_20d / volatility_20d"）
3. operators：公式涉及的数据字段/算子列表（非空且不重复，从 formula 提取，如 ["pb", "roe"]）
4. estimated_runtime_seconds：单次评估预计运行秒数（正整数，如 60）
5. universe：股票池（默认 "csi300"）
6. date_range：回测日期范围（默认 {{"start": "2020-01-01", "end": "2023-12-31"}}）
7. forward_return_horizon：前瞻收益窗口（只能取 1/3/5/10/20 之一，默认 5）

请以JSON格式返回：
{{
  "name": "因子名称",
  "formula": "计算公式",
  "operators": ["field_or_op1", "field_or_op2"],
  "estimated_runtime_seconds": 60,
  "universe": "csi300",
  "date_range": {{"start": "2020-01-01", "end": "2023-12-31"}},
  "forward_return_horizon": 5
}}"""

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

    if "```json" in content:
        json_str = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        json_str = content.split("```")[1].split("```")[0].strip()
    else:
        json_str = content.strip()

    import json

    spec = json.loads(json_str)
    if not isinstance(spec, dict):
        raise ValueError("LLM response is not a JSON object")
    return _validate_or_patch(spec, args)


def _gen_schema_execute(args: GenSchemaArgs, ctx: dict) -> dict[str, Any]:
    """真LLM实现：根据因子idea和match结果生成FactorSpec（契约合法 dict）。"""
    import json
    import os

    try:
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

        return _llm_spec(args, api_key, base_url, model)

    except Exception as e:
        # 降级：规则生成（诚实标注：打日志，不再往契约 dict 里塞 _fallback 非法键）
        logger.warning("gen_schema: LLM unavailable (%s); using rule-based FactorSpec", e)
        return _rule_based_spec(args)


gen_schema_tool = ToolDef(
    id="gen_schema",
    description=(
        "Given a factor idea and the match_main result, generate a FactorSpec dict "
        "that always validates against schemas.factor.FactorSpec "
        "(FactorSpec(**output) must pass). "
        "Use this after match_main has confirmed compatibility."
    ),
    schema=GenSchemaArgs,
    execute=_gen_schema_execute,
)


__all__ = ["GenSchemaArgs", "gen_schema_tool"]

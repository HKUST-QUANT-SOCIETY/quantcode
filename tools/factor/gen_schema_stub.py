"""gen_schema prototype tool — dynamic schema code + stable stub contract.

Day 4 keeps the current ToolDef contract (id="gen_schema") and enriches the
stub with the Lead Day 3 prototype: generate Pydantic code, exec-validate it,
and return JSON-serializable schema metadata. Real LLM generation can later swap
out _gen_schema_execute without changing registry/MCP callers.
"""
from __future__ import annotations

import re
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


def _safe_name(idea: str) -> str:
    return idea.strip().replace(" ", "_").lower()[:32] or "unnamed_factor"


def _idea_to_class_name(idea: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", idea)
    base = "".join(t.capitalize() for t in tokens) if tokens else "Custom"
    return f"{base}FactorSpec"


def _schema_code(idea: str, class_name: str, operators: list[str]) -> str:
    op_literal = str(operators) if operators else "[]"
    return f'''from pydantic import BaseModel, Field, field_validator


class {class_name}(BaseModel):
    """动态生成的因子 schema — idea: {idea}"""

    window: int = Field(description="回看窗口(交易日)", ge=1, le=500)
    universe: str = Field(description="标的池", default="CSI1000")
    numerator: str = Field(description="分子字段", default="market_cap")
    denominator: str = Field(description="分母字段", default="book_value")
    operators: list[str] = Field(default_factory=lambda: {op_literal})

    @field_validator("window")
    @classmethod
    def _window_min(cls, v: int) -> int:
        if v < 2:
            raise ValueError("window 太短(<2),因子无统计意义")
        return v
'''


def _pick_formula(match_result: dict[str, Any]) -> str:
    ops = match_result.get("suggested_operators") or []
    if "fundamental_ratio" in ops:
        return "pb * roe"
    if ops:
        return " -> ".join(str(op) for op in ops)
    return "custom_factor_expression"


def _gen_schema_execute(args: GenSchemaArgs, ctx: dict) -> dict[str, Any]:
    """Prototype: generate dynamic schema metadata while preserving old keys."""
    operators = args.match_result.get("suggested_operators") or args.match_result.get("suggested_fields") or []
    class_name = _idea_to_class_name(args.idea)
    code = _schema_code(args.idea, class_name, list(operators))

    namespace: dict[str, Any] = {}
    try:
        exec(code, namespace)  # noqa: S102 - isolated prototype validation
        generated_cls = namespace[class_name]
        json_schema = generated_cls.model_json_schema()
        valid = True
        error = None
    except Exception as exc:  # pragma: no cover - exercised in tests via valid path
        json_schema = {}
        valid = False
        error = f"{type(exc).__name__}: {exc}"

    return {
        # old contract keys (keep AgentRunner/tests stable)
        "name": _safe_name(args.idea),
        "formula": _pick_formula(args.match_result),
        "fields": list(operators),
        "rebalance": "quarterly",
        # prototype upgrade keys
        "class_name": class_name,
        "schema_code": code,
        "json_schema": json_schema,
        "valid": valid,
        "error": error,
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

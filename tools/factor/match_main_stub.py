"""match_main tool — fixture-backed mainline compatibility prototype.

Day 4 keeps the current ToolDef contract (id="match_main") and replaces the
constant stub body with a tiny fixture mainline. Real LLM/RAG mainline matching
can swap out _match_main_execute later without changing registry/MCP callers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "factor_mainline"
    / "operators.py"
)


def _load_mainline_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the small factor-mainline fixture without making tests a package."""
    spec = importlib.util.spec_from_file_location("factor_mainline_operators", _FIXTURE_PATH)
    if spec is None or spec.loader is None:
        return {}, {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "OPERATORS", {}), getattr(module, "COMPATIBILITY_RULES", {})


class MatchMainArgs(BaseModel):
    """match_main tool 的入参 schema。"""

    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048, description="因子想法描述,如 'PB-ROE 因子,季度再平衡'")
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description="透传字段:Lead 接真 LLM 时可塞入已有因子列表 / 主线函数签名 / 历史等",
    )


def _new_operator_hint(idea: str) -> str:
    idea_lower = idea.lower()
    if "比值" in idea or "ratio" in idea_lower or "/" in idea:
        return "divide_fundamental"
    if "窗口" in idea or "均值" in idea or "mean" in idea_lower:
        return "custom_ts_aggregation"
    return "custom_operator"


def _rule_fields(rule: dict[str, Any], operators: list[str]) -> list[str]:
    fields: list[str] = []
    for key in ("numerator", "denominator", "window"):
        if key in rule:
            fields.append(str(rule[key]))
    return fields or operators


def _match_main_execute(args: MatchMainArgs, ctx: dict) -> dict[str, Any]:
    """Prototype: match an idea against a fixture operator/rule mainline."""
    operators, rules = _load_mainline_fixture()
    idea_lower = args.idea.lower()

    for keyword, rule in rules.items():
        if keyword.lower() in idea_lower:
            suggested_operators = list(rule.get("operators", []))
            reason = f"'{args.idea}' matched mainline rule '{keyword}'"
            return {
                "compatible": True,
                "suggested_fields": _rule_fields(rule, suggested_operators),
                "notes": reason,
                "suggested_operators": suggested_operators,
                "need_new_operator": False,
                "new_operator_hint": None,
                "reason": reason,
            }

    mentioned = [op_name for op_name in operators if op_name.lower() in idea_lower]
    if mentioned:
        reason = f"idea directly mentioned mainline operators {mentioned}"
        return {
            "compatible": True,
            "suggested_fields": mentioned,
            "notes": reason,
            "suggested_operators": mentioned,
            "need_new_operator": False,
            "new_operator_hint": None,
            "reason": reason,
        }

    hint = _new_operator_hint(args.idea)
    reason = f"'{args.idea}' did not match fixture mainline rules or known operators"
    return {
        "compatible": False,
        "suggested_fields": [],
        "notes": reason,
        "suggested_operators": [],
        "need_new_operator": True,
        "new_operator_hint": hint,
        "reason": reason,
    }


match_main_tool = ToolDef(
    id="match_main",
    description=(
        "Given a factor idea (text), return matching mainline fields/operators and a "
        "compatibility verdict. Use this as the first step before generating a FactorSpec."
    ),
    schema=MatchMainArgs,
    execute=_match_main_execute,
)


__all__ = ["MatchMainArgs", "match_main_tool"]

"""Register market (qsdata) group tools to the global registry.

风格对齐 tools/risk/_register.py：ToolDef + register_tool；核心实现放
backing.py（纯函数，便于测试直调）。
P-01 工具签名见 specs/data/SPEC.md §2.4。
调用 ``import tools.market._register`` 即完成注册。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from tools.market import backing
from tools.registry import ToolDef, register_tool


class ListFactorsArgs(BaseModel):
    pool_filter: dict[str, Any] | None = Field(
        default=None,
        description="Exact-match filter over selected_pool.csv columns, "
        "e.g. {\"family\": \"lqtp_1014\"}",
    )
    backend: str | None = Field(
        default=None, description="Data backend override (default: QS_DATA_BACKEND or staging)"
    )


class LoadFactorPanelArgs(BaseModel):
    factor_id: str = Field(min_length=1, description="factor_name in selected_pool.csv")
    year_start: int
    year_end: int
    as_of: datetime = Field(description="PIT cutoff; rows with calc_time > as_of are dropped")
    backend: str | None = None
    blackboard_db_path: str | None = Field(
        default=None, description="Optional BlackboardService db override (tests)"
    )
    write_to_blackboard: bool = Field(
        default=True, description="Write contract JSON to shared.datasets.panel/{factor_id}"
    )


class LoadReturnsArgs(BaseModel):
    name: str = Field(min_length=1)
    date_start: date
    date_end: date
    backend: str | None = None


class PoolBrowseArgs(BaseModel):
    factor_id: str | None = None
    family: str | None = None
    backend: str | None = None


def _list_factors_execute(args: ListFactorsArgs, ctx: dict) -> dict[str, Any]:
    return backing.list_factors_impl(args.pool_filter, backend=args.backend)


def _load_factor_panel_execute(args: LoadFactorPanelArgs, ctx: dict) -> dict[str, Any]:
    result = backing.load_factor_panel_impl(
        args.factor_id, args.year_start, args.year_end, args.as_of, backend=args.backend
    )
    if "error" in result:
        return result
    summary = result["summary"]
    if args.write_to_blackboard:
        # 诚实署名（audit #18）：ctx 未提供 task_id 时写 T0.<thread_hash>
        # 占位（T0 = 未分配任务，可追溯，不冒充真实 ComposeTask），
        # 不再用 "T1.00000000"/"model" 假身份兜底。
        from tools.model.write_blackboard import _synthesize_task_id

        task_id = str(ctx.get("task_id") or "") or _synthesize_task_id(
            str(ctx.get("thread_id") or ctx.get("session_id") or "default-thread")
        )
        group = str(ctx.get("group") or "factor")
        written = backing.write_panel_to_blackboard(
            result["panel"],
            blackboard_db_path=ctx.get("blackboard_db_path") or args.blackboard_db_path,
            written_by_task_id=task_id,
            written_by_group=group,
        )
        summary["blackboard_key"] = written["blackboard_key"]
        summary["blackboard_version"] = written["entry"]["version"]
        summary["written_by_task_id"] = task_id
    # SPEC §2.3：返回只含 key+摘要+统计，大矩阵（panel.values）不进返回值。
    return summary


def _load_returns_execute(args: LoadReturnsArgs, ctx: dict) -> dict[str, Any]:
    return backing.load_returns_impl(
        args.name, args.date_start, args.date_end, backend=args.backend
    )


def _pool_browse_execute(args: PoolBrowseArgs, ctx: dict) -> dict[str, Any]:
    return backing.pool_browse_impl(args.factor_id, args.family, backend=args.backend)


list_factors_tool = ToolDef(
    id="list_factors",
    description=(
        "List factors in the qs-cold selected pool (247 admitted factors) with family "
        "distribution. Read-only local staging files; no network."
    ),
    schema=ListFactorsArgs,
    execute=_list_factors_execute,
)

load_factor_panel_tool = ToolDef(
    id="load_factor_panel",
    description=(
        "Load one factor's cross-section panel from qs-cold staging: drops is_valid==0 "
        "rows, PIT-filters calc_time <= as_of, writes contract JSON to Blackboard key "
        "shared.datasets.panel/{factor_id}. Returns key + summary + stats only."
    ),
    schema=LoadFactorPanelArgs,
    execute=_load_factor_panel_execute,
)

load_returns_tool = ToolDef(
    id="load_returns",
    description=(
        "Load a ReturnsDataset for a date window. First version: qs-cold staging has no "
        "A-share returns table, so this returns a no_source error object until the "
        "quote-table backend lands (SPEC §5)."
    ),
    schema=LoadReturnsArgs,
    execute=_load_returns_execute,
)

pool_browse_tool = ToolDef(
    id="pool_browse",
    description=(
        "Browse qs-cold pool metadata (factor formula, family, rank_ic, direction) "
        "optionally filtered by factor_id or family. Read-only."
    ),
    schema=PoolBrowseArgs,
    execute=_pool_browse_execute,
)

register_tool(list_factors_tool)
register_tool(load_factor_panel_tool)
register_tool(load_returns_tool)
register_tool(pool_browse_tool)

__all__ = [
    "list_factors_tool",
    "load_factor_panel_tool",
    "load_returns_tool",
    "pool_browse_tool",
]
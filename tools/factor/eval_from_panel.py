"""eval_from_panel 工具 — 真实数据因子评估（FactorPanel → 真实 IC 报告）。

封装 flows.factor_eval_real.evaluate_factor_panel：从 Blackboard
``shared.datasets.panel/{factor_id}`` 读 FactorPanel 契约 JSON（读出方
model_validate，背书走 tools/market/backing.read_panel_from_blackboard），
算真实 rank IC / 换手率 / 5 分层 / 多空差，写
artifacts/factor/{name}-report-real.json，返回 summary（不含大矩阵）。

配 panel 数据时优先本工具而非 autoeval（autoeval 走外部 AutoEval 服务或
mock 降级）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef


class EvalFromPanelArgs(BaseModel):
    """eval_from_panel 输入。"""

    model_config = ConfigDict(extra="forbid")

    panel_key: str = Field(
        min_length=1,
        description=(
            "Blackboard dataset key, e.g. shared.datasets.panel/<factor_id> "
            "(FactorPanel contract from load_factor_panel)."
        ),
    )
    factor_name: str | None = Field(
        default=None,
        description="Optional display name; defaults to panel.factor_id.",
    )
    date_range: list[str] | None = Field(
        default=None,
        description="Optional [start, end] (inclusive ISO dates) to trim the panel before eval.",
    )
    blackboard_db_path: str | None = Field(
        default=None, description="Optional Blackboard sqlite path override (tests)."
    )


_EVAL_NOTES = (
    "Evaluate a FactorPanel from Blackboard shared.datasets.panel/* with REAL "
    "statistics (spearman rank IC / turnover / 5-quantile layers / long-short). "
    "Proxy returns are next-day factor-value changes (factor momentum) — qs-cold "
    "has no returns table yet, so results carry a proxy_return_warning and are "
    "not for pool admission. Prefer this over autoeval when panel data exists. "
    "Writes artifacts/factor/{name}-report-real.json."
)


def _trim_panel(panel: Any, date_range: list[str] | None) -> Any:
    if not date_range:
        return panel
    from datetime import date as _date

    start = _date.fromisoformat(str(date_range[0]))
    end = _date.fromisoformat(str(date_range[1]))
    keep = [i for i, d in enumerate(panel.dates) if start <= d <= end]
    if not keep:
        raise ValueError(f"date_range {date_range} selects no rows in panel")
    panel = panel.model_copy(
        update={
            "dates": [panel.dates[i] for i in keep],
            "values": [panel.values[i] for i in keep],
        }
    )
    return panel


def eval_from_panel_impl(
    panel_key: str,
    *,
    factor_name: str | None = None,
    date_range: list[str] | None = None,
    blackboard_db_path: str | None = None,
) -> dict[str, Any]:
    """核心实现（tests 与 ToolDef 共用；错误以 error 对象返回，不抛崩溃）。"""
    from flows.factor_eval_real import evaluate_factor_panel
    from tools.market.backing import staging_error

    try:
        from pydantic import ValidationError

        from runner.blackboard import BlackboardService
        from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
        from schemas import BlackboardScope
        from tools.market.backing import validate_dataset_payload

        service = BlackboardService(
            db_path=Path(blackboard_db_path) if blackboard_db_path else None,
            session_id=PROJECT_SESSION_ID,
            requester_group=None,
        )
        entry = service.get_entry(BlackboardScope.PROJECT, None, make_read_key(panel_key))
        if entry is None:
            return staging_error(
                "panel_not_found", detail=f"blackboard entry not found: {panel_key}",
                panel_key=panel_key,
            )
        # D1-A10：读出方强制 _contract 戳校验（read_panel_from_blackboard 只做
        # model_validate，contract 字段有默认值会吞掉缺戳，这里需显式校验）
        try:
            panel = validate_dataset_payload(entry.value)
        except (ValidationError, TypeError) as e:
            return staging_error(
                "panel_contract_invalid",
                detail=f"{type(e).__name__}: {e}", panel_key=panel_key,
            )
    except Exception as e:
        return staging_error(
            "panel_read_failed", detail=f"{type(e).__name__}: {e}", panel_key=panel_key
        )

    try:
        panel = _trim_panel(panel, date_range)
    except (ValueError, TypeError) as e:
        return staging_error("bad_date_range", detail=str(e), date_range=date_range)

    result = evaluate_factor_panel(panel)
    if "error" in result:
        return {**result, "panel_key": panel_key}
    if factor_name:
        result["report"]["factor_name"] = factor_name
        result["report"]["eval_run_id"] = f"{factor_name}-{result['engine']}"
    # summary 只回统计与工件路径，values 矩阵不进返回值（SPEC §2.3）
    return {
        "panel_key": panel_key,
        "engine": result["engine"],
        "summary": result["report"],
        "acceptance": result["acceptance"],
        "artifacts": result["artifacts"],
        "proxy_return_warning": result["proxy_return_warning"],
    }


def _eval_from_panel_execute(args: EvalFromPanelArgs, ctx: dict) -> dict[str, Any]:
    return eval_from_panel_impl(
        args.panel_key,
        factor_name=args.factor_name,
        date_range=args.date_range,
        blackboard_db_path=ctx.get("blackboard_db_path") or args.blackboard_db_path,
    )


eval_from_panel_tool = ToolDef(
    id="eval_from_panel",
    description=_EVAL_NOTES,
    schema=EvalFromPanelArgs,
    execute=_eval_from_panel_execute,
)

__all__ = ["EvalFromPanelArgs", "eval_from_panel_impl", "eval_from_panel_tool"]
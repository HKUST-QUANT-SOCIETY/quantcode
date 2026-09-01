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


# ---------------------------------------------------------------------------
# eval_factor_panel — dataset_key + IR 阈值口径的任务签名版
# ---------------------------------------------------------------------------


class EvalFactorPanelArgs(BaseModel):
    """eval_factor_panel 输入（P-01 任务签名：dataset_key + ic_abs_threshold）。"""

    model_config = ConfigDict(extra="forbid")

    dataset_key: str = Field(
        min_length=1,
        description=(
            "Blackboard dataset key of a FactorPanel, e.g. "
            "shared.datasets.panel/<factor_id>; a bare factor id is accepted "
            "and expanded to that namespace."
        ),
    )
    ic_abs_threshold: float = Field(
        default=0.03,
        description=(
            "Acceptance gate on |ic_mean| (engine-level pre-check, aligned with "
            "configs/acceptance.factor.yaml ic_abs_min)."
        ),
    )
    date_range: list[str] | None = Field(
        default=None,
        description="Optional [start, end] (inclusive ISO dates) to trim the panel before eval.",
    )
    blackboard_db_path: str | None = Field(
        default=None, description="Optional Blackboard sqlite path override (tests)."
    )


def _normalize_dataset_key(key: str) -> str:
    """裸因子 id → shared.datasets.panel/<id>（已含 / 的完整 key 原样透传）。"""
    return key if "/" in key else f"shared.datasets.panel/{key}"


def eval_factor_panel_impl(
    dataset_key: str,
    ic_abs_threshold: float = 0.03,
    *,
    date_range: list[str] | None = None,
    blackboard_db_path: str | None = None,
) -> dict[str, Any]:
    """核心实现（tests 与 ToolDef 共用；错误以 error 对象返回，不抛崩溃）。

    读路径复用 eval_from_panel_impl（背书 tools/market/backing），在此之上
    增加 |ic_mean| >= ic_abs_threshold 的 acceptance 复核与 key+摘要返回
    （SPEC §2.3：大矩阵不进返回值）。
    """
    result = eval_from_panel_impl(
        _normalize_dataset_key(dataset_key),
        date_range=date_range,
        blackboard_db_path=blackboard_db_path,
    )
    if "error" in result:
        result.setdefault("dataset_key", dataset_key)
        return result

    summary = result["summary"]
    ic_mean = float(summary.get("ic_metrics", {}).get("ic_mean", 0.0))
    ic_pass = abs(ic_mean) >= ic_abs_threshold
    if not ic_pass:
        summary["fail_reasons"] = list(summary.get("fail_reasons", [])) + [
            f"|ic_mean| {abs(ic_mean):.4f} < ic_abs_threshold {ic_abs_threshold}"
        ]
        summary["verdict"] = "fail"
        result["acceptance"] = {
            "verdict": "fail",
            "checks": result["acceptance"]["checks"]
            + [
                {
                    "name": "ic_abs_threshold",
                    "passed": False,
                    "message": f"|ic_mean| >= {ic_abs_threshold}",
                }
            ],
        }

    return {
        "dataset_key": _normalize_dataset_key(dataset_key),
        "factor_id": summary.get("factor_name"),
        "engine": result["engine"],
        "ic": {
            "ic_mean": ic_mean,
            "ir": float(summary.get("ic_metrics", {}).get("ir", 0.0)),
        },
        "turnover_monthly": float(summary.get("turnover", {}).get("monthly", 0.0)),
        "verdict": summary.get("verdict"),
        "fail_reasons": summary.get("fail_reasons", []),
        "acceptance": result["acceptance"],
        "summary": summary,
        "artifacts": result["artifacts"],
        "proxy_return_warning": result["proxy_return_warning"],
        "note": (
            "|ic_mean| gate: engine verdict uses configs/acceptance.factor.yaml; "
            "ic_abs_threshold here re-checks the caller-supplied bar (default 0.03 "
            "= yaml ic_abs_min). Proxy returns are factor momentum, not real PnL."
        ),
    }


def _eval_factor_panel_execute(args: EvalFactorPanelArgs, ctx: dict) -> dict[str, Any]:
    return eval_factor_panel_impl(
        args.dataset_key,
        args.ic_abs_threshold,
        date_range=args.date_range,
        blackboard_db_path=ctx.get("blackboard_db_path") or args.blackboard_db_path,
    )


eval_factor_panel_tool = ToolDef(
    id="eval_factor_panel",
    description=(
        "Evaluate a FactorPanel dataset (Blackboard shared.datasets.panel/*) with "
        "real cross-sectional statistics: spearman rank IC series -> IC mean/IR, "
        "monthly turnover (top-decile Jaccard), 5-quantile layered proxy returns. "
        "Acceptance = configs/acceptance.factor.yaml thresholds re-checked against "
        "the caller-supplied ic_abs_threshold (default 0.03). Proxy returns are "
        "next-day factor-value changes (momentum), NOT real PnL — flagged in every "
        "result via proxy_return_warning. Writes artifacts/factor/{name}-report-real.json."
    ),
    schema=EvalFactorPanelArgs,
    execute=_eval_factor_panel_execute,
)

__all__ = [
    "EvalFactorPanelArgs",
    "EvalFromPanelArgs",
    "eval_factor_panel_impl",
    "eval_factor_panel_tool",
    "eval_from_panel_impl",
    "eval_from_panel_tool",
]
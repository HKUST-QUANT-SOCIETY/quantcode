"""validate_factor_contract + merge_to_main — 因子验收闸门与主线登记（PRD §4.1.3 / F-06）。

两个 ToolDef 共一文件（PRD 承诺的两个能力，合并闭环的最后一环）：

- validate_factor_contract(report)：FactorReport dict 逐项校验（verdict==pass +
  |ic_mean|/ir/t_stat/turnover 阈值，阈值缺省走 runner.acceptance.factor_thresholds()
  即 configs/acceptance.factor.yaml 单源）。纯判定，零 LLM，零状态写入。
- merge_to_main(factor_id, report)：gate 通过 → HumanGate interrupt（复用
  runner.human_gate 的 interrupt/resume 机制，approve 不可由 LLM 自批——
  human_approved 只能经 ctx 或 graph resume 注入，不在 ToolDef 参数里）→
  写主线登记簿 .quantcode/mainline/factors.json。

qs-cold 模式：主线登记是文件系统清单（JSON），非 git 操作。
# ponytail: 写 .quantcode/mainline/factors.json 索引 + copy 报告工件即可；
真实 git merge 升级路径 = match_main 侧 Server A 主线库（SSH，见 P0-7）。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef


# ---------------------------------------------------------------------------
# 配置（configs/factor_main.yaml 单源，代码默认兜底）
# ---------------------------------------------------------------------------

_DEFAULT_MAINLINE_INDEX = ".quantcode/mainline/factors.json"


def _main_config() -> dict[str, Any]:
    """主线登记配置：mainline_index 路径 + require_human 开关。"""
    from runner.config_loader import load_yaml

    cfg = load_yaml("factor_main", strict=True)
    return {
        "mainline_index": cfg.get("mainline_index", _DEFAULT_MAINLINE_INDEX),
        "require_human": bool(cfg.get("require_human", True)),
    }


def _index_path(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    return Path(_main_config()["mainline_index"])


# ---------------------------------------------------------------------------
# A. validate_factor_contract：纯判定
# ---------------------------------------------------------------------------


def validate_factor_contract_impl(
    report: dict[str, Any], thresholds: dict[str, Any] | None = None
) -> dict[str, Any]:
    """FactorReport dict → {eligible, reasons, verdict}。不写任何状态。

    缺失字段（factor_name / ic_metrics.* / turnover.monthly）→ reasons；
    数值判定复用 runner.acceptance.run_acceptance("factor:evaluation") 与
    验收 yaml 单源；verdict 必须 == "pass"（marginal 也不放行）。
    """
    if not isinstance(report, dict):
        return {"eligible": False, "reasons": ["report is not a dict"], "verdict": None}

    verdict = report.get("verdict")
    reasons: list[str] = []

    for key in ("factor_name", "ic_metrics", "turnover"):
        if report.get(key) in (None, {}, []):
            reasons.append(f"missing field: {key}")

    ic = report.get("ic_metrics") or {}
    numeric_ok = True
    for key in ("ic_mean", "ir", "t_stat"):
        v = ic.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            reasons.append(f"missing field: ic_metrics.{key}")
            numeric_ok = False
    monthly = (report.get("turnover") or {}).get("monthly")
    if isinstance(monthly, bool) or not isinstance(monthly, (int, float)):
        reasons.append("missing field: turnover.monthly")
        numeric_ok = False

    if verdict != "pass":
        reasons.append(f"verdict is {verdict!r}, need 'pass'")

    # 数值阈值：字段齐时复用验收单源（yaml 优先），零双维护
    if numeric_ok:
        from runner.acceptance import run_acceptance

        acc = run_acceptance(
            "factor:evaluation",
            {"ic_metrics": ic, "turnover": report.get("turnover")},
            thresholds,
        )
        reasons.extend(c.message for c in acc.checks if not c.passed)

    return {"eligible": not reasons, "reasons": reasons, "verdict": verdict}


# ---------------------------------------------------------------------------
# B. merge_to_main：gate → HumanGate → 主线登记
# ---------------------------------------------------------------------------


def _code_hash(factor_id: str, report: dict[str, Any]) -> str:
    """因子内容稳定指纹（幂等键）：显式 report['code_hash'] 优先，否则
    sha256(factor_id + formula + eval_run_id)。"""
    explicit = report.get("code_hash")
    if explicit:
        return str(explicit)
    src = json.dumps(
        {
            "factor_id": factor_id,
            "formula": str(report.get("formula") or report.get("factor_name", "")),
            "eval_run_id": report.get("eval_run_id"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def _build_record(
    factor_id: str, report: dict[str, Any], report_path: str | None
) -> dict[str, Any]:
    name = str(report.get("factor_name") or factor_id)
    return {
        "factor_id": factor_id,
        "factor_name": name,
        "merged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rank_ic": (report.get("ic_metrics") or {}).get("ic_mean"),
        "formula": report.get("formula"),
        "code_hash": report.get("code_hash") or _code_hash(factor_id, report),
        "report_path": report_path
        or f"artifacts/factor/{name}-report-real.json",
    }


def merge_to_main_impl(
    factor_id: str,
    report: dict[str, Any],
    *,
    human_approved: bool = False,
    dry_run: bool = False,
    thresholds: dict[str, Any] | None = None,
    index_path: str | Path | None = None,
    report_path: str | None = None,
    thread_id: str = "",
    evidence_dir: str | Path | None = None,
    actor_id: str = "approver",
    gate_id: str | None = None,
) -> dict[str, Any]:
    """合入主线登记簿：gate 不合格拒绝；合格未人审只出 gate（waiting_for_human）；
    人审通过（或 require_human=false）才写 .quantcode/mainline/factors.json。

    幂等：同 code_hash 已登记 → {merged: True, already: True}，不重复写。
    dry_run=True 只返回将写入的记录，不落盘、不触发 gate。
    """
    if dry_run:
        gate = validate_factor_contract_impl(report, thresholds)
        return {
            "merged": False,
            "stage": "dry_run",
            "dry_run": True,
            "record": _build_record(factor_id, report, report_path),
            "gate": gate,
        }

    gate = validate_factor_contract_impl(report, thresholds)
    if not gate["eligible"]:
        return {
            "merged": False,
            "stage": "gate_rejected",
            "eligible": False,
            "verdict": gate["verdict"],
            "reasons": gate["reasons"],
            "gate_id": None,
        }

    cfg = _main_config()
    if cfg["require_human"] and not human_approved:
        from runner.human_gate import build_interrupt_payload, make_gate_id

        gate_id = make_gate_id(thread_id or "factor-merge")
        metrics = {k: v for k, v in gate.items() if k in ("verdict", "reasons")}
        metrics["factor_id"] = factor_id
        metrics["factor_name"] = report.get("factor_name")
        ic = report.get("ic_metrics") or {}
        metrics["ic_mean"] = ic.get("ic_mean")
        metrics["ir"] = ic.get("ir")
        payload = build_interrupt_payload(
            gate_id=gate_id,
            kind="merge",
            resource=f"factor:{factor_id}",
            evidence=metrics,
            reasons=gate["reasons"],
            message=f"⏸️ HumanGate(kind=merge): 合入主线待审批 — {factor_id}",
        )
        return {
            "merged": False,
            "stage": "waiting_for_human",
            "gate_id": gate_id,
            "gate": payload,
            "interrupt_payload": payload,
        }

    path = _index_path(index_path)
    record = _build_record(factor_id, report, report_path)
    entries: list[dict[str, Any]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = loaded
        except (ValueError, TypeError):
            entries = []
    if any(e.get("code_hash") == record["code_hash"] for e in entries):
        existing = next(e for e in entries if e.get("code_hash") == record["code_hash"])
        return {
            "merged": True,
            "already": True,
            "stage": "already_merged",
            "record": existing,
            "index_path": str(path),
        }
    from runner.evidence import append_event
    from runner.human_gate import make_gate_id

    decision_gate_id = gate_id or make_gate_id(thread_id or f"factor-merge-{factor_id}")
    evidence = {
        "factor_id": factor_id,
        "resource": f"factor:{factor_id}",
        "record": record,
    }

    append_event(
        thread_id or f"factor-merge-{factor_id}",
        "human_gate",
        {
            "gate_id": decision_gate_id,
            "kind": "merge",
            "status": "approved",
            "actor": actor_id,
            "resource": f"factor:{factor_id}",
            "evidence": evidence,
            "decision": {
                "action": "approve",
                "decided_by": actor_id,
                "reason": None,
            },
        },
        evidence_dir or (path.parent / ".evidence"),
        required=True,
    )
    entries.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "merged": True,
        "already": False,
        "stage": "merged",
        "record": record,
        "index_path": str(path),
    }


# ---------------------------------------------------------------------------
# ToolDef：human_approved 不进参数（防 LLM 自批），只能 ctx / graph resume 注入
# ---------------------------------------------------------------------------


class ValidateFactorContractArgs(BaseModel):
    """validate_factor_contract 输入。"""

    model_config = ConfigDict(extra="forbid")

    report: dict[str, Any] = Field(
        description="FactorReport dict (quant_evaluator / eval_from_panel summary output)."
    )


class MergeMainArgs(BaseModel):
    """merge_to_main 输入。

    ⚠️ 无 human_approved 参数：批准只能走 HumanGate（graph resume approve），
    LLM 无法通过改参数自批。
    """

    model_config = ConfigDict(extra="forbid")

    factor_id: str = Field(min_length=1, description="Stable factor id for the mainline record.")
    report: dict[str, Any] = Field(
        description="FactorReport dict from quant_evaluator / eval_from_panel summary."
    )
    dry_run: bool = Field(
        default=False,
        description="True → 只返回将写入的登记记录，不落盘、不触发 HumanGate。",
    )


def _validate_factor_contract_execute(args: ValidateFactorContractArgs, ctx: dict) -> dict[str, Any]:
    return validate_factor_contract_impl(args.report, thresholds=ctx.get("thresholds"))


def _merge_execute(args: MergeMainArgs, ctx: dict) -> dict[str, Any]:
    result = merge_to_main_impl(
        args.factor_id,
        args.report,
        human_approved=bool(ctx.get("human_approved")),
        dry_run=args.dry_run,
        thresholds=ctx.get("thresholds"),
        index_path=ctx.get("mainline_index"),
        report_path=ctx.get("report_path"),
        thread_id=str(ctx.get("thread_id") or ""),
        evidence_dir=ctx.get("evidence_dir"),
        actor_id=str(ctx.get("actor_id") or "approver"),
    )
    if result.get("stage") != "waiting_for_human" or args.dry_run:
        return result
    # 不在 LangGraph runnable 里（直接 registry.call）→ 返回 gate 结果即可
    try:
        from langgraph.config import get_config

        get_config()
    except Exception:
        return result
    # 图内 → 真 HumanGate interrupt（复用 request_human_review 的 resume 协议）
    from langgraph.types import interrupt

    from runner.human_gate import normalize_external_decision, parse_resume_decision

    resume_value = interrupt(result["interrupt_payload"])
    if normalize_external_decision(parse_resume_decision(resume_value) or "") == "approve":
        return merge_to_main_impl(
            args.factor_id,
            args.report,
            human_approved=True,
            dry_run=False,
            thresholds=ctx.get("thresholds"),
            index_path=ctx.get("mainline_index"),
            report_path=ctx.get("report_path"),
            thread_id=str(ctx.get("thread_id") or ""),
            evidence_dir=ctx.get("evidence_dir"),
            actor_id=str(ctx.get("actor_id") or "approver"),
            gate_id=str(result.get("gate_id") or "") or None,
        )
    from runner.evidence import append_event
    decision_evidence_dir = ctx.get("evidence_dir")
    if decision_evidence_dir is None:
        decision_evidence_dir = _index_path(ctx.get("mainline_index")).parent / ".evidence"

    append_event(
        str(ctx.get("thread_id") or f"factor-merge-{args.factor_id}"),
        "human_gate",
        {
            "gate_id": result.get("gate_id"),
            "kind": "merge",
            "status": "rejected",
            "actor": str(ctx.get("actor_id") or "approver"),
            "resource": f"factor:{args.factor_id}",
            "evidence": result.get("gate", {}).get("evidence", {}),
            "decision": {
                "action": "reject",
                "decided_by": str(ctx.get("actor_id") or "approver"),
                "reason": "rejected by human gate",
            },
        },
        decision_evidence_dir,
        required=True,
    )
    return {
        "merged": False,
        "stage": "human_rejected",
        "factor_id": args.factor_id,
        "gate_id": result.get("gate_id"),
    }


validate_factor_contract_tool = ToolDef(
    id="validate_factor_contract",
    description=(
        "Check whether a FactorReport passes the merge gate: verdict must be 'pass' "
        "and |ic_mean|/ir/t_stat/turnover must meet configs/acceptance.factor.yaml "
        "thresholds. Pure check, no side effects. Returns {eligible, reasons, verdict}."
    ),
    schema=ValidateFactorContractArgs,
    execute=_validate_factor_contract_execute,
)

merge_to_main_tool = ToolDef(
    id="merge_to_main",
    description=(
        "Merge a factor into the mainline registry (.quantcode/mainline/factors.json). "
        "Runs validate_factor_contract first; eligible factors pause at a HumanGate "
        "(kind=merge) until a human approves, then the record is written. "
        "dry_run=True previews the record without writes. Idempotent by code_hash."
    ),
    schema=MergeMainArgs,
    execute=_merge_execute,
)


__all__ = [
    "ValidateFactorContractArgs",
    "MergeMainArgs",
    "validate_factor_contract_impl",
    "validate_factor_contract_tool",
    "merge_to_main_impl",
    "merge_to_main_tool",
]

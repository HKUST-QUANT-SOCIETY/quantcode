"""ABReport 契约与比较核 — FUNCTIONAL P-05。

- ABReport: TypedDict schemas 层契约（baseline_id / challenger_id /
  dataset_snapshot_hash / metrics 比较 / verdict / fail_reasons / artifacts…）。
- compare_metrics(): 逐指标比较（challenger strictly> 才算 better；turnover 例外，
  低者更好），delta = challenger - base。
- build_ab_report(): 组装报告并把违规原因并进来（fail_reasons）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict


class MetricComparison(TypedDict):
    metric: str
    base: float
    chall: float
    delta: float
    better: str  # "challenger" | "baseline" | "tie"


class ABReport(TypedDict):
    exp_id: str
    baseline_id: str
    challenger_id: str
    dataset_key: str
    dataset_snapshot_hash: str
    oos_range: dict[str, str] | None
    metrics: list[MetricComparison]
    verdict: str  # "challenger" | "baseline" | "tie"
    fail_reasons: list[str]
    artifacts: list[str]
    created_at: str


# 参与比较的指标名（与 evaluate_factor_panel report 键对齐）。
COMPARABLE_METRICS = ("ic_mean", "ir", "t_stat", "turnover")
# turnover 数值越低越好，其余 strictly> 为 challenger 更优。
LOWER_IS_BETTER = frozenset({"turnover"})


def _extract_metric(report: dict[str, Any], name: str) -> float:
    """从 evaluate_factor_panel report dict 里取指标（ic_mean/ir/t_stat 在
    ic_metrics 下，turnover 在 turnover.monthly 下）。缺失 → ValueError。"""
    if name == "turnover":
        v = report.get("turnover", {}).get("monthly")
    else:
        v = report.get("ic_metrics", {}).get(name)
    if v is None:
        raise ValueError(f"metric '{name}' missing in evaluation report")
    return float(v)


def compare_metrics(
    base_report: dict[str, Any], chall_report: dict[str, Any]
) -> list[MetricComparison]:
    """逐指标比较：challenger strictly 占优于 challenger，否则 baseline，
    恰好相等 → tie。delta = chall - base（turnover 越低越好 → 直接差可比）。"""
    out: list[MetricComparison] = []
    for name in COMPARABLE_METRICS:
        base, chall = _extract_metric(base_report, name), _extract_metric(chall_report, name)
        delta = chall - base
        if chall > base:
            better = "challenger"
        elif chall < base:
            better = "baseline"
        else:
            better = "tie"
        if name in LOWER_IS_BETTER and better != "tie":
            better = "baseline" if better == "challenger" else "challenger"
        out.append(
            {"metric": name, "base": base, "chall": chall,
             "delta": delta, "better": better}
        )
    return out


def verdict_from_metrics(metrics: list[MetricComparison]) -> str:
    """全部指标 challenger 更优（better=='challenger'）→ challenger；
    全部 baseline 更优 → baseline；混合/全 tie → tie。"""
    betters = {m["better"] for m in metrics}
    if betters == {"challenger"}:
        return "challenger"
    if betters == {"baseline"}:
        return "baseline"
    return "tie"


def snapshot_hash(payload: Any) -> str:
    """payload 的 sha256 十六进制（dataset_snapshot_hash，稳定 JSON 序列化）。"""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def build_ab_report(
    *,
    exp_id: str,
    baseline_id: str,
    challenger_id: str,
    dataset_key: str,
    dataset_snapshot_hash: str,
    oos_range: dict[str, str] | None,
    base_report: dict[str, Any],
    chall_report: dict[str, Any],
    fail_reasons: list[str],
    artifacts: list[str],
    created_at: str,
) -> ABReport:
    """比较 + 装配 ABReport。fail_reasons 非空时 verdict 强制 "tie" 且进报告
    （oos_discipline 违规不能写成 challenger 胜出）。"""
    comparisons = compare_metrics(base_report, chall_report)
    verdict = verdict_from_metrics(comparisons)
    if fail_reasons:
        verdict = "tie"
    return {
        "exp_id": exp_id,
        "baseline_id": baseline_id,
        "challenger_id": challenger_id,
        "dataset_key": dataset_key,
        "dataset_snapshot_hash": dataset_snapshot_hash,
        "oos_range": oos_range,
        "metrics": comparisons,
        "verdict": verdict,
        "fail_reasons": list(fail_reasons),
        "artifacts": list(artifacts),
        "created_at": created_at,
    }


__all__ = [
    "ABReport",
    "MetricComparison",
    "COMPARABLE_METRICS",
    "compare_metrics",
    "verdict_from_metrics",
    "snapshot_hash",
    "build_ab_report",
]
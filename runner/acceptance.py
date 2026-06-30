"""Acceptance runner: 跑预设阈值校验，返回 pass / fail。

约定：
- 阈值放在 `pipelines/<skill>/config.yaml`，由 owner 维护
- 本模块只负责"读 payload + 读阈值 + 跑 check + 出 verdict"
- 不做副作用（写 PR 评论 / 发邮件由调用方处理，必须 @dedupe_within）

Owner: T0 / 用户（Lead）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""


@dataclass
class AcceptanceResult:
    verdict: str  # "pass" | "fail"
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _check_risk_gate(payload: dict[str, Any], thresholds: dict[str, Any]) -> list[CheckResult]:
    """RiskProfile 验收：max_drawdown / position_limit / correlation / VaR"""
    max_dd = thresholds.get("max_drawdown", 0.20)
    pos_limit = thresholds.get("position_limit", 0.30)
    corr_limit = thresholds.get("correlation_limit", 0.60)
    return [
        CheckResult(
            name="max_drawdown",
            passed=payload.get("max_drawdown", 1.0) <= max_dd,
            message=f"max_drawdown <= {max_dd}",
        ),
        CheckResult(
            name="position_limit",
            passed=payload.get("position_limit", 1.0) <= pos_limit,
            message=f"position_limit <= {pos_limit}",
        ),
        CheckResult(
            name="correlation",
            passed=abs(payload.get("correlation_with_existing", 1.0)) <= corr_limit,
            message=f"|correlation| <= {corr_limit}",
        ),
        CheckResult(
            name="var_99_present",
            passed=payload.get("tail_risk_var_99") is not None,
            message="tail_risk_var_99 not null",
        ),
    ]


def _check_factor_eval(payload: dict[str, Any], thresholds: dict[str, Any]) -> list[CheckResult]:
    """FactorReport 验收：IC / IR / 换手 / t_stat"""
    ic = payload.get("ic_metrics", {})
    ic_min = thresholds.get("ic_abs_min", 0.03)
    ir_min = thresholds.get("ir_min", 0.5)
    turnover_max = thresholds.get("turnover_monthly_max", 0.8)
    tstat_min = thresholds.get("t_stat_min", 2.0)
    return [
        CheckResult(
            name="ic_mean",
            passed=abs(ic.get("ic_mean", 0.0)) >= ic_min,
            message=f"|ic_mean| >= {ic_min}",
        ),
        CheckResult(
            name="ir",
            passed=ic.get("ir", 0.0) >= ir_min,
            message=f"ir >= {ir_min}",
        ),
        CheckResult(
            name="turnover",
            passed=payload.get("turnover", {}).get("monthly", 1.0) <= turnover_max,
            message=f"turnover_monthly <= {turnover_max}",
        ),
        CheckResult(
            name="t_stat",
            passed=ic.get("t_stat", 0.0) >= tstat_min,
            message=f"t_stat >= {tstat_min}",
        ),
    ]


def _check_pit_rag(payload: dict[str, Any], thresholds: dict[str, Any]) -> list[CheckResult]:
    """PITResult 验收：所有文档 published_at <= as_of_date"""
    as_of = thresholds.get("as_of_date") or payload.get("as_of_date")
    docs = payload.get("documents", [])
    leaked = [d["id"] for d in docs if as_of and d.get("published_at", "") > as_of]
    return [CheckResult(
        name="no_lookahead",
        passed=len(leaked) == 0,
        message=f"as_of={as_of}; leaked_docs={leaked}" if leaked else "all docs <= as_of_date",
    )]


def _check_research_pdf(payload: dict[str, Any], thresholds: dict[str, Any]) -> list[CheckResult]:
    """research-pdf 验收：渲染成功 + 章节非空 + 引用数"""
    min_citations = thresholds.get("min_citations", 10)
    required = thresholds.get(
        "required_sections",
        ["overview", "business", "financials", "valuation", "risks"],
    )
    sections = set(payload.get("sections_generated", []))
    return [
        CheckResult(
            name="pdf_rendered",
            passed=bool(payload.get("pdf_path")),
            message="pdf_path present",
        ),
        CheckResult(
            name="sections_complete",
            passed=set(required).issubset(sections),
            message=f"required {required} ⊆ generated",
        ),
        CheckResult(
            name="citations",
            passed=payload.get("citations_count", 0) >= min_citations,
            message=f"citations >= {min_citations}",
        ),
    ]


_DISPATCH: dict[str, Callable[[dict[str, Any], dict[str, Any]], list[CheckResult]]] = {
    "risk-gate": _check_risk_gate,
    "factor-eval": _check_factor_eval,
    "factor:autoeval": _check_factor_eval,
    "pit-rag": _check_pit_rag,
    "research-pdf": _check_research_pdf,
}


def run_acceptance(
    skill: str,
    payload: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
) -> AcceptanceResult:
    """根据 skill 类型跑对应阈值校验。

    Args:
        skill: 已注册 skill 名（见 _DISPATCH）
        payload: skill 输出的 JSON
        thresholds: 阈值字典，缺省时每个 check 取默认值

    Returns:
        AcceptanceResult with verdict and per-check results
    """
    thresholds = thresholds or {}
    fn = _DISPATCH.get(skill)
    if fn is None:
        return AcceptanceResult(
            verdict="fail",
            checks=[CheckResult(name="unknown_skill", passed=False, message=f"skill={skill}")],
        )
    checks = fn(payload, thresholds)
    verdict = "pass" if all(c.passed for c in checks) else "fail"
    return AcceptanceResult(verdict=verdict, checks=checks)

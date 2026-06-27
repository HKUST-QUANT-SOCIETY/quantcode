"""Acceptance runner: 跑预设阈值校验，返回 pass / fail。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""


@dataclass
class AcceptanceResult:
    verdict: str  # "pass" | "fail"
    checks: list[CheckResult]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


# TODO: T0 owner 实现具体校验逻辑
def run_acceptance(skill: str, payload: dict[str, Any], thresholds: dict[str, Any]) -> AcceptanceResult:
    """根据 skill 类型跑对应阈值校验。

    Args:
        skill: 'risk-gate' / 'factor-eval' / 'research-pdf' / 'pit-rag'
        payload: skill 输出的 JSON
        thresholds: 来自 pipelines/<skill>/config.yaml 的阈值字典

    Returns:
        AcceptanceResult with verdict and per-check results
    """
    raise NotImplementedError("T0 owner 实现，参考 schemas/<skill>.schema.json 的字段定义")

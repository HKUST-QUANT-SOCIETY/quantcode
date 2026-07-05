"""Risk group tools — read / calc / profile / gate / comment."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from schemas.risk_profile import RiskProfile, RiskThresholds
from tools.risk.statistics_stub import calc_risk_stub
from tools.utils.dedupe import dedupe_within

_SCENARIO = Literal["normal", "high_risk"]
_STUB_EXTRA_FIELDS = frozenset({"volatility", "position_limit_usage", "thresholds"})
_DEDUPE_SECONDS = 300
_DEDUPED_WRITERS: dict[str, Callable[..., dict[str, str]]] = {}


def read_blackboard(input_data: dict[str, Any]) -> dict[str, Any]:
    """读取 model_spec（Day3：input_data 或 blackboard 嵌套）。"""
    if "model_spec" in input_data:
        return {"model_spec": input_data["model_spec"]}

    blackboard = input_data.get("blackboard")
    if isinstance(blackboard, dict) and "model_spec" in blackboard:
        return {"model_spec": blackboard["model_spec"]}

    raise KeyError(
        "model_spec not found in input_data['model_spec'] "
        "or input_data['blackboard']['model_spec']"
    )


def calc_risk(model_spec: dict[str, Any], scenario: str = "normal") -> dict[str, Any]:
    """调用 statistics_stub 计算风控指标。"""
    if scenario not in ("normal", "high_risk"):
        raise ValueError(f"Unknown scenario: {scenario!r}")

    metrics = calc_risk_stub(scenario)  # type: ignore[arg-type]
    if model_name := model_spec.get("model_name"):
        metrics["strategy_id"] = model_name
    return metrics


def generate_risk_profile(
    model_spec: dict[str, Any],
    risk_metrics: dict[str, Any],
    pr_url: str | None = None,
) -> RiskProfile:
    """将 stub 输出转为 RiskProfile。"""
    payload = {
        key: value
        for key, value in risk_metrics.items()
        if key not in _STUB_EXTRA_FIELDS
    }
    if model_name := model_spec.get("model_name"):
        payload["strategy_id"] = model_name
    if pr_url is not None:
        payload["pr_url"] = pr_url
    return RiskProfile(**payload)


def check_gate(profile: RiskProfile, thresholds: RiskThresholds) -> dict[str, Any]:
    """检查是否需人工审批，返回 requires_human 与 reasons。"""
    reasons = profile.breached_thresholds(thresholds)
    return {
        "requires_human": bool(reasons),
        "reasons": reasons,
    }


def _profile_hash(profile: RiskProfile) -> str:
    """Stable hash for dedupe keys."""
    return hashlib.sha256(profile.model_dump_json().encode()).hexdigest()


def _pr_comment_dedupe_key(
    profile: RiskProfile,
    *,
    pr_url: str,
    pr_number: str,
    head_sha: str,
    artifacts_root: str | Path = "artifacts/risk/pr-comments",
    dedupe_db_path: str | Path | None = None,
) -> str:
    return f"pr_comment:{pr_url}:{head_sha}:{_profile_hash(profile)}"


def _write_pr_comment_impl(
    profile: RiskProfile,
    *,
    pr_url: str,
    pr_number: str,
    head_sha: str,
    artifacts_root: str | Path = "artifacts/risk/pr-comments",
    dedupe_db_path: str | Path | None = None,
) -> dict[str, str]:
    """写入 PR comment artifact（不调用 GitHub API）。"""
    root = Path(artifacts_root)
    root.mkdir(parents=True, exist_ok=True)

    comment_id = f"comment-{pr_number}-{head_sha[:7]}"
    artifact_path = root / f"pr-{pr_number}-{head_sha[:7]}.json"
    payload = {
        "comment_id": comment_id,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "risk_profile": profile.model_dump(mode="json"),
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "comment_id": comment_id,
        "artifact_path": artifact_path.as_posix(),
    }


def _dedupe_writer_cache_key(db_path: str | Path | None) -> str:
    if db_path is None:
        return "__default__"
    return str(Path(db_path).resolve())


def _get_deduped_writer(db_path: str | Path | None = None) -> Callable[..., dict[str, str]]:
    cache_key = _dedupe_writer_cache_key(db_path)
    writer = _DEDUPED_WRITERS.get(cache_key)
    if writer is None:
        writer = dedupe_within(
            seconds=_DEDUPE_SECONDS,
            key=_pr_comment_dedupe_key,
            db_path=db_path,
        )(_write_pr_comment_impl)
        _DEDUPED_WRITERS[cache_key] = writer
    return writer


def clear_write_pr_comment_dedupe_cache() -> None:
    """Clear cached dedupe writers (tests only)."""
    _DEDUPED_WRITERS.clear()


def write_pr_comment(
    profile: RiskProfile,
    *,
    pr_number: str,
    head_sha: str,
    pr_url: str | None = None,
    artifacts_root: str | Path = "artifacts/risk/pr-comments",
    dedupe_db_path: str | Path | None = None,
) -> dict[str, str]:
    """写入 PR comment artifact；同 pr_url + head_sha + profile 去重。"""
    resolved_url = pr_url or profile.pr_url
    if not resolved_url:
        raise ValueError("pr_url must be provided or set on profile")

    writer = _get_deduped_writer(dedupe_db_path)
    return writer(
        profile,
        pr_url=resolved_url,
        pr_number=pr_number,
        head_sha=head_sha,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db_path,
    )

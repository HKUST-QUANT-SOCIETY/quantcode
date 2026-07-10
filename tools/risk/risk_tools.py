"""Risk group tools — read / calc / profile / gate / comment."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from schemas import BlackboardScope, ModelSpec
from schemas.risk_profile import RiskProfile, RiskThresholds
from tools.github_comments import find_existing_comment, github_request, post_pr_comment
from tools.risk.statistics_stub import calc_risk_stub
from tools.utils.dedupe import dedupe_within

_SCENARIO = Literal["normal", "high_risk"]
_STUB_EXTRA_FIELDS = frozenset({"volatility", "position_limit_usage", "thresholds"})
_DEDUPE_SECONDS = 300
_DEDUPED_WRITERS: dict[str, Callable[..., dict[str, Any]]] = {}


def read_blackboard(input_data: dict[str, Any]) -> dict[str, Any]:
    """读取 ModelSpec。

    生产路径：通过 BlackboardService 从 PROJECT scope 读取（PR #18 接口）。
    test/demo fallback：input_data[\"model_spec\"] 或嵌套 blackboard（非生产路径）。
    """
    blackboard_key = input_data.get("blackboard_key", "model_spec")
    project_id = input_data.get("project_id")
    blackboard_db_path = input_data.get("blackboard_db_path")

    if project_id is not None or blackboard_db_path is not None:
        from runner.blackboard import BlackboardService, DEFAULT_SESSION_ID

        service = BlackboardService(
            db_path=blackboard_db_path,
            session_id=project_id or DEFAULT_SESSION_ID,
            requester_group="risk",
        )
        entry = service.get_entry(BlackboardScope.PROJECT, None, blackboard_key)
        if entry is not None:
            value = entry.value
            if isinstance(value, dict) and "model_spec" in value:
                return {"model_spec": value["model_spec"]}
            return {"model_spec": value}

    # test/demo fallback — not the production path
    if "model_spec" in input_data:
        return {"model_spec": input_data["model_spec"]}

    blackboard = input_data.get("blackboard")
    if isinstance(blackboard, dict) and "model_spec" in blackboard:
        return {"model_spec": blackboard["model_spec"]}

    raise KeyError(
        "model_spec not found: set project_id/blackboard_db_path for BlackboardService, "
        "or provide input_data['model_spec'] / input_data['blackboard']['model_spec'] "
        "(test/demo fallback only)"
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
    """检查是否需人工审批，返回 requires_human / reasons / risk_profile。

    Day 4: route_gate_node 会直接消费这个结果构造 HumanGate interrupt payload，
    所以这里把 risk_profile 一并带回，避免 gate node 再倒推上游状态。
    """
    reasons = profile.breached_thresholds(thresholds)
    return {
        "requires_human": bool(reasons),
        "reasons": reasons,
        "risk_profile": profile.model_dump(mode="json"),
    }


def _profile_hash(profile: RiskProfile) -> str:
    return hashlib.sha256(profile.model_dump_json().encode()).hexdigest()


def _pr_comment_dedupe_key(
    profile: RiskProfile,
    *,
    pr_url: str,
    pr_number: str,
    head_sha: str,
    artifacts_root: str | Path = "artifacts/risk/pr-comments",
    dedupe_db_path: str | Path | None = None,
    github_repo: str | None = None,
    github_token: str | None = None,
    post_to_github: bool | None = None,
) -> str:
    return f"pr_comment:{pr_url}:{head_sha}:{_profile_hash(profile)}"


def _risk_comment_marker(head_sha: str, profile: RiskProfile) -> str:
    return f"<!-- quantcode:risk-gate:profile:{head_sha}:{_profile_hash(profile)} -->"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _status(ok: bool) -> str:
    return "PASS" if ok else "NEEDS REVIEW"


def format_risk_comment(
    profile: RiskProfile,
    *,
    pr_number: str,
    head_sha: str,
) -> str:
    """生成 QuantCode Risk Gate Report Markdown（含 dedupe marker）。"""
    thresholds = RiskThresholds()
    breaches = set(profile.breached_thresholds(thresholds))
    verdict = profile.evaluate_verdict(thresholds)
    marker = _risk_comment_marker(head_sha, profile)
    rows = [
        (
            "Max drawdown",
            _pct(profile.max_drawdown),
            f"<= {_pct(thresholds.max_drawdown)}",
            _status("max_drawdown" not in breaches),
        ),
        (
            "Position limit",
            _pct(profile.position_limit),
            f"<= {_pct(thresholds.position_limit_usage)}",
            _status("position_limit" not in breaches),
        ),
        (
            "Tail VaR 99",
            _pct(profile.tail_risk_var_99),
            f"<= {_pct(thresholds.tail_risk_var_99)}",
            _status("tail_risk_var_99" not in breaches),
        ),
        (
            "Correlation",
            f"{profile.correlation_with_existing:.2f}",
            f"abs <= {thresholds.correlation_limit:.2f}",
            _status("correlation_with_existing" not in breaches),
        ),
    ]
    table = "\n".join(f"| {name} | {value} | {limit} | {status} |" for name, value, limit, status in rows)
    breached_text = ", ".join(sorted(breaches)) if breaches else "None"
    return f"""## QuantCode Risk Gate Report

**Verdict:** `{verdict}`  
**Strategy:** `{profile.strategy_id}`  
**PR:** #{pr_number}  
**Head SHA:** `{head_sha}`  
**As of:** `{profile.as_of_date}`

| Metric | Value | Limit | Status |
|---|---:|---:|---|
{table}

**Breached thresholds:** {breached_text}

<details>
<summary>RiskProfile JSON</summary>

```json
{profile.model_dump_json(indent=2)}
```

</details>

{marker}
"""


def _post_github_risk_comment(
    profile: RiskProfile,
    *,
    repo: str,
    pr_number: str,
    head_sha: str,
    token: str,
) -> dict[str, str]:
    marker = _risk_comment_marker(head_sha, profile)
    body = format_risk_comment(profile, pr_number=pr_number, head_sha=head_sha)
    # body already contains marker at the end
    existing = find_existing_comment(repo, pr_number, token, marker)
    if existing is not None:
        return {
            "github_comment_id": str(existing.get("id", "")),
            "github_comment_url": str(existing.get("html_url", "")),
            "deduped_by": "github_comment_marker",
        }

    created = github_request(
        "POST",
        repo,
        f"/issues/{pr_number}/comments",
        token,
        {"body": body},
    )
    return {
        "github_comment_id": str(created.get("id", "")),
        "github_comment_url": str(created.get("html_url", "")),
    }


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _should_post_to_github(post_to_github: bool | None) -> bool:
    if post_to_github is not None:
        return post_to_github
    return _env_flag_enabled("QUANTCODE_POST_RISK_COMMENT")


def _dedupe_writer_cache_key(db_path: str | Path | None) -> str:
    if db_path is None:
        return "__default__"
    return str(Path(db_path).resolve())


def _write_pr_comment_impl(
    profile: RiskProfile,
    *,
    pr_url: str,
    pr_number: str,
    head_sha: str,
    artifacts_root: str | Path = "artifacts/risk/pr-comments",
    dedupe_db_path: str | Path | None = None,
    github_repo: str | None = None,
    github_token: str | None = None,
    post_to_github: bool | None = None,
) -> dict[str, Any]:
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
        **(
            _post_github_risk_comment(
                profile,
                repo=github_repo or os.environ.get("GITHUB_REPOSITORY", ""),
                pr_number=pr_number,
                head_sha=head_sha,
                token=github_token or os.environ.get("GITHUB_TOKEN", ""),
            )
            if _should_post_to_github(post_to_github)
            else {}
        ),
    }


def _get_deduped_writer(db_path: str | Path | None = None) -> Callable[..., dict[str, Any]]:
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
    github_repo: str | None = None,
    github_token: str | None = None,
    post_to_github: bool | None = None,
) -> dict[str, Any]:
    """Write a risk PR comment artifact and optionally post it to GitHub."""
    resolved_url = pr_url or profile.pr_url
    if not resolved_url:
        raise ValueError("pr_url must be provided or set on profile")

    if _should_post_to_github(post_to_github):
        resolved_repo = github_repo or os.environ.get("GITHUB_REPOSITORY")
        resolved_token = github_token or os.environ.get("GITHUB_TOKEN")
        if not resolved_repo:
            raise ValueError("github_repo or GITHUB_REPOSITORY is required when posting to GitHub")
        if not resolved_token:
            raise ValueError("github_token or GITHUB_TOKEN is required when posting to GitHub")

    writer = _get_deduped_writer(dedupe_db_path)
    return writer(
        profile,
        pr_url=resolved_url,
        pr_number=pr_number,
        head_sha=head_sha,
        artifacts_root=artifacts_root,
        dedupe_db_path=dedupe_db_path,
        github_repo=github_repo,
        github_token=github_token,
        post_to_github=post_to_github,
    )


def validate_model_spec(model_spec: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化 ModelSpec（供 tool registry 使用）。"""
    return ModelSpec(**model_spec).model_dump(mode="json")

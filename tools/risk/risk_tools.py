"""Risk group tools — read / calc / profile / gate / comment."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from schemas.risk_profile import RiskProfile, RiskThresholds
from tools.risk.statistics_stub import calc_risk_stub
from tools.utils.dedupe import dedupe_within

_SCENARIO = Literal["normal", "high_risk"]
_STUB_EXTRA_FIELDS = frozenset({"volatility", "position_limit_usage", "thresholds"})
_DEDUPE_SECONDS = 300
_DEDUPED_WRITERS: dict[str, Callable[..., dict[str, Any]]] = {}


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
    github_repo: str | None = None,
    github_token: str | None = None,
    post_to_github: bool | None = None,
) -> str:
    return f"pr_comment:{pr_url}:{head_sha}:{_profile_hash(profile)}"


def _github_request(
    method: str,
    repo: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    url = f"{api_base}/repos/{repo}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {detail}") from exc


def _risk_comment_marker(head_sha: str, profile: RiskProfile) -> str:
    return f"<!-- quantcode:risk-gate:profile:{head_sha}:{_profile_hash(profile)} -->"


def _find_existing_github_comment(
    repo: str,
    pr_number: str,
    token: str,
    marker: str,
) -> dict[str, Any] | None:
    comments = _github_request(
        "GET",
        repo,
        f"/issues/{pr_number}/comments?per_page=100",
        token,
    )
    if not isinstance(comments, list):
        return None

    for comment in comments:
        body = str(comment.get("body", ""))
        if marker in body:
            return comment
    return None


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _status(ok: bool) -> str:
    return "PASS" if ok else "NEEDS REVIEW"


def _format_risk_comment(
    profile: RiskProfile,
    *,
    pr_number: str,
    head_sha: str,
) -> str:
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
    existing = _find_existing_github_comment(repo, pr_number, token, marker)
    if existing is not None:
        return {
            "github_comment_id": str(existing.get("id", "")),
            "github_comment_url": str(existing.get("html_url", "")),
            "deduped_by": "github_comment_marker",
        }

    created = _github_request(
        "POST",
        repo,
        f"/issues/{pr_number}/comments",
        token,
        {"body": _format_risk_comment(profile, pr_number=pr_number, head_sha=head_sha)},
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
    """Write a risk PR comment artifact and optionally post it to GitHub."""
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
    """Write a risk PR comment artifact and optionally post it to GitHub.

    GitHub posting is explicit to avoid accidental comments during local tests.
    Set ``post_to_github=True`` or ``QUANTCODE_POST_RISK_COMMENT=1`` in CI.
    """
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

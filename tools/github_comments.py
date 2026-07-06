"""Shared GitHub PR comment client — risk / model 组复用。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def github_request(
    method: str,
    repo: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Send a GitHub REST API request."""
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


def find_existing_comment(
    repo: str,
    pr_number: str,
    token: str,
    marker: str,
) -> dict[str, Any] | None:
    """Find an existing PR comment containing the HTML marker."""
    comments = github_request(
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


def post_pr_comment(
    repo: str,
    pr_number: str,
    token: str,
    body: str,
    *,
    marker: str | None = None,
) -> dict[str, Any]:
    """Post a PR comment, optionally with dedupe marker lookup first."""
    if marker is not None:
        existing = find_existing_comment(repo, pr_number, token, marker)
        if existing is not None:
            return {
                "id": existing.get("id"),
                "html_url": existing.get("html_url"),
                "deduped_by": "github_comment_marker",
            }

    full_body = f"{body}\n\n{marker}" if marker else body
    return github_request(
        "POST",
        repo,
        f"/issues/{pr_number}/comments",
        token,
        {"body": full_body},
    )

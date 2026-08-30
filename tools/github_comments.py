"""Shared GitHub PR comment client — risk / model 组复用。"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

# ponytail: SSRF 守卫（Mimosa L3 high 修复）——repo 只接受 owner/repo 形式，
# API path 白名单前缀且禁 ".."；官方 API host 为常量，httpx client 以
# base_url + 相对路径发请求，不存在拼接任意 URL 的 sink。
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_PATH_PREFIXES = ("/issues/", "/pulls/", "/repos/")
_API_HOST = "https://api.github.com"


def github_request(
    method: str,
    repo: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Send a GitHub REST API request.

    ponytail: SSRF 守卫——repo 必须是 owner/repo 全字匹配；path 白名单前缀 +
    禁 ".."；请求经 httpx base_url 客户端发出，URL 协议与主机由常量唯一确定。
    """
    if not _REPO_RE.fullmatch(repo):
        raise ValueError(f"invalid repo identifier: {repo!r}")
    if not path.startswith(_ALLOWED_PATH_PREFIXES) or ".." in path:
        raise ValueError(f"disallowed API path: {path!r}")

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(
        base_url=_API_HOST,
        timeout=20.0,
        follow_redirects=False,
        headers=headers,
    ) as client:
        response = client.request(method, "/repos/" + repo + path, json=payload)

    if response.status_code >= 400:
        raise RuntimeError(
            f"GitHub API {method} {response.request.url} failed: "
            f"{response.status_code} {response.text[:500]}"
        )
    if not response.content:
        return {}
    return response.json()


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

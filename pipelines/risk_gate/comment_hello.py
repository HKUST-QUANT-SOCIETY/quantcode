"""Post a minimal risk-gate PR comment with the shared dedupe guard.

Day 1 scope: prove that GitHub Actions can write one PR comment and that
repeat calls for the same PR commit are deduped.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from tools.utils import dedupe_within


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


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


def _find_existing_comment(
    repo: str,
    pr_number: str,
    token: str,
    marker: str,
) -> int | None:
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
            comment_id = comment.get("id")
            return int(comment_id) if comment_id is not None else None
    return None


@dedupe_within(
    seconds=300,
    key=lambda repo, pr_number, head_sha, body, token: (
        f"risk-gate:hello:{repo}:{pr_number}:{head_sha}:{body}"
    ),
)
def post_hello_comment(
    repo: str,
    pr_number: str,
    head_sha: str,
    body: str,
    token: str,
) -> dict[str, Any]:
    marker = f"<!-- quantcode:risk-gate:hello:{head_sha} -->"
    existing_id = _find_existing_comment(repo, pr_number, token, marker)
    if existing_id is not None:
        return {"id": existing_id, "deduped_by": "github_comment_marker"}

    return _github_request(
        "POST",
        repo,
        f"/issues/{pr_number}/comments",
        token,
        {"body": f"{body}\n\n{marker}"},
    )


def main() -> None:
    repo = os.environ.get("GITHUB_REPOSITORY") or _required_env("REPO")
    pr_number = _required_env("PR_NUMBER")
    head_sha = _required_env("HEAD_SHA")
    token = _required_env("GITHUB_TOKEN")
    body = os.environ.get("COMMENT_BODY", "hello")

    result = post_hello_comment(repo, pr_number, head_sha, body, token)
    print(f"risk-gate hello comment id={result.get('id')}")


if __name__ == "__main__":
    main()

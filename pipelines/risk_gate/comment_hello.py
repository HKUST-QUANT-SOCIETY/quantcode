"""Post a minimal risk-gate PR comment with the shared dedupe guard."""
from __future__ import annotations

import os
from typing import Any

from tools.github_comments import find_existing_comment, github_request
from tools.utils import dedupe_within


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


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
    existing_id = find_existing_comment(repo, pr_number, token, marker)
    if existing_id is not None:
        return {"id": existing_id.get("id"), "deduped_by": "github_comment_marker"}

    return github_request(
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

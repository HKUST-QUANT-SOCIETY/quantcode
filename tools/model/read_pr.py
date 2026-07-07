"""read_pr tool — 读取本地 PR fixture 或真实 GitHub PR。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from tools.github_comments import github_request
from tools.registry import ToolDef


class ReadPRArgs(BaseModel):
    pr_path: str | None = None
    pr_number: int | None = Field(default=None, gt=0)
    repo: str | None = None

    @model_validator(mode="after")
    def _has_source(self) -> "ReadPRArgs":
        if self.pr_path is None and self.pr_number is None:
            raise ValueError("read_pr requires pr_path or pr_number")
        return self


def _find_pr_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else None


def _resolve_repo(args: ReadPRArgs, ctx: dict) -> str:
    repo = (
        args.repo
        or ctx.get("github_repo")
        or ctx.get("repo")
        or os.environ.get("GITHUB_REPOSITORY")
    )
    if not repo:
        raise ValueError("repo or GITHUB_REPOSITORY is required for GitHub PR reads")
    return str(repo)


def _resolve_token(ctx: dict) -> str:
    token = ctx.get("github_token") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for GitHub PR reads")
    return str(token)


def _read_local_pr(path_str: str) -> dict:
    path = Path(path_str)
    body = path.read_text(encoding="utf-8")
    return {
        "source": str(path),
        "body": body,
        "pr_url": _find_pr_url(body),
    }


def _normalize_file(file_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": file_info.get("filename"),
        "status": file_info.get("status"),
        "additions": file_info.get("additions"),
        "deletions": file_info.get("deletions"),
        "changes": file_info.get("changes"),
        "patch": file_info.get("patch"),
    }


def _compose_diff(files: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for file_info in files:
        filename = file_info.get("filename", "<unknown>")
        status = file_info.get("status", "modified")
        chunks.append(f"diff --git a/{filename} b/{filename}")
        chunks.append(f"# status: {status}")
        patch = file_info.get("patch")
        if patch:
            chunks.append(str(patch))
    return "\n".join(chunks)


def _read_github_pr(args: ReadPRArgs, ctx: dict) -> dict:
    if args.pr_number is None:
        raise ValueError("pr_number is required for GitHub PR reads")

    repo = _resolve_repo(args, ctx)
    token = _resolve_token(ctx)
    pr = github_request("GET", repo, f"/pulls/{args.pr_number}", token)
    files_payload = github_request(
        "GET",
        repo,
        f"/pulls/{args.pr_number}/files?per_page=100",
        token,
    )
    if not isinstance(pr, dict):
        raise ValueError("GitHub pull request response must be an object")
    if not isinstance(files_payload, list):
        raise ValueError("GitHub pull request files response must be a list")

    files = [_normalize_file(file_info) for file_info in files_payload]
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    user = pr.get("user") if isinstance(pr.get("user"), dict) else {}
    body = str(pr.get("body") or "")
    return {
        "source": f"github:{repo}#{args.pr_number}",
        "repo": repo,
        "pr_number": args.pr_number,
        "pr_url": pr.get("html_url"),
        "title": pr.get("title"),
        "author": user.get("login"),
        "body": body,
        "head_sha": head.get("sha"),
        "base_sha": base.get("sha"),
        "diff": _compose_diff(files),
        "files": files,
    }


def read_pr_execute(args: ReadPRArgs, ctx: dict) -> dict:
    if args.pr_path is not None:
        return _read_local_pr(args.pr_path)
    return _read_github_pr(args, ctx)


read_pr_tool = ToolDef(
    id="read_pr",
    description=(
        "Read a local PR markdown fixture by pr_path, or read a real GitHub PR "
        "by pr_number and repo/GITHUB_REPOSITORY. GitHub reads require GITHUB_TOKEN."
    ),
    schema=ReadPRArgs,
    execute=read_pr_execute,
)

__all__ = ["read_pr_tool", "ReadPRArgs", "read_pr_execute"]

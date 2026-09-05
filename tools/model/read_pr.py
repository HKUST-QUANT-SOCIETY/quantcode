"""read_pr tool — 读取本地 PR fixture 或真实 GitHub PR。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from tools.github_comments import github_request
from tools.registry import ToolDef

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    if ctx.get("role") is not None:
        from tools.admin._register import _resolve_github_token
        token = _resolve_github_token(ctx)
    else:
        # Trusted CI callers without a user Session Context retain the service
        # credential path; authenticated researchers never inherit it.
        token = ctx.get("github_token") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GitHub identity credential is not configured")
    return str(token)


def _read_local_pr(path_str: str) -> dict:
    """Read a local fixture only from the approved QuantCode checkout."""
    candidate = Path(path_str).expanduser()
    source = str(candidate) if candidate.is_absolute() else None
    path = (PROJECT_ROOT / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    # macOS workspaces may expose the same checkout through a case-variant
    # alias (``QUANTcode`` vs ``quantcode``).  Accept only an ancestor proven
    # to be the same directory inode; never broaden to an arbitrary path.
    approved_root = PROJECT_ROOT
    relative: Path | None = None
    for ancestor in (path, *path.parents):
        try:
            if ancestor.is_dir() and approved_root.is_dir() and os.path.samefile(ancestor, approved_root):
                relative = path.relative_to(ancestor)
                break
        except OSError:
            continue
    if relative is None:
        raise ValueError("pr_path must remain inside the approved QuantCode checkout")
    path = approved_root / relative
    if not path.is_file():
        raise ValueError("pr_path must reference a regular file inside the approved checkout")
    body = path.read_text(encoding="utf-8")
    return {
        "source": source or str(path),
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
    if ctx.get("role") is not None:
        from tools.admin._register import _visible_repos
        visible, _ = _visible_repos(ctx, token)
        if repo.lower() not in {str(item.get("full_name") or "").lower() for item in visible}:
            raise PermissionError("repository is outside the current GitHub scope")
    pr = github_request("GET", repo, f"/pulls/{args.pr_number}", token)
    if not isinstance(pr, dict):
        raise ValueError("GitHub pull request response must be an object")
    files_payload = []
    for page in range(1, 31):
        suffix = "" if page == 1 else f"&page={page}"
        batch = github_request("GET", repo, f"/pulls/{args.pr_number}/files?per_page=100{suffix}", token)
        if not isinstance(batch, list):
            raise ValueError("GitHub pull request files response must be a list")
        files_payload.extend(batch)
        if len(batch) < 100:
            break
    changed_files = pr.get("changed_files")
    if isinstance(changed_files, int) and changed_files > len(files_payload):
        raise ValueError("GitHub PR file listing is incomplete; refusing to evaluate a partial diff")

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

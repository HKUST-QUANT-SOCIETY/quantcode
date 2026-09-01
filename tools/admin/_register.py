"""Register Admin 中枢工具（P-08）——跨组只读查询 + GitGraph/pop 数据源。

import 即触发 6 个 ToolDef 注册（AG-C 模式：ToolDef 全部放本外部模块，
``quantcode/mcp_server.py`` 只加一行 import；不在 mcp_server 模块体内注册，
否则 test_mcp_server 的 QUANTCODE_GROUP=model 精确集合断言会红——外部模块
import 在 reload 时是 no-op，admin 工具不会重新灌进被清空的 registry）。

工具清单：
- ``admin_list_runs(status_filter?, group_filter?, limit?)``  跨组 run 聚合
- ``admin_errors(window?)``                                   错误沉淀汇总
- ``admin_blackboard_read(key)``                              跨组只读读 Blackboard
- ``admin_repo_status()``                                     org repo 状态（GitGraph 数据源）
- ``admin_package_updates(since_days?)``                      依赖文件更新检测（package pop 数据源）
- ``ssh_status()``                                            SSH 配置状态（AG-F 后端，此处仅注册）

权限边界（P-08 定版：Admin = 角色而非第七组）：
- 六个工具全部走 **_meta 通道**（不进各组 tool_allowlist，六组 MCP server 的
  tools/list 都能列出——发现面全员一致）；
- 五个 ``admin_*`` 工具 execute 入口先过 :func:`runner.admin_scope.is_admin`
  （identity 取 ctx["identity"]/ctx["ssh_fingerprint"]，或进程级
  ``QUANTCODE_ADMIN=1``）；非 Admin 返回 ``{"ok": False, "error": "admin only"}``
  **不抛异常**——对齐 solution 工具的领域拒绝返回值模式（tool_node 会把异常
  脱敏成类名，吞掉拒绝原因；原因必须对 LLM 可见）；
- ``ssh_status`` 是 F-05 登录界面的数据层（登录前就要能看），**不设 admin 门禁**。
"""
from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

from tools.registry import ToolDef, registry

# GitHub org（P-08 定版）。repo 名来自 GitHub API 响应，插 URL 前过 _NAME_RE 校验。
GH_ORG = "HKUST-QUANT-SOCIETY"
GH_API_HOST = "https://api.github.com"
# 依赖文件匹配：pyproject.toml 精确 + requirements*.txt 通配（P-08 定版口径）。
_DEP_FILE_EXACT = ("pyproject.toml",)
_DEP_FILE_GLOB = ("requirements*.txt",)
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Blackboard GROUP scope 的可扫组集合（六研究组；与 tools/subagent.VALID_GROUPS
# 同源口径。ponytail: 本地常量而非 import subagent 模块——避免注册副作用耦合）。
GROUP_SCAN = ("model", "risk", "factor", "fundamental", "options", "strategy")


# ---------------------------------------------------------------------------
# 共享助手：admin 门禁 + GitHub 只读 GET（复用 read_pr 的 token 通道语义）
# ---------------------------------------------------------------------------


def _admin_gate(ctx: dict) -> dict[str, Any] | None:
    """Admin 门禁：Admin → None（放行）；非 Admin → 领域拒绝 payload（不抛）。"""
    from runner.admin_scope import is_admin

    ident = ctx.get("identity") or ctx.get("ssh_fingerprint")
    if is_admin(ident if isinstance(ident, str) else None, ctx.get("group")):
        return None
    return {"ok": False, "error": "admin only"}


def _org_metadata_gate(ctx: dict) -> dict[str, Any] | None:
    """org 只读元数据门禁：全员放行（2026-09-01 定版——双类 pop 需全组可见，
    repo/package 元数据非敏感面；数据字段清单类敏感蒸馏仍由能力卡 Mask 承担）。
    admin_repo_status / admin_package_updates 专用，其余 admin_* 仍走 _admin_gate。"""
    return None


def _resolve_github_token(ctx: dict) -> str | None:
    """复用 read_pr 的 token 解析语义（tools/model/read_pr._resolve_token）：
    ctx["github_token"] 优先，退化 ``GITHUB_TOKEN`` env。缺失 → None（调用方
    返回诚实空态，绝不伪造数据）。"""
    token = ctx.get("github_token") or os.environ.get("GITHUB_TOKEN")
    return str(token) if token else None


def _gh_get(path: str, token: str) -> Any:
    """GitHub REST 只读 GET。

    ponytail: tools/github_comments.github_request 的 path 白名单不含
    /orgs 与 /commits（非本波文件集，不改），故此处自带极简 GET——host 是
    常量、path 只由 GH_ORG 常量与过 _NAME_RE 校验的 repo 名拼接，SSRF 面与
    github_request 同级。token 解析与 read_pr 同通道。
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(
        base_url=GH_API_HOST, timeout=20.0, follow_redirects=False, headers=headers
    ) as client:
        resp = client.get(path)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"GitHub API GET {path} failed: {resp.status_code} {resp.text[:200]}"
        )
    if not resp.content:
        return {}
    return resp.json()


def _safe_repo(name: Any) -> str | None:
    """repo 名校验（_NAME_RE 全字匹配）；非法 → None（跳过，不进 URL）。"""
    s = str(name or "")
    return s if _NAME_RE.fullmatch(s) else None


def _iso_date(value: Any) -> datetime | None:
    """GitHub ISO8601 时间戳 → aware datetime；解析失败 → None。"""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _first_line(message: Any) -> str:
    text = str(message or "").strip()
    return text.splitlines()[0] if text else ""


# ---------------------------------------------------------------------------
# admin_list_runs — 跨组 run 聚合
# ---------------------------------------------------------------------------


class AdminListRunsArgs(BaseModel):
    """admin_list_runs 入参——跨组 list_runs 聚合（F-09 语义查询①）。"""

    status_filter: str | None = Field(
        default=None, description="按 status 过滤（completed/error/stopped/...）；空=不过滤。"
    )
    group_filter: str | None = Field(
        default=None,
        description="按组过滤（model/risk/factor/fundamental/options/strategy）；空=跨组全量。",
    )
    limit: int = Field(
        default=200, ge=1, le=2000, description="聚合窗口：最近 N 条 run 记录（metrics.jsonl）。"
    )


def _admin_list_runs_execute(args: AdminListRunsArgs, ctx: dict) -> dict[str, Any]:
    denied = _admin_gate(ctx)
    if denied:
        return denied
    from runner import metrics

    runs = metrics.read_recent(args.limit)
    return metrics.aggregate_runs(
        runs, status_filter=args.status_filter, group_filter=args.group_filter
    )


# ---------------------------------------------------------------------------
# admin_errors — 错误沉淀汇总
# ---------------------------------------------------------------------------


class AdminErrorsArgs(BaseModel):
    """admin_errors 入参——错误沉淀汇总（F-09 语义查询③）。"""

    window: int = Field(
        default=200, ge=1, le=2000, description="错误扫描窗口：最近 N 条 run 记录。"
    )


def _admin_errors_execute(args: AdminErrorsArgs, ctx: dict) -> dict[str, Any]:
    denied = _admin_gate(ctx)
    if denied:
        return denied
    from runner import metrics

    return metrics.error_digest(metrics.read_recent(args.window))


# ---------------------------------------------------------------------------
# admin_blackboard_read — 跨组只读读 Blackboard entry
# ---------------------------------------------------------------------------


class AdminBlackboardReadArgs(BaseModel):
    """admin_blackboard_read 入参——跨组只读（拒绝写语义：本工具无任何写路径）。"""

    key: str = Field(
        min_length=1,
        description="Blackboard 条目名（裸名自动经 make_read_key 归一补 shared. 前缀）。",
    )


def _blackboard_service(ctx: dict):
    from runner.blackboard import BlackboardService
    from runner.blackboard_keys import PROJECT_SESSION_ID

    db_path = ctx.get("blackboard_db_path")
    return BlackboardService(
        db_path=db_path,
        session_id=PROJECT_SESSION_ID,
        # requester_group=None：PROJECT scope 天然全组可读；GROUP scope 条目
        # 由下方逐组以该组身份读取（Admin 跨组只读是 P-08 明示授权面）。
    )


def _admin_blackboard_read_execute(args: AdminBlackboardReadArgs, ctx: dict) -> dict[str, Any]:
    denied = _admin_gate(ctx)
    if denied:
        return denied

    from runner.blackboard_keys import make_read_key
    from schemas import BlackboardScope

    raw = args.key.strip()
    key_norm = make_read_key(raw)
    svc = _blackboard_service(ctx)
    entries = []

    # ① PROJECT scope（跨组共享条目，key 经 make_read_key 归一）。
    entry = svc.get_entry(BlackboardScope.PROJECT, None, key_norm, requester_group=None)
    if entry is not None:
        entries.append(entry)
    # ② GROUP scope（组私有条目，key 为写入时的裸名）：逐组以该组身份读。
    for g in GROUP_SCAN:
        for k in ((raw, key_norm) if key_norm != raw else (raw,)):
            found = svc.get_entry(BlackboardScope.GROUP, g, k, requester_group=g)
            if found is not None:
                entries.append(found)
    return {
        "ok": True,
        "key": key_norm,
        "found": bool(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


# ---------------------------------------------------------------------------
# admin_repo_status — org repo 状态（GitGraph 面板数据源，AG-K）
# ---------------------------------------------------------------------------


class AdminRepoStatusArgs(BaseModel):
    """admin_repo_status 无入参（org 固定为 GH_ORG 常量）。"""

    pass


def _admin_repo_status_execute(args: AdminRepoStatusArgs, ctx: dict) -> dict[str, Any]:
    denied = _org_metadata_gate(ctx)
    if denied:
        return denied
    token = _resolve_github_token(ctx)
    if not token:
        # 诚实空态：无 token 不伪造数据（P-08：无凭据必须明示 error 字段）。
        return {
            "ok": False,
            "error": "GITHUB_TOKEN not set (nor ctx['github_token']) — GitHub API unavailable",
            "org": GH_ORG,
            "repos": [],
        }
    try:
        repos = _gh_get(f"/orgs/{GH_ORG}/repos?per_page=100&sort=pushed", token)
    except Exception as e:
        return {"ok": False, "error": f"GitHub API failed: {e}", "org": GH_ORG, "repos": []}
    if not isinstance(repos, list):
        return {
            "ok": False,
            "error": "unexpected GitHub API response (not a list)",
            "org": GH_ORG,
            "repos": [],
        }

    out: list[dict[str, Any]] = []
    for r in repos:
        if not isinstance(r, dict):
            continue
        name = _safe_repo(r.get("name"))
        if name is None:
            continue
        branch = str(r.get("default_branch") or "main")
        item: dict[str, Any] = {
            "name": name,
            "pushed_at": r.get("pushed_at"),
            "default_branch": branch,
        }
        try:
            commit = _gh_get(f"/repos/{GH_ORG}/{name}/commits/{branch}?per_page=1", token)
            info = commit.get("commit") if isinstance(commit, dict) else {}
            author = info.get("author") if isinstance(info, dict) else {}
            item["latest_commit"] = {
                "sha": str(commit.get("sha") or "")[:12] if isinstance(commit, dict) else "",
                "message": _first_line(info.get("message") if isinstance(info, dict) else ""),
                "date": author.get("date") if isinstance(author, dict) else None,
                "author": author.get("name") if isinstance(author, dict) else None,
            }
        except Exception as e:
            item["error"] = f"commit fetch failed: {e}"
        out.append(item)
    return {"ok": True, "org": GH_ORG, "count": len(out), "repos": out}


# ---------------------------------------------------------------------------
# admin_package_updates — 依赖文件更新检测（双类 pop 之 package pop 数据源）
# ---------------------------------------------------------------------------


class AdminPackageUpdatesArgs(BaseModel):
    """admin_package_updates 入参——“有更新”按时间窗判定（无基线存储，诚实可测）。"""

    since_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="“有更新”判定窗口：依赖文件最近 N 天内有 commit 即算有更新（默认 7）。",
    )


def _dep_files_of(names: Any) -> list[str]:
    """从 repo 根 contents 列表挑依赖文件（pyproject.toml / requirements*.txt）。"""
    out: list[str] = []
    if not isinstance(names, list):
        return out
    for item in names:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = str(item.get("name") or "")
        if name in _DEP_FILE_EXACT or any(
            fnmatch.fnmatchcase(name, pat) for pat in _DEP_FILE_GLOB
        ):
            out.append(name)
    return sorted(out)


def _admin_package_updates_execute(args: AdminPackageUpdatesArgs, ctx: dict) -> dict[str, Any]:
    denied = _org_metadata_gate(ctx)
    if denied:
        return denied
    token = _resolve_github_token(ctx)
    if not token:
        return {
            "ok": False,
            "error": "GITHUB_TOKEN not set (nor ctx['github_token']) — GitHub API unavailable",
            "org": GH_ORG,
            "updates": [],
        }
    try:
        repos = _gh_get(f"/orgs/{GH_ORG}/repos?per_page=100", token)
    except Exception as e:
        return {"ok": False, "error": f"GitHub API failed: {e}", "org": GH_ORG, "updates": []}
    if not isinstance(repos, list):
        return {
            "ok": False,
            "error": "unexpected GitHub API response (not a list)",
            "org": GH_ORG,
            "updates": [],
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    updates: list[dict[str, Any]] = []
    checked = 0
    for r in repos:
        if not isinstance(r, dict):
            continue
        name = _safe_repo(r.get("name"))
        if name is None:
            continue
        try:
            dep_files = _dep_files_of(_gh_get(f"/repos/{GH_ORG}/{name}/contents", token))
        except Exception:
            continue  # 空 repo / contents 不可读 → 跳过该 repo（诚实：不进清单）
        checked += 1
        files: list[dict[str, Any]] = []
        last_change: datetime | None = None
        for dep in dep_files:
            try:
                commits = _gh_get(
                    f"/repos/{GH_ORG}/{name}/commits?path={dep}&per_page=1", token
                )
            except Exception:
                continue
            if not isinstance(commits, list) or not commits:
                continue
            head = commits[0] if isinstance(commits[0], dict) else {}
            info = head.get("commit") if isinstance(head.get("commit"), dict) else {}
            author = info.get("author") if isinstance(info, dict) else {}
            date = _iso_date(author.get("date") if isinstance(author, dict) else None)
            files.append({
                "file": dep,
                "sha": str(head.get("sha") or "")[:12],
                "date": author.get("date") if isinstance(author, dict) else None,
                "message": _first_line(info.get("message")),
            })
            if date is not None and (last_change is None or date > last_change):
                last_change = date
        if files and last_change is not None and last_change >= cutoff:
            updates.append({
                "repo": name,
                "last_change": last_change.isoformat(),
                "files": files,
            })
    return {
        "ok": True,
        "org": GH_ORG,
        "window_days": args.since_days,
        "repos_checked": checked,
        "updates": updates,
    }


# ---------------------------------------------------------------------------
# ssh_status — 元工具注册（后端实现在 runner/server_ssh.py，AG-F 交付）
# ---------------------------------------------------------------------------


class SshStatusArgs(BaseModel):
    """ssh_status 无入参（只读本地配置与绑定文件，不联网）。"""

    pass


def _ssh_status_execute(args: SshStatusArgs, ctx: dict) -> dict[str, Any]:
    from runner.server_ssh import ssh_status

    return ssh_status()


# ---------------------------------------------------------------------------
# ToolDef 注册（模块 import 副作用触发，覆盖式幂等，reload 安全）
# ---------------------------------------------------------------------------


def _register_admin_tools() -> None:
    """构造并注册 6 个 ToolDef（ponytail: 与 list_capabilities 同款——_meta 通道
    + ``registry._tools[id] = tool`` 覆盖式注册，不抛重复注册错）。"""
    specs = (
        (
            "admin_list_runs",
            "Admin-only cross-group run aggregation (P-08): reads "
            ".quantcode/metrics.jsonl and groups recent runs by group -> "
            "thread (person/session) -> status/errors. Optional status_filter "
            "/ group_filter. Non-admin callers get {'ok': False, 'error': "
            "'admin only'}.",
            AdminListRunsArgs,
            _admin_list_runs_execute,
        ),
        (
            "admin_errors",
            "Admin-only error digest (P-08): summarizes failed runs "
            "(status=error or non-empty error) from recent metrics.jsonl "
            "records, grouped by group with ts/thread/flow/message. Empty "
            "window returns an honest zero state. Non-admin callers get "
            "{'ok': False, 'error': 'admin only'}.",
            AdminErrorsArgs,
            _admin_errors_execute,
        ),
        (
            "admin_blackboard_read",
            "Admin-only cross-group READ-ONLY blackboard lookup (P-08): reads "
            "a BlackboardEntry by key (normalized via make_read_key; PROJECT "
            "scope first, then GROUP-scope entries of all six groups). No "
            "write path exists on this tool. Non-admin callers get {'ok': "
            "False, 'error': 'admin only'}.",
            AdminBlackboardReadArgs,
            _admin_blackboard_read_execute,
        ),
        (
            "admin_repo_status",
            "Admin-only GitHub org repo status (P-08 GitGraph data source): "
            "lists org repos with pushed_at and each default branch's latest "
            "commit summary (sha/message/date/author). Requires GITHUB_TOKEN; "
            "without it returns an honest empty state with an error field.",
            AdminRepoStatusArgs,
            _admin_repo_status_execute,
        ),
        (
            "admin_package_updates",
            "Admin-only dependency update check (P-08 package-pop data "
            "source): for each org repo, finds the latest commit touching "
            "pyproject.toml / requirements*.txt and reports repos whose "
            "dependency files changed within since_days. Requires "
            "GITHUB_TOKEN; without it returns an honest empty state.",
            AdminPackageUpdatesArgs,
            _admin_package_updates_execute,
        ),
        (
            "ssh_status",
            "Read-only SSH mainline config status (P0-7/F-05): per configured "
            "server returns host/user/port, env role, host_key digest, key "
            "file presence, and SSH->group binding readiness. No network, "
            "zero side effects.",
            SshStatusArgs,
            _ssh_status_execute,
        ),
    )
    for tool_id, description, schema, execute in specs:
        tool = ToolDef(id=tool_id, description=description, schema=schema, execute=execute)
        tool._meta = True  # type: ignore[attr-defined]
        registry._tools[tool.id] = tool


_register_admin_tools()


__all__ = ["GH_ORG", "GROUP_SCAN", "_register_admin_tools"]

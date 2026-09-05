"""QuantCode MCP server — Day 3 尹一帆。

把 QuantCode 的 tool 注册表 + AgentRunner 通过 Model Context Protocol (MCP)
暴露给 OpenCode / 其他 MCP 客户端。

MCP 协议要点（基于 Anthropic MCP spec）：
- stdio 传输：服务端从 stdin 读 JSON-RPC 请求，往 stdout 写响应
- 客户端通过 ``initialize`` / ``tools/list`` / ``tools/call`` 三个 method 与服务端交互
- 每个 tool 必须声明 ``name`` / ``description`` / ``inputSchema``（JSON Schema）

启动方式::

    python -m quantcode.mcp_server

OpenCode 配置（``opencode.jsonc`` 的 ``mcp`` 段）::

    "mcp": {
        "quantcode": {
            "type": "local",
            "command": ["uv", "run", "python", "-m", "quantcode.mcp_server"],
            "enabled": true
        }
    }

参考：
- MCP 协议：https://modelcontextprotocol.io/
- 本仓库规划：``docs/QuantCode_Design.md`` §2 控制平面
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# 诊断日志：stderr（不污染 stdout JSON-RPC），Dev 模式默认开启
logger = logging.getLogger("quantcode.mcp")

# 让 ``python -m quantcode.mcp_server`` 也能找到 tools / runner
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.registry import registry, ToolDef
from tools.schema_utils import pydantic_to_json_schema  # Day 4: 提取到公共模块
from quantcode import identity  # P0-7: SSH key → group 绑定解析

# MCP server 暴露的 tool 集合按会话身份和组 allowlist 过滤。
# 开发测试可显式使用 ``QUANTCODE_ENV=test`` + ``QUANTCODE_ALLOW_UNAUTH=1``；
# 生产环境无 roster 身份时 fail-closed，避免泄漏未授权内部 tool。
#
# P0-7：组身份解析升级为三级（SSH key → 组长期绑定，会话内不可变，
# 见 ``docs/QuantCode_Design.md`` §2.1 与 ``quantcode/identity.py``）：
#   a) env ``QUANTCODE_SSH_KEY_FINGERPRINT``（别名 ``QUANTCODE_SSH_FINGERPRINT``）
#      存在 → 查绑定映射；命中 → 返回该组并进程内缓存；未命中 → fail-closed。
#   b) 无指纹且映射文件缺失/为空 → 沿用 ``QUANTCODE_GROUP`` env（本地单用户降级）。
#   c) 无指纹但映射文件有绑定 → fail-closed，除非 ``QUANTCODE_ALLOW_UNAUTH=1``
#      （此时 env 兜底 + warning）。
# 会话内不可变：指纹一旦解析出组即锁定为会话组（一个 MCP server 进程 = 一个会话），
# 之后即使 env 指纹消失或绑定文件被改，会话组身份也不变（防会话中途降权/换组）。
_SESSION_GROUP: str | None = None
# The group alone is not a session identity.  Once the first authenticated
# request resolves a roster entry, freeze the complete non-secret context for
# the lifetime of this MCP process so a changed host env cannot swap actor or
# workspace while retaining the same group.
_SESSION_CONTEXT: dict[str, Any] | None = None
_SESSION_ID = f"qc_{uuid.uuid4().hex}"
_VALID_GROUPS = frozenset({"fundamental", "factor", "model", "risk", "strategy", "options"})

# 管理查询面分为两类：GitGraph/package 元数据按 GitHub 可见范围提供给
# 普通用户；跨组运行、错误和 Blackboard 查询只给 Admin。该集合同时用于
# tools/list 和 tools/call，避免出现“列表看不到但仍可直接调用”的旁路。
_ADMIN_ONLY_META_TOOLS = frozenset(
    {"admin_list_runs", "admin_errors", "admin_blackboard_read"}
)
_APPROVER_META_TOOLS = frozenset({"review_distill_candidate"})


def _get_ssh_fingerprint() -> str | None:
    """读取宿主注入的 SSH 公钥指纹 env（主名 + 兼容别名）。"""
    fp = (
        os.environ.get("QUANTCODE_SSH_KEY_FINGERPRINT")
        or os.environ.get("QUANTCODE_SSH_FINGERPRINT")
        or ""
    ).strip()
    return fp or None


def _env_group() -> str | None:
    return os.environ.get("QUANTCODE_GROUP", "").strip() or None


def _validate_group(group: str | None) -> str | None:
    if group is not None and group not in _VALID_GROUPS:
        raise RuntimeError(f"invalid QuantCode group {group!r}; expected one of {sorted(_VALID_GROUPS)}")
    return group


def _development_mode() -> bool:
    return os.environ.get("QUANTCODE_ENV", "").strip().lower() in {
        "dev", "development", "test"
    }


def _get_mcp_group() -> str | None:
    """解析当前活跃组（P0-7 三级，见模块头注释）。

    途径：
    1. SSH 指纹 env（``QUANTCODE_SSH_KEY_FINGERPRINT``/``QUANTCODE_SSH_FINGERPRINT``）
       → ``.opencode/authorized_groups.yaml`` 绑定映射（命中后进程内锁定为会话组）
    2. 无绑定配置时降级：``QUANTCODE_GROUP`` env（shell export 或
       opencode.jsonc 的 ``mcp.<server>.environment.QUANTCODE_GROUP``）
    3. 有绑定配置但无指纹：fail-closed，或显式 ``QUANTCODE_ALLOW_UNAUTH=1`` 降级
    """
    global _SESSION_GROUP, _SESSION_CONTEXT
    # Tests and explicit process restarts clear the legacy group sentinel.  Do
    # the same for the full context cache; a real session stores an empty group
    # as ``""`` so the no-group development fallback remains immutable too.
    if _SESSION_GROUP is None and _SESSION_CONTEXT is not None:
        _SESSION_CONTEXT = None
    if _SESSION_CONTEXT is not None:
        return str(_SESSION_CONTEXT.get("group") or "") or None
    if _SESSION_GROUP is not None:
        # 会话内已通过指纹解析 → 不可变，直接返回
        return _SESSION_GROUP or None

    fp = _get_ssh_fingerprint()
    if fp is not None:
        entry = identity.resolve_identity(fp)
        group = _validate_group(entry.get("group") if entry else None)
        if group is None:
            raise RuntimeError(
                f"P0-7 fail-closed: SSH 指纹 {fp} 未在 "
                f"{identity.DEFAULT_BINDINGS_PATH} 命中任何组绑定。"
                "如何修复: python -m quantcode.identity add --group <group> "
                "--public-key <pubkey_path> "
                "（指纹可用 ssh-keygen -lf <pubkey> 或 "
                "python -m quantcode.identity list 核对）。"
            )
        if not _development_mode():
            required = ("actor_id", "role", "workspace_id", "workspace_path")
            if entry is None or any(not entry.get(key) for key in required):
                raise RuntimeError(
                    "AUTHENTICATION_REQUIRED: SSH roster entry lacks required Session Context fields"
                )
            if str(entry.get("role") or "").strip() not in {"analyst", "approver", "admin"}:
                raise RuntimeError(
                    "AUTHENTICATION_REQUIRED: SSH roster entry has an invalid Session Context role"
                )
        _SESSION_GROUP = group
        return group

    bindings = identity.load_bindings()
    if bindings:
        # 有绑定配置但本会话未提供指纹 → 默认 fail-closed
        if _development_mode() and os.environ.get("QUANTCODE_ALLOW_UNAUTH", "").strip() == "1":
            g = _validate_group(_env_group())
            if g:
                _SESSION_GROUP = g
            logger.warning(
                "_get_mcp_group: 已配置 SSH 组绑定但未提供指纹，"
                "QUANTCODE_ALLOW_UNAUTH=1 显式降级，组身份来自环境变量 (%s)。",
                g or "(unset)",
            )
            return g
        raise RuntimeError(
            f"P0-7 fail-closed: 检测到 {len(bindings)} 条 SSH 组绑定 "
            f"({identity.DEFAULT_BINDINGS_PATH}) 但本会话未提供指纹。三条出路: "
            "1) export QUANTCODE_SSH_KEY_FINGERPRINT=SHA256:... "
            "(或别名 QUANTCODE_SSH_FINGERPRINT，指纹来自 ssh-keygen -lf "
            "/ python -m quantcode.identity list); "
            "2) python -m quantcode.identity add --group <group> "
            "--public-key <pubkey_path> 绑定本机; "
            "3) 本地单用户显式降级: export QUANTCODE_ALLOW_UNAUTH=1。"
        )

    # No roster is allowed only in an explicit local development process.
    if not _development_mode():
        raise RuntimeError(
            "AUTHENTICATION_REQUIRED: production MCP requires SSH roster identity"
        )
    g = _validate_group(_env_group())
    if g is not None and not _development_mode():
        raise RuntimeError(
            "AUTHENTICATION_REQUIRED: production MCP requires SSH roster identity; "
            "QUANTCODE_GROUP is only allowed in explicit development mode"
        )
    if g is None:
        logger.warning(
            "_get_mcp_group: 未配置 SSH 绑定（绑定文件缺失或为空），"
            "QUANTCODE_GROUP 也未设置 — 组过滤关闭，返回全部 tool。"
            "配置途径: 1) shell export, 2) mcp.<server>.environment in opencode.jsonc, "
            "3) python -m quantcode.identity add 绑定 SSH key。"
        )
    else:
        logger.warning(
            "_get_mcp_group: 未配置 SSH 绑定，组身份来自环境变量 "
            "QUANTCODE_GROUP=%s（本地单用户降级）。生产部署请改用 "
            "python -m quantcode.identity add 绑定 SSH key。",
            g,
        )
        if g:
            _SESSION_GROUP = g
    # Empty string is a locked development-session sentinel; ``None`` remains
    # reserved for an unresolved/failed production session.
    _SESSION_GROUP = g or ""
    return g


from tools.model._register import (  # noqa: F401  触发 model tool 注册
    read_pr_tool,
    extract_metadata_tool,
    generate_model_spec_tool,
    write_blackboard_tool,
    trigger_risk_flow_tool,
)
from tools.options._register import (  # noqa: F401  触发 options tool 注册
    build_vol_surface_tool,
    calc_greeks_tool,
    run_options_backtest_stub_tool,
)
import tools.risk._register  # noqa: F401  触发 risk tool 注册
import tools.factor._register  # noqa: F401  触发 factor tool 注册(Day 4 尹一帆)
import tools.market._register  # noqa: F401  触发 market tool 注册(P-01)
import tools.strategy._register  # noqa: F401  触发 strategy tool 注册
import tools.fundamental._register  # noqa: F401  触发 fundamental tool 注册
import tools.algorithms._register as _algorithms_register  # noqa: F401  触发算法注册表三工具注册(ROADMAP A3)
from tools.algorithms._register import (  # noqa: F401
    describe_algorithm_tool,
    list_algorithms_tool,
    run_algorithm_tool,
)
import tools.experiments._register as _experiments_register  # noqa: F401  触发 AB 实验三工具注册(ROADMAP A3 / P-05)
from tools.experiments._register import (  # noqa: F401
    get_experiment_tool,
    list_experiments_tool,
    run_ab_experiment_tool,
)
import runner.agent_mcp_tool  # noqa: F401  触发 run_agent tool 注册（Day 4 俞高磊）
import tools.solution._register  # noqa: F401,E402  触发 solution 四工具注册（P-10，AG-J 移交项）
import runner.distill.cards  # noqa: F401,E402  触发 list_capabilities 元工具注册（P-07，_meta 通道）
import tools.admin._register  # noqa: F401,E402  触发 admin 六工具注册（P-08，AG-D：_meta 通道 + 运行时 admin 门禁）


# ---------------------------------------------------------------------------
# list_algorithms 只读工具（configs/algorithms.yaml 注册表目录，ROADMAP A3）
# ---------------------------------------------------------------------------

# ponytail: 走 list_runs 同款 _meta 通道 —— 不进各组 allowlist 也能被六组 MCP
# server 的 tools/list 列出（list_tools 末尾统一附加 meta tool），只读无副作用。
# 三件套（list/describe/run）全部 _meta：算法实验是平台级能力。
list_algorithms_tool._meta = True  # type: ignore[attr-defined]
describe_algorithm_tool._meta = True  # type: ignore[attr-defined]
run_algorithm_tool._meta = True  # type: ignore[attr-defined]
# 幂等：覆盖式注册（register_tool 已是覆盖语义，重复 register 无害）
for _t in (list_algorithms_tool, describe_algorithm_tool, run_algorithm_tool):
    registry._tools[_t.id] = _t


# ---------------------------------------------------------------------------
# AB 实验三工具（artifacts/experiments 归档 + 排行榜，ROADMAP A3 / P-05）
# ---------------------------------------------------------------------------

# 走 algorithms 三件套同款 _meta 通道：平台级实验能力，所有组 MCP 可见，只读无副作用
# （run_ab_experiment 只写 artifacts/，不碰 Blackboard/交易数据）。
run_ab_experiment_tool._meta = True  # type: ignore[attr-defined]
list_experiments_tool._meta = True  # type: ignore[attr-defined]
get_experiment_tool._meta = True  # type: ignore[attr-defined]
for _t in (run_ab_experiment_tool, list_experiments_tool, get_experiment_tool):
    registry._tools[_t.id] = _t


# ---------------------------------------------------------------------------
# list_runs 只读工具（metrics 查询，monitor Tab 数据源）
# ---------------------------------------------------------------------------


class ListRunsArgs(BaseModel):
    """list_runs 的输入参数 — 只读查询 `.quantcode/metrics.jsonl`。"""

    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="返回最近 N 条 run 记录（1-200，默认 20）。",
    )


def _list_runs_execute(args: ListRunsArgs, ctx: dict) -> dict:
    """执行 list_runs：read_recent + aggregate 汇总。只读，best-effort。"""
    from runner import metrics

    runs = metrics.read_recent(args.limit)
    group = str((ctx or {}).get("group") or "").strip()
    if group and not _is_admin_session(group):
        runs = [run for run in runs if run.get("group") == group]
    return {
        "recent_runs": runs,
        "aggregate": metrics.aggregate_records(runs),
    }


list_runs_tool = ToolDef(
    id="list_runs",
    description=(
        "Read-only query of recent agent run metrics from .quantcode/metrics.jsonl. "
        "Returns recent runs (group/flow/status/duration/tool_calls) and aggregate "
        "stats (runs/success_rate/avg_duration_s/error_rate/by_group)."
    ),
    schema=ListRunsArgs,
    execute=_list_runs_execute,
)
# ponytail: 走 run_agent 同款 _meta 通道 — 不进各组 allowlist 也能被所有 6 组
# MCP server 的 tools/list 列出（list_tools 末尾统一附加 meta tool），只读无副作用。
list_runs_tool._meta = True  # type: ignore[attr-defined]
# 幂等：register_tool 覆盖式注册（模块 reload 安全，registry.register 会因重复 id 抛错）
registry._tools[list_runs_tool.id] = list_runs_tool


# ---------------------------------------------------------------------------
# list_skills 只读工具（`.opencode/groups/<group>/skills/` 目录枚举，lens Skill 下拉数据源）
# ---------------------------------------------------------------------------


class ListSkillsArgs(BaseModel):
    """list_skills 的输入参数 — 只读枚举某组的 SKILL.md 目录。"""

    group: str = Field(
        description="组名（model / risk / factor / fundamental / options / strategy）。",
    )


# SKILL.md frontmatter 解析：PyYAML（仓库已依赖，与 tools/registry.py 同源），
# 与 tools/skills/loader.py::_strip_frontmatter 的 "---...\n---\n" 边界语义一致。
# 非法/非 dict frontmatter → 返回空字段 dict（try/except 兜底，best-effort）。
def _parse_skill_frontmatter(md_text: str) -> dict:
    """提取 SKILL.md frontmatter 里的 name/description/pattern（缺失字段值为 ""）。"""
    import yaml

    out = {"name": "", "description": "", "pattern": ""}
    if not md_text.startswith("---"):
        return out
    try:
        _head, fm_text, _body = md_text.split("---", 2)
        data = yaml.safe_load(fm_text)
    except (ValueError, yaml.YAMLError):
        return out
    if not isinstance(data, dict):
        return out
    for key in out:
        value = data.get(key)
        if isinstance(value, str):
            out[key] = value.strip()
    return out


def _list_skills_execute(args: ListSkillsArgs, ctx: dict) -> dict:
    """扫描 .opencode/groups/<group>/skills/*/SKILL.md，返回目录（只读）。"""
    group = args.group.strip()
    if not group or any(part in {"", ".", ".."} for part in group.replace("\\", "/").split("/")):
        return {"error": f"invalid group '{group}'"}
    if not all(ch.isalnum() or ch in "_.-" for ch in group):
        return {"error": f"invalid group '{group}'"}
    session_group = str((ctx or {}).get("group") or "").strip()
    if session_group and group != session_group and not _is_admin_session(session_group):
        return {
            "error": (
                f"group mismatch: authenticated session is '{session_group}', "
                f"requested skills for '{group}'"
            )
        }
    groups_root = PROJECT_ROOT / ".opencode" / "groups"
    group_dir = groups_root / group
    skills_dir = group_dir / "skills"
    # 组合法性 = 组目录存在；组目录在但 skills/ 为空 → 空列表（合法的空组）
    if not group_dir.is_dir():
        available = sorted(
            p.name for p in groups_root.glob("*") if (p / "skills").is_dir()
        ) if groups_root.is_dir() else []
        return {"error": f"invalid group '{group}', valid: {', '.join(available) or '(none)'}"}
    skills: list[dict] = []
    if skills_dir.is_dir():
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            md = d / "SKILL.md"
            if not md.is_file():
                continue
            fm = _parse_skill_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            skills.append({
                "id": d.name,               # 目录名（load_skill 的 skill_name 参数）
                "name": fm["name"] or d.name,
                "description": fm["description"],
                "pattern": fm["pattern"],
            })
    return {"group": group, "skills": skills}


list_skills_tool = ToolDef(
    id="list_skills",
    description=(
        "Read-only catalog of available skills for a group: scans "
        ".opencode/groups/<group>/skills/*/SKILL.md and returns "
        "{group, skills:[{id, name, description, pattern]}. Use before "
        "load_skill to discover skill ids per group."
    ),
    schema=ListSkillsArgs,
    execute=_list_skills_execute,
)
# 走 list_runs 同款 _meta 通道：所有 6 组 MCP server 的 tools/list 都能列出，只读无副作用。
list_skills_tool._meta = True  # type: ignore[attr-defined]
# 幂等：覆盖式注册（模块 reload 安全）
registry._tools[list_skills_tool.id] = list_skills_tool


# ---------------------------------------------------------------------------
# session_context 只读工具（UI 读取服务端签发的组/角色摘要）
# ---------------------------------------------------------------------------


class SessionContextArgs(BaseModel):
    """session_context 无参数，只返回当前 MCP session 的非敏感身份摘要。"""

    pass


def _session_context_execute(args: SessionContextArgs, ctx: dict) -> dict:
    """返回当前认证上下文；不返回私钥、token 或生产拓扑。"""
    group = str((ctx or {}).get("group") or "").strip() or None
    context = ctx or {}
    role = "admin" if _is_admin_session(group) else str(context.get("role") or "analyst")
    if role not in {"analyst", "approver", "admin"}:
        return {"error": "AUTHENTICATION_REQUIRED: invalid Session Context role"}
    return {
        "session_id": context.get("session_id") or _SESSION_ID,
        "group": group,
        "role": role,
        "actor_id": context.get("actor_id"),
        "workspace_id": context.get("workspace_id"),
        "workspace_path": context.get("workspace_path"),
        "github_subject": context.get("github_subject"),
        "resource_scopes": context.get("resource_scopes", []),
        "identity_source": context.get("identity_source")
        or ("ssh_roster" if context.get("ssh_fingerprint") else "development_override"),
    }


session_context_tool = ToolDef(
    id="session_context",
    description=(
        "Read-only summary of the authenticated QuantCode session group, role, "
        "workspace and resource scopes. Secrets and private keys are never returned."
    ),
    schema=SessionContextArgs,
    execute=_session_context_execute,
)
session_context_tool._meta = True  # type: ignore[attr-defined]
registry._tools[session_context_tool.id] = session_context_tool


# ---------------------------------------------------------------------------
# search_memory 只读工具（F-04 UI/Agent 真实 Memory 通道）
# ---------------------------------------------------------------------------


class SearchMemoryArgs(BaseModel):
    """组内长期 Memory FTS 查询参数。"""

    query: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=10, ge=1, le=50)


def _search_memory_execute(args: SearchMemoryArgs, ctx: dict) -> dict:
    """Search maintained long-term Memory with group ACL; never auto-reconciles disk."""
    # MemoryService.root is the project root.  It owns the canonical
    # ``<project>/.quantcode/memory/...`` layout; passing ``.quantcode`` here
    # would create a second ``.quantcode/.quantcode`` prefix on disk.
    memory_root = PROJECT_ROOT
    db_path = memory_root / ".quantcode" / "memory.db"
    if not db_path.is_file():
        return {
            "status": "UNAVAILABLE",
            "error": "Memory store is not initialized",
            "hits": [],
        }

    from runner.memory.service import MemoryService

    group = str((ctx or {}).get("group") or "").strip() or None
    role = str((ctx or {}).get("role") or "").strip()
    if role == "admin":
        hits = []
        # Admin may inspect all group scopes, while the service still applies
        # its normal fail-closed check for each explicit scope.
        for scope_id in sorted(_VALID_GROUPS):
            service = MemoryService(db_path, root=memory_root, requester_group=scope_id)
            hits.extend(
                hit
                for hit in service.search(query=args.query, scope="groups", scope_id=scope_id, limit=args.limit,
                                          long_term_only=True, strict_errors=True)
            )
        service = MemoryService(db_path, root=memory_root)
        for scope in ("global", "projects"):
            hits.extend(service.search(query=args.query, scope=scope, limit=args.limit,
                                       long_term_only=True, strict_errors=True))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        selected = hits[: args.limit]
    else:
        service = MemoryService(db_path, root=memory_root, requester_group=group)
        # A group membership is not project authorization. This product surface
        # exposes only global contracts and the bound group's knowledge until
        # project grants are explicitly resolved from the session.
        selected = service.search(query=args.query, scope="global", limit=args.limit,
                                  long_term_only=True, strict_errors=True)
        if group in _VALID_GROUPS:
            selected.extend(service.search(query=args.query, scope="groups", scope_id=group,
                                           limit=args.limit, long_term_only=True, strict_errors=True))
        selected.sort(key=lambda hit: hit.score, reverse=True)
        selected = selected[:args.limit]
    result = {
        "status": "CONNECTED" if selected else "EMPTY",
        "hits": [hit.to_dict() for hit in selected],
    }
    if role == "admin":
        from runner.admin_scope import audited_read_result

        return audited_read_result("search_memory", ctx, result)
    return result


search_memory_tool = ToolDef(
    id="search_memory",
    description=(
        "Search the authenticated group's maintained long-term Memory. "
        "Runtime checkpoints, progress and raw trace are not returned as knowledge."
    ),
    schema=SearchMemoryArgs,
    execute=_search_memory_execute,
)
registry._tools[search_memory_tool.id] = search_memory_tool


# ---------------------------------------------------------------------------
# consume_status 只读工具（dream consumer 状态：候选数/最近消费/rlhf 行数，ROADMAP A4）
# ---------------------------------------------------------------------------


class ConsumeStatusArgs(BaseModel):
    """consume_status 的输入参数 — 只读查询蒸馏闭环消费端状态。"""

    pass


def _consume_status_execute(args: ConsumeStatusArgs, ctx: dict) -> dict:
    """执行 consume_status：候选数 / 最近消费时间 / rlhf 行数。只读，best-effort。"""
    from runner.dream_consumer import consume_status

    return consume_status()


consume_status_tool = ToolDef(
    id="consume_status",
    description=(
        "Read-only status of the dream distill consumer loop (ROADMAP A4): "
        "number of pending SKILL.md candidates in .quantcode/distill_candidates/, "
        "last consume timestamp, and RLHF record count in .quantcode/rlhf_data.jsonl."
    ),
    schema=ConsumeStatusArgs,
    execute=_consume_status_execute,
)
# 走 list_runs 同款 _meta 通道：所有 6 组 MCP server 的 tools/list 都能列出，只读无副作用。
consume_status_tool._meta = True  # type: ignore[attr-defined]
# 幂等：覆盖式注册（模块 reload 安全）
registry._tools[consume_status_tool.id] = consume_status_tool


# ---------------------------------------------------------------------------
# subagent 元工具（P-04：spawn/check/kill/list 经 _meta 通道注册）
# ---------------------------------------------------------------------------

# 实现（schema+execute）在 tools/subagent/_register.py。四个工具均为编排层元
# 工具，不进各组 tool_allowlist，经统一 _meta 通道向控制器（OpenCode compose /
# monitor）暴露——与 list_runs / list_skills 同路。
import tools.subagent._register  # noqa: F401,E402  触发 subagent tool 注册（P-04）
import tools.stream._register  # noqa: F401,E402  触发 check_tool_stream 注册（_meta 通道）
import tools.portfolio._register  # noqa: F401,E402  触发 portfolio 三工具注册（_meta 通道，确定性数值）


# ---------------------------------------------------------------------------
# LLM 模型工厂（Day 4 俞高磊）
# ---------------------------------------------------------------------------


def _get_model():
    """从环境变量实例化 LLM 模型，供 run_agent tool 使用（P0-6/C30 收敛：仅 env）。

    - QUANTCODE_API_KEY：API key（唯一 key 入口）
    - QUANTCODE_MODEL_PROVIDER：deepseek | anthropic | stepfun（默认 deepseek）
    - QUANTCODE_MODEL_NAME：模型名（默认按 provider：deepseek-chat / claude-sonnet-4-5 / step-3.7-flash）
    - QUANTCODE_MODEL_BASE_URL：自定义 API base URL（deepseek 默认 https://api.deepseek.com/v1，stepfun 默认 step_plan/v1）

    返回一个可调用对象，签名 ``(messages, tools=...) -> AIMessage``，
    适配 AgentRunner 的 model 接口。配置失败返回 None。
    """
    api_key = os.environ.get("QUANTCODE_API_KEY", "").strip()
    if not api_key:
        # ★ 诊断：列出所有包含 KEY / API 的环境变量键名，帮助定位问题
        all_keys = sorted(os.environ.keys())
        key_candidates = [k for k in all_keys if any(kw in k.upper() for kw in ("KEY", "API", "STEPFUN", "ANTHROPIC", "QUANTCODE", "DEEPSEEK"))]
        logger.warning(
            "_get_model: no API key found. "
            "Checked env: QUANTCODE_API_KEY=MISSING. "
            "Relevant env keys present: %s. Total env vars: %d",
            key_candidates, len(all_keys),
        )
        return None

    provider = os.environ.get("QUANTCODE_MODEL_PROVIDER", "deepseek") or "deepseek"

    _DEFAULT_MODELS = {
        "deepseek": "deepseek-chat",
        "anthropic": "claude-sonnet-4-5",
        "stepfun": "step-3.7-flash",
    }
    _DEFAULT_BASE_URLS = {
        "deepseek": "https://api.deepseek.com/v1",
        "stepfun": "https://api.stepfun.com/step_plan/v1",
    }
    model_name = os.environ.get("QUANTCODE_MODEL_NAME", "") or _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS["deepseek"])
    base_url = os.environ.get("QUANTCODE_MODEL_BASE_URL", "") or _DEFAULT_BASE_URLS.get(provider, "")

    def _build_model():
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model_name, api_key=api_key, temperature=0.1, max_tokens=4096,
            )
        elif provider == "stepfun":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=0.1, max_tokens=4096,
            )
        elif provider == "deepseek":
            # ponytail: deepseek 是 OpenAI 兼容 API，直接复用 ChatOpenAI，不再引独立适配层
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=0.1, max_tokens=4096,
            )
        return None

    try:
        chat_model = _build_model()
    except ImportError as e:
        logger.error("_get_model: import failed for provider=%s — missing dependency: %s", provider, e)
        return None
    except Exception as e:
        logger.error("_get_model: build failed for provider=%s model=%s — %s: %s",
                     provider, model_name, type(e).__name__, e)
        return None

    if chat_model is None:
        return None

    # ★ 关键：ChatOpenAI 不可直接调用，只有 .invoke()
    # AgentRunner 的 make_llm_node 调 model(messages, tools=...)
    def _callable_model(messages, tools=None):
        if tools:
            tool_dicts = []
            for t in tools:
                params = {}
                if hasattr(t, 'schema') and hasattr(t.schema, 'model_json_schema'):
                    try:
                        js = t.schema.model_json_schema()
                        js.pop("title", None)
                        params = js
                    except Exception:
                        params = {"type": "object", "properties": {}}
                tool_dicts.append({
                    "type": "function",
                    "function": {
                        "name": t.id, "description": t.description, "parameters": params,
                    }
                })
            bound = chat_model.bind_tools(tool_dicts, strict=False)
        else:
            bound = chat_model
        return bound.invoke(messages)

    return _callable_model


# ---------------------------------------------------------------------------
# Pydantic schema → JSON Schema（已提取到 tools/schema_utils.py）
# ---------------------------------------------------------------------------

# pydantic_to_json_schema 从 tools.schema_utils import，保留此注释块作为文档锚点


def tool_def_to_mcp(tool: ToolDef) -> dict:
    """把 ToolDef 转成 MCP tool 声明格式。"""
    return {
        "name": tool.id,
        "description": tool.description,
        "inputSchema": pydantic_to_json_schema(tool.schema),
    }


# ---------------------------------------------------------------------------
# 简单的 MCP stdio server（手写 JSON-RPC，避免引 mcp.server 复杂依赖）
# ---------------------------------------------------------------------------


def _is_admin_session(group: str | None = None) -> bool:
    """按当前 MCP session 判断 Admin；身份来自 SSH 指纹或显式 Admin 进程。"""
    from runner.admin_scope import is_admin

    if _SESSION_CONTEXT is not None:
        return _SESSION_CONTEXT.get("role") == "admin"
    fingerprint = _get_ssh_fingerprint()
    return is_admin(fingerprint, group)


def _session_role(group: str | None = None) -> str:
    """Resolve the roster role for tools/list and tools/call filtering."""
    context = _session_context_for_call(group)
    return str(context.get("role") or "analyst")


def _session_context_for_call(group: str | None = None) -> dict[str, Any]:
    """Resolve and freeze the complete non-secret MCP session context.

    ``_SESSION_GROUP`` is kept for compatibility with existing callers, but it
    is not sufficient for authorization: actor, role, workspace and GitHub
    scope must all come from the same roster entry and remain stable together.
    """
    global _SESSION_CONTEXT

    mcp_group = group if group is not None else _get_mcp_group()
    if _SESSION_CONTEXT is not None:
        cached_group = str(_SESSION_CONTEXT.get("group") or "") or None
        if cached_group != mcp_group:
            raise RuntimeError("AUTHENTICATION_REQUIRED: session group changed")
        return dict(_SESSION_CONTEXT)

    fingerprint = _get_ssh_fingerprint()
    context: dict[str, Any] = {
        "source": "mcp",
        "session_id": _SESSION_ID,
        "group": mcp_group,
        "role": "analyst",
        "identity_source": "development_override",
    }
    if fingerprint:
        try:
            entry = identity.resolve_identity(fingerprint) or {}
            context.update(
                {
                    "identity": fingerprint,
                    "ssh_fingerprint": fingerprint,
                    "actor_id": entry.get("actor_id"),
                    "role": str(entry.get("role") or "analyst").strip(),
                    "workspace_id": entry.get("workspace_id"),
                    "workspace_path": entry.get("workspace_path"),
                    "github_subject": entry.get("github_subject"),
                    "resource_scopes": list(entry.get("resource_scopes") or []),
                    "identity_source": "ssh_roster",
                }
            )
        except Exception as exc:
            if not _development_mode():
                raise RuntimeError("AUTHENTICATION_REQUIRED: roster could not be loaded") from exc
        if not _development_mode():
            required = ("actor_id", "role", "workspace_id", "workspace_path")
            if entry.get("group") != mcp_group or any(not entry.get(key) for key in required):
                raise RuntimeError("AUTHENTICATION_REQUIRED: roster changed or is incomplete")
    if _is_admin_session(mcp_group):
        context["role"] = "admin"
    if context["role"] not in {"analyst", "approver", "admin"}:
        raise RuntimeError("AUTHENTICATION_REQUIRED: invalid Session Context role")

    _SESSION_CONTEXT = dict(context)
    return dict(context)
_ADMIN_ONLY_TOOLS = frozenset({"deploy_alphaflow"})


def _tools_for_session(group: str | None, role: str | None = None) -> list[ToolDef]:
    """返回当前 MCP session 的 effective tool set。"""
    effective_role = role or _session_role(group)
    if group:
        visible = registry.get_tools_for_group(group)
    else:
        visible = registry.list_all()

    if not _is_admin_session(group):
        visible = [tool for tool in visible if tool.id not in _ADMIN_ONLY_TOOLS]

    for tool in registry.list_all():
        if not getattr(tool, "_meta", False) or tool in visible:
            continue
        if tool.id in _ADMIN_ONLY_META_TOOLS and not _is_admin_session(group):
            continue
        if tool.id in _APPROVER_META_TOOLS and effective_role not in {"approver", "admin"}:
            continue
        visible.append(tool)
    return sorted(visible, key=lambda tool: tool.id)


def list_tools() -> dict:
    """实现 MCP 的 ``tools/list``：返回 QUANTCODE_GROUP 过滤后的 tool。

    未设置 ``QUANTCODE_GROUP`` 环境变量时保持原行为（返回全部已注册 tool）。
    设置后仅返回该组 ``.opencode/groups/<group>/tool_allowlist.yaml`` 内的 tool。

    Day 4 俞高磊: 在列表末尾附加 run_agent meta tool（若存在），
    让 OpenCode compose agent 能发现并调用它。
    """
    _mcp_group = _get_mcp_group()
    tools = _tools_for_session(_mcp_group, _session_role(_mcp_group))
    logger.info(
        "list_tools: group=%s admin=%s → %d tools",
        _mcp_group or "(unset)",
        _is_admin_session(_mcp_group),
        len(tools),
    )

    tool_ids = [t.id for t in tools]
    logger.debug("list_tools: returning %s", tool_ids)
    return {
        "tools": [tool_def_to_mcp(t) for t in tools],
    }


def call_tool(name: str, arguments: dict) -> dict:
    """实现 MCP 的 ``tools/call``：执行 tool 并返回结果。

    返回 MCP 规定的格式::

        {
            "content": [{"type": "text", "text": "..."}],
            "isError": False
        }

    Day 4 俞高磊：ctx 注入 group（当前活跃组）+ _model（LLM 实例），
    供 run_agent 等需要完整 AgentRunner 上下文的 tool 使用。
    """
    try:
        mcp_group = _get_mcp_group()
        session_context = _session_context_for_call(mcp_group)
        session_role = str(session_context.get("role") or "analyst")
        allowed_tools = {tool.id for tool in _tools_for_session(mcp_group, session_role)}
        if name not in allowed_tools:
            raise PermissionError(
                f"tool '{name}' is not available for the authenticated session"
            )
        ctx: dict[str, Any] = {
            **session_context,
            "session_id": _SESSION_ID,
            "_model": _get_model(),
            "_allowed_tool_ids": allowed_tools,
        }
        logger.info("call_tool: %s(%s) group=%s model=%s",
                     name, json.dumps(arguments, default=str)[:200],
                     mcp_group or "(unset)",
                     "present" if ctx["_model"] else "missing")
        result = registry.call(name, arguments, ctx=ctx)
        text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error: {type(e).__name__}: {e}"}],
            "isError": True,
        }


def handle_request(req: dict) -> dict:
    """处理一条 JSON-RPC 请求，返回响应 dict。"""
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "quantcode-mcp", "version": "0.1.0"},
            },
        }
    elif method == "notifications/initialized":
        # 客户端通知，无需响应
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": list_tools(),
        }
    elif method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": call_tool(name, arguments),
        }
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def _configure_stdio_encoding() -> None:
    """Make JSON-RPC output deterministic on Windows locales such as GBK."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            continue


def serve_stdio() -> None:
    """从 stdin 读 JSON-RPC 请求，往 stdout 写响应。

    协议：每行一条 JSON。响应可选（notifications 无 id 时不写）。
    """
    _configure_stdio_encoding()
    logger.info("MCP server starting: cwd=%s python=%s group=%s "
                "QUANTCODE_API_KEY=%s",
                os.getcwd(), sys.executable,
                _get_mcp_group() or "(unset)",
                "set" if os.environ.get("QUANTCODE_API_KEY") else "MISSING")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Invalid JSON: {e}\n")
            continue
        try:
            resp = handle_request(req)
        except Exception as e:
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main() -> None:
    """入口：serve_stdio。"""
    serve_stdio()


if __name__ == "__main__":
    main()

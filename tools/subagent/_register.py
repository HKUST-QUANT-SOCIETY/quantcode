"""subagent tools — P-04 并行 subagent（FUNCTIONAL_SPEC §P-04 / ROADMAP R3 Q2）。

import 即触发 4 个 ToolDef 注册（与 tools/factor/_register.py 风格一致）：
- spawn_subagent(task/group/skill_name/budget_tokens) — 后台线程跑 AgentRunner
- check_subagent(subagent_id, wait_s)   — 轮询状态；wait_s>0 时阻塞等终态
- kill_subagent(subagent_id, reason)    — 协作式 kill（cancel flag + join）
- list_subagents(parent_thread_id)      — 任务树

权限边界：
- 四个 tool 均为 **元工具**（_meta=True 风格的编排层）：子任务继承父 ctx 的
  group 校验——目标 group 必须在 ``.opencode/authorized_groups.yaml``（或
  QUANTCODE_GROUP env 指定）的允许集内，越权 fail-closed（架构 §3.4 组隔离）。
- spawn/kill 有副作用：不写入各组 tool_allowlist（LLM 不应自主 spawn），
  经 mcp_server._meta 通道仅向控制器暴露（list_subagents）。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tools.registry import ToolDef, registry

VALID_GROUPS = ("model", "risk", "factor", "fundamental", "options", "strategy")


# ---------------------------------------------------------------------------
# Helpers（工具之间共享，保持薄）
# ---------------------------------------------------------------------------


def _allowed_groups(ctx: dict) -> set[str]:
    """父会话允许的 group 集合：显式注入优先，无约束时全集。

    - ctx["allowed_groups"]（list/str）→ 直接使用（测试/编排器显式窄化）
    - ctx["group"] → 单组会话（SSH 绑定或 QUANTCODE_GROUP）
    - 都没有 → 全部六组（本地单用户降级，与 mcp_server 无组过滤语义一致）
    """
    explicit = ctx.get("allowed_groups")
    if explicit:
        if isinstance(explicit, str):
            return {explicit}
        return {str(g) for g in explicit}
    parent = str(ctx.get("group") or "")
    if parent:
        return {parent}
    return set(VALID_GROUPS)


def _check_group_permitted(group: str, ctx: dict) -> str | None:
    """子 group 必须在父允许集内；返回错误信息或 None。"""
    if group not in VALID_GROUPS:
        return f"invalid group '{group}', valid: {', '.join(VALID_GROUPS)}"
    allowed = _allowed_groups(ctx)
    if allowed and group not in allowed:
        return (
            f"group '{group}' is not permitted for this session "
            f"(allowed: {', '.join(sorted(allowed))})"
        )
    return None


def _is_admin_context(ctx: dict) -> bool:
    return str(ctx.get("role") or "").strip() == "admin"


def _owns_subagent(snapshot: dict, ctx: dict) -> bool:
    """A non-admin may only inspect children spawned by its current thread."""
    if _is_admin_context(ctx):
        return True
    parent = str(ctx.get("thread_id") or ctx.get("session_id") or "")
    if not parent or not ctx.get("group"):
        return True  # trusted embedded/dev callers retain legacy local behavior
    return snapshot.get("parent_thread_id") == parent and snapshot.get("group") == ctx.get("group")


def _resolve_model(ctx: dict) -> Any | None:
    """优先 ctx['_model']（mcp_server 注入），退化 mcp_server._get_model()。"""
    model = ctx.get("_model")
    if model is None:
        try:
            from quantcode.mcp_server import _get_model

            model = _get_model()
        except Exception:
            model = None
    return model


def _checkpoint_db_arg(ctx: dict) -> str | None:
    """ctx["_checkpoint_db"]（测试注入）→ str 路径；缺省 None → registry 默认 DB。"""
    db = ctx.get("_checkpoint_db")
    return str(db) if db is not None else None


# ---------------------------------------------------------------------------
# spawn_subagent
# ---------------------------------------------------------------------------


class SpawnSubagentArgs(BaseModel):
    """spawn_subagent 入参（P-04 契约含 budget）。"""

    task: str = Field(min_length=1, description="子任务描述文本（自然语言）。")
    group: str = Field(description="子任务运行组（model/risk/factor/fundamental/options/strategy）。")
    skill_name: str | None = Field(default=None, description="可选：子任务加载的 skill 名。")
    budget_tokens: int | None = Field(default=None, description="可选：子任务 token 预算（超限暂停待人审，不 kill）。")


def _spawn_subagent_execute(args: SpawnSubagentArgs, ctx: dict) -> dict:
    group = args.group.strip()
    err = _check_group_permitted(group, ctx)
    if err:
        return {"status": "error", "error": err}
    parent_group = str(ctx.get("group") or "").strip()
    if parent_group and group != parent_group:
        return {
            "status": "error",
            "error": f"child group '{group}' is not permitted; must inherit parent session group '{parent_group}'",
        }
    model = _resolve_model(ctx)
    if model is None:
        return {
            "status": "error",
            "error": "No LLM model configured (ctx['_model'] missing / QUANTCODE_API_KEY unset).",
        }

    parent_budget = ctx.get("budget_tokens")
    parent_used = int(ctx.get("budget_used") or 0)
    if isinstance(parent_budget, (int, float)) and parent_budget > 0:
        remaining = max(int(parent_budget) - parent_used, 0)
        if args.budget_tokens is not None and args.budget_tokens > remaining:
            return {
                "status": "error",
                "error": f"child budget {args.budget_tokens} exceeds parent remaining budget {remaining}",
            }

    from runner.task_classifier import classify_task

    classification = classify_task(args.task, file_count=0, cross_repo=False)

    from runner.parallel_registry import MAX_TREE_DEPTH, parallel_registry

    try:
        entry = parallel_registry.create_subagent(
            args.task,
            group,
            skill_name=args.skill_name,
            budget_tokens=args.budget_tokens,
            parent_thread_id=str(ctx.get("thread_id") or ctx.get("session_id") or ""),
            model=model,
            checkpoint_db=_checkpoint_db_arg(ctx),
            allowed_tool_ids=ctx.get("_allowed_tool_ids"),
            actor_id=ctx.get("actor_id"),
            role=ctx.get("role"),
            session_id=ctx.get("session_id"),
            workspace_id=ctx.get("workspace_id"),
            workspace_path=ctx.get("workspace_path"),
            github_subject=ctx.get("github_subject"),
            resource_scopes=ctx.get("resource_scopes"),
            solution_required=classification.solution_required,
        )
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    entry["max_tree_depth"] = MAX_TREE_DEPTH
    return entry


# ---------------------------------------------------------------------------
# check_subagent
# ---------------------------------------------------------------------------


class CheckSubagentArgs(BaseModel):
    """check_subagent 入参。"""

    subagent_id: str = Field(min_length=1, description="spawn 返回的 subagent_id。")
    wait_s: float = Field(default=0, ge=0, le=120, description="阻塞等待终态的秒数（0=立即返回当前快照）。")


def _check_subagent_execute(args: CheckSubagentArgs, ctx: dict) -> dict:
    from runner.parallel_registry import TERMINAL_STATUSES, parallel_registry

    deadline = args.wait_s and (args.wait_s > 0)
    waited = 0.0
    interval = 0.05
    while True:
        try:
            snap = parallel_registry.get_status(args.subagent_id)
        except KeyError:
            return {"status": "error", "error": f"subagent '{args.subagent_id}' not found"}
        if not _owns_subagent(snap, ctx):
            return {"status": "error", "error": "PERMISSION_DENIED: subagent is outside this session"}
        if not deadline_wait(snap, TERMINAL_STATUSES) or not deadline_active(deadline, waited, args.wait_s):
            return snap
        import time as _time

        _time.sleep(interval)
        waited += interval


def deadline_wait(snapshot: dict, terminal: frozenset[str]) -> bool:
    """True = 还需要继续等（未到终态）。"""
    return snapshot.get("status") not in terminal


def deadline_active(wait_enabled: bool, waited: float, wait_s: float) -> bool:
    return bool(wait_enabled) and waited < wait_s


# ---------------------------------------------------------------------------
# kill_subagent
# ---------------------------------------------------------------------------


class KillSubagentArgs(BaseModel):
    """kill_subagent 入参。"""

    subagent_id: str = Field(min_length=1, description="要终止的 subagent_id。")
    reason: str = Field(default="", description="终止原因（写入审计/状态）。")


def _kill_subagent_execute(args: KillSubagentArgs, ctx: dict) -> dict:
    from runner.parallel_registry import parallel_registry

    try:
        snapshot = parallel_registry.get_status(args.subagent_id)
        if not _owns_subagent(snapshot, ctx):
            return {"status": "error", "error": "PERMISSION_DENIED: subagent is outside this session"}
        return parallel_registry.kill(args.subagent_id, reason=args.reason)
    except KeyError:
        return {"status": "error", "error": f"subagent '{args.subagent_id}' not found"}


# ---------------------------------------------------------------------------
# list_subagents（任务树）
# ---------------------------------------------------------------------------


class ListSubagentsArgs(BaseModel):
    """list_subagents 入参 — 只读枚举某父线程下的子任务。"""

    parent_thread_id: str = Field(default="", description="父 run 的 thread_id；空=列出全部 subagent。")


def _list_subagents_execute(args: ListSubagentsArgs, ctx: dict) -> dict:
    from runner.parallel_registry import MAX_TREE_DEPTH, parallel_registry

    current_parent = str(ctx.get("thread_id") or ctx.get("session_id") or "")
    if args.parent_thread_id and current_parent and args.parent_thread_id != current_parent and not _is_admin_context(ctx):
        return {"status": "error", "error": "PERMISSION_DENIED: parent thread is outside this session"}
    pid = args.parent_thread_id or current_parent
    if not pid and ctx.get("group") and not _is_admin_context(ctx):
        return {"status": "error", "error": "PERMISSION_DENIED: parent thread is required"}
    children = parallel_registry.list_children(pid) if pid else _list_all()
    return {
        "parent_thread_id": pid,
        "children": children,
        "count": len(children),
        "max_tree_depth": MAX_TREE_DEPTH,
    }


def _list_all() -> list[dict]:
    from runner.parallel_registry import parallel_registry

    with parallel_registry._lock:
        ids = sorted(parallel_registry._entries)
    return [parallel_registry.get_status(sid) for sid in ids]


# ---------------------------------------------------------------------------
# ToolDefs
# ---------------------------------------------------------------------------

spawn_subagent_tool = ToolDef(
    id="spawn_subagent",
    description=(
        "Spawn a parallel subagent (P-04): runs AgentRunner(group, budget) in a "
        "background thread and returns {'status':'running','subagent_id',...}. "
        "The child group must be within this session's allowed groups. "
        "Poll with check_subagent; cancel with kill_subagent. Budget-exhausted "
        "children pause (waiting_for_human) instead of dying."
    ),
    schema=SpawnSubagentArgs,
    execute=_spawn_subagent_execute,
)
check_subagent_tool = ToolDef(
    id="check_subagent",
    description=(
        "Read subagent status snapshot (status/budget_used/output_data/trace). "
        "wait_s>0 blocks until a terminal state (completed/stopped/aborted/"
        "waiting_for_human/error) or timeout."
    ),
    schema=CheckSubagentArgs,
    execute=_check_subagent_execute,
)
kill_subagent_tool = ToolDef(
    id="kill_subagent",
    description=(
        "Cooperatively cancel a running subagent: sets its stop flag; the child "
        "aborts before its next LLM step. Idempotent on already-finished agents."
    ),
    schema=KillSubagentArgs,
    execute=_kill_subagent_execute,
)
list_subagents_tool = ToolDef(
    id="list_subagents",
    description=(
        "Read-only task tree query (P-04): list subagents under a parent "
        "thread_id with status/budget/task info. Empty parent filters to all."
    ),
    schema=ListSubagentsArgs,
    execute=_list_subagents_execute,
)

# 有副作用的编排元工具：不进各组 allowlist，控制器经 _meta 通道发现。
spawn_subagent_tool._meta = True   # type: ignore[attr-defined]
kill_subagent_tool._meta = True    # type: ignore[attr-defined]
list_subagents_tool._meta = True   # type: ignore[attr-defined]
# check_subagent 只是读快照，同样经 meta 通道暴露（不供子 agent 递归调用）。
check_subagent_tool._meta = True   # type: ignore[attr-defined]

for _t in (spawn_subagent_tool, check_subagent_tool, kill_subagent_tool, list_subagents_tool):
    registry._tools[_t.id] = _t  # 幂等覆盖（reload 安全）


__all__ = [
    "spawn_subagent_tool",
    "check_subagent_tool",
    "kill_subagent_tool",
    "list_subagents_tool",
    "VALID_GROUPS",
]

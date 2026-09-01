"""Register solution workflow tools (P-10 方案先行) to the global registry.

四工具 = /solution 流程的动作面（specs/FUNCTIONAL_SPEC.md P-10）：
- ``draft_solution``    开启方案文档（status=draft，激活阶段限流）
- ``revise_solution``   记录一轮人机讨论（feedback 必填）
- ``freeze_solution``   冻结方案（confirm=True 显式确认 + 轮次 >= min_rounds）
- ``solution_status``   只读：查方案当前状态/轮次/偏离面

设计说明：
- 状态机与双写落盘在 ``runner/solution_workflow.py``（本模块只做参数校验 + 调用）；
- ``permission`` 保持 None（=allow）：P-10 是流程阶段约束，不是权限门禁，
  **不得**给方案工具配 ask/deny 制造新的 HumanGate 触发点；
- 领域性拒绝（轮次不足 / 重复 id / 未显式确认等）返回 ``{"ok": False, "error": ...}``
  而不是抛异常——tool_node 对非 read_ 前缀工具的异常做脱敏（只留类名），
  会吞掉拒绝原因；方案工具的拒绝原因是给 LLM 的纠偏指引，必须可见。
  ponytail: 仅包装 SolutionWorkflowError（预期内领域拒绝），意外异常照常上抛。
- 成功输出统一携带 ``solution_id`` + ``solution_phase``，经
  runner/agent_nodes._extract_state_fields 注入 AgentState，激活后续阶段限流。

接线注意：本模块需被 import 才会注册（与 tools/risk 等同模式）。注册 import 行
在 ``quantcode/mcp_server.py`` 的注册块——该文件属 AG-C/AG-D 独占窗口，AG-J
不触碰；已按交接约定移交 AG-D W3 加一行
``import tools.solution._register  # noqa: F401  触发 solution tool 注册（P-10）``。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

import runner.solution_workflow as sw
from schemas.solution_doc import SolutionDoc
from tools.registry import ToolDef, register_tool


def _store_from_ctx(ctx: dict | None) -> sw.SolutionStore:
    """ctx 携带 blackboard_db_path（make_tool_node 注入）→ 同一 bb 文件。"""
    return sw.SolutionStore(blackboard_db_path=(ctx or {}).get("blackboard_db_path"))


def _doc_payload(doc: SolutionDoc) -> dict[str, Any]:
    cfg = sw.load_workflow_config()
    return {
        "ok": True,
        "solution_id": str(doc.id),
        "solution_phase": str(doc.status.value),
        "status": str(doc.status.value),
        "version": doc.version,
        "doc_hash": doc.doc_hash,
        "rounds": len(doc.rounds),
        "min_rounds": cfg["min_rounds"],
        "max_rounds": cfg["max_rounds"],
        "needs_human": doc.needs_human,
        "file_impact": list(doc.file_impact),
        "acceptance_criteria": list(doc.acceptance_criteria),
    }


def _error_payload(e: sw.SolutionWorkflowError) -> dict[str, Any]:
    return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 参数 schema
# ---------------------------------------------------------------------------


class DraftSolutionArgs(BaseModel):
    goal: str = Field(min_length=1, description="任务目标（自然语言，方案围绕它展开）")
    doc_id: str | None = Field(
        default=None, description="方案 id（省略时按 goal 派生稳定 id）；重复 id 会被拒绝"
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="验收标准（一致性判定的语义输入）"
    )
    file_impact: list[str] = Field(
        default_factory=list,
        description="预期改动文件面（repo 相对路径）；之外的改动会在一致性判定中列为偏离",
    )
    trivial: bool = Field(
        default=False,
        description="trivial 单点修复豁免声明（需 configs/solution_workflow.yaml 开启开关）",
    )


class ReviseSolutionArgs(BaseModel):
    doc_id: str = Field(min_length=1, description="方案 id")
    feedback: str = Field(min_length=1, description="本轮人的反馈（必填，不可为空）")
    revision: str = Field(default="", description="本轮对方案的修订摘要（可空=未改动）")


class FreezeSolutionArgs(BaseModel):
    doc_id: str = Field(min_length=1, description="方案 id")
    confirm: bool = Field(
        default=False,
        description="用户显式确认冻结（必须为 true；讨论轮次 >= min_rounds 才会被接受）",
    )


class SolutionStatusArgs(BaseModel):
    doc_id: str = Field(min_length=1, description="方案 id")


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


def _draft_execute(args: DraftSolutionArgs, ctx: dict) -> dict[str, Any]:
    try:
        doc = sw.start_solution(
            args.goal,
            doc_id=args.doc_id,
            acceptance_criteria=args.acceptance_criteria,
            file_impact=args.file_impact,
            trivial=args.trivial,
            store=_store_from_ctx(ctx),
        )
    except sw.SolutionWorkflowError as e:
        return _error_payload(e)
    return _doc_payload(doc)


def _revise_execute(args: ReviseSolutionArgs, ctx: dict) -> dict[str, Any]:
    try:
        doc = sw.add_round(
            args.doc_id,
            args.feedback,
            revision=args.revision,
            store=_store_from_ctx(ctx),
        )
    except sw.SolutionWorkflowError as e:
        return _error_payload(e)
    return _doc_payload(doc)


def _freeze_execute(args: FreezeSolutionArgs, ctx: dict) -> dict[str, Any]:
    try:
        doc = sw.freeze_solution(args.doc_id, confirm=args.confirm, store=_store_from_ctx(ctx))
    except sw.SolutionWorkflowError as e:
        return _error_payload(e)
    return _doc_payload(doc)


def _status_execute(args: SolutionStatusArgs, ctx: dict) -> dict[str, Any]:
    doc = sw.get_solution(args.doc_id, store=_store_from_ctx(ctx))
    if doc is None:
        return {"ok": False, "error": f"方案不存在：{args.doc_id}（先用 draft_solution 创建）"}
    return _doc_payload(doc)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

draft_solution_tool = ToolDef(
    id="draft_solution",
    description=(
        "P-10 方案先行：开启方案文档（status=draft）。非平凡任务必须先出完整方案 "
        "（目标/验收标准/预期改动文件面），经人机讨论轮次后才能 freeze；draft 态下"
        "写类代码工具不可用。trivial=True 仅限单点修复且需配置开启豁免。"
    ),
    schema=DraftSolutionArgs,
    execute=_draft_execute,
)

revise_solution_tool = ToolDef(
    id="revise_solution",
    description=(
        "P-10 方案先行：记录一轮人机讨论（人的反馈必填，可附方案修订摘要）。"
        "freeze 要求讨论轮次 >= min_rounds（默认 2）。"
    ),
    schema=ReviseSolutionArgs,
    execute=_revise_execute,
)

freeze_solution_tool = ToolDef(
    id="freeze_solution",
    description=(
        "P-10 方案先行：冻结方案（draft → frozen），需 confirm=true 的用户显式确认；"
        "冻结后阶段限流解除，代码工具恢复可用，实现以冻结文档为一致性判定基准。"
    ),
    schema=FreezeSolutionArgs,
    execute=_freeze_execute,
)

solution_status_tool = ToolDef(
    id="solution_status",
    description=(
        "P-10 方案先行：只读查询方案当前状态（status/轮次/file_impact/doc_hash/"
        "needs_human 人裁标记）。"
    ),
    schema=SolutionStatusArgs,
    execute=_status_execute,
)

register_tool(draft_solution_tool)
register_tool(revise_solution_tool)
register_tool(freeze_solution_tool)
register_tool(solution_status_tool)

__all__ = [
    "draft_solution_tool",
    "revise_solution_tool",
    "freeze_solution_tool",
    "solution_status_tool",
]

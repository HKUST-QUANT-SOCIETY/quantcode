"""P-10 方案先行工作流引擎 — 状态机 + 阶段限流钩子（specs/FUNCTIONAL_SPEC.md P-10）。

职责两块：

1. **SolutionDoc 状态机**（draft → frozen → superseded）：
   - ``start_solution`` / ``add_round`` / ``freeze_solution`` / ``supersede_solution``；
   - freeze 需**用户显式确认**（confirm=True）且讨论轮次 ≥ ``min_rounds``；
   - 讨论轮次达 ``max_rounds`` 仍处 draft → 置 ``needs_human`` 人裁标记；
   - trivial 单点修复可显式豁免（开关 ``allow_trivial_exempt``，默认关）。
   - 双写落盘：``artifacts/solutions/<id>-v<n>.md`` + Blackboard
     ``shared.solutions.<id>``（key 经 runner/blackboard_keys 归一）。

2. **阶段限流钩子**（供 runner/agent_nodes.py 的 tool 过滤段调用）：
   - draft 态白名单 = 方案类工具（SOLUTION_TOOLS）+ 只读工具（前缀判定）；
   - 写类工具被 deny，返回"方案未冻结，代码工具不可用"拒绝信息；
   - frozen 后解除。
   - **实现为 tool 过滤，不是 interrupt**——不新增 HumanGate 触发点
     （P-10 语义边界：流程阶段约束，不是权限门禁）。

配置：``configs/solution_workflow.yaml``（min_rounds / max_rounds /
allow_trivial_exempt），经 runner/config_loader.load_yaml（lru_cache）读取，
缺失时代码默认兜底。
"""
from __future__ import annotations

import functools
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from runner.blackboard import BlackboardService
from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
from runner.config_loader import PROJECT_ROOT as _CONFIG_ROOT, load_yaml
from schemas import BlackboardScope, GroupName, WritePolicy
from schemas.solution_doc import SolutionDoc, SolutionRound, SolutionStatus

# 方案文档默认落盘目录（测试可经 SolutionStore(artifacts_dir=...) 覆盖）。
SOLUTIONS_DIR = _CONFIG_ROOT / "artifacts" / "solutions"

# 平台级写入的诚实占位 task_id（TASK_ID_PATTERN 只接受 T<digits>(.<digits>)*；
# T0 = 未分配任务，与 tools/model/write_blackboard._synthesize_task_id 同约定）。
_SOLUTION_TASK_ID = "T0.0"

__all__ = [
    "SOLUTION_TOOLS",
    "PHASE_DENY_MESSAGE",
    "READONLY_TOOL_PREFIXES",
    "SolutionStore",
    "SolutionWorkflowError",
    "filter_tools_for_phase",
    "freeze_solution",
    "get_solution",
    "is_readonly_tool",
    "load_workflow_config",
    "add_round",
    "start_solution",
    "supersede_solution",
    "sync_phase_from_blackboard",
    "tool_allowed_in_phase",
    "tool_denied_message",
]


# ---------------------------------------------------------------------------
# 阶段限流钩子（agent_nodes tool 过滤段消费；纯函数，无状态）
# ---------------------------------------------------------------------------

# 方案类工具（tools/solution/_register.py 注册；draft 态白名单成员）。
SOLUTION_TOOLS = (
    "draft_solution",
    "revise_solution",
    "freeze_solution",
    "solution_status",
)

# 只读工具前缀白名单（draft 态与方案类工具一并放行）。
#
# 写类工具判定依据（2026-09-01 对 tools.registry 全量 48 个注册工具的命名/元数据
# 盘点）：registry 内不存在通用 file 写/edit 工具（write_file/bash 等是 OpenCode
# 平台侧 tool，不经本 registry，见 tests/test_allowlist_consistency.py 的
# PLATFORM_TOOLS）；registry 内的写/副作用类按命名归纳为 write_*（write_blackboard、
# write_pr_comment）、merge_to_main（共享写入）、deployment_candidate（Admin 交接）、
# spawn_subagent / trigger_risk_flow（流程副作用）、run_*（执行类）、
# generate_* / mark_task_done 等——它们全部不命中下列只读前缀。
# 因此采用**白名单**实现：命中只读前缀或方案类工具 → 放行，其余一律视为写类
# deny（fail-closed，新写类工具默认被限，零维护）。
# ponytail: 前缀白名单而非逐个枚举 deny 名单——新只读工具按命名自动放行。
READONLY_TOOL_PREFIXES = (
    "read_",
    "list_",
    "get_",
    "extract_",
    "describe_",
    "check_",
    "match_",
    "search_",
    "pit_",
    "pool_",
    "request_",
)
READONLY_TOOL_IDS = frozenset({"risk_verdict", "portfolio_verdict"})

# 拒绝信息（P-10 验收草案断言文案："方案未冻结，代码工具不可用"）。
PHASE_DENY_MESSAGE = "方案未冻结，代码工具不可用"


def is_readonly_tool(tool_id: str) -> bool:
    """按前缀白名单判定只读工具（draft 态放行）。"""
    return tool_id in READONLY_TOOL_IDS or str(tool_id).startswith(READONLY_TOOL_PREFIXES)


def tool_allowed_in_phase(
    tool_id: str,
    phase: str | None,
    *,
    solution_required: bool = False,
) -> bool:
    """阶段限流判定：仅 draft 态收窄为「方案类工具 + 只读工具」白名单。

    只有有效 frozen 方案，或未要求方案且未启动工作流时放行写操作。
    已废弃、丢失或无法验证的方案不能作为继续执行的依据。
    """
    if phase == "frozen" or (phase is None and not solution_required):
        return True
    return tool_id in SOLUTION_TOOLS or is_readonly_tool(tool_id)


def tool_denied_message(tool_id: str) -> str:
    """draft 态写类工具的拒绝信息（进 ToolMessage，给 LLM 可读的纠偏指引）。"""
    return (
        f"{PHASE_DENY_MESSAGE}（P-10 方案先行：当前方案未冻结、已失效或无法验证，仅放行方案类工具 "
        f"{list(SOLUTION_TOOLS)} 与只读工具）。被拒工具：{tool_id}。"
        "请先用 draft_solution 产出完整方案、经讨论轮次后 freeze_solution。"
    )


def filter_tools_for_phase(
    tools: Iterable[Any],
    phase: str | None,
    *,
    solution_required: bool = False,
) -> list[Any]:
    """按阶段过滤 tool 列表（llm_node 提供给模型的可见工具面）。

    元素为 ToolDef（取 .id）或裸 str 均可。未要求方案且 phase != "draft" 时
    原样返回；L2/L3 的 phase=None 按 draft 白名单处理。
    """
    return [
        t for t in tools
        if tool_allowed_in_phase(
            getattr(t, "id", t), phase, solution_required=solution_required
        )
    ]


# ---------------------------------------------------------------------------
# 配置（runner/config_loader 既有模式：load_yaml + lru_cache + 代码默认兜底）
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def load_workflow_config() -> dict[str, Any]:
    """读 configs/solution_workflow.yaml → {min_rounds, max_rounds, allow_trivial_exempt}。

    缺文件/坏 YAML/缺键 → 代码默认（min_rounds=2 / max_rounds=3 / 豁免关）。
    测试或运行期改配置后调 ``load_workflow_config.cache_clear()``。
    """
    cfg = load_yaml("solution_workflow")
    try:
        min_rounds = max(1, int(cfg.get("min_rounds", 2)))
    except (TypeError, ValueError):
        min_rounds = 2
    try:
        max_rounds = max(min_rounds, int(cfg.get("max_rounds", 3)))
    except (TypeError, ValueError):
        max_rounds = max(min_rounds, 3)
    allow_exempt = bool(cfg.get("allow_trivial_exempt", False))
    return {
        "min_rounds": min_rounds,
        "max_rounds": max_rounds,
        "allow_trivial_exempt": allow_exempt,
    }


class SolutionWorkflowError(ValueError):
    """状态机拒绝（轮次不足 / 未显式确认 / 超轮数需人裁 / 豁免未开启等）。"""


# ---------------------------------------------------------------------------
# SolutionStore — 状态机 + 双写落盘（memory → blackboard + artifacts md）
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_doc_hash(doc: SolutionDoc) -> str:
    """方案内容摘要：sha256 前 16 位（排除 doc_hash/updated_at 自身，可复核）。"""
    payload = doc.model_dump(mode="json")
    payload.pop("doc_hash", None)
    payload.pop("updated_at", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def render_doc_markdown(doc: SolutionDoc) -> str:
    """SolutionDoc → 静态 Markdown（冻结后的人可读文档）。"""
    lines = [
        f"# SolutionDoc {doc.id} (v{doc.version})",
        "",
        f"- status: `{doc.status.value if isinstance(doc.status, SolutionStatus) else doc.status}`",
        f"- doc_hash: `{doc.doc_hash}`",
        f"- created_at: {doc.created_at}",
        f"- trivial_exempt: {doc.trivial_exempt}" if doc.trivial_exempt else None,
        f"- needs_human: {doc.needs_human}" if doc.needs_human else None,
        "",
        "## Goal",
        "",
        doc.goal,
        "",
        "## Discussion Rounds",
        "",
    ]
    if doc.rounds:
        for r in doc.rounds:
            lines.append(f"### Round {r.round_no} ({r.at})")
            lines.append("")
            lines.append(f"- feedback: {r.feedback}")
            if r.revision:
                lines.append(f"- revision: {r.revision}")
            lines.append("")
    else:
        lines.append("(无讨论轮次记录)" + "")
        lines.append("")
    lines += ["## Acceptance Criteria", ""]
    lines += [f"- {c}" for c in doc.acceptance_criteria] or ["(未填写)"]
    lines += ["", "## File Impact", ""]
    lines += [f"- `{f}`" for f in doc.file_impact] or ["(未填写)"]
    return "\n".join([ln for ln in lines if ln is not None]) + "\n"


class SolutionStore:
    """SolutionDoc 仓储：进程内缓存 + Blackboard ``shared.solutions.*`` + md 文件。

    - ``blackboard_db_path``/``artifacts_dir`` 可注入（测试隔离；None → 默认路径）；
    - Blackboard 写 PROJECT scope（跨组可读），key 经 make_read_key 归一；
    - 每次落盘 version+1，md 文件名 ``<id>-v<version>.md``（保留历史版本）。
    """

    def __init__(
        self,
        *,
        blackboard_db_path: str | Path | None = None,
        artifacts_dir: str | Path | None = None,
    ) -> None:
        self.db_path = Path(blackboard_db_path) if blackboard_db_path else None
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else SOLUTIONS_DIR

    # ----- blackboard -----
    def _service(self) -> BlackboardService:
        # ponytail: 每次新建 service（sqlite 连接便宜），避免持有连接的跨线程问题
        return BlackboardService(
            db_path=self.db_path,
            session_id=PROJECT_SESSION_ID,
            requester_group=None,
        )

    @staticmethod
    def blackboard_key(doc_id: str) -> str:
        """Blackboard 条目 key（make_read_key 归一；``shared.`` 开头原样保留）。"""
        return make_read_key(f"shared.solutions.{doc_id}")

    def _persist(self, doc: SolutionDoc) -> SolutionDoc:
        doc = doc.model_copy(update={"updated_at": _utc_now_iso()})
        payload = doc.model_dump(mode="json")
        self._service().write_value(
            scope=BlackboardScope.PROJECT,
            key=self.blackboard_key(str(doc.id)),
            value=payload,
            write_policy=WritePolicy.OWNER,
            written_by_task_id=_SOLUTION_TASK_ID,
            # ponytail: written_by_group 为 schema 必填；方案是平台级流程文档，
            # PROJECT scope 无组隔离语义，署名借用 model 组（与 write_blackboard
            # 的 ctx 缺省同约定），不做权限语义。
            written_by_group=GroupName.MODEL,
        )
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        md_path = self.artifacts_dir / f"{doc.id}-v{doc.version}.md"
        md_path.write_text(render_doc_markdown(doc), encoding="utf-8")
        return doc

    # ----- CRUD -----
    def save(self, doc: SolutionDoc) -> SolutionDoc:
        return self._persist(doc)

    def get(self, doc_id: str) -> SolutionDoc | None:
        entry = self._service().get_entry(BlackboardScope.PROJECT, None, self.blackboard_key(doc_id))
        if entry is None or not isinstance(entry.value, dict):
            return None
        try:
            doc = SolutionDoc.model_validate(entry.value)
        except Exception:
            return None
        if not doc.doc_hash or doc.doc_hash != compute_doc_hash(doc):
            raise SolutionWorkflowError(f"方案 {doc_id} 内容摘要不匹配，请恢复有效版本")
        return doc


_DEFAULT_STORE: SolutionStore | None = None


def get_store() -> SolutionStore:
    """默认仓储（懒创建；避免 import 期触碰 .quantcode/blackboard.db）。"""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SolutionStore()
    return _DEFAULT_STORE


def sync_phase_from_blackboard(
    phase: str | None,
    doc_id: str | None,
    blackboard_db_path: str | Path | None,
    *,
    store: SolutionStore | None = None,
) -> str | None:
    """workflow 激活时从 Blackboard 回源 SolutionDoc 当前状态（agent_nodes tool 段用）。

    跨进程语义：/solution 面板（AG-G）在同一 blackboard db 上冻结文档后，
    run 侧下一次 tool 执行即可读到 frozen、解除限流。

    无工作流时不读库；已关联的方案每次读当前版本。
    文档丢失、读取失败或摘要不符时返回 invalid，限制为只读与方案修复工具。
    """
    if not doc_id:
        return "invalid" if phase else None
    try:
        doc = (store or SolutionStore(blackboard_db_path=blackboard_db_path)).get(str(doc_id))
    except Exception:
        return "invalid"
    if doc is None:
        return "invalid"
    return str(doc.status.value)


# ---------------------------------------------------------------------------
# 状态机操作（模块级便捷入口；store 可注入）
# ---------------------------------------------------------------------------

def start_solution(
    goal: str,
    *,
    doc_id: str | None = None,
    acceptance_criteria: list[str] | None = None,
    file_impact: list[str] | None = None,
    trivial: bool = False,
    store: SolutionStore | None = None,
) -> SolutionDoc:
    """开启一个方案文档（status=draft）。

    trivial=True 且配置开启豁免 → 直接以 frozen 落库留痕（跳过讨论轮次）；
    配置未开启豁免 → SolutionWorkflowError。
    """
    if not str(goal or "").strip():
        raise SolutionWorkflowError("goal 不能为空")
    cfg = load_workflow_config()
    if trivial and not cfg["allow_trivial_exempt"]:
        raise SolutionWorkflowError(
            "trivial 豁免未开启（configs/solution_workflow.yaml: allow_trivial_exempt），"
            "非平凡任务必须走方案先行流程"
        )
    sid = str(doc_id or "").strip() or _derive_doc_id(goal)
    if store is None:
        store = get_store()
    if store.get(sid) is not None:
        raise SolutionWorkflowError(f"方案 id 已存在：{sid}（请换 id 或用 revise_solution）")
    doc = SolutionDoc(
        id=sid,
        goal=goal.strip(),
        status=SolutionStatus.FROZEN if trivial else SolutionStatus.DRAFT,
        acceptance_criteria=[str(c) for c in (acceptance_criteria or []) if str(c).strip()],
        file_impact=[str(f) for f in (file_impact or []) if str(f).strip()],
        trivial_exempt=trivial,
        created_at=_utc_now_iso(),
    )
    doc = doc.model_copy(update={"doc_hash": compute_doc_hash(doc)})
    return store.save(doc)


def add_round(
    doc_id: str,
    feedback: str,
    *,
    revision: str = "",
    store: SolutionStore | None = None,
) -> SolutionDoc:
    """记录一轮人机讨论（feedback 必填；revision 为该轮方案修订摘要）。

    仅 draft 态可加轮；轮次达 max_rounds 后再要求加轮 → 拒绝并提示需要人裁
    （文档已置 needs_human=True 标记）。
    """
    if not str(feedback or "").strip():
        raise SolutionWorkflowError("讨论轮次的 feedback 不能为空")
    doc = _require(doc_id, store)
    if doc.status != SolutionStatus.DRAFT:
        raise SolutionWorkflowError(f"方案 {doc_id} 已是 {doc.status.value}，不可再加讨论轮次")
    cfg = load_workflow_config()
    if len(doc.rounds) >= cfg["max_rounds"]:
        raise SolutionWorkflowError(
            f"讨论轮次已达上限（{len(doc.rounds)}/{cfg['max_rounds']}），"
            "需要人裁：请人工裁决冻结、废弃或放宽轮次上限"
        )
    doc = doc.model_copy(update={
        "rounds": list(doc.rounds) + [SolutionRound(
            round_no=len(doc.rounds) + 1,
            feedback=feedback.strip(),
            revision=str(revision or "").strip(),
            at=_utc_now_iso(),
        )],
        "version": doc.version + 1,
        "needs_human": len(doc.rounds) + 1 >= cfg["max_rounds"],
    })
    doc = doc.model_copy(update={"doc_hash": compute_doc_hash(doc)})
    return (store or get_store()).save(doc)


def freeze_solution(
    doc_id: str,
    *,
    confirm: bool = False,
    store: SolutionStore | None = None,
) -> SolutionDoc:
    """冻结方案（draft → frozen）。用户显式确认（confirm=True）且
    讨论轮次 ≥ min_rounds 才放行；否则 SolutionWorkflowError。
    """
    doc = _require(doc_id, store)
    if doc.status == SolutionStatus.FROZEN:
        return doc  # 幂等：重复冻结返回原样
    if doc.status != SolutionStatus.DRAFT:
        raise SolutionWorkflowError(f"方案 {doc_id} 状态为 {doc.status.value}，不可冻结")
    if not confirm:
        raise SolutionWorkflowError("冻结需用户显式确认（confirm=True）")
    cfg = load_workflow_config()
    n = len(doc.rounds)
    if n < cfg["min_rounds"]:
        raise SolutionWorkflowError(
            f"讨论轮次不足（{n}/{cfg['min_rounds']}），冻结被拒；"
            "请先经人机讨论（revise_solution 记录每轮 feedback）"
        )
    doc = doc.model_copy(update={
        "status": SolutionStatus.FROZEN,
        "needs_human": False,
        "version": doc.version + 1,
    })
    doc = doc.model_copy(update={"doc_hash": compute_doc_hash(doc)})
    return (store or get_store()).save(doc)


def supersede_solution(doc_id: str, *, store: SolutionStore | None = None) -> SolutionDoc:
    """废弃方案（frozen → superseded；draft 也可直接废弃）。"""
    doc = _require(doc_id, store)
    if doc.status == SolutionStatus.SUPERSEDED:
        return doc
    doc = doc.model_copy(update={
        "status": SolutionStatus.SUPERSEDED,
        "version": doc.version + 1,
    })
    doc = doc.model_copy(update={"doc_hash": compute_doc_hash(doc)})
    return (store or get_store()).save(doc)


def get_solution(doc_id: str, *, store: SolutionStore | None = None) -> SolutionDoc | None:
    """按 id 读取 Blackboard 当前方案并校验摘要。"""
    return (store or get_store()).get(doc_id)


def _require(doc_id: str, store: SolutionStore | None) -> SolutionDoc:
    doc = (store or get_store()).get(str(doc_id or "").strip())
    if doc is None:
        raise SolutionWorkflowError(f"方案不存在：{doc_id}（先用 draft_solution 创建）")
    return doc


def _derive_doc_id(goal: str) -> str:
    """goal → 稳定短 id：``sol-<sha1[:8]>``（同目标同 id，天然去重入口）。"""
    digest = hashlib.sha1(goal.strip().encode("utf-8")).hexdigest()[:8]
    return f"sol-{digest}"

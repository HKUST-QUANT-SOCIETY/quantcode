"""P-10 方案先行工作流 — SolutionDoc 契约（specs/FUNCTIONAL_SPEC.md P-10）。

方案先行纪律：任何非平凡任务先出完整解决方案，经 ≥min_rounds 轮人机讨论，
冻结为静态文档；代码按文档生成，验收以文档为基准做一致性判定（runner/judge）。

**语义边界**：本契约是流程阶段载体，不是权限门禁——不新增 HumanGate 触发点。
"冻结前代码工具不可用"由 runner/solution_workflow.py 的阶段限流（tool 过滤）实现。

存储（双写，runner/solution_workflow.py 负责落盘）：
- artifacts/solutions/<id>-v<n>.md（冻结后的静态文档，人可读）
- Blackboard ``shared.solutions.<id>``（PROJECT scope，跨组可读；
  key 经 runner/blackboard_keys.make_read_key 归一）
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SolutionStatus(StrEnum):
    """方案文档状态机：draft → frozen → superseded（被新方案替代）。"""

    DRAFT = "draft"
    FROZEN = "frozen"
    SUPERSEDED = "superseded"


class SolutionRound(BaseModel):
    """一轮人机讨论：人的反馈 + 该轮对方案的修订摘要。"""

    model_config = ConfigDict(extra="forbid")

    round_no: int = Field(ge=1, description="轮次编号，从 1 起")
    feedback: str = Field(min_length=1, description="本轮人的反馈（不可为空）")
    revision: str = Field(default="", description="本轮对方案的修订摘要（可空=未改动）")
    at: str = Field(default="", description="ISO8601 时间戳（写侧生成）")


class SolutionDoc(BaseModel):
    """方案文档（P-10 唯一契约，extra="forbid"）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="方案 id（进入 artifacts 文件名与 blackboard key，限安全字符）",
    )
    goal: str = Field(min_length=1, description="任务目标（自然语言）")
    rounds: list[SolutionRound] = Field(
        default_factory=list,
        description="人机讨论轮次；freeze 要求 len(rounds) >= min_rounds",
    )
    status: SolutionStatus = Field(default=SolutionStatus.DRAFT)
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="验收标准（一致性判定的语义输入）"
    )
    file_impact: list[str] = Field(
        default_factory=list,
        description="预期改动文件面（repo 相对路径）；之外的改动必须在偏离清单里报告",
    )
    doc_hash: str = Field(
        default="",
        description="方案内容摘要（sha256 前 16 位，由 runner/solution_workflow 计算）",
    )
    # —— 以下为存储/流转所需的派生字段（契约核心字段之外的最小补充）——
    version: int = Field(
        default=1, ge=1, description="文档版本号（每次落盘递增，对应 <id>-v<n>.md）"
    )
    trivial_exempt: bool = Field(
        default=False,
        description="trivial 单点修复豁免标记（需 configs/solution_workflow.yaml 开关放行）；"
        "豁免文档直接以 frozen 状态落库留痕，代码工具不受限",
    )
    needs_human: bool = Field(
        default=False,
        description="超 max_rounds 仍处 draft 时的人裁标记",
    )
    created_at: str = Field(default="", description="ISO8601 创建时间")
    updated_at: str = Field(default="", description="ISO8601 最后更新时间")


__all__ = ["SolutionDoc", "SolutionRound", "SolutionStatus"]

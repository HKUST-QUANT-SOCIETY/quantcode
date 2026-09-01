"""P-07 组织资产蒸馏 — CapabilityCard 契约（specs/FUNCTIONAL_SPEC.md P-07 / F-04）。

能力卡片 = "对现有系统的预训练"：AI 必须知道组织有什么、何时复用、何时别自造。
**禁止凭会议记忆手写卡片——一律从真实仓库蒸馏**（Step 0 调研见 docs/audit/ASSET_INVENTORY.md）。

**蒸馏粒度守则**（本契约的注释即守则）：蒸 **API 面**（入口模块 / 门面函数 / 契约类型名），
**不蒸实现细节**；数据字段清单（data_access semantic_fields 等）与部署底层结构
（alpha_flow 模块内部）不进卡片正文——细节走属组 scope Memory 检索（弱保证），
常驻摘要只有 id+name+when_to_use 一行（强保证，runner/distill/inject.py）。

两类蒸馏物（type 字段区分）：
- ``asset``     资产卡：组织真实仓库的能力登记（首批：quant_evaluator / factor_engine /
                data_access / quant_platform / alpha_flow）；
- ``contract``  口径契约卡：数据口径 / 工程契约登记（首批：TargetReturnView/v1 目标收益口径）。

权限 Mask（F-04）：游客组（未认证 / 未知组）**仅 contract 卡可见**（fail-closed）；
asset 卡落 Memory 时进属组 ``groups`` scope（owner_group），复用 Memory GROUP 隔离语义。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 卡片类型：asset=资产卡（repo 蒸馏）；contract=口径契约卡（数据/工程契约）。
CardType = Literal["asset", "contract"]

# owner_group 取值：六研究组之一（与 .opencode/groups/ 枚举同源）；
# "all" 仅用于 contract 卡（口径契约全组织统一）与 asset 卡的属组展示。
# asset 卡落 Memory 时 owner_group 必须是六组之一（groups scope 需要具体组 id）。
OWNER_GROUPS: tuple[str, ...] = (
    "factor",
    "fundamental",
    "model",
    "options",
    "risk",
    "strategy",
    "all",
)

OwnerGroup = Literal["factor", "fundamental", "model", "options", "risk", "strategy", "all"]


class CapabilityCard(BaseModel):
    """能力卡片（P-07 唯一契约，extra="forbid"）。

    落盘单源：``configs/capabilities.yaml``（configs 顶层键 ``cards:`` 列表，
    经 runner/config_loader.load_yaml 加载——yaml 单源模式，不走 db）。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
        description="卡片 id（kebab-case；进入摘要行 / list_capabilities / Memory key）",
    )
    name: str = Field(
        min_length=1,
        max_length=80,
        description="能力显示名（如 'Quant Evaluator 批量因子评估器'）",
    )
    type: CardType = Field(
        description="asset=资产卡（repo 蒸馏）；contract=口径契约卡（如 TargetReturnView/v1）",
    )
    api_surface: list[str] = Field(
        default_factory=list,
        description="关键入口列表（每条 = 模块路径/门面函数/契约类型名 + 一句话）；"
        "蒸馏粒度守则：只蒸 API 面，不蒸实现细节；数据字段清单与部署底层结构不进本字段",
    )
    when_to_use: str = Field(
        min_length=1,
        description="何时用（进入常驻摘要行；写给 Agent 的复用触发条件）",
    )
    when_not_to_reinvent: str = Field(
        min_length=1,
        description="何时别自造（最大复用原则的反面清单：已有能力覆盖时禁止另造）",
    )
    owner_group: OwnerGroup = Field(
        description="属组（Git repo 权限 = Memory 权限同源）；"
        "contract 卡用 'all'；asset 卡为六组之一（Memory groups scope 落点）",
    )
    source_commit: str = Field(
        default="",
        max_length=64,
        description="蒸馏源 commit（org repo 的 HEAD sha 短码，Step 0 gh 实测）；"
        "in-repo 契约卡（本仓 schemas/）无法读 git 时留空并在 name/描述标注分支",
    )
    distilled_at: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="蒸馏日期（ISO 日期，Step 0 调研日）",
    )


__all__ = ["CapabilityCard", "CardType", "OWNER_GROUPS", "OwnerGroup"]

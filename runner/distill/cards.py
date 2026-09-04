"""能力卡片：加载（yaml 单源）/ group 可见过滤（Mask）/ Memory scope 映射 / list_capabilities 元工具。

权限 Mask（F-04 / P-07，fail-closed）：
- **游客组**（未认证 / ``guest`` / 不在六组枚举内的未知组）→ **仅 contract 卡可见**；
- 已认证研究组 → contract 卡 + 全部 asset 卡可见（Git repo 权限同源：org 成员可见核心仓）；
- 数据字段清单类**细节**对无权限组 Mask 的实现 = 两层投放分工：
  (a) 常驻摘要只有 id+name+when_to_use 一行（api_surface 本就不在摘要里）；
  (b) asset 卡细节（api_surface 全文）蒸馏进 Memory 时落 **属组 ``groups`` scope**
      （:func:`card_memory_location`），跨组/游客 FTS 检索被既有
      ``MemoryService`` GROUP 隔离 fail-closed 拦截（零 service.py 改动）。

list_capabilities 元工具：与 list_runs / list_skills 同走 **_meta 通道**
（不进各组 tool_allowlist，六组 MCP server 的 tools/list 都能列出，只读无副作用）。
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from runner.config_loader import load_yaml
from schemas.capability_card import CapabilityCard

logger = logging.getLogger(__name__)

# yaml 单源配置名（configs/capabilities.yaml；QUANTCODE_CONFIG_DIR 可覆盖）。
CAPABILITIES_CONFIG = "capabilities"

# 游客组语义：未认证 / 显式 guest / 未知组一律按游客处理（fail-closed）。
GUEST_GROUP = "guest"

# 六研究组枚举（与 .opencode/groups/ 同源；identity/permission 权威源对齐由主 Agent 裁决）。
RESEARCH_GROUPS: frozenset[str] = frozenset(
    {"factor", "fundamental", "model", "options", "risk", "strategy"}
)


# ---------------------------------------------------------------------------
# 加载（configs/capabilities.yaml 单源 → CapabilityCard）
# ---------------------------------------------------------------------------

def load_cards(config_name: str = CAPABILITIES_CONFIG) -> list[CapabilityCard]:
    """从 ``configs/<name>.yaml`` 加载并校验能力卡片。

    Returns:
        校验通过的卡片列表（保序）。文件缺失 → 空列表（调用方按"无目录"降级）。

    Raises:
        ValueError: 某张卡不符合 :class:`CapabilityCard` 契约（契约完整性 fail-fast；
            常驻摘要注入侧会兜底 catch，不让坏卡砸 run）。
    """
    data = load_yaml(config_name)
    raw_cards = data.get("cards") or []
    if not isinstance(raw_cards, list):
        raise ValueError(f"capabilities.yaml 顶层 cards 必须是列表（got {type(raw_cards).__name__}）")
    cards: list[CapabilityCard] = []
    for i, item in enumerate(raw_cards):
        try:
            cards.append(CapabilityCard.model_validate(item))
        except ValidationError as e:
            raise ValueError(f"capabilities.yaml 第 {i} 张卡校验失败: {e}") from e
    return cards


def strict_reuse_enabled(config_name: str = CAPABILITIES_CONFIG) -> bool:
    """strict_reuse 开关（P-07 复用纪律：true=禁止引入外部自造实现，仅允许已登记能力）。"""
    return bool(load_yaml(config_name).get("strict_reuse", False))


# ---------------------------------------------------------------------------
# 权限 Mask（group 可见过滤，复用 Memory GROUP 隔离语义 fail-closed）
# ---------------------------------------------------------------------------

def _is_guest(requester_group: str | None) -> bool:
    """未认证 / guest / 未知组 → 游客（fail-closed：未知一律收紧）。"""
    g = (requester_group or "").strip()
    return (not g) or g == GUEST_GROUP or g not in RESEARCH_GROUPS


def visible_cards(
    cards: list[CapabilityCard],
    requester_group: str | None,
    requester_role: str | None = None,
) -> list[CapabilityCard]:
    """按请求组过滤卡片（Mask 决策唯一入口）。

    规则：
    - 游客组（未认证 / guest / 未知组）→ 仅 ``type == "contract"``；
    - 已认证研究组 → contract + non-admin asset（数据字段清单细节的 Mask 在
      Memory scope 层实现，见 :func:`card_memory_location`）；
    - Admin role → 全部卡片。
    """
    if _is_guest(requester_group):
        return [c for c in cards if c.type == "contract"]
    if requester_role == "admin":
        return list(cards)
    return [c for c in cards if c.visibility != "admin"]


def card_memory_location(card: CapabilityCard) -> tuple[str, str | None]:
    """卡片 → Memory ``(scope, scope_id)`` 落点（细节 FTS 检索的权限边界）。

    - contract 卡 → ``("global", None)``：全组织统一口径（含游客可检索）；
    - asset 卡 → ``("groups", owner_group)``：细节仅属组可检索（跨组/游客被
      GROUP 隔离 fail-closed 拦截）——因此 asset 卡 owner_group 必须是六组之一。
    """
    if card.type == "contract":
        return ("global", None)
    if card.owner_group not in RESEARCH_GROUPS:
        raise ValueError(
            f"asset 卡 {card.id!r} owner_group={card.owner_group!r} 不是具体研究组，"
            "无法落 groups scope（Memory 细节检索需要明确属组）"
        )
    return ("groups", card.owner_group)


def render_card_body(card: CapabilityCard) -> str:
    """卡片 → Memory markdown 正文（蒸 API 面，不蒸实现细节——字段即卡片全文）。"""
    lines = [
        f"# CapabilityCard: {card.id}",
        f"- name: {card.name}",
        f"- type: {card.type}",
        f"- owner_group: {card.owner_group}",
        f"- canonical_repo: {card.canonical_repo or '(unregistered)'}",
        f"- maturity_status: {card.maturity_status}",
        f"- integration_status: {card.integration_status}",
        f"- source_commit: {card.source_commit or '(in-repo)'}",
        f"- distilled_at: {card.distilled_at}",
        "",
        "## api_surface",
        *(f"- {s}" for s in card.api_surface),
        "",
        "## when_to_use",
        card.when_to_use,
        "",
        "## when_not_to_reinvent",
        card.when_not_to_reinvent,
        "",
    ]
    return "\n".join(lines)


def distill_cards_to_memory(
    service: Any,
    cards: list[CapabilityCard],
) -> list[str]:
    """把卡片蒸馏进 Memory（写入侧：系统以属组身份落盘，属组隔离立即生效）。

    contract 卡落 global scope；asset 卡落 ``groups/<owner_group>`` scope
    （写入 requester 即属组——蒸馏源就是属组仓库，见 ASSET_INVENTORY.md）。

    Returns:
        写入的磁盘路径列表（与入参卡片一一对应，失败的卡跳过并 warning）。
    """
    written: list[str] = []
    for card in cards:
        scope, scope_id = card_memory_location(card)
        try:
            path = service.write(
                scope=scope,
                scope_id=scope_id,
                type="reference",
                key=f"capability-card-{card.id}",
                body=render_card_body(card),
                requester_group=(card.owner_group if scope == "groups" else None),
            )
        except Exception as e:  # noqa: BLE001 — 单卡失败不阻塞整批蒸馏
            logger.warning("distill_cards_to_memory: 卡片 %s 写入失败: %s", card.id, e)
            continue
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# list_capabilities 只读元工具（_meta 通道，复用 list_runs / list_skills 模式）
# ---------------------------------------------------------------------------

def _list_capabilities_execute(args: Any, ctx: dict) -> dict:
    """执行 list_capabilities：返回请求组可见的能力目录（Mask 后）。只读，best-effort。"""
    try:
        cards = load_cards()
    except ValueError as e:
        return {"error": f"capabilities.yaml 校验失败: {e}"}
    group = (ctx or {}).get("group")
    visible = visible_cards(cards, group, (ctx or {}).get("role"))
    return {
        "group": group or GUEST_GROUP,
        "strict_reuse": strict_reuse_enabled(),
        "capabilities": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "when_to_use": c.when_to_use,
                "when_not_to_reinvent": c.when_not_to_reinvent,
                "owner_group": c.owner_group,
                "canonical_repo": c.canonical_repo,
                "maturity_status": c.maturity_status,
                "integration_status": c.integration_status,
                "observed_at": c.observed_at,
            }
            for c in visible
        ],
    }


def _register_list_capabilities_tool() -> None:
    """构造并注册 ``list_capabilities`` ToolDef（模块 import 副作用触发，幂等）。

    ponytail: 覆盖式注册（``registry._tools[id] = tool``，与 mcp_server 的
    list_runs/list_skills 同款），模块 reload 安全且不抛重复注册错。
    """
    from pydantic import BaseModel

    from tools.registry import ToolDef, registry

    class ListCapabilitiesArgs(BaseModel):
        """list_capabilities 无输入参数（目录全量返回，Mask 按 ctx.group）。"""

        pass

    tool = ToolDef(
        id="list_capabilities",
        description=(
            "Read-only catalog of the org's reusable capabilities (P-07): "
            "capability cards distilled from real repos — {id, name, type, "
            "api_surface, when_to_use, when_not_to_reinvent, owner_group}. "
            "Check BEFORE writing new code: prefer registered capabilities, "
            "ask a human when coverage is incomplete instead of reinventing. "
            "Guest/unauthenticated groups only see contract cards (mask, fail-closed)."
        ),
        schema=ListCapabilitiesArgs,
        execute=_list_capabilities_execute,
    )
    # _meta 通道：不进各组 allowlist，但所有 6 组 MCP server 的 tools/list 都能列出。
    tool._meta = True  # type: ignore[attr-defined]
    registry._tools[tool.id] = tool


_register_list_capabilities_tool()


__all__ = [
    "CAPABILITIES_CONFIG",
    "GUEST_GROUP",
    "RESEARCH_GROUPS",
    "card_memory_location",
    "distill_cards_to_memory",
    "load_cards",
    "render_card_body",
    "strict_reuse_enabled",
    "visible_cards",
]

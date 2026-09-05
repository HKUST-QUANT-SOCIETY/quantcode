"""常驻目录摘要注入（P-07 两层投放的强保证层）。

run 指令组装时把能力目录摘要附到 system prompt 末尾——**每次 run 可见**，
细节仍走 FTS 检索（弱保证，属组 groups scope）。摘要从
``configs/capabilities.yaml`` 读（config_loader 单源模式，不走 db）。

接入点：``runner/agent_engine.py::AgentRunner.build``（system_prompt 组装 seam，
对 run() 与直接 build() 两条路都生效）。本模块函数**绝不抛异常**——目录缺席
（yaml 缺失 / 坏卡 / 依赖缺失）时原样返回 system_prompt，不砸 run。
"""
from __future__ import annotations

import logging
from typing import Any

from runner.distill.cards import (
    CAPABILITIES_CONFIG,
    strict_reuse_enabled,
    visible_cards,
)

logger = logging.getLogger(__name__)

# 摘要块限长兜底（yaml digest_max_chars 可覆盖；超限截断目录行并留标记）。
DEFAULT_DIGEST_MAX_CHARS = 2000

# 每行格式："- {id} | {name} | {when_to_use}"；when_to_use 超长截断（限长纪律）。
_LINE_WHEN_MAX = 120

_DIGEST_HEADER = "## 组织能力目录（P-07 能力卡片）"
_REUSE_DISCIPLINE = (
    "复用纪律：写代码前先对照目录——已有能力覆盖时禁止另造；"
    "覆盖不全先向人征询，不许直接跳自造方案。"
    "细节用 search_memory 检索属组 Memory，或调 list_capabilities。"
)
_STRICT_REUSE_DISCIPLINE = "【严格复用模式】禁止引入外部自造实现，仅允许使用已登记能力。"
_TRUNCATION_MARK = "…（目录已截断，全量用 list_capabilities 查看）"


def _format_card_line(card: Any) -> str:
    """一卡一行：id + name + when_to_use（超长截断）。"""
    when = card.when_to_use
    if len(when) > _LINE_WHEN_MAX:
        when = when[: _LINE_WHEN_MAX - 1] + "…"
    return (f"- {card.id} | {card.name} | {when} | "
            f"{card.maturity_status}/{card.integration_status} | {card.when_not_to_reinvent}")


def capability_digest(
    group: str | None = None,
    *,
    config_name: str = CAPABILITIES_CONFIG,
    max_chars: int | None = None,
) -> str:
    """生成限长的常驻摘要块（游客组仅契约卡，fail-closed）。

    Args:
        group: 请求组（None/未知 → 游客语义，仅 contract 卡）。
        config_name: yaml 配置名（测试可注入临时目录）。
        max_chars: 总限长；None → yaml ``digest_max_chars``（缺省 2000）。

    Returns:
        摘要块字符串（含首尾换行分隔的前导 ``\\n\\n`` 由
        :func:`append_capability_digest` 处理）；无可显示卡片时返回空串。
    """
    from runner.config_loader import read_yaml
    from runner.distill.cards import load_cards

    try:
        cards = load_cards(config_name)
    except ValueError as e:
        # ponytail: 坏卡不砸 run——只登记错误，返回空摘要。
        logger.warning("capability_digest: 卡片校验失败，本次 run 无目录摘要: %s", e)
        return ""

    if not cards:
        return ""

    if max_chars is None:
        cfg_max = read_yaml(config_name).get("digest_max_chars")
        max_chars = int(cfg_max) if cfg_max else DEFAULT_DIGEST_MAX_CHARS

    header = [_DIGEST_HEADER, _REUSE_DISCIPLINE]
    if strict_reuse_enabled(config_name):
        header.append(_STRICT_REUSE_DISCIPLINE)
    card_lines = [_format_card_line(c) for c in visible_cards(cards, group)]

    block = "\n".join(header + card_lines)
    if len(block) > max_chars:
        # 超限：保 header（纪律行优先于目录行），按序放得下的目录行尽量保留，补截断标记。
        body = list(header)
        for line in card_lines:
            if len("\n".join(body + [line, _TRUNCATION_MARK])) > max_chars:
                break
            body.append(line)
        block = "\n".join(body + [_TRUNCATION_MARK])
    return block


def append_capability_digest(system_prompt: str, *, group: str | None = None) -> str:
    """system prompt 组装 seam 的接入函数（agent_engine.build 调用）。

    best-effort：任何异常（yaml 缺失 / 依赖问题）都原样返回入参，绝不抛出。
    摘要为空（无卡 / 注入关闭）时也原样返回。
    """
    try:
        from runner.config_loader import read_yaml

        if not read_yaml(CAPABILITIES_CONFIG).get("inject_enabled", True):
            return system_prompt
        block = capability_digest(group)
        if not block:
            return system_prompt
        base = system_prompt or ""
        joiner = "\n\n" if base.strip() else ""
        return f"{base}{joiner}{block}"
    except Exception as e:  # noqa: BLE001 — 摘要缺席不砸 run（F-04 强保证以可用为前提）
        logger.warning("append_capability_digest 失败（跳过注入）: %s", e)
        return system_prompt


__all__ = [
    "DEFAULT_DIGEST_MAX_CHARS",
    "append_capability_digest",
    "capability_digest",
]

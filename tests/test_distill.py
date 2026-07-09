"""Distill 原型整体闭环测试 — Day 5 尹一帆。

覆盖:
1. 读 RLHF 数据 → 识别 ≥3 次相同 pattern → 生成 SKILL.md 草案
2. 空 RLHF → 不抛异常,返空列表
3. 生成的草案文件可读 + 含 trigger / steps / verify 段

不依赖 LLM —— 纯 stdlib 统计,符合维护难度低优先原则。
"""
from __future__ import annotations

import json
from pathlib import Path

from dream.distill import distill


def test_distill_generates_skill_draft_from_repeated_pattern(tmp_path):
    """Day 5 #C:RLHF 含 5 次 calc_risk(high_risk) → 生成 1 份 SKILL.md。

    走整体逻辑闭环:
    1. 写 5 条相同 tool_call pattern 的 RLHF
    2. 调 distill(threshold=3)
    3. 验证 drafts/ 下真有 .md 文件 + 含正确段
    """
    rlhf = tmp_path / "rlhf.jsonl"
    lines = []
    for i in range(5):
        lines.append(json.dumps({
            "thread_id": f"t-{i}",
            "action": {
                "tool_name": "calc_risk",
                "tool_args": {"scenario": "high_risk"},
            },
            "observation": {"success": True, "summary": "ok"},
        }))
    rlhf.write_text("\n".join(lines) + "\n", encoding="utf-8")

    drafts_dir = tmp_path / "drafts"

    generated = distill(
        rlhf_path=rlhf,
        output_dir=drafts_dir,
        threshold=3,
    )

    assert len(generated) >= 1, f"应生成 ≥1 份草案, got {generated}"
    draft_path = generated[0]
    assert draft_path.exists()
    body = draft_path.read_text(encoding="utf-8")
    # 草案含 trigger / steps / verify 段
    assert "## Trigger" in body, f"草案应含 Trigger 段, got: {body[:200]}"
    assert "## Steps" in body, f"草案应含 Steps 段, got: {body[:200]}"
    assert "## Verify" in body, f"草案应含 Verify 段, got: {body[:200]}"
    # 含真实 tool 名
    assert "calc_risk" in body


def test_distill_handles_empty_rlhf_gracefully(tmp_path):
    """Day 5 #C:RLHF 不存在或为空 → 不抛异常,返 []。

    走整体逻辑闭环:无数据 → 无产出。
    """
    rlhf = tmp_path / "empty.jsonl"
    rlhf.write_text("", encoding="utf-8")

    generated = distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "drafts",
        threshold=3,
    )

    assert generated == [], f"空 RLHF 应返 [], got {generated}"


def test_distill_handles_missing_rlhf_gracefully(tmp_path):
    """Day 5 #C:RLHF 文件不存在 → 不抛异常,返 []。

    走整体逻辑闭环:无文件 → 无产出。
    """
    rlhf = tmp_path / "no_such.jsonl"

    generated = distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "drafts",
        threshold=3,
    )

    assert generated == [], f"RLHF 不存在应返 [], got {generated}"


def test_distill_skips_rare_patterns(tmp_path):
    """Day 5 #C:相同 pattern 仅 2 次 < threshold=3 → 不生成草案。

    验证 threshold 阈值生效。
    """
    rlhf = tmp_path / "rlhf.jsonl"
    lines = []
    # 2 次 calc_risk(rare)
    for i in range(2):
        lines.append(json.dumps({
            "thread_id": f"rare-{i}",
            "action": {"tool_name": "calc_risk", "tool_args": {"x": 1}},
            "observation": {"success": True},
        }))
    rlhf.write_text("\n".join(lines) + "\n", encoding="utf-8")

    generated = distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "drafts",
        threshold=3,
    )

    assert generated == [], f"rare pattern(2 次 < threshold=3) 不应生成, got {generated}"
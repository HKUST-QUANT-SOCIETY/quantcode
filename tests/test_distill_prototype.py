"""Distill 原型测试 — Day 5 Lead。

验收（Day5 §5）：识别 ≥1 个重复 pattern → 产候选 SKILL.md 草案。
"""
from __future__ import annotations

import json
from pathlib import Path

from dream.distill_prototype import run_distill


def _write_rlhf(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )


def _entry(group: str, thread_id: str, tool_name: str) -> dict:
    return {
        "thread_id": thread_id,
        "group": group,
        "action": {"tool_name": tool_name, "tool_args": {}},
        "observation": {"success": True, "summary": ""},
    }


def _risk_thread(thread_id: str) -> list[dict]:
    """一个典型的 risk 流：read_blackboard → calc_risk → check_gate。"""
    return [
        _entry("risk", thread_id, "read_blackboard"),
        _entry("risk", thread_id, "calc_risk"),
        _entry("risk", thread_id, "check_gate"),
    ]


def test_distill_identifies_repeated_pattern(tmp_path):
    """两个 thread 走同样的 read_blackboard→calc_risk→check_gate 序列，
    Distill 应识别出 ≥1 个候选。"""
    rlhf = tmp_path / "rlhf.jsonl"
    _write_rlhf(rlhf, _risk_thread("t1") + _risk_thread("t2"))

    candidates = run_distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "distill",
        min_occurrences=2,
    )

    assert len(candidates) >= 1, "应识别出至少 1 个重复 pattern"
    top = candidates[0]
    assert top["group"] == "risk"
    assert top["occurrences"] >= 2
    assert "read_blackboard" in top["tool_sequence"]


def test_distill_writes_skill_md_draft(tmp_path):
    """候选应落盘为 SKILL.md 草案，含 frontmatter + draft 标记。"""
    rlhf = tmp_path / "rlhf.jsonl"
    _write_rlhf(rlhf, _risk_thread("t1") + _risk_thread("t2"))

    candidates = run_distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "distill",
        min_occurrences=2,
    )

    path = Path(candidates[0]["skill_md_path"])
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "status: draft" in text
    assert "source: distill" in text
    assert "Distill" in text


def test_distill_respects_min_occurrences(tmp_path):
    """只出现 1 次的序列不达 min_occurrences=2，不产候选。"""
    rlhf = tmp_path / "rlhf.jsonl"
    _write_rlhf(rlhf, _risk_thread("only-once"))

    candidates = run_distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "distill",
        min_occurrences=2,
    )
    assert candidates == []


def test_distill_empty_when_no_rlhf(tmp_path):
    """rlhf 文件不存在 → 返回空列表，不报错。"""
    candidates = run_distill(
        rlhf_path=tmp_path / "nonexistent.jsonl",
        output_dir=tmp_path / "distill",
    )
    assert candidates == []


def test_distill_separates_groups(tmp_path):
    """不同组的相同序列不应跨组合并统计。"""
    rlhf = tmp_path / "rlhf.jsonl"
    # risk 组重复 2 次；model 组的序列只 1 次
    entries = _risk_thread("r1") + _risk_thread("r2") + [
        _entry("model", "m1", "read_pr"),
        _entry("model", "m1", "extract_metadata"),
    ]
    _write_rlhf(rlhf, entries)

    candidates = run_distill(
        rlhf_path=rlhf,
        output_dir=tmp_path / "distill",
        min_occurrences=2,
    )
    groups = {c["group"] for c in candidates}
    assert "risk" in groups
    assert "model" not in groups, "model 序列只 1 次，不应成候选"

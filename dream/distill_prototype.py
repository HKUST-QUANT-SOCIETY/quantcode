"""Distill 原型 — Day 5 Lead。

对齐 Design §4.1 / §2.5：识别重复的手动/自动操作序列，把高频 pattern
打包成候选 SKILL.md 草案，供人工审核后转正为正式 skill。

与 Dream 的分工：
- Dream（``dream_prototype.py``）：从单条 trace 提取"知识"写入 Memory。
- Distill（本模块）：跨多条 trace 聚类"重复操作序列"，产出候选 SKILL.md。

数据源：``.quantcode/rlhf_data.jsonl``（每行一条 tool call 记录，含
``action.tool_name`` / ``action.tool_args`` / ``group`` / ``thread_id``）。

用法::

    from dream.distill_prototype import run_distill
    candidates = run_distill(rlhf_path=".quantcode/rlhf_data.jsonl")
    # candidates: list[dict]，每个含 name/group/tool_sequence/occurrences/skill_md_path
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_rlhf_records(rlhf_path: Path) -> list[dict[str, Any]]:
    """读 rlhf_data.jsonl 的所有非空 JSON 行。"""
    if not rlhf_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with rlhf_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _group_by_thread(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 (group, thread_id) 分组，保留每条的 tool 调用顺序。"""
    by_thread: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        group = rec.get("group", "") or "unknown"
        tid = rec.get("thread_id", "") or "unknown"
        by_thread[f"{group}::{tid}"].append(rec)
    return by_thread


def _tool_sequence(records: list[dict[str, Any]]) -> tuple[str, ...]:
    """从一个 thread 的记录里抽出 tool_name 序列（保序、去掉空名）。"""
    seq: list[str] = []
    for rec in records:
        action = rec.get("action", {})
        name = action.get("tool_name", "") if isinstance(action, dict) else ""
        if name:
            seq.append(name)
    return tuple(seq)


def _ngram_counts(
    sequences: list[tuple[tuple[str, ...], str]],
    *,
    min_len: int = 2,
    max_len: int = 5,
) -> Counter:
    """统计所有 thread 里长度 [min_len, max_len] 的 tool 子序列出现次数。

    key = (group, tool_subsequence)；只在同 group 内统计（跨组序列无意义）。
    """
    counts: Counter = Counter()
    for seq, group in sequences:
        n = len(seq)
        for size in range(min_len, min(max_len, n) + 1):
            for i in range(n - size + 1):
                sub = seq[i : i + size]
                counts[(group, sub)] += 1
    return counts


def _candidate_name(group: str, sub: tuple[str, ...]) -> str:
    """给候选 skill 起个可读名：<group>-<第一个>-to-<最后一个>。"""
    if len(sub) == 1:
        return f"{group}-{sub[0]}"
    return f"{group}-{sub[0]}-to-{sub[-1]}"


def _render_skill_md(
    name: str,
    group: str,
    sub: tuple[str, ...],
    occurrences: int,
) -> str:
    """把一个重复 pattern 渲染成候选 SKILL.md 草案（含 frontmatter）。"""
    steps = "\n".join(f"{i + 1}. 调用 `{tool}`" for i, tool in enumerate(sub))
    tools_line = " / ".join(sub)
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: （Distill 候选草案，待人工审核）{group} 组高频操作序列，"
        f"在 trace 中重复出现 {occurrences} 次\n"
        f"group: {group}\n"
        f"status: draft\n"
        f"source: distill\n"
        f"generated_at: {datetime.now(UTC).isoformat()}\n"
        f"---\n\n"
        f"# {name}（Distill 候选草案）\n\n"
        f"> ⚠️ 本文件由 Distill 自动生成，是**候选草案**，需人工审核补全 system prompt、\n"
        f"> 输入/输出契约、验收标准后才能转为正式 SKILL.md。\n\n"
        f"## 识别依据\n\n"
        f"Distill 在执行 trace 中发现该 tool 序列在 {group} 组重复出现 "
        f"**{occurrences}** 次，判定为可固化的工作流。\n\n"
        f"## 高频操作序列\n\n"
        f"涉及 tool：`{tools_line}`\n\n"
        f"{steps}\n\n"
        f"## 待补全（人工）\n\n"
        f"- [ ] System Prompt：这个序列在什么场景下触发？\n"
        f"- [ ] 输入契约：首个 tool 的输入从哪来？\n"
        f"- [ ] 输出契约：末个 tool 的产出是什么 schema？\n"
        f"- [ ] 验收标准：怎么判断这条流跑成功了？\n"
    )


def run_distill(
    *,
    rlhf_path: str | Path = ".quantcode/rlhf_data.jsonl",
    output_dir: str | Path = "artifacts/distill",
    min_occurrences: int = 2,
    min_len: int = 2,
    max_len: int = 5,
    write_files: bool = True,
) -> list[dict[str, Any]]:
    """Distill 主入口：扫 rlhf trace → 聚类重复序列 → 产候选 SKILL.md 草案。

    Args:
        rlhf_path: rlhf_data.jsonl 路径。
        output_dir: 候选 SKILL.md 草案输出目录。
        min_occurrences: 一个序列至少重复几次才算候选（默认 2）。
        min_len / max_len: 考虑的 tool 子序列长度范围。
        write_files: True 时把草案写到 output_dir；False 时只返回不落盘。

    Returns:
        候选列表，每个 dict 含：
        - ``name``：候选 skill 名
        - ``group``：所属组
        - ``tool_sequence``：list[str] tool 序列
        - ``occurrences``：重复次数
        - ``skill_md_path``：草案文件路径（write_files=False 时为 None）
    """
    rlhf_path = Path(rlhf_path)
    output_dir = Path(output_dir)

    records = _load_rlhf_records(rlhf_path)
    if not records:
        return []

    by_thread = _group_by_thread(records)
    sequences: list[tuple[tuple[str, ...], str]] = []
    for key, recs in by_thread.items():
        group = key.split("::", 1)[0]
        seq = _tool_sequence(recs)
        if seq:
            sequences.append((seq, group))

    counts = _ngram_counts(sequences, min_len=min_len, max_len=max_len)

    # 只保留达到 min_occurrences 的；同 group 内若长序列已覆盖，优先长的
    # （按 (出现次数, 序列长度) 降序，取有意义的候选）。
    qualified = [
        (group, sub, cnt)
        for (group, sub), cnt in counts.items()
        if cnt >= min_occurrences
    ]
    qualified.sort(key=lambda x: (x[2], len(x[1])), reverse=True)

    # 去冗余：若一个较短序列完全被已选的较长序列包含且次数相同，跳过。
    selected: list[tuple[str, tuple[str, ...], int]] = []
    for group, sub, cnt in qualified:
        redundant = any(
            g == group and cnt == c and _is_contiguous_subseq(sub, longer)
            for g, longer, c in selected
        )
        if not redundant:
            selected.append((group, sub, cnt))

    if write_files and selected:
        output_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []
    for group, sub, cnt in selected:
        name = _candidate_name(group, sub)
        skill_md_path: str | None = None
        if write_files:
            md = _render_skill_md(name, group, sub, cnt)
            path = output_dir / f"candidate-{name}.md"
            path.write_text(md, encoding="utf-8")
            skill_md_path = path.as_posix()
        candidates.append(
            {
                "name": name,
                "group": group,
                "tool_sequence": list(sub),
                "occurrences": cnt,
                "skill_md_path": skill_md_path,
            }
        )
    return candidates


def _is_contiguous_subseq(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    """short 是否为 long 的连续子序列。"""
    n, m = len(short), len(long)
    if n >= m:
        return False
    return any(long[i : i + n] == short for i in range(m - n + 1))


__all__ = ["run_distill"]

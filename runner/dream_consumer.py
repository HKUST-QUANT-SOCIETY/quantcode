"""Dream consumer — P0-9 遗留闭环（ROADMAP A4 蒸馏闭环消费端）。

生产端早已存在：
- ``.quantcode/evidence/<run_id>.jsonl``（``runner.evidence.append_event``）
- ``.quantcode/rlhf_data.jsonl``（``runner.routing.rlhf_logger.log_rlhf_entry``）

本模块补上消费端：tail evidence 目录增量 → 抽出**已完成且成功** run 的
tool 序列 → 喂给既有 ``dream.distill_prototype.run_distill`` 产候选
SKILL.md 草案（写 .quantcode/distill_candidates/，index.json 登记去重）→
对带 goal/trace 的 run 可选走 ``runner.judge.judge_run``，verdict 经既有
``runner.routing.session_review.apply_judged_session`` 落 RLHF。

分离的小函数（全部可独立调用/测试）：
- ``scan_completed_runs``      扫 evidence 目录 → 新完成 run 的事件列表
- ``run_records_from_events``  事件 → distill 输入格式的 rlhf 记录（失败 run → 空）
- ``distill_new_runs``         记录喂 run_distill → 候选落盘 + index.json 去重
- ``judge_new_runs``           带 goal 的 run 走 judge → apply_judged_session 落 RLHF
- ``consume_once``             一轮 = 扫描 + distill + 可选 judge（CLI / 测试入口）
- ``consume_status``           只读：候选数 / 最近消费时间 / rlhf 行数
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from runner.distill.governance import review_candidate

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = PROJECT_ROOT / ".quantcode" / "evidence"
CANDIDATES_DIR = PROJECT_ROOT / ".quantcode" / "distill_candidates"

__all__ = [
    "CANDIDATES_DIR",
    "EVIDENCE_DIR",
    "consume_once",
    "consume_status",
    "distill_new_runs",
    "judge_new_runs",
    "run_records_from_events",
    "scan_completed_runs",
    "review_candidate",
]


# ---------------------------------------------------------------------------
# scan_completed_runs — tail evidence 增量
# ---------------------------------------------------------------------------

def scan_completed_runs(
    evidence_dir: str | Path = EVIDENCE_DIR,
    *,
    seen_run_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """扫 evidence 目录，返回尚未消费过且**已完成**的 run 事件列表。

    已完成 = 链中有带 ``status`` 的 ``output_data`` 环（agent_engine run/stream/
    resume 完成钩子收尾必落）。``seen_run_ids`` 传入已消费 run_id 集合——
    CLI/调用方用它做跨轮增量（首轮为空集，之后把返回的 run_id 累计进去）；
    不传则为单轮语义。坏行静默跳过（与 evidence 读侧语义一致）。

    Returns:
        [{"run_id", "events": [AuditEvent dict, ...]}, ...]，按 run_id 排序。
    """
    seen = seen_run_ids if seen_run_ids is not None else set()
    root = Path(evidence_dir)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.jsonl")):
        run_id = path.stem
        if run_id in seen:
            continue
        events: list[dict[str, Any]] = []
        completed = False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            if (
                event.get("kind") == "output_data"
                and isinstance(event.get("payload"), dict)
                and "status" in event["payload"]
            ):
                completed = True
        if completed:
            seen.add(run_id)
            out.append({"run_id": run_id, "events": events})
    return out


# ---------------------------------------------------------------------------
# run_records_from_events — 事件 → distill 输入记录
# ---------------------------------------------------------------------------

def run_records_from_events(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    group: str = "",
) -> list[dict[str, Any]]:
    """把一个 completed run 的证据环转成 run_distill 的 rlhf 记录格式。

    tool_call/tool_result 按 tool_call_id 配对回填 success；任一环
    is_error=True 的 run（error run）不产正向候选，返回空列表。
    """
    call_ids: list[str] = []
    records: list[dict[str, Any]] = []
    ok_by_id: dict[str, bool] = {}
    for e in events:
        kind = e.get("kind")
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if kind == "tool_call":
            tcid = str(payload.get("tool_call_id", ""))
            call_ids.append(tcid)
            records.append({
                "thread_id": run_id,
                "group": group,
                "action": {
                    "tool_name": payload.get("tool", ""),
                    "tool_args": payload.get("args") or {},
                },
                "observation": {"success": True, "summary": ""},
            })
        elif kind == "tool_result" and call_ids:
            ok_by_id[call_ids[-1]] = not bool(payload.get("is_error", False))
    if not ok_by_id or not all(ok_by_id.values()):
        return []
    return records


# ---------------------------------------------------------------------------
# distill_new_runs — 喂 run_distill → 候选落盘 + index 去重
# ---------------------------------------------------------------------------

def _load_index(candidates_dir: Path) -> dict[str, Any]:
    path = candidates_dir / "index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("candidates"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"candidates": []}


def _candidate_key(name: str, tool_sequence: list[str]) -> str:
    """去重键：name + tool 序列相同视为同一候选（跨轮幂等）。"""
    return f"{name}|{'>'.join(tool_sequence)}"


def distill_new_runs(
    runs: list[dict[str, Any]],
    *,
    candidates_dir: str | Path = CANDIDATES_DIR,
    work_path: str | Path | None = None,
    min_occurrences: int = 1,
) -> list[dict[str, Any]]:
    """把新 run 的记录喂既有 ``run_distill`` → 候选草案 + index.json 登记。

    每 run 的转换记录须已挂在 ``run["_records"]``（见 run_records_from_events）。
    min_occurrences 默认 1：consumer 按轮喂增量，序列出现 1 次即登记候选，
    人工审核仍是转正闸门（候选本身 status: draft）。

    去重：候选 key 已在 index.json 的情况跳过（不重写草案、不重复登记）。
    """
    records: list[dict[str, Any]] = []
    for run in runs:
        records.extend(run.get("_records") or [])
    if not records:
        return []

    from dream.distill_prototype import run_distill  # 延迟 import：只消费不改

    candidates_dir = Path(candidates_dir)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    work = Path(work_path) if work_path is not None else candidates_dir / ".work-rlhf.jsonl"
    work.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    produced = run_distill(
        rlhf_path=work,
        output_dir=candidates_dir,
        min_occurrences=min_occurrences,
    )

    index = _load_index(candidates_dir)
    known = {
        _candidate_key(c.get("name", ""), c.get("tool_sequence", []))
        for c in index["candidates"]
    }
    run_ids = [r["run_id"] for r in runs]
    fresh: list[dict[str, Any]] = []
    for c in produced:
        key = _candidate_key(c["name"], c["tool_sequence"])
        if key in known:
            continue
        known.add(key)
        fresh.append({**c, "run_ids": run_ids})
        index["candidates"].append(fresh[-1])
    if fresh:
        index["updated_at"] = datetime.now(UTC).isoformat()
        (candidates_dir / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return fresh


# ---------------------------------------------------------------------------
# judge_new_runs — goal/trace → judge → apply_judged_session 落 RLHF
# ---------------------------------------------------------------------------

def judge_new_runs(
    runs: list[dict[str, Any]],
    *,
    llm: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """对带 goal 的新 run 走 judge，verdict 经 apply_judged_session 落 RLHF。

    evidence 链本身不含 task 文本——带 goal 的调用方（/goal 命令侧）在
    run 项上补 ``goal`` / ``trace`` 字段即可命中；无 goal 的 run 直接跳过。
    verdict 降级(unevaluated)时 apply_judged_session 不碰 RLHF 文件（诚实降级）。
    """
    reports: list[dict[str, Any]] = []
    for run in runs:
        goal = str(run.get("goal") or "").strip()
        if not goal:
            continue
        from runner.routing.session_review import apply_judged_session  # 延迟：同上

        reports.append(
            apply_judged_session(run["run_id"], goal, run.get("trace") or [], llm=llm)
        )
    return reports


# ---------------------------------------------------------------------------
# consume_once / consume_status
# ---------------------------------------------------------------------------

def consume_once(
    *,
    evidence_dir: str | Path = EVIDENCE_DIR,
    candidates_dir: str | Path = CANDIDATES_DIR,
    with_judge: bool = False,
    llm: Callable[..., Any] | None = None,
    group: str = "",
    min_occurrences: int = 1,
    consumed_run_ids: set[str] | None = None,
) -> dict[str, Any]:
    """一轮消费：扫新完成 run → 成功 run 蒸馏候选（+ 可选 judge 落 RLHF）。

    ``consumed_run_ids``（可选集合，就地更新）承担跨轮增量：CLI 的 interval
    循环模式传同一集合即可每轮只处理新 run；--once 传 None（全量扫一遍，
    幂等由 index.json 去重兜底）。

    Returns:
        {"scanned_runs", "new_runs", "candidates", "judged"}。
    """
    scanned = scan_completed_runs(evidence_dir, seen_run_ids=consumed_run_ids)
    runs: list[dict[str, Any]] = []
    for run in scanned:
        recs = run_records_from_events(run["run_id"], run["events"], group=group)
        if recs:
            runs.append({**run, "_records": recs})

    fresh = distill_new_runs(
        runs, candidates_dir=candidates_dir, min_occurrences=min_occurrences
    )
    judged = judge_new_runs(runs, llm=llm) if with_judge else []

    Path(candidates_dir).mkdir(parents=True, exist_ok=True)
    (Path(candidates_dir) / ".last_consumed").write_text(
        datetime.now(UTC).isoformat(), encoding="utf-8"
    )
    return {
        "scanned_runs": len(scanned),
        "new_runs": len(runs),
        "candidates": fresh,
        "judged": judged,
    }


def consume_status(
    *,
    candidates_dir: str | Path = CANDIDATES_DIR,
    rlhf_path: str | Path | None = None,
) -> dict[str, Any]:
    """只读状态（mcp_server ``consume_status`` 工具的数据面）。"""
    cdir = Path(candidates_dir)
    index = _load_index(cdir)
    last = None
    sp = cdir / ".last_consumed"
    if sp.exists():
        last = sp.read_text(encoding="utf-8").strip() or None
    rlhf = Path(rlhf_path) if rlhf_path is not None else (
        PROJECT_ROOT / ".quantcode" / "rlhf_data.jsonl"
    )
    lines = 0
    try:
        with rlhf.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    lines += 1
    except OSError:
        pass
    return {
        "candidates": len(index["candidates"]),
        "last_consumed": last,
        "rlhf_lines": lines,
    }

"""Dream consumer 测试 — P0-9 遗留闭环（ROADMAP A4 蒸馏闭环消费端）。

覆盖：
1. fixture evidence 文件端到端：一轮 → 候选 SKILL.md 草案落盘 + index.json 登记
2. 二次运行：同候选去重（index 不重复登记）
3. 无新 run：consume_once no-op（不产生候选、不改状态时间戳）
4. CLI --once 退出码 0（subprocess 真跑）
5. consume_status 三个数字正确
6. judge 分支：带 goal 的 run 走 apply_judged_session 落 RLHF（mock LLM）
7. error run（有 is_error 环）不产候选
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import runner.dream_consumer as dc
from runner.dream_consumer import (
    consume_once,
    consume_status,
    run_records_from_events,
    scan_completed_runs,
)


# ---------------------------------------------------------------------------
# Fixtures — 直接拼 evidence JSONL（与 runner.evidence.append_event 落盘同构）
# ---------------------------------------------------------------------------

def _event(seq: int, kind: str, payload: dict) -> dict:
    return {
        "seq": seq,
        "kind": kind,
        "at": datetime.now(UTC).isoformat(),
        "payload": payload,
        "payload_hash": "0" * 64,
        "prev_hash": None,
        "entry_hash": "0" * 64,
    }


def _write_evidence(dir_path: Path, run_id: str, events: list[dict]) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{run_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return path


def _ok_run(tool_seq: list[str]) -> list[dict]:
    """一个成功 run：tool_call/tool_result 交替 + 收尾带 status 的 output_data。"""
    events: list[dict] = []
    for i, tool in enumerate(tool_seq, start=1):
        events.append(_event(len(events) + 1, "tool_call",
                             {"tool": tool, "args": {}, "tool_call_id": f"c{i}"}))
        events.append(_event(len(events) + 1, "tool_result",
                             {"tool": tool, "tool_call_id": f"c{i}",
                              "result": "ok", "is_error": False}))
    events.append(_event(len(events) + 1, "output_data", {"status": "completed"}))
    return events


@pytest.fixture
def evidence_dir(tmp_path) -> Path:
    return tmp_path / "evidence"


@pytest.fixture
def candidates_dir(tmp_path) -> Path:
    return tmp_path / "distill_candidates"


# ---------------------------------------------------------------------------
# 1. 端到端：一轮产出候选文件 + index 登记
# ---------------------------------------------------------------------------

def test_consume_once_produces_candidate(evidence_dir, candidates_dir):
    """两个成功 run 走同一 tool 序列 → 蒸馏出候选草案 + index 登记。"""
    for run_id in ("run-a", "run-b"):
        _write_evidence(evidence_dir, run_id, _ok_run(["read_blackboard", "calc_risk", "risk_verdict"]))

    summary = consume_once(
        evidence_dir=evidence_dir, candidates_dir=candidates_dir, group="risk",
    )

    assert summary["scanned_runs"] == 2
    assert summary["new_runs"] == 2
    assert len(summary["candidates"]) >= 1
    # 候选草案文件真实落盘（run_distill 写的 candidate-*.md）
    md_files = list(candidates_dir.glob("candidate-*.md"))
    assert md_files, "应有候选 SKILL.md 草案落盘"
    assert "status: draft" in md_files[0].read_text(encoding="utf-8")
    # index.json 登记且带来源 run_ids
    index = json.loads((candidates_dir / "index.json").read_text(encoding="utf-8"))
    assert len(index["candidates"]) == len(summary["candidates"])
    top = index["candidates"][0]
    assert top["group"] == "risk"
    assert set(top["run_ids"]) == {"run-a", "run-b"}


# ---------------------------------------------------------------------------
# 2. 去重：二次运行不重复登记
# ---------------------------------------------------------------------------

def test_second_run_dedupes(evidence_dir, candidates_dir):
    _write_evidence(evidence_dir, "run-a", _ok_run(["read_blackboard", "calc_risk", "risk_verdict"]))
    _write_evidence(evidence_dir, "run-b", _ok_run(["read_blackboard", "calc_risk", "risk_verdict"]))

    first = consume_once(evidence_dir=evidence_dir, candidates_dir=candidates_dir, group="risk")
    n_first = len(first["candidates"])
    assert n_first >= 1

    # 二次：无新 run（consumed 集合已含）→ no-op
    consumed = {"run-a", "run-b"}
    second = consume_once(
        evidence_dir=evidence_dir, candidates_dir=candidates_dir,
        group="risk", consumed_run_ids=consumed,
    )
    assert second["scanned_runs"] == 0
    assert second["candidates"] == []

    # 二次强制重扫同 run → 同名候选被 index 去重
    rerun = consume_once(evidence_dir=evidence_dir, candidates_dir=candidates_dir, group="risk")
    index = json.loads((candidates_dir / "index.json").read_text(encoding="utf-8"))
    keys = [f"{c['name']}|{'>'.join(c['tool_sequence'])}" for c in index["candidates"]]
    assert len(keys) == len(set(keys)), "index 内候选键不得重复"
    assert len(index["candidates"]) == n_first, "重扫不应产生重复登记"


# ---------------------------------------------------------------------------
# 3. 无新 run → no-op；error run 不产候选
# ---------------------------------------------------------------------------

def test_no_new_runs_is_noop(evidence_dir, candidates_dir):
    summary = consume_once(evidence_dir=evidence_dir, candidates_dir=candidates_dir)
    assert summary == {"scanned_runs": 0, "new_runs": 0, "candidates": [], "judged": []}
    assert not (candidates_dir / "index.json").exists()


def test_error_run_yields_no_candidate(evidence_dir, candidates_dir):
    """含 is_error 环的 run 不喂蒸馏（候选只收成功序列）。"""
    events = _ok_run(["read_blackboard", "calc_risk"])
    # 把最后一个 tool_result 翻成 error
    events[3] = _event(4, "tool_result",
                       {"tool": "calc_risk", "tool_call_id": "c2", "result": "boom", "is_error": True})
    _write_evidence(evidence_dir, "bad-1", events)
    _write_evidence(evidence_dir, "bad-2", events)

    summary = consume_once(evidence_dir=evidence_dir, candidates_dir=candidates_dir)
    assert summary["scanned_runs"] == 2
    assert summary["new_runs"] == 0
    assert summary["candidates"] == []


def test_waiting_run_is_not_marked_completed(evidence_dir, candidates_dir):
    """A pending HumanGate is runtime state, never a distillation source."""
    events = _ok_run(["read_blackboard", "calc_risk"])
    events[-1] = _event(len(events), "output_data", {"status": "waiting_for_human"})
    _write_evidence(evidence_dir, "waiting-1", events)
    _write_evidence(evidence_dir, "waiting-2", events)

    summary = consume_once(evidence_dir=evidence_dir, candidates_dir=candidates_dir)

    assert summary["scanned_runs"] == 0
    assert summary["new_runs"] == 0
    assert summary["candidates"] == []


def test_run_records_pairs_results(evidence_dir):
    """配对口径：error 环 → 空；成功环 → 与 tool_call 等长的记录列表。"""
    events = _ok_run(["t1", "t2"])
    recs = run_records_from_events("r1", events, group="risk")
    assert [r["action"]["tool_name"] for r in recs] == ["t1", "t2"]
    assert all(r["thread_id"] == "r1" and r["group"] == "risk" for r in recs)


def test_run_records_match_tool_results_by_call_id_and_require_all_results():
    """Multi-call evidence must not be paired by the last-seen call."""
    events = [
        {"kind": "tool_call", "payload": {"tool": "first", "args": {}, "tool_call_id": "c1"}},
        {"kind": "tool_call", "payload": {"tool": "second", "args": {}, "tool_call_id": "c2"}},
        {"kind": "tool_result", "payload": {"tool": "first", "tool_call_id": "c1", "is_error": False}},
        {"kind": "tool_result", "payload": {"tool": "second", "tool_call_id": "c2", "is_error": False}},
    ]
    recs = run_records_from_events("multi", events, group="factor")
    assert [r["action"]["tool_name"] for r in recs] == ["first", "second"]

    missing = run_records_from_events("missing", events[:-1], group="factor")
    assert missing == []


# ---------------------------------------------------------------------------
# 4. CLI --once 退出码
# ---------------------------------------------------------------------------

def test_cli_once_exit_code(tmp_path, evidence_dir, candidates_dir):
    _write_evidence(evidence_dir, "cli-run", _ok_run(["read_blackboard", "calc_risk"]))

    result = subprocess.run(
        [
            sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "dream_consume.py"),
            "--once",
            "--evidence-dir", str(evidence_dir),
            "--candidates-dir", str(candidates_dir),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"CLI 应成功, stderr: {result.stderr}"
    assert "[dream_consume]" in result.stdout
    assert (candidates_dir / ".last_consumed").exists()


# ---------------------------------------------------------------------------
# 5. consume_status 数字
# ---------------------------------------------------------------------------

def test_consume_status_numbers(evidence_dir, candidates_dir, tmp_path):
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        "\n".join(json.dumps({"thread_id": f"t{i}"}) for i in range(3)) + "\n",
        encoding="utf-8",
    )

    # 空状态：无候选、未消费、行数=3
    status = consume_status(candidates_dir=candidates_dir, rlhf_path=rlhf)
    assert status == {"candidates": 0, "last_consumed": None, "rlhf_lines": 3}

    # 消费一轮后：候选 ≥1、last_consumed 指纹存在
    _write_evidence(evidence_dir, "s-1", _ok_run(["read_blackboard", "calc_risk"]))
    _write_evidence(evidence_dir, "s-2", _ok_run(["read_blackboard", "calc_risk"]))
    consume_once(evidence_dir=evidence_dir, candidates_dir=candidates_dir)

    status = consume_status(candidates_dir=candidates_dir, rlhf_path=rlhf)
    assert status["candidates"] >= 1
    assert status["last_consumed"]
    assert status["rlhf_lines"] == 3


# ---------------------------------------------------------------------------
# 6. judge 分支：goal run → apply_judged_session 落 RLHF
# ---------------------------------------------------------------------------

def test_judge_new_runs_writes_rlhf(monkeypatch, tmp_path):
    """--with-judge 路径：met verdict → label=1 回填 RLHF。"""
    import runner.routing.session_review as sr
    import runner.routing.rlhf_logger as rl

    rlhf_path = tmp_path / "rlhf_data.jsonl"
    monkeypatch.setattr(rl, "RLHF_PATH", rlhf_path)
    monkeypatch.setattr(sr, "RLHF_PATH", rlhf_path)
    rlhf_path.write_text(
        json.dumps({
            "thread_id": "goal-1", "gate_purpose": "normal", "label": None,
            "risk_score": 0.42, "metadata": {"iteration": 1},
        }) + "\n", encoding="utf-8",
    )

    trace = [
        {"schema_version": "agent_trace.v1", "seq": 1, "type": "tool_call",
         "thread_id": "goal-1", "data": {"tool": "calc_risk", "tool_call_id": "c1"}},
        {"schema_version": "agent_trace.v1", "seq": 2, "type": "tool_result",
         "thread_id": "goal-1", "data": {"tool": "calc_risk", "tool_call_id": "c1",
                                         "result": "ok", "is_error": False}},
        {"schema_version": "agent_trace.v1", "seq": 3, "type": "output_data",
         "thread_id": "goal-1", "data": {"status": "completed"}},
    ]

    def _llm(messages, tools=None):
        return AIMessage(content='{"verdict": "met", "reasons": ["done"]}')

    runs = [{"run_id": "goal-1", "goal": "算一遍 risk", "trace": trace}]
    reports = dc.judge_new_runs(runs, llm=_llm)

    assert len(reports) == 1
    assert reports[0]["verdict"] == "met"
    assert reports[0]["mode"] == "judge"
    records = [json.loads(l) for l in rlhf_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r.get("label") == 1 for r in records), "met verdict 应回填 label=1"


def test_judge_new_runs_skips_goalless():
    """无 goal 的 run 直接跳过，不调 judge 不碰文件。"""
    assert dc.judge_new_runs([{"run_id": "x"}]) == []


def test_consume_rolls_back_seen_ids_when_processing_fails(evidence_dir, candidates_dir, monkeypatch):
    """Transient consumer failures must not permanently drop completed runs."""
    _write_evidence(evidence_dir, "retry-me", _ok_run(["read_blackboard", "calc_risk"]))
    consumed: set[str] = set()

    def fail_once(*args, **kwargs):
        raise RuntimeError("temporary distill failure")

    monkeypatch.setattr(dc, "distill_new_runs", fail_once)
    with pytest.raises(RuntimeError, match="temporary"):
        consume_once(
            evidence_dir=evidence_dir,
            candidates_dir=candidates_dir,
            consumed_run_ids=consumed,
        )

    assert consumed == set()


def test_consume_marks_seen_only_after_successful_processing(evidence_dir, candidates_dir):
    """A completed but malformed run remains retryable until processing succeeds."""
    events = _ok_run(["read_blackboard"])
    # Keep the terminal marker but remove the matching result, making the run
    # non-distillable while still satisfying the scanner's completion marker.
    events = [event for event in events if not (
        event.get("kind") == "tool_result"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("tool_call_id") == "c1"
    )]
    _write_evidence(evidence_dir, "malformed-complete", events)
    consumed: set[str] = set()

    first = consume_once(
        evidence_dir=evidence_dir,
        candidates_dir=candidates_dir,
        consumed_run_ids=consumed,
    )
    assert first["scanned_runs"] == 1 and first["new_runs"] == 0
    assert consumed == {"malformed-complete"}

    # A caller can clear/reprocess the id after repairing evidence; the
    # consumer itself does not mark it before downstream work.
    consumed.clear()
    _write_evidence(evidence_dir, "malformed-complete", _ok_run(["read_blackboard"]))
    repaired = consume_once(
        evidence_dir=evidence_dir,
        candidates_dir=candidates_dir,
        consumed_run_ids=consumed,
    )
    assert repaired["new_runs"] == 1

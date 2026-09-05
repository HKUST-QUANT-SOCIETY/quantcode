"""Tests for runner.judge + runner.routing.session_review（PRD §4.4 P2 Goal+Judge）。

覆盖：
- judge_run：mock LLM 三分支（met / partial / missed）+ 诚实降级
  （无 LLM / 非法 JSON / 非法 verdict / LLM 异常 / 空 goal）→ unevaluated
- summarize_run：agent_engine.stream() v1 事件形态 + 旧版扁平形态
- apply_session_verdict：monkeypatch RLHF_PATH 常量 → jsonl 回填断言
- apply_judged_session：假 trace → verdict → label 端到端
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import runner.routing.session_review as session_review_module
from runner.judge import VALID_VERDICTS, judge_run, summarize_run
from runner.routing.rlhf_logger import log_rlhf_entry, make_rlhf_entry
from runner.routing.session_review import (
    apply_judged_session,
    apply_session_verdict,
    reviewer_review_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llm_returning(payload: str):
    """构造 mock LLM callable：(messages, tools=None) -> AIMessage。"""
    def _model(messages, tools=None):
        return AIMessage(content=payload)
    return _model


def _trace_v1(status: str = "completed") -> list[dict]:
    """agent_engine.stream() 的 v1 事件形态假 trace。"""
    return [
        {"schema_version": "agent_trace.v1", "seq": 1, "type": "agent_start",
         "thread_id": "t1", "data": {"task": "build factor"}},
        {"schema_version": "agent_trace.v1", "seq": 2, "type": "tool_call",
         "thread_id": "t1", "data": {"tool": "gen_schema", "args": {}, "tool_call_id": "c1"}},
        {"schema_version": "agent_trace.v1", "seq": 3, "type": "tool_result",
         "thread_id": "t1", "data": {"tool": "gen_schema", "tool_call_id": "c1",
                                     "result": "ok: factor report written", "is_error": False}},
        {"schema_version": "agent_trace.v1", "seq": 4, "type": "tool_call",
         "thread_id": "t1", "data": {"tool": "calc_ic", "args": {}, "tool_call_id": "c2"}},
        {"schema_version": "agent_trace.v1", "seq": 5, "type": "tool_result",
         "thread_id": "t1", "data": {"tool": "calc_ic", "tool_call_id": "c2",
                                     "result": "error: missing price", "is_error": True}},
        {"schema_version": "agent_trace.v1", "seq": 6, "type": "output_data",
         "thread_id": "t1", "data": {"output_data": {"ic": 0.05}}},
        {"schema_version": "agent_trace.v1", "seq": 7, "type": "artifact",
         "thread_id": "t1", "data": {"path": "artifacts/factor/report.json"}},
        {"schema_version": "agent_trace.v1", "seq": 8, "type": "agent_end",
         "thread_id": "t1", "data": {"status": status, "iterations": 3}},
    ]


def _seed_risk_continues(tmp_path: Path, thread_id: str, iterations_scores: list[tuple[int, float]]) -> Path:
    """往临时 RLHF jsonl 写入若干 normal continue 记录，返回该路径。"""
    path = tmp_path / "rlhf_data.jsonl"
    for it, score in iterations_scores:
        entry = make_rlhf_entry(
            thread_id=thread_id,
            group="risk",
            tool_name="calc_risk_stub",
            system_decision="continue",
            human_decision="",
            risk_features={"tail_risk_var_99": 0.03},
            iteration=it,
        )
        entry["risk_score"] = score  # 直接覆盖，确保排序确定性
        log_rlhf_entry(entry, path=path)
    return path


@pytest.fixture
def tmp_rlhf_path(tmp_path, monkeypatch):
    """把 session_review / rlhf_logger 的 RLHF_PATH 指到临时文件。"""
    path = tmp_path / "rlhf_data.jsonl"
    monkeypatch.setattr(session_review_module, "RLHF_PATH", path, raising=True)
    # judge 分支内的延迟 import 也走 rlhf_logger 模块对象 → 其常量同样被 monkeypatch
    import runner.routing.rlhf_logger as rlhf_logger_module
    monkeypatch.setattr(rlhf_logger_module, "RLHF_PATH", path, raising=True)
    return path


# ---------------------------------------------------------------------------
# judge_run — mock LLM 三分支
# ---------------------------------------------------------------------------

class TestJudgeRunBranches:
    def test_met(self):
        llm = _llm_returning('{"verdict": "met", "reasons": ["ic>0.03 达标"]}')
        r = judge_run("factor IC > 0.03", {"status": "completed", "tools": []}, llm=llm)
        assert r["verdict"] == "met"
        assert r["reasons"] == ["ic>0.03 达标"]

    def test_partial(self):
        llm = _llm_returning('{"verdict": "partial", "reasons": ["报告生成但缺回测"]}')
        r = judge_run("全流程跑通", {"status": "completed"}, llm=llm)
        assert r["verdict"] == "partial"

    def test_missed(self):
        llm = _llm_returning('{"verdict": "missed", "reasons": ["报错退出"]}')
        r = judge_run("跑通风控流", {"status": "error"}, llm=llm)
        assert r["verdict"] == "missed"

    def test_verdicts_constant(self):
        assert VALID_VERDICTS == ("met", "partial", "missed")


# ---------------------------------------------------------------------------
# judge_run — 诚实降级 → unevaluated
# ---------------------------------------------------------------------------

class TestJudgeRunUnevaluated:
    def test_no_llm_and_no_env(self, monkeypatch):
        monkeypatch.delenv("QUANTCODE_API_KEY", raising=False)
        r = judge_run("任何目标", {"status": "completed"})
        assert r["verdict"] == "unevaluated"
        assert r["reasons"]  # 有可读原因，不编造

    def test_invalid_json(self):
        llm = _llm_returning("我觉得任务完成得不错！没有 JSON。")
        r = judge_run("目标", {}, llm=llm)
        assert r["verdict"] == "unevaluated"
        assert any("JSON" in s for s in r["reasons"])

    def test_invalid_verdict_value(self):
        llm = _llm_returning('{"verdict": "excellent", "reasons": ["超预期"]}')
        r = judge_run("目标", {}, llm=llm)
        assert r["verdict"] == "unevaluated"

    def test_llm_raises(self):
        def _boom(messages, tools=None):
            raise RuntimeError("API down")
        r = judge_run("目标", {}, llm=_boom)
        assert r["verdict"] == "unevaluated"
        assert any("RuntimeError" in s for s in r["reasons"])

    def test_empty_goal(self):
        r = judge_run("   ", {}, llm=_llm_returning('{"verdict": "met"}'))
        assert r["verdict"] == "unevaluated"

    def test_markdown_fenced_json_is_ok(self):
        llm = _llm_returning('```json\n{"verdict": "met", "reasons": ["ok"]}\n```')
        r = judge_run("目标", {}, llm=llm)
        assert r["verdict"] == "met"


# ---------------------------------------------------------------------------
# summarize_run — trace 提取
# ---------------------------------------------------------------------------

class TestSummarizeRun:
    def test_v1_trace_extraction(self):
        s = summarize_run(_trace_v1(status="completed"))
        assert s["status"] == "completed"
        assert [t["tool"] for t in s["tools"]] == ["gen_schema", "calc_ic"]
        assert s["tools"][0]["success"] is True
        assert s["tools"][1]["success"] is False
        assert len(s["errors"]) == 1
        assert "missing price" in s["errors"][0]
        assert s["artifacts"] == ["artifacts/factor/report.json"]
        assert "ic" in s["output_excerpt"]

    def test_legacy_flat_trace(self):
        trace = [
            {"type": "tool_call", "tool": "t1", "args": {}},
            {"type": "tool_result", "tool": "t1", "result": "failed to fetch", "is_error": True},
            {"type": "artifact", "path": "/tmp/a.csv"},
            {"type": "agent_end", "status": "error", "iterations": 2},
        ]
        s = summarize_run(trace)
        assert s["status"] == "error"
        assert s["tools"][0]["success"] is False
        assert s["errors"] == ["failed to fetch"]
        assert s["artifacts"] == ["/tmp/a.csv"]

    def test_empty_and_none(self):
        s = summarize_run([])
        assert s["status"] == "" and s["tools"] == [] and s["artifacts"] == []
        s2 = summarize_run(None)
        assert s2["tools"] == []


# ---------------------------------------------------------------------------
# apply_session_verdict — 人工裁决回填
# ---------------------------------------------------------------------------

class TestApplySessionVerdict:
    def test_reviewer_default_none(self):
        assert reviewer_review_session("t-x") is None

    def test_risky_auto_top_n(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9), (7, 0.5), (11, 0.8)])
        report = apply_session_verdict("t1", "risky", top_n=1)
        assert report["mode"] == "auto"
        assert report["marked_iterations"] == [3]  # risk_score 最高者
        # label 已回填到第 3 条
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        by_iter = {r["metadata"]["iteration"]: r for r in lines}
        assert by_iter[3]["label"] == 1
        assert by_iter[7]["label"] is None
        assert by_iter[11]["label"] is None

    def test_risky_top_n_2(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9), (7, 0.5), (11, 0.8)])
        report = apply_session_verdict("t1", "risky", top_n=2)
        assert sorted(report["marked_iterations"]) == [3, 11]
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        by_iter = {r["metadata"]["iteration"]: r for r in lines}
        assert by_iter[3]["label"] == 1
        assert by_iter[11]["label"] == 1

    def test_safe_no_change(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9)])
        apply_session_verdict("t1", "safe")
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        assert all(r["label"] is None for r in lines)

    def test_other_threads_untouched(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9)])
        _seed_risk_continues(tmp_rlhf_path.parent, "t2", [(5, 0.7)])
        apply_session_verdict("t1", "risky", top_n=1)
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        t2 = [r for r in lines if r["thread_id"] == "t2"]
        assert all(r["label"] is None for r in t2)


# ---------------------------------------------------------------------------
# apply_judged_session — judge 分支端到端（假 trace → verdict → label）
# ---------------------------------------------------------------------------

class TestApplyJudgedSession:
    def test_met_end_to_end(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9), (7, 0.5)])
        llm = _llm_returning('{"verdict": "met", "reasons": ["目标达成"]}')
        report = apply_judged_session("t1", "factor IC>0.03", _trace_v1(), llm=llm)
        assert report["verdict"] == "met"
        assert report["mode"] == "judge"
        assert report["marked_iterations"] == [3]
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        by_iter = {r["metadata"]["iteration"]: r for r in lines}
        assert by_iter[3]["label"] == 1
        assert by_iter[3]["notes"].startswith("judge:met")
        assert by_iter[7]["label"] is None

    def test_missed_end_to_end(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9)])
        llm = _llm_returning('{"verdict": "missed", "reasons": ["任务失败"]}')
        report = apply_judged_session("t1", "目标", _trace_v1("error"), llm=llm)
        assert report["verdict"] == "missed"
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        top3 = [r for r in lines if r["metadata"]["iteration"] == 3][0]
        assert top3["label"] == 0

    def test_partial_no_label_only_notes(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9), (7, 0.4)])
        llm = _llm_returning('{"verdict": "partial", "reasons": ["一半达成"]}')
        report = apply_judged_session("t1", "目标", _trace_v1(), llm=llm)
        assert report["verdict"] == "partial"
        assert report["marked_iterations"] == []
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        by_iter = {r["metadata"]["iteration"]: r for r in lines}
        assert by_iter[3]["label"] is None          # 0.5 落不进 0/1 域 → 不写 label
        assert by_iter[3]["notes"].startswith("judge:partial")

    def test_unevaluated_touches_nothing(self, tmp_rlhf_path):
        _seed_risk_continues(tmp_rlhf_path.parent, "t1", [(3, 0.9)])
        before = tmp_rlhf_path.read_text()
        report = apply_judged_session("t1", "目标", _trace_v1(), llm=None)
        assert report["verdict"] == "unevaluated"
        assert report["mode"] == "unevaluated"
        assert tmp_rlhf_path.read_text() == before  # 文件一点没动

    def test_no_risk_continues_still_writes_notes_on_normal(self, tmp_rlhf_path):
        # 没有 risk_score 的 normal 记录：partial 时也应记 notes，不抛异常
        entry = make_rlhf_entry(
            thread_id="t9", group="risk", system_decision="continue",
            iteration=1,
        )
        entry.pop("risk_score", None)
        log_rlhf_entry(entry, path=tmp_rlhf_path)
        llm = _llm_returning('{"verdict": "partial", "reasons": ["r"]}')
        report = apply_judged_session("t9", "目标", _trace_v1(), llm=llm)
        assert report["verdict"] == "partial"
        lines = [json.loads(l) for l in tmp_rlhf_path.read_text().splitlines() if l.strip()]
        assert lines[0]["notes"].startswith("judge:partial")
        assert lines[0]["label"] is None
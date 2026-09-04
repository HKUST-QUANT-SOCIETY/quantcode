"""validate_factor_contract / merge_to_main 测试（PRD §4.1.3 / F-06 闭合）。

覆盖:
1. gate 判定：pass+达标 → eligible；marginal/fail → false+reasons；阈值覆盖生效
2. merge 流：gate_rejected → waiting_for_human（interrupt kind=merge）→ approve → 登记
3. 登记幂等（同 code_hash → already）；dry_run 不落盘；mainline 索引结构
4. ScriptedLLM 集成一条：eval_from_panel 产出 → merge_to_main → waiting_for_human
   → resume approve → 登记成功
"""
from __future__ import annotations

import importlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import tools.factor._register as _factor_register
from tools.registry import registry

from tools.factor.merge_to_main import (
    validate_factor_contract_impl,
    merge_to_main_impl,
)


@pytest.fixture(autouse=True)
def _ensure_registered():
    """全量 pytest 时 registry 可能被其他文件清空；reload 注册链（幂等）。"""
    importlib.reload(_factor_register)
    yield


def _good_report(**overrides) -> dict:
    report = {
        "factor_name": "pb_roe",
        "verdict": "pass",
        "evaluation_period": {"start": "2026-01-01", "end": "2026-02-01"},
        "universe": "CSI1000",
        "ic_metrics": {
            "ic_mean": 0.12, "ic_std": 0.03, "ir": 2.5,
            "t_stat": 6.0, "ic_method": "spearman",
        },
        "turnover": {"monthly": 0.3},
        "formula": "roe_ttm / pb",
        "eval_run_id": "pb_roe-panel_real_v1",
    }
    report.update(overrides)
    return report


# ---------------------------------------------------------------------------
# 1. validate_factor_contract 纯判定
# ---------------------------------------------------------------------------


def test_gate_pass_report_eligible():
    out = validate_factor_contract_impl(_good_report())
    assert out["eligible"] is True
    assert out["reasons"] == []
    assert out["verdict"] == "pass"


def test_gate_marginal_not_eligible_with_reason():
    report = _good_report(verdict="marginal")
    out = validate_factor_contract_impl(report)
    assert out["eligible"] is False
    assert any("verdict" in r for r in out["reasons"])
    assert out["verdict"] == "marginal"


def test_gate_metric_below_threshold_gives_reasons():
    report = _good_report(ic_metrics={
        "ic_mean": 0.01, "ic_std": 0.03, "ir": 0.2, "t_stat": 1.0,
    })
    out = validate_factor_contract_impl(report)
    assert out["eligible"] is False
    text = " | ".join(out["reasons"])
    assert "ic_mean" in text and "ir" in text and "t_stat" in text


def test_gate_missing_fields_fail_closed():
    report = _good_report()
    del report["ic_metrics"], report["turnover"]
    out = validate_factor_contract_impl(report)
    assert out["eligible"] is False
    assert any("ic_metrics" in r for r in out["reasons"])
    assert any("turnover" in r for r in out["reasons"])


def test_gate_thresholds_override_via_tmp_yaml(tmp_path, monkeypatch):
    """thresholds 显式传参（tmp yaml 同款语义）覆盖单源：ic_abs_min 提到 0.5。"""
    import runner.config_loader

    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    runner.config_loader.load_yaml.cache_clear()
    try:
        # tmp 配置目录无 acceptance.factor.yaml → 代码默认兜底：|0.12| 达标
        assert validate_factor_contract_impl(_good_report())["eligible"] is True
        # 显式阈值收紧 → 不达标
        out = validate_factor_contract_impl(
            _good_report(), thresholds={"ic_abs_min": 0.5, "ir_min": 0.5,
                                        "turnover_monthly_max": 0.8, "t_stat_min": 2.0}
        )
        assert out["eligible"] is False
        assert any("ic_mean" in r for r in out["reasons"])
    finally:
        runner.config_loader.load_yaml.cache_clear()


def test_check_gate_tool_no_report_write_side_effects(tmp_path):
    """validate_factor_contract_tool 纯判定：不写任何文件、不产生 gate。"""
    before = sorted(p.name for p in tmp_path.iterdir())
    out = registry.call("validate_factor_contract", {"report": _good_report()}, ctx={})
    assert out["eligible"] is True
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ---------------------------------------------------------------------------
# 2. merge_to_main impl：gate → HumanGate → 登记
# ---------------------------------------------------------------------------


def test_merge_gate_rejected(tmp_path):
    idx = tmp_path / "mainline" / "factors.json"
    out = merge_to_main_impl("pb_roe", _good_report(verdict="fail"), index_path=idx)
    assert out == {
        "merged": False, "stage": "gate_rejected", "eligible": False,
        "verdict": "fail", "reasons": out["reasons"], "gate_id": None,
    }
    assert out["reasons"]
    assert not idx.exists()


def test_merge_waiting_for_human_builds_merge_gate(tmp_path):
    idx = tmp_path / "mainline" / "factors.json"
    out = merge_to_main_impl(
        "pb_roe", _good_report(), index_path=idx, thread_id="t-merge"
    )
    assert out["stage"] == "waiting_for_human"
    assert out["merged"] is False
    gate = out["gate"]
    assert gate["kind"] == "merge"
    assert gate["gate_id"].startswith("hg_t-merge_")
    assert gate["evidence"]["factor_id"] == "pb_roe"
    # 未落盘：等人审
    assert not idx.exists()


def test_merge_dry_run_returns_record_without_writes(tmp_path):
    idx = tmp_path / "mainline" / "factors.json"
    out = merge_to_main_impl("pb_roe", _good_report(), dry_run=True, index_path=idx)
    assert out["dry_run"] is True
    assert out["stage"] == "dry_run"
    rec = out["record"]
    assert rec["factor_id"] == "pb_roe"
    assert rec["factor_name"] == "pb_roe"
    assert rec["formula"] == "roe_ttm / pb"
    assert rec["rank_ic"] == 0.12
    assert rec["report_path"] == "artifacts/factor/pb_roe-report-real.json"
    assert rec["code_hash"] and len(rec["code_hash"]) == 16
    assert not idx.exists()


def test_merge_idempotent_by_code_hash(tmp_path):
    idx = tmp_path / "mainline" / "factors.json"
    first = merge_to_main_impl(
        "pb_roe", _good_report(), human_approved=True, index_path=idx
    )
    assert first["merged"] is True and first["already"] is False
    second = merge_to_main_impl(
        "pb_roe", _good_report(), human_approved=True, index_path=idx
    )
    assert second["merged"] is True and second["already"] is True
    assert second["record"]["code_hash"] == first["record"]["code_hash"]
    # 索引只有一条
    assert len(json.loads(idx.read_text(encoding="utf-8"))) == 1


def test_merge_writes_mainline_index_structure(tmp_path):
    """登记簿是普通 JSON 清单（非 _contract 契约），字段齐全。"""
    idx = tmp_path / "mainline" / "factors.json"
    out = merge_to_main_impl(
        "pb_roe", _good_report(), human_approved=True, index_path=idx
    )
    entries = json.loads(idx.read_text(encoding="utf-8"))
    assert isinstance(entries, list) and len(entries) == 1
    entry = entries[0]
    assert entry["code_hash"] == out["record"]["code_hash"]
    for key in ("factor_id", "factor_name", "merged_at", "rank_ic",
                "formula", "code_hash", "report_path"):
        assert key in entry, key


def test_approved_merge_writes_decision_record_to_evidence_chain(tmp_path):
    """An approved merge must be replayable as a HumanGate decision."""
    idx = tmp_path / "mainline" / "factors.json"
    evidence_dir = tmp_path / "evidence"
    out = merge_to_main_impl(
        "pb_roe",
        _good_report(),
        human_approved=True,
        index_path=idx,
        evidence_dir=evidence_dir,
        thread_id="merge-evidence-1",
        actor_id="factor-approver",
    )

    from runner.evidence import build_report

    report = build_report("merge-evidence-1", evidence_dir)
    assert out["merged"] is True
    assert report.decision is not None
    assert report.decision.gate_id
    assert report.decision.action.value == "approve"
    assert report.decision.decided_by == "factor-approver"


def test_merge_thresholds_cover(tmp_path):
    """merge 前置 gate 同样接受 thresholds 覆盖（与 check impl 同参）。"""
    idx = tmp_path / "mainline" / "factors.json"
    out = merge_to_main_impl(
        "pb_roe", _good_report(), human_approved=True, index_path=idx,
        thresholds={"ic_abs_min": 0.9, "ir_min": 0.5, "turnover_monthly_max": 0.8,
                    "t_stat_min": 2.0},
    )
    assert out["stage"] == "gate_rejected"


# ---------------------------------------------------------------------------
# 3. ToolDef 层：human_approved 不可自批 + registry 端到端
# ---------------------------------------------------------------------------


def test_merge_tool_schema_has_no_human_approved_param():
    """防 LLM 自批：MergeMainArgs 不存在 human_approved 参数。"""
    from tools.factor.merge_to_main import MergeMainArgs

    assert "human_approved" not in MergeMainArgs.model_fields


def test_merge_tool_via_registry_waits_for_human(tmp_path):
    """registry.call（图外）：eligible 但未人审 → waiting_for_human，不落盘。"""
    idx = tmp_path / "mainline" / "factors.json"
    out = registry.call(
        "merge_to_main",
        {"factor_id": "pb_roe", "report": _good_report()},
        ctx={"mainline_index": idx, "thread_id": "ctx-t"},
    )
    assert out["stage"] == "waiting_for_human"
    assert out["gate"]["kind"] == "merge"
    assert not idx.exists()


def test_merge_tool_via_registry_respects_ctx_human_approved(tmp_path):
    """human_approved 只能经 ctx 注入（图外手动路径）。"""
    idx = tmp_path / "mainline" / "factors.json"
    out = registry.call(
        "merge_to_main",
        {"factor_id": "pb_roe", "report": _good_report()},
        ctx={"mainline_index": idx, "human_approved": True},
    )
    assert out["merged"] is True and out["stage"] == "merged"
    assert idx.exists()


# ---------------------------------------------------------------------------
# 4. ScriptedLLM 集成：eval_from_panel 产出 → merge → waiting → approve → 登记
# ---------------------------------------------------------------------------

ASSET_COUNT = 10
DATE_COUNT = 30


def _perfect_panel_values() -> list[list[float]]:
    """与 test_factor_eval_real 同款保序面板：截面 rank IC ≈ 1。"""
    import numpy as np

    g = np.array([0.01 * (a + 1) for a in range(ASSET_COUNT)])
    values = np.empty((DATE_COUNT, ASSET_COUNT))
    values[0] = 1.0
    for t in range(1, DATE_COUNT):
        gt = g.copy()
        if t == 15:
            gt[8], gt[9] = gt[9], gt[8]
        values[t] = values[t - 1] * (1.0 + gt)
    return values.tolist()


def test_agent_flow_eval_then_merge_pause_then_approve(tmp_path, monkeypatch):
    """AgentRunner 集成：eval_from_panel → merge_to_main（HumanGate 暂停）
    → resume approve → 登记成功。human_approved 由 graph resume 注入。"""
    from runner.agent_engine import AgentRunner
    from runner.config_loader import load_yaml
    from runner.langgraph_base import clear_checkpointer_cache
    from schemas.data_contracts import FactorPanel
    from tools.market import backing

    # mainline 索引落到 tmp（configs/factor_main.yaml 单源，QUANTCODE_CONFIG_DIR 覆盖）
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    (cfg_dir / "factor_main.yaml").write_text(
        f'mainline_index: "{tmp_path / "mainline" / "factors.json"}"\n'
        "require_human: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(cfg_dir))
    evidence_target = tmp_path / "evidence"
    monkeypatch.setenv("QUANTCODE_EVIDENCE_DIR", str(evidence_target))
    load_yaml.cache_clear()
    clear_checkpointer_cache()
    idx_path = tmp_path / "mainline" / "factors.json"
    panel = FactorPanel(
        factor_id="pb_roe_lead",
        factor_version="v1",
        data_snapshot_id="snap-test",
        dates=[date(2026, 7, 6) + timedelta(days=i) for i in range(DATE_COUNT)],
        assets=[f"{600000 + i}.SH" for i in range(ASSET_COUNT)],
        values=_perfect_panel_values(),
        source_path="synthetic",
    )
    written = backing.write_panel_to_blackboard(
        panel, blackboard_db_path=tmp_path / "bb.db",
        written_by_task_id="T1", written_by_group="factor",
    )
    panel_key = written["blackboard_key"]

    def _ai(name: str, args: dict, cid: str) -> AIMessage:
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])

    # eval_from_panel 的 summary 即 FactorReport dict；merge 脚本用同源负载
    from tools.factor.eval_from_panel import eval_from_panel_impl

    eval_out = eval_from_panel_impl(
        panel_key, blackboard_db_path=tmp_path / "bb.db"
    )
    assert "error" not in eval_out, eval_out
    merge_report = {
        k: eval_out["summary"][k]
        for k in ("factor_name", "verdict", "ic_metrics", "turnover",
                  "eval_run_id", "evaluation_period", "universe")
        if k in eval_out["summary"]
    }
    merge_report["formula"] = "lead_proxy"
    assert merge_report["verdict"] == "pass", merge_report.get("verdict")

    class _ScriptedLLM:
        def __init__(self):
            self._i = 0

        def __call__(self, messages, tools=None):
            self._i += 1
            # resume 后第 3 次调用：merge tool 已返回 merged 结果 → 收尾
            if self._i == 1:
                return _ai("eval_from_panel", {"panel_key": panel_key}, "c1")
            if self._i == 2:
                return _ai(
                    "merge_to_main",
                    {"factor_id": "pb_roe_lead", "report": merge_report},
                    "c2",
                )
            return AIMessage(content="done")

    llm = _ScriptedLLM()
    runner = AgentRunner(
        group="factor", model=llm,
        checkpoint_db=tmp_path / "ckpt.db",
        # dataset 工具（eval_from_panel/merge_to_main）在图内读同一 bb 文件
        # （与上方 backing.write_panel_to_blackboard 写入的 tmp bb.db 同源）
        blackboard_db_path=tmp_path / "bb.db",
    )
    paused = runner.stream(
        task="评估 pb_roe_lead 并合入主线",
        thread_id="merge-e2e-1",
        flow_name="merge_e2e",
    )
    try:
        assert paused.get("status") == "waiting_for_human" or "__interrupt__" in paused
        # interrupt 是 kind=merge 的 gate
        from runner.human_gate import extract_interrupt_payload

        payload = extract_interrupt_payload(paused)
        assert payload is not None and payload.get("kind") == "merge", payload
        assert (payload.get("evidence") or {}).get("factor_id") == "pb_roe_lead"
        assert not idx_path.exists(), "人审前不落盘"

        resumed = runner.resume(
            thread_id="merge-e2e-1", decision="approve", flow_name="merge_e2e",
        )
        assert "__interrupt__" not in resumed
        assert idx_path.exists(), "approve 后登记落盘"
        entries = json.loads(idx_path.read_text(encoding="utf-8"))
        assert entries and entries[0]["factor_id"] == "pb_roe_lead"
        # 登记后的 tool 结果含 merged 状态
        assert any(
            "merged" in str(getattr(m, "content", "")) for m in resumed["messages"]
        )
        from runner.evidence import build_report

        evidence_report = build_report("merge-e2e-1", evidence_target)
        assert evidence_report.decision is not None
        assert evidence_report.decision.action.value == "approve"
        assert evidence_report.decision.decided_by == "approver"
        assert any(event.kind.value == "tool_call" for event in evidence_report.chain)
    finally:
        clear_checkpointer_cache()
        load_yaml.cache_clear()

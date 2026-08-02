#!/usr/bin/env python3
"""Day5 §7 acceptance runner — strategy / fundamental / options.

Validates functional goals (not just a smoke script):
1. Tool chains produce schema-valid artifacts
2. fundamental pit_rag uses Chroma when installed + PIT filter
3. fundamental human-review gate via AgentRunner interrupt/resume
4. strategy/options AgentRunner multi-step tool calls
5. fixtures inventory present with degradation labels

Usage::

    python3 scripts/accept_jerry_day5.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from langchain_core.messages import AIMessage

from runner.agent_engine import AgentRunner
from runner.archive_pack import pack_jerry_demo_results
from runner.jerry_demos import run_all_demos
from runner.langgraph_base import clear_checkpointer_cache
from schemas.archive import ArchiveManifest, ArchiveSource
from schemas.fundamental import PITResult, ResearchResult
from schemas.options import GreeksProfile, OptionsBacktestReport, VolSurfaceResult
from schemas.strategy import StrategyReport
from tools.registry import PROJECT_ROOT, registry


class ScriptedLLM:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="done")
        self._idx += 1
        return resp


def _ai(name: str, args: dict, cid: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": cid}],
    )


def _check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise AssertionError(name)


def accept_linear_demos() -> dict:
    # archive=False here; we pack once with acceptance source tag below
    results = run_all_demos(archive=False)
    s_path = PROJECT_ROOT / results["strategy"]["artifact_path"]
    StrategyReport.model_validate(json.loads(s_path.read_text(encoding="utf-8")))
    _check("strategy StrategyReport schema", True, s_path.name)

    o_path = PROJECT_ROOT / results["options"]["artifact_path"]
    o = json.loads(o_path.read_text(encoding="utf-8"))
    VolSurfaceResult.model_validate(
        {
            k: o["vol_surface"][k]
            for k in (
                "underlying",
                "as_of_date",
                "forward_price",
                "points",
                "interpolation_method",
                "data_quality",
            )
            if k in o["vol_surface"]
        }
    )
    GreeksProfile.model_validate(
        {
            k: v
            for k, v in o["greeks_profile"].items()
            if k
            in (
                "underlying",
                "as_of_date",
                "portfolio_greeks",
                "leg_greeks",
                "currency",
            )
        }
    )
    OptionsBacktestReport.model_validate(o["backtest"])
    _check("options OptionsRisk bundle schema", True, o_path.name)

    f = results["fundamental"]
    b_path = PROJECT_ROOT / f["artifact_path"]
    bundle = json.loads(b_path.read_text(encoding="utf-8"))
    PITResult.model_validate(bundle["pit"])
    ResearchResult.model_validate(bundle["research"])
    _check(
        "fundamental PIT filtered lookahead",
        bundle["pit_safety"]["filtered_count"] >= 1
        and bundle["pit_safety"]["all_published_at_lte_as_of"],
        f"backend={bundle['pit_safety']['backend']}",
    )
    _check(
        "fundamental markdown filled",
        bundle.get("markdown_filled") is True,
        bundle["research"].get("markdown_path"),
    )
    md = (PROJECT_ROOT / bundle["research"]["markdown_path"]).read_text(encoding="utf-8")
    _check("fundamental markdown has DCF/PIT", "Fair value" in md and "FCF TTM" in md)
    _check(
        "fundamental human_gate recorded",
        bundle.get("human_gate", {}).get("decision") == "approve",
    )

    packs = pack_jerry_demo_results(
        results,
        source=ArchiveSource.ACCEPTANCE,
        acceptance={"status": "passed", "suite": "accept_jerry_day5.linear_demos"},
    )
    for track, pack in packs.items():
        ArchiveManifest.model_validate(pack.manifest.model_dump())
        _check(
            f"archive pack {track}",
            pack.file_count >= 1 and (PROJECT_ROOT / pack.manifest_path).exists(),
            pack.archive_dir,
        )
        results[track]["archive_id"] = pack.archive_id
        results[track]["archive_dir"] = pack.archive_dir
    return results


def accept_agentrunner_fundamental_human_gate() -> None:
    import tools.fundamental._register  # noqa: F401

    tmp = Path(tempfile.mkdtemp())
    db = tmp / "ckpt.db"
    thread_id = "accept-fund-1"
    try:
        clear_checkpointer_cache()
        llm = ScriptedLLM(
            [
                _ai(
                    "pit_rag_search",
                    {"query": "蜜雪冰城 估值", "as_of_date": "2025-01-01"},
                    "c1",
                ),
                _ai(
                    "extract_financial",
                    {"target_identifier": "2097.HK", "as_of_date": "2025-01-01"},
                    "c2",
                ),
                _ai(
                    "dcf_valuation",
                    {
                        "target_identifier": "2097.HK",
                        "fcf_ttm": 1944.0,
                        "shares_outstanding_m": 812.0,
                    },
                    "c3",
                ),
                _ai(
                    "render_report",
                    {
                        "target_identifier": "2097.HK",
                        "target_name": "蜜雪冰城",
                        "as_of_date": "2025-01-01",
                        "fair_value_per_share": 43.47,
                        "use_typst": False,
                    },
                    "c4",
                ),
                _ai(
                    "request_human_review",
                    {"reason": "研报待研究员验收"},
                    "c5",
                ),
                # After human approve resume, finish cleanly.
                _ai("mark_task_done", {"summary": "研报已人审通过"}, "c6"),
            ]
        )
        runner = AgentRunner(group="fundamental", model=llm, checkpoint_db=db)
        paused = runner.stream(
            task="分析公司 2097.HK 估值并提交人审",
            skill_name="fundamental-compose",
            thread_id=thread_id,
            flow_name="fundamental_accept",
        )
        ids = {t.id for t in registry.get_tools_for_group("fundamental")}
        _check(
            "fundamental allowlist has request_human_review",
            "request_human_review" in ids,
            str(sorted(ids)),
        )
        waiting = (
            paused.get("status") == "waiting_for_human"
            or "__interrupt__" in paused
            or any(
                e.get("type") == "human_gate"
                for e in (paused.get("execution_trace") or [])
            )
        )
        _check(
            "fundamental AgentRunner interrupt at human review",
            waiting,
            f"status={paused.get('status')} keys={sorted(paused.keys())[:12]}",
        )

        resumed = runner.resume(
            thread_id=thread_id,
            decision="approve",
            skill_name="fundamental-compose",
            flow_name="fundamental_accept",
        )
        _check(
            "fundamental AgentRunner resume approve",
            isinstance(resumed, dict)
            and "__interrupt__" not in resumed
            and resumed.get("task_status") == "done",
            f"task_status={resumed.get('task_status') if isinstance(resumed, dict) else None}",
        )
    finally:
        clear_checkpointer_cache()
        shutil.rmtree(tmp, ignore_errors=True)


def accept_agentrunner_strategy_options() -> None:
    import tools.options._register  # noqa: F401
    import tools.strategy._register  # noqa: F401

    tmp = Path(tempfile.mkdtemp())
    try:
        clear_checkpointer_cache()
        llm_s = ScriptedLLM(
            [
                _ai(
                    "select_signals",
                    {
                        "candidates": [
                            {
                                "signal_id": "pb_roe_ranker",
                                "source_group": "factor",
                                "weight_hint": 0.4,
                            },
                            {
                                "signal_id": "momentum_20d",
                                "source_group": "factor",
                                "weight_hint": 0.3,
                            },
                        ]
                    },
                    "s1",
                ),
                _ai(
                    "combine_signals",
                    {
                        "selected": [
                            {
                                "signal_id": "pb_roe_ranker",
                                "source_group": "factor",
                                "weight_hint": 0.4,
                            },
                            {
                                "signal_id": "momentum_20d",
                                "source_group": "factor",
                                "weight_hint": 0.3,
                            },
                        ]
                    },
                    "s2",
                ),
                _ai(
                    "run_strategy_backtest",
                    {
                        "strategy_name": "multi_signal_csi1000",
                        "as_of_date": "2026-06-27",
                        "weights": {"pb_roe_ranker": 0.57, "momentum_20d": 0.43},
                    },
                    "s3",
                ),
                AIMessage(content="strategy done"),
            ]
        )
        r1 = AgentRunner(
            group="strategy", model=llm_s, checkpoint_db=tmp / "s.db"
        ).run(
            task="组合 PB-ROE 与动量信号并回测",
            skill_name="strategy-compose",
            thread_id="accept-strat-1",
        )
        _check("strategy AgentRunner iterations", r1.get("iterations", 0) >= 2)

        llm_o = ScriptedLLM(
            [
                _ai(
                    "build_vol_surface",
                    {
                        "strategy_name": "gc_vol_carry",
                        "underlying": "GC",
                        "as_of_date": "2026-06-27",
                    },
                    "o1",
                ),
                _ai(
                    "calc_greeks",
                    {
                        "underlying": "GC",
                        "as_of_date": "2026-06-27",
                        "spot_price": 3400.0,
                    },
                    "o2",
                ),
                AIMessage(content="options done"),
            ]
        )
        r2 = AgentRunner(
            group="options", model=llm_o, checkpoint_db=tmp / "o.db"
        ).run(
            task="构建 GC 波动率曲面并计算 Greeks",
            skill_name="options-compose",
            thread_id="accept-opt-1",
        )
        _check("options AgentRunner iterations", r2.get("iterations", 0) >= 2)
    finally:
        clear_checkpointer_cache()
        shutil.rmtree(tmp, ignore_errors=True)


def accept_fixtures_inventory() -> None:
    required = [
        "tests/fixtures/pit_corpus_sample.json",
        "tests/fixtures/strategy_backtest_result.json",
        "tests/fixtures/factor_backtest_result.json",
        "tests/fixtures/risk_metrics_normal.json",
        "tests/fixtures/risk_metrics_breach.json",
        "tests/fixtures/sample_model/model_spec.json",
        "data/sample_options/gc_options_merged_sample.csv",
        "tests/fixtures/README.md",
    ]
    for rel in required:
        _check(f"fixture exists {rel}", (PROJECT_ROOT / rel).exists())


def main() -> int:
    print("=== Day5 Jerry acceptance ===")
    accept_fixtures_inventory()
    accept_linear_demos()
    accept_agentrunner_strategy_options()
    accept_agentrunner_fundamental_human_gate()
    pit = registry.call(
        "pit_rag_search",
        {"query": "蜜雪冰城", "as_of_date": "2025-01-01"},
    )
    _check(
        "pit_rag backend reported",
        pit.get("backend") in ("chroma", "fixture_json"),
        str(pit.get("backend")),
    )
    if pit.get("backend") == "chroma":
        _check("pit_rag using Chroma", True)
    else:
        print(
            "[WARN] chromadb not available — backend=fixture_json "
            "(install chromadb to satisfy 真 Chroma)"
        )
        _check("pit_rag using Chroma", False, "chromadb missing")
    print("=== ALL ACCEPTANCE CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

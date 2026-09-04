"""Day 5 demo pipelines — strategy / fundamental / options（刘炽）。

可被 scripts/demo_jerry_tracks.py 与 pytest 复用；走 ToolRegistry 真 tool 链，
产出 artifact 并通过 Pydantic schema 校验。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from schemas.fundamental import PITResult, ResearchResult
from schemas.options import GreeksProfile, OptionsBacktestReport, VolSurfaceResult
from schemas.strategy import StrategyReport
from tools.registry import PROJECT_ROOT, registry

import tools.fundamental._register  # noqa: F401
import tools.options._register  # noqa: F401
import tools.strategy._register  # noqa: F401


def _write_artifact(rel_path: str, payload: dict) -> str:
    path = PROJECT_ROOT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rel_path


def run_strategy_demo(
    *,
    fixture_path: str = "tests/fixtures/strategy_backtest_result.json",
) -> dict[str, Any]:
    """select → combine → backtest → deploy，产出 StrategyReport。"""
    fixture = json.loads((PROJECT_ROOT / fixture_path).read_text(encoding="utf-8"))

    selected = registry.call(
        "select_signals",
        {
            "candidates": fixture["candidates"],
            "max_positions": 3,
            "min_weight_hint": 0.05,
        },
    )
    combined = registry.call(
        "combine_signals",
        {"selected": selected["selected"], "target_gross_exposure": 1.0},
    )
    report_raw = registry.call(
        "run_strategy_backtest",
        {
            "strategy_name": fixture["strategy_name"],
            "as_of_date": fixture["as_of_date"],
            "weights": combined["weights"],
        },
    )
    report = StrategyReport.model_validate(report_raw)

    deploy = registry.call(
        "deployment_candidate",
        {
            "strategy_name": report.strategy_name,
            "verdict": report.verdict.value,
        },
    )

    artifact_path = _write_artifact(
        f"artifacts/strategy/{report.strategy_name}/strategy_report.json",
        report.model_dump(mode="json"),
    )
    return {
        "track": "strategy",
        "schema": "StrategyReport",
        "artifact_path": artifact_path,
        "verdict": report.verdict.value,
        "deploy_status": deploy.get("status"),
        "selected_signals": report.selected_signals,
    }


def run_fundamental_demo(
    *,
    target_identifier: str = "2097.HK",
    target_name: str = "蜜雪冰城",
    as_of_date: str = "2025-01-01",
    query: str = "蜜雪冰城 财务 估值",
) -> dict[str, Any]:
    """pit_rag → extract → dcf → render；验证 PIT 时点安全。"""
    pit_raw = registry.call(
        "pit_rag_search",
        {"query": query, "as_of_date": as_of_date, "top_k": 10},
    )
    pit = PITResult.model_validate(
        {k: v for k, v in pit_raw.items() if k not in ("backend", "pit_rule")}
    )
    assert all(d.published_at <= pit.as_of_date for d in pit.documents), (
        "PIT violation: published_at > as_of_date"
    )
    backend = pit_raw.get("backend", "unknown")

    fin = registry.call(
        "extract_financial",
        {
            "target_identifier": target_identifier,
            "as_of_date": as_of_date,
            "documents": [d.model_dump(mode="json") for d in pit.documents],
        },
    )
    dcf = registry.call(
        "dcf_valuation",
        {
            "target_identifier": target_identifier,
            "fcf_ttm": fin["fcf_ttm"],
            "shares_outstanding_m": fin["shares_outstanding_m"],
        },
    )
    report_raw = registry.call(
        "render_report",
        {
            "target_identifier": target_identifier,
            "target_name": target_name,
            "as_of_date": as_of_date,
            "research_questions": ["收入增长驱动力？", "估值是否合理？"],
            "fair_value_per_share": dcf["fair_value_per_share"],
            "citations_count": len(pit.documents),
            "use_typst": True,
            "financials": fin,
            "dcf": dcf,
            "documents": [d.model_dump(mode="json") for d in pit.documents],
            "pit_filtered_count": pit.filtered_count,
        },
    )
    research = ResearchResult.model_validate(
        {
            k: v
            for k, v in report_raw.items()
            if k not in ("typst_used", "markdown_filled", "pdf_filled")
        }
    )

    # Human review gate (Pattern 5) — deterministic approve for automated acceptance.
    # In OpenCode/AgentRunner this is an interrupt; here we record the gate payload.
    human_gate = {
        "tool": "request_human_review",
        "reason": f"研报待验收: {target_identifier} as_of {as_of_date}",
        "status": "approved_for_acceptance",
        "decision": "approve",
        "note": "Automated acceptance path records gate; live AgentRunner uses interrupt/resume",
    }

    bundle = {
        "target_identifier": target_identifier,
        "as_of_date": as_of_date,
        "pit": pit.model_dump(mode="json"),
        "pit_safety": {
            "filtered_count": pit.filtered_count,
            "all_published_at_lte_as_of": True,
            "backend": backend,
            "pit_rule": pit_raw.get("pit_rule", "published_at <= as_of_date"),
            "note": (
                "Day5: prefer Chroma PersistentClient; "
                "fixture_json only if chromadb unavailable"
            ),
        },
        "financials": fin,
        "dcf": dcf,
        "research": research.model_dump(mode="json"),
        "human_gate": human_gate,
        "typst_used": report_raw.get("typst_used", False),
        "pdf_filled": report_raw.get("pdf_filled", False),
        "markdown_filled": report_raw.get("markdown_filled", False),
    }
    artifact_path = _write_artifact(
        f"artifacts/research/{target_identifier.replace('.', '_')}-{as_of_date}/fundamental_bundle.json",
        bundle,
    )
    return {
        "track": "fundamental",
        "schema": "PITResult + ResearchResult",
        "artifact_path": artifact_path,
        "pit_filtered_count": pit.filtered_count,
        "pit_doc_count": len(pit.documents),
        "pit_backend": backend,
        "human_gate": human_gate["status"],
        "markdown_path": research.markdown_path,
        "pdf_path": research.pdf_path,
        "typst_used": report_raw.get("typst_used", False),
        "markdown_filled": report_raw.get("markdown_filled", False),
        "pdf_filled": report_raw.get("pdf_filled", False),
    }


def run_options_demo(
    *,
    strategy_name: str = "gc_vol_carry",
    underlying: str = "GC",
    as_of_date: str = "2026-06-27",
) -> dict[str, Any]:
    """build_vol_surface → calc_greeks → backtest，产出 OptionsRisk bundle。"""
    surface_raw = registry.call(
        "build_vol_surface",
        {
            "strategy_name": strategy_name,
            "underlying": underlying,
            "as_of_date": as_of_date,
            "write_artifact": True,
        },
    )
    surface = VolSurfaceResult.model_validate(
        {k: v for k, v in surface_raw.items() if k not in ("strategy_name", "artifact_path", "risk_free_rate")}
    )
    forward = surface_raw.get("forward_price", surface.forward_price)

    greeks_raw = registry.call(
        "calc_greeks",
        {
            "underlying": underlying,
            "as_of_date": as_of_date,
            "spot_price": forward,
            "call_quantity": 10,
            "surface_artifact_path": surface_raw.get("artifact_path"),
            "write_artifact": True,
            "strategy_name": strategy_name,
        },
    )
    greeks = GreeksProfile.model_validate(
        {
            k: v
            for k, v in greeks_raw.items()
            if k
            not in (
                "surface_interpolation",
                "surface_data_quality",
                "artifact_path",
            )
        }
    )

    backtest_raw = registry.call(
        "run_options_backtest_stub",
        {
            "strategy_name": strategy_name,
            "underlying": underlying,
            "start_date": "2026-01-01",
            "end_date": as_of_date,
        },
    )
    backtest = OptionsBacktestReport.model_validate(backtest_raw)

    options_risk = {
        "strategy_name": strategy_name,
        "underlying": underlying,
        "as_of_date": as_of_date,
        "vol_surface": surface_raw,
        "greeks_profile": greeks.model_dump(mode="json"),
        "backtest": backtest.model_dump(mode="json"),
        "surface_points": len(surface.points),
        "interpolation": surface.interpolation_method,
        "data_quality": surface.data_quality,
        "notes": "OptionsRisk bundle = VolSurface + GreeksProfile + OptionsBacktestReport",
    }
    artifact_path = _write_artifact(
        f"artifacts/options/{strategy_name}/options_risk.json",
        options_risk,
    )
    return {
        "track": "options",
        "schema": "VolSurfaceResult + GreeksProfile + OptionsBacktestReport",
        "artifact_path": artifact_path,
        "surface_artifact": surface_raw.get("artifact_path"),
        "greeks_artifact": greeks_raw.get("artifact_path"),
        "portfolio_delta": greeks.portfolio_greeks.delta,
        "backtest_sharpe": backtest.sharpe,
    }


def run_all_demos() -> dict[str, Any]:
    return {
        "strategy": run_strategy_demo(),
        "fundamental": run_fundamental_demo(),
        "options": run_options_demo(),
    }


__all__ = [
    "run_strategy_demo",
    "run_fundamental_demo",
    "run_options_demo",
    "run_all_demos",
]

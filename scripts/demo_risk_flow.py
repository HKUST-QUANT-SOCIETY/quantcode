"""Day 3 standup demo for risk:gate — normal + HumanGate interrupt/resume."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flows.risk_gate import build_workflow, resume_risk_gate
from runner.compose_executor import execute_compose_flow, register_flow, unregister_flow
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id
from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache

_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts" / "risk" / "demo"
_DEDUPE_DB = PROJECT_ROOT / ".quantcode" / "demo-dedupe.sqlite"
_CHECKPOINT_DB = PROJECT_ROOT / ".quantcode" / "demo-checkpoints.db"


def _fixture_model_spec() -> dict:
    path = PROJECT_ROOT / "tests/fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _flow_input(*, scenario: str, pr_number: str) -> dict:
    return {
        "scenario": scenario,
        "model_spec": _fixture_model_spec(),
        "pr_number": pr_number,
        "head_sha": "demo1234567890abcdef",
        "pr_url": f"https://github.com/hkust-quant-society/quantcode/pull/{pr_number}",
        "artifacts_root": str(_ARTIFACTS_ROOT / scenario),
        "dedupe_db_path": str(_DEDUPE_DB),
    }


def _banner(title: str) -> None:
    line = "═" * 60
    print(f"\n{line}")
    print(f"  {title}")
    print(line)


def _print_risk_profile(profile: dict) -> None:
    print("\n📊 RiskProfile")
    print(f"   strategy_id          : {profile['strategy_id']}")
    print(f"   as_of_date           : {profile['as_of_date']}")
    print(f"   max_drawdown         : {profile['max_drawdown']:.2%}")
    print(f"   tail_risk_var_99     : {profile['tail_risk_var_99']:.2%}")
    print(f"   position_limit       : {profile['position_limit']:.2%}")
    print(f"   correlation          : {profile['correlation_with_existing']:.2f}")


def _print_output_summary(output: dict) -> None:
    print(f"\n✅ status               : {output['status']}")
    print(f"   acceptance verdict   : {output['acceptance']['verdict']}")
    if output.get("human_decision"):
        print(f"   human_decision       : {output['human_decision']}")
    if output.get("pr_comment"):
        print(f"   comment_id           : {output['pr_comment']['comment_id']}")
        print(f"   comment artifact     : {output['pr_comment']['artifact_path']}")


def demo_normal() -> None:
    _banner("场景 1 / normal — 风险未超阈值，直接完成")

    thread_id = make_thread_id("risk", "risk:gate", suffix="demo-normal")
    app = build_workflow(checkpoint_db=_CHECKPOINT_DB)
    register_flow("risk", "risk:gate", app, overwrite=True)
    try:
        result = execute_compose_flow(
            group="risk",
            flow_name="risk:gate",
            input_data=_flow_input(scenario="normal", pr_number="101"),
            thread_id=thread_id,
        )
    finally:
        unregister_flow("risk", "risk:gate")

    output = result["output_data"]
    _print_risk_profile(output["risk_profile"])
    _print_output_summary(output)
    print("\n📁 artifacts")
    for path in result["artifacts"]:
        print(f"   • {path}")


def demo_high_risk() -> None:
    _banner("场景 2 / high_risk — VaR 超阈值 → HumanGate 人审 → approve → 完成")

    thread_id = make_thread_id("risk", "risk:gate", suffix="demo-high-risk")
    app = build_workflow(checkpoint_db=_CHECKPOINT_DB)
    config = {"configurable": {"thread_id": thread_id}}
    init_state = {
        "group": "risk",
        "flow_name": "risk:gate",
        "thread_id": thread_id,
        "input_data": _flow_input(scenario="high_risk", pr_number="202"),
        "output_data": None,
        "artifacts": [],
        "errors": [],
    }

    print("\n▶ 启动 risk:gate flow（high_risk stub）…")
    paused = app.invoke(init_state, config=config)

    interrupt_payload = paused["__interrupt__"][0].value
    _print_risk_profile(interrupt_payload["risk_profile"])

    print("\n⚠️  风控指标超阈值")
    for reason in interrupt_payload["reasons"]:
        print(f"   • {reason}")

    print(f"\n{interrupt_payload['message']}")
    print(f"   gate_id              : {interrupt_payload['gate_id']}")
    print("   等待 risk-lead 审批…")

    print("\n▶ 模拟人审 approve …")
    result = resume_risk_gate(app, thread_id, "approve")

    output = result["output_data"]
    _print_output_summary(output)
    print("\n📁 artifacts")
    for path in result["artifacts"]:
        print(f"   • {path}")

    failed_checks = [
        c["name"] for c in output["acceptance"]["checks"] if not c["passed"]
    ]
    if failed_checks:
        print("\n💡 说明：acceptance 仍记录超阈值项", failed_checks)
        print("   但人审 approve 后 flow 继续完成并写入 PR comment。")


def main() -> None:
    print("QuantCode Day 3 — risk:gate Demo")
    print("使用本地 statistics_stub，不调用 GitHub API")

    _ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
    _CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)

    try:
        demo_normal()
        demo_high_risk()
    finally:
        clear_checkpointer_cache()
        clear_write_pr_comment_dedupe_cache()

    _banner("Demo 完成")
    print("  normal    : 一次跑完，acceptance=pass")
    print("  high_risk : interrupt 暂停 → approve → resume → comment 写入 artifact")
    print()


if __name__ == "__main__":
    main()

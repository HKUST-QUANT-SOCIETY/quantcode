"""G2-A8 HumanGate 写操作收窄断言（governance SPEC §2.3/§4，F-03 v0.2 定版）。

收窄原则（2026-09-01）：**产出不 gate**（人本来要看，报告平台承接）、
**代码不 gate**（CI/PR 承接）、只有**写操作进入生产面**才 gate。

断言清单：
- (a) test_research_flow_zero_interrupts — 纯研究流（研报审阅路径，原
      request_human_review interrupt 处）全程零 ``__interrupt__``；
      组合越限路径见 test_portfolio_breach_path_zero_interrupts。
- (b) test_threshold_breach_verdict_is_fail — RiskThresholds 越限 →
      ``RiskProfile.evaluate_verdict() == "fail"``（不再 needs_human），
      且 acceptance 单源同样 verdict=fail（产出门禁内化于评估流程）。
- (c) test_write_gate_triggers_preserved — 三类写闸仍生效：
      merge（tools/factor/merge_to_main，kind=merge；E2E 回归 =
      tests/test_factor_merge.py）、跨组 ask（runner/permission_engine；
      E2E 回归 = tests/test_permission_engine.py）、预算
      （QUANTCODE_TOKEN_BUDGET 硬约束阻断；回归 = tests/test_token_budget.py）。
- (d) SSH 写生产环境触发点（kind=deploy）— 见文件尾 TODO（AG-F 落地后
      AG-I 回填 test_ssh_prod_write_gate）。
"""
from __future__ import annotations

import importlib
import pytest
from langchain_core.messages import AIMessage

from runner.acceptance import run_acceptance
from schemas.risk_profile import RiskGateVerdict, RiskProfile, RiskThresholds

BANNER = "#" * 400  # ≈100 tokens（chars/4 估算，与 test_token_budget 同款）


class ScriptedLLM:
    """按调用次数返回预设 AIMessage（与 test_agent_engine_basic 同款）。"""

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
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])


def _tool_outputs(final_state: dict) -> list[str]:
    return [str(getattr(m, "content", "")) for m in final_state.get("messages", [])]


@pytest.fixture(autouse=True)
def _checkpoint_clean():
    from runner.langgraph_base import clear_checkpointer_cache

    yield
    clear_checkpointer_cache()


# ---------------------------------------------------------------------------
# (a) 纯研究流零 interrupt
# ---------------------------------------------------------------------------


def test_research_flow_zero_interrupts(tmp_path):
    """研报研究流（render_report → request_human_review → mark_task_done）：

    原 request_human_review 在此处 LangGraph interrupt 暂停等人审；收窄后
    写 review_requested 标记直接放行 → 全程零 ``__interrupt__``，流程完成。
    """
    pytest.importorskip("langgraph")
    import tools.fundamental._register  # noqa: F401

    importlib.reload(tools.fundamental._register)
    from runner.agent_engine import AgentRunner

    llm = ScriptedLLM(
        [
            _ai(
                "render_report",
                {
                    "target_identifier": "2097.HK",
                    "target_name": "蜜雪冰城",
                    "as_of_date": "2025-01-01",
                    "fair_value_per_share": 43.47,
                    "use_typst": False,
                },
                "c1",
            ),
            _ai("request_human_review", {"reason": "研报待研究员验收"}, "c2"),
            _ai("mark_task_done", {"summary": "研报产出完成，审阅由报告平台承接"}, "c3"),
        ]
    )
    runner = AgentRunner(group="fundamental", model=llm, checkpoint_db=tmp_path / "ckpt.db")
    final = runner.run(
        task="渲染研报并挂审阅标记",
        skill_name="fundamental-compose",
        thread_id="narrowing-research-1",
        flow_name="narrowing_research",
    )

    # 全程零 human_gate interrupt
    assert "__interrupt__" not in final
    assert final.get("task_status") == "done"
    # 审阅标记存在（trace 留痕），且不是 gate payload
    outputs = _tool_outputs(final)
    assert any("review_requested" in o for o in outputs), f"missing review marker: {outputs}"
    assert not any("waiting_for_human" in o for o in outputs)


def test_portfolio_breach_path_zero_interrupts(tmp_path):
    """组合越限研究路径：check_portfolio_gate 越限 → 裁决 fail 返回，零 interrupt。"""
    pytest.importorskip("langgraph")
    from tools.registry import register_tool
    from tools.registry import registry as global_registry

    global_registry._tools.clear()
    try:
        import sys as _sys

        importlib.reload(_sys.modules.get("tools.portfolio._register")
                         or __import__("tools.portfolio._register", fromlist=["_register"]))
        register_tool(_mark_done_tool())
        from runner.agent_engine import AgentRunner

        llm = ScriptedLLM(
            [
                _ai("rebalance_plan", {"current": {}, "target": {"A": 0.5, "B": 0.5}}, "p1"),
                _ai("check_portfolio_gate", {
                    "plan": {"trades": [
                        {"asset": "A", "from_w": 0.0, "to_w": 0.5, "est_cost": 0.00015},
                        {"asset": "B", "from_w": 0.0, "to_w": 0.5, "est_cost": 0.00015},
                    ], "turnover": 1.0, "fee_total": 0.0003},
                    "thresholds": {"max_single_weight": 0.10, "max_turnover": 0.5},
                }, "p2"),
                _ai("mark_task_done", {"ok": True}, "p3"),
            ]
        )
        runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_path / "ckpt.db")
        final = runner.stream(
            task="rebalance then gate check",
            system_prompt="x",
            thread_id="narrowing-portfolio-1",
            flow_name="narrowing_portfolio",
        )
        assert "__interrupt__" not in final
        assert final.get("task_status") == "done"
        outputs = _tool_outputs(final)
        # 裁决 fail 随 tool_result 返回（不再构造 HumanGate payload）
        assert any("single_weight" in o for o in outputs), f"missing fail verdict: {outputs}"
        assert not any("waiting_for_human" in o for o in outputs)
    finally:
        global_registry._tools.clear()


# ---------------------------------------------------------------------------
# (b) 阈值越限 verdict=fail
# ---------------------------------------------------------------------------


def test_threshold_breach_verdict_is_fail():
    """RiskThresholds 越限 → evaluate_verdict()=="fail"；needs_human 语义已删除。"""
    thresholds = RiskThresholds()
    breach = RiskProfile(
        strategy_id="narrowing-breach",
        as_of_date="2026-09-01",
        max_drawdown=0.22,
        position_limit=0.10,
        correlation_with_existing=0.20,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.08,
    )
    assert "max_drawdown" in breach.breached_thresholds(thresholds)
    assert "tail_risk_var_99" in breach.breached_thresholds(thresholds)
    assert breach.evaluate_verdict(thresholds) == RiskGateVerdict.FAIL
    assert breach.evaluate_verdict(thresholds) == "fail"
    # 产出门禁语义删除的防漂移锚点：枚举不再有 needs_human / rejected
    assert not hasattr(RiskGateVerdict, "NEEDS_HUMAN")
    assert not hasattr(RiskGateVerdict, "REJECTED")

    # 未越限 → pass
    ok = RiskProfile(
        strategy_id="narrowing-ok",
        as_of_date="2026-09-01",
        max_drawdown=0.08,
        position_limit=0.10,
        correlation_with_existing=0.20,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.02,
    )
    assert ok.evaluate_verdict(thresholds) == RiskGateVerdict.PASS

    # acceptance 单源同样 fail（评估流程内化，纯判定零 interrupt）
    acc = run_acceptance("risk-gate", breach.model_dump(mode="json"))
    assert acc.verdict == "fail"


# ---------------------------------------------------------------------------
# (c) 四类写操作触发点保留（本测覆盖三类；deploy 见 (d) TODO）
# ---------------------------------------------------------------------------


def _mark_done_tool():
    from pydantic import BaseModel

    from tools.registry import ToolDef

    class Args(BaseModel):
        ok: bool = True

    def _execute(args: Args, ctx: dict) -> dict:
        return {"task_status": "done", "output_data": {"ok": args.ok}}

    return ToolDef(id="mark_task_done", description="mark task done", schema=Args, execute=_execute)


def _eligible_factor_report() -> dict:
    """过 check_factor_gate 的合格报告（阈值走 configs/acceptance.factor.yaml 单源）。"""
    return {
        "factor_name": "narrowing_factor",
        "verdict": "pass",
        "ic_metrics": {"ic_mean": 0.05, "ir": 0.8, "t_stat": 3.0},
        "turnover": {"monthly": 0.3},
        "formula": "rank(close)",
        "eval_run_id": "run-narrowing-1",
    }


def test_write_gate_triggers_preserved(tmp_path, monkeypatch):
    """merge / 跨组 ask / 预算 三类写闸仍生效（SSH deploy 见 (d) TODO）。"""
    pytest.importorskip("langgraph")

    # ── ① merge_to_main（kind=merge）：合格报告未经人审不落登记簿 ──────────
    # E2E 回归：tests/test_factor_merge.py（原样保留，波末主 Agent 统一跑）
    from tools.factor.merge_to_main import merge_to_main_impl

    blocked = merge_to_main_impl(
        "factor_narrowing",
        _eligible_factor_report(),
        index_path=tmp_path / "factors.json",  # 隔离：不写真实登记簿
    )
    assert blocked["merged"] is False
    assert blocked["stage"] == "waiting_for_human"
    assert blocked["interrupt_payload"]["kind"] == "merge"
    assert not (tmp_path / "factors.json").exists()

    approved = merge_to_main_impl(
        "factor_narrowing",
        _eligible_factor_report(),
        human_approved=True,
        index_path=tmp_path / "factors.json",
    )
    assert approved["merged"] is True
    assert (tmp_path / "factors.json").exists()

    # ── ② 跨组资源 ask（kind=permission）：未批准 → ask，批准后才 allow ────
    # E2E 回归：tests/test_permission_engine.py（原样保留）
    from runner import permission_engine

    perm_file = tmp_path / "permissions.yaml"
    perm_file.write_text(
        "permissions:\n  narrowing.secret_tool: ask\n", encoding="utf-8"
    )
    monkeypatch.setenv("QUANTCODE_PERMISSIONS_FILE", str(perm_file))
    permission_engine.reset_cache()
    try:
        ask = permission_engine.check("secret_tool", "narrowing", ctx={})
        assert ask["decision"] == "ask"
        allowed = permission_engine.check("secret_tool", "narrowing", ctx={"human_approved": True})
        assert allowed["decision"] == "allow"
    finally:
        monkeypatch.delenv("QUANTCODE_PERMISSIONS_FILE", raising=False)
        permission_engine.reset_cache()

    # ── ③ 预算（QUANTCODE_TOKEN_BUDGET）：硬约束阻断，不是"标记后放行" ──────
    # 回归：tests/test_token_budget.py。现实现经 kind=budget 的 gate 实现阻断
    # （approve=追加额度继续，reject=硬停）；按 AG-A 卡片要求断言阻断语义：
    # 超限必然 halt（绝不带着超限继续跑完），reject 后终止并留 budget_exhausted。
    from runner.agent_engine import AgentRunner

    llm = ScriptedLLM([AIMessage(content=BANNER)])
    runner = AgentRunner(
        group="model",
        model=llm,
        checkpoint_db=tmp_path / "budget.db",
        budget_tokens=1,
    )
    paused = runner.stream(
        task="hi",
        system_prompt="x",
        thread_id="narrowing-budget-1",
        flow_name="narrowing_budget",
    )
    assert paused.get("status") == "waiting_for_human", "预算超限必须阻断执行"
    interrupts = paused.get("__interrupt__") or []
    payload = getattr(interrupts[0], "value", {}) if interrupts else {}
    assert payload.get("kind") == "budget"

    resumed = runner.resume(
        thread_id="narrowing-budget-1",
        decision="reject",
        system_prompt="x",
        flow_name="narrowing_budget",
    )
    assert resumed.get("task_status") == "done"
    assert resumed.get("output_data", {}).get("budget_exhausted") is True
    assert not resumed.get("__interrupt__")


# ---------------------------------------------------------------------------
# (d) SSH 写生产环境触发点（kind=deploy）
# ---------------------------------------------------------------------------

# TODO(G2-A8d, blocked on AG-F): SSH 写生产环境 gate（普通 SSH 读/开发环境写
# 不 gate；push 自动操作不 gate）随 F-05 登录界面 + permission hook 落地后，
# 由 AG-I 回填 test_ssh_prod_write_gate 断言 kind=deploy interrupt。

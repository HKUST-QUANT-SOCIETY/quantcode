"""test_portfolio.py — portfolio 三工具（construct / rebalance / gate）测试。

覆盖：
- 等权手算（4 资产 0.25）
- 风险平价 3 资产 max/min 风险贡献 ≤ 1.5
- 奇异协方差回退 equal_weight + 注记
- 截断后 Σw = 1 守恒（max_single_weight 后处理）
- 调仓 delta 阈值 + 成本（佣金/印花税）
- 超阈值 → 裁决 fail（requires_human=False、无 interrupt payload，G2-A8 收窄）
  + AgentRunner 端到端零 interrupt 完成（ScriptedLLM）
- configs/portfolio.yaml 单源（tmp 值生效）
"""
from __future__ import annotations

import importlib
import math
from pathlib import Path

import numpy as np
import pytest
import yaml
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from schemas.portfolio import (
    PortfolioGateVerdict,
    PortfolioWeights,
    RebalancePlan,
    TargetPortfolio,
)
from tools.registry import ToolDef, register_tool
from tools.registry import registry as global_registry

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _construct(cfg: TargetPortfolio, **kw) -> PortfolioWeights:
    from tools.portfolio.construct import construct_impl

    return construct_impl(cfg, **kw)


def _cfg(**over) -> TargetPortfolio:
    return TargetPortfolio(name="test-pf", **over)


class ScriptedLLM:
    """按调用次数返回预设 AIMessage（与 test_agent_engine_basic.py 同款）。"""

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


def _ai_with_tools(calls: list[tuple[str, dict]], prefix: str = "pf") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"{prefix}-{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


RETURNS = {
    "A": [0.01, 0.02, 0.01, 0.0, -0.01, 0.02],
    "B": [0.02, 0.01, 0.03, 0.01, 0.02, 0.01],
    "C": [-0.01, 0.005, 0.01, 0.02, 0.015, 0.01],
    "D": [0.005, 0.01, 0.005, 0.01, 0.008, 0.012],
}


# ---------------------------------------------------------------------------
# construct：等权 / 风险平价 / 最小方差
# ---------------------------------------------------------------------------


def test_equal_weight_hand_computed():
    w = _construct(_cfg(method="equal_weight"), returns_by_asset={"A": RETURNS["A"], "B": RETURNS["B"],
                                                                  "C": RETURNS["C"], "D": RETURNS["D"]})
    assert w.method == "equal_weight"
    # 默认 cap 0.10 会截断 0.25 → 手算用宽松 cap 验证等权
    w2 = _construct(_cfg(method="equal_weight", max_single_weight=0.5),
                    returns_by_asset={"A": RETURNS["A"], "B": RETURNS["B"],
                                      "C": RETURNS["C"], "D": RETURNS["D"]})
    for v in w2.weights.values():
        assert math.isclose(v, 0.25, abs_tol=1e-6)
    assert math.isclose(sum(w2.weights.values()), 1.0, abs_tol=1e-9)
    assert set(w.weights) == {"A", "B", "C", "D"}


def test_risk_parity_risk_contribution_ratio():
    """3 资产风险平价：max/min 风险贡献 ≤ 1.5（cap 需放宽避免截断破坏比例）。"""
    from tools.portfolio.construct import risk_contributions

    rets = {a: RETURNS[a] for a in ("A", "B", "D")}  # 3 资产
    w = _construct(_cfg(method="risk_parity", max_single_weight=1.0), returns_by_asset=rets)
    cols = np.vstack([np.asarray(rets[a]) for a in sorted(rets)])
    cov = np.cov(cols)
    rc = risk_contributions(w.weights, cov)
    assert rc, "should return contributions"
    ratio = max(rc.values()) / min(rc.values())
    assert ratio <= 1.5, f"risk contribution ratio {ratio:.3f} > 1.5 ({rc})"


def test_min_variance_solves_and_sums_to_one():
    rets = {a: RETURNS[a] for a in ("A", "B", "C")}
    w = _construct(_cfg(method="min_variance", max_single_weight=0.9), returns_by_asset=rets)
    assert math.isclose(sum(w.weights.values()), 1.0, abs_tol=1e-6)
    assert "singular_cov_fallback_equal_weight" not in w.notes


def test_singular_cov_fallback_to_equal_weight():
    """完全相同的收益序列 → 协方差奇异 → 回退等权 + 注记。"""
    same = [0.01, 0.02, 0.03]
    w = _construct(
        _cfg(method="min_variance", max_single_weight=0.9),
        returns_by_asset={"A": same, "B": list(same), "C": list(same)},
    )
    assert "singular_cov_fallback_equal_weight" in w.notes
    for v in w.weights.values():
        assert math.isclose(v, 1 / 3, abs_tol=1e-6)


def test_cap_redistribution_conserves_sum():
    """6 资产等权 0.1667，cap 0.12 → 全体触顶，Σ=0.72 ≤ gross 1.0（不虚构余量）。

    守恒（Σw=1）在「有未触顶资产可接收余量」时成立：min_variance 3 资产、
    cap 0.40 —— 最优解把权重集中到低方差的 B/D，超 cap 者截到 0.40，余量
    按比例重分给未触顶者，Σw 仍 =1。
    """
    six = {"A": RETURNS["A"], "B": RETURNS["B"], "C": RETURNS["C"], "D": RETURNS["D"],
           "E": [0.01, -0.005, 0.02, 0.01, 0.015, 0.005],
           "F": [0.012, 0.008, -0.01, 0.02, 0.01, 0.004]}
    w = _construct(_cfg(method="equal_weight", max_single_weight=0.12), returns_by_asset=six)
    total = sum(w.weights.values())
    assert math.isclose(total, 0.72, abs_tol=1e-6)
    assert all(v <= 0.12 + 1e-9 for v in w.weights.values())

    three = {"A": RETURNS["A"], "B": RETURNS["B"], "C": RETURNS["C"]}
    # cap 0.34 < 未截断最优 0.3846 → B 截到 0.34，余量按 headroom 重分给 A/C，Σw 仍=1
    w3 = _construct(_cfg(method="min_variance", max_single_weight=0.34), returns_by_asset=three)
    assert math.isclose(sum(w3.weights.values()), 1.0, abs_tol=1e-6)
    assert max(w3.weights.values()) <= 0.34 + 1e-9
    assert math.isclose(w3.weights["B"], 0.34, abs_tol=1e-9)  # 最高占比资产贴 cap
    # 未截断时 A(0.2923) < C(0.3231)，headroom 重分保持 A<C 顺序但两者都抬升
    assert w3.weights["A"] > 0.2923 and w3.weights["C"] > 0.3231
    assert w3.notes == []  # 未走等权回退，是正常的截断重分


def test_cap_all_capped_gross_respected():
    """2 资产 cap 0.10 → 每顶 0.10，Σ=0.2 ≤ 1.0（不做强行守恒到 1）。"""
    w = _construct(_cfg(max_single_weight=0.10), returns_by_asset={"A": RETURNS["A"], "B": RETURNS["B"]})
    assert math.isclose(w.weights["A"], 0.10, abs_tol=1e-9)
    assert math.isclose(sum(w.weights.values()), 0.20, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# rebalance：delta 阈值 + 成本
# ---------------------------------------------------------------------------


def test_rebalance_delta_threshold_and_costs():
    """A: |0.01| < 0.05/4=0.0125 → 不动；B: 0.1 买入；C: 0.1 卖出（含印花税）。"""
    from tools.portfolio.rebalance import rebalance_plan_impl

    plan = rebalance_plan_impl(
        {"A": 0.24, "B": 0.3, "C": 0.3, "D": 0.16},
        {"A": 0.25, "B": 0.4, "C": 0.2, "D": 0.15},
        rebalance_min_turnover=0.05,
    )
    names = {t["asset"] for t in plan.trades}
    assert "A" not in names, "A 的 delta 低于阈值不应交易"
    by = {t["asset"]: t for t in plan.trades}
    b, c = by["B"], by["C"]
    assert b["side"] == "buy"
    assert math.isclose(b["est_cost"], 0.10 * 0.0003, abs_tol=1e-10)
    assert c["side"] == "sell"
    assert math.isclose(c["est_cost"], 0.10 * (0.0003 + 0.0005), abs_tol=1e-10)
    assert math.isclose(plan.turnover, 0.20, abs_tol=1e-9)  # D 的 0.01 低于阈值不动
    assert isinstance(plan, RebalancePlan)


def test_rebalance_plan_as_dict_via_tool():
    # 全量 pytest 时其他文件会清空全局 registry（clean_registry 语义），
    # import 已被缓存 → 显式 reload 重新注册（幂等覆盖，与 test_agent_engine_basic 同防御）。
    import sys as _sys

    importlib.reload(_sys.modules.get("tools.portfolio._register")
                     or __import__("tools.portfolio._register", fromlist=["_register"]))

    out = global_registry.call(
        "rebalance_plan",
        {"current": {"A": 0.5}, "target": {"A": 0.0}},
        ctx={},
    )
    assert out["turnover"] == pytest.approx(0.5)
    assert out["trades"][0]["side"] == "sell"


# ---------------------------------------------------------------------------
# gate：阈值 / 回撤代理 / 收窄语义（verdict fail，无 interrupt payload）
# ---------------------------------------------------------------------------


def test_gate_passthrough_when_within_thresholds():
    from tools.portfolio.gate import check_portfolio_gate_impl
    from tools.portfolio.rebalance import rebalance_plan_impl

    plan = rebalance_plan_impl({}, {"A": 0.05, "B": 0.05})
    v = check_portfolio_gate_impl(plan, thresholds={"max_single_weight": 0.10, "max_turnover": 0.5})
    assert isinstance(v, PortfolioGateVerdict)
    assert v.breached == []
    assert v.requires_human is False
    assert v.interrupt_payload is None


def test_gate_breach_verdict_fail_without_interrupt_payload():
    """G2-A8 收窄：越限 = 裁决 fail（breached/reasons 承载），不再构造 HumanGate payload。"""
    from tools.portfolio.gate import check_portfolio_gate_impl
    from tools.portfolio.rebalance import rebalance_plan_impl

    plan = rebalance_plan_impl({}, {"A": 0.5})
    v = check_portfolio_gate_impl(
        plan, thresholds={"max_single_weight": 0.10, "max_turnover": 0.4}, thread_id="t-gate-1"
    )
    assert v.requires_human is False
    assert v.interrupt_payload is None
    assert set(v.breached) == {"single_weight", "turnover"}
    assert len(v.reasons) == len(v.breached)
    assert all("max_single_weight" in r or "max_turnover" in r for r in v.reasons)


def test_gate_drawdown_proxy():
    from tools.portfolio.gate import check_portfolio_gate_impl, max_drawdown_proxy_impl
    from tools.portfolio.rebalance import rebalance_plan_impl

    assert max_drawdown_proxy_impl([1.0, 1.2, 0.9, 1.1]) == pytest.approx(0.25)
    plan = rebalance_plan_impl({}, {"A": 0.05})
    v = check_portfolio_gate_impl(plan, thresholds={"max_drawdown_proxy": 0.20}, equity_curve=[1.0, 1.2, 0.9])
    assert "drawdown_proxy" in v.breached
    v2 = check_portfolio_gate_impl(plan, thresholds={"max_drawdown_proxy": 0.20}, equity_curve=[1.0, 1.1])
    assert "drawdown_proxy" not in v2.breached


# ---------------------------------------------------------------------------
# 集成：ScriptedLLM Agent 跑 portfolio 工具，超阈 → 裁决 fail、零 interrupt 完成
# ---------------------------------------------------------------------------


class _MarkDoneArgs(BaseModel):
    ok: bool = True


def _mark_done(args: _MarkDoneArgs, ctx: dict) -> dict:
    return {"task_status": "done", "output_data": {"ok": args.ok}}


@pytest.fixture
def clean_registry():
    global_registry._tools.clear()
    yield global_registry
    global_registry._tools.clear()


def _gate_mark_done_tool() -> ToolDef:
    """mark_task_done 工具（同名则与 _extract_state_fields 的 task_status 映射对齐）。"""
    return ToolDef(
        id="mark_task_done",
        description="mark task done",
        schema=_MarkDoneArgs,
        execute=_mark_done,
    )


@pytest.fixture
def tmp_db(tmp_path):
    from runner.langgraph_base import clear_checkpointer_cache

    db = tmp_path / "portfolio-checkpoints.db"
    yield db
    clear_checkpointer_cache()


def test_runagent_portfolio_gate_breach_zero_interrupts(tmp_db, clean_registry):
    """G2-A8 收窄 E2E：LLM 调 construct_portfolio → rebalance_plan → check_portfolio_gate，
    gate 超阈 → 裁决 fail 随 tool_result 返回，全程零 __interrupt__，流程正常完成。"""
    pytest.importorskip("langgraph")
    register_tool(_gate_mark_done_tool())
    # clean_registry 清空了全局 registry；模块 import 已被缓存（副作用不再触发），
    # 必须显式 reload 让三 portfolio 工具重新注册（与 test_allowlist_consistency 同防御）。
    import sys as _sys

    importlib.reload(_sys.modules["tools.portfolio._register"])

    # 手工算好的超阈 target：单权重 0.5 > 0.10，换手 1.0 > 0.5
    llm = ScriptedLLM(
        [
            _ai_with_tools(
                [
                    ("construct_portfolio", {
                        "name": "agent-pf",
                        "method": "equal_weight",
                        "returns_by_asset": {"A": [0.01, 0.02], "B": [0.02, 0.01]},
                    }),
                ],
                "s1",
            ),
            _ai_with_tools(
                [("rebalance_plan", {"current": {}, "target": {"A": 0.5, "B": 0.5}})],
                "s2",
            ),
            _ai_with_tools(
                [("check_portfolio_gate", {
                    "plan": {"trades": [
                        {"asset": "A", "from_w": 0.0, "to_w": 0.5, "est_cost": 0.00015},
                        {"asset": "B", "from_w": 0.0, "to_w": 0.5, "est_cost": 0.00015},
                    ], "turnover": 1.0, "fee_total": 0.0003},
                    "thresholds": {"max_single_weight": 0.10, "max_turnover": 0.5},
                })],
                "s3",
            ),
            # 无需任何 resume：裁决 fail 后直接收尾（状态变化避免 fingerprint 误判 loop）
            _ai_with_tools([("mark_task_done", {"ok": True})], "s4"),
        ]
    )
    from runner.agent_engine import AgentRunner

    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db, max_iterations=20)
    final = runner.stream(
        task="Construct a portfolio and rebalance, then gate check",
        system_prompt="x",
        thread_id="portfolio-gate-e2e-1",
        flow_name="portfolio_e2e",
    )
    # 收窄语义：零 interrupt、不停在 waiting_for_human、流程完成
    assert "__interrupt__" not in final, (
        f"组合越限不应再触发 interrupt；got {final.get('__interrupt__')}"
    )
    assert final.get("status") != "waiting_for_human"
    assert final.get("task_status") == "done"
    # 裁决 fail 随 tool_result 返回（breached / requires_human=False 可见）
    tool_outputs = [str(getattr(m, "content", "")) for m in final["messages"]]
    assert any("single_weight" in output for output in tool_outputs), (
        f"expected breached verdict in tool outputs; trace={final.get('execution_trace')}"
    )
    assert any("requires_human" in output and "False" in output for output in tool_outputs)


# ---------------------------------------------------------------------------
# configs/portfolio.yaml 单源（tmp 值生效）
# ---------------------------------------------------------------------------


def test_config_yaml_single_source(tmp_path, monkeypatch):
    """QUANTCODE_CONFIG_DIR 指向 tmp configs；改 portfolio.yaml 值 → rebalance/gate 行为随之变。"""
    import shutil
    from pathlib import Path

    import tools.portfolio.gate as gate_mod
    import tools.portfolio.rebalance as reb_mod
    from runner.config_loader import load_yaml, PROJECT_ROOT

    repo_yaml = PROJECT_ROOT / "configs" / "portfolio.yaml"
    data = yaml.safe_load(repo_yaml.read_text(encoding="utf-8"))
    # 单源校验：repo 配置与 schema/代码默认一致
    assert data["max_single_weight"] == 0.10
    assert data["commission"] == 0.0003
    assert data["stamp_tax"] == 0.0005
    assert data["rebalance_min_turnover"] == 0.05

    # copy + 修改 commission/stamp_tax → tmp 生效
    cfgs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", cfgs)
    (cfgs / "portfolio.yaml").write_text(yaml.dump({**data, "commission": 0.001, "stamp_tax": 0.0}))

    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(cfgs))
    load_yaml.cache_clear()
    try:
        importlib.reload(reb_mod)
        importlib.reload(gate_mod)
        pf = reb_mod.rebalance_plan_impl({}, {"A": 0.1})
        # commission 覆盖生效：成本 = 0.1 * 0.001（stamp=0，买入）
        assert pf.trades[0]["est_cost"] == pytest.approx(0.1 * 0.001)
        # gate 默认阈值经 load_yaml 从同源 yaml 读（改 tmp 值生效）
        monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(cfgs))
        (cfgs / "portfolio.yaml").write_text(yaml.dump({**data, "max_turnover_gate": 0.01}))
        load_yaml.cache_clear()
        importlib.reload(gate_mod)
        plan = reb_mod.rebalance_plan_impl({}, {"A": 0.5}, rebalance_min_turnover=0.0)
        v = gate_mod.check_portfolio_gate_impl(plan)
        assert "turnover" in v.breached
        assert v.thresholds["max_turnover"] == pytest.approx(0.01)
    finally:
        load_yaml.cache_clear()
        monkeypatch.delenv("QUANTCODE_CONFIG_DIR", raising=False)
        importlib.reload(reb_mod)
        importlib.reload(gate_mod)
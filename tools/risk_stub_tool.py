"""calc_risk_stub tool — 提供 normal/high_risk 两种风控场景数据。"""
from __future__ import annotations

from tools.registry import ToolDef
from tools.risk_stub import CalcRiskStubArgs, calc_risk_stub


def _calc_risk_stub_execute(args: CalcRiskStubArgs, ctx: dict) -> dict:
    """执行 calc_risk_stub 并自动注入 risk_profile 到 state（测试场景支持）。

    这样测试中 calc_risk_stub(high_risk) 可以直接触发 HumanGate，
    无需手动调用 generate_risk_profile 工具。
    """
    result = calc_risk_stub(args.scenario)

    # 自动注入 risk_profile 到 ctx（如果存在）
    # 测试场景：ctx 会传入 state 引用，允许工具修改 state
    # 生产场景：真正的 generate_risk_profile 工具会覆盖此值
    if ctx and "risk_profile" not in ctx:
        # 构造一个简单的 risk_profile（包含 risk_metrics 的关键字段）
        ctx["risk_profile"] = {
            "strategy_id": result.get("strategy_id"),
            "as_of_date": result.get("as_of_date"),
            "max_drawdown": result.get("max_drawdown"),
            "tail_risk_var_99": result.get("tail_risk_var_99"),
            "scenario": args.scenario,
        }

    return result


calc_risk_stub_tool = ToolDef(
    id="calc_risk_stub",
    description=(
        "Compute risk metrics for a given scenario. "
        "Returns {tail_risk_var_99, max_drawdown, volatility, position_limit, "
        "correlation_with_existing, var_99_trend, max_drawdown_trend, thresholds}. "
        "Use 'normal' to get safe metrics, 'high_risk' to get metrics that exceed thresholds."
    ),
    schema=CalcRiskStubArgs,
    execute=_calc_risk_stub_execute,
)

__all__ = ["calc_risk_stub_tool"]

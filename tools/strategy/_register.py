"""注册 strategy 组全部 tool — Day 4 刘炽。"""
from __future__ import annotations

from tools.registry import register_tool
from tools.strategy.combine_signals import combine_signals_tool
from tools.strategy.deploy_strategy import deploy_strategy_tool
from tools.strategy.run_strategy_backtest import run_strategy_backtest_tool
from tools.strategy.select_signals import select_signals_tool

register_tool(select_signals_tool)
register_tool(combine_signals_tool)
register_tool(run_strategy_backtest_tool)
register_tool(deploy_strategy_tool)

__all__ = [
    "select_signals_tool",
    "combine_signals_tool",
    "run_strategy_backtest_tool",
    "deploy_strategy_tool",
]

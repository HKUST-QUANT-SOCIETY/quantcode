"""注册 options 组全部 tool。"""
from __future__ import annotations

from tools.options.build_vol_surface import build_vol_surface_tool
from tools.options.calc_greeks import calc_greeks_tool
from tools.options.run_options_backtest_stub import run_options_backtest_stub_tool
from tools.registry import register_tool

register_tool(build_vol_surface_tool)
register_tool(calc_greeks_tool)
register_tool(run_options_backtest_stub_tool)

__all__ = [
    "build_vol_surface_tool",
    "calc_greeks_tool",
    "run_options_backtest_stub_tool",
]

"""factor group tool 注册 — Day 4 尹一帆。

import 即触发 3 个 ToolDef 注册到全局 registry(与 tools/risk/_register.py / tools/options/_register.py 风格一致)。

调用方:
- quantcode/quantcode/mcp_server.py(MCP 暴露 factor tool)
- 测试 / 任何想跑 AgentRunner(group="factor") 的代码

字段契约见 docs/Day4/factor_tool_schema_proposal.md,后续 Lead 接真 LLM 时
只替换各 stub 的 _execute 函数体,本文件不动。
"""
from __future__ import annotations

from tools.registry import register_tool

# 触发 3 个 ToolDef 注册
from tools.factor.match_main_stub import match_main_tool  # noqa: F401
from tools.factor.gen_schema_stub import gen_schema_tool  # noqa: F401
from tools.factor.autoeval_stub import autoeval_tool  # noqa: F401

register_tool(match_main_tool)
register_tool(gen_schema_tool)
register_tool(autoeval_tool)


__all__ = ["match_main_tool", "gen_schema_tool", "autoeval_tool"]

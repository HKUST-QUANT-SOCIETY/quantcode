"""factor group tool 注册 — Day 4 尹一帆，Day 5 Lead 真LLM实现。

import 即触发 3 个 ToolDef 注册到全局 registry(与 tools/risk/_register.py / tools/options/_register.py 风格一致)。

Day 5 切换逻辑：
- 环境变量 QUANTCODE_FACTOR_USE_REAL_LLM=1 时使用真LLM实现
- 否则使用stub（默认，保持Day 4向后兼容）

调用方:
- quantcode/quantcode/mcp_server.py(MCP 暴露 factor tool)
- 测试 / 任何想跑 AgentRunner(group="factor") 的代码

字段契约见 docs/Day4/factor_tool_schema_proposal.md,后续 Lead 接真 LLM 时
只替换各 stub 的 _execute 函数体,本文件不动。
"""
from __future__ import annotations

import os

from tools.registry import register_tool

# Day 5: 切换真LLM或stub
USE_REAL_LLM = os.environ.get("QUANTCODE_FACTOR_USE_REAL_LLM", "0") == "1"

if USE_REAL_LLM:
    from tools.factor.match_main import match_main_tool
    from tools.factor.gen_schema_stub import gen_schema_tool  # gen_schema 暂时还是stub
    from tools.factor.autoeval_stub import autoeval_tool  # autoeval 暂时还是stub
else:
    # 触发 3 个 ToolDef 注册（stub版本）
    from tools.factor.match_main_stub import match_main_tool  # noqa: F401
    from tools.factor.gen_schema_stub import gen_schema_tool  # noqa: F401
    from tools.factor.autoeval_stub import autoeval_tool  # noqa: F401

register_tool(match_main_tool)
register_tool(gen_schema_tool)
register_tool(autoeval_tool)


__all__ = ["match_main_tool", "gen_schema_tool", "autoeval_tool"]

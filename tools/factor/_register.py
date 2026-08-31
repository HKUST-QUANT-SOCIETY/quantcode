"""factor group tool 注册 — Day 4 尹一帆，Day 5 Lead 真LLM实现。

import 即触发 4 个 ToolDef 注册到全局 registry(与 tools/risk/_register.py 风格一致)。

恒注册真版实现（无 stub/双开关）：
- match_main / gen_schema: 真 LLM 实现，API 不可用时自动降级（见各模块 _execute）
- autoeval: 真 AutoEval API 实现，未配置/失败时降级返回 mock（_is_mock 标记）
- eval_from_panel: 真实数据评估（FactorPanel 契约 → 真实 IC/换手/分层），
  配 panel 数据时优先于 autoeval

调用方:
- quantcode/quantcode/mcp_server.py(MCP 暴露 factor tool)
- 测试 / 任何想跑 AgentRunner(group="factor") 的代码
"""
from __future__ import annotations

from tools.factor.autoeval import autoeval_tool
from tools.factor.eval_from_panel import eval_from_panel_tool
from tools.factor.gen_schema import gen_schema_tool
from tools.factor.match_main import match_main_tool
from tools.registry import register_tool

register_tool(match_main_tool)
register_tool(gen_schema_tool)
register_tool(autoeval_tool)
register_tool(eval_from_panel_tool)


__all__ = ["match_main_tool", "gen_schema_tool", "autoeval_tool", "eval_from_panel_tool"]

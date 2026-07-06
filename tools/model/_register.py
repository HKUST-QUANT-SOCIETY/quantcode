"""注册 model 组全部 tool —— Day 3 尹一帆。

调用 ``import tools.model._register`` 即可把 5 个 tool 注册到全局 registry。
"""
from __future__ import annotations

from tools.model.extract_metadata import extract_metadata_tool
from tools.model.generate_model_spec import generate_model_spec_tool
from tools.model.read_pr import read_pr_tool
from tools.model.trigger_risk_flow import trigger_risk_flow_tool
from tools.model.write_blackboard import write_blackboard_tool
from tools.registry import register_tool

register_tool(read_pr_tool)
register_tool(extract_metadata_tool)
register_tool(generate_model_spec_tool)
register_tool(write_blackboard_tool)
register_tool(trigger_risk_flow_tool)

__all__ = [
    "read_pr_tool",
    "extract_metadata_tool",
    "generate_model_spec_tool",
    "write_blackboard_tool",
    "trigger_risk_flow_tool",
]
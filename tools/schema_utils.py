"""Pydantic schema → JSON Schema 工具函数 — Day 4 尹一帆。

从 ``quantcode/mcp_server.py`` 提取，供 MCP server 和 LLM provider 共用，
避免循环依赖。

用法::

    from tools.schema_utils import pydantic_to_json_schema, tool_def_to_openai_function

    # MCP 用
    mcp_tool = tool_def_to_mcp(tool_def)

    # OpenAI function calling 用
    openai_func = tool_def_to_openai_function(tool_def)
"""
from __future__ import annotations

from tools.registry import ToolDef


def pydantic_to_json_schema(schema: type) -> dict:
    """把 Pydantic BaseModel 转成 JSON Schema dict。

    Pydantic v2 的 ``model_json_schema()`` 直接输出 JSON Schema 草案，
    与 MCP / OpenAI function calling 兼容。
    """
    return schema.model_json_schema()


def tool_def_to_openai_function(tool: ToolDef) -> dict:
    """把 ToolDef 转成 OpenAI function calling 格式。

    返回::

        {
            "type": "function",
            "function": {
                "name": "tool_id",
                "description": "tool description",
                "parameters": {...}  # JSON Schema
            }
        }
    """
    return {
        "type": "function",
        "function": {
            "name": tool.id,
            "description": tool.description,
            "parameters": pydantic_to_json_schema(tool.schema),
        },
    }


__all__ = ["pydantic_to_json_schema", "tool_def_to_openai_function"]
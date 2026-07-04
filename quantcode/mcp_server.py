"""QuantCode MCP server — Day 3 尹一帆。

把 QuantCode 的 tool 注册表 + AgentRunner 通过 Model Context Protocol (MCP)
暴露给 OpenCode / 其他 MCP 客户端。

MCP 协议要点（基于 Anthropic MCP spec）：
- stdio 传输：服务端从 stdin 读 JSON-RPC 请求，往 stdout 写响应
- 客户端通过 ``initialize`` / ``tools/list`` / ``tools/call`` 三个 method 与服务端交互
- 每个 tool 必须声明 ``name`` / ``description`` / ``inputSchema``（JSON Schema）

启动方式::

    python -m quantcode.mcp_server

OpenCode 配置（``opencode.jsonc`` 的 ``mcp`` 段）::

    "mcp": {
        "quantcode": {
            "type": "local",
            "command": ["uv", "run", "python", "-m", "quantcode.mcp_server"],
            "enabled": true
        }
    }

参考：
- MCP 协议：https://modelcontextprotocol.io/
- 本仓库规划：``docs/Architecture_Spec.md`` §2 控制平面
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 让 ``python -m quantcode.mcp_server`` 也能找到 tools / runner
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.registry import registry, ToolDef
from tools.model._register import (  # noqa: F401  触发 model tool 注册
    read_pr_tool,
    extract_metadata_tool,
    generate_model_spec_tool,
    write_blackboard_tool,
    trigger_risk_flow_tool,
)


# ---------------------------------------------------------------------------
# Pydantic schema → JSON Schema
# ---------------------------------------------------------------------------


def pydantic_to_json_schema(schema: type) -> dict:
    """把 Pydantic BaseModel 转成 JSON Schema dict（用于 MCP inputSchema）。

    Pydantic v2 的 ``model_json_schema()`` 直接输出 JSON Schema 草案，
    与 MCP 兼容。
    """
    return schema.model_json_schema()


def tool_def_to_mcp(tool: ToolDef) -> dict:
    """把 ToolDef 转成 MCP tool 声明格式。"""
    return {
        "name": tool.id,
        "description": tool.description,
        "inputSchema": pydantic_to_json_schema(tool.schema),
    }


# ---------------------------------------------------------------------------
# 简单的 MCP stdio server（手写 JSON-RPC，避免引 mcp.server 复杂依赖）
# ---------------------------------------------------------------------------


def list_tools() -> dict:
    """实现 MCP 的 ``tools/list``：返回所有已注册 tool。"""
    return {
        "tools": [tool_def_to_mcp(t) for t in registry.list_all()],
    }


def call_tool(name: str, arguments: dict) -> dict:
    """实现 MCP 的 ``tools/call``：执行 tool 并返回结果。

    返回 MCP 规定的格式::

        {
            "content": [{"type": "text", "text": "..."}],
            "isError": False
        }
    """
    try:
        result = registry.call(name, arguments, ctx={"source": "mcp"})
        text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error: {type(e).__name__}: {e}"}],
            "isError": True,
        }


def handle_request(req: dict) -> dict:
    """处理一条 JSON-RPC 请求，返回响应 dict。"""
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "quantcode-mcp", "version": "0.1.0"},
            },
        }
    elif method == "notifications/initialized":
        # 客户端通知，无需响应
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": list_tools(),
        }
    elif method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": call_tool(name, arguments),
        }
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def serve_stdio() -> None:
    """从 stdin 读 JSON-RPC 请求，往 stdout 写响应。

    协议：每行一条 JSON。响应可选（notifications 无 id 时不写）。
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Invalid JSON: {e}\n")
            continue
        try:
            resp = handle_request(req)
        except Exception as e:
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main() -> None:
    """入口：serve_stdio。"""
    serve_stdio()


if __name__ == "__main__":
    main()
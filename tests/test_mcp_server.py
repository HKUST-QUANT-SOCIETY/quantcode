"""MCP server 单测 — Day 3 尹一帆。"""
from __future__ import annotations

import importlib
import json

import pytest

from quantcode import mcp_server
from tools.registry import registry as global_registry
import tools.model._register  # noqa: F401  注册 model 5 个 tool


@pytest.fixture(autouse=True)
def _clean_registry():
    """清空 + 重新注册 model tools。"""
    global_registry._tools.clear()
    importlib.reload(tools.model._register)
    yield
    global_registry._tools.clear()


# ---------------------------------------------------------------------------
# pydantic_to_json_schema
# ---------------------------------------------------------------------------


def test_pydantic_to_json_schema_basic():
    from pydantic import BaseModel

    class Args(BaseModel):
        x: int
        y: str

    schema = mcp_server.pydantic_to_json_schema(Args)
    assert "properties" in schema
    assert "x" in schema["properties"]
    assert "y" in schema["properties"]


def test_pydantic_to_json_schema_with_optional_field():
    from typing import Optional
    from pydantic import BaseModel

    class Args(BaseModel):
        x: int
        y: Optional[str] = None

    schema = mcp_server.pydantic_to_json_schema(Args)
    assert "x" in schema["properties"]
    assert "y" in schema["properties"]


# ---------------------------------------------------------------------------
# tool_def_to_mcp
# ---------------------------------------------------------------------------


def test_tool_def_to_mcp_shape():
    from pydantic import BaseModel

    class Args(BaseModel):
        x: int

    from tools.registry import ToolDef

    tool = ToolDef(
        id="my_tool",
        description="A test tool",
        schema=Args,
        execute=lambda args, ctx: "ok",
    )
    mcp = mcp_server.tool_def_to_mcp(tool)
    assert mcp["name"] == "my_tool"
    assert mcp["description"] == "A test tool"
    assert "inputSchema" in mcp
    assert "properties" in mcp["inputSchema"]


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


def test_list_tools_returns_all_registered():
    result = mcp_server.list_tools()
    assert "tools" in result
    tool_names = {t["name"] for t in result["tools"]}
    # 5 个 model tool 都应该出现
    assert "read_pr" in tool_names
    assert "extract_metadata" in tool_names
    assert "generate_model_spec" in tool_names
    assert "write_blackboard" in tool_names
    assert "trigger_risk_flow" in tool_names


def test_list_tools_empty_registry(tmp_path):
    """测试 list_tools 在空 registry 下返回空列表。"""
    global_registry._tools.clear()
    result = mcp_server.list_tools()
    assert result == {"tools": []}


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------


def test_call_tool_success():
    result = mcp_server.call_tool("read_pr", {"pr_number": 42})
    assert result["isError"] is False
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert "42" in result["content"][0]["text"]


def test_call_tool_unknown_tool():
    result = mcp_server.call_tool("nonexistent_tool", {})
    assert result["isError"] is True
    assert "nonexistent_tool" in result["content"][0]["text"]


def test_call_tool_invalid_args():
    result = mcp_server.call_tool("read_pr", {"pr_number": "not an int"})
    assert result["isError"] is True
    assert "Invalid arguments" in result["content"][0]["text"] or "failed" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# handle_request
# ---------------------------------------------------------------------------


def test_handle_initialize():
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    resp = mcp_server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "protocolVersion" in resp["result"]
    assert resp["result"]["serverInfo"]["name"] == "quantcode-mcp"


def test_handle_tools_list():
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    resp = mcp_server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 2
    assert "tools" in resp["result"]
    assert len(resp["result"]["tools"]) >= 5


def test_handle_tools_call():
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "read_pr", "arguments": {"pr_number": 99}},
    }
    resp = mcp_server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 3
    result = resp["result"]
    assert result["isError"] is False
    assert "99" in result["content"][0]["text"]


def test_handle_ping():
    req = {"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {}}
    resp = mcp_server.handle_request(req)
    assert resp["result"] == {}


def test_handle_unknown_method():
    req = {"jsonrpc": "2.0", "id": 5, "method": "unknown/method", "params": {}}
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_handle_notifications_initialized_returns_none():
    """notifications/initialized 不需要响应 → handle_request 返回 None。"""
    req = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    resp = mcp_server.handle_request(req)
    assert resp is None
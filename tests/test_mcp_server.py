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


def test_list_tools_filters_by_quantcode_group(monkeypatch):
    """Day 3 评审修复（🟢#6）：设置 ``QUANTCODE_GROUP`` 后只返回 allowlist 内的 tool。

    验证：
    1. 设置 ``QUANTCODE_GROUP=model`` 时，仅返回 ``.opencode/groups/model/tool_allowlist.yaml`` 中的 tool
    2. 未设置环境变量时保持原行为（全量）
    """
    # Case 1: 设置 QUANTCODE_GROUP=model
    monkeypatch.setenv("QUANTCODE_GROUP", "model")
    # 因为 _MCP_GROUP 在模块导入时就计算了，重新 import 让新值生效
    importlib.reload(mcp_server)
    importlib.reload(tools.model._register)  # 重新注册 model 5 个 tool
    result = mcp_server.list_tools()
    tool_names = {t["name"] for t in result["tools"]}
    # model allowlist 里有
    assert "read_pr" in tool_names
    assert "extract_metadata" in tool_names
    # model allowlist 里没有的 tool（不在 yaml 里）应被过滤掉
    # 例如 'fetch_url' 是其他组的
    assert tool_names == tool_names & {
        "read_pr",
        "extract_metadata",
        "generate_model_spec",
        "write_blackboard",
        "trigger_risk_flow",
        "search_memory",
        "read_file",
        "write_file",
        "bash",
    }, f"未预期的 tool 出现了: {tool_names - {'read_pr','extract_metadata','generate_model_spec','write_blackboard','trigger_risk_flow','search_memory','read_file','write_file','bash'}}"

    # Case 2: 不设置 → 全部
    monkeypatch.delenv("QUANTCODE_GROUP", raising=False)
    importlib.reload(mcp_server)
    importlib.reload(tools.model._register)
    result = mcp_server.list_tools()
    assert "read_pr" in {t["name"] for t in result["tools"]}


def test_list_tools_excludes_non_model_tools_when_quantcode_group_is_model(monkeypatch):
    """🟢#6 负向断言（Day 3 评审修复）：当 QUANTCODE_GROUP=model 时，非 model 组的
    tool **必须**被过滤掉。

    之前的测试只正向断言 model 工具**存在**。本次注册一个"factor 组"专属的 mock
    tool，断言它在 QUANTCODE_GROUP=model 下不出现；不设环境变量时**出现**（兜底
    原行为）。
    """
    from pydantic import BaseModel

    class FactorOnlyArgs(BaseModel):
        x: int

    from tools.registry import ToolDef

    def _factor_exec(args: FactorOnlyArgs, ctx: dict) -> str:
        return f"factor-only:{args.x}"

    global_registry.register(ToolDef(
        id="factor_only_tool",
        description="Fake factor-group tool (never in model allowlist)",
        schema=FactorOnlyArgs,
        execute=_factor_exec,
    ))
    try:
        monkeypatch.setenv("QUANTCODE_GROUP", "model")
        importlib.reload(mcp_server)
        importlib.reload(tools.model._register)
        tool_names = {t["name"] for t in mcp_server.list_tools()["tools"]}
        # model group 工具都在
        assert "read_pr" in tool_names
        # factor 组工具被排除
        assert "factor_only_tool" not in tool_names, (
            f"factor 工具泄漏到 model 组下：{tool_names}"
        )

        # 兜底：不设环境变量时，所有工具（包括 factor_only_tool）都应可见
        monkeypatch.delenv("QUANTCODE_GROUP", raising=False)
        importlib.reload(mcp_server)
        importlib.reload(tools.model._register)
        all_names = {t["name"] for t in mcp_server.list_tools()["tools"]}
        assert "factor_only_tool" in all_names
    finally:
        global_registry._tools.pop("factor_only_tool", None)


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------


def test_call_tool_success():
    result = mcp_server.call_tool("read_pr", {"pr_path": "tests/fixtures/sample_model_pr/README.md"})
    assert result["isError"] is False
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert "ModelSpec" in result["content"][0]["text"]


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
        "params": {
            "name": "read_pr",
            "arguments": {"pr_path": "tests/fixtures/sample_model_pr/README.md"},
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 3
    result = resp["result"]
    assert result["isError"] is False
    assert "ModelSpec" in result["content"][0]["text"]


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
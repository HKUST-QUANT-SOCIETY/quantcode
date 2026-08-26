"""Tests for risk tool registry and MCP exposure."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from quantcode import mcp_server
from tools.registry import registry as global_registry


@pytest.fixture(autouse=True)
def _reload_risk_tools():
    """与 test_mcp_server 一致：清空后重载 model + risk 注册。"""
    global_registry._tools.clear()
    importlib.reload(__import__("tools.model._register", fromlist=["*"]))
    importlib.reload(__import__("tools.risk._register", fromlist=["*"]))
    importlib.reload(mcp_server)
    yield
    global_registry._tools.clear()


def test_risk_tools_registered():
    ids = global_registry.list_ids()
    for tool_id in (
        "read_blackboard",
        "calc_risk",
        "generate_risk_profile",
        "check_gate",
        "write_pr_comment",
    ):
        assert tool_id in ids


def test_risk_allowlist_filters_tools(monkeypatch):
    monkeypatch.setenv("QUANTCODE_GROUP", "risk")
    importlib.reload(mcp_server)
    tools = mcp_server.list_tools()["tools"]
    names = {t["name"] for t in tools}
    assert names == {"spawn_risk_scout"}


def test_registry_call_read_blackboard():
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    model_spec = json.loads(path.read_text(encoding="utf-8"))
    result = global_registry.call("read_blackboard", {"input_data": {"model_spec": model_spec}})
    assert result["model_spec"]["model_name"] == "pb_roe_ranker"


def test_registry_call_check_gate_high_risk():
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    model_spec = json.loads(path.read_text(encoding="utf-8"))
    metrics = global_registry.call("calc_risk", {"model_spec": model_spec, "scenario": "high_risk"})
    profile_wrap = global_registry.call(
        "generate_risk_profile",
        {"model_spec": model_spec, "risk_metrics": metrics},
    )
    gate = global_registry.call("check_gate", {"risk_profile": profile_wrap["risk_profile"]})
    assert gate["requires_human"] is True


def test_mcp_call_tool_calc_risk():
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    model_spec = json.loads(path.read_text(encoding="utf-8"))
    result = mcp_server.call_tool("calc_risk", {"model_spec": model_spec, "scenario": "normal"})
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["max_drawdown"] == 0.08

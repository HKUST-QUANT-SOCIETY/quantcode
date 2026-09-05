"""Headless process smoke: the shipped stdio entrypoint, no LLM/network calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("group", ["factor", "model", "risk", "strategy", "options", "fundamental"])
def test_mcp_stdio_catalog_and_deploy_boundary(group):
    env = {key: value for key, value in os.environ.items() if not key.startswith("QUANTCODE_")}
    env.update(PYTHONPATH=str(ROOT), QUANTCODE_ENV="test", QUANTCODE_GROUP=group)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "deploy_alphaflow", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
    ]
    result = subprocess.run(
        [sys.executable, "-m", "quantcode.mcp_server"],
        input="".join(json.dumps(request) + "\n" for request in requests),
        text=True, encoding="utf-8", capture_output=True, env=env, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stderr[-1000:]
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [item["id"] for item in responses] == [1, 2, 3, 4]
    catalog = {tool["name"] for tool in responses[1]["result"]["tools"]}
    assert {"run_agent", "session_context", "list_skills"} <= catalog
    assert "deploy_alphaflow" not in catalog
    assert responses[2]["result"]["isError"] is True
    assert responses[3]["result"] == {}

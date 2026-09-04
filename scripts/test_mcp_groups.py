"""MCP 多组烟测 — Day 4 刘炽 OpenCode 落地检验。

模拟 OpenCode 通过 MCP 调 Python tools（与 ``scripts/test_mcp_client.py`` 同协议）。
对 strategy / fundamental / options 三组各跑：
  initialize → tools/list → tools/call（代表性 tool）

用法：
    cd quantcode/
    python3 scripts/test_mcp_groups.py
    python3 scripts/test_mcp_groups.py --group strategy
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
MCP_MODULE = "quantcode.mcp_server"


class MCPClient:
    def __init__(self, group: str):
        self.group = group
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT) + os.pathsep + self.env.get("PYTHONPATH", "")
        self.env["QUANTCODE_GROUP"] = group
        self.env["QUANTCODE_ENV"] = "test"
        self.env["QUANTCODE_ALLOW_UNAUTH"] = "1"
        self.proc: subprocess.Popen | None = None
        self._req_id = 0

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [PYTHON, "-m", MCP_MODULE],
            cwd=str(ROOT),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        notify = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(notify) + "\n")
        self.proc.stdin.flush()
        resp = self._send("initialize", {})
        name = resp.get("result", {}).get("serverInfo", {}).get("name")
        if name != "quantcode-mcp":
            raise RuntimeError(f"bad server: {resp}")

    def _send(self, method: str, params: dict | None = None) -> dict:
        self._req_id += 1
        req: dict = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params is not None:
            req["params"] = params
        assert self.proc and self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"server closed; stderr={err}")
        return json.loads(line)

    def list_tools(self) -> list[dict]:
        return self._send("tools/list", {}).get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._send("tools/call", {"name": name, "arguments": arguments}).get(
            "result", {}
        )

    def close(self) -> None:
        if self.proc:
            if self.proc.stdin:
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# group → (expected tool ids, sample call)
GROUP_CASES: dict[str, tuple[set[str], tuple[str, dict]]] = {
    "strategy": (
        {"select_signals", "combine_signals", "run_strategy_backtest", "deployment_candidate"},
        (
            "select_signals",
            {
                "candidates": [
                    {"signal_id": "pb_roe", "source_group": "factor", "weight_hint": 0.4},
                    {"signal_id": "mom20", "source_group": "factor", "weight_hint": 0.6},
                ],
                "max_positions": 2,
            },
        ),
    ),
    "fundamental": (
        {"pit_rag_search", "extract_financial", "dcf_valuation", "render_report"},
        (
            "pit_rag_search",
            {"query": "蜜雪冰城 财务", "as_of_date": "2025-01-01", "top_k": 5},
        ),
    ),
    "options": (
        {"build_vol_surface", "calc_greeks", "run_options_backtest_stub"},
        (
            "build_vol_surface",
            {
                "strategy_name": "gc_vol_carry",
                "underlying": "GC",
                "as_of_date": "2026-06-27",
                "write_artifact": False,
            },
        ),
    ),
}


def run_group(group: str) -> bool:
    expected, (tool_name, tool_args) = GROUP_CASES[group]
    print(f"\n{'=' * 60}\nGROUP: {group}\n{'=' * 60}")
    client = MCPClient(group)
    try:
        client.start()
        tools = client.list_tools()
        names = {t["name"] for t in tools}
        print(f"[list] {len(tools)} tools: {sorted(names)}")
        if not expected <= names:
            print(f"[FAIL] missing {sorted(expected - names)}, got {sorted(names)}")
            return False

        result = client.call_tool(tool_name, tool_args)
        if result.get("isError"):
            print(f"[FAIL] {tool_name}: {result['content'][0]['text']}")
            return False
        text = result["content"][0]["text"]
        payload = json.loads(text)
        print(f"[call] {tool_name} OK — keys: {list(payload.keys())[:8]}")
        return True
    except Exception as e:
        print(f"[FAIL] {group}: {e}")
        return False
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        choices=list(GROUP_CASES.keys()),
        help="只测一组；默认测 strategy+fundamental+options",
    )
    args = parser.parse_args()
    groups = [args.group] if args.group else list(GROUP_CASES.keys())

    t0 = time.time()
    ok = all(run_group(g) for g in groups)
    print(f"\n{'=' * 60}")
    print(f"{'ALL PASSED' if ok else 'SOME FAILED'} in {time.time() - t0:.2f}s")
    print(f"{'=' * 60}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

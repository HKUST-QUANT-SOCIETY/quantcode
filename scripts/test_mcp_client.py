"""MCP 客户端烟测脚本 — Day 3 尹一帆。

目的：
    Day 3 review §3.3 / §3.4 实测发现 ``cd ../MiMo-code/packages/opencode && npm run dev``
    会爆 ``RangeError: Maximum call stack size exceeded``（hono router 循环）。
    我们的 MCP server 是 Python stdio 进程，**跟 OpenCode 自身完全解耦**——本脚本
    直接 spawn ``python -m quantcode.mcp_server`` 当 subprocess，用 JSON-RPC over stdio
    调它的 ``initialize`` / ``tools/list`` / ``tools/call`` 三个 method。

    跑通这个脚本 = 100% 验证 MCP 协议层 OK，不需要 OpenCode TUI 启动成功。

用法：
    cd quantcode/
    python scripts/test_mcp_client.py
    # 或显式指定 Python 环境
    "C:/ProgramData/Anaconda3/envs/hkust-quant/python.exe" scripts/test_mcp_client.py

退出码：
    0 = 全部 RPC 成功
    1 = 任何 RPC 失败或 subprocess 异常

Owner: 尹一帆
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
QUANTCODE_ROOT = SCRIPT_DIR.parent
PYTHON = sys.executable  # 默认用当前 Python 解释器
MCP_MODULE = "quantcode.mcp_server"


# ---------------------------------------------------------------------------
# JSON-RPC over stdio 客户端（手写，避免引依赖）
# ---------------------------------------------------------------------------


class MCPClient:
    """最简 MCP stdio client：subprocess + 每行一条 JSON。"""

    def __init__(self, cmd: list[str], cwd: Path | None = None, env: dict | None = None):
        self.cmd = cmd
        self.cwd = cwd
        # 合并环境变量，确保 PYTHONPATH 让 subprocess 能找到 quantcode 包
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        if str(QUANTCODE_ROOT) not in full_env.get("PYTHONPATH", ""):
            full_env["PYTHONPATH"] = (
                str(QUANTCODE_ROOT)
                + os.pathsep
                + full_env.get("PYTHONPATH", "")
            )
        self.env = full_env
        self.proc: subprocess.Popen | None = None
        self._req_id = 0

    def start(self) -> None:
        print(f"[client] starting: {' '.join(self.cmd)}")
        print(f"[client] cwd: {self.cwd or QUANTCODE_ROOT}")
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=str(self.cwd or QUANTCODE_ROOT),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # 行缓冲
        )
        # 启动后立刻发 initialize
        self._send_initialize()

    def _send(self, method: str, params: dict | None = None) -> dict:
        self._req_id += 1
        req = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params is not None:
            req["params"] = params
        line = json.dumps(req, ensure_ascii=False)
        print(f"[client] → {method} (id={self._req_id})")
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

        # 读响应（一行 JSON）
        assert self.proc and self.proc.stdout
        resp_line = self.proc.stdout.readline()
        if not resp_line:
            stderr = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"server closed stdin; stderr: {stderr}")
        resp = json.loads(resp_line)
        print(f"[client] ← id={resp.get('id')} {'OK' if 'result' in resp else 'ERR'}")
        return resp

    def _send_initialize(self) -> None:
        # notifications/initialized 是通知（无 id），不需要响应
        notify = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(notify) + "\n")
        self.proc.stdin.flush()

        # initialize 是请求，需要响应
        resp = self._send("initialize", {})
        result = resp.get("result", {})
        assert result.get("serverInfo", {}).get("name") == "quantcode-mcp", (
            f"unexpected server: {result}"
        )
        print(f"[client] server protocol: {result.get('protocolVersion')}")

    def list_tools(self) -> list[dict]:
        resp = self._send("tools/list", {})
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        resp = self._send("tools/call", {"name": name, "arguments": arguments})
        return resp.get("result", {})

    def ping(self) -> None:
        self._send("ping", {})

    def close(self) -> None:
        if self.proc:
            self.proc.stdin.close() if self.proc.stdin else None
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            stderr_out = self.proc.stderr.read() if self.proc.stderr else ""
            if stderr_out.strip():
                print(f"[server stderr]\n{stderr_out}")


# ---------------------------------------------------------------------------
# 烟测流程
# ---------------------------------------------------------------------------


def smoke_test() -> int:
    cmd = [PYTHON, "-m", MCP_MODULE]
    client = MCPClient(cmd)

    t0 = time.time()
    try:
        client.start()
    except Exception as e:
        print(f"[FAIL] server failed to start: {e}")
        return 1

    print()
    print("=" * 60)
    print("Phase 1: ping")
    print("=" * 60)
    try:
        client.ping()
    except Exception as e:
        print(f"[FAIL] ping: {e}")
        client.close()
        return 1

    print()
    print("=" * 60)
    print("Phase 2: tools/list")
    print("=" * 60)
    try:
        tools = client.list_tools()
    except Exception as e:
        print(f"[FAIL] tools/list: {e}")
        client.close()
        return 1
    if not tools:
        print("[FAIL] tools/list returned empty")
        client.close()
        return 1
    print(f"[OK] discovered {len(tools)} tools:")
    for t in tools:
        props = list(t.get("inputSchema", {}).get("properties", {}).keys())
        print(f"  - {t['name']:25s} ({len(props)} args: {props})")

    print()
    print("=" * 60)
    print("Phase 3: tools/call read_pr")
    print("=" * 60)
    try:
        result = client.call_tool("read_pr", {"pr_number": 42})
    except Exception as e:
        print(f"[FAIL] tools/call: {e}")
        client.close()
        return 1
    if result.get("isError"):
        print(f"[FAIL] tool returned error: {result['content'][0]['text']}")
        client.close()
        return 1
    text = result["content"][0]["text"]
    print(f"[OK] read_pr(42) returned {len(text)} chars")
    print(f"     first 200: {text[:200]}")

    print()
    print("=" * 60)
    print("Phase 4: tools/call extract_metadata")
    print("=" * 60)
    try:
        result = client.call_tool(
            "extract_metadata",
            {"diff": "TICKER: NVDA\nFACTOR_NAME: mom_12_1\n"},
        )
    except Exception as e:
        print(f"[FAIL] extract_metadata call: {e}")
        client.close()
        return 1
    if result.get("isError"):
        print(f"[FAIL] extract_metadata returned error: {result['content'][0]['text']}")
        client.close()
        return 1
    print(f"[OK] extract_metadata returned: {result['content'][0]['text']}")

    print()
    print("=" * 60)
    print(f"ALL PHASES PASSED in {time.time() - t0:.2f}s")
    print("=" * 60)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(smoke_test())
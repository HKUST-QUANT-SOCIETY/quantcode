"""
Minimal MCP server exposing calc_risk_stub as a discoverable tool.

OpenCode spawns this via stdio, discovers the tool, and agents can
call it directly when they need risk profile data.

Launch (called by opencode): python tools/risk_stub_mcp.py
"""
from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tools.risk_stub import calc_risk_stub

server = Server("quantcode-risk-stub")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="calc_risk_stub",
            description="Generate risk profile data for a given scenario.",
            inputSchema={
                "type": "object",
                "properties": {
                    "scenario": {
                        "type": "string",
                        "description": "Either 'normal' (all metrics safe) or 'high_risk' (metrics exceed).",
                    }
                },
                "required": ["scenario"],
            },
        )
    ]


@server.call_tool()
async def call_calc_risk_stub(name: str, arguments: dict) -> list[TextContent]:
    if name != "calc_risk_stub":
        raise ValueError(f"Unknown tool: {name}")
    import json
    result = calc_risk_stub(arguments["scenario"])
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

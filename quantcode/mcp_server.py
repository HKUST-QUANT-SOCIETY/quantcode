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
import logging
import os
import sys
from pathlib import Path
from typing import Any

# 诊断日志：stderr（不污染 stdout JSON-RPC），Dev 模式默认开启
logger = logging.getLogger("quantcode.mcp")

# 让 ``python -m quantcode.mcp_server`` 也能找到 tools / runner
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.registry import registry, ToolDef
from tools.schema_utils import pydantic_to_json_schema  # Day 4: 提取到公共模块

# Day 3 评审修复（🟢#6）：MCP server 暴露的 tool 集合受 ``QUANTCODE_GROUP`` 环境变量过滤。
# 默认（未设置）保持原行为：返回所有已注册 tool（兼容 day3-merge 后尚未分组的 tool）。
# 设置如 ``QUANTCODE_GROUP=model`` 后只返回该组 allowlist 内的 tool，避免泄漏
# 尚未上线或跨组的内部 tool。
#
# Day 4 俞高磊：改为惰性函数 _get_mcp_group()，每次请求实时读环境变量，
# 避免切换组时需要 importlib.reload。
def _strip_jsonc_comments(text: str) -> str:
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            result.append(ch)
            i += 1
        elif not in_string and text[i:i + 2] == "//":
            while i < len(text) and text[i] != "\n":
                i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _load_local_mcp_env() -> dict[str, str]:
    """从 ``opencode.local.jsonc`` 读取 ``mcp.quantcode.environment`` 作为 fallback。"""
    local_config = PROJECT_ROOT / "opencode.local.jsonc"
    if not local_config.exists():
        return {}
    try:
        text = local_config.read_text(encoding="utf-8")
        config = json.loads(_strip_jsonc_comments(text))
        return config.get("mcp", {}).get("quantcode", {}).get("environment", {}) or {}
    except Exception:
        return {}


def _get_mcp_group() -> str | None:
    """读取当前活跃组，三级优先级：
    1. QUANTCODE_GROUP 环境变量（静态注入，支持 OpenCode MCP environment 块）
    2. .quantcode_group 文件（动态切换，set_group.py 写入，秒级生效无需重启）
    3. opencode.local.jsonc 的 mcp.quantcode.environment.QUANTCODE_GROUP（兜底）
    """
    g = os.environ.get("QUANTCODE_GROUP", "").strip() or None
    if g is not None:
        return g

    # 2. 动态文件（Day 5 组绑定）—— 解决硬编码在 local.jsonc 的静态注入问题
    group_file = PROJECT_ROOT / ".quantcode_group"
    if group_file.exists():
        g = group_file.read_text(encoding="utf-8").strip() or None
        if g is not None:
            return g

    # 3. opencode.local.jsonc 兜底
    local_env = _load_local_mcp_env()
    g = local_env.get("QUANTCODE_GROUP", "").strip() or None
    return g


from tools.model._register import (  # noqa: F401  触发 model tool 注册
    read_pr_tool,
    extract_metadata_tool,
    generate_model_spec_tool,
    write_blackboard_tool,
    trigger_risk_flow_tool,
)
from tools.options._register import (  # noqa: F401  触发 options tool 注册
    build_vol_surface_tool,
    calc_greeks_tool,
    run_options_backtest_stub_tool,
)
import tools.risk._register  # noqa: F401  触发 risk tool 注册
import tools.factor._register  # noqa: F401  触发 factor tool 注册(Day 4 尹一帆)
import tools.strategy._register  # noqa: F401  触发 strategy tool 注册
import tools.fundamental._register  # noqa: F401  触发 fundamental tool 注册
import runner.agent_mcp_tool  # noqa: F401  触发 run_agent tool 注册（Day 4 俞高磊）


# ---------------------------------------------------------------------------
# LLM 模型工厂（Day 4 俞高磊）
# ---------------------------------------------------------------------------


def _get_model():
    """从环境变量或 ``opencode.local.jsonc`` 实例化 LLM 模型，供 run_agent tool 使用。

    优先级：环境变量 > ``opencode.local.jsonc`` 的 ``mcp.quantcode.environment``。
    支持的环境变量 / 配置项：
    - QUANTCODE_API_KEY / ANTHROPIC_API_KEY / STEPFUN_PLAN_API_KEY：API key
    - QUANTCODE_MODEL_NAME：模型名（默认 step-3.7-flash）
    - QUANTCODE_MODEL_PROVIDER：anthropic | stepfun（默认 stepfun）
    - QUANTCODE_MODEL_BASE_URL：自定义 API base URL

    返回一个可调用对象，签名 ``(messages, tools=...) -> AIMessage``，
    适配 AgentRunner 的 model 接口。配置失败返回 None。
    """
    local_env = _load_local_mcp_env()

    api_key = (
        os.environ.get("QUANTCODE_API_KEY")
        or os.environ.get("STEPFUN_PLAN_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY", "")
        or local_env.get("QUANTCODE_API_KEY")
        or local_env.get("STEPFUN_PLAN_API_KEY")
        or local_env.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        # ★ 诊断：列出所有包含 KEY / API 的环境变量键名，帮助定位问题
        all_keys = sorted(os.environ.keys())
        key_candidates = [k for k in all_keys if any(kw in k.upper() for kw in ("KEY", "API", "STEPFUN", "ANTHROPIC", "QUANTCODE"))]
        logger.warning(
            "_get_model: no API key found. "
            "Checked env: QUANTCODE_API_KEY=%s, STEPFUN_PLAN_API_KEY=%s, ANTHROPIC_API_KEY=%s. "
            "Checked local: QUANTCODE_API_KEY=%s, STEPFUN_PLAN_API_KEY=%s, ANTHROPIC_API_KEY=%s. "
            "Relevant env keys present: %s. Total env vars: %d",
            "set" if os.environ.get("QUANTCODE_API_KEY") else "MISSING",
            "set" if os.environ.get("STEPFUN_PLAN_API_KEY") else "MISSING",
            "set" if os.environ.get("ANTHROPIC_API_KEY") else "MISSING",
            "set" if local_env.get("QUANTCODE_API_KEY") else "MISSING",
            "set" if local_env.get("STEPFUN_PLAN_API_KEY") else "MISSING",
            "set" if local_env.get("ANTHROPIC_API_KEY") else "MISSING",
            key_candidates, len(all_keys),
        )
        return None

    provider = os.environ.get("QUANTCODE_MODEL_PROVIDER", "stepfun") or local_env.get("QUANTCODE_MODEL_PROVIDER", "stepfun")
    model_name = os.environ.get("QUANTCODE_MODEL_NAME", "step-3.7-flash") or local_env.get("QUANTCODE_MODEL_NAME", "step-3.7-flash")
    base_url = os.environ.get("QUANTCODE_MODEL_BASE_URL", "https://api.stepfun.com/step_plan/v1") or local_env.get("QUANTCODE_MODEL_BASE_URL", "https://api.stepfun.com/step_plan/v1")

    def _build_model():
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model_name, api_key=api_key, temperature=0.1, max_tokens=4096,
            )
        elif provider == "stepfun":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=0.1, max_tokens=4096,
            )
        return None

    try:
        chat_model = _build_model()
    except ImportError as e:
        logger.error("_get_model: import failed for provider=%s — missing dependency: %s", provider, e)
        return None
    except Exception as e:
        logger.error("_get_model: build failed for provider=%s model=%s — %s: %s",
                     provider, model_name, type(e).__name__, e)
        return None

    if chat_model is None:
        return None

    # ★ 关键：ChatOpenAI 不可直接调用，只有 .invoke()
    # AgentRunner 的 make_llm_node 调 model(messages, tools=...)
    def _callable_model(messages, tools=None):
        if tools:
            tool_dicts = []
            for t in tools:
                params = {}
                if hasattr(t, 'schema') and hasattr(t.schema, 'model_json_schema'):
                    try:
                        js = t.schema.model_json_schema()
                        js.pop("title", None)
                        params = js
                    except Exception:
                        params = {"type": "object", "properties": {}}
                tool_dicts.append({
                    "type": "function",
                    "function": {
                        "name": t.id, "description": t.description, "parameters": params,
                    }
                })
            bound = chat_model.bind_tools(tool_dicts, strict=False)
        else:
            bound = chat_model
        return bound.invoke(messages)

    _callable_model._quantcode_model_name = model_name  # type: ignore[attr-defined]

    return _callable_model


# ---------------------------------------------------------------------------
# Pydantic schema → JSON Schema（已提取到 tools/schema_utils.py）
# ---------------------------------------------------------------------------

# pydantic_to_json_schema 从 tools.schema_utils import，保留此注释块作为文档锚点


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


def _tools_for_mcp_group(group: str | None) -> list[ToolDef]:
    """Resolve the exact externally callable surface for one MCP group."""

    if group:
        tools = registry.get_tools_for_group(group)
        if group == "risk":
            # Fixed RiskProfile tools remain legacy-internal; desktop/MCP enters
            # through the bounded dynamic child task.
            tools = [tool for tool in tools if tool.id == "spawn_risk_scout"]
    else:
        tools = registry.list_all()

    try:
        run_agent = registry.get("run_agent")
        if getattr(run_agent, "_meta", False) and run_agent not in tools:
            tools = [*tools, run_agent]
    except KeyError:
        pass
    return sorted(tools, key=lambda tool: tool.id)


def list_tools() -> dict:
    """实现 MCP 的 ``tools/list``：返回 QUANTCODE_GROUP 过滤后的 tool。

    未设置 ``QUANTCODE_GROUP`` 环境变量时保持原行为（返回全部已注册 tool）。
    设置后仅返回该组 ``.opencode/groups/<group>/tool_allowlist.yaml`` 内的 tool。

    Day 4 俞高磊: 在列表末尾附加 run_agent meta tool（若存在），
    让 OpenCode compose agent 能发现并调用它。
    """
    _mcp_group = _get_mcp_group()
    tools = _tools_for_mcp_group(_mcp_group)
    if _mcp_group:
        logger.info("list_tools: group=%s → %d tools", _mcp_group, len(tools))
    else:
        logger.info("list_tools: no group → %d tools (all)", len(tools))

    tool_ids = [t.id for t in tools]
    logger.debug("list_tools: returning %s", tool_ids)
    return {
        "tools": [tool_def_to_mcp(t) for t in tools],
    }


def call_tool(name: str, arguments: dict) -> dict:
    """实现 MCP 的 ``tools/call``：执行 tool 并返回结果。

    返回 MCP 规定的格式::

        {
            "content": [{"type": "text", "text": "..."}],
            "isError": False
        }

    Day 4 俞高磊：ctx 注入 group（当前活跃组）+ _model（LLM 实例），
    供 run_agent 等需要完整 AgentRunner 上下文的 tool 使用。
    """
    try:
        mcp_group = _get_mcp_group()
        if mcp_group:
            allowed = {tool.id for tool in _tools_for_mcp_group(mcp_group)}
            if name not in allowed:
                raise PermissionError(
                    f"tool '{name}' is not exposed to MCP group '{mcp_group}'"
                )
        else:
            registry.get(name)
        ctx: dict[str, Any] = {
            "source": "mcp",
            "_model": _get_model(),
        }
        # ★ 只有 group 非空时才注入，避免 ctx["group"]=None 导致
        # dict.get("group", "") 返回 None 而非默认值 ""
        if mcp_group:
            ctx["group"] = mcp_group
        logger.info(
            "call_tool: %s argument_keys=%s group=%s model=%s",
            name,
            sorted(arguments) if isinstance(arguments, dict) else [],
            mcp_group or "(unset)",
            "present" if ctx["_model"] else "missing",
        )
        result = registry.call(name, arguments, ctx=ctx)
        text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
    except Exception as e:
        if isinstance(e, PermissionError):
            detail = str(e)
        elif isinstance(e, KeyError):
            detail = f"unknown tool '{name}'"
        else:
            detail = "request failed"
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: {type(e).__name__}: {detail}",
                }
            ],
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
    logger.info("MCP server starting: cwd=%s python=%s group=%s "
                "STEPFUN_PLAN_API_KEY=%s QUANTCODE_API_KEY=%s",
                os.getcwd(), sys.executable,
                _get_mcp_group() or "(unset)",
                "set(len=%d)" % len(os.environ["STEPFUN_PLAN_API_KEY"]) if "STEPFUN_PLAN_API_KEY" in os.environ else "MISSING",
                "set" if "QUANTCODE_API_KEY" in os.environ else "MISSING")
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

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

from pydantic import BaseModel, Field

# 诊断日志：stderr（不污染 stdout JSON-RPC），Dev 模式默认开启
logger = logging.getLogger("quantcode.mcp")

# 让 ``python -m quantcode.mcp_server`` 也能找到 tools / runner
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.registry import registry, ToolDef
from tools.schema_utils import pydantic_to_json_schema  # Day 4: 提取到公共模块
from quantcode import identity  # P0-7: SSH key → group 绑定解析

# Day 3 评审修复（🟢#6）：MCP server 暴露的 tool 集合受 ``QUANTCODE_GROUP`` 环境变量过滤。
# 默认（未设置）保持原行为：返回所有已注册 tool（兼容 day3-merge 后尚未分组的 tool）。
# 设置如 ``QUANTCODE_GROUP=model`` 后只返回该组 allowlist 内的 tool，避免泄漏
# 尚未上线或跨组的内部 tool。
#
# P0-7：组身份解析升级为三级（SSH key → 组长期绑定，会话内不可变，
# 见 ``docs/Architecture_Spec.md`` §2.1 与 ``quantcode/identity.py``）：
#   a) env ``QUANTCODE_SSH_KEY_FINGERPRINT``（别名 ``QUANTCODE_SSH_FINGERPRINT``）
#      存在 → 查绑定映射；命中 → 返回该组并进程内缓存；未命中 → fail-closed。
#   b) 无指纹且映射文件缺失/为空 → 沿用 ``QUANTCODE_GROUP`` env（本地单用户降级）。
#   c) 无指纹但映射文件有绑定 → fail-closed，除非 ``QUANTCODE_ALLOW_UNAUTH=1``
#      （此时 env 兜底 + warning）。
# 会话内不可变：指纹一旦解析出组即锁定为会话组（一个 MCP server 进程 = 一个会话），
# 之后即使 env 指纹消失或绑定文件被改，会话组身份也不变（防会话中途降权/换组）。
_SESSION_GROUP: str | None = None


def _get_ssh_fingerprint() -> str | None:
    """读取宿主注入的 SSH 公钥指纹 env（主名 + 兼容别名）。"""
    fp = (
        os.environ.get("QUANTCODE_SSH_KEY_FINGERPRINT")
        or os.environ.get("QUANTCODE_SSH_FINGERPRINT")
        or ""
    ).strip()
    return fp or None


def _env_group() -> str | None:
    return os.environ.get("QUANTCODE_GROUP", "").strip() or None


def _get_mcp_group() -> str | None:
    """解析当前活跃组（P0-7 三级，见模块头注释）。

    途径：
    1. SSH 指纹 env（``QUANTCODE_SSH_KEY_FINGERPRINT``/``QUANTCODE_SSH_FINGERPRINT``）
       → ``.opencode/authorized_groups.yaml`` 绑定映射（命中后进程内锁定为会话组）
    2. 无绑定配置时降级：``QUANTCODE_GROUP`` env（shell export 或
       opencode.jsonc 的 ``mcp.<server>.environment.QUANTCODE_GROUP``）
    3. 有绑定配置但无指纹：fail-closed，或显式 ``QUANTCODE_ALLOW_UNAUTH=1`` 降级
    """
    global _SESSION_GROUP
    if _SESSION_GROUP is not None:
        # 会话内已通过指纹解析 → 不可变，直接返回
        return _SESSION_GROUP

    fp = _get_ssh_fingerprint()
    if fp is not None:
        group = identity.resolve_group(fp, identity.load_bindings())
        if group is None:
            raise RuntimeError(
                f"P0-7 fail-closed: SSH 指纹 {fp} 未在 "
                f"{identity.DEFAULT_BINDINGS_PATH} 命中任何组绑定。"
                "如何修复: python -m quantcode.identity add --group <group> "
                "--public-key <pubkey_path> "
                "（指纹可用 ssh-keygen -lf <pubkey> 或 "
                "python -m quantcode.identity list 核对）。"
            )
        _SESSION_GROUP = group
        return group

    bindings = identity.load_bindings()
    if bindings:
        # 有绑定配置但本会话未提供指纹 → 默认 fail-closed
        if os.environ.get("QUANTCODE_ALLOW_UNAUTH", "").strip() == "1":
            g = _env_group()
            logger.warning(
                "_get_mcp_group: 已配置 SSH 组绑定但未提供指纹，"
                "QUANTCODE_ALLOW_UNAUTH=1 显式降级，组身份来自环境变量 (%s)。",
                g or "(unset)",
            )
            return g
        raise RuntimeError(
            f"P0-7 fail-closed: 检测到 {len(bindings)} 条 SSH 组绑定 "
            f"({identity.DEFAULT_BINDINGS_PATH}) 但本会话未提供指纹。三条出路: "
            "1) export QUANTCODE_SSH_KEY_FINGERPRINT=SHA256:... "
            "(或别名 QUANTCODE_SSH_FINGERPRINT，指纹来自 ssh-keygen -lf "
            "/ python -m quantcode.identity list); "
            "2) python -m quantcode.identity add --group <group> "
            "--public-key <pubkey_path> 绑定本机; "
            "3) 本地单用户显式降级: export QUANTCODE_ALLOW_UNAUTH=1。"
        )

    # 无绑定配置 → 沿用 env（本地单用户降级）
    g = _env_group()
    if g is None:
        logger.warning(
            "_get_mcp_group: 未配置 SSH 绑定（绑定文件缺失或为空），"
            "QUANTCODE_GROUP 也未设置 — 组过滤关闭，返回全部 tool。"
            "配置途径: 1) shell export, 2) mcp.<server>.environment in opencode.jsonc, "
            "3) python -m quantcode.identity add 绑定 SSH key。"
        )
    else:
        logger.warning(
            "_get_mcp_group: 未配置 SSH 绑定，组身份来自环境变量 "
            "QUANTCODE_GROUP=%s（本地单用户降级）。生产部署请改用 "
            "python -m quantcode.identity add 绑定 SSH key。",
            g,
        )
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
import tools.market._register  # noqa: F401  触发 market tool 注册(P-01)
import tools.strategy._register  # noqa: F401  触发 strategy tool 注册
import tools.fundamental._register  # noqa: F401  触发 fundamental tool 注册
import tools.algorithms._register as _algorithms_register  # noqa: F401  触发算法注册表三工具注册(ROADMAP A3)
from tools.algorithms._register import (  # noqa: F401
    describe_algorithm_tool,
    list_algorithms_tool,
    run_algorithm_tool,
)
import runner.agent_mcp_tool  # noqa: F401  触发 run_agent tool 注册（Day 4 俞高磊）


# ---------------------------------------------------------------------------
# list_algorithms 只读工具（configs/algorithms.yaml 注册表目录，ROADMAP A3）
# ---------------------------------------------------------------------------

# ponytail: 走 list_runs 同款 _meta 通道 —— 不进各组 allowlist 也能被六组 MCP
# server 的 tools/list 列出（list_tools 末尾统一附加 meta tool），只读无副作用。
# 三件套（list/describe/run）全部 _meta：算法实验是平台级能力。
list_algorithms_tool._meta = True  # type: ignore[attr-defined]
describe_algorithm_tool._meta = True  # type: ignore[attr-defined]
run_algorithm_tool._meta = True  # type: ignore[attr-defined]
# 幂等：覆盖式注册（register_tool 已是覆盖语义，重复 register 无害）
for _t in (list_algorithms_tool, describe_algorithm_tool, run_algorithm_tool):
    registry._tools[_t.id] = _t


# ---------------------------------------------------------------------------
# list_runs 只读工具（metrics 查询，monitor Tab 数据源）
# ---------------------------------------------------------------------------


class ListRunsArgs(BaseModel):
    """list_runs 的输入参数 — 只读查询 `.quantcode/metrics.jsonl`。"""

    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="返回最近 N 条 run 记录（1-200，默认 20）。",
    )


def _list_runs_execute(args: ListRunsArgs, ctx: dict) -> dict:
    """执行 list_runs：read_recent + aggregate 汇总。只读，best-effort。"""
    from runner import metrics

    return {
        "recent_runs": metrics.read_recent(args.limit),
        "aggregate": metrics.aggregate(window=max(args.limit, 20)),
    }


list_runs_tool = ToolDef(
    id="list_runs",
    description=(
        "Read-only query of recent agent run metrics from .quantcode/metrics.jsonl. "
        "Returns recent runs (group/flow/status/duration/tool_calls) and aggregate "
        "stats (runs/success_rate/avg_duration_s/error_rate/by_group)."
    ),
    schema=ListRunsArgs,
    execute=_list_runs_execute,
)
# ponytail: 走 run_agent 同款 _meta 通道 — 不进各组 allowlist 也能被所有 6 组
# MCP server 的 tools/list 列出（list_tools 末尾统一附加 meta tool），只读无副作用。
list_runs_tool._meta = True  # type: ignore[attr-defined]
# 幂等：register_tool 覆盖式注册（模块 reload 安全，registry.register 会因重复 id 抛错）
registry._tools[list_runs_tool.id] = list_runs_tool


# ---------------------------------------------------------------------------
# list_skills 只读工具（`.opencode/groups/<group>/skills/` 目录枚举，lens Skill 下拉数据源）
# ---------------------------------------------------------------------------


class ListSkillsArgs(BaseModel):
    """list_skills 的输入参数 — 只读枚举某组的 SKILL.md 目录。"""

    group: str = Field(
        description="组名（model / risk / factor / fundamental / options / strategy）。",
    )


# SKILL.md frontmatter 解析：PyYAML（仓库已依赖，与 tools/registry.py 同源），
# 与 tools/skills/loader.py::_strip_frontmatter 的 "---...\n---\n" 边界语义一致。
# 非法/非 dict frontmatter → 返回空字段 dict（try/except 兜底，best-effort）。
def _parse_skill_frontmatter(md_text: str) -> dict:
    """提取 SKILL.md frontmatter 里的 name/description/pattern（缺失字段值为 ""）。"""
    import yaml

    out = {"name": "", "description": "", "pattern": ""}
    if not md_text.startswith("---"):
        return out
    try:
        _head, fm_text, _body = md_text.split("---", 2)
        data = yaml.safe_load(fm_text)
    except (ValueError, yaml.YAMLError):
        return out
    if not isinstance(data, dict):
        return out
    for key in out:
        value = data.get(key)
        if isinstance(value, str):
            out[key] = value.strip()
    return out


def _list_skills_execute(args: ListSkillsArgs, ctx: dict) -> dict:
    """扫描 .opencode/groups/<group>/skills/*/SKILL.md，返回目录（只读）。"""
    group = args.group.strip()
    groups_root = PROJECT_ROOT / ".opencode" / "groups"
    group_dir = groups_root / group
    skills_dir = group_dir / "skills"
    # 组合法性 = 组目录存在；组目录在但 skills/ 为空 → 空列表（合法的空组）
    if not group_dir.is_dir():
        available = sorted(
            p.name for p in groups_root.glob("*") if (p / "skills").is_dir()
        ) if groups_root.is_dir() else []
        return {"error": f"invalid group '{group}', valid: {', '.join(available) or '(none)'}"}
    skills: list[dict] = []
    if skills_dir.is_dir():
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            md = d / "SKILL.md"
            if not md.is_file():
                continue
            fm = _parse_skill_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            skills.append({
                "id": d.name,               # 目录名（load_skill 的 skill_name 参数）
                "name": fm["name"] or d.name,
                "description": fm["description"],
                "pattern": fm["pattern"],
            })
    return {"group": group, "skills": skills}


list_skills_tool = ToolDef(
    id="list_skills",
    description=(
        "Read-only catalog of available skills for a group: scans "
        ".opencode/groups/<group>/skills/*/SKILL.md and returns "
        "{group, skills:[{id, name, description, pattern]}. Use before "
        "load_skill to discover skill ids per group."
    ),
    schema=ListSkillsArgs,
    execute=_list_skills_execute,
)
# 走 list_runs 同款 _meta 通道：所有 6 组 MCP server 的 tools/list 都能列出，只读无副作用。
list_skills_tool._meta = True  # type: ignore[attr-defined]
# 幂等：覆盖式注册（模块 reload 安全）
registry._tools[list_skills_tool.id] = list_skills_tool


# ---------------------------------------------------------------------------
# subagent 元工具（P-04：spawn/check/kill/list 经 _meta 通道注册）
# ---------------------------------------------------------------------------

# 实现（schema+execute）在 tools/subagent/_register.py。四个工具均为编排层元
# 工具，不进各组 tool_allowlist，经统一 _meta 通道向控制器（OpenCode compose /
# monitor）暴露——与 list_runs / list_skills 同路。
import tools.subagent._register  # noqa: F401,E402  触发 subagent tool 注册（P-04）
import tools.stream._register  # noqa: F401,E402  触发 check_tool_stream 注册（_meta 通道）
import tools.portfolio._register  # noqa: F401,E402  触发 portfolio 三工具注册（_meta 通道，确定性数值）


# ---------------------------------------------------------------------------
# LLM 模型工厂（Day 4 俞高磊）
# ---------------------------------------------------------------------------


def _get_model():
    """从环境变量实例化 LLM 模型，供 run_agent tool 使用（P0-6/C30 收敛：仅 env）。

    - QUANTCODE_API_KEY：API key（唯一 key 入口）
    - QUANTCODE_MODEL_PROVIDER：deepseek | anthropic | stepfun（默认 deepseek）
    - QUANTCODE_MODEL_NAME：模型名（默认按 provider：deepseek-chat / claude-sonnet-4-5 / step-3.7-flash）
    - QUANTCODE_MODEL_BASE_URL：自定义 API base URL（deepseek 默认 https://api.deepseek.com/v1，stepfun 默认 step_plan/v1）

    返回一个可调用对象，签名 ``(messages, tools=...) -> AIMessage``，
    适配 AgentRunner 的 model 接口。配置失败返回 None。
    """
    api_key = os.environ.get("QUANTCODE_API_KEY", "").strip()
    if not api_key:
        # ★ 诊断：列出所有包含 KEY / API 的环境变量键名，帮助定位问题
        all_keys = sorted(os.environ.keys())
        key_candidates = [k for k in all_keys if any(kw in k.upper() for kw in ("KEY", "API", "STEPFUN", "ANTHROPIC", "QUANTCODE", "DEEPSEEK"))]
        logger.warning(
            "_get_model: no API key found. "
            "Checked env: QUANTCODE_API_KEY=MISSING. "
            "Relevant env keys present: %s. Total env vars: %d",
            key_candidates, len(all_keys),
        )
        return None

    provider = os.environ.get("QUANTCODE_MODEL_PROVIDER", "deepseek") or "deepseek"

    _DEFAULT_MODELS = {
        "deepseek": "deepseek-chat",
        "anthropic": "claude-sonnet-4-5",
        "stepfun": "step-3.7-flash",
    }
    _DEFAULT_BASE_URLS = {
        "deepseek": "https://api.deepseek.com/v1",
        "stepfun": "https://api.stepfun.com/step_plan/v1",
    }
    model_name = os.environ.get("QUANTCODE_MODEL_NAME", "") or _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS["deepseek"])
    base_url = os.environ.get("QUANTCODE_MODEL_BASE_URL", "") or _DEFAULT_BASE_URLS.get(provider, "")

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
        elif provider == "deepseek":
            # ponytail: deepseek 是 OpenAI 兼容 API，直接复用 ChatOpenAI，不再引独立适配层
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


def list_tools() -> dict:
    """实现 MCP 的 ``tools/list``：返回 QUANTCODE_GROUP 过滤后的 tool。

    未设置 ``QUANTCODE_GROUP`` 环境变量时保持原行为（返回全部已注册 tool）。
    设置后仅返回该组 ``.opencode/groups/<group>/tool_allowlist.yaml`` 内的 tool。

    Day 4 俞高磊: 在列表末尾附加 run_agent meta tool（若存在），
    让 OpenCode compose agent 能发现并调用它。
    """
    _mcp_group = _get_mcp_group()
    if _mcp_group:
        tools = registry.get_tools_for_group(_mcp_group)
        logger.info("list_tools: group=%s → %d tools", _mcp_group, len(tools))
    else:
        tools = registry.list_all()
        logger.info("list_tools: no group → %d tools (all)", len(tools))

    # 附加 meta tool（run_agent / list_runs 等，_meta=True 不进 allowlist，
    # 但所有组的 MCP server 都应能列出）。原 run_agent 硬编码推广为遍历 _meta。
    meta_tools = [
        t for t in registry.list_all()
        if getattr(t, '_meta', False) and t not in tools
    ]
    if meta_tools:
        tools = tools + meta_tools

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
        ctx: dict[str, Any] = {
            "source": "mcp",
            "_model": _get_model(),
        }
        # ★ 只有 group 非空时才注入，避免 ctx["group"]=None 导致
        # dict.get("group", "") 返回 None 而非默认值 ""
        if mcp_group:
            ctx["group"] = mcp_group
        logger.info("call_tool: %s(%s) group=%s model=%s",
                     name, json.dumps(arguments, default=str)[:200],
                     mcp_group or "(unset)",
                     "present" if ctx["_model"] else "missing")
        result = registry.call(name, arguments, ctx=ctx)
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
    logger.info("MCP server starting: cwd=%s python=%s group=%s "
                "QUANTCODE_API_KEY=%s",
                os.getcwd(), sys.executable,
                _get_mcp_group() or "(unset)",
                "set" if os.environ.get("QUANTCODE_API_KEY") else "MISSING")
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
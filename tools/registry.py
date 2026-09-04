"""ToolDef / ToolRegistry / 按组过滤 — Day 3 尹一帆。

设计要点：
- ToolDef 是量化工具的统一契约（Pydantic 模型），对齐 MimoCode ``Def`` 的 4 个核心字段
  （id / description / parameters / execute）+ 可选 ``formatValidationError``。
- ToolRegistry 单例（``registry``），各组 tool 通过装饰器 ``@register_tool`` 自动注册。
- 按组过滤通过 ``.opencode/groups/<group>/tool_allowlist.yaml`` 配置（架构 §3.3）。
- ``registry.call(tool_id, args, ctx)`` 是给 ``tool_node`` 用的入口：自动校验 schema → 执行。

复用与新建：
- 新建：ToolDef / ToolRegistry / get_tools_for_group / load_group_config
- 复用：``tools.utils.dedupe``（给副作用 tool 加去重，Day 1 陈镇鸿）

参考：
- docs/QuantCode_Design.md §3.3
- MimoCode ``packages/opencode/src/tool/tool.ts`` 中的 ``Def`` 接口
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

# tools/registry.py → tools/ → quantcode/（仓库根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROUPS_DIR = PROJECT_ROOT / ".opencode" / "groups"


# ---------------------------------------------------------------------------
# ToolDef：工具的统一契约
# ---------------------------------------------------------------------------

# execute 签名：(validated_args: BaseModel, ctx: dict) -> Any
ExecuteFn = Callable[[BaseModel, dict], Any]
FormatErrorFn = Callable[[Exception], str]

# G4-A1：permission 合法值（None = 未声明，执行层按缺省配置/allow 处理）
VALID_PERMISSIONS = ("allow", "ask", "deny")


def _validate_permission(tool: "ToolDef") -> None:
    """注册时校验 permission 字段（None 或 allow/ask/deny），非法值抛 ValueError。"""
    p = getattr(tool, "permission", None)
    if p is not None and p not in VALID_PERMISSIONS:
        raise ValueError(
            f"Tool '{tool.id}' has invalid permission {p!r}; "
            f"expected one of {VALID_PERMISSIONS} or None"
        )


class ToolDef(BaseModel):
    """量化工具的统一契约（Pydantic 模型）。

    字段对照 MimoCode ``Def``（见 ``Mimo-code/.../tool/tool.ts``）：
    - id             → id             唯一标识，LLM 决策依据
    - description    → description    LLM 可见，描述调用时机
    - schema         → parameters     Pydantic schema（MimoCode 用 Zod）
    - execute        → execute        执行函数
    - format_validation_error → formatValidationError  自定义错误格式化

    取消的字段：
    - shell: TS 专属特性，Python 无 shell-mode 概念
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    id: str
    description: str
    schema: type[BaseModel]
    execute: ExecuteFn
    format_validation_error: Optional[FormatErrorFn] = None
    # G4-A1：权限三态声明（ask/deny/allow）。None = 未声明（执行层默认 allow）。
    # 仅元数据；实际执行策略由 runner/permission_engine 读 configs/permissions.yaml。
    permission: Optional[str] = None


# ---------------------------------------------------------------------------
# ToolRegistry：单例 + 按组过滤
# ---------------------------------------------------------------------------


class ToolRegistry:
    """tool 注册中心。

    用法::

        from tools.registry import registry

        @register_tool
        class ReadPR(ToolDef):
            id = "read_pr"
            ...

        tools = registry.get_tools_for_group("model")   # 按 allowlist 过滤
        result = registry.call("read_pr", {"pr_number": 123})
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    # ----- 注册 -----
    def register(self, tool: ToolDef) -> ToolDef:
        """注册一个 tool；id 重复会抛错。"""
        _validate_permission(tool)
        if tool.id in self._tools:
            raise ValueError(
                f"Tool '{tool.id}' already registered "
                f"(existing: {self._tools[tool.id].execute.__qualname__})"
            )
        self._tools[tool.id] = tool
        return tool

    # ----- 查询 -----
    def get(self, tool_id: str) -> ToolDef:
        """按 id 获取 tool，未找到抛 KeyError。"""
        if tool_id not in self._tools:
            raise KeyError(
                f"Tool '{tool_id}' not found. Available: {sorted(self._tools)}"
            )
        return self._tools[tool_id]

    def list_all(self) -> list[ToolDef]:
        """所有已注册 tool（按 id 排序，deterministic）。"""
        return sorted(self._tools.values(), key=lambda t: t.id)

    def list_ids(self) -> list[str]:
        return sorted(self._tools.keys())

    # ----- 按组过滤（架构 §3.3） -----
    def get_tools_for_group(self, group: str, include_meta: bool = False) -> list[ToolDef]:
        """根据 ``.opencode/groups/<group>/tool_allowlist.yaml`` 过滤 tool。

        行为：
        - allowlist 不存在 → 返回空列表（该组无可用 tool）
        - allowlist 为空 → 返回空列表
        - allowlist 含未注册的 id → 静默跳过（不抛错，便于删 tool 不报错）
        - include_meta=False（默认）：不附加 _meta tool
        - include_meta=True：附加 _meta tool（仅供 MCP list_tools 等外部调用者使用）

        返回的 list 按 id 排序，便于 deterministic。
        """
        config = load_group_config(group)
        allowlist = set(config.get("allowlist", []))
        matched = [t for t in self._tools.values() if t.id in allowlist]
        # Day 4 俞高磊：附加 meta tool（如 run_agent）。
        # ★ include_meta 默认 False——内部 AgentRunner agent 不应看到 meta tool
        if include_meta:
            for t in self._tools.values():
                if getattr(t, '_meta', False) and t not in matched:
                    matched.append(t)
        matched.sort(key=lambda t: t.id)
        return matched

    # ----- 执行（给 tool_node 用） -----
    def call(self, tool_id: str, args: dict, ctx: Optional[dict] = None) -> Any:
        """校验 args → 执行 tool → 返回结果。

        校验失败抛 ``ValueError``（含格式化后的错误信息），
        执行失败抛原异常（让 ``tool_node`` 决定如何处理）。
        """
        tool = self.get(tool_id)
        ctx = ctx or {}
        try:
            validated = tool.schema(**args)
        except Exception as e:
            if tool.format_validation_error is not None:
                msg = tool.format_validation_error(e)
            else:
                msg = f"Invalid arguments for tool '{tool_id}': {e}"
            raise ValueError(msg) from e
        return tool.execute(validated, ctx)


# 全局单例
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# 装饰器：@register_tool
# ---------------------------------------------------------------------------


def register_tool(tool: ToolDef) -> ToolDef:
    """把 ToolDef 实例注册到全局 registry，返回原对象。

    幂等：若 id 已存在则**覆盖**（用于模块重 import 场景）。
    需要严格检查时用 ``registry.register()``。

    用法::

        read_pr_tool = register_tool(ToolDef(
            id="read_pr",
            description="Read the diff of a GitHub PR",
            schema=ReadPRArgs,
            execute=read_pr_execute,
        ))
    """
    if not isinstance(tool, ToolDef):
        raise TypeError(
            f"register_tool 需要 ToolDef 实例，得到 {type(tool).__name__}"
        )
    _validate_permission(tool)
    # 幂等：直接覆盖，不报错（让模块重 import 安全）
    registry._tools[tool.id] = tool
    return tool


# ---------------------------------------------------------------------------
# 按组配置加载
# ---------------------------------------------------------------------------


def load_group_config(group: str) -> dict:
    """加载 ``.opencode/groups/<group>/tool_allowlist.yaml``。

    文件不存在或解析失败 → 返回 ``{"allowlist": []}``（不抛错，
    保证 ``get_tools_for_group`` 始终能返回空列表而不是崩溃）。

    YAML 格式::

        allowlist:
          - read_pr
          - extract_metadata
          ...
    """
    cfg_path = GROUPS_DIR / group / "tool_allowlist.yaml"
    if not cfg_path.exists():
        return {"allowlist": []}
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"allowlist": []}
    if not isinstance(data, dict):
        return {"allowlist": []}
    if "allowlist" not in data:
        return {"allowlist": []}
    allowlist = data["allowlist"]
    if not isinstance(allowlist, list):
        return {"allowlist": []}
    return {"allowlist": [str(x) for x in allowlist]}


__all__ = [
    "ToolDef",
    "ToolRegistry",
    "ExecuteFn",
    "FormatErrorFn",
    "VALID_PERMISSIONS",
    "registry",
    "register_tool",
    "load_group_config",
    "GROUPS_DIR",
    "PROJECT_ROOT",
]

"""allowlist ↔ registry 一致性断言 — P1-6 教训制度化。

背景：tool_allowlist.yaml 里出现 registry 未注册的 id 时，
``get_tools_for_group`` 只静默跳过（见 registry.py 行为说明），幽灵 id 不会报错，
问题要到运行时才暴露。本测试把「yaml 里每个 id 必须可注册」变成 CI 硬约束：

- 遍历六组 yaml，解析 allowlist；
- 除已知平台侧四件（OpenCode 平台侧提供，QuantCode registry 无此 tool）外，
  每个 id 必须出现在 ``registry``（import 完成全部 _register 注册链后核对）；
- 未来任何人往 yaml 加 registry 不存在的 id → 此测试失败。
"""
from __future__ import annotations

import importlib

import pytest
import yaml

# 注册链：import 副作用触发 register_tool（与 quantcode/mcp_server.py 底部的注册块一致）
import runner.agent_mcp_tool  # noqa: F401  run_agent (meta tool)
import tools.factor._register as _factor_register  # noqa: F401  factor group tools
import tools.fundamental._register as _fundamental_register  # noqa: F401
import tools.market._register as _market_register  # noqa: F401  market group tools (P-01)
import tools.model._register as _model_register  # noqa: F402  model group tools
import tools.options._register as _options_register  # noqa: F401  options group tools
import tools.risk._register as _risk_register  # noqa: F401  risk group tools
import tools.strategy._register as _strategy_register
from tools.registry import GROUPS_DIR, registry

# 由 OpenCode 平台侧提供的内建 tool（registry 无此 tool，get_tools_for_group 静默跳过）
PLATFORM_TOOLS = frozenset({"search_memory", "read_file", "write_file", "bash"})

GROUPS = ("factor", "fundamental", "model", "options", "risk", "strategy")

# 全量 pytest 时，其他测试文件会用 registry._tools.clear() 清空全局单例；
# 本文件与它们同跑时必须先 reload 注册链（register_tool 幂等，与 test_day5_jerry_demos.py 同款防御）。
_REGISTER_MODULES = (
    _factor_register,
    _fundamental_register,
    _market_register,
    _model_register,
    _options_register,
    _risk_register,
    _strategy_register,
)


@pytest.fixture(autouse=True)
def _ensure_registered():
    # register_tool 幂等；agent_mcp_tool 用严格 registry.register，已存在时跳过
    for module in _REGISTER_MODULES:
        importlib.reload(module)
    if "run_agent" not in registry.list_ids():
        import runner.agent_mcp_tool as _mcp

        importlib.reload(_mcp)
    yield


def _load_allowlist(group: str) -> list[str]:
    data = yaml.safe_load((GROUPS_DIR / group / "tool_allowlist.yaml").read_text(encoding="utf-8")) or {}
    return [str(x) for x in (data.get("allowlist") or [])]


def _registered_ids() -> set[str]:
    return set(registry.list_ids())


def test_registry_has_tools_after_import_chain():
    """健全性：注册链 import 完成后 registry 非空（防止本测试自身 import 漏掉某组）。"""
    assert len(_registered_ids()) >= 20


def test_allowlist_ids_exist_in_registry():
    """核心断言：除平台侧四件外，六组 yaml 里每个 id 都必须在 registry 注册。"""
    reg = _registered_ids()
    ghost: dict[str, list[str]] = {}
    for group in GROUPS:
        allowlist = _load_allowlist(group)
        ghosts = sorted(set(allowlist) - reg - PLATFORM_TOOLS)
        if ghosts:
            ghost[group] = ghosts
    assert not ghost, (
        f"tool_allowlist.yaml 含 registry 未注册的幽灵 id"
        f"（平台侧 {sorted(PLATFORM_TOOLS)} 除外）: {ghost}"
    )


def test_platform_tools_not_in_registry():
    """锁死契约：平台侧四件确实不由 QuantCode registry 提供（防有人误注册成幽灵反转）。"""
    reg = _registered_ids()
    overlap = sorted(PLATFORM_TOOLS & reg)
    assert not overlap, f"平台侧 tool 不应在 QuantCode registry 注册: {overlap}"


def test_each_group_allowlist_nonempty():
    """每个组至少留一个可用 tool（空名单 = 该组 agent 瘫痪，通常是误删）。"""
    for group in GROUPS:
        allowlist = _load_allowlist(group)
        assert allowlist, f"{group} 的 allowlist 为空"
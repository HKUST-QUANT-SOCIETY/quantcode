"""ToolDef / ToolRegistry / 按组过滤 — Day 3 尹一帆。

覆盖：
- ToolDef Pydantic 模型构造
- register / get / has / list_all / list_ids
- get_tools_for_group 按 allowlist 过滤（不存在 allowlist → 空）
- call() 自动 schema 校验 + 执行 + format_validation_error
- register_tool 装饰器
- load_group_config 容错（文件不存在 / 解析失败 / 格式错 → 空 allowlist）
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from tools.registry import (
    GROUPS_DIR,
    PROJECT_ROOT,
    ToolDef,
    ToolRegistry,
    load_group_config,
    register_tool,
    registry,
)


# ---------------------------------------------------------------------------
# Test fixtures: 清理全局 registry 状态
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个 test 前清空全局 registry（防止 test 间污染）。"""
    registry._tools.clear()
    yield
    registry._tools.clear()


# ---------------------------------------------------------------------------
# ToolDef fixture：mock tool 用
# ---------------------------------------------------------------------------


class MockArgs(BaseModel):
    x: int


def _mock_execute(args: MockArgs, ctx: dict) -> str:
    return f"executed with x={args.x}"


def _mock_format_error(e: Exception) -> str:
    return f"格式化后的错误：{e!r}"


def make_mock_tool(
    tool_id: str = "mock",
    description: str = "A mock tool",
    execute=_mock_execute,
) -> ToolDef:
    return ToolDef(
        id=tool_id,
        description=description,
        schema=MockArgs,
        execute=execute,
        format_validation_error=_mock_format_error,
    )


# ---------------------------------------------------------------------------
# ToolDef
# ---------------------------------------------------------------------------


def test_tool_def_constructs_with_required_fields():
    tool = ToolDef(
        id="read_pr",
        description="Read a PR",
        schema=MockArgs,
        execute=_mock_execute,
    )
    assert tool.id == "read_pr"
    assert tool.description == "Read a PR"
    assert tool.schema is MockArgs
    assert tool.execute is _mock_execute
    assert tool.format_validation_error is None


def test_tool_def_accepts_format_validation_error():
    tool = make_mock_tool()
    assert tool.format_validation_error is _mock_format_error


# ---------------------------------------------------------------------------
# ToolRegistry: register / get / has / list
# ---------------------------------------------------------------------------


def test_register_and_get():
    tool = make_mock_tool()
    registry.register(tool)
    assert registry.get("mock") is tool


def test_register_duplicate_raises():
    registry.register(make_mock_tool())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_mock_tool())


def test_get_unknown_raises_with_available_list():
    registry.register(make_mock_tool("read_pr"))
    registry.register(make_mock_tool("write_pr"))
    with pytest.raises(KeyError, match="read_pr") as exc_info:
        registry.get("missing")
    msg = str(exc_info.value)
    assert "read_pr" in msg and "write_pr" in msg


def test_has():
    registry.register(make_mock_tool("a"))
    assert registry.has("a") is True
    assert registry.has("b") is False


def test_list_all_and_list_ids_sorted():
    registry.register(make_mock_tool("z"))
    registry.register(make_mock_tool("a"))
    registry.register(make_mock_tool("m"))
    assert [t.id for t in registry.list_all()] == ["a", "m", "z"]
    assert registry.list_ids() == ["a", "m", "z"]


# ---------------------------------------------------------------------------
# register_tool 装饰器
# ---------------------------------------------------------------------------


def test_register_tool_decorator():
    """register_tool 接受一个 ToolDef 实例并注册，返回原对象。"""
    tool = make_mock_tool("decorated")
    result = register_tool(tool)
    assert result is tool
    assert registry.has("decorated")
    assert registry.get("decorated").id == "decorated"


def test_register_tool_decorator_rejects_non_tool_def():
    with pytest.raises(TypeError, match="ToolDef"):
        register_tool("not a tool")


# ---------------------------------------------------------------------------
# get_tools_for_group
# ---------------------------------------------------------------------------


def test_get_tools_for_group_filters_by_allowlist(tmp_path, monkeypatch):
    # 把 GROUPS_DIR 临时指向 tmp_path，写一个 model 组的 allowlist
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "tool_allowlist.yaml").write_text(
        "allowlist:\n  - read_pr\n  - write_pr\n", encoding="utf-8"
    )

    registry.register(make_mock_tool("read_pr"))
    registry.register(make_mock_tool("write_pr"))
    registry.register(make_mock_tool("other_tool"))

    tools = registry.get_tools_for_group("model")
    assert {t.id for t in tools} == {"read_pr", "write_pr"}


def test_get_tools_for_group_missing_allowlist_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    # 不创建 allowlist 文件
    registry.register(make_mock_tool("anything"))
    assert registry.get_tools_for_group("nonexistent_group") == []


def test_get_tools_for_group_sorted(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    g = tmp_path / "test"
    g.mkdir()
    (g / "tool_allowlist.yaml").write_text(
        "allowlist:\n  - z\n  - a\n  - m\n", encoding="utf-8"
    )
    registry.register(make_mock_tool("z"))
    registry.register(make_mock_tool("a"))
    registry.register(make_mock_tool("m"))
    ids = [t.id for t in registry.get_tools_for_group("test")]
    assert ids == ["a", "m", "z"]


def test_get_tools_for_group_silently_skips_unregistered(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    g = tmp_path / "test"
    g.mkdir()
    (g / "tool_allowlist.yaml").write_text(
        "allowlist:\n  - registered_tool\n  - never_registered\n", encoding="utf-8"
    )
    registry.register(make_mock_tool("registered_tool"))
    tools = registry.get_tools_for_group("test")
    assert {t.id for t in tools} == {"registered_tool"}


# ---------------------------------------------------------------------------
# load_group_config 容错
# ---------------------------------------------------------------------------


def test_load_group_config_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    assert load_group_config("ghost") == {"allowlist": []}


def test_load_group_config_malformed_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    g = tmp_path / "bad"
    g.mkdir()
    (g / "tool_allowlist.yaml").write_text("not: valid: yaml: [[", encoding="utf-8")
    # 不抛错，返回空 allowlist
    assert load_group_config("bad") == {"allowlist": []}


def test_load_group_config_missing_allowlist_key(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    g = tmp_path / "noallowlist"
    g.mkdir()
    (g / "tool_allowlist.yaml").write_text("other_key: 1\n", encoding="utf-8")
    assert load_group_config("noallowlist") == {"allowlist": []}


def test_load_group_config_allowlist_not_a_list(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    g = tmp_path / "weird"
    g.mkdir()
    (g / "tool_allowlist.yaml").write_text("allowlist: 'not a list'\n", encoding="utf-8")
    assert load_group_config("weird") == {"allowlist": []}


def test_load_group_config_normalizes_to_strings(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.registry.GROUPS_DIR", tmp_path)
    g = tmp_path / "mixed"
    g.mkdir()
    (g / "tool_allowlist.yaml").write_text(
        "allowlist:\n  - 123\n  - true\n  - read_pr\n", encoding="utf-8"
    )
    cfg = load_group_config("mixed")
    assert cfg["allowlist"] == ["123", "True", "read_pr"]


# ---------------------------------------------------------------------------
# call: 校验 + 执行
# ---------------------------------------------------------------------------


def test_call_validates_args_and_executes():
    registry.register(make_mock_tool("echo"))
    result = registry.call("echo", {"x": 42})
    assert result == "executed with x=42"


def test_call_invalid_args_uses_format_validation_error():
    registry.register(make_mock_tool("echo"))
    with pytest.raises(ValueError, match="格式化后的错误") as exc_info:
        registry.call("echo", {"x": "not an int"})
    # 原始 pydantic ValidationError 挂在 cause
    assert exc_info.value.__cause__ is not None


def test_call_invalid_args_falls_back_to_default_message():
    """没有 format_validation_error 时，错误信息应包含 field 路径和类型提示。"""

    def _exec(args: MockArgs, ctx: dict) -> str:
        return "ok"

    tool = ToolDef(
        id="no_fmt",
        description="no formatter",
        schema=MockArgs,
        execute=_exec,
        # format_validation_error 未设置
    )
    registry.register(tool)
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("no_fmt", {"x": "wrong"})


def test_call_unknown_tool_raises():
    with pytest.raises(KeyError, match="missing"):
        registry.call("missing", {})


def test_call_executes_with_provided_ctx():
    """execute 收到的 ctx 应是 call() 传入的 dict。"""
    seen = {}

    def _exec(args: MockArgs, ctx: dict) -> str:
        seen.update(ctx)
        return "ok"

    registry.register(
        ToolDef(id="ctx_aware", description="x", schema=MockArgs, execute=_exec)
    )
    registry.call("ctx_aware", {"x": 1}, ctx={"session_id": "abc", "group": "model"})
    assert seen == {"session_id": "abc", "group": "model"}


# ---------------------------------------------------------------------------
# 路径常量 sanity check
# ---------------------------------------------------------------------------


def test_project_root_points_to_quantcode():
    # tools/registry.py → tools/ → quantcode/（仓库根）
    assert PROJECT_ROOT.name == "quantcode"
    assert (PROJECT_ROOT / "tools").is_dir()
    assert (PROJECT_ROOT / "runner").is_dir()


def test_groups_dir_under_project_root():
    # GROUPS_DIR = PROJECT_ROOT / ".opencode" / "groups"
    assert GROUPS_DIR.parent == PROJECT_ROOT / ".opencode"
    assert GROUPS_DIR.name == "groups"
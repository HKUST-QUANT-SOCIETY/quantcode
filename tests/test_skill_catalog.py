"""list_skills 只读元工具单测 — F-01 缺口修复。

lens UI 的 Skill 下拉此前是 panels.tsx 硬编码 4 条；本工具让 MCP server
枚举 `.opencode/groups/<group>/skills/*/SKILL.md` 真实目录，UI 经 MCP 消费。

覆盖：
1. fixture 临时 .opencode 结构 → 返回组内全部 skill（id/name/description/pattern）
2. 非法 group → 返回 {"error": ...} 对象（不抛异常、不崩 MCP tools/call）
3. _meta 通道可见性：list_tools() 在全部 6 组下都包含 list_skills
"""
from __future__ import annotations

import importlib
import json

import pytest

from quantcode import identity, mcp_server
from tools.registry import registry as global_registry
import tools.model._register  # noqa: F401  注册 model tools（对齐 test_mcp_server）


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch, tmp_path):
    """与 test_mcp_server._clean_registry 同款：隔离身份解析 + 清空 registry。"""
    monkeypatch.delenv("QUANTCODE_GROUP", raising=False)
    for _var in (
        "QUANTCODE_SSH_KEY_FINGERPRINT",
        "QUANTCODE_SSH_FINGERPRINT",
        "QUANTCODE_ALLOW_UNAUTH",
    ):
        monkeypatch.delenv(_var, raising=False)
    monkeypatch.setattr(
        identity, "DEFAULT_BINDINGS_PATH", tmp_path / "nonexistent" / "authorized_groups.yaml"
    )
    monkeypatch.setattr(mcp_server, "_SESSION_GROUP", None)
    global_registry._tools.clear()
    importlib.reload(mcp_server)
    importlib.reload(tools.model._register)
    yield
    global_registry._tools.clear()


SKILL_MD = """---
name: {name}
description: {description}
group: fake
owner: 测试
pattern: {pattern}
---

# 正文（loader 会 strip 掉）
"""


def _make_group(tmp_path, group: str, skills: dict[str, str]):
    """在 tmp 下搭 .opencode/groups/<group>/skills/<sid>/SKILL.md。

    value 为 "" 时只建目录不写 SKILL.md（覆盖「无 SKILL.md 被跳过」分支）。
    """
    base = tmp_path / ".opencode" / "groups" / group / "skills"
    for sid, body in skills.items():
        d = base / sid
        d.mkdir(parents=True, exist_ok=True)
        if body:
            (d / "SKILL.md").write_text(body, encoding="utf-8")


@pytest.fixture
def fake_repo(monkeypatch, tmp_path):
    """把 mcp_server 的仓库根指到 tmp（PROJECT_ROOT 在函数内取，可 monkeypatch）。"""
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. 正常枚举
# ---------------------------------------------------------------------------


def test_list_skills_returns_all_skills_in_group(fake_repo):
    _make_group(fake_repo, "fakegrp", {
        "alpha": SKILL_MD.format(name="grp:alpha", description="Alpha 主工作流", pattern="Pattern 1"),
        "beta": SKILL_MD.format(name="grp:beta", description="Beta 辅助", pattern="Pattern 2"),
        "gamma": SKILL_MD.format(name="", description="", pattern="")  # 空 frontmatter 值
                   .replace("name: \n", "\n").replace("description: \n", "\n")
                   .replace("pattern: \n", "\n"),
    })

    result = mcp_server.call_tool("list_skills", {"group": "fakegrp"})
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["group"] == "fakegrp"
    ids = [s["id"] for s in payload["skills"]]
    assert ids == ["alpha", "beta", "gamma"]  # 排序 deterministic
    by_id = {s["id"]: s for s in payload["skills"]}
    assert by_id["alpha"]["name"] == "grp:alpha"
    assert by_id["alpha"]["description"] == "Alpha 主工作流"
    assert by_id["alpha"]["pattern"] == "Pattern 1"
    # 无 frontmatter 字段时回退：name=目录名，description/pattern 为空
    assert by_id["gamma"]["name"] == "gamma"
    assert by_id["gamma"]["description"] == ""


def test_list_skills_skips_dir_without_skill_md(fake_repo):
    """skills/ 下无 SKILL.md 的子目录被跳过。"""
    _make_group(fake_repo, "fakegrp", {"real": SKILL_MD.format(
        name="x", description="d", pattern="p"), "no-md": ""})
    result = mcp_server.call_tool("list_skills", {"group": "fakegrp"})
    payload = json.loads(result["content"][0]["text"])
    assert [s["id"] for s in payload["skills"]] == ["real"]


def test_list_skills_missing_skills_dir(fake_repo):
    """组目录合法但 skills/ 不存在 → 返回空列表（而非 error）。"""
    (fake_repo / ".opencode" / "groups" / "risk").mkdir(parents=True)
    result = mcp_server.call_tool("list_skills", {"group": "risk"})
    payload = json.loads(result["content"][0]["text"])
    assert payload == {"group": "risk", "skills": []}


# ---------------------------------------------------------------------------
# 2. 非法组 → error 对象
# ---------------------------------------------------------------------------


def test_list_skills_invalid_group_returns_error_object():
    result = mcp_server.call_tool("list_skills", {"group": "nonexistent"})
    assert result["isError"] is False  # 业务级错误走 error 对象，不崩工具
    payload = json.loads(result["content"][0]["text"])
    assert "error" in payload
    assert "nonexistent" in payload["error"]


def test_list_skills_handles_real_repo_groups():
    """真实仓库 .opencode：六组各有 2-4 个 SKILL.md，结构可解析。"""
    GROUPS = ("model", "risk", "factor", "fundamental", "options", "strategy")
    for group in GROUPS:
        result = mcp_server.call_tool("list_skills", {"group": group})
        payload = json.loads(result["content"][0]["text"])
        assert payload["group"] == group
        assert 1 <= len(payload["skills"]) <= 4, f"{group}: {payload['skills']}"
        for s in payload["skills"]:
            assert s["id"] and s["name"]  # 目录名兜底 name


# ---------------------------------------------------------------------------
# 3. _meta 通道可见性（list_tools 含 list_skills）
# ---------------------------------------------------------------------------


def test_list_tools_includes_list_skills_for_all_groups(monkeypatch):
    """list_skills 走 _meta 通道：不进 allowlist，但 6 组 MCP server 都能 tools/list 列出。"""
    for group in ("model", "risk", "factor", "fundamental", "strategy", "options"):
        monkeypatch.setenv("QUANTCODE_GROUP", group)
        importlib.reload(mcp_server)
        names = {t["name"] for t in mcp_server.list_tools()["tools"]}
        assert "list_skills" in names, f"group={group} 缺 list_skills: {names}"


def test_list_skills_not_in_any_allowlist():
    """meta tool 不进组内 ReAct agent 的 allowlist（与 list_runs 同契约）。"""
    internal = {t.id for t in global_registry.get_tools_for_group("model")}
    assert "list_skills" not in internal
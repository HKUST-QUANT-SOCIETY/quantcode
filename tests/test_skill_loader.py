"""skill loader 测试 — Day 3 尹一帆。

覆盖：
- frontmatter 剥离（基本 / 多次 --- / 中文键）
- 业务 skill 加载（成功 / 找不到）
- 元 skill 加载（成功 / 找不到）
- 业务 + 元 skill 叠加
- 元 skill 缺失时静默跳过
"""
from __future__ import annotations

import pytest

from tools.skills.loader import (
    MIMOCODE_SKILLS_DIR,
    MIMOCODE_SKILLS_DIR_FALLBACK,
    MIMOCODE_SKILLS_DIR_VENDORED,
    _strip_frontmatter,
    load_skill,
)


# ---------- frontmatter 剥离 ----------

def test_strip_frontmatter_removes_yaml_block() -> None:
    """带 --- 块的输入应剥离出 frontmatter。"""
    text = "---\nname: tdd\ndescription: TDD method\n---\n\n# Body\n\nContent here.\n"
    result = _strip_frontmatter(text)
    assert "name: tdd" not in result
    assert "description: TDD method" not in result
    assert "# Body" in result
    assert "Content here." in result


def test_strip_frontmatter_keeps_body() -> None:
    """只在开头剥离第一个 frontmatter 块，后续 --- 应当保留。"""
    text = (
        "---\n"
        "name: tdd\n"
        "---\n"
        "\n"
        "# Title\n"
        "\n"
        "Some --- dashes --- in body\n"
        "---\n"
        "more body\n"
    )
    result = _strip_frontmatter(text)
    # frontmatter 不应存在
    assert "name: tdd" not in result
    # body 中的 --- 应当保留
    assert "Some --- dashes --- in body" in result
    assert "more body" in result
    assert "# Title" in result


def test_strip_frontmatter_handles_chinese() -> None:
    """frontmatter 含中文键也应正确剥离。"""
    text = (
        "---\n"
        "name: pit-rag\n"
        "description: 量化研究专用 RAG\n"
        "group: fundamental\n"
        "owner: 用户（Lead）\n"
        "---\n"
        "\n"
        "# Point-in-Time RAG Skill\n"
        "\n"
        "正文内容。\n"
    )
    result = _strip_frontmatter(text)
    assert "name: pit-rag" not in result
    assert "description: 量化研究专用 RAG" not in result
    assert "group: fundamental" not in result
    assert "owner: 用户（Lead）" not in result
    assert "# Point-in-Time RAG Skill" in result
    assert "正文内容。" in result


def test_strip_frontmatter_handles_windows_line_endings() -> None:
    text = "---\r\nname: factor\r\n---\r\n\r\n# Body\r\n"
    result = _strip_frontmatter(text)
    assert "name: factor" not in result
    assert "# Body" in result


# ---------- 业务 skill 加载 ----------

def test_load_business_skill_returns_main_workflow() -> None:
    """load_skill(business) 文本应含 '# 主工作流：<name>' 标题。"""
    text = load_skill("pit-rag", group="fundamental")
    assert "主工作流：pit-rag" in text
    # frontmatter 不应泄露到正文
    assert "name: pit-rag" not in text
    # 业务 SKILL.md 的实际标题
    assert "Point-in-Time RAG Skill" in text or "PIT" in text.upper() or "Point-in-Time" in text


def test_load_business_skill_missing_raises() -> None:
    """load_skill(business, 不存在) 应抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        load_skill("nonexistent", group="factor")


@pytest.mark.parametrize("value", ["../outside", "nested/skill", r"..\\outside", ""])
def test_skill_paths_reject_traversal(value: str) -> None:
    with pytest.raises((ValueError, FileNotFoundError)):
        load_skill(value, group="factor")
    assert "方法论：tdd" in load_skill("tdd", meta_skills=[value])


# ---------- 元 skill 加载 ----------

def test_meta_skill_path_exists() -> None:
    """至少有一个 MimoCode skill 路径应存在（前置校验）。"""
    exists = (
        MIMOCODE_SKILLS_DIR_VENDORED.exists()
        or MIMOCODE_SKILLS_DIR.exists()
        or MIMOCODE_SKILLS_DIR_FALLBACK.exists()
    )
    assert exists, "MimoCode skill bundle 目录不存在"


def test_load_meta_skill_returns_methodology() -> None:
    """load_skill(meta) 文本应含 '# 方法论：<name>' 标题。"""
    text = load_skill("tdd")
    assert "方法论：tdd" in text
    # frontmatter 不应泄露到正文（tdd 元 skill 应有 hidden:true 之类的）
    # 注意 tdd 这个 skill 实际可能通过我们拷贝到 model/tdd 加载，我们应优先从 .bundle/ 加载
    # 因此这里只是断言方法论标题


def test_load_meta_skill_missing_raises() -> None:
    """load_skill(meta, 不存在) 应抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        load_skill("nonexistent_meta")


# ---------- 业务 + 元 skill 叠加 ----------

def test_load_combined_business_and_meta() -> None:
    """load_skill(business, meta_skills=[...]) 应同时含主工作流和方法论补充。"""
    text = load_skill("pit-rag", group="fundamental", meta_skills=["tdd"])
    assert "主工作流：pit-rag" in text
    assert "方法论补充：tdd" in text


def test_meta_skill_missing_in_supplement_silently_skipped() -> None:
    """附加元 skill 列表中的缺失项应静默跳过，不阻塞主流程。"""
    text = load_skill("pit-rag", group="fundamental", meta_skills=["tdd", "nonexistent"])
    # 应正常返回
    assert "主工作流：pit-rag" in text
    # 应包含 tdd
    assert "方法论补充：tdd" in text
    # 不应包含 nonexistent（因为它被跳过了）
    assert "nonexistent" not in text or "方法论补充：nonexistent" not in text


# ---------------------------------------------------------------------------
# 全量元 skill 覆盖（Day 3 review 问题 #1 修复）
# ---------------------------------------------------------------------------

ALL_META_SKILLS = [
    "ask",
    "brainstorm",
    "debug",
    "execute",
    "feedback",
    "merge",
    "new-skill",
    "parallel",
    "plan",
    "report",
    "review",
    "subagent",
    "tdd",
    "verify",
    "worktree",
]


@pytest.mark.parametrize("skill_name", ALL_META_SKILLS)
def test_load_every_mimocode_meta_skill(skill_name):
    """Day 3 review 修复：15 个 MimoCode 元 skill 全部能 load。

    之前 review §1.3 只测了 tdd，覆盖 1/15；现在覆盖 15/15。
    """
    text = load_skill(skill_name)

    # 不空
    assert len(text) > 0
    # 字节数合理（> 1000 bytes 排除空模板）
    assert len(text) > 1000, f"{skill_name} body 太小：{len(text)} bytes"
    # frontmatter 必须被剥离（不含 --- 起始行）
    assert not text.startswith("---"), f"{skill_name} frontmatter 没被剥离"
    # 含方法论标题
    assert f"方法论：{skill_name}" in text


def test_all_meta_skills_can_be_combined():
    """任意 2-3 个元 skill 叠加，都能拼成一个 system prompt。"""
    # 随机抽 3 个组合
    combo = ["plan", "review", "tdd"]
    text = load_skill("plan", meta_skills=combo[1:])
    # 主工作流（plan）
    assert "方法论：plan" in text
    # 方法论补充（review + tdd）
    assert "方法论补充：review" in text
    assert "方法论补充：tdd" in text


def test_all_meta_skills_count():
    """防御性检查：ALL_META_SKILLS 列表要保持 15 个。"""
    assert len(ALL_META_SKILLS) == 15

"""SKILL.md → system prompt 适配器 — Day 3 尹一帆。

支持业务 skill（仓库内）+ 元 skill（来自 MiMo-Code 上游）。
两者可叠加：业务 skill 作为主工作流，元 skill 作为方法论补充。

参考：
- docs/QuantCode_Design.md §2：MimoCode 的通用 compose skill 是 markdown 文本，引擎无关
- docs/archive/pre-v5/Day3_TaskList.md：历史落地背景
"""
from __future__ import annotations

import re
from pathlib import Path

# 项目根目录（loader.py → skills/ → tools/ → quantcode/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GROUPS_DIR = PROJECT_ROOT / ".opencode" / "groups"

# MimoCode 上游仓库的 skill 路径（与 Mimo-code 内容一致，按 GitHub 仓库名大小写）。
# 实际布局：packages/opencode/src/skill/compose/.bundle（含 src/）。
# 同时保留不含 src/ 的备选，兼容历史布局。
#
# 仓库内受跟踪的 meta-skill 副本（15 个 compose skill，132KB，替代已删除的
# 144MB vendor/mimo-code fork 镜像——见 docs/IMPLEMENTATION_AUDIT.md）。
TRACKED_BUNDLE = PROJECT_ROOT / ".opencode" / "meta-skills"
MIMOCODE_SKILLS_DIR_VENDORED = TRACKED_BUNDLE

_MIMOCODE_BASE = PROJECT_ROOT.parent / "MiMo-Code" / "packages" / "opencode"
_MIMOCODE_BASE_FALLBACK = PROJECT_ROOT.parent / "Mimo-code" / "packages" / "opencode"
MIMOCODE_SKILLS_DIR = _MIMOCODE_BASE / "src" / "skill" / "compose" / ".bundle"
MIMOCODE_SKILLS_DIR_LEGACY = _MIMOCODE_BASE / "skill" / "compose" / ".bundle"

# 备选路径（如果用户克隆成 Mimo-code 小写）
MIMOCODE_SKILLS_DIR_FALLBACK = _MIMOCODE_BASE_FALLBACK / "src" / "skill" / "compose" / ".bundle"
MIMOCODE_SKILLS_DIR_FALLBACK_LEGACY = _MIMOCODE_BASE_FALLBACK / "skill" / "compose" / ".bundle"


def _strip_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter（首两个 --- 之间的内容）。"""
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)


def _find_business_skill(group: str, skill_name: str) -> Path:
    """在 .opencode/groups/<group>/skills/ 下找 SKILL.md。"""
    skill_dir = GROUPS_DIR / group / "skills" / skill_name
    return skill_dir / "SKILL.md"


def _find_meta_skill(skill_name: str) -> Path | None:
    """在 MiMo-Code/.bundle/ 或 Mimo-code/.bundle/ 下找 SKILL.md。

    元 skill 没有 group 概念，单一来源。
    同时检查带 src/ 和不带 src/ 的两种布局。
    """
    for base in (
        MIMOCODE_SKILLS_DIR_VENDORED,          # 优先仓库内受跟踪副本（.opencode/meta-skills）
        MIMOCODE_SKILLS_DIR,
        MIMOCODE_SKILLS_DIR_LEGACY,
        MIMOCODE_SKILLS_DIR_FALLBACK,
        MIMOCODE_SKILLS_DIR_FALLBACK_LEGACY,
    ):
        candidate = base / skill_name / "SKILL.md"
        if candidate.exists():
            return candidate
    return None


def load_skill(
    skill_name: str,
    *,
    group: str | None = None,
    meta_skills: list[str] | None = None,
) -> str:
    """加载 skill markdown 并拼装成 system prompt。

    Args:
        skill_name: 主 skill 名。业务 skill 配 group；元 skill 配 ``skill_name="tdd"`` 等。
        group: 业务 skill 所在组（model / risk / factor / fundamental / options）。
               加载元 skill 时不需要。
        meta_skills: 附加的元 skill 列表，每个会作为方法论补充拼在后面。

    Returns:
        拼装好的 markdown 文本（去掉 frontmatter）。

    Raises:
        FileNotFoundError: 主 skill 文件找不到。

    Examples:
        >>> # 加载业务 skill
        >>> text = load_skill("model-pr-submit", group="model")
        >>> # 加载元 skill（来自 MimoCode）
        >>> text = load_skill("tdd")
        >>> # 业务 + 元叠加
        >>> text = load_skill("pit-rag", group="fundamental", meta_skills=["tdd"])
    """
    parts: list[str] = []

    # 1. 主 skill
    if group is not None:
        # 业务 skill
        path = _find_business_skill(group, skill_name)
        if not path.exists():
            raise FileNotFoundError(
                f"Business skill '{skill_name}' not found for group '{group}' "
                f"(expected at {path})"
            )
        body = _strip_frontmatter(path.read_text(encoding="utf-8"))
        parts.append(f"# 主工作流：{skill_name}\n\n{body}")
    else:
        # 元 skill
        path = _find_meta_skill(skill_name)
        if path is None:
            raise FileNotFoundError(
                f"Meta skill '{skill_name}' not found in MimoCode (.bundle/). "
                f"Checked: {MIMOCODE_SKILLS_DIR}, {MIMOCODE_SKILLS_DIR_FALLBACK}"
            )
        body = _strip_frontmatter(path.read_text(encoding="utf-8"))
        parts.append(f"# 方法论：{skill_name}\n\n{body}")

    # 2. 元 skill 附加
    for m in meta_skills or []:
        mpath = _find_meta_skill(m)
        if mpath is None:
            # 找不到的元 skill 跳过，不阻塞主流程
            continue
        mbody = _strip_frontmatter(mpath.read_text(encoding="utf-8"))
        parts.append(f"\n# 方法论补充：{m}\n\n{mbody}")

    text = "\n\n---\n\n".join(parts)
    # ★ Day 4 俞高磊：追加简短 tool-call 指令
    _call_hint = "\n\n## RULES\n- Call tools. Do not describe them.\n"
    return text + _call_hint


__all__ = [
    "load_skill",
    "PROJECT_ROOT",
    "GROUPS_DIR",
    "MIMOCODE_SKILLS_DIR",
]

"""Memory 路径解析与安全检查 — Day 2 尹一帆（重写）。

严格移植自 MimoCode ``memory/paths.ts``，QuantCode 扩展：
- 加 ``groups`` scope（QuantCode 6 组隔离；MimoCode 对应是 ``cc``）
- Task progress remains nested under ``sessions`` Runtime State; it is not
  exposed as long-term organizational Memory.

API 与 MimoCode 对齐：
- :class:`MemoryLocator` —— ``{scope, scope_id, type, key}``
- :func:`parse_path` —— 解析绝对 / 相对路径
- :func:`build_path` —— 反向构造路径
- :func:`assert_safe_component` —— 拒绝 ``..`` 与前导 ``/``
- :func:`resolve_project_id` —— path 12-char sha256（前缀）

注意与 MimoCode 的差异（QuantCode 扩展部分）：
- ``groups`` 走 ``<root>/.quantcode/groups/<group>/memory/<key>.md`` 路径前缀
- Session task files parse as ``scope="sessions"`` with key
  ``tasks/<tid>/<key>``. They are Runtime State and stay out of Group Memory UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 类型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryLocator:
    """解析后的 memory 路径（结构与 MimoCode ``paths.ts`` MemoryLocator 一致）。"""

    scope: str       # global / projects / groups / sessions / tasks
    scope_id: str    # global 时为空串；其他为对应 id
    type: str        # free / memory / checkpoint / progress / notes / feedback / ...
    key: str         # 文件去除 .md 与 scope/scope_id/type 之后的部分，可含子目录


# ---------------------------------------------------------------------------
# Type 检测（与 MimoCode ``TYPE_PATTERNS`` 1:1）
# ---------------------------------------------------------------------------

# MimoCode 设计要点：
# - 仅 `memory` 是 case-insensitive（兼容 legacy 的 MEMORY.md 重命名迁移）
# - `checkpoint` / `progress` / `notes` 是 exact match（前缀变体也算）
# - `tasks/<id>/progress` / `tasks/<id>/notes` 整体匹配
_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^memory$", re.IGNORECASE),     "memory"),
    (re.compile(r"^memory-",   re.IGNORECASE),   "memory"),
    (re.compile(r"^checkpoint$"),                "checkpoint"),
    (re.compile(r"^checkpoint-"),               "checkpoint"),
    (re.compile(r"^tasks/[^/]+/progress$"),     "progress"),
    (re.compile(r"^tasks/[^/]+/notes$"),        "notes"),
)


def detect_type(key: str) -> str:
    """MimoCode ``detectType`` 的 Python 翻译。fallback 是 ``"free"``。"""
    for pattern, typ in _TYPE_PATTERNS:
        if pattern.match(key):
            return typ
    return "free"


# ---------------------------------------------------------------------------
# 路径解析 —— QuantCode 5-scope flavor
# ---------------------------------------------------------------------------

# MimoCode 的 regex（去掉 `/memory/` 部分作为固定前导）：
#   /\/(global|projects|sessions)(?:\/([^/]+))?\/(.+)\.md$/
# 量化：5 scope + QuantCode 的 `.quantcode/memory/` 前缀（也兼容 `/memory/`）

# QuantCode groups: `<root>/.quantcode/groups/<group>/memory/<key>.md`
# 或更通用：`<root>/groups/<group>/<key>.md`
_RX_QUANTCODE_GROUPS = re.compile(
    r"/groups/(?P<group>[^/]+)/(?P<key>.+)\.md$"
)

# Runtime tasks: `<root>/.quantcode/memory/sessions/<sid>/tasks/<tid>/<key>.md`
_RX_QUANTCODE_TASKS = re.compile(
    r"/(?:[^/]+/)?memory/sessions/(?P<sid>[^/]+)/tasks/(?P<tid>[^/]+)/(?P<key>.+)\.md$"
)

# MimoCode-aligned: global / projects / sessions 走 `.quantcode/memory/<scope>/...`
# scope_id 在 projects / sessions 可选（global 时 idMaybe=None）
_RX_MIMOCODE = re.compile(
    r"/(?:[^/]+/)?memory/(?P<scope>global|projects|sessions)"
    r"(?:/(?P<id>[^/]+))?/(?P<key>.+)\.md$"
)


def parse_path(abs_path: str) -> MemoryLocator | None:
    """解析一个磁盘路径。

    返回 :class:`MemoryLocator` 或 ``None``（路径不匹配任何已知 layout）。

    QuantCode 优先级（先匹配更具体的 scope）：
    1. tasks（`sessions/<sid>/tasks/<tid>/<key>`）
    2. groups（`groups/<group>/<key>`）
    3. global / projects / sessions（统一走 `.quantcode/memory/<scope>/...`）

    Args:
        abs_path: 磁盘绝对路径或项目相对路径（运行时 ``parse_path`` 自动处理
                  cwd 偏移）。Python 端不强制绝对——只要字符串含可识别的尾部
                  layout 段即可解析。

    Returns:
        :class:`MemoryLocator` 或 ``None``。

    Examples (与 MimoCode paths.test.ts 对齐):

        >>> parse_path("/data/memory/global/tooling-prefs.md")
        MemoryLocator(scope='global', scope_id='', type='free', key='tooling-prefs')

        >>> parse_path("/data/memory/projects/uuid-1/memory.md")
        MemoryLocator(scope='projects', scope_id='uuid-1', type='memory', key='memory')

        >>> parse_path("/data/memory/sessions/ses_abc/checkpoint.md")
        MemoryLocator(scope='sessions', scope_id='ses_abc', type='checkpoint', key='checkpoint')

        >>> parse_path("/data/memory/sessions/ses_abc/tasks/T1/progress.md")
        MemoryLocator(scope='sessions', scope_id='ses_abc', type='progress', key='tasks/T1/progress')

        >>> parse_path("/quantcode/groups/factor/memory/foo.md")
        MemoryLocator(scope='groups', scope_id='factor', type='memory', key='foo')

        >>> parse_path("/data/checkpoints/ses_abc/001.md")  # 不是 memory 路径
        None
    """
    if not abs_path:
        return None
    raw = abs_path.replace("\\", "/")

    # 优先级 1：tasks
    m = _RX_QUANTCODE_TASKS.search(raw)
    if m:
        key = m.group("key")
        return MemoryLocator(
            scope="sessions",
            scope_id=m.group("sid"),
            type=detect_type(f"tasks/{m.group('tid')}/{key}"),  # 沿用 MimoCode pattern
            key=f"tasks/{m.group('tid')}/{key}",
        )

    # 优先级 2：groups（QuantCode 扩展）
    m = _RX_QUANTCODE_GROUPS.search(raw)
    if m:
        group = m.group("group")
        key = m.group("key")
        return MemoryLocator(
            scope="groups",
            scope_id=group,
            type=detect_type(key),
            key=key,
        )

    # 优先级 3：MimoCode 的 global / projects / sessions
    m = _RX_MIMOCODE.search(raw)
    if m:
        scope = m.group("scope")
        scope_id = m.group("id") or "" if scope != "global" else ""
        key = m.group("key")
        return MemoryLocator(
            scope=scope,
            scope_id=scope_id,
            type=detect_type(key),
            key=key,
        )

    return None


# ---------------------------------------------------------------------------
# 反向构造（与 MimoCode buildPath 严格对齐）
# ---------------------------------------------------------------------------

def assert_safe_component(value: str) -> None:
    """拒绝 ``..`` 与前导 ``/``（MimoCode ``assertSafeComponent`` 1:1）。

    Raises:
        ValueError: 含 ``..`` segment 或前导 ``/``。
    """
    value = str(value)
    if "\x00" in value:
        raise ValueError(f"buildPath: invalid path component: {value!r}")
    # Normalize Windows separators before checking segments.  Checking only
    # ``/`` lets ``..\\escape`` become ``../escape`` after the final join.
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError(f"buildPath: invalid path component: {value!r}")
    for seg in normalized.split("/"):
        if seg == "..":
            raise ValueError(f"buildPath: invalid path component: {value!r}")


def build_path(
    *,
    root: str,
    scope: str,
    key: str,
    scope_id: str | None = None,
) -> str:
    """反向构造路径。

    QuantCode 调整：
    - global / projects / sessions：走 ``<root>/.quantcode/memory/<scope>/...``
    - groups：``<root>/.quantcode/memory/groups/<scope_id>/<key>.md``

    Args:
        root: 项目根或 .quantcode 根。
        scope: LEGAL_SCOPES 之一。
        key: 文件 key（不含 .md 后缀；可能含子目录如 ``"tasks/T1/progress"``）。
        scope_id: 当 scope ≠ global 时必填。

    Returns:
        拼好的绝对路径。

    Raises:
        ValueError: scope 非法 / scope_id 缺 / segment 非法（含 ``..`` 或前导 ``/``）。
    """
    from .fts import LEGAL_SCOPES

    if scope not in LEGAL_SCOPES:
        raise ValueError(f"buildPath: scope {scope!r} 不在 {LEGAL_SCOPES}")

    # safety
    if scope_id is not None:
        assert_safe_component(scope_id)
    assert_safe_component(key)

    if scope == "global":
        if scope_id:
            raise ValueError("buildPath: global scope 不应传 scope_id")
        parts = [root, ".quantcode", "memory", "global", f"{key}.md"]
    elif scope == "groups":
        if not scope_id:
            raise ValueError("buildPath: groups scope 需要 scope_id")
        parts = [root, ".quantcode", "memory", "groups", scope_id, f"{key}.md"]
    elif scope == "sessions":
        if not scope_id:
            raise ValueError("buildPath: sessions scope 需要 scope_id")
        parts = [root, ".quantcode", "memory", "sessions", scope_id, f"{key}.md"]
    elif scope == "projects":
        if not scope_id:
            raise ValueError("buildPath: projects scope 需要 scope_id")
        parts = [root, ".quantcode", "memory", "projects", scope_id, f"{key}.md"]
    else:
        raise ValueError(f"buildPath: 未实现的 scope {scope!r}")

    # 强制用正斜杠（与 MimoCode path.join 在 POSIX 上的行为一致；Windows 上
    # Path(*parts) 会变成反斜杠，破坏 cross-platform 一致性）
    return "/".join(parts).replace("\\", "/")


# ---------------------------------------------------------------------------
# 项目 id 解析（与 MimoCode resolveProjectId 1:1）
# ---------------------------------------------------------------------------

def resolve_project_id(abs_repo_path: str) -> str:
    """path → 12-char hex（sha256 前 12 位）。

    与 MimoCode 行为一致；同输入同输出、确定性、跨平台一致。
    """
    import hashlib
    return hashlib.sha256(abs_repo_path.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "MemoryLocator",
    "assert_safe_component",
    "build_path",
    "detect_type",
    "parse_path",
    "resolve_project_id",
]

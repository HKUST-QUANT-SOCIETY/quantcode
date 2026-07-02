"""FTS5 查询构造与转义 — Day 2 尹一帆（重写）。

严格 1:1 移植自 MimoCode ``memory/fts-query.ts``。

关键点（MimoCode 注释原文）：
- FTS5 MATCH grammar 自带操作符 / 特殊字符
  （``"``、``(``、``)``、``*``、``:``、``^``、``-``、``.``、``{``、``}``）。
  直接把原始字符串传到 MATCH 会让 parser 崩。每个 token 用 phrase 双引号
  包成 literal-word 即可避开；同时 OR-join 保留高召回率。
- token 类用 ``[\\p{L}\\p{N}_]+`` 一段（Python 用 ``\\w+`` 近似，覆盖
  Unicode 字母 + 数字 + 下划线，对 CJK / Japanese 同样有效）。
- OR（不是 AND）：AND 要求每个 token 都命中，召回极低；OR 让 BM25 按"匹配
  token 数 / 稀有度"排名，caller 再用相对 floor 砍噪音。
- 解析后无 token 返回 ``None``（不是空串），caller 应当成"空查询无结果"，
  不要把 None 送进 SQL。

Public API：
- :func:`build_fts_query` —— 主入口；返回 ``str | None``
"""
from __future__ import annotations

import re


# 1:1 对应 MimoCode fts-query.ts:31：
#     raw.match(/[\p{L}\p{N}_]+/gu)
# Python 标准 `re` 不支持 \p{L}\p{N}；`\w` 在 Python 3 + re.UNICODE（默认）
# 下的行为近似（覆盖 Unicode 字母 + 数字 + `_`），CJK / 平假名 / 汉字全部命中。
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def build_fts_query(raw: str) -> str | None:
    """Build an FTS5 MATCH expression from a free-form user query.

    与 MimoCode 行为完全一致：
    - 空白 / 全控制字符 → ``None``
    - 每个 token 双引号包裹 + OR join
    - FTS5 特殊字符（``"``、``(``、``)``、``*`` 等）当 token 分隔符抛弃

    Args:
        raw: 用户查询字符串。

    Returns:
        FTS5 MATCH 字符串，或 ``None``（无有效 token）。

    Examples (与 MimoCode fts-query.test.ts 9 个用例逐一对齐):

        >>> build_fts_query("hello world")
        '"hello" OR "world"'
        >>> build_fts_query("FOO_bar baz-1")
        '"FOO_bar" OR "baz" OR "1"'
        >>> build_fts_query("金银价格")
        '"金银价格"'
        >>> build_fts_query("価格 2026年")
        '"価格" OR "2026年"'
        >>> build_fts_query("")
        None
        >>> build_fts_query("T5.3 closure")
        '"T5" OR "3" OR "closure"'
        >>> build_fts_query("(foo) bar* baz/qux")
        '"foo" OR "bar" OR "baz" OR "qux"'
        >>> build_fts_query('say "hi"')
        '"say" OR "hi"'
        >>> build_fts_query("foo and bar")
        '"foo" OR "and" OR "bar"'
        >>> build_fts_query("postgres database port 5433")
        '"postgres" OR "database" OR "port" OR "5433"'
    """
    if raw is None:
        return None
    tokens = _TOKEN_RE.findall(raw)
    # MimoCode 原文还要 `.map(t => t.trim()).filter(Boolean)`；
    # Python 的 \w+ 已经 trim 过 empty，且 \w 必 ≥1 char，无需额外过滤。
    # 唯一特例：单一空格输入，``tokens`` 已是空 list。
    if not tokens:
        return None
    # MimoCode: quoted = tokens.map(t => `"${t.replaceAll('"', "")}"`)  ——
    # 内部 `"` 直接删掉，**不**做 FTS5 的转义双写。MimoCode 选择放弃内嵌 `"`，
    # 防止 syntax 错误。我们沿用同样行为。
    quoted = [f'"{t.replace(chr(34), "")}"' for t in tokens]
    return " OR ".join(quoted)


__all__ = ["build_fts_query"]

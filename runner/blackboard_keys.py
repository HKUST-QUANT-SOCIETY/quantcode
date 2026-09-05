"""Blackboard 跨组共享条目的 session/key 归一层（唯一真源，P0-2/A03/A08）。

修复的问题：model→risk 跨组 handoff 的主键 ``(session_id, entry_key)``
两端各自拼装——写侧（write_blackboard）拿 thread_id 当 session_id 且给 key
加 ``shared.model_entries.`` 前缀；读侧（risk read_blackboard / agent_mcp_tool
队列读取）用 ``project_id or DEFAULT_SESSION_ID`` 当 session_id、key 用裸名——
两端永远对不上（runner/blackboard.py:78 的 ``PRIMARY KEY (session_id, entry_key)``）。

归一规则：
- 跨组共享条目统一写 PROJECT scope + 固定 session ``PROJECT_SESSION_ID``；
- model 组产出的条目 key 统一带 ``KEY_MODEL_ENTRY_PREFIX`` 前缀（幂等）；
- 所有写/读侧一律从本模块取常量与帮助函数，禁止各自拼装。

本模块零依赖（不 import schemas / runner），保证任何一侧都能安全引用。
"""
from __future__ import annotations

# 跨组共享条目统一使用的固定 session（与 runner.blackboard.DEFAULT_SESSION_ID 同值，
# 但本模块是唯一真源；blackboard.py 反向引用本常量）。
PROJECT_SESSION_ID = "S0000000000000001"

# risk 组消费的跨组 handoff 队列 key（PROJECT scope）。
KEY_PENDING_RISK_REVIEWS = "shared.pending_risk_reviews"

# model 组写入 PROJECT scope 的条目 key 前缀。
KEY_MODEL_ENTRY_PREFIX = "shared.model_entries."

# 既有共享命名空间前缀：以此为开头的 key 视为完整 key，不再加 model 前缀。
_SHARED_NAMESPACE_PREFIX = "shared."


def make_read_key(key: str) -> str:
    """把条目名归一为跨组共享的完整 entry_key（幂等）。

    规则：
    - 已带 ``shared.model_entries.`` 前缀 → 原样返回；
    - 已在 ``shared.`` 共享命名空间（如 ``shared.pending_risk_reviews``）
      → 视为完整 key，原样返回；
    - 其他裸名（如 ``model_spec``、``model.pr_7_spec``）
      → 补上 ``KEY_MODEL_ENTRY_PREFIX``。
    """
    if key.startswith(KEY_MODEL_ENTRY_PREFIX) or key.startswith(_SHARED_NAMESPACE_PREFIX):
        return key
    return f"{KEY_MODEL_ENTRY_PREFIX}{key}"


def normalize_key(key: str) -> str:
    """读侧 key 归一入口（当前等价 :func:`make_read_key`，未来扩展点）。"""
    return make_read_key(key)


__all__ = [
    "KEY_MODEL_ENTRY_PREFIX",
    "KEY_PENDING_RISK_REVIEWS",
    "PROJECT_SESSION_ID",
    "make_read_key",
    "normalize_key",
]

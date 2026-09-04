"""Shared pytest fixtures for the QuantCode repository.

The repository itself is the import root (``runner/``, ``tools/`` and
``schemas/`` live next to this file).  This used to be a leftover from the
pre-v5 monorepo layout and injected a sibling ``quantcode/`` directory into
``sys.path``.  In a multi-worktree checkout that silently made tests exercise
another worktree's code.  Keep the import path local and deterministic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_path_str = str(_PROJECT_ROOT)
if _path_str not in sys.path:
    # Keep local source ahead of an editable install from another worktree.
    sys.path.insert(0, _path_str)


@pytest.fixture(autouse=True)
def _explicit_test_environment(monkeypatch):
    """Unauthenticated environment fallbacks are legal only in explicit tests."""
    monkeypatch.setenv("QUANTCODE_ENV", "test")


# ---------------------------------------------------------------------------
# Day 4: 真 LLM fixtures（DeepSeek）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def real_llm():
    """会话级 fixture：当 ``QUANTCODE_USE_REAL_LLM=1`` 时创建 DeepSeek LLM。

    用法::

        def test_something(real_llm):
            if real_llm is None:
                pytest.skip("QUANTCODE_USE_REAL_LLM not set")
            result = AgentRunner(group="risk", model=real_llm).run(...)

    Returns:
        DeepSeekAdapter callable，或 None（环境变量未设置 / config.json 不存在）。
    """
    if os.environ.get("QUANTCODE_USE_REAL_LLM", "").strip() != "1":
        return None

    try:
        from runner.llm_provider import create_deepseek_llm

        return create_deepseek_llm()
    except ValueError as e:
        pytest.skip(f"DeepSeek LLM 不可用: {e}")
        return None  # unreachable, but makes type checkers happy


@pytest.fixture
def require_real_llm(real_llm):
    """测试级 fixture：当 real_llm 为 None 时自动 skip 测试。

    用法::

        def test_real_integration(require_real_llm):
            # 到这里 real_llm 一定非 None
            result = AgentRunner(group="risk", model=require_real_llm).run(...)
    """
    if real_llm is None:
        pytest.skip("设置 QUANTCODE_USE_REAL_LLM=1 并配置 config.json 后运行此测试")
    return real_llm

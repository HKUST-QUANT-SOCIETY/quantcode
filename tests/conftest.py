"""Day 2 测试 conftest —— 把 quantcode 项目加进 sys.path。

由于 ``test_codes/day2/`` 在 ``quantcode/`` 之外，pytest 直接从这里跑
时 ``from runner.memory import ...`` 会找不到模块。本 conftest 在
session 启动时把 ``quantcode/`` 根注入 ``sys.path``，让 import 正常工作。

运行（hkust-quant env）：

    # 从含 quantcode/ 与 test_codes/ 的同级目录（即项目根）执行
    cd <PROJECT_ROOT>
    pytest test_codes/day2/ -v

或在 conda 环境激活时：

    conda activate hkust-quant
    pytest <PROJECT_ROOT>/test_codes/day2/test_memory.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# test_codes/day2/conftest.py
# -> test_codes/day2/         (here)
# -> test_codes/              (parent)
# -> <PROJECT_ROOT>/          (项目根，与 quantcode/ 平级)
# -> quantcode/               (the python project we want to import)
_PROJECT_ROOT_FOR_QUANTCODE: Path = Path(__file__).resolve().parent.parent.parent / "quantcode"

# 防御：万一项目目录不存在，不要让 conftest 失败；只把存在的目录放进 sys.path
if _PROJECT_ROOT_FOR_QUANTCODE.is_dir():
    _path_str = str(_PROJECT_ROOT_FOR_QUANTCODE)
    if _path_str not in sys.path:
        # 头插：胜过 site-packages，避免环境里已有的同名 runner 包
        sys.path.insert(0, _path_str)


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

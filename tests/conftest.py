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

import sys
from pathlib import Path

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

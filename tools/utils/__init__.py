"""QuantCode 跨组共享工具。

模块：
- dedupe: 副作用 tool 去重保险栓（@dedupe_within），由陈镇鸿 Day 1 实现
"""

from .dedupe import dedupe_within

__all__ = ["dedupe_within"]
from .paths import safe_filename_component

__all__ = ["safe_filename_component"]

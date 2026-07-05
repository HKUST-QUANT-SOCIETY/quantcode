"""死循环检测 —— Day 3 尹一帆。

实现 LangGraph 编排层的自研运行时加固（架构 §3.2.1）：

- ``LoopDetector`` — 滑动窗口统计相同 (tool_name, args) 调用次数，
                     阈值内重复出现 ``threshold`` 次即判为死循环。

状态指纹（架构 §3.2.3）从 PR #16 (shutong-114) 的 ``runner/routing/fingerprint.py``
**白名单实现** cherry-pick（只算 5 个业务字段：current_step / last_tool /
tool_args / output_data / errors），从源头避开 messages 累积导致指纹永不重复
的问题。本模块不再含 ``state_fingerprint`` 函数。

依赖：仅 stdlib（``collections``、``json``、``typing``），
        不引入 langgraph 或任何 agent 框架，便于单测与复用。

参考：
- Architecture_Spec.md §3.2.1（死循环检测）
- Architecture_Spec.md §3.2.3（状态指纹循环检测，见 ``runner/routing/fingerprint.py``）
"""
from __future__ import annotations

import json
from collections import deque
from typing import Any


# ---------------------------------------------------------------------------
# 模块级常量
# ---------------------------------------------------------------------------

#: ReAct 循环的迭代上限（架构 §3.2.2）。
#: Agent 单次任务的最多步数，超过则强制中止。
MAX_ITERATIONS: int = 100


def _args_to_hashable(args: Any) -> str:
    """把 args 序列化成稳定字符串（用于循环检测的哈希 key）。

    支持嵌套 dict / list / 基本类型；非 JSON 原生类型走 ``default=str``。
    """
    return json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 死循环检测
# ---------------------------------------------------------------------------


class LoopDetector:
    """滑动窗口死循环检测器。

    行为：
    - 维护最近 ``window`` 次调用的签名 ``(tool_name, frozenset(args.items()))``。
    - 每次 ``check`` 先追加新调用，再统计该签名在窗口内出现次数。
    - 当次数 ``>= threshold`` 时返回 ``True``，调用方据此返回 ``"loop"`` 路由。

    特性：
    - ``deque(maxlen=window)`` 自动淘汰最旧记录，无需手动裁剪。
    - ``reset()`` 用于跨任务清空窗口（每次新 build/run 自动调用）。
    - 纯 stdlib，不依赖 langgraph，便于单独单测与替换。
    """

    def __init__(self, window: int = 10, threshold: int = 5) -> None:
        if window <= 0:
            raise ValueError("window must be > 0")
        if threshold <= 0:
            raise ValueError("threshold must be > 0")
        if threshold > window:
            raise ValueError("threshold must be <= window")

        self.window: int = window
        self.threshold: int = threshold
        # deque(maxlen=window) 满了之后自动从左端弹出最旧元素
        self._recent_calls: deque[tuple[str, frozenset]] = deque(maxlen=window)

    def check(self, tool_name: str, args: dict) -> bool:
        """记录本次调用，并判断是否触发死循环。

        参数：
            tool_name: 被调用工具的 id（与 ``ToolDef.id`` 对齐）。
            args:      调用参数字典。

        返回：
            ``True`` 表示窗口内已出现 ``>= threshold`` 次相同 (tool_name, args)；
            ``False`` 表示尚未触发。

        实现：args 用 ``json.dumps(..., sort_keys=True, default=str)`` 序列化成字符串，
        避免嵌套 dict 不可哈希的问题。
        """
        sig = (tool_name, _args_to_hashable(args))
        self._recent_calls.append(sig)
        # deque.count 对相同元素计数；窗口小（<=100）所以 O(n) 完全可接受
        return self._recent_calls.count(sig) >= self.threshold

    def reset(self) -> None:
        """清空历史记录，下一次 ``check`` 重新统计。

        Day 3 评审修复：``AgentRunner.build()`` 入口调用此方法，
        避免跨任务复用 runner 实例时把上一次任务的循环检测窗口带进来。
        """
        self._recent_calls.clear()


__all__ = [
    "MAX_ITERATIONS",
    "LoopDetector",
]
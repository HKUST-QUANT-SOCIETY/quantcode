"""Tests for ``tools.loop_detector`` — 死循环检测 / 状态指纹。

覆盖：
- LoopDetector 在阈值处触发，区分 tool 名 / args 差异；
- 窗口滑动后历史被淘汰，可再次触发；
- ``state_fingerprint`` 对噪音 key 鲁棒，对真实差异敏感，且确定性。
"""
from __future__ import annotations

import pytest

from tools.loop_detector import (
    LoopDetectedError,
    LoopDetector,
    MAX_ITERATIONS,
    StateLoopError,
    state_fingerprint,
)


# ---------------------------------------------------------------------------
# LoopDetector
# ---------------------------------------------------------------------------


def test_loop_detector_triggers_after_threshold() -> None:
    """同一 (tool, args) 连调 5 次，第 5 次返回 True。"""
    detector = LoopDetector(window=10, threshold=5)
    args = {"path": "/tmp/foo.txt", "limit": 10}

    # 前 4 次都不触发
    for i in range(4):
        assert detector.check("read_file", args) is False, f"call #{i + 1} should not trigger"
    # 第 5 次达到阈值
    assert detector.check("read_file", args) is True


def test_loop_detector_different_args_does_not_trigger() -> None:
    """args 不同时永远不会触发，即使调用次数很多。"""
    detector = LoopDetector(window=10, threshold=5)

    for i in range(20):
        # 每次 args 都不同，签名也不同
        assert detector.check("read_file", {"path": f"/tmp/file_{i}.txt"}) is False


def test_loop_detector_different_tools_does_not_trigger() -> None:
    """tool 名不同时永远不会触发，即使 args 一样。"""
    detector = LoopDetector(window=10, threshold=5)
    args = {"pr_number": 123}

    for i in range(20):
        # 每次 tool 名都不同
        assert detector.check(f"tool_{i}", args) is False


def test_loop_detector_resets_after_window_slides() -> None:
    """窗口满后旧调用被淘汰，可再次触发新一轮循环。

    流程：
    1. 调 5 次相同 (触发)；
    2. 调 5 次不同（把窗口里的旧签名全挤出去）；
    3. 再调 5 次相同 → 再次触发。
    """
    detector = LoopDetector(window=5, threshold=5)
    same = {"x": 1}

    # 第 1 阶段：相同调用连调 5 次，第 5 次触发
    for i in range(4):
        assert detector.check("tool_a", same) is False
    assert detector.check("tool_a", same) is True

    # 第 2 阶段：5 次不同 args，把旧 (tool_a, same) 全部挤出窗口
    for i in range(5):
        assert detector.check("tool_a", {"x": i}) is False

    # 第 3 阶段：再连调 5 次相同 args，窗口里全是它，第 5 次触发
    for i in range(4):
        assert detector.check("tool_a", same) is False
    assert detector.check("tool_a", same) is True


def test_loop_detector_reset_clears_history() -> None:
    """``reset()`` 后历史清空，不会立即触发。"""
    detector = LoopDetector(window=10, threshold=5)
    args = {"a": 1}

    # 先调 4 次（不触发）
    for _ in range(4):
        assert detector.check("t", args) is False

    # reset 之后再调 4 次同样签名，仍然不触发
    detector.reset()
    for _ in range(4):
        assert detector.check("t", args) is False

    # 第 5 次才触发（因为 reset 清掉了之前的计数）
    assert detector.check("t", args) is True


# ---------------------------------------------------------------------------
# state_fingerprint
# ---------------------------------------------------------------------------


def test_state_fingerprint_ignores_noisy_keys() -> None:
    """timestamp / step / iterations / thread_id 变化不应影响指纹。"""
    s1 = {"messages": ["hi"], "timestamp": "2026-07-04T10:00:00", "step": 1, "thread_id": "abc"}
    s2 = {"messages": ["hi"], "timestamp": "2026-07-04T10:00:01", "step": 2, "thread_id": "xyz"}

    assert state_fingerprint(s1) == state_fingerprint(s2)


def test_state_fingerprint_differs_on_real_changes() -> None:
    """messages 不同 → 指纹不同。"""
    s1 = {"messages": ["hi"], "blackboard": {"k": "v"}}
    s2 = {"messages": ["bye"], "blackboard": {"k": "v"}}

    assert state_fingerprint(s1) != state_fingerprint(s2)


def test_state_fingerprint_is_deterministic() -> None:
    """同一状态两次调用应返回完全相同的指纹。"""
    state = {"messages": ["a", "b"], "blackboard": {"k": [1, 2, 3]}, "tool_calls": 7}

    fp1 = state_fingerprint(state)
    fp2 = state_fingerprint(state)

    assert fp1 == fp2
    # sha256 hex 长度 = 64
    assert len(fp1) == 64


# ---------------------------------------------------------------------------
# 异常类型 + 模块常量（顺带 smoke test，确保 export 可用）
# ---------------------------------------------------------------------------


def test_exceptions_are_distinct_and_subclass_exception() -> None:
    """两类异常都继承自 Exception 且互不相同。"""
    assert issubclass(LoopDetectedError, Exception)
    assert issubclass(StateLoopError, Exception)
    assert LoopDetectedError is not StateLoopError


def test_max_iterations_constant_default() -> None:
    """架构 §3.2.2 规定的默认上限为 100。"""
    assert MAX_ITERATIONS == 100
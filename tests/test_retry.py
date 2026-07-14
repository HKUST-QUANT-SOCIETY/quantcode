"""LLM 重试机制整体闭环测试 — Day 5 尹一帆。

覆盖:
1. LLM 抖动 3 次后成功 → AgentRunner 跑通 + RetryStats 记录
2. LLM 持续失败超 max_retries → 抛 LLMRetryExhausted,state 保留错误信息
3. 不可重试异常(ValueError)→ 不重试立即抛
4. max_retries=0 → 不重试
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from runner.retry import LLMRetryExhausted, RetryWrapper


# ---------------------------------------------------------------------------
# 1. LLM 抖动后成功
# ---------------------------------------------------------------------------


def test_retry_wrapper_recovers_from_transient_failure():
    """Day 5 #A:LLM 抖动 2 次后第 3 次成功 → RetryWrapper 跑通。

    走整体逻辑闭环:用 RetryWrapper 包一个会抖动的 mock LLM,
    调 RetryWrapper.__call__ → 验证最终拿到 AIMessage 且 call_count=3。
    """
    call_count = {"n": 0}

    class _FlakyLLM:
        def __call__(self, messages, tools=None):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("API 抖动 mock")
            return AIMessage(content="ok")

    wrapped = RetryWrapper(_FlakyLLM(), max_retries=3, base_delay=0.0)
    result = wrapped(messages=[])

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert call_count["n"] == 3, f"应调 3 次,实际 {call_count['n']}"
    assert wrapped.stats.total_calls == 3
    assert wrapped.stats.retry_count == 2
    assert wrapped.stats.success_after_retry is True


# ---------------------------------------------------------------------------
# 2. LLM 持续失败
# ---------------------------------------------------------------------------


def test_retry_wrapper_raises_after_max_retries_exhausted():
    """Day 5 #A:LLM 持续失败超 max_retries → 抛 LLMRetryExhausted。

    验证异常类 + 原异常链 + stats 记录。
    """
    class _AlwaysFails:
        def __call__(self, messages, tools=None):
            raise TimeoutError("持续超时 mock")

    wrapped = RetryWrapper(_AlwaysFails(), max_retries=2, base_delay=0.0)

    with __import__("pytest").raises(LLMRetryExhausted) as exc_info:
        wrapped(messages=[])

    # 异常链里包含原 TimeoutError
    assert isinstance(exc_info.value.__cause__, TimeoutError)
    # 记录最后一次的异常信息
    assert wrapped.stats.total_calls == 3  # 初次 + 2 次重试
    assert wrapped.stats.retry_count == 2
    assert wrapped.stats.success_after_retry is False


# ---------------------------------------------------------------------------
# 3. 不可重试异常
# ---------------------------------------------------------------------------


def test_retry_wrapper_does_not_retry_value_error():
    """Day 5 #A:ValueError 等业务异常不重试(避免掩盖真实错误)。

    走整体逻辑闭环:抛 ValueError → 立即向上抛 → stats 只记录 1 次。
    """
    import pytest

    class _BadArgs:
        def __call__(self, messages, tools=None):
            raise ValueError("参数错了")

    wrapped = RetryWrapper(_BadArgs(), max_retries=5, base_delay=0.0)

    with pytest.raises(ValueError, match="参数错了"):
        wrapped(messages=[])

    assert wrapped.stats.total_calls == 1
    assert wrapped.stats.retry_count == 0


# ---------------------------------------------------------------------------
# 4. max_retries=0 不重试
# ---------------------------------------------------------------------------


def test_retry_wrapper_max_retries_zero():
    """Day 5 #A:max_retries=0 → 不重试,失败立即抛 LLMRetryExhausted。

    验证 max_retries=0 的边界行为。
    """
    import pytest

    class _AlwaysFails:
        def __call__(self, messages, tools=None):
            raise ConnectionError("mock")

    wrapped = RetryWrapper(_AlwaysFails(), max_retries=0, base_delay=0.0)

    with pytest.raises(LLMRetryExhausted):
        wrapped(messages=[])
    assert wrapped.stats.total_calls == 1
    assert wrapped.stats.retry_count == 0
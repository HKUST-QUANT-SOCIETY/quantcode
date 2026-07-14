"""LLM 重试机制 — Day 5 尹一帆。

包装用户传入的 LLM ``model`` 调用,遇到可重试异常自动退避重试。

可重试异常(白名单):
- ``ConnectionError`` —— 网络抖动
- ``TimeoutError`` —— 超时
- ``openai.APIError`` —— OpenAI 系列 API 错误(可选依赖,未装则跳过)
- ``openai.APITimeoutError`` —— OpenAI 超时(可选依赖)

不可重试异常(其他)→ 立即向上抛,不重试(避免掩盖真实错误)。

设计要点:
- 通过 ``RetryWrapper(model, max_retries=3)`` 包装,不侵入 AgentRunner 内部
- 暴露 ``stats`` 属性供 IDE / 监控读:total_calls / retry_count / success_after_retry
- ``base_delay`` 用于指数退避,默认 0.5 秒(测试时设 0.0)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 可选依赖:OpenAI 错误类型
# ---------------------------------------------------------------------------

try:
    from openai import APIError, APITimeoutError  # type: ignore

    _OPENAI_ERRORS = (APIError, APITimeoutError)
except ImportError:  # pragma: no cover
    _OPENAI_ERRORS = ()

#: 可重试异常白名单
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
) + _OPENAI_ERRORS


# ---------------------------------------------------------------------------
# 异常类型
# ---------------------------------------------------------------------------


class LLMRetryExhausted(Exception):
    """LLM 重试用尽后抛出。

    ``__cause__`` 保留最后一次的原始异常。
    """

    def __init__(self, message: str, *, attempts: int, last_error: BaseException):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


@dataclass
class RetryStats:
    """RetryWrapper 运行统计。"""

    total_calls: int = 0
    retry_count: int = 0
    success_after_retry: bool = False
    last_error: str = ""


# ---------------------------------------------------------------------------
# RetryWrapper
# ---------------------------------------------------------------------------


class RetryWrapper:
    """包装 LLM 调用,自动重试可恢复的异常。

    用法::

        wrapped = RetryWrapper(model, max_retries=3)
        result = wrapped(messages=[...], tools=[...])
        # result 同 model(...) 原签名返回

    Args:
        model: 被包装的 LLM,签名 ``(messages, tools=None) -> AIMessage``
        max_retries: 最大重试次数(不含初次),默认 3
        base_delay: 退避基数(秒),实际延迟 = base_delay * 2^retry_count
        retryable: 可重试异常白名单(测试时可注入)
    """

    def __init__(
        self,
        model: Callable[..., Any],
        *,
        max_retries: int = 3,
        base_delay: float = 0.5,
        retryable: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if base_delay < 0:
            raise ValueError("base_delay must be >= 0")
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.retryable = retryable if retryable is not None else RETRYABLE_EXCEPTIONS
        self.stats = RetryStats()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """包装调用,自动重试。"""
        last_error: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            self.stats.total_calls += 1
            try:
                result = self.model(*args, **kwargs)
                if attempt > 0:
                    self.stats.success_after_retry = True
                return result
            except self.retryable as e:
                last_error = e
                self.stats.last_error = f"{type(e).__name__}: {e}"
                # 已用尽重试机会 → 不再重试,记 0 retry_count 直接抛
                if attempt >= self.max_retries:
                    break
                # 还有重试机会 → 记一次 retry,等退避后重试
                self.stats.retry_count += 1
                if self.base_delay > 0:
                    # 指数退避:base_delay * 2^retry_count
                    time.sleep(self.base_delay * (2 ** self.stats.retry_count))
                continue

        # 重试用尽
        assert last_error is not None
        raise LLMRetryExhausted(
            f"LLM call failed after {self.max_retries + 1} attempts: "
            f"{type(last_error).__name__}: {last_error}",
            attempts=self.max_retries + 1,
            last_error=last_error,
        ) from last_error


__all__ = [
    "LLMRetryExhausted",
    "RetryWrapper",
    "RetryStats",
    "RETRYABLE_EXCEPTIONS",
]
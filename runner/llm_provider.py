"""LLM Provider 适配器 — Day 4 尹一帆。

把 DeepSeek API（OpenAI 兼容）包装成 AgentRunner 需要的 ``model`` 签名：
``(messages: list[BaseMessage], tools: list[ToolDef] | None) -> AIMessage``。

用法::

    from runner.llm_provider import create_deepseek_llm

    llm = create_deepseek_llm()  # 从 config.json 读取配置
    runner = AgentRunner(group="risk", model=llm, ...)

    # 或手动传参：
    llm = create_deepseek_llm(api_key="sk-...", model="deepseek-chat")

设计要点：
- DeepSeek API 与 OpenAI 完全兼容，用 ``langchain-openai`` 的 ``ChatOpenAI``
- ``bind_tools()`` 把 ToolDef 列表转成 OpenAI function calling 格式
- 返回的 ``AIMessage`` 包含 ``tool_calls`` 字段，与 LangChain 兼容
"""
from __future__ import annotations

import os
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from runner.llm_config import get_llm_config
from tools.registry import ToolDef
from tools.schema_utils import tool_def_to_openai_function


def create_deepseek_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Callable[[list[BaseMessage], list[ToolDef] | None], AIMessage]:
    """创建 DeepSeek LLM 适配器，返回与 AgentRunner 兼容的 callable。

    优先级：显式参数 > config.json > 默认值。

    Args:
        api_key: DeepSeek API key。若为 None，从 config.json 或 DEEPSEEK_API_KEY 环境变量读取。
        model: 模型名。默认 ``"deepseek-chat"``。
        base_url: API 地址。默认 ``"https://api.deepseek.com/v1"``。
        temperature: 温度参数。默认 0.0（确定性输出）。
        max_tokens: 最大输出 token。默认 4096。

    Returns:
        Callable ``(messages, tools=None) -> AIMessage``，可直接传给 AgentRunner。

    Raises:
        ValueError: 没有可用的 API key（config.json 不存在且 DEEPSEEK_API_KEY 未设置）。
    """
    # 从 config.json 加载（runner-direct fallback）；MCP 注入的统一环境
    # 变量优先，避免工具链使用另一套凭据/模型配置。
    cfg = get_llm_config() or {}

    resolved_api_key = (
        api_key
        or os.environ.get("QUANTCODE_API_KEY", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        or cfg.get("api_key", "")
    )
    if not resolved_api_key or resolved_api_key == "sk-your-deepseek-api-key-here":
        raise ValueError(
            "DeepSeek API key 未配置。请：\n"
            "1. 复制 config.example.json 为 config.json\n"
            "2. 填入你的 DeepSeek API key\n"
            "3. 或设置环境变量 DEEPSEEK_API_KEY"
        )

    resolved_model = (
        model
        or os.environ.get("QUANTCODE_MODEL_NAME", "").strip()
        or os.environ.get("DEEPSEEK_MODEL", "").strip()
        or cfg.get("model", "deepseek-chat")
    )
    resolved_base_url = (
        base_url
        or os.environ.get("QUANTCODE_MODEL_BASE_URL", "").strip()
        or os.environ.get("DEEPSEEK_BASE_URL", "").strip()
        or cfg.get("base_url", "https://api.deepseek.com/v1")
    )
    resolved_temperature = temperature if temperature is not None else cfg.get("temperature", 0.0)
    resolved_max_tokens = max_tokens if max_tokens is not None else cfg.get("max_tokens", 4096)

    chat_openai = ChatOpenAI(
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        temperature=resolved_temperature,
        max_tokens=resolved_max_tokens,
    )

    return DeepSeekAdapter(chat_openai)


class DeepSeekAdapter:
    """把 ChatOpenAI 包装成 AgentRunner 需要的 ``(messages, tools) -> AIMessage`` 签名。

    ``ChatOpenAI.bind_tools()`` 需要 OpenAI function calling 格式的 tool 列表，
    本适配器在每次调用时动态 bind（因为不同 run 可能用不同 tool 集合）。
    """

    def __init__(self, chat_openai: ChatOpenAI) -> None:
        self._llm = chat_openai

    def __call__(
        self,
        messages: list[BaseMessage],
        tools: list[ToolDef] | None = None,
    ) -> AIMessage:
        """调 DeepSeek LLM，返回 AIMessage。

        Args:
            messages: LangChain BaseMessage 列表（SystemMessage / HumanMessage / AIMessage / ToolMessage）。
            tools: ToolDef 列表。为 None 或空列表时，LLM 不产生 tool_calls。

        Returns:
            AIMessage，可能含 ``tool_calls`` 字段。
        """
        if tools:
            openai_tools = [tool_def_to_openai_function(t) for t in tools]
            llm_with_tools = self._llm.bind_tools(openai_tools)
        else:
            llm_with_tools = self._llm

        return llm_with_tools.invoke(messages)


__all__ = ["create_deepseek_llm", "DeepSeekAdapter"]

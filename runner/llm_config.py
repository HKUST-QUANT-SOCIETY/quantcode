"""LLM 配置加载模块 — Day 4 尹一帆。

从 ``config.json`` 读取 LLM 配置，支持环境变量覆盖。
``config.json`` 不入库（已在 ``.gitignore`` 中排除），
``config.example.json`` 作为模板提交。

用法::

    from runner.llm_config import get_llm_config

    cfg = get_llm_config()
    if cfg is None:
        print("config.json 不存在，请从 config.example.json 复制并填入 API key")
    else:
        print(f"Provider: {cfg['provider']}, Model: {cfg['model']}")

环境变量优先级（高到低）：
1. ``DEEPSEEK_API_KEY`` — 直接覆盖 api_key
2. ``config.json`` 中的 ``llm.api_key``
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# config.json 在项目根目录（quantcode/），本文件在 runner/ 下
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.json"


def get_llm_config() -> dict[str, Any] | None:
    """从 ``config.json`` 读取 LLM 配置，不存在时返回 None。

    环境变量 ``DEEPSEEK_API_KEY`` 会覆盖 ``config.json`` 中的 ``api_key``。

    Returns:
        dict 含 provider / api_key / model / base_url / temperature / max_tokens，
        或 None（config.json 不存在或解析失败）。
    """
    if not _CONFIG_PATH.exists():
        return None

    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    llm = data.get("llm", {})
    if not isinstance(llm, dict):
        return None

    cfg: dict[str, Any] = {
        "provider": llm.get("provider", "deepseek"),
        "api_key": llm.get("api_key", ""),
        "model": llm.get("model", "deepseek-chat"),
        "base_url": llm.get("base_url", "https://api.deepseek.com/v1"),
        "temperature": float(llm.get("temperature", 0.0)),
        "max_tokens": int(llm.get("max_tokens", 4096)),
    }

    # 环境变量覆盖
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        cfg["api_key"] = env_key

    return cfg


__all__ = ["get_llm_config"]
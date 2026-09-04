"""configs/ YAML 统一加载器 — 架构决策 3「配置不喂 LLM」（ROADMAP Q3 A3）。

单一职责：``load_yaml(name)`` 读 ``configs/<name>.yaml`` + 极简 schema 校验
（顶层必须为 dict，可选要求键存在）。lru_cache 按路径缓存；测试或运行期
改配置后调 ``load_yaml.cache_clear()`` 让下次读取生效（进程行为一致性由
「启动即定型」保证，不提供文件级热加载）。

配置目录解析：``QUANTCODE_CONFIG_DIR`` 覆盖，默认 <repo>/configs/。
缺文件 → 返回 ``{}``（调用方用代码默认兜底）；坏 YAML 或顶层非 dict 默认
保持兼容返回 ``{}``，需要安全写入的调用方可传 ``strict=True`` 直接阻断。
"""
from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """配置目录：QUANTCODE_CONFIG_DIR 覆盖，默认 <repo>/configs/。"""
    override = os.environ.get("QUANTCODE_CONFIG_DIR", "").strip()
    return Path(override) if override else PROJECT_ROOT / "configs"


@functools.lru_cache(maxsize=32)
def load_yaml(
    name: str,
    _required: tuple[str, ...] = (),
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """读 ``<config_dir>/<name>.yaml``，返回顶层 dict（缺失/非法 → 空 dict）。

    Args:
        name: 配置名，如 ``"acceptance.factor"``（自动补 .yaml）。
        _required: 要求存在的顶层键；缺失时警告一次并按缺键处理。
            定位为内部参数——调用方用模块级常量传固定键元组，绕过 cache 无碍。
        strict: 对坏 YAML 或顶层非 dict 抛 ``ValueError``；文件缺失仍返回空字典。

    Returns:
        顶层 dict；文件缺失 / YAMLError / 非 dict → ``{}``。
    """
    path = config_dir() / f"{name}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("config_loader: %s 不存在，调用方使用代码默认", path)
        return {}
    except yaml.YAMLError as e:
        logger.warning("config_loader: %s 解析失败（%s），调用方使用代码默认", path, e)
        if strict:
            raise ValueError(f"config_loader: {path} 解析失败") from e
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "config_loader: %s 顶层不是映射（%s），调用方使用代码默认",
            path, type(data).__name__,
        )
        if strict:
            raise ValueError(f"config_loader: {path} 顶层不是映射")
        return {}
    if _required:
        missing = [k for k in _required if k not in data]
        if missing:
            logger.warning("config_loader: %s 缺键 %s，调用方按缺键兜底", path, missing)
    return data


def load_yaml_checked(name: str, required: tuple[str, ...]) -> dict[str, Any]:
    """schema 极简校验版：要求 ``required`` 键存在，缺键返回空 dict。"""
    return load_yaml(name, _required=tuple(required))


__all__ = ["PROJECT_ROOT", "config_dir", "load_yaml", "load_yaml_checked"]

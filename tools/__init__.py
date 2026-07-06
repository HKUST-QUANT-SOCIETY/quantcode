"""QuantCode 工具层 — Day 3 尹一帆。

本包分层：
- ``tools.registry``     — ToolDef / ToolRegistry / 按组过滤 / load_group_config
- ``tools.loop_detector`` — 死循环检测 / 状态指纹（架构 §3.2.1、§3.2.3）
- ``tools.skills``        — SKILL.md → system prompt 适配器（业务 + 元 skill）
- ``tools.<group>``       — 各组 tool 实现（model / risk / factor / fundamental / options）
- ``tools.utils``         — 跨组共享工具（dedupe 等，由陈镇鸿 Day 1 实现）

调用约定：所有 LangGraph Agent 通过 ``tools.registry.registry`` 单例获取 tool，
不要直接 import ``tools.model.read_pr`` 等具体模块。
"""
from __future__ import annotations

__all__ = []
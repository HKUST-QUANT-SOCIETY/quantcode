"""runner/distill — P-07 组织资产蒸馏管线（能力卡片 / 权限 Mask / 常驻摘要）。

模块一览：
- :mod:`cards`  — 卡片加载（configs/capabilities.yaml 单源）+ group 可见过滤（Mask）
                  + Memory scope 映射 + ``list_capabilities`` 元工具注册；
- :mod:`inject` — 常驻目录摘要生成与 system prompt 注入（run 指令组装 seam）。

两层投放（F-04）：**目录摘要常驻组上下文**（每次 run 可见，强保证）
+ **细节走 FTS 检索**（弱保证，落属组 ``groups`` scope，复用 Memory GROUP 隔离）。
"""
from runner.distill import cards, governance, inject  # noqa: F401

__all__ = ["cards", "governance", "inject"]

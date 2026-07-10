"""dream package — Day 4 尹一帆。

扫 execution trace → LLM 提取 → 写 memory。
入口:``dream.dream_prototype.run_dream(...)``。

不在 ``runner/``(那是引擎层)也不在 ``tools/``(那是 LLM 决策工具),
Dream 是"元任务"——跨 runner/tools/memory,顶级 package 最自然。
"""

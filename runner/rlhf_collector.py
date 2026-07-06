"""RLHF 接入点 — Day 3 Agent 引擎。

依据架构规范 §3.2.4，本模块记录 Agent 在每次交互中的
``(state, action, reward)`` 元组到 JSONL 文件，供后续 RLHF 训练使用。

设计要点（Day 3 决策）：
- 单条追加 + 每写一次 ``flush()``，避免崩溃时丢失数据（Day 3 简单优先）
- state / action / reward 由调用方提供；state 可能含 LangChain ``BaseMessage``
  之类不可直接 JSON 序列化对象，故提供 :func:`_make_serializable` 递归转换
- 线程安全：Day 3 agent loop 单线程调用即可；后续若需并发可加 :class:`threading.Lock`
- 父目录不存在时自动创建，与 :mod:`runner.memory.fts` 风格一致
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Day 3 评审修复（🟡#5e）：每条 ``record()`` 都 flush，
# 保留逐条强制 flush 的语义，移除简化为 1 的阈值常量与计数器。


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------

def _make_serializable(obj: Any) -> Any:
    """递归地把 ``obj`` 转换为可 JSON 序列化的结构。

    处理三类常见的非 JSON-safe 对象（Agent state 经常混入）：

    - **LangChain BaseMessage 实例** → 取出 ``content`` 属性（字符串）
    - **datetime / date** → ``isoformat()`` 字符串
    - **其他对象** → 退化为 ``str(obj)``，避免 :class:`TypeError`

    字典与列表会被递归处理；其余基本类型（int / float / bool / str / None）原样返回。

    提示：判定 ``BaseMessage`` 用鸭子类型（``content`` 属性 + 类名含 ``Message``），
    避免对 langchain 包的硬依赖。
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_make_serializable(v) for v in obj]

    # LangChain BaseMessage 鸭子类型判定（不引入 langchain 依赖）
    cls = type(obj)
    cls_name = cls.__name__
    if cls_name.endswith("Message") and hasattr(obj, "content"):
        return _make_serializable(getattr(obj, "content"))

    # numpy / pandas 等可能附带 .tolist() / .to_dict()
    if hasattr(obj, "tolist") and callable(obj.tolist):
        try:
            return _make_serializable(obj.tolist())
        except Exception:
            pass

    return str(obj)


def _json_default(obj: Any) -> Any:
    """``json.dumps(default=...)`` 兜底回调 —— 调用 :func:`_make_serializable`。"""
    return _make_serializable(obj)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class RLHFCollector:
    """将 ``(state, action, reward)`` 元组追加写入 JSONL 文件。

    每条记录一行 JSON，结构为::

        {"timestamp": <epoch_seconds>, "state": ..., "action": ..., "reward": ...}

    使用示例::

        collector = RLHFCollector(".quantcode/rlhf_data.jsonl")
        collector.record(state={"messages": [...]}, action={"tool": "..."}, reward=1.0)
        collector.close()

    也可作为上下文管理器::

        with RLHFCollector(path) as c:
            c.record(state, action, reward)

    线程安全：
        **非线程安全**。Day 3 agent loop 单线程调用；若日后需要并发访问，请自行加锁
        或每线程一个实例。
    """

    def __init__(self, output_path: str | Path = ".quantcode/rlhf_data.jsonl") -> None:
        """初始化 collector，打开目标文件（append 模式）。

        Args:
            output_path: JSONL 文件路径，默认 ``.quantcode/rlhf_data.jsonl``。
                         父目录不存在会自动创建。
        """
        self._path: Path = Path(output_path)
        # 父目录自动创建 —— 与 runner/memory/fts.py 风格一致
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" 保证 Windows 下不插入多余 \r —— json.dumps 已写入 \n
        self._fp = open(self._path, "a", encoding="utf-8", newline="")

    # -- 写入 --------------------------------------------------------------

    def record(self, state: dict, action: dict, reward: float) -> None:
        """追加单条 ``(state, action, reward)`` 记录到 JSONL 文件。

        写入后立即 ``flush()``，避免进程崩溃时丢数据。

        Args:
            state:  agent 决策时的状态快照；可为任意嵌套 dict（不可 JSON 序列化的
                    值会被 :func:`_make_serializable` 转换）。
            action: agent 选择的动作描述。
            reward: 该次决策的奖励值（float）。
        """
        entry = {
            "timestamp": time.time(),
            "state": _make_serializable(state),
            "action": _make_serializable(action),
            "reward": float(reward),
        }
        line = json.dumps(entry, ensure_ascii=False, default=_json_default)
        self._fp.write(line + "\n")
        # 每条立即 flush，避免进程崩溃时丢数据（Day 3 简单优先）
        self._fp.flush()

    # -- 生命周期 ----------------------------------------------------------

    def close(self) -> None:
        """关闭文件句柄（幂等）。"""
        fp = getattr(self, "_fp", None)
        if fp is not None and not fp.closed:
            try:
                fp.flush()
            except Exception:
                pass
            fp.close()

    def __enter__(self) -> "RLHFCollector":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        # 防止句柄泄漏；__close 自身已做幂等保护
        try:
            self.close()
        except Exception:
            pass


__all__ = [
    "RLHFCollector",
]

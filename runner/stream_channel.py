"""run_id → JSONL 事件通道 — attach_stream（控制器中途读执行轨迹）。

架构一句话：**文件即通道** — 每次 attach_stream=true 的 start run 把
``AgentRunner.stream()`` 的 execution_trace 事件逐条 append 到
``.quantcode/streams/<run_id>.jsonl``（run_id = thread_id，与 evidence.jsonl
同款命名），控制器用 ``read_from(run_id, cursor)`` 按行偏移增量消费。

- 游标 = 行偏移（0 起）；读不重复不丢，``next_cursor`` 直接回传即可续读。
- 文件缺失（未 attach / run 已清理）→ ``exists=False`` 空返回，不抛错。
- 进程内 registry（dict + threading.Lock，parallel_registry 同款）记
  StreamChannel 单例，防同 run_id 多开句柄交叉清空。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from runner.langgraph_base import PROJECT_ROOT  # 复用同一仓库根判定（.quantcode 的锚点）

STREAMS_DIR = PROJECT_ROOT / ".quantcode" / "streams"


class StreamChannel:
    """一个 run_id 的 append-only JSONL 通道。"""

    def __init__(self, run_id: str, path: Path) -> None:
        self.run_id = run_id
        self.path = path

    def emit(self, event: dict) -> None:
        """append 一行 JSON。失败静默 — 通道是旁路，不能砸主流程。"""
        # ponytail: 旁路 emit 失败静默（evidence 同款 best-effort）；若上游需要
        # 硬保证，换 O_APPEND + fdatasync 并抛错重试。
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass


def open_stream(run_id: str) -> StreamChannel:
    """创建/清空 ``.quantcode/streams/<run_id>.jsonl``，返回通道（幂等）。"""
    STREAMS_DIR.mkdir(parents=True, exist_ok=True)
    path = STREAMS_DIR / f"{run_id}.jsonl"
    path.write_text("", encoding="utf-8")
    return StreamChannel(run_id, path)


def read_from(run_id: str, cursor: int = 0) -> dict:
    """读 ``.quantcode/streams/<run_id>.jsonl`` 第 cursor 行起的全部事件。

    Returns:
        {"events": [...], "next_cursor": int, "exists": bool}
        next_cursor = 新的行偏移；events 里每条带隐式序号 =
        cursor + 索引（通道契约按行对齐，事件本身不注入字段）。
    """
    path = STREAMS_DIR / f"{run_id}.jsonl"
    if not path.is_file():
        return {"events": [], "next_cursor": int(cursor), "exists": False}
    # ponytail: 全文件读取后切片 — 单 run 事件量级 ~几十行，O(n) 足够；
    # 若涨到大文件再换 seek 按行偏移。
    lines = path.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines[int(cursor):]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"events": events, "next_cursor": len(lines), "exists": True}


# 进程内 registry：run_id → StreamChannel。open_stream 记账，防同 run_id
# 重复 open 交叉清空（parallel_registry 同款 dict + Lock 模式）。
_registry_lock = threading.Lock()
_registry: dict[str, StreamChannel] = {}


def get_or_open(run_id: str) -> StreamChannel:
    """registry 命中复用，未命中走 open_stream（清空首次创建的文件）。"""
    with _registry_lock:
        ch = _registry.get(run_id)
        if ch is None:
            ch = open_stream(run_id)
            _registry[run_id] = ch
        return ch


def stream_exists(run_id: str) -> bool:
    """该 run_id 是否已有通道文件（控制器决定 attach 与否的快速检查）。"""
    return (STREAMS_DIR / f"{run_id}.jsonl").is_file()


__all__ = [
    "StreamChannel",
    "STREAMS_DIR",
    "open_stream",
    "read_from",
    "get_or_open",
    "stream_exists",
]
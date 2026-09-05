"""run_id → JSONL 事件通道 — attach_stream（控制器中途读执行轨迹）。

架构一句话：**文件即通道** — 每次 attach_stream=true 的 start run 把
``AgentRunner.stream()`` 的 execution_trace 事件逐条 append 到
``.quantcode/streams/<run_id>.jsonl``（run_id = thread_id，与 evidence.jsonl
同款命名），控制器用 ``read_from(run_id, cursor)`` 按行偏移增量消费。

- 游标 = 行偏移（0 起）；读不重复不丢，``next_cursor`` 直接回传即可续读。
- 文件缺失（未 attach / run 已清理）→ ``exists=False`` 空返回，不抛错。
- 进程内 registry（dict + threading.Lock，parallel_registry 同款）记
  StreamChannel 单例，复用同 run_id 的通道。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from runner.langgraph_base import PROJECT_ROOT  # 复用同一仓库根判定（.quantcode 的锚点）

STREAMS_DIR = PROJECT_ROOT / ".quantcode" / "streams"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_run_id(run_id: str) -> str:
    """Validate the opaque run id before using it as a filename component."""
    value = str(run_id or "")
    if not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError("run_id must be an opaque identifier using letters, digits, '.', '_' or '-'")
    return value


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
    """创建/重开 ``.quantcode/streams/<run_id>.jsonl``，返回通道（幂等）。"""
    run_id = _validate_run_id(run_id)
    STREAMS_DIR.mkdir(parents=True, exist_ok=True)
    path = STREAMS_DIR / f"{run_id}.jsonl"
    path.touch(exist_ok=True)
    return StreamChannel(run_id, path)


def read_from(run_id: str, cursor: int = 0) -> dict:
    """读 ``.quantcode/streams/<run_id>.jsonl`` 第 cursor 行起的全部事件。

    Returns:
        {"events": [...], "next_cursor": int, "exists": bool}
        next_cursor = 新的行偏移；events 里每条带隐式序号 =
        cursor + 索引（通道契约按行对齐，事件本身不注入字段）。
    """
    run_id = _validate_run_id(run_id)
    if cursor < 0:
        raise ValueError("cursor must be non-negative")
    path = STREAMS_DIR / f"{run_id}.jsonl"
    if not path.is_file():
        return {"events": [], "next_cursor": int(cursor), "exists": False}
    events = []
    next_cursor = 0
    # Consume complete lines only: an in-flight append must remain readable on
    # the next poll rather than advancing the cursor past an incomplete event.
    with path.open("rb") as source:
        for index, line in enumerate(source):
            if not line.endswith(b"\n"):
                break
            next_cursor = index + 1
            if index < cursor:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    return {"events": events, "next_cursor": max(cursor, next_cursor), "exists": True}



# 进程内 registry：run_id → StreamChannel，文件在进程退出后仍可重开。
_registry_lock = threading.Lock()
_registry: dict[str, StreamChannel] = {}


def get_or_open(run_id: str) -> StreamChannel:
    """registry 命中复用，未命中重开持久文件，保留进程退出前的事件。"""
    run_id = _validate_run_id(run_id)
    with _registry_lock:
        ch = _registry.get(run_id)
        if ch is None:
            ch = open_stream(run_id)
            _registry[run_id] = ch
        return ch


def stream_exists(run_id: str) -> bool:
    """该 run_id 是否已有通道文件（控制器决定 attach 与否的快速检查）。"""
    run_id = _validate_run_id(run_id)
    return (STREAMS_DIR / f"{run_id}.jsonl").is_file()


__all__ = [
    "StreamChannel",
    "STREAMS_DIR",
    "open_stream",
    "read_from",
    "get_or_open",
    "stream_exists",
]

"""Dream 后台调度器 — Day 5 尹一帆。

守护线程 + ``threading.Event.wait`` 实现,不引入 APScheduler 等额外依赖。

用法::

    scheduler = DreamScheduler(interval=300, ...)
    scheduler.start()
    # ... 后台跑 ...
    scheduler.stop()  # 优雅停机

设计要点:
- 守护线程,主进程退出时自动结束(不阻塞 shutdown)
- ``stop()`` 幂等,可多次调用
- 单次 ``trigger_dream()`` 异常不杀死线程,stderr 打印后继续
- 用 ``Event.wait`` 替代 ``time.sleep``,可被 stop() 立即唤醒
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable


class DreamScheduler:
    """Dream 后台调度器(守护线程)。"""

    def __init__(
        self,
        interval: int = 300,
        *,
        rlhf_path: str | Path = ".quantcode/rlhf_data.jsonl",
        memory_root: str | Path = ".quantcode",
        event_sink: Path | Callable[[dict], None] | None = None,
        llm_mode: str = "auto",
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        self.interval = interval
        self.rlhf_path = rlhf_path
        self.memory_root = memory_root
        self.event_sink = event_sink
        self.llm_mode = llm_mode
        self.on_error = on_error
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """启动后台线程(已启动则不重复)。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="dream-scheduler",
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """停止调度器(幂等)。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        """守护线程主循环。"""
        from dream.trigger import trigger_dream  # 延迟 import

        while not self._stop_event.is_set():
            try:
                trigger_dream(
                    rlhf_path=self.rlhf_path,
                    memory_root=self.memory_root,
                    event_sink=self.event_sink,
                    llm_mode=self.llm_mode,
                )
            except Exception as e:
                if self.on_error is not None:
                    self.on_error(e)
                else:
                    print(
                        f"[dream-scheduler] 触发失败: {type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
            # 用 Event.wait 替代 time.sleep,可被 stop() 立即唤醒
            if self._stop_event.wait(timeout=self.interval):
                break


__all__ = ["DreamScheduler"]
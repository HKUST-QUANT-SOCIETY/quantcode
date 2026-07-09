"""Dream CLI 入口 — Day 5 尹一帆。

用法::

    # 跑一次
    python -m dream.cli --once

    # 定时跑(每 N 秒)
    python -m dream.cli --interval 300

参数透传给 ``trigger_dream()``。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dream: 扫 trace 提取 memory")
    parser.add_argument(
        "--once", action="store_true",
        help="只跑一次(默认行为,显式声明以便与 --interval 互斥)",
    )
    parser.add_argument(
        "--interval", type=int, default=0,
        help="定时跑间隔(秒),0 或 --once 表示只跑一次",
    )
    parser.add_argument(
        "--rlhf-path", default=".quantcode/rlhf_data.jsonl",
        help="RLHF 数据文件路径",
    )
    parser.add_argument(
        "--memory-root", default=".quantcode",
        help="MemoryService 写入根目录",
    )
    parser.add_argument(
        "--event-sink", default=".quantcode/dream_events.jsonl",
        help="事件流文件路径(JSONL append)",
    )
    parser.add_argument(
        "--llm-mode", default="auto",
        choices=["auto", "mock", "real"],
        help="LLM 模式: auto(有 config.json 用 real)/ mock / real",
    )
    args = parser.parse_args(argv)

    # 延迟 import:CLI 启动后再加载(避免 CLI --help 慢)
    from dream.trigger import trigger_dream

    if args.interval <= 0 or args.once:
        # 单次
        trigger_dream(
            rlhf_path=args.rlhf_path,
            memory_root=args.memory_root,
            event_sink=Path(args.event_sink),
            llm_mode=args.llm_mode,
        )
        return 0

    # 定时循环(简单实现,生产可换 APScheduler)
    while True:
        try:
            trigger_dream(
                rlhf_path=args.rlhf_path,
                memory_root=args.memory_root,
                event_sink=Path(args.event_sink),
                llm_mode=args.llm_mode,
            )
        except Exception as e:
            print(f"[dream] 触发失败: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
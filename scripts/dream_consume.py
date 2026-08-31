"""Dream consumer CLI — P0-9 遗留闭环消费端入口。

用法（调度模式与 ``python -m dream.cli`` 一致）::

    # 跑一轮
    python scripts/dream_consume.py --once

    # 守护式每 N 秒消费增量
    python scripts/dream_consume.py --interval 300

一轮 = tail .quantcode/evidence/*.jsonl 新完成 run → 成功 run 的 tool 序列
→ dream.distill_prototype.run_distill 产候选 SKILL.md 草案到
.quantcode/distill_candidates/（index.json 去重）→ 可选 judge 落 RLHF。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 脚本方式运行时 sys.path[0]=scripts/ 而非仓库根，site-packages 里存在第三方
# schemas 命名空间包会抢在仓库 schemas 之前——沿用 quantcode/mcp_server.py 同款
# 仓库根注入，保证 schemas/runner 解析到仓库内包。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dream consumer: tail evidence runs → distill candidates (+ judge RLHF)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="只跑一次(默认行为,显式声明以便与 --interval 互斥)",
    )
    parser.add_argument(
        "--interval", type=int, default=0,
        help="定时跑间隔(秒),0 或 --once 表示只跑一次",
    )
    parser.add_argument(
        "--evidence-dir", default=None,
        help="evidence 目录(默认 .quantcode/evidence)",
    )
    parser.add_argument(
        "--candidates-dir", default=None,
        help="候选输出目录(默认 .quantcode/distill_candidates)",
    )
    parser.add_argument(
        "--group", default="",
        help="喂蒸馏时给 run 记录标的 group(默认空,distill 归 unknown 组)",
    )
    parser.add_argument(
        "--min-occurrences", type=int, default=1,
        help="序列至少重复几次才成候选(默认 1,消费端按轮喂增量)",
    )
    parser.add_argument(
        "--with-judge", action="store_true",
        help="对带 goal 的新 run 走 judge → apply_judged_session 落 RLHF",
    )
    args = parser.parse_args(argv)

    from runner.dream_consumer import consume_once  # 延迟 import:CLI --help 快

    consumed: set[str] = set()

    def _round() -> None:
        kwargs: dict = {
            "with_judge": args.with_judge,
            "group": args.group,
            "min_occurrences": args.min_occurrences,
            "consumed_run_ids": consumed if args.interval > 0 else None,
            }
        if args.evidence_dir:
            kwargs["evidence_dir"] = args.evidence_dir
        if args.candidates_dir:
            kwargs["candidates_dir"] = args.candidates_dir
        summary = consume_once(**kwargs)
        print(
            f"[dream_consume] scanned={summary['scanned_runs']} "
            f"new_runs={summary['new_runs']} "
            f"candidates+={len(summary['candidates'])} "
            f"judged={summary['judged']}"
        )

    if args.interval <= 0 or args.once:
        _round()
        return 0

    # 守护循环(consumed 集合跨轮增量,与 dream/cli --interval 同模式)
    while True:
        try:
            _round()
        except Exception as e:
            print(f"[dream_consume] 轮次失败: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
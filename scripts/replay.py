"""最小 replay 工具 — 查看 / 恢复 LangGraph checkpoint 线程。

⚠️ 最小 replay，PRD §5.3 完整时间旅行另行（当前只做 list / show 两个只读动作）。

用法：
    python -m scripts.replay list [--db PATH]
    python -m scripts.replay show --thread THREAD [--db PATH]

- list   ：sqlite3 只读列出 DISTINCT thread_id + 最近 checkpoint_id
           （LangGraph 的 checkpoint_id 是时间有序 UUID，MAX 即最近）。
- show   ：该 thread 最近 checkpoint 概要（channel_values / 节点写入，尽力容错）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# 裸跑自愈：`python scripts/replay.py` 无 PYTHONPATH 时，先注入仓库根再 import 项目包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.langgraph_base import CHECKPOINTS_DB  # noqa: E402

# ---------------------------------------------------------------------------
# 只读连接与 list
# ---------------------------------------------------------------------------

def _connect_ro(db_path: str | Path) -> sqlite3.Connection:
    """只读打开 checkpoint db（URI mode=ro，绝不写库）。"""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"checkpoint db 不存在: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def list_threads(db_path: str | Path = CHECKPOINTS_DB) -> list[dict[str, Any]]:
    """列出所有 thread（DISTINCT）及其最近 checkpoint_id。

    空库 / 无 checkpoints 表（非 LangGraph db）容错返回空列表。
    """
    conn = _connect_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT thread_id, MAX(checkpoint_id) AS latest"
            " FROM checkpoints GROUP BY thread_id ORDER BY latest DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [{"thread_id": row[0], "checkpoint_id": row[1]} for row in rows]


# ---------------------------------------------------------------------------
# show：最近 checkpoint 概要（尽力容错）
# ---------------------------------------------------------------------------

def show_thread(db_path: str | Path, thread_id: str) -> str:
    """读该 thread 最近 checkpoint，返回可打印概要。

    metadata 在 sqlite saver 中是纯 JSON；checkpoint blob 是 msgpack
    （JsonPlusSerializer）。解不出来一律降级为原始长度展示，不抛异常。
    """
    conn = _connect_ro(db_path)
    try:
        row = conn.execute(
            "SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata"
            " FROM checkpoints WHERE thread_id = ?"
            " ORDER BY checkpoint_id DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        return f"读取 checkpoint 失败: {exc}"
    finally:
        conn.close()

    if row is None:
        return f"thread 不存在: {thread_id}"

    checkpoint_id, parent_id, cp_type, cp_blob, metadata_blob = row
    lines = [
        f"thread_id     : {thread_id}",
        f"checkpoint_id : {checkpoint_id}",
        f"parent_id     : {parent_id or '-'}",
    ]

    metadata: dict[str, Any] = {}
    if metadata_blob:
        try:
            metadata = json.loads(metadata_blob)
        except Exception:
            metadata = {}
    if metadata:
        lines.append(f"step/source   : {metadata.get('step')} / {metadata.get('source')}")
        writes = metadata.get("writes")
        if isinstance(writes, dict) and writes:
            lines.append(f"节点写入       : {', '.join(writes.keys())}")

    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

        checkpoint = JsonPlusSerializer().loads_typed((cp_type, cp_blob))
        channel_values = (checkpoint or {}).get("channel_values") or {}
        lines.append(
            f"channel_values: {', '.join(sorted(channel_values.keys())) or '-'}"
        )
        for key in (
            "task_status",
            "status",
            "human_review_result",
            "gate_decision",
            "output_data",
            "artifacts",
            "errors",
        ):
            if key in channel_values:
                lines.append(f"  {key} = {str(channel_values[key])[:300]}")
    except Exception as exc:
        size = len(cp_blob) if cp_blob else 0
        lines.append(f"checkpoint blob 解码失败（原始 {size} bytes）: {exc}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="replay",
        description="最小 replay：只读查看 LangGraph checkpoint 线程",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db",
        default=str(CHECKPOINTS_DB),
        help="checkpoint db 路径（默认 .quantcode/checkpoints.db）",
    )

    sub.add_parser("list", parents=[common], help="列出所有 thread（DISTINCT + 最近 checkpoint）")
    p_show = sub.add_parser("show", parents=[common], help="查看某 thread 最近 checkpoint 概要")
    p_show.add_argument("--thread", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db: str | Path = args.db

    if args.command == "list":
        threads = list_threads(db)
        if not threads:
            print("(no threads)")
            return 0
        for item in threads:
            print(f"{item['checkpoint_id']}\t{item['thread_id']}")
        return 0

    if args.command == "show":
        print(show_thread(db, args.thread))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

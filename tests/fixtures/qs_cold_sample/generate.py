"""Generate tests/fixtures/qs_cold_sample — tiny qs-cold staging replica.

Run:  python tests/fixtures/qs_cold_sample/generate.py
Layout mirrors SPEC §2.1:
  selected_pool.csv / index.json
  factors/GTJA191_M019/year=2024/data.parquet  (8 rows)
  factors/GTJA191_M019/year=2025/data.parquet  (8 rows)
Rows include 2 is_valid==0 rows and a PIT-late row (sole data point of its
date) so D1-A4 (PIT) and D1-A5 (invalid) are exercisable.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
FACTOR_DIR = HERE / "factors" / "GTJA191_M019"
ASSETS = ["600519.SH", "000001.SZ", "300750.SZ", "871981.BJ"]


def _rows_year2024():
    # 长表 12 行，列含义见 SPEC §2.1。
    # - 无效行（D1-A5）：(2024-01-02, 871981.BJ) 与 (2024-01-03, 300750.SZ)
    #   两个单元格，所在日期另有他行 → 剔除后该单元格为 None。
    # - PIT 行（D1-A4）：2024-01-04 只有 871981.BJ 一行，calc_time=2024-06-01
    #   → as_of=2024-02-01 早截断时该日期整体不进 dates。
    rows = [
        # (2024-01-02, 3 assets, 其中 871981.BJ invalid)
        # (2024-01-03, 3 assets, 其中 300750.SZ invalid)
        # (2024-01-04, 仅 871981.BJ，calc_time 晚到)
    ]
    for di, d in enumerate([date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]):
        assets_today = ASSETS if di < 2 else [ASSETS[3]]
        for a in assets_today:
            ai = ASSETS.index(a)
            invalid = (di == 0 and a == "871981.BJ") or (di == 1 and a == "300750.SZ")
            calc = (
                datetime(2024, 6, 1, 12, 0)
                if (di == 2)
                else datetime(2024, 1, 1, 20, 0)
            )
            rows.append(
                {
                    "datetime": datetime(2024, 1, 2 + di),
                    "asset": a,
                    "value": float(100 + di * 4 + ai),
                    "calc_time": calc,
                    "factor_version": "v1.2",
                    "data_snapshot_id": "snap-20260816",
                    "is_valid": 0 if invalid else 1,
                    "invalid_reason": "" if not invalid else "missing_raw_data",
                }
            )
    return rows


def _rows_year2025():
    # 8 rows: 2 dates x 4 assets; all valid, all calc_time before any test as_of
    rows = []
    for di, d in enumerate([date(2025, 1, 6), date(2025, 1, 7)]):
        for ai, a in enumerate(ASSETS):
            idx = di * len(ASSETS) + ai
            rows.append(
                {
                    "datetime": datetime(2025, 1, 6 + di),
                    "asset": a,
                    "value": float(200 + idx),
                    "calc_time": datetime(2025, 1, 2, 20, 0),
                    "factor_version": "v1.2",
                    "data_snapshot_id": "snap-20260816",
                    "is_valid": 1,
                    "invalid_reason": "",
                }
            )
    return rows


def _table(rows):
    return pa.table(
        {
            "datetime": pa.array([r["datetime"] for r in rows], pa.timestamp("us")),
            "asset": pa.array([r["asset"] for r in rows], pa.string()),
            "value": pa.array([r["value"] for r in rows], pa.float32()),
            "calc_time": pa.array([r["calc_time"] for r in rows], pa.timestamp("us")),
            "factor_version": pa.array([r["factor_version"] for r in rows], pa.string()),
            "data_snapshot_id": pa.array([r["data_snapshot_id"] for r in rows], pa.string()),
            "is_valid": pa.array([r["is_valid"] for r in rows], pa.int64()),
            "invalid_reason": pa.array([r["invalid_reason"] for r in rows], pa.string()),
        }
    )


def main() -> None:
    (FACTOR_DIR / "year=2024").mkdir(parents=True, exist_ok=True)
    (FACTOR_DIR / "year=2025").mkdir(parents=True, exist_ok=True)
    pq.write_table(_table(_rows_year2024()), FACTOR_DIR / "year=2024" / "data.parquet")
    pq.write_table(_table(_rows_year2025()), FACTOR_DIR / "year=2025" / "data.parquet")

    (HERE / "selected_pool.csv").write_text(
        "factor_name,family,factor_dir,factor_values_path,format,rank_ic_mean,"
        "abs_rank_ic,factor_direction,formula,code_hash\n"
        "GTJA191_M019,lqtp_1014,GTJA191_M019,factors/GTJA191_M019,parquet,"
        "0.021,0.021,positive,alpha_191#M019,abc123\n"
        "DEMO_ABS,lqtp_1014,DEMO_ABS,factors/DEMO_ABS,parquet,"
        "0.018,0.018,negative,x/y,def456\n",
        encoding="utf-8",
    )
    (HERE / "index.json").write_text(
        "{\n"
        '  "algorithm": "min_degree_greedy_tiebreak_abs_rank_ic",\n'
        '  "candidates": 979,\n'
        '  "selected": 247,\n'
        '  "max_abs_corr": 0.7,\n'
        '  "family_distribution": {"lqtp_1014": 158, "abs_rankic": 44,\n'
        '                          "cogalpha": 26, "alphasage": 17, "quantalpha": 2}\n'
        "}\n",
        encoding="utf-8",
    )
    print("fixture written to", HERE)


if __name__ == "__main__":
    main()
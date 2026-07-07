"""build_vol_surface tool — 从样本期权链拟合波动率曲面（stub）。"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from schemas.options import OptionSide, VolSurfacePoint, VolSurfaceResult
from tools.registry import PROJECT_ROOT, ToolDef


class BuildVolSurfaceArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    underlying: str = Field(min_length=1, examples=["GC"])
    as_of_date: date
    data_path: str = Field(
        default="data/sample_options/gc_options_merged_sample.csv",
        description="repo-relative 或绝对路径",
    )


def _parse_expiry(raw: str) -> date:
    if "T" in raw:
        return datetime.fromisoformat(raw).date()
    return date.fromisoformat(raw)


def _load_points(data_path: Path, underlying: str, as_of_date: date) -> list[VolSurfacePoint]:
    if not data_path.exists():
        return [
            VolSurfacePoint(
                expiry=as_of_date,
                strike=3400.0,
                side=OptionSide.CALL,
                implied_vol=0.22,
                moneyness=1.0,
            )
        ]

    points: list[VolSurfacePoint] = []
    with data_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("underlying", "").strip() and underlying not in row["underlying"]:
                continue
            strike = float(row["strike_price"])
            mid = float(row.get("mid_px") or row.get("close") or 0)
            if mid <= 0:
                continue
            side_raw = row.get("instrument_class", "call").lower()
            side = OptionSide.PUT if side_raw == "put" else OptionSide.CALL
            points.append(
                VolSurfacePoint(
                    expiry=_parse_expiry(row["expiration"]),
                    strike=strike,
                    side=side,
                    implied_vol=round(min(max(mid / strike, 0.05), 0.8), 4),
                    moneyness=round(strike / 3400.0, 4),
                )
            )
    return points or [
        VolSurfacePoint(
            expiry=as_of_date,
            strike=3400.0,
            side=OptionSide.CALL,
            implied_vol=0.22,
        )
    ]


def build_vol_surface_execute(args: BuildVolSurfaceArgs, ctx: dict) -> dict:
    data_path = Path(args.data_path)
    if not data_path.is_absolute():
        data_path = PROJECT_ROOT / data_path

    points = _load_points(data_path, args.underlying, args.as_of_date)
    result = VolSurfaceResult(
        underlying=args.underlying,
        as_of_date=args.as_of_date,
        forward_price=3400.0,
        points=points,
        interpolation_method="sample_csv_stub",
        data_quality="sample" if data_path.exists() else "mock",
    )
    payload = result.model_dump(mode="json")
    payload["strategy_name"] = args.strategy_name
    return payload


build_vol_surface_tool = ToolDef(
    id="build_vol_surface",
    description=(
        "Build an implied volatility surface from options market data. "
        "Input: strategy_name, underlying, as_of_date, optional data_path. "
        "Returns VolSurfaceResult JSON (underlying, forward_price, points[])."
    ),
    schema=BuildVolSurfaceArgs,
    execute=build_vol_surface_execute,
)

__all__ = ["build_vol_surface_tool", "BuildVolSurfaceArgs", "build_vol_surface_execute"]

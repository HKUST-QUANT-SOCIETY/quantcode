"""build_vol_surface tool — 从期权链用 BS 反推 IV 并落盘 artifact（Day4 真实化）。"""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from schemas.options import OptionSide, VolSurfacePoint, VolSurfaceResult
from tools.registry import PROJECT_ROOT, ToolDef
from tools.utils.paths import resolve_input_path, safe_filename_component


class BuildVolSurfaceArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    underlying: str = Field(min_length=1, examples=["GC"])
    as_of_date: date
    data_path: str = Field(
        default="data/sample_options/gc_options_merged_sample.csv",
        description="repo-relative 或绝对路径",
    )
    forward_price: float | None = Field(
        default=None,
        gt=0,
        description="远期/标的价格；默认用 ATM strike 中位数",
    )
    risk_free_rate: float = Field(default=0.03, ge=0, le=0.2)
    write_artifact: bool = Field(
        default=True,
        description="写入 artifacts/options/<strategy>/vol_surface.json",
    )

    @field_validator("underlying")
    @classmethod
    def _normalize_underlying(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("underlying must not be blank")
        return value


def _parse_expiry(raw: str) -> date:
    if "T" in raw:
        return datetime.fromisoformat(raw).date()
    return date.fromisoformat(raw)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(
    spot: float,
    strike: float,
    t: float,
    r: float,
    vol: float,
    is_call: bool,
) -> float:
    if t <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
        return intrinsic
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    if is_call:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _implied_vol(
    mid: float,
    spot: float,
    strike: float,
    t: float,
    r: float,
    is_call: bool,
) -> float:
    """Bisection IV solve; fallback to mid/strike clip if unsolvable."""
    if mid <= 0 or spot <= 0 or strike <= 0:
        return 0.2
    # Intrinsic floors
    discounted_k = strike * math.exp(-r * max(t, 0.0))
    lower = max(spot - discounted_k, 0.0) if is_call else max(discounted_k - spot, 0.0)
    if mid < lower * 0.99:
        return round(min(max(mid / strike, 0.05), 0.8), 4)

    lo, hi = 1e-4, 5.0
    for _ in range(60):
        mid_vol = 0.5 * (lo + hi)
        price = _bs_price(spot, strike, max(t, 1e-6), r, mid_vol, is_call)
        if price > mid:
            hi = mid_vol
        else:
            lo = mid_vol
    return round(min(max(0.5 * (lo + hi), 0.01), 5.0), 4)


def _year_fraction(as_of: date, expiry: date) -> float:
    days = (expiry - as_of).days
    # Options often quote on futures; allow tiny positive tau for near-dated
    return max(days / 365.0, 1.0 / 365.0)


def _load_rows(data_path: Path, underlying: str) -> list[dict]:
    if not data_path.exists():
        return []
    target = underlying.strip().upper()

    def matches(row_underlying: str) -> bool:
        value = row_underlying.strip().upper()
        if not value:
            return False
        if value == target:
            return True
        # Futures option roots may append a contract month/year (e.g. GCZ6),
        # but arbitrary substring matches (G matching GCZ6) are unsafe.
        suffix = value[len(target) :] if value.startswith(target) else ""
        return bool(suffix and re.fullmatch(r"[A-Z]\d{1,4}", suffix))

    rows: list[dict] = []
    with data_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not matches(row.get("underlying", "")):
                continue
            rows.append(row)
    return rows


def _load_points(
    data_path: Path,
    underlying: str,
    as_of_date: date,
    forward: float | None,
    rate: float,
) -> tuple[list[VolSurfacePoint], float, str]:
    rows = _load_rows(data_path, underlying)
    if not rows:
        return (
            [
                VolSurfacePoint(
                    expiry=as_of_date,
                    strike=3400.0,
                    side=OptionSide.CALL,
                    implied_vol=0.22,
                    moneyness=1.0,
                )
            ],
            3400.0,
            "mock",
        )

    strikes = [float(r["strike_price"]) for r in rows]
    spot = forward if forward is not None else float(sorted(strikes)[len(strikes) // 2])

    points: list[VolSurfacePoint] = []
    for row in rows:
        strike = float(row["strike_price"])
        mid = float(row.get("mid_px") or row.get("close") or 0)
        if mid <= 0:
            continue
        side_raw = row.get("instrument_class", "call").lower()
        is_call = side_raw != "put"
        side = OptionSide.CALL if is_call else OptionSide.PUT
        expiry = _parse_expiry(row["expiration"])
        t = _year_fraction(as_of_date, expiry)
        iv = _implied_vol(mid, spot, strike, t, rate, is_call)
        points.append(
            VolSurfacePoint(
                expiry=expiry,
                strike=strike,
                side=side,
                implied_vol=iv,
                moneyness=round(strike / spot, 4),
            )
        )

    if not points:
        points = [
            VolSurfacePoint(
                expiry=as_of_date,
                strike=spot,
                side=OptionSide.CALL,
                implied_vol=0.22,
                moneyness=1.0,
            )
        ]
        quality = "mock"
    else:
        quality = "sample_bs_iv"
    return points, spot, quality


def build_vol_surface_execute(args: BuildVolSurfaceArgs, ctx: dict) -> dict:
    data_path = resolve_input_path(args.data_path, root=PROJECT_ROOT)

    points, forward, quality = _load_points(
        data_path,
        args.underlying,
        args.as_of_date,
        args.forward_price,
        args.risk_free_rate,
    )
    result = VolSurfaceResult(
        underlying=args.underlying,
        as_of_date=args.as_of_date,
        forward_price=forward,
        points=points,
        interpolation_method="black_scholes_iv_bisection",
        data_quality=quality,
    )
    payload = result.model_dump(mode="json")
    payload["strategy_name"] = args.strategy_name
    payload["risk_free_rate"] = args.risk_free_rate

    if args.write_artifact:
        art_dir = PROJECT_ROOT / "artifacts" / "options" / safe_filename_component(args.strategy_name)
        art_dir.mkdir(parents=True, exist_ok=True)
        art_path = art_dir / "vol_surface.json"
        art_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            payload["artifact_path"] = str(art_path.relative_to(PROJECT_ROOT))
        except ValueError:
            payload["artifact_path"] = str(art_path)

    return payload


build_vol_surface_tool = ToolDef(
    id="build_vol_surface",
    description=(
        "Build an implied volatility surface from options market data using "
        "Black-Scholes IV bisection on mid prices. "
        "Input: strategy_name, underlying, as_of_date, optional data_path/forward_price. "
        "Returns VolSurfaceResult JSON and writes artifacts/options/<strategy>/vol_surface.json."
    ),
    schema=BuildVolSurfaceArgs,
    execute=build_vol_surface_execute,
)

__all__ = ["build_vol_surface_tool", "BuildVolSurfaceArgs", "build_vol_surface_execute"]

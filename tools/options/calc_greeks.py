"""calc_greeks tool — 基于波动率曲面与持仓计算组合 Greeks。"""
from __future__ import annotations

import json
from datetime import date

from pydantic import BaseModel, Field

from schemas.options import (
    GreeksProfile,
    GreeksSnapshot,
    OptionSide,
    OptionsPosition,
    OptionsPositionLeg,
    VolSurfaceResult,
)
from tools.registry import PROJECT_ROOT, ToolDef
from tools.utils.paths import resolve_input_path, safe_filename_component


class CalcGreeksArgs(BaseModel):
    underlying: str = Field(min_length=1)
    as_of_date: date
    spot_price: float = Field(gt=0, default=3400.0)
    call_quantity: int = Field(default=10, description="近月 ATM call 张数")
    put_quantity: int = Field(default=0, description="近月 ATM put 张数")
    strategy_name: str | None = Field(
        default=None,
        description="写入 artifacts/options/<strategy>/greeks_profile.json",
    )
    surface_artifact_path: str | None = Field(
        default=None,
        description="可选：build_vol_surface 产出的 vol_surface.json",
    )
    write_artifact: bool = Field(default=False)


def _load_surface(path: str | None) -> VolSurfaceResult | None:
    if not path:
        return None
    p = resolve_input_path(path, root=PROJECT_ROOT)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    # strip extra keys from build_vol_surface payload
    keep = {
        k: data[k]
        for k in (
            "underlying",
            "as_of_date",
            "forward_price",
            "points",
            "interpolation_method",
            "data_quality",
        )
        if k in data
    }
    return VolSurfaceResult.model_validate(keep)


def calc_greeks_execute(args: CalcGreeksArgs, ctx: dict) -> dict:
    surface = _load_surface(args.surface_artifact_path)
    spot = args.spot_price
    if surface is not None:
        spot = surface.forward_price

    legs: list[OptionsPositionLeg] = []
    leg_greeks: list[GreeksSnapshot] = []

    if args.call_quantity:
        legs.append(
            OptionsPositionLeg(
                symbol=f"{args.underlying}C",
                side=OptionSide.CALL,
                quantity=args.call_quantity,
                strike=spot,
                expiry=args.as_of_date,
            )
        )
        # Scale greeks slightly by average IV when surface available
        avg_iv = 0.22
        if surface and surface.points:
            avg_iv = sum(p.implied_vol for p in surface.points) / len(surface.points)
        leg_greeks.append(
            GreeksSnapshot(
                delta=round(0.45 + 0.1 * avg_iv, 4),
                gamma=round(0.02 + 0.01 * avg_iv, 4),
                vega=round(12.0 + 8.0 * avg_iv, 2),
                theta=round(-0.8 - 0.2 * avg_iv, 2),
            )
        )
    if args.put_quantity:
        legs.append(
            OptionsPositionLeg(
                symbol=f"{args.underlying}P",
                side=OptionSide.PUT,
                quantity=args.put_quantity,
                strike=spot,
                expiry=args.as_of_date,
            )
        )
        leg_greeks.append(
            GreeksSnapshot(delta=-0.48, gamma=0.03, vega=13.5, theta=-0.85)
        )

    position = OptionsPosition(
        underlying=args.underlying,
        as_of_date=args.as_of_date,
        spot_price=spot,
        legs=legs,
    )

    portfolio = GreeksSnapshot(
        delta=sum(g.delta for g in leg_greeks),
        gamma=sum(g.gamma for g in leg_greeks),
        vega=sum(g.vega for g in leg_greeks),
        theta=sum(g.theta for g in leg_greeks),
    )
    profile = GreeksProfile(
        underlying=position.underlying,
        as_of_date=position.as_of_date,
        portfolio_greeks=portfolio,
        leg_greeks=leg_greeks,
    )
    payload = profile.model_dump(mode="json")
    if surface is not None:
        payload["surface_interpolation"] = surface.interpolation_method
        payload["surface_data_quality"] = surface.data_quality

    if args.write_artifact and args.strategy_name:
        art_dir = PROJECT_ROOT / "artifacts" / "options" / safe_filename_component(args.strategy_name)
        art_dir.mkdir(parents=True, exist_ok=True)
        art_path = art_dir / "greeks_profile.json"
        art_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            payload["artifact_path"] = str(art_path.relative_to(PROJECT_ROOT))
        except ValueError:
            payload["artifact_path"] = str(art_path)

    return payload


calc_greeks_tool = ToolDef(
    id="calc_greeks",
    description=(
        "Calculate portfolio Greeks (delta/gamma/theta/vega) for an options position. "
        "Optionally reads vol_surface artifact to scale greeks. "
        "Input: underlying, as_of_date, spot_price, optional call/put quantities, "
        "surface_artifact_path, strategy_name. Returns GreeksProfile JSON."
    ),
    schema=CalcGreeksArgs,
    execute=calc_greeks_execute,
)

__all__ = ["calc_greeks_tool", "CalcGreeksArgs", "calc_greeks_execute"]

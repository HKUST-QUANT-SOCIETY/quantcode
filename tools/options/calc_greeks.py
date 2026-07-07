"""calc_greeks tool — 基于持仓计算组合 Greeks（stub）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from schemas.options import (
    GreeksProfile,
    GreeksSnapshot,
    OptionSide,
    OptionsPosition,
    OptionsPositionLeg,
)
from tools.registry import ToolDef


class CalcGreeksArgs(BaseModel):
    underlying: str = Field(min_length=1)
    as_of_date: date
    spot_price: float = Field(gt=0, default=3400.0)
    call_quantity: int = Field(default=10, description="近月 ATM call 张数")
    put_quantity: int = Field(default=0, description="近月 ATM put 张数")


def calc_greeks_execute(args: CalcGreeksArgs, ctx: dict) -> dict:
    legs: list[OptionsPositionLeg] = []
    leg_greeks: list[GreeksSnapshot] = []

    if args.call_quantity:
        legs.append(
            OptionsPositionLeg(
                symbol=f"{args.underlying}C",
                side=OptionSide.CALL,
                quantity=args.call_quantity,
                strike=args.spot_price,
                expiry=args.as_of_date,
            )
        )
        leg_greeks.append(
            GreeksSnapshot(delta=0.52, gamma=0.03, vega=14.0, theta=-0.9)
        )
    if args.put_quantity:
        legs.append(
            OptionsPositionLeg(
                symbol=f"{args.underlying}P",
                side=OptionSide.PUT,
                quantity=args.put_quantity,
                strike=args.spot_price,
                expiry=args.as_of_date,
            )
        )
        leg_greeks.append(
            GreeksSnapshot(delta=-0.48, gamma=0.03, vega=13.5, theta=-0.85)
        )

    position = OptionsPosition(
        underlying=args.underlying,
        as_of_date=args.as_of_date,
        spot_price=args.spot_price,
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
    return profile.model_dump(mode="json")


calc_greeks_tool = ToolDef(
    id="calc_greeks",
    description=(
        "Calculate portfolio Greeks (delta/gamma/theta/vega) for an options position. "
        "Input: underlying, as_of_date, spot_price, optional call/put quantities. "
        "Returns GreeksProfile JSON."
    ),
    schema=CalcGreeksArgs,
    execute=calc_greeks_execute,
)

__all__ = ["calc_greeks_tool", "CalcGreeksArgs", "calc_greeks_execute"]

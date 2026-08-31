"""P-01 数据接入契约（specs/data/SPEC.md §2.2 + §4 D1-A1..A3/A8）。

FactorPanel / ReturnsDataset：qs-cold staging 只读接入的 typed 契约对象。
- numpy 数组字段用 Any + validator 校验（不把 pandas/pyarrow 依赖带进 schemas；
  内部实现可用 numpy）。
- ``_contract`` 版本戳随对象走：写 Blackboard 前后均可校验（D1-A8/A10）。
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

# SPEC §2.2 不变量②：A 股代码（6 位数字 + SH/SZ/BJ 后缀）。
ASSET_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

CONTRACT_PANEL = "FactorPanel/v1"
CONTRACT_RETURNS = "ReturnsDataset/v1"

# numpy 运行时才校验的字段统一用 Any（schemas 不引 pandas；numpy 为可选运行时依赖，
# 缺失时构造方直接传 list 也能过校验）。
ArrayLike = Any


def _check_dates_ascending_strict(dates: list) -> None:
    """SPEC 不变量①：dates 严格升序无重复。"""
    if len(dates) < 2:
        return
    prev = dates[0]
    for cur in dates[1:]:
        if not cur > prev:
            raise ValueError(
                "dates must be strictly ascending without duplicates; "
                f"got ...{prev} followed by {cur}"
            )
        prev = cur


def _check_no_inf(values: Any, field: str) -> None:
    """递归扫描数值容器，禁止 inf/NaN 之外的 inf（ReturnsDataset 不变量）。"""
    if isinstance(values, dict):
        for v in values.values():
            _check_no_inf(v, field)
    elif isinstance(values, (list, tuple)):
        for v in values:
            _check_no_inf(v, field)
    elif isinstance(values, float) and math.isinf(values):
        raise ValueError(f"{field} must not contain inf")


class FactorPanel(BaseModel):
    """qs-cold 单因子截面矩阵（date × asset）。

    is_valid==0 与 calc_time > as_of 的行在载入时剔除（tools/market/backing.py），
    剔除统计记入 meta.removed / meta.pit_filtered。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # SPEC 不变量⑤：_contract 版本戳随对象走（Blackboard 契约 JSON 必带，D1-A8/A10）。
    contract: Literal["FactorPanel/v1"] = Field(
        default="FactorPanel/v1", alias="_contract", serialization_alias="_contract"
    )
    factor_id: str = Field(min_length=1)
    factor_version: str = Field(min_length=1)
    data_snapshot_id: str = Field(min_length=1)
    dates: list[date]
    assets: list[str]
    values: ArrayLike  # date × asset float 矩阵（ndarray 或嵌套 list）
    source_path: str = Field(min_length=1)
    as_of: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _serialize_model(self, handler) -> dict[str, Any]:
        """默认 dump 路径也带 ``_contract`` 键（Blackboard 载荷契约戳）。"""
        data = handler(self)
        if isinstance(data, dict):
            data["_contract"] = self.contract
            data.pop("contract", None)
        return data

    @field_serializer("values")
    def _serialize_values(self, v: Any) -> Any:
        # numpy ndarray 不在 pydantic JSON 序列化白名单里；ndarray → 嵌套 list。
        if hasattr(v, "tolist"):
            return v.tolist()
        return v

    @field_validator("assets")
    @classmethod
    def _assets_are_a_share_codes(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("assets must not be empty")
        bad = [a for a in v if not ASSET_PATTERN.match(a)]
        if bad:
            raise ValueError(
                f"assets must match {ASSET_PATTERN.pattern} (e.g. '600519.SH'); "
                f"invalid: {bad[:5]}"
            )
        if len(set(v)) != len(v):
            raise ValueError("assets must be unique")
        return v

    @field_validator("dates")
    @classmethod
    def _dates_strictly_ascending(cls, v: list[date]) -> list[date]:
        if not v:
            raise ValueError("dates must not be empty")
        _check_dates_ascending_strict(v)
        return v

    @model_validator(mode="after")
    def _values_shape(self) -> "FactorPanel":
        rows = len(self.dates)
        cols = len(self.assets)
        if hasattr(self.values, "shape"):  # numpy ndarray
            if tuple(self.values.shape) != (rows, cols):
                raise ValueError(
                    f"values shape {tuple(self.values.shape)} != (len(dates), len(assets)) "
                    f"= ({rows}, {cols})"
                )
        elif isinstance(self.values, (list, tuple)):
            if len(self.values) != rows:
                raise ValueError(f"values has {len(self.values)} rows, expected {rows}")
        else:
            raise ValueError("values must be an ndarray or nested list")
        return self

    def summary(self) -> dict[str, Any]:
        """SPEC §2.3：LLM 只见 key+摘要，大矩阵不进返回值。"""
        return {
            "factor_id": self.factor_id,
            "factor_version": self.factor_version,
            "data_snapshot_id": self.data_snapshot_id,
            "n_dates": len(self.dates),
            "date_start": self.dates[0].isoformat() if self.dates else None,
            "date_end": self.dates[-1].isoformat() if self.dates else None,
            "n_assets": len(self.assets),
            "meta": self.meta,
        }


class ReturnsDataset(BaseModel):
    """收益数据集：dates 严格升序、NaN 白名单化、禁 inf（SPEC §2.2）。

    qs-cold 无收益表，首版 returns 来源为 backend 现有行情表（见 SPEC §5）。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    contract: Literal["ReturnsDataset/v1"] = Field(
        default="ReturnsDataset/v1", alias="_contract", serialization_alias="_contract"
    )

    name: str = Field(min_length=1)
    dates: list[date]
    returns: ArrayLike  # dict[asset, vec] 或 date×asset 矩阵
    source_path: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dates")
    @classmethod
    def _dates_strictly_ascending(cls, v: list[date]) -> list[date]:
        if not v:
            raise ValueError("dates must not be empty")
        _check_dates_ascending_strict(v)
        return v

    @model_validator(mode="after")
    def _returns_no_inf(self) -> "ReturnsDataset":
        _check_no_inf(self.returns, "returns")
        rows = len(self.dates)
        if isinstance(self.returns, dict):
            lengths = {len(vec) for vec in self.returns.values()}
            if lengths and lengths != {rows}:
                raise ValueError(
                    f"each returns vector must have length {rows} (len(dates)); "
                    f"got lengths {sorted(lengths)}"
                )
        elif hasattr(self.returns, "shape"):
            if tuple(self.returns.shape) != (rows, len(self.returns.columns)):
                raise ValueError(
                    f"returns shape {tuple(self.returns.shape)} "
                    f"does not match dates row count {rows}"
                )
        elif isinstance(self.returns, (list, tuple)):
            if len(self.returns) != rows:
                raise ValueError(
                    f"returns has {len(self.returns)} rows, expected {rows}"
                )
        return self

    def summary(self) -> dict[str, Any]:
        n_assets = (
            len(self.returns)
            if isinstance(self.returns, dict)
            else None
        )
        return {
            "name": self.name,
            "n_dates": len(self.dates),
            "date_start": self.dates[0].isoformat() if self.dates else None,
            "date_end": self.dates[-1].isoformat() if self.dates else None,
            "n_assets": n_assets,
            "meta": self.meta,
        }


__all__ = [
    "ASSET_PATTERN",
    "CONTRACT_PANEL",
    "CONTRACT_RETURNS",
    "FactorPanel",
    "ReturnsDataset",
]
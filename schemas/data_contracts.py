"""P-01 数据接入契约（specs/data/SPEC.md §2.2/§2.5 + §4 D1-A1..A3/A8/A11/A12）。

FactorPanel / ReturnsDataset / TargetReturnView：qs-cold staging 只读接入的
typed 契约对象。
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
CONTRACT_TARGET_RETURN = "TargetReturnView/v1"

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
            bad_rows = [
                len(row) if isinstance(row, (list, tuple)) else None
                for row in self.values
                if not isinstance(row, (list, tuple)) or len(row) != cols
            ]
            if bad_rows:
                raise ValueError(
                    f"values rows must each have {cols} columns; got {bad_rows[:3]}"
                )
        else:
            raise ValueError("values must be an ndarray or nested list")
        return self

    # DataFrame 等价表示（list-of-records），零外部依赖。
    def to_records(self) -> list[dict[str, Any]]:
        """面板 → 长表 records：每行 ``{"date", "asset", "value"}``。

        不引 pandas（schemas 零重依赖，模块 docstring）；下游需要 pandas
        DataFrame 时 ``pd.DataFrame(panel.to_records())`` 即可。value 为
        float；NaN 保持 float('nan')（NaN 白名单口径，见 ReturnsDataset）。
        """
        return [
            {"date": d, "asset": a, "value": float(row[c])}
            for i, d in enumerate(self.dates)
            for c, a in enumerate(self.assets)
            for row in [self.values[i]]
        ]

    # 鸭子类型等价 pandas DataFrame(pivot) 的窄接口：调用方按
    # frame["dates"] / frame["assets"] / frame["values"] 取，不绑定 pandas。
    def to_frame(self) -> dict[str, Any]:
        """面板 → 宽表等价表示（date 行 × asset 列，结构化 dict）。

        values 是纯嵌套 list（ndarray 已 tolist），date 为 ISO 字符串；
        供下游（如回测/组合域）零拷贝消费，不把 pandas 带进 schemas。
        """
        values = self.values
        if hasattr(values, "tolist"):
            values = values.tolist()
        return {
            "dates": [d.isoformat() for d in self.dates],
            "assets": list(self.assets),
            "values": values,
        }

    def summary(self) -> dict[str, Any]:
        """SPEC §2.3：LLM 只见 key+摘要，大矩阵不进返回值。"""
        n_cells = len(self.dates) * len(self.assets)
        return {
            "factor_id": self.factor_id,
            "factor_version": self.factor_version,
            "data_snapshot_id": self.data_snapshot_id,
            "n_dates": len(self.dates),
            "date_start": self.dates[0].isoformat() if self.dates else None,
            "date_end": self.dates[-1].isoformat() if self.dates else None,
            "n_assets": len(self.assets),
            "n_cells": n_cells,
            "meta": self.meta,
        }

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], **overrides: Any) -> "FactorPanel":
        """长表 records（见 :meth:`to_records`）→ FactorPanel（反向转换）。

        排序口径：dates 严格升序（不变量①），assets 按首次出现顺序去重。
        records 里缺失的 (date, asset) 组合填 NaN；非法 asset 格式由
        契约校验器拒绝。
        """
        if not records:
            raise ValueError("records must not be empty")
        by_date: dict[date, dict[str, float]] = {}
        for rec in records:
            d = rec["date"]
            if not isinstance(d, date):
                d = date.fromisoformat(str(d))
            a = str(rec["asset"])
            by_date.setdefault(d, {})[a] = float(rec["value"])
        dates = sorted(by_date)
        assets: list[str] = []
        for d in dates:
            for a in by_date[d]:
                if a not in assets:
                    assets.append(a)
        nan = float("nan")
        values = [[by_date[d].get(a, nan) for a in assets] for d in dates]
        kwargs: dict[str, Any] = {
            "dates": dates,
            "assets": assets,
            "values": values,
        }
        kwargs.update(overrides)
        return cls(**kwargs)


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
            row_lengths = [
                len(row) if isinstance(row, (list, tuple)) else None
                for row in self.returns
            ]
            if any(length is None for length in row_lengths):
                raise ValueError("returns rows must be nested sequences")
            if len(set(row_lengths)) != 1:
                raise ValueError(
                    f"returns rows must have a consistent number of columns; got {row_lengths}"
                )
        return self

    def to_records(self) -> list[dict[str, Any]]:
        """收益集 → 长表 records：每行 ``{"date", name_key, "return"}``。

        dict 返回时 name_key 为资产代码；矩阵/list-of-vec 返回时用
        ``asset_{col}`` 占位列名（顺序即列序）。cell = 行 t（date）× 列 c。
        """
        if isinstance(self.returns, dict):
            return [
                {"date": d, "asset": a, "return": float(vec[i])}
                for i, d in enumerate(self.dates)
                for a, vec in self.returns.items()
            ]
        rows = self.returns if isinstance(self.returns, list) else list(self.returns)
        return [
            {"date": d, "asset": f"asset_{c}", "return": float(rows[i][c])}
            for i, d in enumerate(self.dates)
            for c in range(len(rows[i]))
        ]

    def to_frame(self) -> dict[str, Any]:
        """收益集 → 宽表等价表示（dict[asset, vec] 口径的纯容器版）。

        dict 返回直接深拷贝；矩阵/list-of-vec 返回转成
        ``{"asset_0": [...], ...}``，供下游按列消费。
        """
        if isinstance(self.returns, dict):
            return {a: [float(v) for v in vec] for a, vec in self.returns.items()}
        rows = self.returns if isinstance(self.returns, list) else list(self.returns)
        return {
            f"asset_{c}": [float(vec[c]) for vec in rows]
            for c in range(next((len(r) for r in rows), 0))
        }

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], **overrides: Any) -> "ReturnsDataset":
        """长表 records（见 :meth:`to_records`）→ ReturnsDataset。

        dates 严格升序去重（不变量）；assets 按首次出现顺序；缺失
        (date, asset) 组合填 NaN（白名单口径）。inf 由契约校验器拒绝。
        """
        if not records:
            raise ValueError("records must not be empty")
        by_date: dict[date, dict[str, float]] = {}
        for rec in records:
            d = rec["date"]
            if not isinstance(d, date):
                d = date.fromisoformat(str(d))
            a = str(rec["asset"])
            by_date.setdefault(d, {})[a] = float(rec["return"])
        dates = sorted(by_date)
        assets: list[str] = []
        for d in dates:
            for a in by_date[d]:
                if a not in assets:
                    assets.append(a)
        nan = float("nan")
        returns = {a: [by_date[d].get(a, nan) for d in dates] for a in assets}
        kwargs: dict[str, Any] = {"dates": dates, "returns": returns}
        kwargs.update(overrides)
        return cls(**kwargs)

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
            "n_cells": (
                len(self.dates) * n_assets if n_assets is not None else None
            ),
            "meta": self.meta,
        }


class TargetReturnView(BaseModel):
    """目标收益口径契约（SPEC §2.5，D1-A11/A12；FUNCTIONAL_SPEC F-06/P-07 定版）。

    唯一取值源为数据仓目标收益表（后复权表内含 Horizon∈{1,5,10,20} 的
    t+1→t+2 forward return），组员/Agent 禁止自算；本契约只登记口径。

    ponytail: qs-cold 无该表，staging 数据源接线 blocked，契约先行——
    取值字段（returns/values）待接线时再加，现在只登记 Horizon / 复权 / 对齐。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # SPEC 不变量⑤同款：_contract 版本戳随对象走。
    contract: Literal["TargetReturnView/v1"] = Field(
        default="TargetReturnView/v1", alias="_contract", serialization_alias="_contract"
    )
    # D1-A11：Horizon 枚举锁死 {1,5,10,20}，其他值（如 3）构造即抛 ValidationError。
    horizon: Literal[1, 5, 10, 20]
    # D1-A12：复权标记必填，且仅接受后复权（hfq）——禁止未复权口径。
    adjusted: Literal["hfq"]  # hfq = 后复权
    # 对齐口径字段：默认且仅接受 t+1→t+2（§2.5 实测案例的正确口径，防再算成 t→t+1）。
    alignment: Literal["t+1->t+2"] = "t+1->t+2"


__all__ = [
    "ASSET_PATTERN",
    "CONTRACT_PANEL",
    "CONTRACT_RETURNS",
    "CONTRACT_TARGET_RETURN",
    "FactorPanel",
    "ReturnsDataset",
    "TargetReturnView",
]

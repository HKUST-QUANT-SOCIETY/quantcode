"""qs-cold staging 后端加载器（P-01，specs/data/SPEC.md §2.1-§2.3）。

只读接入约定：
- ``QS_DATA_BACKEND``：``staging``（默认，本地 staging 副本，零网络）。
  其他值 fail-closed：未知 backend 无凭据时抛 PermissionError/ValueError，
  绝不静默降级（D1-A7）。
- ``QS_DATA_STAGING_ROOT``：Server A staging 副本根路径（本机不存在时
  工具返回明确错误对象而非崩溃）。

staging 目录布局（SPEC §2.1）：
    <root>/delivery_pool_all_maxcard/
        selected_pool.csv          # 247 入选因子
        index.json                 # 筛选算法统计
        factors/{factor_id}/year={Y}/data.parquet  # 长表
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from schemas.data_contracts import CONTRACT_PANEL, FactorPanel
from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key

DEFAULT_STAGING_ROOT = (
    "/srv/quant/data/migration-staging/20260814/hwudf/delivery_values_20260816/"
    "delivery_pool_all_maxcard"
)
POOL_DIRNAME = "selected_pool.csv"
INDEX_FILENAME = "index.json"
FACTORS_DIRNAME = "factors"

SUPPORTED_BACKENDS = frozenset({"staging"})


# ---------------------------------------------------------------------------
# backend 解析（fail-closed）
# ---------------------------------------------------------------------------


def resolve_backend(backend: str | None = None) -> dict[str, Any]:
    """解析当前数据后端配置。

    返回 ``{"backend": ..., "root": Path, "exists": bool}``；
    未知 backend 抛 PermissionError|ValueError（D1-A7，绝不降级到默认数据源）。
    """
    name = (backend or os.environ.get("QS_DATA_BACKEND") or "staging").strip().lower()
    if name != "staging":
        # ponytail: 仅 staging 一个 backend；COS backend 等 QS_DATA_COS_* 凭据
        # 可用后在这里加，凭据未配置时必须继续抛错而不是回落 staging。
        raise PermissionError(
            f"unknown QS_DATA_BACKEND {name!r}: no credentials configured; "
            f"supported backends: {sorted(SUPPORTED_BACKENDS)}"
        )
    root = Path(os.environ.get("QS_DATA_STAGING_ROOT") or DEFAULT_STAGING_ROOT)
    return {"backend": "staging", "root": root, "exists": root.is_dir()}


def _require_pyarrow() -> Any:
    """lazy import pyarrow.parquet；缺包时抛带安装指引的 ImportError。"""
    try:
        import pyarrow.parquet

        return pyarrow.parquet
    except ImportError as e:  # pragma: no cover - 取决于环境
        raise ImportError(
            "pyarrow is required to read qs-cold staging parquet files; "
            "install with `pip install pyarrow`"
        ) from e


def staging_error(error: str, **details: Any) -> dict[str, Any]:
    """明确的错误对象（工具返回值，不崩溃）。"""
    return {"error": error, "backend": resolve_backend_silent(), **details}


def resolve_backend_silent() -> str:
    """backend 名（不抛错，用于错误对象装配）。"""
    return (os.environ.get("QS_DATA_BACKEND") or "staging").strip().lower() or "staging"


# ---------------------------------------------------------------------------
# 池元数据：selected_pool.csv + index.json
# ---------------------------------------------------------------------------


def _pool_dir(root: Path) -> Path:
    return root


def _read_selected_pool(pool_csv: Path) -> list[dict[str, str]]:
    with pool_csv.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def list_factors_impl(
    pool_filter: dict[str, Any] | None = None,
    *,
    backend: str | None = None,
) -> dict[str, Any]:
    """读 selected_pool.csv + index.json，返回因子清单 + 家族分布。"""
    cfg = resolve_backend(backend)
    root: Path = cfg["root"]
    if not cfg["exists"]:
        return staging_error(
            "staging_root_missing",
            detail=f"staging root does not exist on this machine: {root}",
            staging_root=str(root),
        )
    pool_csv = _pool_dir(root) / POOL_DIRNAME
    if not pool_csv.is_file():
        return staging_error(
            "selected_pool_missing", detail=f"{pool_csv} not found", staging_root=str(root)
        )

    rows = _read_selected_pool(pool_csv)
    if pool_filter:
        rows = [
            r
            for r in rows
            if all(str(r.get(k, "")).strip() == str(v) for k, v in pool_filter.items())
        ]

    families: dict[str, int] = {}
    for r in rows:
        fam = r.get("family") or "unknown"
        families[fam] = families.get(fam, 0) + 1

    index_summary: dict[str, Any] | None = None
    index_path = _pool_dir(root) / INDEX_FILENAME
    if index_path.is_file():
        try:
            index_summary = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            index_summary = None

    return {
        "count": len(rows),
        "factors": rows,
        "family_distribution": families,
        "index": index_summary,
        "source": str(pool_csv),
    }


# ---------------------------------------------------------------------------
# 因子长表 → FactorPanel（PIT + is_valid 过滤）
# ---------------------------------------------------------------------------


# ponytail: 路径穿越守卫（Mimosa high 修复）——factor 类 key 在污点入口处归一化：
# 只允许字母数字、点、下划线、连字符与单个斜杠分隔层级；含 ".."、以斜杠开头
# 或出现反斜杠的输入直接拒绝，污点无法进入路径拼接。
_FACTOR_KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


def sanitize_factor_key(factor_key: str) -> str | None:
    """归一化 factor_id/factor_dir；非法（穿越/绝对路径/空段）返回 None。"""
    key = (factor_key or "").strip().strip("/")
    if not key or "\\" in key or ".." in key or "//" in key:
        return None
    if not _FACTOR_KEY_RE.fullmatch(key):
        return None
    return key


def _factor_data_path(root: Path, factor_dir: str, year: int) -> Path | None:
    """SPEC §2.1 布局：factors/{factor_dir}/year={Y}/data.parquet。

    selected_pool.csv 的 factor_dir 是 qs-cold 内相对路径；staging 副本里
    长表按 factors/<factor_id>/year=... 归位，两种 key 都试。
    路径穿越在 sanitize_factor_key 入口已掐断（含 ".." 直接 None）。
    """
    key = sanitize_factor_key(factor_dir)
    if key is None:
        return None
    factors_root = (root / FACTORS_DIRNAME).resolve()
    for base in (factors_root / key, factors_root / Path(key).name):
        p = base / f"year={year}" / "data.parquet"
        if p.is_file():
            return p
    return None


def _resolve_factor_row(root: Path, factor_id: str) -> dict[str, str] | None:
    pool_csv = _pool_dir(root) / POOL_DIRNAME
    if not pool_csv.is_file():
        return None
    for row in _read_selected_pool(pool_csv):
        if row.get("factor_name") == factor_id or row.get("factor_dir") == factor_id:
            return row
    return None


def load_factor_panel_impl(
    factor_id: str,
    year_start: int,
    year_end: int,
    as_of: datetime,
    *,
    backend: str | None = None,
) -> dict[str, Any]:
    """读因子长表 → 剔 is_valid==0 → PIT 过滤 calc_time<=as_of → FactorPanel。

    返回 dict：``{"panel": FactorPanel, "summary": {...}}``（LLM 只见摘要，
    大矩阵走 Blackboard，SPEC §2.3）。
    """
    cfg = resolve_backend(backend)
    root: Path = cfg["root"]
    if not cfg["exists"]:
        return staging_error(
            "staging_root_missing",
            detail=f"staging root does not exist on this machine: {root}",
            staging_root=str(root),
        )
    if year_end < year_start:
        return staging_error(
            "bad_year_range", detail=f"year_end {year_end} < year_start {year_start}"
        )

    row = _resolve_factor_row(root, factor_id)
    paths: list[Path] = []
    if row is not None:
        for y in range(year_start, year_end + 1):
            p = _factor_data_path(root, row.get("factor_dir") or factor_id, y)
            if p is not None:
                paths.append(p)
    else:
        # 不在池里的 factor_id：仍允许直接按 factors/{factor_id}/ 探测
        for y in range(year_start, year_end + 1):
            p = _factor_data_path(root, factor_id, y)
            if p is not None:
                paths.append(p)
    if not paths:
        return staging_error(
            "factor_data_missing",
            detail=f"no factor data for {factor_id!r} years {year_start}-{year_end} "
            f"under {root}",
            factor_id=factor_id,
        )

    pq = _require_pyarrow()

    dates: list[date] = []
    assets: list[str] = []
    values_by_key: dict[tuple[date, str], float] = {}
    removed = 0
    invalid_reasons: dict[str, int] = {}
    pit_filtered = 0
    latest_calc_time: datetime | None = None
    factor_version = row.get("factor_version", "") if row else ""
    snapshot_id = ""
    source_dir = str(paths[0].parent.parent)

    for path in paths:
        table = pq.read_table(path)
        columns = {name: table.column(name).to_pylist() for name in table.column_names}
        dt_col = columns.get("datetime") or columns.get("datetime_date") or []
        for i, dt in enumerate(columns.get("datetime", dt_col)):
            if dt is None:
                continue
            snap = str(columns["data_snapshot_id"][i] or "")
            snapshot_id = snapshot_id or snap
            factor_version = factor_version or str(columns["factor_version"][i] or "")
            ct = columns["calc_time"][i]
            if isinstance(ct, datetime) and (
                latest_calc_time is None or ct > latest_calc_time
            ):
                latest_calc_time = ct
            if ct is not None and isinstance(ct, datetime) and ct > as_of:
                pit_filtered += 1  # PIT：calc_time 晚于 as_of 的行不进面板
                continue
            if int(columns["is_valid"][i]) == 0:
                removed += 1
                reason = str(columns["invalid_reason"][i] or "unknown")
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                continue
            d = dt.date() if isinstance(dt, datetime) else dt
            a = str(columns["asset"][i])
            if d not in dates:
                dates.append(d)
            if a not in assets:
                assets.append(a)
            values_by_key[(d, a)] = float(columns["value"][i])

    dates.sort()
    assets.sort()
    values = [[values_by_key.get((d, a)) for a in assets] for d in dates]

    panel = FactorPanel(
        factor_id=factor_id,
        factor_version=factor_version or "unknown",
        data_snapshot_id=snapshot_id or "unknown",
        dates=dates,
        assets=assets,
        values=values,
        source_path=source_dir,
        as_of=as_of,
        meta={
            "removed": {"count": removed, "invalid_reasons": invalid_reasons},
            "pit_filtered": pit_filtered,
            "year_start": year_start,
            "year_end": year_end,
        },
    )
    return {"panel": panel, "summary": _panel_summary(panel)}


def _panel_summary(panel: FactorPanel) -> dict[str, Any]:
    """工具返回值摘要（key+摘要+统计，大矩阵不进返回值，SPEC §2.3）。"""
    summary = panel.summary()
    summary["source_path"] = panel.source_path
    summary["_contract"] = CONTRACT_PANEL
    summary["blackboard_key"] = make_read_key(f"shared.datasets.panel/{panel.factor_id}")
    return summary


# ---------------------------------------------------------------------------
# Blackboard 写读（契约 JSON + _contract 戳，D1-A9/A10）
# ---------------------------------------------------------------------------


def panel_to_contract_payload(panel: FactorPanel) -> dict[str, Any]:
    """FactorPanel → Blackboard 可存 JSON dict（含 _contract 戳）。

    NaN 因 pyarrow to_pylist 可能混入，白名单化成 None（JSON null）。
    """
    payload = panel.model_dump(mode="json")
    payload["_contract"] = CONTRACT_PANEL
    payload["values"] = [
        [None if (isinstance(v, float) and v != v) else v for v in row]
        for row in payload["values"]
    ]
    return payload


def validate_dataset_payload(value: Any, expect: str = CONTRACT_PANEL) -> FactorPanel:
    """D1-A10：写入 panel namespace 的 dict 必须带匹配的 ``_contract`` 戳。

    无戳或版本不匹配抛 pydantic ValidationError；通过则返回 FactorPanel
    （读出方同样走 model_validate，D1-A9）。
    """
    from pydantic import ValidationError

    if not isinstance(value, dict):
        raise TypeError("dataset payload must be a dict (contract JSON)")
    stamp = value.get("_contract")
    if stamp != expect:
        raise ValidationError.from_exception_data(
            title="FactorPanel",
            line_errors=[
                {
                    "type": "value_error",
                    "loc": ("_contract",),
                    "input": stamp,
                    "ctx": {"error": f"expected _contract stamp {expect!r}, got {stamp!r}"},
                }
            ],
        )
    return FactorPanel.model_validate(value)


def write_panel_to_blackboard(
    panel: FactorPanel,
    *,
    blackboard_db_path: str | Path | None,
    written_by_task_id: str,
    written_by_group: str,
) -> dict[str, Any]:
    """写契约 JSON 到 PROJECT scope ``shared.datasets.panel/{factor_id}``。"""
    from runner.blackboard import BlackboardService
    from schemas import BlackboardScope, GroupName, WritePolicy

    payload = panel_to_contract_payload(panel)
    validate_dataset_payload(payload)  # D1-A10：写入口强制 _contract 戳

    service = BlackboardService(
        db_path=Path(blackboard_db_path) if blackboard_db_path else None,
        session_id=PROJECT_SESSION_ID,
        requester_group=GroupName(written_by_group),
    )
    entry = service.write_value(
        scope=BlackboardScope.PROJECT,
        key=make_read_key(f"shared.datasets.panel/{panel.factor_id}"),
        value=payload,
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id=written_by_task_id,
        written_by_group=GroupName(written_by_group),
    )
    return {"blackboard_key": make_read_key(f"shared.datasets.panel/{panel.factor_id}"),
            "entry": entry.model_dump(mode="json")}


def read_panel_from_blackboard(
    key: str,
    *,
    blackboard_db_path: str | Path | None,
) -> FactorPanel:
    """按 key 读回契约对象（读出方 model_validate，D1-A9）。"""
    from runner.blackboard import BlackboardService
    from schemas import BlackboardScope

    from schemas.data_contracts import FactorPanel as _FP

    service = BlackboardService(
        db_path=Path(blackboard_db_path) if blackboard_db_path else None,
        session_id=PROJECT_SESSION_ID,
        requester_group=None,
    )
    entry = service.get_entry(BlackboardScope.PROJECT, None, make_read_key(key))
    if entry is None:
        raise KeyError(f"blackboard entry not found: {make_read_key(key)}")
    return _FP.model_validate(entry.value)


# ---------------------------------------------------------------------------
# returns（首版：staging 无收益表 → 明确 no_source 错误对象）
# ---------------------------------------------------------------------------


def load_returns_impl(
    name: str,
    date_start: date,
    date_end: date,
    *,
    backend: str | None = None,
) -> dict[str, Any]:
    """ReturnsDataset 装载。

    qs-cold 无 A 股收益表（SPEC §2.2/§5）：staging 后端首版返回明确
    ``no_source`` 错误对象；后续接 backend 现有行情表（StockDailyBar.Return）。
    """
    resolve_backend(backend)  # fail-closed backend 校验
    if date_end < date_start:
        return staging_error(
            "bad_date_range", detail=f"date_end {date_end} < date_start {date_start}"
        )
    return staging_error(
        "no_source",
        detail=(
            "no returns source available: qs-cold staging has no A-share returns "
            "table; ReturnsDataset will read the existing quote table "
            "(StockDailyBar.Return) in a later iteration (SPEC §5)"
        ),
        name=name,
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
    )


# ---------------------------------------------------------------------------
# pool_browse：只读池元数据
# ---------------------------------------------------------------------------


def pool_browse_impl(
    factor_id: str | None = None,
    family: str | None = None,
    *,
    backend: str | None = None,
) -> dict[str, Any]:
    cfg = resolve_backend(backend)
    root: Path = cfg["root"]
    if not cfg["exists"]:
        return staging_error(
            "staging_root_missing",
            detail=f"staging root does not exist on this machine: {root}",
            staging_root=str(root),
        )
    pool_csv = _pool_dir(root) / POOL_DIRNAME
    if not pool_csv.is_file():
        return staging_error(
            "selected_pool_missing", detail=f"{pool_csv} not found", staging_root=str(root)
        )
    rows = _read_selected_pool(pool_csv)
    if factor_id:
        rows = [
            r
            for r in rows
            if r.get("factor_name") == factor_id or r.get("factor_dir") == factor_id
        ]
    if family:
        rows = [r for r in rows if r.get("family") == family]
    return {"count": len(rows), "factors": rows, "source": str(pool_csv)}
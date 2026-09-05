"""algorithms 组注册 — configs/algorithms.yaml 执行端三工具（ROADMAP Q3 A3）。

import 即触发 3 个 ToolDef 注册到全局 registry（_meta 通道，六组 MCP 可见，
不进任何组 allowlist——算法实验管理是平台级能力，对所有组只读开放）：

- list_algorithms:      枚举 signal_algorithms 注册表（id + description）
- describe_algorithm:   查单个 entry 全量（entry_point / 描述 / 参数约定）
- run_algorithm:        按 entry.entry_point 动态调用目标函数 fn(panel, top_n)

entry 契约见 configs/algorithms.yaml 头注释；无效条目跳过并 warning。
"""
from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel, Field

from runner.config_loader import load_yaml
from tools.registry import ToolDef, register_tool

_REGISTRY_NAME = "algorithms"
_REQUIRED_ENTRY_KEYS = ("id", "entry_point", "description")


def _entries() -> list[dict[str, Any]]:
    """读取并校验 signal_algorithms 条目（缺键条目跳过）。"""
    data = load_yaml(_REGISTRY_NAME)
    raw = data.get("signal_algorithms", [])
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if isinstance(e, dict) and all(k in e for k in _REQUIRED_ENTRY_KEYS):
            out.append(e)
        else:
            import logging
            logging.getLogger(__name__).warning(
                "algorithms: 跳过无效注册表条目（缺 %s）: %r", _REQUIRED_ENTRY_KEYS, e
            )
    return out


def _find_entry(algorithm_id: str) -> dict[str, Any]:
    for e in _entries():
        if e["id"] == algorithm_id:
            return e
    ids = [e["id"] for e in _entries()]
    raise KeyError(f"algorithm '{algorithm_id}' not found. Registered: {ids}")


# ---------------------------------------------------------------------------
# list_algorithms
# ---------------------------------------------------------------------------


class ListAlgorithmsArgs(BaseModel):
    """list_algorithms 无参数 — 只读。"""


def _list_algorithms_execute(args: ListAlgorithmsArgs, ctx: dict) -> dict:
    return {
        "algorithms": [
            {"id": e["id"], "description": e["description"]} for e in _entries()
        ],
    }


list_algorithms_tool = ToolDef(
    id="list_algorithms",
    description=(
        "List registered signal algorithms from configs/algorithms.yaml "
        "(id + description). Use before run_algorithm to discover ids."
    ),
    schema=ListAlgorithmsArgs,
    execute=_list_algorithms_execute,
)


# ---------------------------------------------------------------------------
# describe_algorithm
# ---------------------------------------------------------------------------


class DescribeAlgorithmArgs(BaseModel):
    """describe_algorithm 输入。"""

    algorithm_id: str = Field(
        min_length=1, description="algorithms.yaml 里的 algorithm id。",
    )


def _describe_algorithm_execute(args: DescribeAlgorithmArgs, ctx: dict) -> dict:
    entry = _find_entry(args.algorithm_id)
    return {"entry": entry}


describe_algorithm_tool = ToolDef(
    id="describe_algorithm",
    description=(
        "Describe one registered signal algorithm: returns the full "
        "algorithms.yaml entry (id / entry_point / description)."
    ),
    schema=DescribeAlgorithmArgs,
    execute=_describe_algorithm_execute,
)


# ---------------------------------------------------------------------------
# run_algorithm
# ---------------------------------------------------------------------------


class RunAlgorithmArgs(BaseModel):
    """run_algorithm 输入。"""

    algorithm_id: str = Field(
        min_length=1, description="algorithms.yaml 里的 algorithm id。",
    )
    dataset_key: str = Field(
        min_length=1,
        description=(
            "Blackboard dataset key, e.g. shared.datasets.panel/<factor_id> "
            "(FactorPanel contract)."
        ),
    )
    top_n: int = Field(
        default=5, ge=1, le=100, description="返回 top N 资产（1-100，默认 5）。",
    )
    blackboard_db_path: str | None = Field(
        default=None,
        description="可选 Blackboard sqlite 路径；不传用默认库。",
    )


def _run_algorithm_execute(args: RunAlgorithmArgs, ctx: dict) -> dict:
    entry = _find_entry(args.algorithm_id)
    module_path, _, fn_name = entry["entry_point"].partition(":")
    if not fn_name:
        return {"error": f"invalid entry_point '{entry['entry_point']}' (need 'module:func')"}
    from tools.market.backing import read_panel_from_blackboard

    panel = read_panel_from_blackboard(
        args.dataset_key, blackboard_db_path=args.blackboard_db_path
    )
    fn = getattr(importlib.import_module(module_path), fn_name)
    result = fn(panel, top_n=args.top_n)
    return {"algorithm_id": entry["id"], **result}


run_algorithm_tool = ToolDef(
    id="run_algorithm",
    description=(
        "Run a registered signal algorithm on a Blackboard dataset: resolves "
        "the algorithms.yaml entry_point (module:function) and calls it with "
        "the FactorPanel from shared.datasets.panel/* plus top_n. Read-only."
    ),
    schema=RunAlgorithmArgs,
    execute=_run_algorithm_execute,
)


register_tool(list_algorithms_tool)
register_tool(describe_algorithm_tool)
register_tool(run_algorithm_tool)


__all__ = ["list_algorithms_tool", "describe_algorithm_tool", "run_algorithm_tool"]
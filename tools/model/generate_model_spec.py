"""generate_model_spec tool — 由 metadata 生成 ModelSpec（mock 实现）。"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel

from tools.registry import ToolDef


class GenerateModelSpecArgs(BaseModel):
    metadata: dict


def _seed_from_metadata(metadata: dict) -> str:
    """基于 metadata 生成稳定的 model_id（同一份输入 → 同一 model_id）。"""
    payload = "|".join(
        f"{k}={metadata[k]}" for k in sorted(metadata) if metadata.get(k) is not None
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def generate_model_spec_execute(args: GenerateModelSpecArgs, ctx: dict) -> dict:
    """Mock：返回固定结构的 ModelSpec dict。

    ModelSpec 字段说明：
    - model_id: 基于 metadata 哈希得到的稳定 id
    - model_type: 固定 ``lightgbm``（Day 4 替换）
    - parameters: 默认超参数（mock）
    - training_window: 来自 metadata.date_range
    """
    metadata = args.metadata or {}
    model_id = f"model-{_seed_from_metadata(metadata)}"
    date_range = metadata.get("date_range") or {"start": "2020-01-01", "end": "2024-12-31"}

    return {
        "model_id": model_id,
        "model_type": "lightgbm",
        "parameters": {
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
        },
        "training_window": {
            "start": date_range.get("start", "2020-01-01"),
            "end": date_range.get("end", "2024-12-31"),
        },
    }


generate_model_spec_tool = ToolDef(
    id="generate_model_spec",
    description=(
        "Generate a ModelSpec dict from factor metadata. "
        "Returns {model_id, model_type, parameters, training_window}."
    ),
    schema=GenerateModelSpecArgs,
    execute=generate_model_spec_execute,
)

__all__ = [
    "generate_model_spec_tool",
    "GenerateModelSpecArgs",
    "generate_model_spec_execute",
]
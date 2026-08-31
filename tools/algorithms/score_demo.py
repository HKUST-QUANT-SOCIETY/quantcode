"""Demo 评分器 — configs/algorithms.yaml 首个真实实现的 algorithm entry_point。

给定 Blackboard ``shared.datasets.panel/<factor_id>`` 的 FactorPanel 契约，
取最新一截面等权合成 rank 分数（0~1，越大越强），返回 top_n 资产表。
纯排名合成，不喂 LLM、无副作用（只读 Blackboard）。
"""
from __future__ import annotations

from typing import Any


def score_equal_weight_composite(panel: Any) -> list[dict[str, Any]]:
    """对 FactorPanel 最新截面做等权 rank 合成，返回全资产分数表。

    每个 facet（factor 列）先按值升序转 rank（1..n），再跨 facet 等权平均、
    归一到 0~1。panel 单列（demo 数据即如此）时退化为单因子 rank。
    """
    dates = list(panel.dates)
    assets = list(panel.assets)
    values = panel.values
    if not dates or not assets:
        return []
    row = values[-1] if not hasattr(values, "iloc") else values.iloc[-1].tolist()
    n = len(assets)
    num_facets = max(len(row), 1) if not hasattr(row, "__len__") else max(len(row), 1)
    # row 可能是标量（单列被压平）或序列——统一展开
    if not hasattr(row, "__iter__") or isinstance(row, (str, bytes)):
        row = [row]
    per_facet_rank = [0.0] * n
    num_facets = max(len(row), 1)
    for facet_value in row:
        # 单值 facet（如面板只有一列且被压平）→ 全资产同值
        col = [facet_value] * n if not hasattr(facet_value, "__iter__") else list(facet_value)
        order = sorted(range(len(col)), key=lambda i: col[i])
        for rank_pos, asset_idx in enumerate(order):
            # 升序 rank → 归一 (rank)/(n) ；并列值不特殊处理（demo 语义，允许）
            per_facet_rank[asset_idx] += (rank_pos + 1) / n
    composite = [r / num_facets for r in per_facet_rank]
    ranked = sorted(zip(assets, composite), key=lambda x: x[1], reverse=True)
    return [{"asset": a, "score": round(s, 6)} for a, s in ranked]


def run_score_demo(panel: Any, top_n: int = 5) -> dict[str, Any]:
    """algorithms.yaml entry 约定签名：fn(panel, top_n) -> dict。"""
    scored = score_equal_weight_composite(panel)
    return {
        "algorithm": "equal_weight_composite_ranker",
        "as_of": str(panel.dates[-1]) if panel.dates else None,
        "factor_id": panel.factor_id,
        "universe_size": len(scored),
        "top_n": top_n,
        "top_assets": scored[:top_n],
        "scores": scored,
    }


__all__ = ["score_equal_weight_composite", "run_score_demo"]
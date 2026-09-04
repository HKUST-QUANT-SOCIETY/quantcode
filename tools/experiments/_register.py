"""AB 实验三工具注册 — ROADMAP A3 + FUNCTIONAL P-05。

import 即触发 3 个 ToolDef 注册到全局 registry（_meta 通道，与
tools/algorithms/_register 同路，不进各组 allowlist）：

- run_ab_experiment : 两侧 panel 各跑 flows/factor_eval_real.evaluate_factor_panel
                      （algorithm_id 仅作标识），逐指标比较 →
                      artifacts/experiments/{exp_id}.json 归档 +
                      experiments/index.json 排行榜
- list_experiments  : 读排行榜（configs/experiments.yaml experiments.leaderboard_k 条）
- get_experiment    : 按实验 id 查单份归档

configs/experiments.yaml 单源：enforce_oos（OOS 纪律开关）+ leaderboard_k。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from runner.config_loader import load_yaml
from tools.registry import ToolDef, register_tool

logger = logging.getLogger(__name__)

_REGISTRY_NAME = "experiments"
_DEFAULTS = {"enforce_oos": True, "leaderboard_k": 20}
_SAFE_EXPERIMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def experiments_config() -> dict[str, Any]:
    """configs/experiments.yaml → {enforce_oos, leaderboard_k}（缺键回代码默认）。"""
    cfg = dict(_DEFAULTS)
    cfg.update(load_yaml(_REGISTRY_NAME).get("experiments", {}) or {})
    return cfg


def experiments_dir() -> Path:
    return Path("artifacts") / "experiments"


# ---------------------------------------------------------------------------
# 核心实现（ToolDef 与 tests 共用）
# ---------------------------------------------------------------------------


def _resolve_panel_key(side_id: str, dataset_key: str) -> str:
    """侧 id → 被评估的 panel key（三条路径，任务签名两套口径都接）：

    - "panel:<key>"            → 显式 panel key（``shared.datasets.panel/x``）
    - "algorithm:<alg_id>"     → algorithms.yaml 条目的 dataset_key
    - 其他（/裸 panel id）      → panel key 取显式 key，否则 shared.datasets.panel/<id>
    """
    if side_id.startswith("panel:"):
        return side_id[len("panel:"):].strip()
    if side_id.startswith("algorithm:"):
        from tools.algorithms._register import _find_entry

        entry = _find_entry(side_id[len("algorithm:"):].strip())
        key = entry.get("dataset_key")
        if not key:
            raise KeyError(
                f"algorithm entry '{side_id}' has no dataset_key in "
                "configs/algorithms.yaml; add one or use panel:<key>"
            )
        return key
    return side_id if "/" in side_id else f"shared.datasets.panel/{side_id}"


def _evaluate_side(
    side_id: str,
    dataset_key: str,
    *,
    oos_range: dict[str, str] | None,
    blackboard_db_path: str | None,
    fail_reasons: list[str],
) -> dict[str, Any]:
    """单侧评估：panel 路径（eval_from_panel_impl，错误走 error 对象不抛）。

    ponytail: 评估不做 OOS 裁剪而是在完整窗口上跑、再校验窗口 ⊆ oos_range —
    纪律是门槛不是裁剪器（ROADMAP 教训：全样本结果不允许伪装成 OOS 结论）。
    """
    from tools.factor.eval_from_panel import eval_from_panel_impl

    out = eval_from_panel_impl(
        dataset_key, factor_name=side_id,
        blackboard_db_path=blackboard_db_path,
    )
    if "error" in out:
        raise ValueError(
            f"side '{side_id}' evaluation failed: {out.get('error')} "
            f"({out.get('detail', '')})"
        )
    if oos_range and experiments_config()["enforce_oos"]:
        period = out["summary"].get("evaluation_period") or {}
        start, end = period.get("start"), period.get("end")
        if not start or not end or start < oos_range["start"] or end > oos_range["end"]:
            fail_reasons.append(
                f"oos_discipline: side '{side_id}' evaluated "
                f"[{start or '?'}, {end or '?'}] ⊄ "
                f"[{oos_range['start']}, {oos_range['end']}]"
            )
    return out


def _read_panel_json(dataset_key: str, blackboard_db_path: str | None) -> dict[str, Any]:
    """读回 Blackboard 原始 panel payload（算 dataset_snapshot_hash）。"""
    from runner.blackboard import BlackboardService
    from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
    from schemas import BlackboardScope

    service = BlackboardService(
        db_path=Path(blackboard_db_path) if blackboard_db_path else None,
        session_id=PROJECT_SESSION_ID,
        requester_group=None,
    )
    entry = service.get_entry(
        BlackboardScope.PROJECT, None, make_read_key(dataset_key)
    )
    if entry is None:
        raise KeyError(f"blackboard entry not found: {make_read_key(dataset_key)}")
    return entry.value


def run_ab_experiment(
    baseline_id: str,
    challenger_id: str,
    dataset_key: str,
    oos_range: dict[str, str] | None = None,
    *,
    blackboard_db_path: str | None = None,
) -> dict[str, Any]:
    """A/B 双侧评估 → 逐指标比较 → 归档 artifacts/experiments/{exp_id}.json
    + experiments/index.json 排行榜。返回 ABReport dict（含 exp_id）。

    两侧 id 支持 "panel:<blackboard_key>"（eval_from_panel 路径）与
    "<algorithms.yaml 的 algorithm_id>"（run_algorithm 路径）；
    传裸字符串时视为各自同名 panel key ``shared.datasets.panel/<id>``。
    dataset_key 仅作记录（进 ABReport.dataset_key，hash 取 baseline 侧
    panel payload 的稳定序列化）。
    """
    fail_reasons: list[str] = []
    base_panel_key = _resolve_panel_key(baseline_id, dataset_key)
    chall_panel_key = _resolve_panel_key(challenger_id, dataset_key)
    base = _evaluate_side(
        baseline_id, base_panel_key, oos_range=oos_range,
        blackboard_db_path=blackboard_db_path, fail_reasons=fail_reasons,
    )
    chall = _evaluate_side(
        challenger_id, chall_panel_key, oos_range=oos_range,
        blackboard_db_path=blackboard_db_path, fail_reasons=fail_reasons,
    )

    from tools.experiments.ab import build_ab_report, snapshot_hash

    exp_id = f"exp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    base_report, chall_report = base["summary"], chall["summary"]
    ab = build_ab_report(
        exp_id=exp_id,
        baseline_id=baseline_id,
        challenger_id=challenger_id,
        dataset_key=dataset_key,
        dataset_snapshot_hash=snapshot_hash(
            {
                "dataset_key": dataset_key,
                "baseline": _read_panel_json(base_panel_key, blackboard_db_path),
                "challenger": _read_panel_json(chall_panel_key, blackboard_db_path),
            }
        ),
        oos_range=oos_range,
        base_report=base_report,
        chall_report=chall_report,
        fail_reasons=fail_reasons,
        artifacts=[],
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    out_dir = experiments_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{exp_id}.json"
    ab["artifacts"] = [path.as_posix()]
    path.write_text(
        json.dumps(ab, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _append_index(path, ab)
    return ab


def _append_index(artifact_path: Path, ab: dict[str, Any]) -> None:
    """读-改-写 experiments/index.json：排行榜条目 = 归档文件相对路径。"""
    from tools.experiments.ab import snapshot_hash

    idx_path = Path("artifacts") / "experiments" / "index.json"
    ranking: list[dict[str, Any]] = []
    if idx_path.is_file():
        try:
            ranking = json.loads(idx_path.read_text(encoding="utf-8")) or []
        except (json.JSONDecodeError, OSError):
            ranking = []
    if not isinstance(ranking, list):
        ranking = []
    ranking.append({
        "exp_id": ab["exp_id"],
        "artifact": artifact_path.as_posix(),
        "baseline_id": ab["baseline_id"],
        "challenger_id": ab["challenger_id"],
        "verdict": ab["verdict"],
        "fail_reasons": ab["fail_reasons"],
        "dataset_snapshot_hash": ab["dataset_snapshot_hash"],
        "entry_hash": snapshot_hash({"exp_id": ab["exp_id"], "verdict": ab["verdict"]}),
        "created_at": ab["created_at"],
    })
    k = int(experiments_config()["leaderboard_k"])
    ranking = ranking[-k:]
    idx_path.write_text(
        json.dumps(ranking, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _load_experiment(exp_id: str) -> dict[str, Any]:
    if not _SAFE_EXPERIMENT_ID.fullmatch(exp_id) or exp_id in {".", ".."}:
        raise KeyError(f"experiment not found: {exp_id}")
    path = experiments_dir() / f"{exp_id}.json"
    if not path.is_file():
        raise KeyError(f"experiment not found: {exp_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_experiments_impl(limit: int | None = None) -> dict[str, Any]:
    """排行榜（最近 K 条，K=configs/leaderboard_k 或调用方传入）。缺 index → 空榜。"""
    idx_path = Path("artifacts") / "experiments" / "index.json"
    if not idx_path.is_file():
        return {"experiments": [], "total": 0}
    try:
        ranking = json.loads(idx_path.read_text(encoding="utf-8")) or []
    except (json.JSONDecodeError, OSError):
        return {"experiments": [], "total": 0}
    if not isinstance(ranking, list):
        return {"experiments": [], "total": 0}
    k = limit if limit is not None else int(experiments_config()["leaderboard_k"])
    return {"experiments": ranking[-k:], "total": len(ranking)}


# ---------------------------------------------------------------------------
# ToolDefs
# ---------------------------------------------------------------------------


class RunABExperimentArgs(BaseModel):
    """run_ab_experiment 输入。"""

    baseline_id: str = Field(min_length=1, description="基线算法/因子 id（仅作标识）。")
    challenger_id: str = Field(min_length=1, description="挑战者算法/因子 id（仅作标识）。")
    dataset_key: str = Field(
        min_length=1,
        description=(
            "Blackboard dataset key, e.g. shared.datasets.panel/<factor_id> "
            "(FactorPanel contract)；两侧共用同一数据集。"
        ),
    )
    oos_start: str | None = Field(
        default=None, description="OOS 起始 ISO 日期（与 oos_end 成对给出才生效）。"
    )
    oos_end: str | None = Field(
        default=None, description="OOS 结束 ISO 日期（与 oos_start 成对给出才生效）。"
    )
    blackboard_db_path: str | None = Field(
        default=None, description="可选 Blackboard sqlite 路径；不传用默认库。"
    )


def _run_ab_experiment_execute(args: RunABExperimentArgs, ctx: dict) -> dict:
    oos_range = None
    if args.oos_start and args.oos_end:
        oos_range = {"start": args.oos_start, "end": args.oos_end}
    return run_ab_experiment(
        args.baseline_id,
        args.challenger_id,
        args.dataset_key,
        oos_range=oos_range,
        blackboard_db_path=ctx.get("blackboard_db_path") or args.blackboard_db_path,
    )


class ListExperimentsArgs(BaseModel):
    """list_experiments 输入。"""

    limit: int | None = Field(
        default=None, ge=1, description="返回最近 N 条；缺省用 configs/leaderboard_k。",
    )


def _list_experiments_execute(args: ListExperimentsArgs, ctx: dict) -> dict:
    return list_experiments_impl(limit=args.limit)


class GetExperimentArgs(BaseModel):
    """get_experiment 输入。"""

    exp_id: str = Field(min_length=1, description="实验 id（run_ab_experiment 返回值）。")


def _get_experiment_execute(args: GetExperimentArgs, ctx: dict) -> dict:
    return {"report": _load_experiment(args.exp_id)}


run_ab_experiment_tool = ToolDef(
    id="run_ab_experiment",
    description=(
        "Run an A/B experiment (FUNCTIONAL P-05): evaluate baseline and "
        "challenger on the same Blackboard FactorPanel with REAL statistics "
        "(panel_real_v1), compare ic_mean/ir/t_stat/turnover strictly, enforce "
        "OOS discipline when oos_start/oos_end given (evaluation window must "
        "be inside OOS), archive to artifacts/experiments/{exp_id}.json plus a "
        "ranking in experiments/index.json."
    ),
    schema=RunABExperimentArgs,
    execute=_run_ab_experiment_execute,
)

list_experiments_tool = ToolDef(
    id="list_experiments",
    description=(
        "Read-only ranking of archived A/B experiments from "
        "artifacts/experiments/index.json (most recent K entries)."
    ),
    schema=ListExperimentsArgs,
    execute=_list_experiments_execute,
)

get_experiment_tool = ToolDef(
    id="get_experiment",
    description=(
        "Fetch one archived A/B experiment report (ABReport) by exp_id. Use "
        "list_experiments first to discover ids."
    ),
    schema=GetExperimentArgs,
    execute=_get_experiment_execute,
)


register_tool(run_ab_experiment_tool)
register_tool(list_experiments_tool)
register_tool(get_experiment_tool)


__all__ = [
    "experiments_config",
    "run_ab_experiment",
    "list_experiments_impl",
    "run_ab_experiment_tool",
    "list_experiments_tool",
    "get_experiment_tool",
]

"""factor:autoeval 集成 Demo — Day 2 下午尹一帆。

端到端验证任务 #12（execute_compose_flow 集成）+ #13（Memory 注入 state）。

参照任务表 §2.2：
- 外部 caller（模拟肖骥超）调用 :func:`execute_compose_flow`
- ``execute_compose_flow`` 把 MemoryService 实例通过 ``inject_memory`` 工厂注入到 ``state["_memory"]``
- node 函数（如 ``validate_factor_spec``）从 state 取 ``_memory``，调用 ``memory.write(scope="groups", scope_id="factor", type="progress", key="last_run", body=...)``
- 后续 node（如 ``call_autoeval_api``）用 ``memory.search(query="PB-ROE", scope="groups", scope_id="factor")`` 拿历史
- 整个 flow 跑完后返回 ``{thread_id, artifacts, output_data, errors, state}``

与 ``runner/hello_world_example.py`` 区别：
- hello_world 只验证 checkpointer（最简 2 node）
- factor_autoeval_demo 验证 execute_compose_flow 集成 + Memory 注入 + 跨组权限 + 端到端产出

运行（必须用 ``-m`` 走包上下文，文件含相对 import）：

    cd quantcode/   # 到含 runner/ 的那一层
    python -m runner.factor_autoeval_demo

默认：使用 tmp 目录隔离的 db + ``.quantcode/memory/`` 根（不污染项目根）。

Owner: 尹一帆
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .compose_executor import (
    FLOW_REGISTRY,
    execute_compose_flow,
    get_memory,
    register_flow,
    unregister_flow,
)
from .langgraph_base import (
    BaseFlowState,
    create_workflow,
    default_compose_edges,
    get_checkpointer,
    clear_checkpointer_cache,
)
from .memory.service import MemoryService


# ---------------------------------------------------------------------------
# Demo 专用 state schema
# ---------------------------------------------------------------------------

class FactorFlowState(BaseFlowState):
    """factor:autoeval 专用 state 扩展（任务表 §2.1 期望形态）。

    扩展字段（皆非累加型 —— node 走覆盖语义）：
    - ``input_spec``：validate 节点输出
    - ``eval_result``：call_autoeval 节点输出
    - ``report``：generate_report 节点输出
    - ``_artifact_dir``：demo 内部用（artifact 写出目录）
    """

    input_spec: dict[str, Any]
    eval_result: dict[str, Any]
    report: dict[str, Any]
    _artifact_dir: str

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node 函数：参照任务表 §2.1 验收清单的 4 个 node
# ---------------------------------------------------------------------------

def _memory(state: FactorFlowState) -> Any:
    """从 state 拿当前 invoke 关联的 MemoryService。

    任务表 §2.2 期望 ``state["_memory"]`` 是 svc；langgraph 1.x checkpointer
    用 msgpack 序列化整个 state，MemoryService（含 sqlite3.Connection）不可
    序列化。compose_executor 把 ``state["_memory"]`` 放成 ``{"_tid": tid}``，
    真实 svc 走 :func:`get_memory`。调用方拿到的 final_state 已是真 svc（不在
    invoke 路径里），可直接 ``.search``。
    """
    handle = state.get("_memory")
    if not isinstance(handle, dict) or "_tid" not in handle:
        raise RuntimeError("validate_factor_spec: state 缺少 _memory handle")
    return get_memory(handle["_tid"])


def validate_factor_spec(state: FactorFlowState) -> dict[str, Any]:
    """node 1：验证因子 spec，幂等 — 不重复写 progress。"""
    memory = _memory(state)
    group = state["group"]

    # 1) 先看是否已跑过同 input（dedupe 验证点：memory 当作跨 invoke 的"缓存"）
    cached = memory.search(
        query=f"{state['input_data'].get('name', '')}",
        scope="groups",
        scope_id=group,
        type="progress",
        limit=1,
    )
    if cached and cached[0].snippet:
        return {
            "input_spec": state["input_data"],
            "errors": [f"validate_factor_spec: 命中 dedupe cache，跳过：{cached[0].path}"],
        }
    # 注意：上一分支已返回，下面才是 miss 路径。
    # 在这里再写一次以保持单一 return 出口简洁。

    # 2) 写一条 progress
    memory.write(
        scope="groups",
        scope_id=group,
        type="progress",
        key="factor_validation",
        body=(
            f"# validate_factor_spec\n\n"
            f"- factor_name: {state['input_data'].get('name')}\n"
            f"- validated_at: <ts>\n"
        ),
        requester_group=group,
    )

    return {"input_spec": state["input_data"]}


def call_autoeval_api(state: FactorFlowState) -> dict[str, Any]:
    """node 2：调 AutoEval（这里走 mock，参考任务表 §2.1 的 mock 模板）。"""
    _spec = state["input_spec"]  # noqa: F841  # 保留 spec 引用以便未来切到真实 AutoEval 客户端
    # 真实接入：autoeval_client.submit(spec)
    eval_result: dict[str, Any] = {
        "ic_mean": 0.045,
        "ir": 0.8,
        "turnover": 0.25,
        "decay_half_life": 5.2,
        "layered_backtest": {
            "quintile_1_return": 0.12,
            "quintile_5_return": -0.03,
        },
    }

    # 顺便：node 拿 history 上 AutoEval 的版本号
    memory = _memory(state)
    history = memory.search(
        query="autoeval_version",
        scope="groups",
        scope_id=state["group"],
        type="memory",
        limit=3,
    )
    if history:
        eval_result["historical_versions_count"] = len(history)

    return {"eval_result": eval_result}


def generate_factor_report(state: FactorFlowState) -> dict[str, Any]:
    """node 3：生成报告 + 写文件。"""
    spec = state["input_spec"]
    eval_result = state["eval_result"]

    # 产出文件（用 tmp_path 风格的目录，避免污染项目根）
    artifact_dir = Path(state.get("_artifact_dir") or tempfile.gettempdir())
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{spec.get('name', 'unknown')}-report.json"
    report = {
        "factor_name": spec.get("name"),
        "ic": eval_result["ic_mean"],
        "ir": eval_result["ir"],
        "turnover": eval_result["turnover"],
        "decay_half_life": eval_result["decay_half_life"],
        "layered_backtest": eval_result["layered_backtest"],
    }
    artifact_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 写一条 notes 到 Memory（量化组员后续会读）
    memory = _memory(state)
    memory.write(
        scope="groups",
        scope_id=state["group"],
        type="notes",
        key=f"factor_report_{spec.get('name', 'unknown')}",
        body=(
            f"# factor_report\n\n"
            f"- factor: {spec.get('name')}\n"
            f"- ic: {eval_result['ic_mean']}\n"
            f"- ir: {eval_result['ir']}\n"
            f"- artifact: {artifact_path}\n"
        ),
        requester_group=state["group"],
    )

    return {"report": report, "artifacts": [str(artifact_path)]}


def run_acceptance(state: FactorFlowState) -> dict[str, Any]:
    """node 4：验收（任务表 §2.1 模板：ic > 0.02, turnover < 0.3）。"""
    report = state["report"]
    if report["ic"] <= 0.02:
        raise AssertionError(f"IC too low: {report['ic']}")
    if report["turnover"] >= 0.3:
        raise AssertionError(f"Turnover too high: {report['turnover']}")
    return {"output_data": report}


# ---------------------------------------------------------------------------
# Self-check（端到端集成验证）
# ---------------------------------------------------------------------------

def _build_workflow() -> Any:
    """构造 4-node StateGraph。"""
    return create_workflow(
        nodes={
            "validate": validate_factor_spec,
            "call_autoeval": call_autoeval_api,
            "generate_report": generate_factor_report,
            "acceptance": run_acceptance,
        },
        edges=default_compose_edges(
            ["validate", "call_autoeval", "generate_report", "acceptance"]
        ),
        state_schema=FactorFlowState,
    ).compile(checkpointer=get_checkpointer())


def _run_e2e(
    *,
    db_path: Path,
    memory_root: Path,
    artifact_dir: Path,
    factor_name: str = "pb_roe",
) -> dict[str, Any]:
    """端到端跑一遍，校验：
    - execute_compose_flow 接受外部 caller 的调用
    - state["_memory"] 已被注入，4 个 node 都能用它
    - MemoryService 的 write / search 都通过 GROUP 隔离校验
    - 返回值结构齐
    """
    # 清掉之前的注册
    for key in list(FLOW_REGISTRY.keys()):
        unregister_flow(*key)

    # 准备 Memory
    if db_path.exists():
        db_path.unlink()
    memory_svc = MemoryService(
        db_path=db_path,
        root=memory_root,
        requester_group="factor",
    )

    # 注册 flow
    app = _build_workflow()
    register_flow("factor", "factor:autoeval", app)

    # 调用集成入口
    init_state = {
        "group": "factor",
        "flow_name": "factor:autoeval",
        "_artifact_dir": str(artifact_dir),
        "input_data": {"name": factor_name, "operators": ["pb", "roe"]},
    }

    result = execute_compose_flow(
        group="factor",
        flow_name="factor:autoeval",
        input_data=init_state["input_data"],
        thread_id=f"factor-autoeval-{factor_name}-demo",
        inject_memory=lambda g: memory_svc,
    )
    return result


def _self_check() -> int:
    """``python -m runner.factor_autoeval_demo`` 时触发。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 用 tmp 目录隔离，不污染项目根（避免 review 时被记录为"运行产物"）
    tmp_root = Path(tempfile.mkdtemp(prefix="factor_demo_"))
    db_path = tmp_root / "memory.db"
    # MemoryService.write 走 build_path(root=..., ".quantcode", "memory", ...)，
    # 所以 root 指**项目根**，service 自动加 .quantcode/memory 子目录
    memory_root = tmp_root
    artifact_dir = tmp_root / "artifacts"

    try:
        result = _run_e2e(
            db_path=db_path,
            memory_root=memory_root,
            artifact_dir=artifact_dir,
        )

        # 1) 顶部结构
        assert "thread_id" in result
        assert "artifacts" in result
        assert "output_data" in result
        assert "errors" in result
        assert "state" in result

        # 2) output_data 是 validate+autoeval+report 三步累计的结果
        out = result["output_data"]
        assert out["factor_name"] == "pb_roe", f"factor_name 错了：{out.get('factor_name')}"
        assert out["ic"] == 0.045
        assert out["ir"] == 0.8

        # 3) artifact 实际文件存在（artifacts 走 operator.add 累加，最末是本步产物）
        assert result["artifacts"], f"artifact 列表为空：{result['artifacts']}"
        art_path = Path(result["artifacts"][-1])
        assert art_path.is_file(), f"artifact 不存在：{art_path}"

        # 4) Memory 真的落了 .md（MimoCode 路径语义：type 存在 DB 列里，不进 path；
        #    service 自动在 root 下加 .quantcode/memory/）
        quantcode_root = memory_root / ".quantcode"
        progress_path = quantcode_root / "memory" / "groups" / "factor" / "factor_validation.md"
        notes_path = quantcode_root / "memory" / "groups" / "factor" / "factor_report_pb_roe.md"
        assert progress_path.is_file(), f"progress 未落盘：{progress_path}"
        assert notes_path.is_file(), f"notes 未落盘：{notes_path}"

        # 5) search 找得到（DB 真索引了）—— query 用宽松词（"factor_report"），
        #    notes body 里有 "# factor_report" 标题，能命中
        from .memory.service import MemoryService
        svc2 = MemoryService(db_path=db_path, root=memory_root, requester_group="factor")
        hits = svc2.search(
            query="factor_report",
            scope="groups",
            scope_id="factor",
            type="notes",
            limit=5,
        )
        assert hits, "search 没命中 notes"

        print("[factor_autoeval_demo self-check] OK")
        print(f"  thread_id   = {result['thread_id']}")
        print(f"  artifacts   = {result['artifacts']}")
        print(f"  output_data = {json.dumps(out, ensure_ascii=False)}")
        print(f"  errors      = {result['errors']}")
        print(f"  memory_dir  = {memory_root}")
        print(f"  search hits = {len(hits)}")
        return 0
    finally:
        # 清理（Windows 文件锁时 unlink 失败用 onerror）
        shutil.rmtree(tmp_root, ignore_errors=True)
        # 清理模块级 checkpointer 缓存
        clear_checkpointer_cache()


if __name__ == "__main__":
    sys.exit(_self_check())
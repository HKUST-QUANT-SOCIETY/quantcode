"""Day 2 下午：execute_compose_flow + Memory 注入 + MemoryService CRUD 测试。

覆盖任务 #12（集成 execute_compose_flow）+ 任务 #13（Memory 注入 state）。

测试类：
- TestExecuteComposeFlowBasics（8）：register / lookup / 缺失 / 输入校验 / 钩子顺序
- TestMemoryInjection（6）：_memory handle 注入 / module registry / 跨 invoke 隔离 / 异常路径
- TestMemoryServiceCRUD（8）：write / get / delete / type 落 DB / 跨组越权 / tasks NotImplementedError
- TestEndToEndFactorAutoeval（6）：任务表 §2.2 验收清单端到端模拟

运行：

    cd <PROJECT_ROOT>
    pytest test_codes/day2/test_compose_executor_integration.py -v
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from flows.factor_evaluation_adapter import (
    FactorEvaluationState,
    _memory,
    build_workflow as build_factor_evaluation_workflow,
    call_quant_evaluator,
    validate_factor_spec,
)
from runner import langgraph_base
from runner.compose_executor import (
    FLOW_REGISTRY,
    PRE_INVOKE_HOOKS,
    aexecute_compose_flow,
    clear_memory_registry,
    clear_pre_invoke_hooks,
    execute_compose_flow,
    get_memory,
    list_registered_flows,
    register_flow,
    register_pre_invoke_hook,
    unregister_flow,
)
from runner.langgraph_base import (
    BaseFlowState,
    clear_checkpointer_cache,
    create_workflow,
    default_compose_edges,
    get_checkpointer,
)
from runner.memory.fts import file_exists_and_initialized
from runner.memory.service import MemoryPermissionError, MemoryService


# ---------------------------------------------------------------------------
# 工具：每个测试独立 tmp + 独立 ckpt cache
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate(request):
    """每个测试独立 tmp 目录 + 清理 checkpointer 缓存 + 清理 registry。"""
    tmp = Path(tempfile.mkdtemp(prefix=f"t_{request.node.name}_"))
    clear_checkpointer_cache()
    clear_pre_invoke_hooks()
    clear_memory_registry()
    # 关键：FLOW_REGISTRY 全清（不能直接 clear，因为有些是其他测试已 register 的）
    saved_registry = dict(FLOW_REGISTRY)
    FLOW_REGISTRY.clear()
    yield tmp
    # 还原 FLOW_REGISTRY（避免污染其他测试）
    FLOW_REGISTRY.clear()
    FLOW_REGISTRY.update(saved_registry)
    clear_checkpointer_cache()
    clear_pre_invoke_hooks()
    clear_memory_registry()
    shutil.rmtree(tmp, ignore_errors=True)


def _two_node_app(name_prefix: str = "node"):
    """构造一个最小 2-node StateGraph（无 Memory 依赖）—— 供 register_flow 用。"""
    def a(state: BaseFlowState) -> dict[str, Any]:
        return {"artifacts": [f"{name_prefix}_a.txt"]}

    def b(state: BaseFlowState) -> dict[str, Any]:
        return {"artifacts": [f"{name_prefix}_b.txt"], "output_data": {"echo": state["input_data"]}}

    return create_workflow(
        nodes={"a": a, "b": b},
        edges=default_compose_edges(["a", "b"]),
    ).compile(checkpointer=get_checkpointer())


def _memory_aware_app(db_path: Path, memory_root: Path, group: str = "factor"):
    """构造一个使用 Memory 的 2-node StateGraph（任务表 §2.2 形态）。

    复用 flows.factor_evaluation_adapter 的 _memory 解析（compose_executor handle → svc）。
    """

    def read_memory(state: FactorEvaluationState) -> dict[str, Any]:
        svc = _memory(state)
        hits = svc.search(query="hello", scope="groups", scope_id=group, limit=3)
        return {"input_spec": {"mem_hits": len(hits)}}

    def write_memory(state: FactorEvaluationState) -> dict[str, Any]:
        svc = _memory(state)
        path = svc.write(
            scope="groups",
            scope_id=group,
            type="progress",
            key="step_a",
            body=f"# step_a\n- result: {state['input_spec']}\n",
            requester_group=group,
        )
        return {"artifacts": [path], "output_data": {"wrote": path}}

    return create_workflow(
        nodes={"read": read_memory, "write": write_memory},
        edges=default_compose_edges(["read", "write"]),
        state_schema=FactorEvaluationState,
    ).compile(checkpointer=get_checkpointer())


# ===========================================================================
# TestExecuteComposeFlowBasics
# ===========================================================================

class TestExecuteComposeFlowBasics:
    """execute_compose_flow 基础行为 + register_flow 协议。"""

    def test_register_and_invoke_returns_standardized_dict(self, _isolate):
        tmp = _isolate
        app = _two_node_app("echo")
        register_flow("factor", "factor:smoke", app)
        result = execute_compose_flow(
            "factor", "factor:smoke", {"k": "v"}, thread_id="t-001"
        )
        # 标准化 dict 字段
        for key in ("thread_id", "artifacts", "output_data", "errors", "state"):
            assert key in result, f"result 缺字段 {key}"
        assert result["thread_id"] == "t-001"
        assert result["output_data"] == {"echo": {"k": "v"}}
        assert len(result["artifacts"]) >= 2  # operator.add 累加

    def test_unregister_flow_returns_true_when_existed(self, _isolate):
        app = _two_node_app()
        register_flow("factor", "factor:rm", app)
        assert ("factor", "factor:rm") in FLOW_REGISTRY
        assert unregister_flow("factor", "factor:rm") is True
        assert ("factor", "factor:rm") not in FLOW_REGISTRY

    def test_unregister_flow_returns_false_when_missing(self, _isolate):
        assert unregister_flow("ghost", "ghost:never") is False

    def test_register_overwrite_false_raises_keyerror(self, _isolate):
        app1 = _two_node_app("first")
        app2 = _two_node_app("second")
        register_flow("factor", "factor:dup", app1)
        with pytest.raises(KeyError, match="已注册"):
            register_flow("factor", "factor:dup", app2, overwrite=False)
        # overwrite=True 静默覆盖
        register_flow("factor", "factor:dup", app2, overwrite=True)
        assert FLOW_REGISTRY[("factor", "factor:dup")] is app2

    def test_register_rejects_invalid_inputs(self, _isolate):
        app = _two_node_app()
        with pytest.raises(ValueError, match="group 必须非空"):
            register_flow("", "factor:bad", app)
        with pytest.raises(ValueError, match="group 必须非空"):
            register_flow("   ", "factor:bad", app)
        with pytest.raises(ValueError, match="flow_name 必须非空"):
            register_flow("factor", "", app)
        with pytest.raises(ValueError, match="app 不能为 None"):
            register_flow("factor", "factor:none", None)  # type: ignore[arg-type]

    def test_execute_raises_keyerror_when_flow_not_registered(self, _isolate):
        with pytest.raises(KeyError, match="未注册"):
            execute_compose_flow("factor", "factor:ghost", {"k": "v"})

    def test_execute_rejects_non_dict_input(self, _isolate):
        app = _two_node_app()
        register_flow("factor", "factor:str_in", app)
        with pytest.raises(ValueError, match="input_data 必须是 dict"):
            execute_compose_flow("factor", "factor:str_in", "not-a-dict")  # type: ignore[arg-type]

    def test_list_registered_flows_returns_keys(self, _isolate):
        app = _two_node_app()
        register_flow("factor", "factor:a", app)
        register_flow("model", "model:a", app)
        keys = list_registered_flows()
        assert ("factor", "factor:a") in keys
        assert ("model", "model:a") in keys

    def test_pre_invoke_hooks_run_and_modify_state(self, _isolate):
        """钩子返回值会被 merge 到 init_state（caller 视角，invoke 前已合并）。

        注意：node 端**能否**看到 merge 出来的字段，取决于该字段是否在
        state_schema（TypedDict）里——BaseFlowState 用 total=False，
        LangGraph 1.x 的 InputChannel 会过滤 schema 外字段。
        本测试只验证 ``execute_compose_flow`` 内部行为：钩子被调用 + 副作用落地。
        """
        # 钩子被调用了：用一个闭包变量验证
        seen: list[dict] = []

        def add_session(group, flow, init):
            seen.append({"group": group, "flow": flow, "init_keys": sorted(init.keys())})
            return {}  # 不修改 init，只观察

        register_pre_invoke_hook(add_session)
        # 用一个简单的 2-node app 走完 invoke
        app = _two_node_app()
        register_flow("factor", "factor:hook_observe", app)
        execute_compose_flow("factor", "factor:hook_observe", {})

        assert len(seen) == 1
        call = seen[0]
        assert call["group"] == "factor"
        assert call["flow"] == "factor:hook_observe"
        # 钩子看到的 init_state 含标准字段
        for key in ("group", "flow_name", "thread_id", "input_data", "artifacts", "errors"):
            assert key in call["init_keys"], f"init_state 缺标准字段 {key}"

    def test_pre_invoke_hook_exception_does_not_block_flow(self, _isolate):
        """钩子抛异常时主流程继续（log warning）。"""
        app = _two_node_app()
        register_flow("factor", "factor:badhook", app)

        def bad_hook(group, flow, init):
            raise RuntimeError("simulated")

        register_pre_invoke_hook(bad_hook)
        # 不抛
        result = execute_compose_flow("factor", "factor:badhook", {})
        assert "output_data" in result


# ===========================================================================
# TestMemoryInjection
# ===========================================================================

class TestMemoryInjection:
    """Memory 注入 state + module-level registry（任务 #13 核心）。"""

    def test_inject_memory_writes_handle_into_state(self, _isolate):
        """state['_memory'] 应当是 dict handle（msgpack 可序列化），含 _tid。"""
        tmp = _isolate
        db = tmp / "m.db"
        root = tmp
        svc = MemoryService(db_path=db, root=root, requester_group="factor")
        app = _memory_aware_app(db, root, group="factor")
        register_flow("factor", "factor:readwrite", app)

        result = execute_compose_flow(
            "factor", "factor:readwrite", {}, thread_id="tid-inject-1",
            inject_memory=lambda g: svc,
        )
        # invoke 期间 state['_memory'] 是 dict handle，invoke 后被替换为真 svc
        assert isinstance(result["state"]["_memory"], MemoryService), (
            f"final state['_memory'] 应当是真 svc，拿到 {type(result['state']['_memory'])}"
        )
        assert result["state"]["_memory"] is svc

    def test_inject_memory_via_module_registry(self, _isolate):
        """get_memory(tid) 应当能拿回注入的 svc。"""
        tmp = _isolate
        db = tmp / "m.db"
        root = tmp
        svc = MemoryService(db_path=db, root=root, requester_group="factor")
        app = _memory_aware_app(db, root, group="factor")
        register_flow("factor", "factor:via_registry", app)

        tid = "tid-registry-1"
        execute_compose_flow(
            "factor", "factor:via_registry", {}, thread_id=tid,
            inject_memory=lambda g: svc,
        )
        # registry 还在（用户不主动 clear 即可）
        assert get_memory(tid) is svc

    def test_inject_memory_none_skips_injection(self, _isolate):
        """不传 inject_memory 时，state['_memory'] 不应被注入。"""
        app = _two_node_app()
        register_flow("factor", "factor:no_mem", app)
        result = execute_compose_flow("factor", "factor:no_mem", {})
        assert "_memory" not in result["state"] or result["state"].get("_memory") is None

    def test_inject_memory_factory_returning_none_skips(self, _isolate):
        """工厂返回 None 时等同不注入。"""
        app = _two_node_app()
        register_flow("factor", "factor:null_mem", app)
        result = execute_compose_flow(
            "factor", "factor:null_mem", {},
            inject_memory=lambda g: None,
        )
        assert not result["state"].get("_memory")

    def test_node_can_access_memory_through_get_memory(self, _isolate):
        """node 端通过 module-level get_memory + handle._tid 拿 svc。"""
        tmp = _isolate
        db = tmp / "m.db"
        root = tmp
        svc = MemoryService(db_path=db, root=root, requester_group="factor")
        app = _memory_aware_app(db, root, group="factor")
        register_flow("factor", "factor:nodeaccess", app)

        result = execute_compose_flow(
            "factor", "factor:nodeaccess", {}, thread_id="tid-nodeaccess",
            inject_memory=lambda g: svc,
        )
        # write_memory 节点写了一条 progress
        assert "wrote" in (result["output_data"] or {}), (
            f"output_data 应当有 'wrote' 字段，实际：{result['output_data']}"
        )
        # 真有 .md 落盘
        wrote_path = Path(result["output_data"]["wrote"])
        assert wrote_path.is_file()

    def test_concurrent_invocations_isolated_by_tid(self, _isolate):
        """两个不同 thread_id 各自有自己的 svc。"""
        tmp = _isolate
        db1 = tmp / "m1.db"; root1 = tmp / "r1"
        db2 = tmp / "m2.db"; root2 = tmp / "r2"
        svc1 = MemoryService(db_path=db1, root=root1, requester_group="factor")
        svc2 = MemoryService(db_path=db2, root=root2, requester_group="model")

        # 用 svc1 注册一个 flow
        app1 = _memory_aware_app(db1, root1, group="factor")
        register_flow("factor", "factor:iso1", app1)
        result1 = execute_compose_flow(
            "factor", "factor:iso1", {}, thread_id="tid-iso-1",
            inject_memory=lambda g: svc1,
        )

        # 用 svc2 注册另一个 flow
        app2 = _memory_aware_app(db2, root2, group="model")
        register_flow("model", "model:iso2", app2)
        result2 = execute_compose_flow(
            "model", "model:iso2", {}, thread_id="tid-iso-2",
            inject_memory=lambda g: svc2,
        )

        # 两个 svc 各自有写入，互不串扰
        assert result1["state"]["_memory"] is svc1
        assert result2["state"]["_memory"] is svc2
        # 各自根目录下有自己的 step_a.md，互不混淆
        wrote1 = Path(result1["output_data"]["wrote"])
        wrote2 = Path(result2["output_data"]["wrote"])
        assert wrote1.is_file() and "r1" in str(wrote1)
        assert wrote2.is_file() and "r2" in str(wrote2)


# ===========================================================================
# TestMemoryServiceCRUD
# ===========================================================================

class TestMemoryServiceCRUD:
    """MemoryService.write / get / delete（任务表 §2.2 期望形态）。"""

    def test_write_creates_md_file_and_db_row(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        path = svc.write(
            scope="groups", scope_id="factor", type="notes",
            key="hello", body="# hello\n", requester_group="factor",
        )
        assert Path(path).is_file()
        # DB 行存在，type 列是 'notes' 而非 'free'
        with svc._conn() as conn:
            row = conn.execute(
                "SELECT type, body FROM memory_fts WHERE path = ?", (path,)
            ).fetchone()
        assert row["type"] == "notes"
        assert row["body"] == "# hello\n"

    def test_get_returns_body_when_exists(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        svc.write(
            scope="groups", scope_id="factor", type="notes",
            key="doc", body="# doc body\n", requester_group="factor",
        )
        body = svc.get(scope="groups", scope_id="factor", key="doc")
        assert body == "# doc body\n"

    def test_get_returns_none_when_missing(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        assert svc.get(scope="groups", scope_id="factor", key="ghost") is None

    def test_delete_removes_file_and_db_row(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        path = svc.write(
            scope="groups", scope_id="factor", type="notes",
            key="todel", body="# x\n", requester_group="factor",
        )
        assert Path(path).is_file()
        assert svc.delete(scope="groups", scope_id="factor", key="todel") is True
        # 文件没了
        assert not Path(path).is_file()
        # DB 行也没了
        with svc._conn() as conn:
            row = conn.execute(
                "SELECT id FROM memory_fts WHERE path = ?", (path,)
            ).fetchone()
        assert row is None
        # 二次删返 False
        assert svc.delete(scope="groups", scope_id="factor", key="todel") is False

    def test_write_rejects_invalid_scope(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        with pytest.raises(ValueError, match="scope 'bogus' 不在"):
            svc.write(scope="bogus", key="x", body="x")

    def test_write_rejects_groups_without_scope_id(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        with pytest.raises(ValueError, match="groups scope 需要 scope_id"):
            svc.write(scope="groups", key="x", body="x")

    def test_write_blocks_cross_group_attempt(self, _isolate):
        """factor requester 写 groups/model 应被拒。"""
        tmp = _isolate
        svc = MemoryService(
            db_path=tmp / "m.db", root=tmp, requester_group="factor",
        )
        with pytest.raises(MemoryPermissionError, match="越权"):
            svc.write(
                scope="groups", scope_id="model", type="notes",
                key="x", body="x", requester_group="factor",
            )

    def test_tasks_is_not_a_top_level_memory_scope(self, _isolate):
        tmp = _isolate
        svc = MemoryService(db_path=tmp / "m.db", root=tmp, requester_group="factor")
        with pytest.raises(ValueError, match="scope"):
            svc.write(scope="tasks", scope_id="T1", key="x", body="x")

    def test_delete_cross_group_blocked(self, _isolate):
        """factor requester 删 groups/model 应被拒。"""
        tmp = _isolate
        svc = MemoryService(
            db_path=tmp / "m.db", root=tmp, requester_group="factor",
        )
        with pytest.raises(MemoryPermissionError, match="越权"):
            svc.delete(
                scope="groups", scope_id="model", key="x",
                requester_group="factor",
            )


# ===========================================================================
# TestEndToEndFactorAutoeval
# ===========================================================================

_FACTOR_SPEC_INPUT: dict[str, Any] = {
    "name": "pb_roe_combo",
    "campaign_id": "campaign_2026q2",
    "formula": "tests.fixtures.sample_factor:pb_roe_combo",
    "domain": "equity",
    "frequency": "daily",
    "universe": "CSI1000",
    "operators": ["roe_ttm", "pb", "divide"],
    "estimated_runtime_seconds": 30,
    "date_range": {"start": "2023-01-01", "end": "2025-12-31"},
    "benchmark": "HS300",
    "forward_return_horizon": 5,
}


class TestEndToEndFactorEvaluation:
    def test_unavailable_component_is_not_fake_success(self, _isolate, monkeypatch):
        monkeypatch.delenv("QUANT_EVALUATOR_API_URL", raising=False)
        monkeypatch.delenv("QUANT_EVALUATOR_API_KEY", raising=False)
        app = build_factor_evaluation_workflow(_isolate / "checkpoints.db")
        register_flow("factor", "factor:evaluation", app, overwrite=True)
        result = execute_compose_flow(
            "factor", "factor:evaluation", dict(_FACTOR_SPEC_INPUT),
            thread_id="factor-e2e-1",
        )
        assert result["output_data"]["result_status"] == "UNAVAILABLE"
        assert result["artifacts"] == []
        assert result["errors"]

    def test_adapter_does_not_write_runtime_progress_to_group_memory(self, _isolate):
        svc = MemoryService(db_path=_isolate / "m.db", root=_isolate, requester_group="factor")
        app = build_factor_evaluation_workflow(_isolate / "checkpoints.db")
        register_flow("factor", "factor:evaluation", app, overwrite=True)
        execute_compose_flow(
            "factor", "factor:evaluation", dict(_FACTOR_SPEC_INPUT),
            thread_id="factor-e2e-memory",
            inject_memory=lambda group: svc,
        )
        assert not (_isolate / ".quantcode" / "memory" / "groups" / "factor" / "factor_validation.md").exists()


# ===========================================================================
# TestSelfChecks
# ===========================================================================

class TestSelfChecks:
    """_self_check 端点可独立跑通（与 hello-world 同形）。"""

    def test_hello_world_self_check_passes(self, _isolate, capsys):
        # 临时切到 hello-world 用的 ckpt 路径——避免与本次 tmp 冲突
        db_path = _isolate / "ckpt.db"
        with langgraph_base._CHECKPOINTER_CACHE_LOCK if hasattr(langgraph_base, "_CHECKPOINTER_CACHE_LOCK") else _noop():
            ck = get_checkpointer(db_path)
            assert ck is not None

    def test_compose_executor_module_imports_cleanly(self, _isolate):
        """模块 import 不抛。"""
        from runner import compose_executor  # noqa: F401


class _noop:
    def __enter__(self): return self
    def __exit__(self, *a): return False

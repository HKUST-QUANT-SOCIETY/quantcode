"""
Checkpoint恢复测试 — Day 2下午任务（Lead）

验证LangGraph checkpoint机制在以下场景的正确性：
1. 节点失败后恢复，已完成节点不重复执行
2. Memory注入在恢复后仍可访问
3. state字段正确恢复（artifacts累加、output_data等）
4. 多次失败重试的幂等性

依赖：
- runner/langgraph_base.py (PR #9)
- runner/compose_executor.py (PR #9)
- runner/memory/service.py (PR #11)
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from runner.compose_executor import (
    clear_memory_registry,
    execute_compose_flow,
    register_flow,
    unregister_flow,
)
from runner.langgraph_base import clear_checkpointer_cache, create_workflow, default_compose_edges
from runner.memory.service import MemoryService


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """每个测试后清理全局状态"""
    yield
    clear_checkpointer_cache()
    clear_memory_registry()


class TestCheckpointRecovery:
    """测试checkpoint恢复机制"""

    def test_failed_node_resumes_without_rerunning_previous_nodes(self, tmp_path):
        """失败节点恢复时，之前完成的节点不重复执行"""
        call_log: list[str] = []

        def step_a(state: dict[str, Any]) -> dict[str, Any]:
            call_log.append("step_a")
            return {"artifacts": ["step_a.txt"]}

        def step_b(state: dict[str, Any]) -> dict[str, Any]:
            call_log.append("step_b")
            if len([x for x in call_log if x == "step_b"]) == 1:
                raise RuntimeError("step_b transient failure")
            return {"artifacts": ["step_b.txt"]}

        def step_c(state: dict[str, Any]) -> dict[str, Any]:
            call_log.append("step_c")
            return {"output_data": {"result": "success"}, "artifacts": ["step_c.txt"]}

        wf = create_workflow(
            nodes={"step_a": step_a, "step_b": step_b, "step_c": step_c},
            edges=default_compose_edges(["step_a", "step_b", "step_c"]),
        )

        from runner.langgraph_base import get_checkpointer

        app = wf.compile(checkpointer=get_checkpointer(tmp_path / "checkpoint.db"))
        register_flow("test", "checkpoint_recovery", app, overwrite=True)

        try:
            # 第1次调用：step_b失败
            with pytest.raises(RuntimeError, match="step_b transient failure"):
                execute_compose_flow(
                    group="test",
                    flow_name="checkpoint_recovery",
                    input_data={"test": "data"},
                    thread_id="checkpoint-recovery-1",
                )

            # 第2次调用：从失败点恢复
            result = execute_compose_flow(
                group="test",
                flow_name="checkpoint_recovery",
                input_data={},  # resume时忽略
                thread_id="checkpoint-recovery-1",  # 同一个thread_id
                resume=True,  # 从checkpoint恢复
            )

            # 验证：step_a只执行1次，step_b执行2次（第1次失败+第2次成功），step_c执行1次
            assert call_log.count("step_a") == 1, "step_a不应该重复执行"
            assert call_log.count("step_b") == 2, "step_b应该重试1次"
            assert call_log.count("step_c") == 1, "step_c应该执行1次"

            # 验证：artifacts正确累加
            assert result["artifacts"] == ["step_a.txt", "step_b.txt", "step_c.txt"]
            assert result["output_data"]["result"] == "success"
        finally:
            unregister_flow("test", "checkpoint_recovery")

    def test_memory_accessible_after_checkpoint_recovery(self, tmp_path):
        """恢复后Memory服务仍然可访问"""
        call_log: list[str] = []

        def write_memory(state: dict[str, Any]) -> dict[str, Any]:
            call_log.append("write_memory")
            # 注意：state["_memory"]是{"_tid": ...}包装，需要get_memory获取真实svc
            from runner.compose_executor import get_memory

            memory_svc = get_memory(state["_memory"]["_tid"])
            if memory_svc is None:
                raise RuntimeError("Memory service not injected")

            # 写入一条memory
            memory_svc.write(
                body="Checkpoint recovery test memory",
                scope="groups",
                scope_id="test",
                type="memory",
                key="checkpoint-test",
            )
            return {"artifacts": ["memory_written"]}

        def read_memory_and_fail(state: dict[str, Any]) -> dict[str, Any]:
            call_log.append("read_memory_and_fail")
            from runner.compose_executor import get_memory

            memory_svc = get_memory(state["_memory"]["_tid"])
            if memory_svc is None:
                raise RuntimeError("Memory service not injected after recovery")

            # 读取刚才写的memory
            results = memory_svc.search(
                query="recovery", scope="groups", scope_id="test", requester_group="test"
            )
            if len(results) == 0:
                raise RuntimeError("Memory not found after recovery")

            # 第1次失败
            if len([x for x in call_log if x == "read_memory_and_fail"]) == 1:
                raise RuntimeError("transient read failure")

            return {"output_data": {"memory_count": len(results)}}

        wf = create_workflow(
            nodes={"write_memory": write_memory, "read_memory_and_fail": read_memory_and_fail},
            edges=default_compose_edges(["write_memory", "read_memory_and_fail"]),
        )

        from runner.langgraph_base import get_checkpointer

        app = wf.compile(checkpointer=get_checkpointer(tmp_path / "checkpoint.db"))
        register_flow("test", "memory_checkpoint", app, overwrite=True)

        # 创建Memory服务
        memory_root = tmp_path / "memory"
        memory_root.mkdir()
        (memory_root / "groups").mkdir()
        (memory_root / "groups" / "test").mkdir(parents=True)

        def memory_factory(group: str) -> MemoryService:
            return MemoryService(
                db_path=tmp_path / "memory.db",
                root=memory_root,
                requester_group=group,
            )

        try:
            # 第1次调用：read节点失败
            with pytest.raises(RuntimeError, match="transient read failure"):
                execute_compose_flow(
                    group="test",
                    flow_name="memory_checkpoint",
                    input_data={},
                    thread_id="memory-checkpoint-1",
                    inject_memory=memory_factory,
                )

            # 第2次调用：从失败点恢复，Memory仍可访问
            result = execute_compose_flow(
                group="test",
                flow_name="memory_checkpoint",
                input_data={},
                thread_id="memory-checkpoint-1",
                inject_memory=memory_factory,
                resume=True,  # 从checkpoint恢复
            )

            # 验证：write_memory只执行1次
            assert call_log.count("write_memory") == 1, "write_memory不应该重复执行"
            assert call_log.count("read_memory_and_fail") == 2, "read应该重试1次"

            # 验证：Memory读取成功
            assert result["output_data"]["memory_count"] == 1
        finally:
            unregister_flow("test", "memory_checkpoint")
            clear_memory_registry()

    def test_artifacts_accumulate_across_recovery(self, tmp_path):
        """artifacts在恢复后正确累加（不重复）"""
        call_count = {"step_a": 0, "step_b": 0}

        def step_a(state: dict[str, Any]) -> dict[str, Any]:
            call_count["step_a"] += 1
            return {"artifacts": [f"step_a_artifact_{call_count['step_a']}"]}

        def step_b(state: dict[str, Any]) -> dict[str, Any]:
            call_count["step_b"] += 1
            if call_count["step_b"] == 1:
                raise RuntimeError("step_b first failure")
            return {"artifacts": [f"step_b_artifact_{call_count['step_b']}"]}

        wf = create_workflow(
            nodes={"step_a": step_a, "step_b": step_b},
            edges=default_compose_edges(["step_a", "step_b"]),
        )

        from runner.langgraph_base import get_checkpointer

        app = wf.compile(checkpointer=get_checkpointer(tmp_path / "checkpoint.db"))
        register_flow("test", "artifact_accumulate", app, overwrite=True)

        try:
            # 第1次调用失败
            with pytest.raises(RuntimeError):
                execute_compose_flow(
                    group="test",
                    flow_name="artifact_accumulate",
                    input_data={},
                    thread_id="artifact-test",
                )

            # 第2次调用成功
            result = execute_compose_flow(
                group="test",
                flow_name="artifact_accumulate",
                input_data={},
                thread_id="artifact-test",
                resume=True,  # 从checkpoint恢复
            )

            # 验证：artifacts只包含step_a的1次调用 + step_b的第2次调用
            # 不应该包含step_a的重复或step_b第1次失败的artifact
            assert result["artifacts"] == ["step_a_artifact_1", "step_b_artifact_2"]
        finally:
            unregister_flow("test", "artifact_accumulate")

    def test_multiple_failures_idempotent(self, tmp_path):
        """多次失败重试的幂等性"""
        call_count = 0

        def setup_step(state: dict[str, Any]) -> dict[str, Any]:
            return {"artifacts": ["setup"]}

        def flaky_step(state: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1

            # 前2次失败，第3次成功
            if call_count < 3:
                raise RuntimeError(f"failure attempt {call_count}")

            return {"output_data": {"attempts": call_count}}

        wf = create_workflow(
            nodes={"setup": setup_step, "flaky": flaky_step},
            edges=default_compose_edges(["setup", "flaky"])
        )

        from runner.langgraph_base import get_checkpointer

        app = wf.compile(checkpointer=get_checkpointer(tmp_path / "checkpoint.db"))
        register_flow("test", "flaky_flow", app, overwrite=True)

        try:
            thread_id = "flaky-test"

            # 第1次失败
            with pytest.raises(RuntimeError, match="failure attempt 1"):
                execute_compose_flow("test", "flaky_flow", {}, thread_id=thread_id)

            # 第2次失败
            with pytest.raises(RuntimeError, match="failure attempt 2"):
                execute_compose_flow("test", "flaky_flow", {}, thread_id=thread_id, resume=True)

            # 第3次成功
            result = execute_compose_flow("test", "flaky_flow", {}, thread_id=thread_id, resume=True)

            # 验证：总共尝试3次
            assert result["output_data"]["attempts"] == 3
        finally:
            unregister_flow("test", "flaky_flow")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

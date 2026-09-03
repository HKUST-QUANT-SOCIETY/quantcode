"""test_agent_mcp_tool.py — run_agent MCP tool 的单元测试 — Day 4 俞高磊。

测试 run_agent tool 的 schema 校验、错误处理（无 group、无 model）、
正常执行（mock AgentRunner）、以及 _meta flag。
"""
from __future__ import annotations

from runner.agent_mcp_tool import (
    RunAgentArgs,
    _format_result,
    _run_agent_execute,
    run_agent_tool,
)


class TestRunAgentArgs:
    """RunAgentArgs schema 校验。"""

    def test_minimal_args(self):
        """只需 task 就能创建。"""
        args = RunAgentArgs(task="test task")
        assert args.task == "test task"
        assert args.skill_name is None
        assert args.max_iterations == 50

    def test_full_args(self):
        """所有字段都可传。"""
        args = RunAgentArgs(task="complex task", skill_name="model-pr-submit", max_iterations=30)
        assert args.task == "complex task"
        assert args.skill_name == "model-pr-submit"
        assert args.max_iterations == 30

    def test_missing_task_fails(self):
        """task 是必填字段 — Day 7: task 现在是 optional（resume 模式不需要传 task）。"""
        args = RunAgentArgs()
        assert args.task is None
        assert args.decision is None

    def test_max_iterations_default(self):
        """不传 max_iterations 时默认为 50。"""
        args = RunAgentArgs(task="test")
        assert args.max_iterations == 50


class TestRunAgentExecuteErrors:
    """run_agent 的错误处理。"""

    def test_no_group_returns_error(self):
        """ctx 中没有 group → 返回 error status。"""
        result = _run_agent_execute(
            RunAgentArgs(task="test"),
            ctx={},
        )
        assert result["status"] == "error"
        assert "QUANTCODE_GROUP" in result["error"]

    def test_group_empty_string_returns_error(self):
        """group 为空字符串 → 返回 error status。"""
        result = _run_agent_execute(
            RunAgentArgs(task="test"),
            ctx={"group": ""},
        )
        assert result["status"] == "error"

    def test_request_group_cannot_override_authenticated_session(self):
        """请求参数不能把已认证 session 改成另一个业务组。"""
        result = _run_agent_execute(
            RunAgentArgs(task="test", group="risk"),
            ctx={"group": "model", "_model": object()},
        )
        assert result["status"] == "error"
        assert "group mismatch" in result["error"]

    def test_no_model_returns_error(self, monkeypatch):
        """ctx 中有 group 但没有 _model，且 fallback _get_model 也返回 None → 返回 error。"""
        import quantcode.mcp_server as _mcp
        monkeypatch.setattr(_mcp, "_get_model", lambda: None)
        result = _run_agent_execute(
            RunAgentArgs(task="test"),
            ctx={"group": "model", "_model": None},
        )
        assert result["status"] == "error"
        assert "API" in result["error"] or "model" in result["error"].lower()

    def test_start_without_task_returns_error(self):
        """start mode 需要 task，否则返回 error。"""
        result = _run_agent_execute(
            RunAgentArgs(),
            ctx={"group": "risk"},
        )
        assert result["status"] == "error"
        assert "task" in result["error"].lower()

    def test_resume_without_thread_id_returns_error(self, monkeypatch):
        """resume mode 需要 thread_id，否则返回 error。"""
        # model check happens before thread_id check in _resume_mode,
        # so we need to pass a dummy model to bypass the model gate.
        dummy_model = lambda x: type("msg", (), {"content": "", "tool_calls": []})()
        result = _run_agent_execute(
            RunAgentArgs(decision="approve"),
            ctx={"group": "risk", "_model": dummy_model},
        )
        assert result["status"] == "error"
        assert "thread_id" in result["error"].lower()


class TestFormatResult:
    """_format_result 的状态提取。"""

    def test_empty_state(self):
        """空 state → 返回默认值。"""
        result = _format_result({}, "model")
        assert result["status"] == "stopped"
        assert result["iterations"] == 0
        assert result["final_message"] == ""
        assert result["tool_calls"] == []

    def test_task_done_state(self):
        """task_status=done → status=completed。"""
        state = {
            "task_status": "done",
            "iterations": 3,
            "thread_id": "tid-1",
            "messages": [],
        }
        result = _format_result(state, "model")
        assert result["status"] == "completed"
        assert result["iterations"] == 3
        assert result["thread_id"] == "tid-1"

    def test_includes_risk_metrics(self):
        """state 有 risk_metrics → 包含在结果中。"""
        state = {"messages": [], "risk_metrics": {"var_99": 0.08}}
        result = _format_result(state, "model")
        assert result["risk_metrics"] == {"var_99": 0.08}

    def test_includes_execution_trace(self):
        """state 有 execution_trace → 包含在结果中。"""
        trace = [{"type": "agent_start", "group": "model", "task": "test"}]
        state = {"messages": [], "execution_trace": trace}
        result = _format_result(state, "model")
        assert result["execution_trace"] == trace

    def test_includes_day4_state_backflow_fields(self):
        """Day4 状态回流字段：output_data / artifacts / gate / errors。"""
        state = {
            "messages": [],
            "output_data": {"ok": True},
            "artifacts": ["a.txt"],
            "gate": {"kind": "human_gate"},
            "errors": ["err"],
        }
        result = _format_result(state, "risk")
        assert result["output_data"] == {"ok": True}
        assert result["artifacts"] == ["a.txt"]
        assert result["gate"] == {"kind": "human_gate"}
        assert result["errors"] == ["err"]


class TestRunAgentToolDef:
    """run_agent ToolDef 元数据。"""

    def test_tool_id_is_run_agent(self):
        """ToolDef id 正确。"""
        assert run_agent_tool.id == "run_agent"

    def test_tool_is_meta(self):
        """_meta=True，不会被 list_tools() 暴露给 LLM。"""
        assert getattr(run_agent_tool, "_meta", False) is True

    def test_tool_has_schema(self):
        """schema 是 RunAgentArgs。"""
        assert run_agent_tool.schema is RunAgentArgs

    def test_tool_has_description(self):
        """有非空描述。"""
        assert len(run_agent_tool.description) > 20

    def test_tool_has_execute(self):
        """execute 是可调用的。"""
        assert callable(run_agent_tool.execute)

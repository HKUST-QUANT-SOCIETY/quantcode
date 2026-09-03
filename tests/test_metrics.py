"""runner/metrics 单测 — 写读聚合、best-effort 容错、list_runs MCP 注册。

metrics 钩子是 best-effort 旁路：这里同时验证它绝不抛错、绝不污染主流程。
"""
from __future__ import annotations

import json

import pytest

from runner import metrics


@pytest.fixture(autouse=True)
def _tmp_metrics(monkeypatch, tmp_path):
    """把 METRICS_PATH 指到 tmp，测试间彻底隔离。"""
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", path)
    yield path


# ---------------------------------------------------------------------------
# record_run → read_recent
# ---------------------------------------------------------------------------


def test_record_run_and_read_recent_roundtrip():
    metrics.record_run(
        group="model",
        flow="mcp_compose",
        thread_id="t-1",
        started_at=100.0,
        ended_at=102.5,
        status="completed",
        trace_events=[
            {"type": "llm_thought", "data": {"content": "thinking"}},
            {"type": "tool_call", "data": {"tool": "read_pr", "args": {}}},
            {"type": "tool_result", "data": {"result": "ok"}},
            {"type": "tool_call", "data": {"tool": "calc_risk", "args": {}}},
        ],
    )
    rows = metrics.read_recent()
    assert len(rows) == 1
    row = rows[0]
    assert row["group"] == "model"
    assert row["flow"] == "mcp_compose"
    assert row["thread_id"] == "t-1"
    assert row["duration_s"] == 2.5
    assert row["status"] == "completed"
    assert row["error"] is None
    assert row["tool_calls"] == 2
    assert row["llm_thoughts"] == 1
    assert isinstance(row["context_chars"], int) and row["context_chars"] > 0
    assert isinstance(row["ts"], float)


def test_record_run_appends_multiple_lines():
    for i in range(3):
        metrics.record_run(
            group="risk", flow="agent", thread_id=f"t-{i}",
            started_at=1.0 * i, ended_at=1.0 * i + 0.5, status="completed",
        )
    rows = metrics.read_recent(limit=2)
    assert len(rows) == 2
    # read_recent 按文件顺序（旧→新），limit 取末尾两条
    assert [r["thread_id"] for r in rows] == ["t-1", "t-2"]


def test_record_run_with_error():
    metrics.record_run(
        group="factor", flow="agent", thread_id="t-e",
        started_at=0.0, ended_at=1.0, status="error", error="ValueError: bad",
    )
    row = metrics.read_recent()[0]
    assert row["status"] == "error"
    assert row["error"] == "ValueError: bad"


def test_record_run_context_chars_passthrough():
    metrics.record_run(
        group="model", flow="agent", thread_id="t",
        started_at=0.0, ended_at=1.0, status="completed", context_chars=1234,
    )
    assert metrics.read_recent()[0]["context_chars"] == 1234


def test_estimate_context_chars_counts_data_values():
    trace = [
        {"type": "llm_thought", "data": {"content": "abcd"}},
        {"type": "tool_call", "data": {"tool": "x", "args": {"a": 1}}},
        "not-a-dict",
    ]
    est = metrics.estimate_context_chars(trace)
    # 事件 data 的序列化长度之和：len("abcd")=4 + len("x")+len("{'a': 1}")>0
    assert est >= 4
    assert metrics.estimate_context_chars(None) is None
    assert metrics.estimate_context_chars([]) is None


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def test_aggregate_stats_and_by_group():
    rows = [
        ("model", "completed", 1.0),
        ("model", "completed", 3.0),
        ("risk", "error", 2.0),
        ("risk", "stopped", 4.0),
    ]
    for i, (g, s, d) in enumerate(rows):
        metrics.record_run(
            group=g, flow="agent", thread_id=f"t-{i}",
            started_at=0.0, ended_at=d, status=s,
            error="boom" if s == "error" else None,
        )
    agg = metrics.aggregate(window=10)
    assert agg["runs"] == 4
    assert agg["success_rate"] == 0.5
    assert agg["error_rate"] == 0.25
    assert agg["avg_duration_s"] == 2.5
    assert agg["by_group"]["model"]["runs"] == 2
    assert agg["by_group"]["model"]["success"] == 2
    assert agg["by_group"]["model"]["avg_duration_s"] == 2.0
    assert agg["by_group"]["risk"]["errors"] == 1
    assert agg["by_group"]["risk"]["avg_duration_s"] == 3.0


def test_aggregate_empty(tmp_path):
    agg = metrics.aggregate()
    assert agg == {
        "runs": 0, "success_rate": 0.0, "avg_duration_s": 0.0,
        "error_rate": 0.0, "by_group": {},
    }


def test_aggregate_window_limits_rows(tmp_path):
    for i in range(30):
        metrics.record_run(
            group="model", flow="agent", thread_id=f"t-{i}",
            started_at=0.0, ended_at=1.0, status="completed",
        )
    assert metrics.aggregate(window=20)["runs"] == 20
    assert metrics.aggregate(window=5)["runs"] == 5


# ---------------------------------------------------------------------------
# best-effort 容错：绝不抛错
# ---------------------------------------------------------------------------


def test_read_recent_missing_file_returns_empty(tmp_path):
    # fixture 已把 METRICS_PATH 指到不存在的 tmp 路径
    assert metrics.read_recent() == []


def test_read_recent_skips_corrupt_lines(tmp_path):
    path = tmp_path / "metrics.jsonl"
    path.write_text(
        json.dumps({"group": "model", "status": "completed"}) + "\n"
        + "{corrupt json\n"
        + json.dumps({"group": "risk", "status": "error"}) + "\n",
        encoding="utf-8",
    )
    rows = metrics.read_recent()
    assert len(rows) == 2
    assert rows[0]["group"] == "model"


def test_record_run_swallows_io_errors(monkeypatch, tmp_path):
    # 让 mkdir 抛错 → record_run 仍然静默
    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(metrics.METRICS_PATH.__class__, "mkdir", _boom)
    metrics.record_run(
        group="model", flow="agent", thread_id="t",
        started_at=0.0, ended_at=1.0, status="completed",
    )  # 不应抛错
    assert metrics.read_recent() == []


def test_record_run_tolerates_bad_start_end_types(tmp_path):
    metrics.record_run(
        group="model", flow="agent", thread_id="t",
        started_at=None, ended_at="not-a-number", status="completed",
    )
    row = metrics.read_recent()[0]
    assert row["duration_s"] is None


# ---------------------------------------------------------------------------
# mcp_server 注册段：list_runs 可列出、可调用
# ---------------------------------------------------------------------------


def test_mcp_list_runs_registered_and_callable(tmp_path, monkeypatch):
    """list_runs 走 run_agent 同款 _meta 通道：不在 allowlist 也应被 tools/list 列出。"""
    import importlib

    monkeypatch.setenv("QUANTCODE_GROUP", "model")
    import quantcode.mcp_server as mcp_server

    importlib.reload(mcp_server)

    # 1) tools/list 含 list_runs（meta 通道，model allowlist 里没有它）
    tool_names = {t["name"] for t in mcp_server.list_tools()["tools"]}
    assert "list_runs" in tool_names

    # 2) tools/call 真跑：写两条记录后读回
    metrics.record_run(
        group="model", flow="agent", thread_id="t-mcp",
        started_at=0.0, ended_at=1.0, status="completed",
    )
    result = mcp_server.call_tool("list_runs", {"limit": 10})
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["aggregate"]["runs"] == 1
    assert payload["aggregate"]["by_group"]["model"]["runs"] == 1
    assert any(r["thread_id"] == "t-mcp" for r in payload["recent_runs"])

    # 3) 参数校验：limit 越界报错
    bad = mcp_server.call_tool("list_runs", {"limit": 0})
    assert bad["isError"] is True


def test_mcp_list_runs_scopes_to_session_group(tmp_path, monkeypatch):
    """普通 session 的 list_runs 只返回当前业务组记录。"""
    import importlib
    import quantcode.mcp_server as mcp_server

    monkeypatch.setenv("QUANTCODE_GROUP", "model")
    monkeypatch.setenv("QUANTCODE_ALLOW_UNAUTH", "1")
    importlib.reload(mcp_server)
    monkeypatch.setattr(metrics, "METRICS_PATH", tmp_path / "metrics.jsonl")
    metrics.record_run("model", "f", "model-1", 0.0, 1.0, "completed")
    metrics.record_run("risk", "f", "risk-1", 0.0, 1.0, "completed")
    result = mcp_server.call_tool("list_runs", {"limit": 10})
    payload = json.loads(result["content"][0]["text"])
    assert {row["group"] for row in payload["recent_runs"]} == {"model"}


def test_agent_engine_record_run_safe_never_raises():
    """_record_run_safe 在 record_run 抛错时静默（不影响主流程）。"""
    from runner import agent_engine

    def _boom(**kwargs):
        raise RuntimeError("metrics down")

    original = agent_engine.record_run if hasattr(agent_engine, "record_run") else None
    agent_engine.record_run = _boom  # type: ignore[attr-defined]
    try:
        agent_engine._record_run_safe(group="m", flow="f", thread_id="t",
                                      started_at=0.0, ended_at=1.0, status="completed")
    finally:
        if original is not None:
            agent_engine.record_run = original  # type: ignore[attr-defined]


def test_agent_engine_stream_records_metrics(tmp_path, monkeypatch):
    """端到端：AgentRunner.stream 完成后 metrics.jsonl 多一行。"""
    import importlib

    importlib.reload(metrics)  # 让 agent_engine 里绑定的符号指向同一模块对象
    monkeypatch.setattr(metrics, "METRICS_PATH", tmp_path / "metrics.jsonl")

    from runner.agent_engine import AgentRunner

    class MockLLM:
        def __call__(self, messages, tools=None):
            from langchain_core.messages import AIMessage

            return AIMessage(content="done, no tools needed")

    from tools.registry import ToolRegistry

    runner = AgentRunner(group="model", model=MockLLM(), registry=ToolRegistry())
    # 不传 skill_name：走默认 system prompt，避免依赖仓库内 skill fixture
    state = runner.stream(task="hello", thread_id="t-stream")
    assert state["thread_id"] == "t-stream"

    rows = metrics.read_recent()
    assert len(rows) == 1
    row = rows[0]
    assert row["group"] == "model"
    assert row["thread_id"] == "t-stream"
    assert row["status"] in ("completed", "stopped", "waiting_for_human")
    assert row["tool_calls"] == 0
    # MockLLM 每轮回一句 no-tool 响应，LLM 会迭代到 max_iterations → 多条 thought
    assert row["llm_thoughts"] >= 1
    assert row["duration_s"] >= 0

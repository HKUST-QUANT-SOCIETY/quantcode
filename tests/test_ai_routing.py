"""Tests for runner.routing.ai_router — LLM trace analyzer."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from runner.routing.ai_router import (
    TraceAnalysis,
    _build_messages,
    _format_trace,
    ai_analyze_trace,
)


# ---------------------------------------------------------------------------
# Trace formatting
# ---------------------------------------------------------------------------

class TestFormatTrace:
    def test_formats_steps(self):
        trace = [
            {"tool": "fetch_pr", "success": True, "result": "PR #42 diff"},
            {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
        ]
        text = _format_trace(trace)
        assert "step 1: fetch_pr → OK" in text
        assert "PR #42 diff" in text
        assert "step 2: extract_metadata → OK" in text

    def test_formats_failed_step(self):
        trace = [
            {"tool": "fetch_pr", "success": False, "error": "404 Not Found"},
        ]
        text = _format_trace(trace)
        assert "FAILED" in text
        assert "404 Not Found" in text

    def test_truncates_long_results(self):
        trace = [
            {"tool": "dump", "success": True, "result": "x" * 500},
        ]
        text = _format_trace(trace)
        assert len(text) < 500  # truncated

    def test_uses_tool_name_fallback(self):
        trace = [
            {"tool_name": "calc_risk", "success": True, "result": "ok"},
        ]
        text = _format_trace(trace)
        assert "calc_risk" in text


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_includes_task_goal_and_trace(self):
        msgs = _build_messages("Process PR #42", "step 1: fetch_pr → OK")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "Process PR #42" in msgs[1]["content"]
        assert "step 1: fetch_pr → OK" in msgs[1]["content"]

    def test_no_threshold_values_in_prompt(self):
        msgs = _build_messages("test", "trace")
        combined = msgs[0]["content"] + msgs[1]["content"]
        # No hardcoded numeric thresholds
        for forbidden in ["0.05", "0.15", "0.8", "MAX_ITERATIONS", "100"]:
            assert forbidden not in combined, (
                f"prompt should not contain threshold '{forbidden}'"
            )


# ---------------------------------------------------------------------------
# Mock StepFun API responses
# ---------------------------------------------------------------------------

def _make_mock_response(json_body: dict) -> dict:
    """Simulate a StepFun chat completion response."""
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(json_body),
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# ai_analyze_trace — success cases
# ---------------------------------------------------------------------------

class TestAiAnalyzeTraceNormal:
    """Normal execution — Agent is making progress."""

    @pytest.fixture(autouse=True)
    def _mock(self):
        with patch("runner.routing.ai_router.urllib.request.urlopen") as m:
            resp = _make_mock_response({
                "suspects_loop": False,
                "is_complete": False,
                "analysis": "Agent is making normal progress.",
            })
            self.mock_read = MagicMock()
            self.mock_read.decode.return_value = json.dumps(resp)
            self.mock_urlopen = m
            self.mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                self.mock_read
            )
            yield

    def test_normal_execution_continues(self):
        trace = [
            {"tool": "fetch_data", "success": True, "result": "data"},
            {"tool": "process", "success": True, "result": "processed"},
        ]
        result = ai_analyze_trace(trace, "Process data", api_key="test-key")
        assert result.suspects_loop is False
        assert result.is_complete is False
        assert result.fallback is False
        assert "normal" in result.analysis.lower()

    def test_complete_task_returns_finish(self):
        trace = [
            {"tool": "fetch_pr", "success": True, "result": "diff"},
            {"tool": "extract_metadata", "success": True, "result": "meta"},
            {"tool": "generate_spec", "success": True, "result": "spec"},
            {"tool": "write_blackboard", "success": True, "result": "written"},
        ]
        resp = _make_mock_response({
            "suspects_loop": False,
            "is_complete": True,
            "analysis": "All required artifacts produced. Task is complete.",
        })
        self.mock_urlopen.return_value.__enter__.return_value.read.return_value.decode.return_value = json.dumps(resp)

        result = ai_analyze_trace(trace, "Process PR and generate ModelSpec", api_key="test-key")
        assert result.is_complete is True
        assert result.suspects_loop is False


class TestAiAnalyzeTraceLoop:
    """Agent is stuck — should detect."""

    @pytest.fixture(autouse=True)
    def _mock(self):
        with patch("runner.routing.ai_router.urllib.request.urlopen") as m:
            resp = _make_mock_response({
                "suspects_loop": True,
                "is_complete": False,
                "analysis": "Same error repeats 7 times without Agent changing strategy.",
            })
            self.mock_urlopen = m
            self.mock_urlopen.return_value.__enter__.return_value.read.return_value.decode.return_value = (
                json.dumps(resp)
            )
            yield

    def test_stuck_agent_detected(self):
        trace = [
            {"tool": "validate_schema", "success": False, "error": "missing author"},
            {"tool": "extract_metadata", "success": True, "result": "meta"},
            {"tool": "validate_schema", "success": False, "error": "missing author"},
            {"tool": "extract_metadata", "success": True, "result": "meta"},
            {"tool": "validate_schema", "success": False, "error": "missing author"},
            {"tool": "extract_metadata", "success": True, "result": "meta"},
            {"tool": "validate_schema", "success": False, "error": "missing author"},
        ]
        result = ai_analyze_trace(trace, "Process PR", api_key="test-key")
        assert result.suspects_loop is True
        assert result.fallback is False


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------

class TestAiAnalyzeTraceFallback:
    def test_api_failure_falls_back(self):
        """Network error → fallback with conservative defaults."""
        with patch("runner.routing.ai_router.urllib.request.urlopen") as m:
            m.side_effect = OSError("Network unreachable")
            result = ai_analyze_trace(
                [{"tool": "test"}], "task", api_key="test-key",
            )
        assert result.fallback is True
        assert result.suspects_loop is False   # conservative: don't abort
        assert result.is_complete is False     # conservative: don't finish
        assert "fallback" in result.analysis.lower()

    def test_invalid_json_response_falls_back(self):
        """Malformed LLM response → fallback."""
        with patch("runner.routing.ai_router.urllib.request.urlopen") as m:
            bad_resp = {"choices": [{"message": {"content": "not-json"}}]}
            m.return_value.__enter__.return_value.read.return_value.decode.return_value = json.dumps(bad_resp)
            result = ai_analyze_trace(
                [{"tool": "test"}], "task", api_key="test-key",
            )
        assert result.fallback is True
        assert result.suspects_loop is False

    def test_missing_api_key_raises(self):
        """No key and no env var → the function falls back gracefully."""
        with patch("runner.routing.ai_router.os.environ", {}):
            result = ai_analyze_trace([{"tool": "test"}], "task", api_key=None)
        assert result.fallback is True


# ---------------------------------------------------------------------------
# TraceAnalysis dataclass
# ---------------------------------------------------------------------------

class TestTraceAnalysis:
    def test_defaults(self):
        ta = TraceAnalysis()
        assert ta.suspects_loop is False
        assert ta.is_complete is False
        assert ta.fallback is False
        assert ta.analysis == ""

    def test_field_assignment(self):
        ta = TraceAnalysis(
            suspects_loop=True,
            analysis="Agent is stuck in A→B loop.",
            fallback=False,
        )
        assert ta.suspects_loop is True
        assert ta.is_complete is False

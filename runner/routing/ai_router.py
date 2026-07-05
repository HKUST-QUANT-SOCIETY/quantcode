"""
AI Router — LLM-based execution trace analyzer.

Calls StepFun API to analyze Agent execution traces. Returns structured
decisions about whether the Agent is stuck (suspects_loop) or finished
(is_complete), using semantic reasoning rather than hardcoded thresholds.

Design:
  - Single HTTP POST per analysis, not multi-turn dialog
  - Structured JSON response via response_format json_object
  - Prompt contains zero threshold values
  - Falls back to deterministic guards on API failure
  - Uses only Python stdlib (urllib), no external dependencies
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.stepfun.com/step_plan/v1"
DEFAULT_MODEL = "step-3.7-flash"
REQUEST_TIMEOUT = 15  # seconds — routing must be fast


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class TraceAnalysis:
    """Result of LLM trace analysis."""

    suspects_loop: bool = False
    """True if LLM believes the Agent is stuck (not making real progress)."""

    is_complete: bool = False
    """True if LLM believes the task goal has been achieved."""

    analysis: str = ""
    """Human-readable explanation for trigger_reason / logging."""

    raw_response: dict[str, Any] = field(default_factory=dict)
    """The full parsed JSON response from the LLM, for debugging."""

    fallback: bool = False
    """True if this result came from the fallback path (API failed)."""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an Agent Execution Monitor for the QuantCode system. Your job is to \
observe an Agent's execution trace and make TWO independent judgments:

1. **Is the Agent stuck?** (suspects_loop)

   The Agent is NOT stuck when:
   - Each step brings new information or a different result
   - Failures are followed by different approaches (healthy exploration)
   - Tool calls vary in their arguments and produce different outputs

   The Agent IS stuck when:
   - The same tool returns the same error repeatedly without the Agent \
changing strategy
   - Different tools are called in alternation but NO progress is made \
(e.g., A→B→A→B with identical results each cycle)
   - The Agent retries a failing step many times without modifying its inputs
   - A single tool dominates the trace (>80% of calls) without advancing \
the task

2. **Is the task complete?** (is_complete)

   The task IS complete when:
   - Every required output mentioned in the task goal has been produced
   - The last successful step delivered the final expected artifact
   - No errors remain unresolved that block the deliverable

   The task is NOT complete when:
   - Required artifacts have not been produced
   - Critical steps are still failing
   - The trace ends with an error or incomplete action

Return ONLY valid JSON with this exact schema:
{
  "suspects_loop": true/false,
  "is_complete": true/false,
  "analysis": "<2-3 sentence explanation of your reasoning>"
}"""

_USER_PROMPT_TEMPLATE = """\
Task goal: {task_goal}

Execution trace:
{execution_trace}"""


def _build_messages(task_goal: str, execution_trace: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(
            task_goal=task_goal,
            execution_trace=execution_trace,
        )},
    ]


# ---------------------------------------------------------------------------
# Trace formatting
# ---------------------------------------------------------------------------

def _format_trace(trace: list[dict[str, Any]]) -> str:
    """Format a structured trace list into a readable text block for the LLM."""
    lines: list[str] = []
    for i, step in enumerate(trace, 1):
        tool = step.get("tool", step.get("tool_name", "unknown"))
        success = step.get("success", step.get("ok", True))
        result = step.get("result", step.get("output", ""))
        error = step.get("error", "")

        status = "OK" if success else "FAILED"
        lines.append(f"step {i}: {tool} → {status}")
        if result and str(result).strip():
            # Truncate long results
            res_str = str(result)
            if len(res_str) > 200:
                res_str = res_str[:200] + "..."
            lines.append(f"  result: {res_str}")
        if error and str(error).strip():
            lines.append(f"  error: {error}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _call_stepfun(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """Send a chat completion request to StepFun API. Returns parsed JSON."""
    url = f"{base_url}/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"StepFun API HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"StepFun API unreachable: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"StepFun API returned invalid JSON: {e}") from e

    # Extract assistant message content
    try:
        content = raw["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Unexpected StepFun response structure: {e}") from e


def _get_api_key(api_key: str | None = None) -> str:
    """Resolve API key: explicit arg → env var."""
    if api_key:
        return api_key
    key = os.environ.get("STEPFUN_PLAN_API_KEY", "")
    if not key:
        raise RuntimeError(
            "No API key provided. Set STEPFUN_PLAN_API_KEY env var "
            "or pass api_key= explicitly."
        )
    return key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ai_analyze_trace(
    execution_trace: list[dict[str, Any]],
    task_goal: str = "",
    *,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = REQUEST_TIMEOUT,
) -> TraceAnalysis:
    """
    Analyze Agent execution trace using LLM.

    Parameters:
      execution_trace: list of step dicts, each with:
        - tool / tool_name: str
        - success / ok: bool (optional, default True)
        - result / output: any (optional)
        - error: str (optional)
      task_goal: natural language description of the task
      api_key: StepFun API key (default: env STEPFUN_PLAN_API_KEY)
      base_url: API base URL
      model: model ID
      timeout: request timeout in seconds

    Returns TraceAnalysis.

    On ANY failure (network, API error, invalid response), the function
    returns TraceAnalysis(fallback=True) with conservative defaults:
    suspects_loop=False, is_complete=False.
    The caller should then fall back to deterministic routing.
    """
    trace_text = _format_trace(execution_trace)
    messages = _build_messages(task_goal, trace_text)

    try:
        key = _get_api_key(api_key)
        result = _call_stepfun(
            messages,
            api_key=key,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
        return TraceAnalysis(
            suspects_loop=bool(result.get("suspects_loop", False)),
            is_complete=bool(result.get("is_complete", False)),
            analysis=str(result.get("analysis", "")),
            raw_response=result,
            fallback=False,
        )
    except Exception as exc:
        # Fallback: conservative — don't abort, don't finish
        return TraceAnalysis(
            suspects_loop=False,
            is_complete=False,
            analysis=f"AI router fallback due to: {exc}",
            raw_response={},
            fallback=True,
        )

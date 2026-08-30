"""Goal/Judge — PRD §4.4 P2：设定目标，自动评估任务完成度。

两个公开函数构成 /goal 的 Python 侧契约（fork 侧 /goal 命令由 AG-17b 提供）::

    from runner.judge import judge_run, summarize_run

    result_summary = summarize_run(final_state["execution_trace"])
    result_summary["status"] = final_state.get("task_status", "")
    verdict = judge_run(goal, result_summary)
    # → {"verdict": "met" | "partial" | "missed" | "unevaluated", "reasons": [..]}

judge 模型读取遵守 AG-01 收敛的 env 规范（与 quantcode/mcp_server._get_model 同约定）：

- ``QUANTCODE_API_KEY``            — 唯一 API key 入口（必填）
- ``QUANTCODE_MODEL_PROVIDER``     — deepseek | anthropic | stepfun（默认 deepseek）
- ``QUANTCODE_MODEL_NAME``         — 模型名（默认按 provider）
- ``QUANTCODE_MODEL_BASE_URL``     — 自定义 base URL

诚实降级：任何失败（无 key / LLM 异常 / 输出不合 JSON / verdict 不合法）
一律返回 ``verdict="unevaluated"``，绝不编造结论。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger("runner.judge")

__all__ = ["judge_run", "summarize_run", "VALID_VERDICTS"]

# judge 只允许三种结论（unevaluated 仅由本模块降级产生，LLM 返回它视为解析失败）
VALID_VERDICTS = ("met", "partial", "missed")

_PROMPT_OUTPUT_EXCERPT_MAX = 2000
_PROMPT_TOOL_HISTORY_MAX = 30


# ---------------------------------------------------------------------------
# LLM 工厂（AG-01 env 规范；复用既有 provider，不新建配置面）
# ---------------------------------------------------------------------------

def _get_judge_llm() -> Callable[..., Any] | None:
    """从 env 构造 judge 用的 LLM callable。

    返回 ``(messages, tools=None) -> AIMessage`` 签名（与 AgentRunner 一致）；
    无 QUANTCODE_API_KEY 或 provider 构建失败时返回 None（诚实降级入口）。
    """
    api_key = os.environ.get("QUANTCODE_API_KEY", "").strip()
    if not api_key:
        return None

    provider = os.environ.get("QUANTCODE_MODEL_PROVIDER", "deepseek").strip().lower() or "deepseek"

    default_models = {
        "deepseek": "deepseek-chat",
        "anthropic": "claude-sonnet-4-5",
        "stepfun": "step-3.7-flash",
    }
    default_base_urls = {
        "deepseek": "https://api.deepseek.com/v1",
        "stepfun": "https://api.stepfun.com/step_plan/v1",
    }
    model_name = os.environ.get("QUANTCODE_MODEL_NAME", "").strip() or default_models.get(provider, default_models["deepseek"])
    base_url = os.environ.get("QUANTCODE_MODEL_BASE_URL", "").strip() or default_base_urls.get(provider, "")

    try:
        # ponytail：deepseek 与 stepfun 均为 OpenAI 兼容 API，复用 ChatOpenAI
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            chat = ChatAnthropic(model=model_name, api_key=api_key, temperature=0.0, max_tokens=1024)
        else:
            from langchain_openai import ChatOpenAI

            chat = ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url, temperature=0.0, max_tokens=1024)
    except Exception as e:  # import 失败或构造失败 → judge 不可用
        logger.error("_get_judge_llm: provider=%s build failed — %s: %s", provider, type(e).__name__, e)
        return None

    def _call(messages: list, tools: list | None = None):  # noqa: ANN001, ANN202
        # judge 不需要 function calling；tools 参数仅为对齐 model 签名
        return chat.invoke(messages)

    return _call


# ---------------------------------------------------------------------------
# summarize_run — trace → result_summary
# ---------------------------------------------------------------------------

def summarize_run(trace: list[dict[str, Any]] | None) -> dict[str, Any]:
    """从 execution_trace 事件数组提取工具序列 + 错误 + 产物路径 → result_summary。

    同时兼容两种 trace 形态：
    - agent_engine.stream() 的 v1 事件（``schema_version`` + ``data`` 载荷）
    - 旧版扁平事件（字段直接在事件上：``tool`` / ``result`` / ``is_error``）

    Returns:
        {
            "status": str,          # agent_end 的 status（缺省 ""）
            "tools": [{"tool", "success", "error"}],   # 按调用顺序
            "errors": [str],
            "artifacts": [str],
            "output_excerpt": str,  # output_data 载荷的 JSON 摘录（截断）
        }
    """
    result: dict[str, Any] = {
        "status": "",
        "tools": [],
        "errors": [],
        "artifacts": [],
        "output_excerpt": "",
    }

    for event in (trace or []):
        if not isinstance(event, dict):
            continue
        etype = str(event.get("type", ""))
        data = event.get("data") if isinstance(event.get("data"), dict) else event

        if etype == "agent_end":
            result["status"] = str(data.get("status", result["status"] or ""))
        elif etype == "tool_call":
            result["tools"].append({
                "tool": str(data.get("tool", "unknown")),
                "success": True,  # 结果由配对的 tool_result 修正
                "error": "",
                "tool_call_id": str(data.get("tool_call_id", "")),
            })
        elif etype == "tool_result":
            result_text = str(data.get("result", "")
                              if "result" in data else data.get("content", ""))
            is_error = bool(data.get("is_error", False))
            # 配对回填：按 tool_call_id 优先，否则填到最近一条无名结果
            tcid = str(data.get("tool_call_id", ""))
            repaired = False
            if tcid:
                for t in reversed(result["tools"]):
                    if t.get("tool_call_id") == tcid:
                        t["success"] = not is_error
                        t["error"] = result_text if is_error else ""
                        repaired = True
                        break
            if not repaired and result["tools"]:
                last = result["tools"][-1]
                if not last.get("result_seen"):
                    last["success"] = not is_error
                    last["error"] = result_text if is_error else ""
            if is_error:
                result["errors"].append(result_text[:500])
        elif etype == "artifact":
            path = str(data.get("path", ""))
            if path:
                result["artifacts"].append(path)
        elif etype == "output_data":
            payload = data.get("output_data", data)
            result.setdefault("_output_payload", payload)

    if result.get("_output_payload") is not None:
        try:
            result["output_excerpt"] = json.dumps(
                result["_output_payload"], ensure_ascii=False, default=str
            )[:_PROMPT_OUTPUT_EXCERPT_MAX]
        except (TypeError, ValueError):
            result["output_excerpt"] = str(result["_output_payload"])[:_PROMPT_OUTPUT_EXCERPT_MAX]
    result.pop("_output_payload", None)

    # 去掉内部对齐用的 key
    for t in result["tools"]:
        t.pop("tool_call_id", None)
        t.pop("result_seen", None)
    # tool_call 里从未被 tool_result 修正过的（前段遗留 success=True 假值）
    # 保持 True：无结果表明该 call 没有落到 tool_result。

    return result


# ---------------------------------------------------------------------------
# judge_run — goal + summary → verdict
# ---------------------------------------------------------------------------

def _content_to_text(content: Any) -> str:
    """AIMessage.content 归一为 str（Anthropic 可能返回分段 list）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(str(c.get("text", "")))
            else:
                parts.append(str(c))
        return "\n".join(parts)
    return str(content)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """从 LLM 输出中提取第一个 JSON 对象（容忍 markdown 代码围栏）。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去 ```json ... ^``` 围栏
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 兜底：截取最外层 { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(cleaned[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return None
    return None


def _format_tools_for_prompt(tools: list[dict[str, Any]]) -> str:
    shown = tools[-_PROMPT_TOOL_HISTORY_MAX:]
    lines = []
    for t in shown:
        status = "ok" if t.get("success") else f"FAILED: {t.get('error', '')[:300]}"
        lines.append(f"- {t.get('tool')}: {status}")
    if len(tools) > _PROMPT_TOOL_HISTORY_MAX:
        lines.insert(0, f"(…共 {len(tools)} 次调用，仅显示最近 {len(shown)} 次)")
    return "\n".join(lines) if lines else "(无工具调用)"


def judge_run(
    goal: str,
    result_summary: dict[str, Any] | None,
    *,
    llm: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """用独立 judge 模型评估一次 run 是否达成 goal。

    Args:
        goal: /goal 设定的目标描述（自然语言）。
        result_summary: summarize_run 的产物（可再由调用方补充 status /
            output 摘录字段）；允许缺键。
        llm: 显式注入的模型 callable ``(messages, tools=None) -> AIMessage``。
            缺省时从 env 走 :func:`_get_judge_llm`（AG-01 规范）。

    Returns:
        ``{"verdict": "met"|"partial"|"missed", "reasons": [str, ...]}``；
        任何失败路径返回 ``{"verdict": "unevaluated", "reasons": [...]}``。
    """
    unevaluated: dict[str, Any] = {"verdict": "unevaluated", "reasons": []}

    if not isinstance(goal, str) or not goal.strip():
        unevaluated["reasons"].append("empty goal: nothing to evaluate")
        return unevaluated

    summary = result_summary if isinstance(result_summary, dict) else {}

    model = llm if llm is not None else _get_judge_llm()
    if model is None:
        unevaluated["reasons"].append(
            "judge LLM unavailable: QUANTCODE_API_KEY not set or provider build failed"
        )
        return unevaluated

    tools_block = _format_tools_for_prompt(summary.get("tools") or [])
    errors_block = "\n".join(f"- {str(e)[:500]}" for e in (summary.get("errors") or [])) or "(无)"
    artifacts_block = "\n".join(f"- {a}" for a in (summary.get("artifacts") or [])) or "(无)"
    excerpt = str(summary.get("output_excerpt", ""))[:_PROMPT_OUTPUT_EXCERPT_MAX] or "(无)"
    status = str(summary.get("status", "")) or "(unknown)"

    system_prompt = (
        "你是一个公正的任务验收评审（Judge）。根据执行摘要判断任务是否达成目标。\n"
        "只输出一个 JSON 对象，格式：\n"
        '{"verdict": "met" | "partial" | "missed", "reasons": ["..."]}\n'
        "- met: 目标完全达成\n"
        "- partial: 部分达成 / 有关键遗留\n"
        "- missed: 明显未达成\n"
        "不要输出任何 JSON 以外的内容。"
    )
    user_prompt = (
        f"# 目标 (goal)\n{goal.strip()}\n\n"
        f"# 最终状态\n{status}\n\n"
        f"# 工具调用历史\n{tools_block}\n\n"
        f"# 错误\n{errors_block}\n\n"
        f"# 产物路径\n{artifacts_block}\n\n"
        f"# 输出数据摘录\n{excerpt}\n"
    )

    try:
        response = model([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    except Exception as e:
        unevaluated["reasons"].append(f"judge LLM call failed: {type(e).__name__}: {e}")
        return unevaluated

    parsed = _extract_json_object(getattr(response, "content", "") or "")
    if parsed is None:
        unevaluated["reasons"].append("judge output is not valid JSON object")
        return unevaluated

    verdict = str(parsed.get("verdict", "")).strip().lower()
    if verdict not in VALID_VERDICTS:
        unevaluated["reasons"].append(
            f"judge returned invalid verdict {verdict!r}; expected one of {list(VALID_VERDICTS)}"
        )
        return unevaluated

    raw_reasons = parsed.get("reasons", [])
    if isinstance(raw_reasons, str):
        raw_reasons = [raw_reasons]
    reasons = [str(r) for r in raw_reasons if str(r).strip()] if isinstance(raw_reasons, list) else []

    return {"verdict": verdict, "reasons": reasons}


__all__ = [
    "judge_run",
    "summarize_run",
    "VALID_VERDICTS",
]
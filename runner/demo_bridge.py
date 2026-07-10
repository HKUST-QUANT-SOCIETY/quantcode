"""Demo bridge — Day 5 Lead。

把 run_agent 的 execution_trace 渲染成人类可读的流式输出，作为 IDE 前端
未完成时的降级演示路径（Day5 §2 / §11 降级预案）。

两种用法：
1. **人读模式**（默认）：彩色/带图标的流式渲染，demo 现场用。
       python -m runner.demo_bridge --group risk --skill risk-gate \
           --task "run risk_stub high_risk"
   撞到 HumanGate 时提示输入 approve/reject，回车后 resume。

2. **JSONL 模式**（--jsonl）：每行一个 execution_trace 事件，供 OpenCode
   spawn 后从 stdout 读取回流（前端渲染同样的事件流）。
       python -m runner.demo_bridge --group factor --task "测 PB-ROE 因子" --jsonl

设计：不引入新依赖，直接调 runner.agent_mcp_tool._run_agent_execute（与 MCP
入口同一函数），保证 bridge 与 IDE 走的是同一条 Python 链路。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


# 事件类型 → 人读图标
_ICONS = {
    "agent_start": "🚀",
    "user_input": "📝",
    "llm_thought": "💭",
    "tool_call": "🔧",
    "tool_result": "✅",
    "risk_metrics": "📊",
    "human_gate": "⏸️",
    "output_data": "📦",
    "artifact": "📄",
    "agent_end": "🏁",
    "error": "❌",
}


def _print_event(ev: dict[str, Any], *, jsonl: bool) -> None:
    """渲染一个 execution_trace 事件。"""
    if jsonl:
        sys.stdout.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
        return
    etype = ev.get("type", "?")
    icon = _ICONS.get(etype, "•")
    data = ev.get("data", {})
    summary = ""
    if etype == "tool_call":
        summary = data.get("tool_name", "") or data.get("name", "")
    elif etype == "tool_result":
        summary = str(data.get("summary", data.get("result", "")))[:80]
    elif etype == "llm_thought":
        summary = str(data.get("text", data.get("content", "")))[:80]
    elif etype == "risk_metrics":
        summary = json.dumps(data.get("metrics", data), ensure_ascii=False)[:80]
    elif etype in ("output_data", "artifact"):
        summary = str(data)[:80]
    print(f"  {icon} [{etype}] {summary}")


def _render_result(result: dict[str, Any], *, jsonl: bool) -> None:
    """渲染一次 run_agent 调用的完整结果。"""
    for ev in result.get("execution_trace", []) or []:
        _print_event(ev, jsonl=jsonl)
    if jsonl:
        # 汇总事件（供前端知道本次调用的终态）
        sys.stdout.write(
            json.dumps(
                {
                    "type": "_result",
                    "status": result.get("status"),
                    "thread_id": result.get("thread_id"),
                    "artifacts": result.get("artifacts", []),
                },
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantCode demo bridge (run_agent renderer)")
    parser.add_argument("--group", required=True, help="组：model/risk/factor/...")
    parser.add_argument("--task", default="", help="任务描述（start 模式必填）")
    parser.add_argument("--skill", default=None, help="skill_name，可选")
    parser.add_argument("--jsonl", action="store_true", help="JSONL 事件流模式（供前端消费）")
    parser.add_argument(
        "--decision",
        default=None,
        choices=["approve", "reject"],
        help="非交互 resume 决策（配合 --thread-id）",
    )
    parser.add_argument("--thread-id", default=None, help="resume 用的 thread_id")
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="撞到 HumanGate 自动 approve（无人值守 demo）",
    )
    args = parser.parse_args(argv)

    from runner.agent_mcp_tool import RunAgentArgs, _run_agent_execute

    ctx = {"group": args.group}

    # resume 模式
    if args.decision is not None:
        result = _run_agent_execute(
            RunAgentArgs(thread_id=args.thread_id, decision=args.decision, group=args.group),
            ctx=ctx,
        )
        _render_result(result, jsonl=args.jsonl)
        return 0 if result.get("status") != "error" else 1

    # start 模式
    if not args.jsonl:
        print(f"▶ 启动 {args.group} Agent：{args.task!r}")
    result = _run_agent_execute(
        RunAgentArgs(task=args.task, group=args.group, skill_name=args.skill),
        ctx=ctx,
    )
    _render_result(result, jsonl=args.jsonl)

    # HumanGate 两阶段
    while result.get("status") == "waiting_for_human":
        thread_id = result.get("thread_id")
        gate = result.get("gate", {})
        if not args.jsonl:
            print(f"\n⏸️  HumanGate：{gate.get('reasons', [])}")
        if args.auto_approve:
            decision = "approve"
        elif args.jsonl:
            # JSONL 模式不交互，交给前端；这里终止等待
            break
        else:
            decision = input("   approve / reject? ").strip() or "reject"
        result = _run_agent_execute(
            RunAgentArgs(thread_id=thread_id, decision=decision, group=args.group),
            ctx=ctx,
        )
        _render_result(result, jsonl=args.jsonl)

    if not args.jsonl:
        print(f"\n✔ 终态：{result.get('status')}  artifacts={result.get('artifacts', [])}")
    return 0 if result.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())

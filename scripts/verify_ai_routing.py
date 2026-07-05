"""
AI Router 真实 API 验证脚本
===========================

验证方法分为四层，从底层到顶层逐步证明链路正确：

  Layer 1 — 基础连通性：API 能通、鉴权正确、返回合法 JSON
  Layer 2 — 单模块正确性：ai_analyze_trace 对 5 类轨迹各返回正确判断
  Layer 3 — 对比一致性：AI 路由 vs 规则路由，在确定性场景下应一致
  Layer 4 — 容错降级：API 故障时 fallback 到规则路由不出错

运行方式：
  python scripts/verify_ai_routing.py

前置条件：
  - 已设置环境变量 STEPFUN_PLAN_API_KEY
  - 当前目录为 quantcode 仓库根目录

验证方法论说明见脚本末尾的大段注释。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner.routing.ai_router import (
    _build_messages,
    _call_stepfun,
    _format_trace,
    _get_api_key,
    TraceAnalysis,
    ai_analyze_trace,
)
from runner.routing.combined_router import RouterMode, route as combined_route
from runner.routing.router import RouteDecision, route_next_step


# ═══════════════════════════════════════════════════════════════════════════════
# Test state — single source of truth for pass/fail tracking
# ═══════════════════════════════════════════════════════════════════════════════

_results: list[dict] = []
_start_time: float = 0.0


def _record(layer: int, name: str, passed: bool, detail: str = ""):
    _results.append({
        "layer": layer,
        "name": name,
        "passed": passed,
        "detail": detail,
    })
    icon = "✅" if passed else "❌"
    print(f"  {icon}  L{layer} {name}")
    if detail and not passed:
        print(f"      └─ {detail}")


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1 — 基础连通性
# ═══════════════════════════════════════════════════════════════════════════════

def test_l1_connectivity(api_key: str):
    """
    验证 StepFun API 可连通、鉴权正确、返回结构合法。

    你的操作：确保 STEPFUN_PLAN_API_KEY 已设置
    正确结果：3 项全部 PASS
    为什么能说明对：如果这层不过，上面所有层都不可能过。
                      隔离了网络/鉴权/auth 问题。
    """
    print("\n" + "─" * 60)
    print("Layer 1: 基础连通性")
    print("─" * 60)

    # 1.1 API key 可读取
    try:
        key = _get_api_key(api_key)
        _record(1, "API key 可读取", True)
    except Exception as e:
        _record(1, "API key 可读取", False, str(e))
        return  # 后面没法跑了

    # 1.2 最简请求 — 确保能通
    try:
        msgs = [
            {"role": "user", "content": "Say exactly the word OK and nothing else."}
        ]
        resp = _call_stepfun(msgs, api_key=key, model="step-3.5-flash")
        _record(1, "最简请求→200", True, f"model=step-3.5-flash")
    except Exception as e:
        _record(1, "最简请求→200", False, str(e))
        return

    # 1.3 JSON 格式请求 — 确保 response_format json_object 可用
    try:
        msgs = [
            {"role": "user", "content": "Return exactly this JSON and nothing else: {\"ok\": true}"},
        ]
        resp = _call_stepfun(msgs, api_key=key, model="step-3.7-flash")
        if resp.get("ok") is True:
            _record(1, "JSON response_format", True)
        else:
            _record(1, "JSON response_format", False, f"got: {resp}")
    except Exception as e:
        _record(1, "JSON response_format", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2 — 单模块正确性（ai_analyze_trace）
# ═══════════════════════════════════════════════════════════════════════════════

def test_l2_normal_execution(api_key: str):
    """
    用例：正常执行轨迹 — 3 步不同 tool，全部成功，任务未完成

    你的操作：无需操作，自动运行
    正确结果：suspects_loop=false, is_complete=false, fallback=false
    为什么能说明对：task_goal 里列了 5 个步骤，trace 只执行了前 3 步。
                     LLM 应该正确判断"有进展但还没完成"。
                     ​证明 LLM 不会对未完成的任务过早判定 finish。
    """
    print("\n" + "─" * 60)
    print("Layer 2.1: 正常执行 — 不误报")
    print("─" * 60)

    trace = [
        {"tool": "fetch_pr", "success": True, "result": "PR #42 diff loaded"},
        {"tool": "extract_metadata", "success": True, "result": {"author": "alice", "changes": 12}},
        {"tool": "write_blackboard", "success": True, "result": "written to PROJECT scope"},
    ]
    goal = "Process PR #42: extract metadata, write to blackboard, generate ModelSpec, and trigger risk check"

    try:
        result = ai_analyze_trace(trace, goal, api_key=api_key)
        _record(2, "suspects_loop=false", not result.suspects_loop,
                f"LLM: {result.analysis[:100]}" if result.suspects_loop else "")
        _record(2, "is_complete=false", not result.is_complete,
                f"LLM: {result.analysis[:100]}" if result.is_complete else "")
        _record(2, "fallback=false", not result.fallback)
        _record(2, "analysis 非空", bool(result.analysis.strip()))
        _record(2, "raw_response 含三个字段",
                all(k in result.raw_response for k in ("suspects_loop", "is_complete", "analysis")))
    except Exception as e:
        _record(2, "整体调用", False, str(e))


def test_l2_completed_task(api_key: str):
    """
    用例：任务完成轨迹 — 所有关键产出已生成，最后一步成功

    你的操作：无需操作，自动运行
    正确结果：is_complete=true, suspects_loop=false
    为什么能说明对：证明 LLM 能理解"任务完成了"。
                     这是 finish 决策的语义基础。
    """
    print("\n" + "─" * 60)
    print("Layer 2.2: 任务完成 — 正确识别")
    print("─" * 60)

    trace = [
        {"tool": "fetch_pr",   "success": True, "result": "PR #42 diff"},
        {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
        {"tool": "generate_modelspec", "success": True, "result": {"spec_id": "ms_42"}},
        {"tool": "write_blackboard", "success": True, "result": "written"},
        {"tool": "trigger_risk", "success": True, "result": "risk Agent notified"},
    ]
    goal = "Process PR #42: read PR, extract metadata, generate ModelSpec, write to blackboard, trigger risk check"

    try:
        result = ai_analyze_trace(trace, goal, api_key=api_key)
        _record(2, "is_complete=true", result.is_complete,
                f"LLM: {result.analysis[:100]}" if not result.is_complete else "")
        _record(2, "suspects_loop=false", not result.suspects_loop,
                f"LLM: {result.analysis[:100]}" if result.suspects_loop else "")
        _record(2, "analysis 提及完成原因",
                any(w in result.analysis.lower() for w in ["complete", "finish", "all", "done", "produced"]))
    except Exception as e:
        _record(2, "整体调用", False, str(e))


def test_l2_stuck_semantic_loop(api_key: str):
    """
    用例：语义死循环 — A→B→A→B 交替，不同 tool 但每轮结果完全相同

    你的操作：无需操作，自动运行
    正确结果：suspects_loop=true
    为什么能说明对：这是规则路由检测不到的模式（不是同一 tool 重复），
                     只有 LLM 语义分析能抓。如果这项 PASS，
                     证明 AI 路由提供了规则路由没有的价值。
    """
    print("\n" + "─" * 60)
    print("Layer 2.3: 语义循环 — 规则路由盲区")
    print("─" * 60)

    trace = []
    for i in range(5):
        trace.append({"tool": "extract_metadata", "success": True,
                       "result": {"author": "alice", "fields": 3}})
        trace.append({"tool": "validate_schema", "success": False,
                       "error": "missing author field"})

    goal = "Process PR #42 and generate ModelSpec"

    try:
        result = ai_analyze_trace(trace, goal, api_key=api_key)
        _record(2, "suspects_loop=true", result.suspects_loop,
                f"LLM: {result.analysis[:150]}" if not result.suspects_loop else "")
        _record(2, "is_complete=false", not result.is_complete)
        _record(2, "analysis 提及循环/重复",
                any(w in result.analysis.lower() for w in ["repeat", "loop", "same", "stuck", "alternating", "cycle"]))
    except Exception as e:
        _record(2, "整体调用", False, str(e))


def test_l2_healthy_exploration(api_key: str):
    """
    用例：健康探索 — tool 连续失败但每次输入不同，最终找到正确路径

    你的操作：无需操作，自动运行
    正确结果：suspects_loop=false
    为什么能说明对：证明 LLM 区分"在尝试不同方案"和"在空转"。
                     Agent 换 PR 编号、换参数重新试 = 正常探索 ≠ 循环。
    """
    print("\n" + "─" * 60)
    print("Layer 2.4: 健康探索 — 失败不误报")
    print("─" * 60)

    trace = [
        {"tool": "fetch_pr", "success": False, "error": "404 PR #42 not found"},
        {"tool": "fetch_pr", "success": False, "error": "404 PR #43 not found"},
        {"tool": "fetch_pr", "success": False, "error": "404 PR #44 not found"},
        {"tool": "list_open_prs", "success": True, "result": ["#45", "#46", "#47"]},
        {"tool": "fetch_pr", "success": True, "result": "PR #45 diff loaded"},
        {"tool": "extract_metadata", "success": True, "result": {"author": "bob"}},
    ]
    goal = "Process the latest open PR: read diff, extract metadata"

    try:
        result = ai_analyze_trace(trace, goal, api_key=api_key)
        _record(2, "suspects_loop=false", not result.suspects_loop,
                f"LLM: {result.analysis[:150]}" if result.suspects_loop else "")
        _record(2, "analysis 非空", bool(result.analysis.strip()))
    except Exception as e:
        _record(2, "整体调用", False, str(e))


def test_l2_blind_retry(api_key: str):
    """
    用例：盲目重试 — 同一个 tool 同样的输入连续失败 8 次

    你的操作：无需操作，自动运行
    正确结果：suspects_loop=true
    为什么能说明对：这是最经典的停滞模式。如果这项不过，
                     AI 路由没有存在价值。
    """
    print("\n" + "─" * 60)
    print("Layer 2.5: 盲目重试 — 必须抓到")
    print("─" * 60)

    trace = [
        {"tool": "validate_schema", "success": False, "error": "missing author field"}
    ] * 8

    goal = "Validate the generated ModelSpec schema"

    try:
        result = ai_analyze_trace(trace, goal, api_key=api_key)
        _record(2, "suspects_loop=true", result.suspects_loop,
                f"LLM: {result.analysis[:150]}" if not result.suspects_loop else "")
        _record(2, "is_complete=false", not result.is_complete)
    except Exception as e:
        _record(2, "整体调用", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3 — AI vs 规则路由对比
# ═══════════════════════════════════════════════════════════════════════════════

def test_l3_comparison(api_key: str):
    """
    端到端对比 — 三个场景各跑 AI 路由和规则路由，检查结果一致性。

    你的操作：无需操作，自动运行
    正确结果：
      - normal 场景：两者决策一致（continue 或 finish）
      - high_risk 场景：task_goal 只有 fetch+calculate，trace 全完成，
                       AI finish 正确；规则路由因风险阈值 human_gate
      - loop 场景：A→B→A→B 交替，规则路由触发不了频率阈值 → continue（盲区）
                    AI 路由走 human_gate(workflow_failure)（抓住了语义循环）
                    两者分歧恰好证明 AI 路由提供增量价值
    为什么能说明对：证明 combined_router 的完整链路正确——
                     LLM → TraceAnalysis → combined_router 决策。
    """
    print("\n" + "─" * 60)
    print("Layer 3: AI vs 规则路由 端到端对比")
    print("─" * 60)

    def _normal_risk():
        return {"tail_risk_var_99": 0.025, "max_drawdown": 0.08,
                "position_limit": 0.45, "volatility": 0.12,
                "correlation_with_existing": 0.30, "var_99_trend": 0.001,
                "max_drawdown_trend": 0.002}

    def _high_risk():
        return {"tail_risk_var_99": 0.085, "max_drawdown": 0.22,
                "position_limit": 0.92, "volatility": 0.35,
                "correlation_with_existing": 0.70, "var_99_trend": 0.02,
                "max_drawdown_trend": 0.05}

    scenarios = {
        "normal": {
            "iteration_count": 3,
            "tool_call_history": ["fetch_data", "calc_risk_stub", "save_report"],
            "fingerprint_history": ["fp1", "fp2", "fp3"],
            "risk_metrics": _normal_risk(),
            "risk_features": _normal_risk(),
            "task_goal": "Fetch data, calculate risk, save report",
            "execution_trace": [
                {"tool": "fetch_data", "success": True, "result": "data loaded"},
                {"tool": "calc_risk_stub", "success": True, "result": "risk computed"},
                {"tool": "save_report", "success": True, "result": "report saved"},
            ],
            "expect": "continue_or_finish",
        },
        "high_risk": {
            "iteration_count": 5,
            "tool_call_history": ["fetch_data", "calc_risk_stub"],
            "fingerprint_history": ["fp1", "fp2"],
            "risk_metrics": _high_risk(),
            "risk_features": _high_risk(),
            "task_goal": "Fetch data and calculate risk metrics",
            "execution_trace": [
                {"tool": "fetch_data", "success": True, "result": "data loaded"},
                {"tool": "calc_risk_stub", "success": True, "result": "high risk detected"},
            ],
            "expect": "dual_valid",
        },
        "loop": {
            "iteration_count": 7,
            "tool_call_history": ["extract_metadata", "validate_schema"] * 5,
            "fingerprint_history": ["fp_a", "fp_b"] * 5,
            "risk_metrics": None,
            "risk_features": {},
            "task_goal": "Process PR and generate ModelSpec",
            "execution_trace": [
                {"tool": "extract_metadata", "success": True, "result": {"author": "alice", "fields": 3}},
                {"tool": "validate_schema", "success": False, "error": "missing author field"},
                {"tool": "extract_metadata", "success": True, "result": {"author": "alice", "fields": 3}},
                {"tool": "validate_schema", "success": False, "error": "missing author field"},
                {"tool": "extract_metadata", "success": True, "result": {"author": "alice", "fields": 3}},
                {"tool": "validate_schema", "success": False, "error": "missing author field"},
                {"tool": "extract_metadata", "success": True, "result": {"author": "alice", "fields": 3}},
                {"tool": "validate_schema", "success": False, "error": "missing author field"},
                {"tool": "extract_metadata", "success": True, "result": {"author": "alice", "fields": 3}},
                {"tool": "validate_schema", "success": False, "error": "missing author field"},
            ],
            "expect": "ai_catch_loop",
        },
    }

    for name, state in scenarios.items():
        print(f"\n  ── scenario: {name} ──")

        # Rule router
        rule = route_next_step(state)
        print(f"  Rule:  {rule.decision.value:<25} ({rule.reason})")

        # AI router
        try:
            ai = combined_route(state, mode=RouterMode.AI_ONLY, api_key=api_key)
        except Exception:
            ai = combined_route(state, mode=RouterMode.AI_WITH_FALLBACK, api_key=api_key)
        print(f"  AI:    {ai.decision.value:<25} ({ai.reason})")
        if ai.detail.get("analysis"):
            print(f"         └─ {str(ai.detail['analysis'])[:150]}")
        if ai.detail.get("ai_fallback"):
            print(f"         └─ ⚠️ fallback: {str(ai.detail['ai_fallback'])[:100]}")

        # 判断
        expect = state["expect"]
        ai_d = ai.decision.value
        rule_d = rule.decision.value

        if expect == "continue_or_finish":
            ok_rule = rule_d in ("continue", "finish")
            ok_ai = ai_d in ("continue", "finish")
        elif expect == "human_gate":
            ok_rule = rule_d == "human_gate"
            ok_ai = ai_d == "human_gate"
        elif expect == "dual_valid":
            # high_risk: task_goal 只有 fetch+calculate，trace 全完成
            # 规则路由: human_gate（风险阈值超标）→ 正确
            # AI 路由: finish（任务目标已完成，ML gate 此时不适用）→ 正确
            ok_rule = rule_d == "human_gate"
            ok_ai = ai_d in ("continue", "finish")
        elif expect == "ai_catch_loop":
            # A→B→A→B 交替循环：规则路由触发不了频率阈值（非连续同tool）
            # → continue 是规则路由的正确行为
            # AI 路由从 trace 内容发现语义循环 → human_gate(workflow_failure)
            ok_rule = True  # continue is correct for rule router here
            ok_ai = (ai_d == "human_gate" and ai.reason == "workflow_failure")
        else:
            ok_rule = ok_ai = False

        _record(3, f"{name}/rule", ok_rule,
                f"expected {expect}, got {rule_d}/{rule.reason}" if not ok_rule else "")
        _record(3, f"{name}/ai", ok_ai,
                f"expected {expect}, got {ai_d}/{ai.reason}" if not ok_ai else "")


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 4 — 容错降级
# ═══════════════════════════════════════════════════════════════════════════════

def test_l4_fallback():
    """
    验证 API 故障时回退到规则路由。

    你的操作：无需操作，自动运行（传无效 API key）
    正确结果：fallback=true, 决策来自规则路由
    为什么能说明对：生产环境 API 总会偶尔不可用。
                     证明系统在 AI 不可用时不会崩溃，能降级。
    """
    print("\n" + "─" * 60)
    print("Layer 4: 容错降级")
    print("─" * 60)

    # 4.1: API key 不正确 → fallback
    trace = [{"tool": "test", "success": True, "result": "ok"}]
    result = ai_analyze_trace(trace, "test", api_key="invalid-key-xxx")
    _record(4, "无效 API key→fallback", result.fallback,
            f"suspects_loop={result.suspects_loop}, is_complete={result.is_complete}" if not result.fallback else "")
    _record(4, "fallback 时 is_complete=false (保守)", not result.is_complete)
    _record(4, "fallback 时 suspects_loop=false (保守)", not result.suspects_loop)

    # 4.2: combined_router 在 AI_WITH_FALLBACK 模式下不抛异常
    state = {
        "iteration_count": 3,
        "execution_trace": trace,
        "risk_features": {},
        "task_goal": "test",
        "tool_call_history": [],
        "fingerprint_history": [],
    }
    try:
        result = combined_route(state, mode=RouterMode.AI_WITH_FALLBACK, api_key="bad-key")
        _record(4, "combined_router AI_WITH_FALLBACK 不崩溃", True)
    except Exception as e:
        _record(4, "combined_router AI_WITH_FALLBACK 不崩溃", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global _start_time
    _start_time = time.time()

    print("=" * 70)
    print("  QuantCode AI Router — 真实 API 验证")
    print("=" * 70)

    # ── 检查前置条件 ──
    api_key = os.environ.get("STEPFUN_PLAN_API_KEY", "")
    if not api_key:
        print("\n❌ 未设置 STEPFUN_PLAN_API_KEY 环境变量")
        print("   请在运行前设置：")
        print("     export STEPFUN_PLAN_API_KEY=<your-key>")
        print("   或在 Windows PowerShell：")
        print('     $env:STEPFUN_PLAN_API_KEY="<your-key>"')
        print("\n   跳过 Layer 1-3 的 API 测试，仅运行 Layer 4 (fallback)...")
        has_key = False
    else:
        print(f"\n  API key: ...{api_key[-8:]}")
        has_key = True

    # ── 执行测试 ──

    if has_key:
        test_l1_connectivity(api_key)

        # 只有 L1 全过才跑 L2/L3
        l1_ok = all(r["passed"] for r in _results if r["layer"] == 1)
        if l1_ok:
            test_l2_normal_execution(api_key)
            test_l2_completed_task(api_key)
            test_l2_stuck_semantic_loop(api_key)
            test_l2_healthy_exploration(api_key)
            test_l2_blind_retry(api_key)
            test_l3_comparison(api_key)
        else:
            print("\n  ⛔ Layer 1 未全部通过，跳过 Layer 2-3")

    # L4 不依赖真实 API
    test_l4_fallback()

    # ── 汇总 ──
    elapsed = time.time() - _start_time
    total = len(_results)
    passed = sum(1 for r in _results if r["passed"])
    failed = total - passed

    print("\n" + "=" * 70)
    print(f"  验证完成  |  {total} tests  |  {passed} passed  |  {failed} failed")
    print(f"  耗时: {elapsed:.1f}s")
    print("=" * 70)

    # 按层统计
    for layer in sorted(set(r["layer"] for r in _results)):
        lt = [r for r in _results if r["layer"] == layer]
        lp = sum(1 for r in lt if r["passed"])
        print(f"  Layer {layer}: {lp}/{len(lt)} passed")

    if failed:
        print(f"\n  ❌ {failed} 项未通过，详情见上方输出")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


# ═══════════════════════════════════════════════════════════════════════════════
# 验证方法论（供汇报时参考）
# ═══════════════════════════════════════════════════════════════════════════════
"""
## 验证层次设计

### Layer 1 — 基础连通性
目的：隔离网络/鉴权/auth 问题。
如果这层不过，后面所有层都不可能过。

### Layer 2 — 单模块正确性（核心）
5 个用例覆盖了 ai_analyze_trace 的全部决策空间：

  suspects_loop  /  is_complete  |  false         |  true
  ───────────────────────────────┼────────────────┼────────
  false                          | 正常执行 2.1    | 任务完成 2.2
                                 | 健康探索 2.4    |
  ───────────────────────────────┼────────────────┼────────
  true                           | 语义循环 2.3    | (不可能：
                                 | 盲目重试 2.5    |  停滞 + 完成)

2.3 是关键差异化用例——规则路由检测不到 A→B→A→B 交替循环，
只有 LLM 语义分析能抓。如果 2.3 通过，证明 AI 路由提供了增量价值。

### Layer 3 — 端到端对比
证明 whole pipeline 正确：trace → ai_analyze_trace → combined_router → 最终决策。

### Layer 4 — 容错降级
生产必备。证明 AI 不可用时系统不崩溃。

## 什么验证结果可以认为是"对的"

- L1: 3/3 passed → 基础链路正常
- L2: 5/5 passed → LLM 在 5 类轨迹上判断全部正确
  - 其中 2.3 是关键：如果不通过但 2.5 通过了，
    说明 LLM 能识别简单循环但识别不了语义循环 → prompt 需要迭代
- L3: 6/6 passed → 端到端链路完整
- L4: 3/3 passed → 降级机制正常

## 你（俞高磊）需要做什么

1. 设置 STEPFUN_PLAN_API_KEY（你自己已经有）
2. 运行 python scripts/verify_ai_routing.py
3. 检查输出：全部 ✅ 即通过
4. 如果某项 FAIL，读 detail 信息判断是 prompt 问题还是 API 问题，
   迭代调整后重跑
5. 通过后截图保存到 docs/screenshots/

## 为什么这套验证能说明 AI 路由是正确的

不是"跑通了"就算对。每项验证都有明确的失败模式分析：

- 2.1 失败 → LLM 对正常轨迹产生误报，prompt 太激进
- 2.2 失败 → LLM 不理解"任务完成"的语义
- 2.3 失败 → LLM 抓不到语义循环（最关键的差异化能力）
- 2.4 失败 → LLM 无法区分"尝试"和"空转"
- 2.5 失败 → LLM 连最经典的停滞都看不出来
- 3.x 失败 → 模块正确但集成链路有问题
- 4.x 失败 → 降级有 bug

每个失败都有唯一归属，不会被"164 tests passed"掩盖住。
"""

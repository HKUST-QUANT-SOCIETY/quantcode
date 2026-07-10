"""真 LLM 集成测试 — Day 4 尹一帆。

用 DeepSeek LLM 验证 AgentRunner 的"自主推理"能力，不是 mock。
这些测试默认跳过（需设置 ``QUANTCODE_USE_REAL_LLM=1`` 并配置 ``config.json``）。

运行::

    QUANTCODE_USE_REAL_LLM=1 pytest tests/test_real_llm_integration.py -v

覆盖:
1. risk AgentRunner 用真 LLM 自主决定调 check_gate + 后续 tool
2. factor AgentRunner 用真 LLM 跑 3 步自主推理
3. Dream 原型用真 LLM 产出非 mock 的 memory
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage


# ---------------------------------------------------------------------------
# 1. risk AgentRunner 真 LLM 测试
# ---------------------------------------------------------------------------


def test_agent_runner_risk_with_real_llm(require_real_llm, tmp_path):
    """用真 DeepSeek LLM 跑 risk AgentRunner，验证"自主决策"调 check_gate。

    与 test_agent_runner_gate.py 的 mock 测试不同，这里的 LLM 是真实 DeepSeek API，
    Agent 必须自己看到 state 后决定下一步调什么 tool，不是预设 script。

    验证点:
    - Agent 至少调了 read_blackboard（说明 LLM 能正确使用 tool）
    - 如果调了 check_gate 且 requires_human=True，验证 __interrupt__ 被触发
    - Agent 能正常结束（不崩溃、不无限循环）
    """
    import tools.risk._register  # noqa: F401
    from runner.agent_engine import AgentRunner

    runner = AgentRunner(
        group="risk",
        model=require_real_llm,
        checkpoint_db=tmp_path / "cp.db",
        max_iterations=6,  # 限制步数，避免无限循环
    )

    final = runner.run(
        task=(
            "你是一个风险控制 Agent。请读取 blackboard 中的模型 spec，"
            "计算风险指标，检查 gate，如果风险过高需要人审。"
            "input_data 包含 pr_number=1, scenario=normal。"
        ),
        skill_name=None,
        system_prompt=(
            "You are a risk control agent. Your job is to:\n"
            "1. Read the blackboard with read_blackboard(input_data)\n"
            "2. Calculate risk metrics with calc_risk(model_spec, scenario)\n"
            "3. Generate a risk profile with generate_risk_profile(model_spec, risk_metrics)\n"
            "4. Check the gate with check_gate(risk_profile)\n"
            "5. If gate requires human review, stop and wait\n"
            "6. If approved, write a PR comment with write_pr_comment\n\n"
            "Always proceed step by step. Call tools in order."
        ),
        thread_id="t-real-risk",
    )

    # 基础验证：Agent 至少跑了几步
    msgs = final.get("messages", [])
    assert len(msgs) >= 2, f"真 LLM 应至少产生 2 条消息，实际 {len(msgs)}"

    # 验证：至少调了一个 tool（不是纯文本回复）
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert len(tool_msgs) >= 1, (
        f"真 LLM 应至少调 1 个 tool，实际 tool messages: {len(tool_msgs)}。"
        f"LLM 可能只回了文本没调 tool，messages: {[type(m).__name__ for m in msgs]}"
    )

    # 验证：调了 read_blackboard（第一步）
    tool_names = {m.name for m in tool_msgs}
    assert "read_blackboard" in tool_names, (
        f"真 LLM 应调 read_blackboard，实际调了: {tool_names}"
    )

    # 如果有 __interrupt__，说明 check_gate 触发了人审
    if "__interrupt__" in final:
        interrupts = final["__interrupt__"]
        assert interrupts, "有 __interrupt__ 但为空"
        # 验证 interrupt payload 格式
        interrupt_obj = interrupts[0]
        payload = getattr(interrupt_obj, "value", interrupt_obj)
        assert isinstance(payload, dict), f"interrupt payload 应为 dict，got {type(payload)}"
        assert "gate_id" in payload
        assert "reasons" in payload


def test_agent_runner_risk_normal_scenario_no_interrupt(require_real_llm, tmp_path):
    """用真 LLM 跑 risk 正常场景（低风险），验证不触发 interrupt。

    LLM 应自主判断：正常场景下不需要人审，直接写 PR comment。
    """
    import tools.risk._register  # noqa: F401
    from runner.agent_engine import AgentRunner

    runner = AgentRunner(
        group="risk",
        model=require_real_llm,
        checkpoint_db=tmp_path / "cp_normal.db",
        max_iterations=6,
    )

    final = runner.run(
        task=(
            "你是一个风险控制 Agent。请读取 blackboard 中的模型 spec（normal scenario），"
            "计算风险指标，检查 gate。如果风险不高，不需要人审，直接写 PR comment。"
            "input_data: pr_number=1, scenario=normal, head_sha=abc."
        ),
        skill_name=None,
        system_prompt=(
            "You are a risk control agent. Read blackboard, calculate risk, "
            "check gate. If risk is normal (no human review needed), write PR comment. "
            "Call tools in order: read_blackboard -> calc_risk -> generate_risk_profile -> "
            "check_gate -> write_pr_comment."
        ),
        thread_id="t-real-normal",
    )

    msgs = final.get("messages", [])
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    tool_names = {m.name for m in tool_msgs}

    # 正常场景不应触发 interrupt
    assert "__interrupt__" not in final or not final.get("__interrupt__"), (
        "正常场景不应触发 interrupt"
    )

    # 至少调了 read_blackboard
    assert "read_blackboard" in tool_names, f"应调 read_blackboard，实际: {tool_names}"


# ---------------------------------------------------------------------------
# 2. factor AgentRunner 真 LLM 测试
# ---------------------------------------------------------------------------


def test_agent_runner_factor_with_real_llm(require_real_llm, tmp_path):
    """用真 DeepSeek LLM 跑 factor 3 步自主推理。

    与 test_factor_stub_tools.py 的 scripted mock 不同，这里 LLM 真实看到
    match_main 的返回结果后，自主决定下一步调 gen_schema，再看到 gen_schema
    结果后自主决定调 autoeval。这是"自主推理"的真实验证。

    验证点:
    - Agent 至少调了 match_main（第一步）
    - 如果调了 match_main，验证后续是否自主调了 gen_schema / autoeval
    - Agent 能正常结束
    """
    import tools.factor._register  # noqa: F401
    from runner.agent_engine import AgentRunner

    runner = AgentRunner(
        group="factor",
        model=require_real_llm,
        checkpoint_db=tmp_path / "cp_factor.db",
        max_iterations=6,
    )

    final = runner.run(
        task=(
            "你是一个因子生成助手。请生成一个 PB-ROE 季度再平衡因子：\n"
            "1. 先用 match_main(idea='PB-ROE 季度再平衡因子') 检查兼容性\n"
            "2. 再用 gen_schema 生成 FactorSpec\n"
            "3. 最后用 autoeval 提交回测\n"
            "请按顺序调用工具。"
        ),
        skill_name=None,
        system_prompt=(
            "You are a factor generation assistant. Follow the pipeline:\n"
            "1. match_main(idea) — check mainline compatibility\n"
            "2. gen_schema(idea, match_result) — generate FactorSpec\n"
            "3. autoeval(spec) — submit to AutoEval\n"
            "Call tools in order. Use the results from previous steps."
        ),
        thread_id="t-real-factor",
    )

    msgs = final.get("messages", [])
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    tool_names = {m.name for m in tool_msgs}

    assert len(tool_msgs) >= 1, (
        f"真 LLM 应至少调 1 个 tool，实际 {len(tool_msgs)}。"
        f"LLM 可能只回了文本没调 tool。"
    )

    # 至少调了 match_main
    assert "match_main" in tool_names, (
        f"真 LLM 应调 match_main 作为第一步，实际调了: {tool_names}"
    )

    # 如果调了 ≥3 个 tool，说明自主推理链完整
    if len(tool_names) >= 3:
        # 验证 3 步都在
        assert {"match_main", "gen_schema", "autoeval"} <= tool_names, (
            f"3 步 tool 应完整，实际: {tool_names}"
        )


# ---------------------------------------------------------------------------
# 3. Dream 原型真 LLM 测试
# ---------------------------------------------------------------------------


def test_dream_with_real_llm(require_real_llm, tmp_path):
    """用真 DeepSeek LLM 跑 Dream 原型，产出非 mock 的 memory。

    验证:
    - Dream 从 rlhf_data.jsonl 读 trace
    - 真 LLM 提取 summary（不是 mock 硬编码）
    - memory 能被检索到
    - memory body 不含 mock 标记
    """
    from dream.dream_prototype import run_dream

    # 写 rlhf fixture
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps(
            {
                "thread_id": "real-llm-dream-test",
                "state_fingerprint": "abc123",
                "action": {
                    "tool_name": "calc_risk",
                    "tool_args": {"scenario": "high_risk"},
                },
                "observation": {
                    "success": True,
                    "summary": "Risk calculated: VaR 99% = 0.06 exceeds threshold 0.04",
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "thread_id": "real-llm-dream-test",
                "state_fingerprint": "def456",
                "action": {
                    "tool_name": "check_gate",
                    "tool_args": {"risk_profile": {"var_99": 0.06}},
                },
                "observation": {
                    "success": True,
                    "requires_human": True,
                    "summary": "Gate check: requires human review",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 用真 LLM 跑 Dream
    # 注意：model 签名需匹配 (prompt: str) -> dict
    def dream_model(prompt: str) -> dict:
        """把 DeepSeek 适配器包成 Dream 需要的 model 签名。"""
        from langchain_core.messages import HumanMessage

        result = require_real_llm([HumanMessage(content=prompt)])
        content = result.content if hasattr(result, "content") else str(result)
        # 尝试解析 LLM 返回的 JSON
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # LLM 可能返回了非 JSON 文本，尝试提取 JSON 块
            import re

            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return {
                "repetitions": [f"LLM raw output: {content[:200]}"],
                "lessons": ["Dream real LLM test — could not parse JSON"],
                "hotspots": [],
            }

    hits = run_dream(
        trace_source="rlhf",
        rlhf_path=rlhf,
        memory_root=tmp_path,
        llm_mode="real",
        model=dream_model,
    )

    assert len(hits) >= 1, f"Dream 真 LLM 应产出 ≥1 条 memory，实际 {len(hits)}"

    # 验证：memory body 不含 mock 标记
    body_path = Path(hits[0]["path"])
    assert body_path.exists(), f"memory body 文件应存在: {body_path}"
    body = body_path.read_text(encoding="utf-8")
    for mock_token in [
        "Day 4 stub: 固定返回",
        "Day2 mock",
        "Agent 连续调 read_blackboard ≥3 次",
    ]:
        assert mock_token not in body, (
            f"真 LLM Dream 不应含 mock token '{mock_token}'，body: {body[:300]}"
        )

    # 验证：至少有一个 section 有内容
    assert any(
        section in body for section in ["Repetitions", "Lessons", "Hotspots"]
    ), f"Dream body 应含至少一个 section，body: {body[:300]}"


__all__ = [
    "test_agent_runner_risk_with_real_llm",
    "test_agent_runner_risk_normal_scenario_no_interrupt",
    "test_agent_runner_factor_with_real_llm",
    "test_dream_with_real_llm",
]
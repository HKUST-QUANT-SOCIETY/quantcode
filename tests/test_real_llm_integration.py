"""Real-provider integration of the legacy Python AgentRunner and Dream prototype.

These tests use a real OpenAI-compatible model with isolated local component
fixtures. They are not acceptance evidence for native QuantCode tasks or
canonical risk/factor services. Set QUANTCODE_USE_REAL_LLM=1 and configure the
provider through QUANTCODE_API_KEY/MODEL_NAME/MODEL_BASE_URL environment values.

运行::

    QUANTCODE_USE_REAL_LLM=1 pytest tests/test_real_llm_integration.py -v

覆盖:
1. risk AgentRunner 用真 LLM 自主决定调 risk_verdict + 后续 tool
2. factor AgentRunner 用真 LLM 跑 3 步自主推理
3. Dream 原型用真 LLM 产出非 mock 的 memory
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage


@pytest.fixture(autouse=True)
def isolated_legacy_runtime(tmp_path, monkeypatch):
    from runner import metrics
    from runner.langgraph_base import clear_checkpointer_cache
    from runner.routing import rlhf_logger
    from tools.registry import registry
    from tools.risk import risk_tools

    monkeypatch.setattr(registry, "_tools", {})
    monkeypatch.setattr(metrics, "METRICS_PATH", tmp_path / "metrics.jsonl")
    monkeypatch.setattr(rlhf_logger, "RLHF_PATH", tmp_path / "rlhf.jsonl")
    monkeypatch.setattr(risk_tools, "_DEDUPED_WRITERS", {})
    monkeypatch.setenv("QUANTCODE_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("QUANTCODE_POST_RISK_COMMENT", "0")
    monkeypatch.setenv("QUANTCODE_SSH_MAINLINE", "[]")
    for name in ("QUANT_EVALUATOR_API_URL", "QUANT_EVALUATOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def reject_external_comment(*args, **kwargs):
        raise AssertionError("Live-provider tests may not publish GitHub comments")

    monkeypatch.setattr(risk_tools, "_post_github_risk_comment", reject_external_comment)
    yield
    clear_checkpointer_cache()


def _run_risk_scenario(model, tmp_path, scenario):
    from runner.agent_engine import AgentRunner
    from runner.blackboard import BlackboardService
    from runner.blackboard_keys import PROJECT_SESSION_ID
    from schemas.model import ModelSpec
    from schemas.risk_profile import RiskProfile
    from tools.registry import ToolRegistry
    from tools.risk import _register as definitions

    spec = ModelSpec.model_validate_json(
        (Path(__file__).parent / "fixtures/sample_model/model_spec.json").read_text()
    ).model_dump(mode="json")
    database = tmp_path / "blackboard.db"
    key = "shared.model_entries.real_llm_fixture"
    BlackboardService(db_path=database, session_id=PROJECT_SESSION_ID, requester_group="model").write_value(
        scope="project", key=key, value=spec, written_by_task_id="T0.1", written_by_group="model",
    )
    input_data = {"blackboard_db_path": str(database), "blackboard_key": key}
    report = {"pr_number": "1", "head_sha": "abc1234", "pr_url": "https://example.invalid/qa/pull/1",
              "artifacts_root": str(tmp_path / "reports"), "dedupe_db_path": str(tmp_path / "dedupe.db"),
              "post_to_github": False}
    registry = ToolRegistry()
    outputs = {}
    failures = []
    tools = (definitions.read_blackboard_tool, definitions.calc_risk_tool,
             definitions.generate_risk_profile_tool, definitions.risk_verdict_tool, definitions.write_pr_comment_tool)
    for definition in tools:
        def execute(args, ctx, tool=definition):
            if tool.id == "read_blackboard":
                assert args.input_data == input_data, "Read the actual isolated Blackboard entry"
            if tool.id == "write_pr_comment":
                assert all(getattr(args, field) == value for field, value in report.items()), "Only the local test report is authorized"
            try:
                result = tool.execute(args, ctx)
            except ValueError as error:
                failures.append({"tool": tool.id, "args": args.model_dump(), "error": str(error)})
                raise
            outputs[tool.id] = result
            return result
        registry.register(definition.model_copy(update={"execute": execute}))

    final = AgentRunner(group="risk", model=model, registry=registry,
                        checkpoint_db=tmp_path / "checkpoint.db", max_iterations=8).run(
        task=(
            "Review the prepared risk fixture and save its local CI report. "
            "This is the legacy Python library test environment; the Blackboard database already exists. "
            f"First call read_blackboard with input_data={json.dumps(input_data)}. "
            f"Use its returned model_spec with calc_risk, scenario={scenario}. "
            "Pass the resulting metrics to generate_risk_profile and its profile to risk_verdict. "
            "Keep all returned profile fields, including the stub provenance in analyst_notes. "
            f"Then call write_pr_comment with that profile and these exact local report options: {json.dumps(report)}. "
            "A risk fail is a domain result and does not require a HumanGate. No GitHub publication is authorized."
        ),
        skill_name=None,
        system_prompt="Use the supplied tools to review the existing local fixture. Return a brief result after the local report is saved.",
        thread_id=f"t-real-risk-{scenario}",
    )
    tool_messages = [message for message in final.get("messages", []) if isinstance(message, ToolMessage)]
    names = [message.name for message in tool_messages]
    expected = [tool.id for tool in tools]
    assert set(expected) <= set(names), f"Incomplete real-provider tool chain: {names}; failures: {failures}"
    assert set(expected) <= outputs.keys(), f"Tool attempts did not succeed: {list(outputs)}"
    assert [names.index(name) for name in expected] == sorted(names.index(name) for name in expected)
    assert not final.get("errors"), {"errors": final.get("errors"), "failures": failures}
    assert not final.get("__interrupt__"), "Risk verdicts do not require a HumanGate"
    assert outputs["read_blackboard"]["model_spec"] == spec
    verdict = outputs["risk_verdict"]
    assert verdict["verdict"] == ("pass" if scenario == "normal" else "fail")
    assert verdict["breached"] is (scenario == "high_risk")
    artifact = Path(outputs["write_pr_comment"]["artifact_path"])
    assert artifact.is_relative_to(tmp_path / "reports")
    saved = json.loads(artifact.read_text())
    profile = RiskProfile.model_validate(saved["risk_profile"])
    assert profile.strategy_id == spec["model_name"]
    assert "_is_stub" in (profile.analyst_notes or "")
    assert saved["risk_profile"] == verdict["risk_profile"]
    assert "github_comment_id" not in outputs["write_pr_comment"]


# ---------------------------------------------------------------------------
# 1. risk AgentRunner 真 LLM 测试
# ---------------------------------------------------------------------------


def test_agent_runner_risk_with_real_llm(require_real_llm, tmp_path):
    """A breached fixture produces a real tool-chain fail report without a Gate."""
    _run_risk_scenario(require_real_llm, tmp_path, "high_risk")


def test_agent_runner_risk_normal_scenario_no_interrupt(require_real_llm, tmp_path):
    """A normal fixture produces a complete local pass report without a Gate."""
    _run_risk_scenario(require_real_llm, tmp_path, "normal")


# ---------------------------------------------------------------------------
# 2. factor AgentRunner 真 LLM 测试
# ---------------------------------------------------------------------------


def test_agent_runner_factor_with_real_llm(require_real_llm, tmp_path):
    """用真 DeepSeek LLM 跑 factor 3 步自主推理。

    与 test_factor_stub_tools.py 的 scripted mock 不同，这里 LLM 真实看到
    match_main 的返回结果后，自主决定下一步调 gen_schema，再看到 gen_schema
    结果后自主决定调 quant_evaluator。这是"自主推理"的真实验证。

    验证点:
    - Agent 至少调了 match_main（第一步）
    - 如果调了 match_main，验证后续是否自主调了 gen_schema / quant_evaluator
    - Agent 能正常结束
    """
    from runner.agent_engine import AgentRunner
    from tools.factor.match_main import match_main_tool
    from tools.factor.gen_schema import gen_schema_tool
    from tools.factor.quant_evaluator_adapter import quant_evaluator_tool
    from tools.registry import ToolRegistry

    registry = ToolRegistry()
    for tool in (match_main_tool, gen_schema_tool, quant_evaluator_tool):
        registry.register(tool)

    runner = AgentRunner(
        group="factor",
        model=require_real_llm,
        registry=registry,
        checkpoint_db=tmp_path / "cp_factor.db",
        max_iterations=6,
    )

    final = runner.run(
        task=(
            "你是一个因子生成助手。请生成一个 PB-ROE 季度再平衡因子：\n"
            "1. 先用 match_main(idea='PB-ROE 季度再平衡因子') 检查兼容性\n"
            "2. 再用 gen_schema 生成 FactorSpec\n"
            "3. 最后用 quant_evaluator 提交回测\n"
            "请按顺序调用工具。"
        ),
        skill_name=None,
        system_prompt=(
            "You are a factor generation assistant. Follow the pipeline:\n"
            "1. match_main(idea) — check mainline compatibility\n"
            "2. gen_schema(idea, match_result) — generate FactorSpec\n"
            "3. quant_evaluator(spec) — submit to AutoEval\n"
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
        assert {"match_main", "gen_schema", "quant_evaluator"} <= tool_names, (
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
                    "tool_name": "risk_verdict",
                    "tool_args": {"risk_profile": {"var_99": 0.06}},
                },
                "observation": {
                    "success": True,
                    "breached": True,
                    "summary": "Risk verdict: fail; report the threshold breach without a HumanGate",
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

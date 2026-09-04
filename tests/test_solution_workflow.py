"""P-10 方案先行工作流测试（specs/FUNCTIONAL_SPEC.md P-10 验收草案四条）。

验收草案断言映射：
1. 下达功能目标后首轮只产方案不产代码 → draft 态写工具调用被 deny 且提示
   "方案未冻结"（test_tool_node_denies_write_in_draft / test_phase_filter*）；
2. min_rounds 未满足时冻结被拒（test_freeze_refused_below_min_rounds /
   test_freeze_tool_refuses_below_min_rounds_via_registry）；
3. frozen 后代码产出经 judge verdict 可复核（test_judge_conformance_conformant）；
4. 偏离方案的文件改动被报告（test_judge_deviation_lists_extra_files）。

语义边界断言：阶段限流实现为 tool 过滤，**零 HumanGate interrupt**——
draft deny 路径返回普通 ToolMessage（test_tool_node_denies_write_in_draft）。
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from runner.agent_nodes import (
    AgentState,
    _extract_state_fields,
    make_llm_node,
    make_tool_node,
)
from runner.config_loader import load_yaml
from runner.judge import SOLUTION_VERDICTS, judge_solution_conformance
from runner.solution_workflow import (
    PHASE_DENY_MESSAGE,
    SOLUTION_TOOLS,
    SolutionStore,
    SolutionWorkflowError,
    add_round,
    filter_tools_for_phase,
    freeze_solution,
    load_workflow_config,
    start_solution,
    supersede_solution,
    sync_phase_from_blackboard,
    tool_allowed_in_phase,
    tool_denied_message,
)
from schemas.solution_doc import SolutionDoc, SolutionRound, SolutionStatus
from tools.registry import ToolDef, ToolRegistry

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_workflow_config():
    """每次测试前后清 config 缓存（load_yaml / load_workflow_config 均 lru_cache）。"""
    load_yaml.cache_clear()
    load_workflow_config.cache_clear()
    yield
    load_yaml.cache_clear()
    load_workflow_config.cache_clear()


@pytest.fixture
def sol_env(tmp_path):
    """隔离的 SolutionStore + blackboard db 路径（测试零仓库副作用）。"""
    db = tmp_path / "bb.db"
    store = SolutionStore(blackboard_db_path=db, artifacts_dir=tmp_path / "solutions")
    return store, db


@pytest.fixture
def std_config(tmp_path, monkeypatch):
    """固定 min_rounds=2 / max_rounds=3 的确定性配置（避免依赖仓库 yaml 现值）。"""
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "solution_workflow.yaml").write_text(
        "min_rounds: 2\nmax_rounds: 3\nallow_trivial_exempt: false\n", encoding="utf-8"
    )
    load_yaml.cache_clear()
    load_workflow_config.cache_clear()
    return {"min_rounds": 2, "max_rounds": 3, "allow_trivial_exempt": False}


def _frozen_doc(store: SolutionStore, goal: str = "做因子", files: list[str] | None = None):
    """走完整流程拿一个 frozen 文档（2 轮讨论 → 显式确认冻结）。"""
    doc = start_solution(goal, store=store, file_impact=files or ["a.py", "b.py"])
    add_round(doc.id, "第一轮反馈：补对照实验", store=store)
    doc = add_round(doc.id, "第二轮反馈：确认口径", store=store)
    return freeze_solution(doc.id, confirm=True, store=store)


# ---------------------------------------------------------------------------
# 契约（SolutionDoc）
# ---------------------------------------------------------------------------


def test_solution_doc_extra_forbid():
    with pytest.raises(ValidationError):
        SolutionDoc(id="sol-x", goal="g", unknown_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SolutionRound(round_no=1, feedback="f", unknown_field=1)  # type: ignore[call-arg]


def test_solution_doc_defaults_and_status_enum():
    doc = SolutionDoc(id="sol-x", goal="g")
    assert doc.status is SolutionStatus.DRAFT
    assert doc.rounds == [] and doc.file_impact == [] and doc.doc_hash == ""
    assert {s.value for s in SolutionStatus} == {"draft", "frozen", "superseded"}


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


def test_start_creates_draft_and_persists_dual_write(sol_env):
    store, _db = sol_env
    doc = start_solution("做一个动量因子", store=store, file_impact=["f1.py"])
    assert doc.status is SolutionStatus.DRAFT
    assert doc.doc_hash  # 内容摘要已计算
    # Blackboard 回源一致
    back = store.get(doc.id)
    assert back is not None and back.status is SolutionStatus.DRAFT
    assert back.doc_hash == doc.doc_hash
    # artifacts md 落盘
    assert (store.artifacts_dir / f"{doc.id}-v{doc.version}.md").exists()


def test_start_rejects_duplicate_and_empty_goal(sol_env):
    store, _db = sol_env
    doc = start_solution("目标A", store=store)
    with pytest.raises(SolutionWorkflowError, match="已存在"):
        start_solution("目标B", doc_id=doc.id, store=store)
    with pytest.raises(SolutionWorkflowError, match="goal"):
        start_solution("   ", store=store)


def test_freeze_refused_below_min_rounds(sol_env, std_config):
    """P-10 验收草案 #2：min_rounds 未满足时冻结被拒。"""
    store, _db = sol_env
    doc = start_solution("g", store=store)
    with pytest.raises(SolutionWorkflowError, match="显式确认"):
        freeze_solution(doc.id, store=store)  # 未 confirm
    with pytest.raises(SolutionWorkflowError, match="讨论轮次不足"):
        freeze_solution(doc.id, confirm=True, store=store)
    add_round(doc.id, "只有一轮反馈", store=store)
    with pytest.raises(SolutionWorkflowError, match="讨论轮次不足"):
        freeze_solution(doc.id, confirm=True, store=store)
    # 文档仍是 draft
    assert store.get(doc.id).status is SolutionStatus.DRAFT


def test_freeze_after_min_rounds_and_hash_bump(sol_env, std_config):
    store, _db = sol_env
    doc = start_solution("g", store=store)
    h1 = doc.doc_hash
    add_round(doc.id, "r1", store=store)
    doc = add_round(doc.id, "r2", store=store)
    assert doc.doc_hash != h1  # 修订后内容摘要变化（可复核）
    frozen = freeze_solution(doc.id, confirm=True, store=store)
    assert frozen.status is SolutionStatus.FROZEN
    # 幂等：重复冻结返回原样
    assert freeze_solution(doc.id, confirm=True, store=store).version == frozen.version


def test_max_rounds_marks_needs_human_and_refuses_more(sol_env, std_config):
    store, _db = sol_env
    doc = start_solution("g", store=store)
    add_round(doc.id, "r1", store=store)
    add_round(doc.id, "r2", store=store)
    doc = add_round(doc.id, "r3", store=store)
    assert doc.needs_human is True  # 达 max_rounds → 人裁标记
    with pytest.raises(SolutionWorkflowError, match="需要人裁"):
        add_round(doc.id, "r4", store=store)  # 超轮数拒绝加轮
    # 达 max_rounds（3 >= min_rounds 2）仍可冻结（人选择放行）
    frozen = freeze_solution(doc.id, confirm=True, store=store)
    assert frozen.needs_human is False and frozen.status is SolutionStatus.FROZEN


def test_trivial_exempt_switch(sol_env, std_config, tmp_path, monkeypatch):
    store, _db = sol_env
    # 默认关：显式声明 trivial 也被拒（非平凡任务必须走方案先行）
    with pytest.raises(SolutionWorkflowError, match="豁免"):
        start_solution("typo fix", trivial=True, store=store)
    # 开关打开 → 直接 frozen 落库留痕（跳过讨论轮次）
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "solution_workflow.yaml").write_text(
        "min_rounds: 2\nmax_rounds: 3\nallow_trivial_exempt: true\n", encoding="utf-8"
    )
    load_yaml.cache_clear()
    load_workflow_config.cache_clear()
    doc = start_solution("typo fix", trivial=True, store=store)
    assert doc.status is SolutionStatus.FROZEN and doc.trivial_exempt is True
    assert doc.rounds == []


def test_supersede(sol_env, std_config):
    store, _db = sol_env
    doc = _frozen_doc(store)
    out = supersede_solution(doc.id, store=store)
    assert out.status is SolutionStatus.SUPERSEDED


def test_workflow_config_defaults_and_clamp(tmp_path, monkeypatch):
    # 仓库配置（min_rounds=2 / max_rounds=3 / 豁免关）
    cfg = load_workflow_config()
    assert cfg == {"min_rounds": 2, "max_rounds": 3, "allow_trivial_exempt": False}
    # 缺文件 → 代码默认兜底；min>max 时 max 被 clamp 到 min
    monkeypatch.setenv("QUANTCODE_CONFIG_DIR", str(tmp_path))
    load_yaml.cache_clear()
    load_workflow_config.cache_clear()
    cfg2 = load_workflow_config()
    assert cfg2["min_rounds"] == 2 and cfg2["max_rounds"] >= cfg2["min_rounds"]


# ---------------------------------------------------------------------------
# 阶段限流（tool 过滤，非 interrupt）
# ---------------------------------------------------------------------------


def test_phase_filter_whitelist():
    # draft 态：方案类工具 + 只读前缀放行；写类（write_*/merge_*/deploy_*/run_*）deny
    for tid in SOLUTION_TOOLS:
        assert tool_allowed_in_phase(tid, "draft")
    for tid in ("read_pr", "read_blackboard", "list_factors", "get_experiment",
                "risk_verdict", "match_main", "pit_rag_search", "pool_browse",
                "describe_algorithm", "extract_metadata"):
        assert tool_allowed_in_phase(tid, "draft"), tid
    for tid in ("write_blackboard", "write_pr_comment", "merge_to_main",
                "deployment_candidate", "run_strategy_backtest", "spawn_subagent",
                "mark_task_done", "trigger_risk_flow"):
        assert not tool_allowed_in_phase(tid, "draft"), tid
    # 拒绝信息含验收文案
    assert PHASE_DENY_MESSAGE == "方案未冻结，代码工具不可用"
    assert PHASE_DENY_MESSAGE in tool_denied_message("write_blackboard")
    # 非 draft：全放行
    for tid in ("write_blackboard", "read_pr", "draft_solution"):
        assert tool_allowed_in_phase(tid, None)
        assert tool_allowed_in_phase(tid, "frozen")


def test_filter_tools_for_phase():
    tools = [_tool("write_blackboard"), _tool("read_pr"), _tool("draft_solution")]
    visible = filter_tools_for_phase(tools, "draft")
    # 过滤保序（不排序）：写类被剔除，只读 + 方案类保留
    assert [t.id for t in visible] == ["read_pr", "draft_solution"]
    # 非 draft 原样放行
    assert len(filter_tools_for_phase(tools, "frozen")) == 3
    assert len(filter_tools_for_phase(tools, None)) == 3


# ----- tool_node / llm_node 接线 -----


class _WriteArgs(BaseModel):
    path: str


class _ReadArgs(BaseModel):
    name: str


class _StubArgs(BaseModel):
    x: str = ""


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def write_exec(self, args: _WriteArgs, ctx: dict) -> str:
        self.calls.append(args.path)
        return f"wrote {args.path}"


def _tool(tid: str) -> ToolDef:
    """按 id 构造最小 ToolDef（filter_tools_for_phase 等纯函数用）。"""
    return ToolDef(id=tid, description=tid, schema=_StubArgs, execute=lambda a, c: {"ok": True})


@pytest.fixture
def phase_registry():
    rec = _Recorder()
    reg = ToolRegistry()
    reg.register(ToolDef(
        id="write_blackboard", description="write-class stub（registry 真实写类命名）",
        schema=_WriteArgs, execute=rec.write_exec,
    ))
    reg.register(ToolDef(
        id="read_pr", description="read-only stub",
        schema=_ReadArgs, execute=lambda a, c: f"pr:{a.name}",
    ))
    return reg, rec


def _ai_call(name: str, args: dict, cid: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])


def test_tool_node_denies_write_in_draft(sol_env, std_config, phase_registry):
    """P-10 验收草案 #1：draft 态写工具调用被 deny 且提示"方案未冻结"。

    同时断言零 HumanGate interrupt：节点正常返回 ToolMessage（任何 interrupt
    冒泡都会让本测试以 GraphInterrupt 失败）。
    """
    store, db = sol_env
    reg, rec = phase_registry
    doc = start_solution("g", store=store)
    node = make_tool_node(reg)
    state: AgentState = {
        "messages": [_ai_call("write_blackboard", {"path": "x.py"})],
        "group": "model",
        "thread_id": "t-sol",
        "solution_phase": "draft",
        "solution_id": doc.id,
        "_blackboard_db_path": str(db),
    }
    out = node(state)
    msg = out["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert PHASE_DENY_MESSAGE in msg.content
    assert "方案未冻结" in msg.content and "代码工具不可用" in msg.content
    assert rec.calls == []  # 写类工具确实未执行
    # 阶段写回 state（llm_node 下一轮可见工具面据此收窄）
    assert out["solution_phase"] == "draft"


def test_tool_node_allows_write_after_frozen_via_blackboard_sync(sol_env, std_config, phase_registry):
    """state 里 phase 仍是 draft，但 Blackboard 上文档已被冻结（模拟 /solution
    面板跨进程冻结）→ tool_node 回源后解除限流并写回 frozen。"""
    store, db = sol_env
    reg, rec = phase_registry
    doc = start_solution("g", store=store)
    add_round(doc.id, "r1", store=store)
    doc = add_round(doc.id, "r2", store=store)
    freeze_solution(doc.id, confirm=True, store=store)
    node = make_tool_node(reg)
    state: AgentState = {
        "messages": [_ai_call("write_blackboard", {"path": "x.py"})],
        "group": "model",
        "thread_id": "t-sol",
        "solution_phase": "draft",  # 陈旧值：靠 Blackboard 回源纠正
        "solution_id": doc.id,
        "_blackboard_db_path": str(db),
    }
    out = node(state)
    assert out["solution_phase"] == "frozen"
    assert rec.calls == ["x.py"]  # frozen 后写类工具恢复可用
    assert out["messages"][0].content == "wrote x.py"


def test_tool_node_without_workflow_untouched(phase_registry):
    """未启动工作流（state 无 solution 字段）→ 行为与改动前完全一致。"""
    reg, rec = phase_registry
    node = make_tool_node(reg)
    state: AgentState = {
        "messages": [_ai_call("write_blackboard", {"path": "y.py"})],
        "group": "model",
        "thread_id": "t-plain",
    }
    out = node(state)
    assert rec.calls == ["y.py"]
    assert "solution_phase" not in out
    assert "solution_id" not in out


def test_tool_node_draft_without_doc_id_still_denies(phase_registry, tmp_path):
    """phase=draft 但 solution_id 缺失/文档读不到 → 保守维持 deny（fail-closed）。"""
    reg, rec = phase_registry
    node = make_tool_node(reg)
    base: AgentState = {
        "messages": [_ai_call("write_blackboard", {"path": "z.py"})],
        "group": "model",
        "thread_id": "t-sol",
        "solution_phase": "draft",
    }
    out = node(base)
    assert PHASE_DENY_MESSAGE in out["messages"][0].content
    assert rec.calls == []
    # solution_id 指向不存在的文档 → 保留现值 draft，仍 deny
    state2: AgentState = {**base, "solution_id": "sol-nope", "_blackboard_db_path": str(tmp_path / "missing.db")}
    out2 = node(state2)
    assert PHASE_DENY_MESSAGE in out2["messages"][0].content
    assert rec.calls == []


def test_tool_node_allows_read_tools_in_draft(sol_env, std_config, phase_registry):
    store, db = sol_env
    reg, _rec = phase_registry
    doc = start_solution("g", store=store)
    node = make_tool_node(reg)
    state: AgentState = {
        "messages": [_ai_call("read_pr", {"name": "n"})],
        "group": "model",
        "thread_id": "t-sol",
        "solution_phase": "draft",
        "solution_id": doc.id,
        "_blackboard_db_path": str(db),
    }
    out = node(state)
    assert out["messages"][0].content == "pr:n"


class _CaptureLLM:
    def __init__(self) -> None:
        self.seen_tools: list[Any] | None = None

    def __call__(self, messages, tools=None):  # noqa: ANN001, ANN202
        self.seen_tools = list(tools or [])
        return AIMessage(content="ok")


def test_llm_node_filters_visible_tools_in_draft():
    llm = _CaptureLLM()
    tools = [_tool("write_blackboard"), _tool("read_pr"), _tool("draft_solution")]
    node = make_llm_node(llm, tools)
    node({"messages": [], "solution_phase": "draft"})
    assert [t.id for t in llm.seen_tools] == ["read_pr", "draft_solution"]
    # 未启动工作流 / frozen → 全量可见
    node({"messages": []})
    assert len(llm.seen_tools) == 3
    node({"messages": [], "solution_phase": "frozen"})
    assert len(llm.seen_tools) == 3


def test_extract_state_fields_injects_solution_keys():
    updates = _extract_state_fields(
        "draft_solution", {"ok": True, "solution_id": "sol-x", "solution_phase": "draft"}
    )
    assert updates["solution_id"] == "sol-x"
    assert updates["solution_phase"] == "draft"
    # 非 solution 工具输出不注入
    assert "solution_id" not in _extract_state_fields("calc_risk", {"risk_metrics": {}})
    # 缺 solution_id 的输出不注入（防误激活工作流）
    assert "solution_id" not in _extract_state_fields("x", {"solution_phase": "draft"})


def test_sync_phase_from_blackboard(sol_env, std_config):
    store, db = sol_env
    doc = _frozen_doc(store)
    # 激活态 + 文档存在 → 回源真实状态
    assert sync_phase_from_blackboard("draft", doc.id, str(db)) == "frozen"
    # 未激活 → 原样返回，不读 db
    assert sync_phase_from_blackboard(None, doc.id, str(db)) is None
    # doc_id 缺失 / 文档不存在 → 保留现值
    assert sync_phase_from_blackboard("draft", None, str(db)) == "draft"
    assert sync_phase_from_blackboard("draft", "sol-nope", str(db)) == "draft"


# ---------------------------------------------------------------------------
# 标准 registry 通道注册（tools/solution/_register.py）
# ---------------------------------------------------------------------------


def test_solution_tools_registered():
    from tools.solution._register import register_all

    register_all()  # 幂等：registry 被先前测试清空后也能恢复

    from tools.registry import registry as global_registry

    ids = global_registry.list_ids()
    for tid in ("draft_solution", "revise_solution", "freeze_solution", "solution_status"):
        assert tid in ids, tid


def test_solution_tool_roundtrip_via_registry(sol_env, std_config):
    """四工具经 registry.call 全流程走通（ctx.blackboard_db_path 注入同一 bb 文件）。"""
    from tools.solution._register import register_all

    register_all()  # 幂等：registry 被先前测试清空后也能恢复

    from tools.registry import registry as global_registry

    _store, db = sol_env
    ctx = {"blackboard_db_path": str(db)}

    out = global_registry.call(
        "draft_solution",
        {"goal": "实现某功能", "file_impact": ["a.py"], "acceptance_criteria": ["c1"]},
        ctx=ctx,
    )
    assert out["ok"] is True and out["solution_phase"] == "draft"
    assert out["min_rounds"] == 2 and out["max_rounds"] == 3
    doc_id = out["solution_id"]

    global_registry.call("revise_solution", {"doc_id": doc_id, "feedback": "r1"}, ctx=ctx)
    rv = global_registry.call("revise_solution", {"doc_id": doc_id, "feedback": "r2"}, ctx=ctx)
    assert rv["ok"] and rv["rounds"] == 2

    st = global_registry.call("solution_status", {"doc_id": doc_id}, ctx=ctx)
    assert st["ok"] and st["status"] == "draft" and st["file_impact"] == ["a.py"]

    fz = global_registry.call("freeze_solution", {"doc_id": doc_id, "confirm": True}, ctx=ctx)
    assert fz["ok"] and fz["solution_phase"] == "frozen"

    missing = global_registry.call("solution_status", {"doc_id": "sol-nope"}, ctx=ctx)
    assert missing["ok"] is False and "不存在" in missing["error"]


def test_freeze_tool_refuses_below_min_rounds_via_registry(sol_env, std_config):
    """P-10 验收草案 #2（工具通道）：拒绝原因对 LLM 可见（返回值而非脱敏异常）。"""
    from tools.solution._register import register_all

    register_all()  # 幂等：registry 被先前测试清空后也能恢复

    from tools.registry import registry as global_registry

    _store, db = sol_env
    ctx = {"blackboard_db_path": str(db)}
    out = global_registry.call("draft_solution", {"goal": "另一目标"}, ctx=ctx)
    refused = global_registry.call(
        "freeze_solution", {"doc_id": out["solution_id"], "confirm": True}, ctx=ctx
    )
    assert refused["ok"] is False
    assert "讨论轮次不足" in refused["error"]
    # 未显式确认
    global_registry.call("revise_solution", {"doc_id": out["solution_id"], "feedback": "r1"}, ctx=ctx)
    global_registry.call("revise_solution", {"doc_id": out["solution_id"], "feedback": "r2"}, ctx=ctx)
    no_confirm = global_registry.call(
        "freeze_solution", {"doc_id": out["solution_id"]}, ctx=ctx
    )
    assert no_confirm["ok"] is False and "显式确认" in no_confirm["error"]
    # 重复 id
    dup = global_registry.call("draft_solution", {"goal": "另一目标"}, ctx=ctx)
    assert dup["ok"] is False and "已存在" in dup["error"]
    # trivial 豁免未开启
    tv = global_registry.call(
        "draft_solution", {"goal": "单点修复", "trivial": True}, ctx=ctx
    )
    assert tv["ok"] is False and "豁免" in tv["error"]


# ---------------------------------------------------------------------------
# 一致性判定（runner/judge.py）
# ---------------------------------------------------------------------------


def test_judge_conformance_conformant(sol_env, std_config):
    """P-10 验收草案 #3：frozen 后 judge verdict 可复核。"""
    store, _db = sol_env
    doc = _frozen_doc(store, files=["a.py", "b.py"])
    res = judge_solution_conformance(store.get(doc.id), ["b.py", "a.py"])
    assert res["verdict"] == "conformant"
    assert res["deviations"] == [] and res["missing"] == []
    assert res["doc_status"] == "frozen" and res["doc_hash"] == doc.doc_hash
    assert res["verdict"] in SOLUTION_VERDICTS


def test_judge_deviation_lists_extra_files(sol_env, std_config):
    """P-10 验收草案 #4：偏离 file_impact 的改动出现在偏离清单。"""
    store, _db = sol_env
    doc = _frozen_doc(store, files=["a.py"])
    res = judge_solution_conformance(store.get(doc.id), ["a.py", "rogue.py", "other.py"])
    assert res["verdict"] == "deviation"
    assert res["deviations"] == ["other.py", "rogue.py"]  # 排序稳定，全部列出
    assert "rogue.py" in res["reasons"][0]


def test_judge_missing_planned_file(sol_env, std_config):
    store, _db = sol_env
    doc = _frozen_doc(store, files=["a.py", "b.py"])
    res = judge_solution_conformance(store.get(doc.id), ["a.py"])
    assert res["verdict"] == "deviation"
    assert res["missing"] == ["b.py"] and res["deviations"] == []


def test_judge_unfrozen_or_missing_doc_needs_human(sol_env, std_config):
    store, _db = sol_env
    doc = start_solution("draft-case", store=store, file_impact=["a.py"])
    # draft（未冻结）不构成判定基准
    res = judge_solution_conformance(store.get(doc.id), ["a.py"])
    assert res["verdict"] == "needs_human"
    # 文档缺失
    assert judge_solution_conformance(None, ["a.py"])["verdict"] == "needs_human"
    # dict 形态入参（model_dump）兼容
    frozen = _frozen_doc(store, goal="dict-case", files=["a.py"])
    res2 = judge_solution_conformance(store.get(frozen.id).model_dump(mode="json"), ["a.py"])
    assert res2["verdict"] == "conformant"


class _FakeJudgeLLM:
    def __init__(self, content: str | Exception) -> None:
        self._content = content

    def __call__(self, messages, tools=None):  # noqa: ANN001, ANN202
        if isinstance(self._content, Exception):
            raise self._content
        return AIMessage(content=self._content)


def test_judge_semantic_escalation_and_degradation(sol_env, std_config):
    """LLM 语义判定接口：只升级（needs_human），不推翻确定性结论；失败诚实降级。"""
    store, _db = sol_env
    doc = _frozen_doc(store, files=["a.py"])
    sdoc = store.get(doc.id)
    # 语义判定 needs_human → 升级
    llm_ok = _FakeJudgeLLM('{"verdict": "needs_human", "reasons": ["验收标准未覆盖"]}')
    res = judge_solution_conformance(sdoc, ["a.py"], llm=llm_ok, semantic=True)
    assert res["verdict"] == "needs_human"
    assert res["semantic"]["degraded"] is False
    assert "验收标准未覆盖" in res["reasons"][-1]
    # 语义 conformant 不推翻确定性 deviation
    res_dev = judge_solution_conformance(
        sdoc, ["a.py", "rogue.py"], llm=_FakeJudgeLLM('{"verdict": "conformant"}'), semantic=True
    )
    assert res_dev["verdict"] == "deviation" and "rogue.py" in res_dev["deviations"]
    # LLM 异常 → 确定性结论保留，semantic 诚实降级
    res_bad = judge_solution_conformance(
        sdoc, ["a.py"], llm=_FakeJudgeLLM(RuntimeError("boom")), semantic=True
    )
    assert res_bad["verdict"] == "conformant"
    assert res_bad["semantic"]["degraded"] is True
    # 要 semantic 但没给 llm → 降级不炸
    res_nollm = judge_solution_conformance(sdoc, ["a.py"], semantic=True)
    assert res_nollm["verdict"] == "conformant" and res_nollm["semantic"]["degraded"] is True
    # 默认不跑语义
    assert judge_solution_conformance(sdoc, ["a.py"])["semantic"] is None

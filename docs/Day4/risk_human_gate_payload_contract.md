# Day 4 · risk HumanGate Interrupt Payload 字段契约

> Owner: 尹一帆(route_gate 节点侧) ⇄ 杨欣琳(resume / write PR comment 侧)
> 同步状态: **草案,待与杨欣琳确认**
> 配套代码:
> - `quantcode/schemas/human_gate.py:HumanGateInterruptPayload`
> - `quantcode/runner/human_gate.py:build_interrupt_payload`
> - `quantcode/runner/risk_agent.py:67-127 run_tool_pipeline`(interrupt 调用点)

---

## 1. 背景

Day 4 §2 / §3 要求 risk 流程"经 AgentRunner 跑通人审场景(超阈值 → interrupt → approve → 恢复),不再是 scripted"。我的实现走 `route_gate` 节点(详细 plan 见 `C:\Users\Yin\.claude\plans\virtual-greeting-robin.md`):

```
AgentRunner (StateGraph)
  llm → tool → [route_gate] → rlhf → llm ...
       └ post_tool_check ─┘
       (gate_tools 列表内的 tool 调完后,自动走 route_gate 检查)
```

`route_gate` 节点检测到 LLM 调了 `check_gate` 且返回值 `requires_human=True` 时,调 LangGraph `interrupt(build_interrupt_payload(...))`。杨欣琳侧通过 `Command(resume={...})` 恢复,Agent 继续推理到 `write_pr_comment` 写出真 PR comment。

**关键问题**:杨欣琳的"测试 PR 上真出现 risk comment"(Day 4 §3 验收)需要 `pr_number` / `repo`,**这些字段的来源是 interrupt payload,还是 `state["input_data"]`?**

---

## 2. 当前 `HumanGateInterruptPayload` 字段(基线)

`quantcode/schemas/human_gate.py:46-55` 定义 Pydantic 模型:

```python
class HumanGateInterruptPayload(BaseModel):
    gate_id: str                    # 唯一 gate 标识(hg_<thread_id>_<uuid12>)
    message: str                    # 固定 "⏸️ 等待人工审批" 或自定义
    risk_profile: dict[str, Any]    # 完整 RiskProfile 序列化
    reasons: list[str]              # breached_thresholds 列表(如 ["var_99_breached"])
    decision: str | None = None     # 恢复时由 Command(resume={"decision": ...}) 注入
```

**`pr_number` / `repo` 都不在 schema 里**,目前 interrupt payload 不携带这些。

---

## 3. JSON 样例(真实值)

`build_interrupt_payload(gate_id="hg_risk_abc123_xyz789", risk_profile=..., reasons=["var_99_breached"])` 返回:

```json
{
  "gate_id": "hg_risk_abc123_xyz789",
  "message": "⏸️ 等待人工审批",
  "risk_profile": {
    "strategy_id": "PB-ROE-v3",
    "var_99": 0.052,
    "max_drawdown": -0.12,
    "position_limit_usage": 0.85,
    "correlation": 0.65,
    "thresholds": {
      "var_99_limit": 0.04,
      "max_drawdown_limit": -0.15,
      "position_limit_limit": 0.8,
      "correlation_limit": 0.7
    },
    "computed_at": "2026-07-08T10:23:45Z"
  },
  "reasons": ["var_99_breached"],
  "decision": null
}
```

恢复时杨欣琳的 `Command(resume={"decision": "approve"})` 会把 `"decision"` 字段填成 `"approve"` 或 `"reject"`,Agent 继续推理到下一步(approve → write_pr_comment / reject → finalize_output)。

---

## 4. 字段表(给杨欣琳看的接口契约)

| 字段 | 类型 | 含义 | 用途 |
|---|---|---|---|
| `gate_id` | `str` | gate 唯一标识 | dedupe、audit log、PR comment marker(在 PR comment 顶部加一行 `<!-- risk-gate: hg_risk_... -->`) |
| `message` | `str` | 人审提示语 | UI 展示给审批人,默认"⏸️ 等待人工审批" |
| `risk_profile` | `dict` | 完整 RiskProfile 序列化 | PR comment 内容生成(从 risk_profile 字段拼 markdown 表格) |
| `reasons` | `list[str]` | 触发 gate 的阈值违例列表 | PR comment 标题(`Risk Profile Rejected: {reasons}`) |
| `decision` | `str \| null` | 恢复时填入("approve"/"reject") | route_gate 节点用此判定 `write_pr_comment` 还是 `finalize_output` |

---

## 5. `pr_number` / `repo` 来源 — 决策建议

**建议:杨欣琳从 `state["input_data"]` 拿,不进 interrupt payload。**

理由:
1. **payload 应保持"业务中性"**:interrupt payload 是 HumanGate 通用机制,不应耦合 PR 概念(strategy / factor / fundamental / options 各种 gate 都能复用)
2. **避免 schema 污染**:`HumanGateInterruptPayload` 加 pr_number 后,所有 gate 实现都要填这个字段,即便没有 PR
3. **input_data 已是事实来源**:`risk_agent.py:run_tool_pipeline` 调 `calc_risk(input_data={"pr_number": 123, "repo": "org/name", ...})`,杨欣琳写 PR comment 时直接读 `state["input_data"]["pr_number"]` 即可
4. **简化接口契约**:`make_route_gate_node` 实现里 `assert "gate_id" in payload` 即可,不需要在 gate 节点访问 input_data

**杨欣琳需要的 input_data 字段**(`runner.risk_agent.write_pr_comment_node` 当前已用):

```python
input_data = state["input_data"]
profile = RiskProfile(**state["risk_profile"])
comment = write_pr_comment_artifact(
    profile,
    pr_number=str(input_data.get("pr_number", "demo")),
    head_sha=input_data.get("head_sha", "deadbeef"),
    pr_url=input_data.get("pr_url"),
    artifacts_root=input_data.get("artifacts_root", "artifacts/risk/pr-comments"),
    dedupe_db_path=input_data.get("dedupe_db_path"),
)
```

---

## 6. 实现侧保证(给杨欣琳的承诺)

我方在 `make_route_gate_node` 实现中保证:

1. `assert "gate_id" in payload`(每次 interrupt 前硬校验,缺 gate_id 立即报错)
2. `gate_id` 唯一稳定:同 thread_id 同次风险评估只产生 1 个 gate_id(去重由 `HumanGateStatus.APPROVED/REJECTED` 状态机保证)
3. `reasons` 列表非空:当 `requires_human=True` 时至少 1 个阈值违例
4. `risk_profile` 完整序列化:`RiskProfile.model_dump(mode="json")` 直接 dump,字段与 `quantcode/schemas/risk_profile.py` 一一对应
5. `decision` 字段:恢复后 `parse_resume_decision(Command(resume={"decision": "approve"}))` 返回 `"approve"`;若 `Command(resume={"decision": "reject"})` 返回 `"reject"`;若 `Command(resume=None)` 保持 `None`(测试场景)

---

## 7. 杨欣琳侧需要做的事(分工)

收到此契约文档后:
1. **确认 §5 决策**:pr_number 从 `input_data` 拿,同意 / 不同意?
2. **确认 §6 实现侧保证**:有遗漏的需求(如 audit log、marker 格式)请提出
3. **同步产物**:回复"OK"或具体修改意见,我把反馈落到 `quantcode/runner/agent_nodes.py:make_route_gate_node` 的实现里
4. **测试用例**:Day 4 §3 验收用例 `test_high_risk_approve_resumes_and_writes_comment`(已在 `tests/test_risk_flow.py:169-204`)+ 我新加的 `tests/test_agent_runner_gate.py:test_route_gate_approve_resumes_and_runs_subsequent_tools` 会覆盖

---

## 8. 不在 Day 4 范围(留 Day 5 / Week 2)

- `HumanGateInterruptPayload` 加 pr_number / repo 字段(若 §5 决策不通过,需要扩展 schema)
- audit log 持久化(目前 dedupe 用 `pr_number + gate_id marker`,不存结构化 audit)
- multi-gate 编排(同一 task 多个 gate 排队)
- token 管理(目前 GITHUB_TOKEN 走 env 注入,文档化留 Day 4 §3 task)

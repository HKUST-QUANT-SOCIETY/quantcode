# SPEC — governance 域：风控门禁与 evidence chain（F-03 + P-06）

> §0 元信息：status=draft · owner=R4 风控合规代理 · source=F-03 + P-06（ROADMAP G2-A1/A2/B1）· target=Q1 G2-A1 / Q3 G2-B1
> §2.1 为既有代码契约梳理（本 spec 只锁定不修改）；§2.2 为 [新增] 契约草案。

## §1 范围与非目标

**范围**：① HumanGate 风控链路契约化锁定；② [新增] evidence chain 报告（run 指纹链 → 审计留痕 → 决策署名）。
**非目标**：不做实时风控（G1-L3，前置 L2 连续一季度零降级）、先不做 PDF 渲染器选型（先 JSON 契约）、不做 Secret 管理（G4-C1 另立）。

## §2 契约

### 2.1 现状契约（全部真实路径）

- `schemas/human_gate.py`：`HumanGate(gate_id, status∈{pending,approved,rejected,escalated}, decision: HumanGateDecision|None)`、`HumanGateDecision(action∈{approve,reject}, decided_by, reason)`、`HumanGateInterruptPayload`；均 `extra="forbid"`。JSON 版 `schemas/human-gate.schema.json`（扩展态枚举 timed_out/cancelled；task_id `^T\d+(\.\d+){0,4}$`；session_id `^S[0-9a-f]{16}$`）。
- `schemas/risk_profile.py`：`RiskThresholds` 单一真源——max_drawdown=0.15、position_limit_usage=0.8、correlation_limit=0.6、tail_risk_var_99=0.05（与 `tools/risk/statistics_stub.py`、`runner/routing/rlhf_logger.py` 同源）；`RiskProfile.evaluate_verdict()` 越界即 needs_human。
- `runner/human_gate.py`：`should_interrupt`（approved/rejected 不可再中断）、`make_gate_id`、`normalize_external_decision` fail-closed（未知决策→reject）。
- 留痕现状：`runner/routing/rlhf_logger.py` → `.quantcode/rlhf_data.jsonl`（追加写）；`runner/metrics.py` → `.quantcode/metrics.jsonl`(best-effort)；`ComposeTaskEvent`（`schemas/compose_task.py`）append-only 事件流。

### 2.2 evidence chain 报告契约 [新增 schemas/evidence_chain.py + schemas/evidence-chain.schema.json + runner/evidence.py]

指纹链（append-only 逐环哈希链）：
`run_id`（=metrics.jsonl thread 记录）→ `AuditEvent[]`（每环 `seq:int`、`kind∈{tool_call,tool_result,risk_gate,human_gate,artifact,output_data}`、`at:datetime`、`payload_hash=sha256(canonical_json(payload))`、`prev_hash`、`entry_hash=sha256(seq|kind|at|payload_hash|prev_hash)`）→ `ArtifactRef[]`（path/sha256/bytes）→ `DecisionRecord`（gate_id/action/decided_by 署名/decided_at/reason，须与 HumanGateDecision 一致）→ 报告级 `report_hash`。
`EvidenceReport(report_id, run_id, generated_at, chain, artifacts, decision, report_hash)`，`extra="forbid"`。
不变量：① 首环 `prev_hash=None` 后逐环衔接；② 重放事件流重算 entry_hash 逐环相等；③ DecisionRecord 存在 ⇔ 链含 human_gate 环；④ 任一环篡改 → 链校验失败。

## §3 数据流

```
AgentRunner run/stream/resume 完成钩子（runner/agent_engine.py）
  → [新增] runner/evidence.py 逐环 append AuditEvent（.quantcode/evidence/<run_id>.jsonl）
risk-gate 越界 → HumanGate interrupt → lens UI 审批 → resume
  → DecisionRecord（可选：仅当链含 approved/rejected 判决的 human_gate 环；decided_by 署名，与 rlhf_data.jsonl 人类决策同源）终结指纹链
  → [新增] runner/evidence.py::build_report(run_id) 校验链 → EvidenceReport JSON → artifacts/evidence/
  → lens UI: panels.tsx HumanGate 面板 + [新增] Evidence 面板（report_hash + 逐环链）
```

## §4 机器可验证断言

- G2-A1: 篡改环内 payload_hash 后 verify_chain() 抛 EvidenceChainError（[新增测试] tests/test_evidence_chain.py::test_tampered_entry_fails_verification）
- G2-A2: 链尾插入未登记事件 → 末环 entry_hash 不匹配 → verify 失败（test_appended_unknown_entry_fails）
- G2-A3: 同一事件流两次 build_report 的 report_hash 相等且与审计日志重算链一致（test_report_replay_deterministic）
- G2-A3b: 交换两环顺序后 verify 失败（test_reordered_entries_fail）
- G2-A4: EvidenceReport 仅当链含 approved/rejected human_gate 环时携带 DecisionRecord，否则构造即 ValidationError（test_decision_requires_human_gate_entry）
- G2-A5: DecisionRecord 与 HumanGateDecision 逐字段一致，不等抛 ValidationError（test_decision_matches_human_gate_payload）
- G2-A6: ArtifactRef.sha256 与磁盘文件重算一致；替换文件后 verify 失败（test_artifact_sha256_binding）
- G2-A7: 现状回归护栏——HumanGate 契约防漂移：`should_interrupt` 对 approved/rejected 恒 False；`normalize_external_decision("garbage")=="reject"`（既有 tests/test_human_gate.py 覆盖 + [新增测试] test_existing_human_gate_contract_unchanged 快照断言）

## §5 开放问题

- 审计环存储选型（JSONL 哈希链 vs SQLite）：先 JSONL（owner: R4，截止 Q1 末）。
- decided_by 密码学签名（GPG/内网 CA）推迟至 G2-C1 WORM 讨论（owner: R4，截止 Q3）。

## §6 verdict

| 断言 | 测试 | 结果 | 日期 |
|---|---|---|---|
| G2-A1..A6（新增段） | tests/test_evidence_chain.py | blocked | — |
| G2-A7 新增快照断言部分 | tests/test_evidence_chain.py::test_existing_human_gate_contract_unchanged | blocked | — |
| G2-A7 现状段 | tests/test_human_gate.py · tests/test_risk_profile.py | pass（702 个测试既有覆盖） | 2026-09-01 |
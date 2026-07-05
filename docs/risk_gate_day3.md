# risk:gate Day 3 说明

> risk 组 · Day 3 交付：`risk:gate` LangGraph flow + HumanGate 人审断点

## 1. risk:gate 做什么

`risk:gate` 是 risk 组的 Compose flow，在 model 组提交 PR / ModelSpec 之后运行：

1. 读取模型元数据（ModelSpec）
2. 计算风控指标（max_drawdown、VaR 等）
3. 生成 `RiskProfile`
4. 判断是否需要人工审批（HumanGate）
5. 写 PR comment artifact，并跑 acceptance 验收

**输出**（`output_data`）包含：`risk_profile`、`gate_result`、`human_decision`、`pr_comment`、`acceptance`、`status`（`completed` / `rejected`）。

代码入口：`flows/risk_gate.py`，注册名 `("risk", "risk:gate")`。

---

## 2. 五个 Node

| Node | 作用 |
|------|------|
| `read_model_spec` | 从 `input_data["model_spec"]` 或 blackboard 读 ModelSpec，校验 schema |
| `calc_risk_metrics` | 调用 `tools/risk/statistics_stub`（Day3 stub，后续换正式统计库） |
| `generate_risk_profile` | 指标 → `RiskProfile`，写 `artifacts/risk/*-profile.json` |
| `check_human_gate` | 对比 `RiskThresholds`；超阈值则 `interrupt()` 暂停，等人审 |
| `write_pr_comment` | 写 comment artifact 到 `artifacts/risk/pr-comments/`（不调 GitHub API） |

另有 **`finalize_output`**（汇总节点）：跑 `run_acceptance("risk-gate", ...)`，组装最终 `output_data`。

**人审路径**还会经过 `human_review`（approve 后的占位节点）。

---

## 3. 两个场景怎么跑

### normal — 风险未超阈值

```bash
.venv/bin/python scripts/demo_risk_flow.py   # 场景 1
# 或
.venv/bin/python -m pytest tests/test_risk_flow.py -k normal
```

`input_data["scenario"] = "normal"` → flow 一次跑完 → `status=completed`，`acceptance=pass`，直接写 comment。

### high_risk — 超阈值，触发人审

```bash
.venv/bin/python scripts/demo_risk_flow.py   # 场景 2
# 或
.venv/bin/python -m pytest tests/test_risk_flow.py -k high_risk
```

`input_data["scenario"] = "high_risk"` → VaR / max_drawdown 等超阈值 → flow 在 `check_human_gate` **暂停** → 人审 approve 后 resume → 写 comment（acceptance 仍为 fail，但 flow 完成）。

---

## 4. HumanGate interrupt / resume

**暂停**：`check_human_gate` 内调用 LangGraph `interrupt()`，payload 含：

- `gate_id`
- `message`: `"⏸️ 等待人工审批"`
- `risk_profile`
- `reasons`（超阈值项列表）

Graph 在此 checkpoint 停住，`snapshot.next == ("check_human_gate",)`。

**恢复**：

```python
from flows.risk_gate import resume_risk_gate

resume_risk_gate(app, thread_id, "approve")   # 继续写 comment
resume_risk_gate(app, thread_id, "reject")    # 不写 comment，status=rejected
```

底层是 `Command(resume={"decision": "approve"|"reject"})`。

**路由**：

- normal → `write_pr_comment` → `finalize_output`
- approve → `human_review` → `write_pr_comment` → `finalize_output`
- reject → `finalize_output`（跳过 comment）

---

## 5. write_pr_comment 为什么要 dedupe

同一 PR、同一 commit、同一 RiskProfile 可能被 CI / 重试 **触发多次**（例如 workflow 重跑、网络重试）。

`write_pr_comment` 用 `@dedupe_within`（`tools/utils/dedupe.py`）：

- key：`pr_comment:{pr_url}:{head_sha}:{hash(profile)}`
- 窗口内重复调用 → 返回缓存结果，**只写一次 artifact**

避免 PR 上出现重复 risk comment，也避免重复副作用。Day1 `pipelines/risk_gate/comment_hello.py` 已有同类设计。

---

## 6. 当前 TODO（未接）

| 项 | 状态 |
|----|------|
| OpenCode UI 人审面板 | 未接 — 目前 CLI / 测试里 `resume_risk_gate(..., "approve")` 模拟 |
| GitHub API 真写 PR comment | 未接 — 只写本地 artifact；可参考 `pipelines/risk_gate/comment_hello.py` |
| MCP tool 暴露 | 未接 |
| Blackboard PROJECT scope 跨组读 | Day3 stub：`input_data["model_spec"]`；等陈镇鸿 `runner/blackboard.py` 正式接入 |
| 俞高磊正式统计库 | 未接 — 现用 `tools/risk/statistics_stub.py` |
| model→risk 跨组 chain | 未接 — 等 `flows/model_pr_submit.py` + 尹一帆 chain_flows |

---

## 快速命令

```bash
# Demo（汇报用）
.venv/bin/python scripts/demo_risk_flow.py

# 测试
.venv/bin/python -m pytest tests/test_risk_flow.py tests/test_risk_tools.py tests/test_human_gate.py -q
```

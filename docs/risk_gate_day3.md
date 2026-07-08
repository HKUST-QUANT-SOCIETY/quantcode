# risk:gate Day 3/4 说明

> risk 组 · Day 3 交付：`risk:gate` LangGraph flow + HumanGate 人审断点
> Day 4（`origin/yifan-day4`）：AgentRunner `route_gate` + risk ReAct 路径已接通

## 1. risk:gate 做什么

`risk:gate` 是 risk 组的风控入口，在 model 组提交 PR / ModelSpec 之后运行：

1. 读取模型元数据（ModelSpec）
2. 计算风控指标（max_drawdown、VaR 等）
3. 生成 `RiskProfile`
4. 判断是否需要人工审批（HumanGate）
5. 写 PR comment（本地 artifact + 可选 GitHub），并跑 acceptance 验收

**两条入口**：

| 路径 | 入口 | 适用 |
|------|------|------|
| **Scripted** | `runner/risk_agent.build_risk_agent()` | CI / GitHub Actions 确定性 pipeline |
| **ReAct** | `AgentRunner(group="risk", gate_tools=["check_gate"])` 或 `run_risk_agent_react()` | OpenCode / LLM 自主调 tool |

`flows/risk_gate.py` 保留 legacy compatibility shim。

---

## 2. ReAct 路径（Day 4）

```
AgentRunner(group="risk", gate_tools=["check_gate"], checkpoint_db=...)
  llm → tool → post_tool_check → gate(route_gate_node) → llm ...
```

LLM 按 SKILL.md 顺序调用 allowlist tools：

`read_blackboard` → `calc_risk` → `generate_risk_profile` → `check_gate` →（HumanGate）→ `write_pr_comment`

- `check_gate` 返回 `requires_human=true` 时，`route_gate_node` 调 `interrupt(build_interrupt_payload(...))`
- 恢复：`runner.resume(thread_id, "approve"|"reject")`（底层 `Command(resume={"decision": ...})`）
- `approve` 后可调 `write_pr_comment`；`reject` 时 tool 层跳过写 comment（`gate_decision=reject`）
- **必须**传 `checkpoint_db`（`gate_tools` 依赖 SqliteSaver）

契约详见 `docs/Day4/risk_human_gate_payload_contract.md`。

---

## 3. Scripted graph（CI）

| Node | 作用 |
|------|------|
| `run_tool_pipeline` | 依次调用 read_blackboard / calc_risk / generate_risk_profile / gate_check |
| `human_review` | HumanGate approve 占位 |
| `write_pr_comment` | 写 artifact；可选 GitHub（`post_to_github` / env） |
| `finalize_output` | acceptance + 组装 `output_data` |

---

## 4. 两个场景

### normal — 未超阈值

`scenario=normal` → 不 interrupt → 直接 `write_pr_comment`。

### high_risk — 超阈值

`scenario=high_risk` → `check_gate` / `check_human_gate` interrupt → approve/resume → 写 comment；reject 跳过 comment。

---

## 5. GitHub comment 与 dedupe

- 发帖开关：`post_to_github=True` 或 `QUANTCODE_POST_RISK_COMMENT=1`
- 凭据：`GITHUB_TOKEN` + `GITHUB_REPOSITORY`（或 tool/input_data 显式传）
- 两层 dedupe：SQLite `@dedupe_within` + GitHub HTML marker

### Token（勿入库）

| 变量 | 说明 |
|------|------|
| `GITHUB_TOKEN` | PAT 或 Actions `secrets.GITHUB_TOKEN` |
| `GITHUB_REPOSITORY` | `owner/repo` |
| `QUANTCODE_POST_RISK_COMMENT` | `1` 开启发帖 |

本地示例：

```bash
export GITHUB_TOKEN="$(gh auth token)"
export GITHUB_REPOSITORY="owner/repo"
export QUANTCODE_POST_RISK_COMMENT=1
.venv/bin/python scripts/run_risk_gate_tool.py --scenario normal --pr-number 42 --head-sha "$(git rev-parse HEAD)"
```

ReAct 恢复示例：

```python
from runner.agent_engine import AgentRunner

runner = AgentRunner("risk", model=llm, gate_tools=["check_gate"], checkpoint_db="cp.db")
paused = runner.run("处理 PR #42", skill_name="risk-gate", thread_id="t-1")
if paused.get("__interrupt__"):
    final = runner.resume("t-1", "approve", skill_name="risk-gate")
```

---

## 快速命令

```bash
# Scripted demo
.venv/bin/python scripts/demo_risk_flow.py

# 测试
.venv/bin/python -m pytest \
  tests/test_risk_agent_runner.py \
  tests/test_risk_github_e2e.py \
  tests/test_risk_react_ready.py \
  tests/test_risk_agent.py \
  tests/test_risk_tools.py \
  tests/test_risk_dedupe.py \
  tests/test_human_gate.py -q
```

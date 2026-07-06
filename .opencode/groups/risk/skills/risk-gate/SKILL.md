---
name: risk-gate
description: 接收模型组 PR，生成 RiskProfile，必要时触发 HumanGate，并向 PR 写入风控评论
group: risk
owner: 杨欣琳
pattern: Pattern 5 (Human-in-the-Loop Gate) + ReAct tool loop
---

# Risk Gate Skill

## 何时使用

当模型组提交 PR，需要风控组判断策略风险是否可接受时调用本 skill。

典型入口：

- GitHub Actions 在 PR 创建或更新时触发
- 模型组通过 `model:pr-submit` handoff 给 risk 组
- OpenCode MCP `quantcode` server（`QUANTCODE_GROUP=risk`）

## ReAct 工作流

你是 risk 组 agent。按以下顺序调用 **allowlist 内的 tools**（可根据上下文调整，但不要跳过必要步骤）：

1. **`read_blackboard`** — 从 Blackboard PROJECT scope 读取 `model_spec`（生产路径）。
   - 传入 `input_data` 含 `project_id` / `blackboard_db_path` / `blackboard_key`。
   - 仅测试/demo 时可直接传 `input_data.model_spec`（非生产路径）。

2. **`calc_risk`** — 对 model_spec 计算风控指标（stub：`scenario=normal|high_risk`）。

3. **`generate_risk_profile`** — 生成并校验 `RiskProfile`。

4. **`check_gate`** — 对照 `RiskThresholds` 判断是否需人工审批。
   - 若 `requires_human=false` → 跳到步骤 6。
   - 若 `requires_human=true` → 触发 **HumanGate interrupt**，等待 `approve` / `reject`。

5. **HumanGate** — 超阈值时暂停，展示 `risk_profile` 与 `reasons`。
   - `approve` → 继续写 PR comment。
   - `reject` → **不要** 调用 `write_pr_comment`。

6. **`write_pr_comment`** — 写入 `QuantCode Risk Gate Report`（本地 artifact + 可选 GitHub）。
   - 同一 PR + 同一 `head_sha` + 同一 profile **自动 dedupe**，不重复发帖。

## 输入

必需：

- `pr_url` — 模型组 PR 链接
- `head_sha` — PR 当前 commit SHA（dedupe key）
- `pr_number` — PR 编号

可选：

- `project_id` / `blackboard_db_path` / `blackboard_key` — BlackboardService 读取参数
- `model_spec` — 仅 test/demo fallback
- `scenario` — `normal`（默认）或 `high_risk`（触发 HumanGate 测试）

## 阈值

唯一来源：`schemas.risk_profile.RiskThresholds`（max_drawdown 15%、position 80%、VaR99 5%、correlation 0.6）。

## 运行路径

- **CI / Actions**：`scripts/run_risk_gate_tool.py` → `runner.risk_agent`（确定性 pipeline + HumanGate interrupt/resume）
- **OpenCode ReAct**：`runner.agent_engine.AgentRunner(group="risk")` + 本 SKILL.md + allowlist tools（#15 已合入）
- **MCP**：`quantcode.mcp_server` 同时注册 model/risk tools；设 `QUANTCODE_GROUP=risk` 过滤

## 依赖

- **BlackboardService**（`runner/blackboard.py`，#15 已合入）：`read_blackboard` 生产路径读取 PROJECT scope
- **test/demo fallback**：`input_data.model_spec` 仅用于单测，非生产路径

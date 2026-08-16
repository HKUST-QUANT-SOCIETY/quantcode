# risk:gate Day 3/4 说明

> risk 组 · Day 3 交付：`risk:gate` LangGraph flow + HumanGate 人审断点
> Day 4 状态：risk tool / GitHub comment / dedupe 已就绪；完整 ReAct 迁移等待
> `AgentRunner` 接入 `route_gate` / `permission=ask` / interrupt-resume。

## 1. risk:gate 做什么

`risk:gate` 是 risk 组的风控入口，在 model 组提交 PR / ModelSpec 之后运行：

1. 读取模型元数据（ModelSpec）
2. 计算风控指标（max_drawdown、VaR 等）
3. 生成 `RiskProfile`
4. 判断是否需要人工审批（HumanGate）
5. 写 PR comment（本地 artifact + 可选 GitHub），并跑 acceptance 验收

**输出**（`output_data`）包含：`risk_profile`、`gate_result`、`human_decision`、`pr_comment`、`acceptance`、`status`（`completed` / `rejected`）。

当前确定性入口：`runner/risk_agent.py`，注册名 `("risk", "risk:gate")`。
`flows/risk_gate.py` 仅保留 legacy compatibility shim。

ReAct 目标入口：`AgentRunner(group="risk", skill_name="risk-gate")`。该路径需要
共享引擎先补 HumanGate gate 能力，否则 `check_gate` 只能返回
`requires_human=true`，不能可靠暂停和 resume。

---

## 2. 当前 scripted graph

Day 3 为了满足 CI / GitHub Actions 的确定性，当前 risk 主入口仍是固定图：

| Node | 作用 |
|------|------|
| `run_tool_pipeline` | 依次调用 `read_blackboard` / `calc_risk` / `generate_risk_profile` / `gate_check` |
| `human_review` | HumanGate approve 后的占位节点 |
| `write_pr_comment` | 写 comment artifact；可选真实 GitHub PR comment |
| `finalize_output` | 跑 `run_acceptance("risk-gate", ...)`，组装最终 `output_data` |

这不是架构终态。Day 4 目标是把编排权交给 `AgentRunner`，由 risk
SKILL.md + tool allowlist 引导 ReAct 自主调用 tool；scripted graph 保留为
CI wrapper 或兼容路径。

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

## 5. GitHub comment 与 dedupe

同一 PR、同一 commit、同一 RiskProfile 可能被 CI / 重试 **触发多次**（例如 workflow 重跑、网络重试）。

`write_pr_comment` 用 `@dedupe_within`（`tools/utils/dedupe.py`）：

- key：`pr_comment:{pr_url}:{head_sha}:{hash(profile)}`
- 窗口内重复调用 → 返回缓存结果，**只写一次 artifact**

真实 GitHub 写入已接入 `tools/github_comments.py`。默认只写本地 artifact；
满足以下条件时会发正式 PR comment：

- `post_to_github=True`，或环境变量 `QUANTCODE_POST_RISK_COMMENT=1`
- 提供 `github_repo` / `github_token`，或设置环境变量
  `GITHUB_REPOSITORY` / `GITHUB_TOKEN`

同一 `head_sha` + 同一 `RiskProfile` 的 GitHub comment 使用 HTML marker
二次去重；如果 PR 上已存在 marker，不再创建新评论。

---

## 6. Day 4 迁移边界

risk 侧已经就绪：

- 5 个 risk tools 已注册进 registry，并由 `.opencode/groups/risk/tool_allowlist.yaml` 过滤
- `read_blackboard` 优先读 `BlackboardService` PROJECT scope
- `check_gate` 输出稳定的 `requires_human` / `reasons`
- HumanGate payload 统一走 `runner.human_gate.build_interrupt_payload`
- `write_pr_comment` 支持 artifact + 真实 GitHub comment + marker dedupe

仍依赖共享引擎：

- `AgentRunner` 需要补 `route_gate` / `permission=ask` / `interrupt()`
- resume 后要把 approve/reject 写回 state，供后续路由决定是否调用
  `write_pr_comment`
- 没有这层能力时，risk ReAct smoke test 最多只能跑到
  `check_gate.requires_human=true`，不能算完整人审闭环

---

## 7. GitHub Token 与环境变量

**不要把 token 写入仓库。** 本地用 shell 环境变量或 `.env`（确保已在 `.gitignore`），CI 用 GitHub Actions secrets。

| 变量 | 必填场景 | 说明 |
|------|----------|------|
| `GITHUB_TOKEN` | 发正式 PR comment | PAT 或 Actions 内置 `secrets.GITHUB_TOKEN` |
| `GITHUB_REPOSITORY` | 发正式 PR comment | `owner/repo`，如 `HKUST-QUANT-SOCIETY/quantcode` |
| `QUANTCODE_POST_RISK_COMMENT` | 可选开关 | 设为 `1` / `true` / `yes` / `on` 时，即使未传 `post_to_github=True` 也会发帖 |
| `GITHUB_API_URL` | 可选 | 默认 `https://api.github.com`；GitHub Enterprise 可覆盖 |

也可在 tool / flow `input_data` 里显式传 `github_token`、`github_repo`、`post_to_github=True`（测试与 OpenCode 桥接常用）。

### 本地运行

```bash
# 仅写本地 artifact（默认）
.venv/bin/python scripts/run_risk_gate_tool.py --scenario normal

# 向真实 PR 发帖（需有 issues:write / pull-requests:write 权限）
export GITHUB_TOKEN="$(gh auth token)"          # 或你自己的 PAT，勿提交
export GITHUB_REPOSITORY="owner/repo"
export QUANTCODE_POST_RISK_COMMENT=1
.venv/bin/python scripts/run_risk_gate_tool.py \
  --scenario normal \
  --pr-number 42 \
  --head-sha "$(git rev-parse HEAD)" \
  --pr-url "https://github.com/owner/repo/pull/42"
```

高风险人审（interrupt → resume）：

```bash
# 第一次：打印 interrupt payload，status=waiting_for_human
.venv/bin/python scripts/run_risk_gate_tool.py --scenario high_risk --decision pending

# approve 后继续写 comment
.venv/bin/python scripts/run_risk_gate_tool.py --scenario high_risk --decision approve

# reject：不写 comment，status=rejected
.venv/bin/python scripts/run_risk_gate_tool.py --scenario high_risk --decision reject
```

### GitHub Actions

旧版 `.github/workflows/risk-gate.yml` 曾直接运行该业务场景，并连续执行两次验证 marker dedupe。该 workflow 已被通用 `.github/workflows/review.yml` 取代。当前 PR Code Review 不执行 Quant Code 业务包；Risk Compose 写评论的 dedupe 应在业务测试或独立业务 workflow 中验证。

### 去重两层

1. **进程内 / SQLite**（`@dedupe_within`）：同 `pr_url` + `head_sha` + `RiskProfile` hash，短窗口内只执行一次副作用。
2. **GitHub HTML marker**：评论末尾含 `<!-- quantcode:risk-gate:profile:{head_sha}:{profile_hash} -->`；发帖前先 `GET /issues/{n}/comments` 查重。

---

## 快速命令

```bash
# Demo（汇报用）
.venv/bin/python scripts/demo_risk_flow.py

# 测试
.venv/bin/python -m pytest \
  tests/test_risk_github_e2e.py \
  tests/test_risk_react_ready.py \
  tests/test_risk_agent.py \
  tests/test_risk_tools.py \
  tests/test_risk_dedupe.py \
  tests/test_human_gate.py -q
```

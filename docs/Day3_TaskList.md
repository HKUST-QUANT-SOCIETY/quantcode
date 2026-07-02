# Day 3 任务清单

> **日期**：开发第三日
> **总体目标**：跑通第一个**跨组协作流程** model→risk，验证 Blackboard PROJECT scope 数据传递 + HumanGate 人审断点触发。
> **核心理念**：Day 2 证明了单组闭环，Day 3 要证明**跨组 handoff** 可行——这是"千组千流"协作的第一块基石。
> **里程碑**：Cross-Group Handoff

---

## 0. Day 3 架构目标

### 从"单组闭环"到"跨组协作"

Day 2 我们跑通了 factor:autoeval（factor 组内闭环）。Day 3 要打通两个组之间的数据流：

```
陈镇鸿的 model 组                    杨欣琳的 risk 组
┌─────────────────────┐            ┌──────────────────────┐
│ model:pr-submit     │            │ risk:gate            │
│                     │  Blackboard│                      │
│ read_pr_diff        │  PROJECT   │ read_model_spec      │
│ extract_metadata    │  scope     │ calc_risk_metrics    │
│ generate_ModelSpec  │──写入──────→│ generate_RiskProfile │
│ write_blackboard    │  model.pr. │ check_human_gate     │
│ trigger_risk_gate   │  {pr_num}  │ write_pr_comment     │
└─────────────────────┘            └──────────────────────┘
         │                                    │
         │ 直接 risk_app.invoke()             │ VaR超阈值
         └────────────────────────────────────┘
                                              ↓
                                    ┌──────────────────┐
                                    │ HumanGate        │
                                    │ interrupt_before │
                                    │ 暂停 → 人审 →恢复 │
                                    └──────────────────┘
```

### 三个关键验证点

1. **Blackboard PROJECT scope 数据传递**：model 写，risk 读，跨组可见
2. **跨 graph 触发**：model flow 结束自动 invoke risk flow（不用 Event Bus）
3. **HumanGate 断点**：VaR 超阈值 → interrupt → checkpoint → 人审 → resume

---

## 1. 全员 Standup（15 分钟）

- Day 2 回顾：4 个 PR 合并（factor:autoeval + Memory FTS5 + dedupe + checkpoint resume）
- Day 3 目标确认：model→risk 跨组跑通，真实 PR 上有 risk comment
- **依赖关系对齐**（关键）：
  - 杨欣琳的 risk-gate **依赖** 俞高磊的风控统计函数
  - 陈镇鸿的 model flow **依赖** 尹一帆的跨 graph 触发机制
  - 三条链路必须在**下午 3 点前**完成各自单测，才能做集成

---

## 2. 陈镇鸿 · model:pr-submit Flow（全天，重头戏）

> **工程量提示**：Day 2 你的 dedupe 测试是 167 行。Day 3 这是一条**完整的 5-node flow + BlackboardService + 集成测试**，预计 600-800 行。这是 Day 3 最核心的交付之一。

### 2.1 上午：BlackboardService 实现（PROJECT scope 数据层）

**背景**：Day 2 的 `compose_executor` 只有 in-memory state，没有跨 flow 的持久化 Blackboard。Day 3 需要真正的 Blackboard 让 model 写、risk 读。

| 任务 | 说明 | 验收 |
|---|---|---|
| 新建 `runner/blackboard.py` | 实现 5-scope Blackboard（复用 Memory FTS5 的 scope 模型）：<br>- `write(scope, scope_id, key, value)` <br>- `read(scope, scope_id, key)` <br>- `list_keys(scope, scope_id)` <br>- PROJECT scope：所有组可读，写入记录 `written_by_group` | 单测：model 组写 PROJECT，risk 组能读到 |
| 复用 `schemas/compose_task.py` 的 `BlackboardEntry` | Day 1 已定义 `BlackboardEntry`、`BlackboardScope`、`WritePolicy`，直接用，不要重复造 | import 成功，字段对齐 |
| 持久化到 SQLite | Blackboard entries 存 `.quantcode/blackboard.db`，重启不丢 | kill 进程后 read 仍能拿到之前写的 |
| **写入权限校验** | GROUP scope 只有 owner 能写；PROJECT scope 记录 `written_by_group` 但所有组可写（GROUP_APPEND policy） | 单测：factor 组不能写 model 组的 GROUP entry |

### 2.2 下午：model:pr-submit 5-node flow

| Node | 输入 | 输出 | 说明 |
|---|---|---|---|
| `read_pr_diff` | pr_number | diff 文本 | 用 `gh pr diff` 或读 `tests/fixtures/sample_model_pr.diff` |
| `extract_model_metadata` | diff | dict（模型类型/超参/训练区间） | 正则或规则提取，不用 LLM |
| `generate_model_spec` | metadata | `ModelSpec`（Day 1 schema） | 构造并校验 ModelSpec，含 `as_of_date` 时点约束 |
| `write_to_blackboard` | ModelSpec | blackboard key | 写 PROJECT scope，key=`model.pr.{pr_number}` |
| `trigger_risk_gate` | blackboard key | risk flow result | 调用尹一帆的跨 graph 触发（`risk_app.invoke`） |

**验收标准**：
- `tests/test_model_flow.py`：至少 8 个测试
  - 每个 node 单测（4 个）
  - ModelSpec 时点校验（training_range.end <= as_of_date）
  - Blackboard 写入验证
  - 完整 flow 集成测试（app.invoke）
  - checkpoint 恢复测试（用 Lead 的 resume API）
- Demo：`python scripts/demo_model_flow.py` 从 sample PR 生成 ModelSpec 并写 Blackboard

### 2.3 fixture 准备

- 造一个 `tests/fixtures/sample_model_pr.diff`（模拟一个提交 LSTM 模型的 PR）
- 内含：模型类型、训练区间、超参数、预期 Sharpe

---

## 3. 杨欣琳 · risk:gate Flow + HumanGate 集成（全天，重头戏）

> **工程量提示**：Day 2 你的 HumanGate 是 449 行。Day 3 要把它**接进真实的 LangGraph flow**，还要修复 Day 2 review 提的 eval() 问题，预计 500-700 行。

### 3.1 上午 Part A：修复 PR #12 的 eval() 安全问题（P0）

**背景**：Day 2 Lead review 发现 `runner/human_gate.py:97` 用了 `eval()`，有安全风险。

| 任务 | 说明 | 验收 |
|---|---|---|
| 移除 `_build_trigger_expression` + `eval` | 改为 `match/case` 直接判断（Lead review 已给出示例代码） | 无 eval，测试仍全过 |
| 补充 timeout 检查 | `should_interrupt` 增加：pending 超过 `timeout_minutes` → 返回 escalate 信号 | 单测：超时场景 |
| rebase 到最新 main | 合入 Lead 的 checkpoint resume API（PR #13） | CI 通过 |

### 3.2 上午 Part B：risk:gate 5-node flow

| Node | 输入 | 输出 | 说明 |
|---|---|---|---|
| `read_model_spec` | blackboard key | ModelSpec | 从 PROJECT scope 读 model 组写的数据 |
| `calc_risk_metrics` | ModelSpec + returns | dict（max_dd/VaR/ES） | 调用俞高磊的统计函数 |
| `generate_risk_profile` | metrics | `RiskProfile` schema | 需 Day 3 新建 RiskProfile schema |
| `check_human_gate` | RiskProfile | interrupt or pass | VaR 超阈值 → 构造 HumanGate → interrupt |
| `write_pr_comment` | RiskProfile | comment id | 用 dedupe，写 risk.json 到 PR |

### 3.3 下午：HumanGate 与 LangGraph interrupt 集成

**这是 Day 3 最难的部分**——把 HumanGate 接进 LangGraph 的 `interrupt_before`。

| 任务 | 说明 | 验收 |
|---|---|---|
| 新建 `schemas/risk_profile.py` | `RiskProfile` Pydantic 模型：max_drawdown/var_99/es_99/verdict/breached_thresholds | 单测覆盖 |
| workflow 配置 interrupt | `app.compile(interrupt_before=["human_review"])` | VaR 超阈值时 flow 在此暂停 |
| 实现 resume 后继续 | 人审 approve（改 HumanGate.status）→ `resume=True` 恢复 → workflow 继续到 write_pr_comment | 端到端测试：暂停→approve→恢复→完成 |
| mock 通知 | HumanGate 触发时打 log "⏸️ 等待人工审批 gate_id=..." | log 可见 |

**验收标准**：
- `tests/test_risk_flow.py`：至少 10 个测试
  - eval 修复后的 should_interrupt（3 个：超阈值/未超/已决议）
  - RiskProfile schema 校验（2 个）
  - 每个 node 单测（3 个）
  - **HumanGate 暂停→恢复端到端**（2 个）：这是核心
- Demo：`python scripts/demo_risk_flow.py` 展示 VaR 超阈值 → 暂停 → 模拟 approve → 恢复 → PR comment

---

## 4. 俞高磊 · 风控统计函数库 + factor 深化（全天）

> **新人背景**：俞高磊（东南大学强基计划数学学院），机器学习/深度学习经验，数学竞赛全国一等奖。熟悉PyTorch、优化算法、数值计算。Day 3 主攻风控统计函数库（为杨欣琳的 risk-gate 提供依赖）+ factor 量化分析。

> **工程量提示**：上午风控统计库是杨欣琳的阻塞依赖（优先级最高），预计 250 行代码 + 15 个测试。下午 factor 分层回测预计 200 行 + 8 个测试。总计 ~450 行。

### 4.1 上午：风控统计函数库（杨欣琳的依赖，优先级最高）

**背景**：Day 1 的 `docs/risk_metrics_formula_checklist.md` 定义了公式，Day 3 要实现成可调用的库。

| 函数 | 签名 | 说明 |
|---|---|---|
| `calc_max_drawdown` | `(returns: list[float]) -> float` | 最大回撤，返回正数（如 0.15 表示 -15%） |
| `calc_var_99` | `(returns: list[float], horizon: int = 1) -> float` | 99% 历史 VaR，支持 horizon 缩放（√t 规则） |
| `calc_expected_shortfall_99` | `(returns: list[float]) -> float` | 99% ES（CVaR），尾部平均损失 |
| `calc_sharpe` | `(returns: list[float], rf: float = 0.0, periods: int = 252) -> float` | 年化 Sharpe |
| `calc_sortino` | `(returns: list[float], rf: float = 0.0) -> float` | 只惩罚下行波动 |
| `calc_calmar` | `(returns: list[float]) -> float` | 年化收益 / 最大回撤 |

**关键要求**（不能只写 happy path）：
- 边界处理：空列表、单元素、全零、全负
- 数值稳定性：大数组不溢出
- 与 `numpy` 结果交叉验证（如果装了 numpy）

**验收标准**：
- `runner/risk_stats.py`（~250 行）
- `tests/test_risk_stats.py`：至少 15 个测试
  - 每个函数 2-3 个正常 case
  - 每个函数 1 个边界 case
  - VaR horizon 缩放验证
  - 与已知答案对拍（造几组手算过的 returns）

### 4.2 下午：factor:autoeval 分层回测 + 衰减分析

在 Day 2 的 factor flow 基础上增加真实计算（替换部分 mock）：

| 任务 | 说明 | 验收 |
|---|---|---|
| 实现 `LayeredBacktest` 计算 | 分 5/10 层，计算各层收益、多空对冲收益、单调性 | 用 sample_factor 跑出真实分层结果 |
| 实现 `DecayMetrics` 计算 | IC 在 1/3/5/10/20 日的衰减曲线 | 衰减曲线单调递减 |
| 接入 factor flow | 替换 `_mock_autoeval_result` 的对应字段为真实计算 | factor flow 产出真实 LayeredBacktest |

**验收标准**：
- `runner/factor_stats.py`（~200 行）
- `tests/test_factor_stats.py`：至少 8 个测试

---

## 5. 尹一帆 · 跨 Graph 触发机制 + Blackboard 集成（全天）

> **工程量提示**：Day 2 你交付了 Memory FTS5（2400+ 行）。Day 3 做跨 graph 编排 + Blackboard 与 Memory 的集成，预计 400-600 行。

### 5.1 上午：跨 Graph 触发机制（chain executor）

**背景**：PRD 明确"6 人小团队不做 Event Bus"，所以 model→risk 用**直接 invoke**。但要做得优雅、可测试。

| 任务 | 说明 | 验收 |
|---|---|---|
| 扩展 `compose_executor.py` | 新增 `chain_flows(flows: list[FlowStep])`：按顺序执行多个 flow，前一个的输出注入后一个的输入 | 单测：flow_a → flow_b 数据传递 |
| 定义 `FlowStep` | `(group, flow_name, input_mapper: Callable)`，input_mapper 从上游 result 提取下游 input | 类型清晰 |
| 处理跨 flow 的 thread_id | model flow 和 risk flow 用**关联的** thread_id（如 `chain-{uuid}-model` / `chain-{uuid}-risk`），便于追溯 | thread_id 可关联 |
| **跨 flow 的错误传播** | 如果 model flow 失败，risk flow 不应触发；chain 返回失败原因 | 单测：上游失败，下游跳过 |

### 5.2 下午：Blackboard ↔ Memory 集成 + reconcile 增强

| 任务 | 说明 | 验收 |
|---|---|---|
| Blackboard 写入触发 Memory 索引 | 当 Blackboard 写 PROJECT scope 时，同步写一份到对应 Memory scope，可被 `memory.search` 检索到 | 单测：写 Blackboard 后能 search 到 |
| reconcile 支持 Blackboard 目录 | 扩展 `reconcile.py` 扫描 `.quantcode/blackboard/` | reconcile 后 Blackboard 内容进 FTS5 |
| 跨 flow 的 Memory 上下文传递 | risk flow 能通过 memory.search 读到 model flow 写的知识（如"这个模型之前被拒过"） | 端到端：model 写 memory → risk search 到 |

**验收标准**：
- `tests/test_chain_flows.py`：至少 8 个测试
- `tests/test_blackboard_memory_integration.py`：至少 5 个测试

---

## 6. Lead · 跨组集成测试 + GROUP 隔离 + 协调（全天）

### 6.1 上午：5-scope 权限矩阵完整测试

Day 2 只测了 groups scope。Day 3 要覆盖全部 5 个 scope 的权限矩阵。

| Scope | 读权限 | 写权限 | 测试 |
|---|---|---|---|
| global | 所有组 | 仅系统 | 2 |
| projects | 所有组 | 所有组（记录 written_by） | 3 |
| groups | 仅 owner | 仅 owner | 已有（Day 2） |
| sessions | 仅 session owner | 仅 session owner | 3 |
| tasks | 仅 task owner + 祖先 task | 仅 task owner | 3 |

**验收**：`tests/test_scope_permission_matrix.py`，覆盖全部 5×2 = 10 种权限组合，至少 12 个测试。

### 6.2 下午：model→risk 端到端集成测试

**这是 Day 3 收工验收的核心**——把三个人的产出串起来。

| 任务 | 说明 | 验收 |
|---|---|---|
| 写 `tests/test_cross_group_handoff.py` | 完整 model→risk 链路集成测试 | 端到端跑通 |
| 场景 1：正常通过 | model 生成 ModelSpec → risk 计算 VaR（未超阈值）→ 直接写 PR comment | flow 一次跑完 |
| 场景 2：HumanGate 触发 | model → risk 计算 VaR（超阈值）→ interrupt → 模拟 approve → resume → 写 comment | 暂停+恢复正确 |
| 场景 3：跨组数据隔离 | 验证 risk 能读 model 的 PROJECT 数据，但读不到 model 的 GROUP 私有数据 | 隔离正确 |
| dedupe 验证 | 同一 PR 同一 commit 触发 2 次，只有 1 条 comment | dedupe 生效 |

### 6.3 协调职责

- **上午 11 点 checkpoint**：确认俞高磊的风控统计库完成（杨欣琳在等）
- **下午 2 点 checkpoint**：确认三条 flow 各自单测通过，可以开始集成
- **下午 4 点**：主持集成联调，解决 flow 之间的接口 mismatch
- 更新架构图：Blackboard 5-scope + 跨组 trigger 时序图

---

## 7. 刘炽 · RiskProfile schema + 集成测试数据 + Typst 深化（全天）

> **工程量提示**：Day 2 你反映任务能 1 小时做完。Day 3 给你三块实打实的活。

### 7.1 上午：RiskProfile schema + risk 报告模板

| 任务 | 说明 | 验收 |
|---|---|---|
| 与杨欣琳共建 `schemas/risk_profile.py` | RiskProfile 字段设计：所有风控指标 + verdict + breached_thresholds + 时点信息 | schema 冻结，单测覆盖 |
| Typst risk 报告模板 | `templates/typst/risk-report.md` 版式：风控指标表格 + VaR 曲线占位 + HumanGate 状态 | 版式文档完整 |

### 7.2 下午：集成测试数据集 + 数据校验工具

**背景**：跨组集成测试需要真实感的测试数据，不能都用 mock。

| 任务 | 说明 | 验收 |
|---|---|---|
| 造 `tests/fixtures/sample_returns.py` | 生成有真实统计特征的收益序列：<br>- 正常序列（Sharpe~1.5）<br>- 高回撤序列（触发 HumanGate）<br>- 尾部风险序列（VaR 超标） | 3 组数据，各有明确特征 |
| 造 `tests/fixtures/sample_model_pr.diff` | 配合陈镇鸿，造一个真实感的模型 PR diff | 陈镇鸿能用 |
| 数据校验工具 `tools/validate_returns.py` | 检查收益序列合法性：无 NaN、长度足够、方差非零 | 单测覆盖 |

### 7.3 机动：补充图表

- 为 Day 4 fundamental flow 准备 2-3 个示例图表（延续 Day 2 未完成的）

---

## 8. Day 3 收工标准（验收清单）

### 核心里程碑
- [ ] **model→risk 完整跑通**：真实 PR 上有 risk comment
- [ ] **HumanGate 触发**：VaR 超阈值 → workflow 暂停 → 日志"⏸️ 等待人工审批" → approve → resume → 完成
- [ ] **Blackboard 跨组**：model 写 PROJECT scope，risk 读到
- [ ] **dedupe 验证**：5 分钟内重复 trigger，PR 只有 1 条评论

### 各组交付
- [ ] 陈镇鸿：`runner/blackboard.py` + model flow + `test_model_flow.py`（8+ 测试）
- [ ] 杨欣琳：eval 修复 + risk flow + HumanGate 集成 + `test_risk_flow.py`（10+ 测试）
- [ ] 俞高磊：`runner/risk_stats.py`（15+ 测试）+ factor 分层回测
- [ ] 尹一帆：`chain_flows` + Blackboard↔Memory 集成（13+ 测试）
- [ ] Lead：5-scope 权限矩阵（12+ 测试）+ 跨组 handoff 集成（4 场景）
- [ ] 刘炽：RiskProfile schema + 测试数据集 + risk 报告模板

### 质量门槛
- [ ] 全量测试通过（预计新增 60+ 测试，总数 150+）
- [ ] CI 全绿
- [ ] 无 eval/exec 等安全隐患
- [ ] 所有 PR 经过 Lead review

---

## 9. 依赖关系图（关键路径）

```
上午：
  俞高磊 risk_stats ──────┐
                          ├──→ 杨欣琳 risk flow（依赖统计函数）
  刘炽 RiskProfile schema ─┘

  尹一帆 chain_flows ──────→ 陈镇鸿 model flow（依赖跨graph触发）

  陈镇鸿 BlackboardService ─→ 杨欣琳 read_model_spec（依赖Blackboard）

下午：
  三条flow单测完成（2点前）
        ↓
  Lead 主持集成联调（4点）
        ↓
  model→risk 端到端跑通（收工）
```

**关键路径**：俞高磊的 risk_stats 必须**上午完成**，否则杨欣琳的 risk flow 卡住。

---

## 10. 与 Day 2 的工程量对比

| 指标 | Day 2 实际 | Day 3 目标 |
|---|---|---|
| 新增代码 | ~6,000 行 | ~4,000 行（更聚焦） |
| 新增测试 | ~30 个 | ~60 个（翻倍） |
| 跨组集成 | 无 | model→risk |
| 新增 schema | 0 | RiskProfile |
| 新增基础设施 | Memory/LangGraph | Blackboard/chain_flows |

**难度提升点**：
1. Day 2 是单组闭环，Day 3 是跨组协作（接口对齐更难）
2. HumanGate 的 interrupt→resume 是 LangGraph 最复杂的机制
3. Blackboard 的持久化 + 权限 + Memory 集成是新的一层
4. 测试从单元测试为主，转向**集成测试**为主

---

**Day 3 目标一句话**：让两个组通过 Blackboard 对话，让 HumanGate 真正暂停一次 workflow。

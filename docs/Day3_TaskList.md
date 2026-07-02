# Day 3 任务清单

> **里程碑**：First Agent Flow（第一条自主推理的 Agent 流跑通）
> **一句话目标**：用 LangGraph 改写 MimoCode compose 引擎的核心循环，跑通第一条流（model 组），验证能自主推理、能调用 tools、能 checkpoint。

---

## 0. 核心共识（全员必读）

经过架构调研和讨论，我们达成的技术路线：

**我们在做什么**：
- 改进 MimoCode 的 compose 模式，让它能做量化场景的"idea → 主线匹配 → 动态 Schema → 程序化验收 → 接入生产"
- 用 **LangGraph 改写 compose 的 ReAct 引擎**（MimoCode 手写的 loop → LangGraph 的标准化图），同时补齐生产级配套（checkpoint / 权限 / 错误处理 / 自研加固）
- **复用 MimoCode 的 15 个 compose skill**（brainstorm / plan / execute / tdd / review…），它们是 markdown 文本，引擎无关，直接喂给 LangGraph Agent
- **加我们的量化能力**：match_main（主线匹配）、gen_schema（动态 Schema）、程序化验收、跨组协作（Blackboard）、RLHF 接入

**技术兼容性**：
- MimoCode compose 的核心 = while 循环（推理 → 调 tool → 观察 → 再推理）
- LangGraph = 把这个循环做范式化封装的图框架（`create_react_agent` 就是这个 loop）
- 两者本质相同，LangGraph 改写 MimoCode loop 是技术上自然的选择

**Day 3 的验证目标**：
1. LangGraph 能不能把 MimoCode compose 的核心 loop 改写起来
2. 15 个 skill 的 markdown 能不能直接喂给 LangGraph Agent 使用
3. 第一条业务流（model 组）能不能在改写后的引擎上跑通

---

## 1. Day 3 架构目标

```
改写前（MimoCode 原版）          改写后（我们的版本）
┌─────────────────────┐         ┌─────────────────────────┐
│ compose 手写 loop    │   →    │ LangGraph StateGraph     │
│ (prompt.ts runLoop) │         │ (create_react_agent)    │
│                     │         │                          │
│ while not done:     │         │ nodes: [推理, 执行, 检查] │
│   llm推理           │         │ edges: [条件路由]        │
│   tool执行          │         │ checkpoint: SqliteSaver  │
│   观察结果          │         │ + 自研加固（死循环检测）  │
└─────────────────────┘         └─────────────────────────┘
         │                                │
    调用 15 个 skill                 调用 15 个 skill
    (markdown 文本)                  (同样的 markdown)
         │                                │
         ↓                                ↓
    MimoCode tools                  MimoCode tools
    (TS tool registry)              + 我们的量化 tools
                                    (通过 MCP 或 TS 接入)
```

**关键点**：
- **引擎层**：从手写 loop 改为 LangGraph（范式化、可扩展、有 checkpoint）
- **skill 层**：15 个 skill markdown 原封不动复用
- **tool 层**：MimoCode 原有 tools 保留 + 我们加量化 tools（read_pr / extract_metadata / match_main / ...）

---

## 2. 全员 Standup（15 分钟）

- Day 2 回顾：Memory FTS5、checkpoint、dedupe 已完成，为 Day 3 打好地基
- **架构共识确认**：LangGraph 改写 compose 引擎 + 复用 15 个 skill + 加量化 tools
- Day 3 目标：跑通第一条流（model 组），验证改写后的引擎能用
- **依赖关系**：尹一帆的引擎改写是所有人的底座（最高优先级）

---

## 3. 尹一帆 · LangGraph 改写 compose 引擎（全天，核心底座）

> **工程量提示**：这是 Day 3 最关键的任务——把 MimoCode compose 的手写 loop 改写成 LangGraph。预计 500-800 行。

### 3.1 上午：最小 LangGraph 改写实验（验证可行性）

**目标**：用最简单的场景验证"LangGraph 能改写 MimoCode compose loop"。

| 任务 | 说明 | 验收 |
|---|---|---|
| 选一个最简单的 skill | 从 MimoCode 的 15 个 skill 选一个（推荐 `plan` 或 `brainstorm`），读它的 SKILL.md | markdown 内容理解清楚 |
| 用 LangGraph 实现基础 loop | `create_react_agent(llm, tools, system_prompt=skill_md)` | Agent 能跑起来 |
| 喂入 skill markdown | 把 SKILL.md 内容作为 system_prompt 或 state_modifier | Agent 的行为符合 skill 指导 |
| 调用 1-2 个 tool | 注册 MimoCode 已有的 tool（如 Read / Write），验证 Agent 能调 | tool 执行成功 |
| checkpoint 集成 | `SqliteSaver` 自动保存，中断后恢复 | 单测：kill → resume |

**验收标准**：
- 能跑通一个完整的 task："写一个实现计划" → Agent 读代码 → 生成计划
- 中断后能从 checkpoint 恢复
- **输出报告**：LangGraph 改写 MimoCode loop 缺了哪些配套（权限？taskGate？goalGate？），列出来

### 3.2 下午：完整引擎封装（生产级配套）

根据上午发现的"缺失配套"，逐一补齐：

| 任务 | 说明 | 验收 |
|---|---|---|
| 封装 `QuantCodeAgent` | 把 `create_react_agent` 包装成我们的 Agent 类，统一接口 | API 清晰 |
| 权限集成（Permission） | tool 执行前检查权限（allow/deny/ask），`ask` 触发 interrupt | 单测：permission=ask → 暂停 |
| taskGate / goalGate | 检查任务完成条件，Agent 自己判断"做完了吗" | 单测：完成条件触发终止 |
| 错误恢复 | 捕获常见错误（tool 报错、LLM invalid output），重试或中止 | 单测：tool 报错 → 重试 |
| 迭代上限 | 最多 N 步（默认 100），防失控 | 单测：超步数 → 中止 |
| SSE 流式输出 | 把 Agent 的 thought / tool_call / tool_result 转成 SSE | 前端（或测试）能实时看 |

**验收标准**：
- `runner/quantcode_agent.py`：封装完整，接口稳定
- `tests/test_quantcode_agent.py`：至少 8 个测试（权限/gate/错误/迭代上限/checkpoint）
- 一个完整示例能跑通：给 task → Agent 自主推理完成 → checkpoint 可恢复

---

## 4. 陈镇鸿 · model 组 tools + Blackboard（全天，600-700 行）

### 4.1 上午：Blackboard 服务（跨组共享数据层）

**背景**：量化场景需要跨组协作（model → risk），Blackboard 是共享数据层。

| 任务 | 说明 | 验收 |
|---|---|---|
| 新建 `runner/blackboard.py` | 实现 `BlackboardService`：<br>- `write(scope, key, value)`<br>- `read(scope, key)` | 单测：write → read |
| 5-scope 支持 | PROJECT（跨组可读）、GROUP（组内私有）| 单测：跨组读取权限正确 |
| 持久化到 SQLite | 存 `.quantcode/blackboard.db` | 重启后数据仍在 |

### 4.2 下午：model 组 5 个 tools

每个 tool 是独立函数，注册到 tool registry（参考 MimoCode 的 `Tool.Def` 格式）。

| Tool | 输入 | 输出 | 说明 |
|---|---|---|---|
| `read_pr` | pr_number | diff 文本 | 从 fixture 或 GitHub API 读 PR diff |
| `extract_metadata` | diff | dict | 正则提取模型类型/超参/训练区间 |
| `generate_model_spec` | metadata | ModelSpec | 构造并校验 Day 1 schema |
| `write_blackboard` | key, value | success | 写 PROJECT scope |
| `trigger_risk_flow` | key | task_id | 触发 risk Agent（简单版：直接调用）|

**验收标准**：
- `tools/model_tools.py`：5 个 tool 定义
- `tests/test_model_tools.py`：每个 tool 单测
- 注册到 MimoCode 兼容的 tool registry（或我们自己的，能被 LangGraph Agent 调用）

---

## 5. 杨欣琳 · risk 组 tools + HumanGate 集成（全天，500-600 行）

### 5.1 上午 Part A：修复 PR #12 的 eval() 问题（P0，先做）

| 任务 | 说明 | 验收 |
|---|---|---|
| 移除 `eval` | 改为 `match/case` 判断 | 无 eval，测试通过 |
| rebase 到最新 main | 合入最新改动 | CI 通过 |

### 5.2 上午 Part B：risk 组 5 个 tools

| Tool | 输入 | 输出 | 说明 |
|---|---|---|---|
| `read_blackboard` | key | value | 从 PROJECT scope 读 model 数据 |
| `calc_risk` | returns | RiskMetrics | 调用俞高磊的 stub |
| `generate_risk_profile` | metrics | RiskProfile | 用刘炽的 schema |
| `check_gate` | profile | bool | VaR 是否超阈值 |
| `write_pr_comment` | pr_number, comment | comment_id | 写 PR 评论（dedupe）|

### 5.3 下午：HumanGate 与 permission 集成

| 任务 | 说明 | 验收 |
|---|---|---|
| Permission 规则定义 | `.quantcode/permissions/risk.yaml`：`check_gate: ask` | 规则可解析 |
| interrupt 触发 | permission=ask → 抛 `NodeInterrupt` → Agent 暂停 | 单测：interrupt 触发 |
| approve/reject API | 人审后恢复执行 | 单测：approve → 恢复 |

**验收标准**：
- `tools/risk_tools.py`：5 个 tool
- `tests/test_risk_agent.py`：至少 8 个测试
- Demo：VaR 超阈值 → interrupt → 日志"⏸️" → approve → 恢复

---

## 6. 俞高磊 · RiskTool stub + 自研加固（全天，400-500 行）

### 6.1 上午：RiskTool stub

| 任务 | 说明 | 验收 |
|---|---|---|
| `tools/risk_tool.py` | 接口 `calc_metrics(returns) -> RiskMetrics` | 接口清晰 |
| Stub 实现 | 从 fixture 读预设值返回 | 单测通过 |
| 注册到 tool registry | risk Agent 能调用 | 集成测试 |

### 6.2 下午：死循环检测（自研加固）

| 任务 | 说明 | 验收 |
|---|---|---|
| `runner/loop_detector.py` | 滑动窗口检测同一 tool 高频调用 | 单测：模拟死循环 |
| 集成到 Agent | tool 执行前检查，触发时中止 | 端到端：死循环 → 自动中止 |

---

## 7. 刘炽 · Schema + fixture + SKILL.md（全天）

### 7.1 上午：RiskProfile schema + fixture

| 任务 | 说明 | 验收 |
|---|---|---|
| `schemas/risk_profile.py` | 与杨欣琳共建 | schema 冻结 |
| `tests/fixtures/risk_metrics.json` | 两组数据（正常+超阈值）| 俞高磊能用 |

### 7.2 下午：model 流的 SKILL.md

**背景**：MimoCode 的 15 个 skill 是 markdown，我们的量化流也写成这个格式，喂给 LangGraph Agent。

| 任务 | 说明 | 验收 |
|---|---|---|
| 参考 MimoCode skill 格式 | 读 `vendor/mimo-code/.../skills/` 下的 SKILL.md，理解格式 | 格式清楚 |
| 写 `model/SKILL.md` | 放 `.opencode/skills/model/SKILL.md`，描述 model 组工作流 | markdown 格式正确 |
| frontmatter | 至少含 `name` + `description` + `tools`（可用 tool 列表）| 能被 Agent 加载 |

**SKILL.md 示例结构**：
```markdown
---
name: model-pr-submit
description: 处理模型 PR 并交给风控
tools: [read_pr, extract_metadata, generate_model_spec, write_blackboard, trigger_risk_flow]
---

# Model 组 PR 提交流程

当你收到"处理 PR #123"这样的任务时，你需要：

1. 读取 PR 内容（调用 read_pr）
2. 提取模型元数据（调用 extract_metadata）
3. 生成 ModelSpec（调用 generate_model_spec，校验 schema）
4. 写入共享层（调用 write_blackboard，key=model.pr.{pr_number}）
5. 触发风控流程（调用 trigger_risk_flow）

每一步完成后检查结果，确保符合预期再继续。
```

---

## 8. Lead · 协调 + 集成测试（全天）

### 8.1 上午：协调与 checkpoint

- **10:30**：确认尹一帆的最小改写实验完成，评估"缺失配套"清单
- **11:30**：确认刘炽的 schema + fixture 完成

### 8.2 下午：model 流端到端集成

| 场景 | 验收标准 |
|---|---|
| 场景 1：model Agent 自主推理 | 给任务"处理 PR #123"，Agent 自己决定调哪些 tool，完成全流程 |
| 场景 2：15 个 skill 复用验证 | 加载 MimoCode 的 1-2 个 skill（如 brainstorm），验证能用 |
| 场景 3：checkpoint 恢复 | 中断 model Agent → 从 checkpoint 恢复 → 继续完成 |
| 场景 4：Blackboard 写入 | model 写 PROJECT scope，数据持久化 |

**交付**：`tests/test_model_flow_e2e.py`，至少 4 个端到端测试。

---

## 9. Day 3 收工标准（验收清单）

### 核心里程碑
- [ ] **LangGraph 改写验证**：最小实验跑通，证明 LangGraph 能改写 MimoCode compose loop
- [ ] **15 个 skill 复用**：至少 1 个 MimoCode skill（如 plan）能在 LangGraph 引擎上使用
- [ ] **model Agent 自主推理**：给任务"处理 PR #123"，Agent 自己决定调哪些 tool，完成 5 步流程
- [ ] **checkpoint 可恢复**：中断后能从断点恢复，不重跑已完成步骤
- [ ] **Blackboard 跨组数据**：model 写 PROJECT scope，数据持久化（为 Day 4 risk 读取做准备）

### 各组交付
- [ ] 尹一帆：LangGraph 改写引擎 + 生产级配套（`runner/quantcode_agent.py`，8+ 测试）
- [ ] 陈镇鸿：Blackboard + model 组 5 个 tools（`runner/blackboard.py` + `tools/model_tools.py`，5+ 测试）
- [ ] 杨欣琳：risk 组 5 个 tools + permission 集成（`tools/risk_tools.py`，8+ 测试）
- [ ] 俞高磊：RiskTool stub + 死循环检测（`tools/risk_tool.py` + `runner/loop_detector.py`，5+ 测试）
- [ ] 刘炽：RiskProfile schema + model SKILL.md（`schemas/` + `.opencode/skills/model/SKILL.md`）
- [ ] Lead：model 流端到端集成（4 场景）

### 质量门槛
- [ ] 全量测试通过（Day 1-3 总数 80+）
- [ ] CI 全绿
- [ ] 所有 PR 经过 Lead review

---

## 10. 依赖关系图（关键路径）

```
上午：
  尹一帆 最小改写实验（10:30 前）──→ 评估"缺失配套"清单
        ↓
  所有人看清楚要补哪些（权限/gate/错误处理）
        ↓
  刘炽 schema + fixture（11:30 前）──→ 俞高磊 stub ──→ 杨欣琳 risk tools
        ↓
  尹一帆 完整引擎封装 ──→ 陈镇鸿集成 model tools

下午：
  尹一帆引擎完成（2 点前）
        ↓
  陈镇鸿 model tools 注册到引擎
        ↓
  Lead 主持端到端集成测试（4 点）
        ↓
  model 流跑通（收工）
```

**关键路径**：尹一帆的最小改写实验（10:30）和完整引擎（下午 2 点）是所有人的依赖。

---

## 11. 与原计划的差异（给团队的说明）

| 原计划（Day 2 后） | Day 3 实际 | 为什么变 |
|---|---|---|
| 预定义 5-node StateGraph | LangGraph 改写 compose loop | MimoCode compose 本质就是 loop，LangGraph 是范式化封装，改写是自然选择 |
| 自己写 ReAct 循环 | 用 `create_react_agent` | 不重复造轮子，LangGraph 官方实现更稳定 |
| 不确定 MimoCode skill 怎么用 | 15 个 skill 直接复用 | skill 是 markdown 文本，引擎无关，喂给 LangGraph 就能用 |

**Day 2 的东西没白做**：Memory、checkpoint、dedupe 全部复用，它们是 Agent 的配套服务，跟引擎实现无关。

---

**Day 3 一句话总结**：用 LangGraph 改写 MimoCode compose 引擎，复用它的 15 个 skill，跑通第一条量化流（model 组），验证改写后的引擎能自主推理、能调 tools、能 checkpoint。

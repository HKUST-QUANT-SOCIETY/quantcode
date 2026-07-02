# QuantCode PRD — 产品需求文档

> **版本**：v1（产品方向已落地到 OpenCode fork + 6 套 Compose 流）
> **Owner**：Agent Group · HKUST QUANT SOCIETY
> **最后更新**：2026-06-30

---

## 0. TL;DR

**一句话定义产品**：
> QuantCode 是 HKUST QUANT SOCIETY 内部使用的量化投研 Agent 平台，**6 个组登录同一个 agent，每个组进入自己工作流的 Compose 流；流跑完自动接入生产主线**。

**一句话定义目标用户**：
> HKUST QUANT SOCIETY 的 6 个研究/业务组（基本面、因子、模型、风控、策略、期权），以及内部 agent 组本身。

**一句话定义核心价值**：
> 把"人与人的协商"换成"机器与机器的 schema 校验"，把验收标准从"看一眼觉得行"换成"`assert` 通过/失败 + Goal/Judge"。

**Agent 搭建边界**：
> QuantCode 不是单纯写一组量化函数库。因子函数、评估配置、风控阈值是 Agent 调用的工具输入；真正的 Agent 工作是把研究员需求路由到 Compose 流的对应 skill，补齐上下文，按 Pattern 1/2/5 调度，执行 schema/assert 验收，并把结果写回 PR、报告或 artifact。

---

## 1. 背景与问题

### 1.1 当前痛点

- **跨组协作的隐性损耗**：模型组提 PR 后需要和风控组协商，风控判断标准不统一，流程慢
- **研报生产不可复用**：每份基本面研报都是手写，结构没法批量生成
- **因子评估口径不一**：每个人算 IC 用的样本和方法不同，难以横向比较
- **AI 工具孤立使用**：组员各自调 ChatGPT / Cursor，没有沉淀成团队资产
- **长任务上下文丢失**：10+ 小时的研究任务在 LLM 中跑会 compact 丢信息

### 1.2 现有方案为什么不够

- **直接用 OpenCode / MimoCode / Claude Code**：通用，没有量化业务知识，没有按组分发，每次都要重新喂上下文
- **完全自建 IDE**：和腾讯 Workbench 比拼端到端体验，必死
- **只做 4 个独立 skill**：协会要的是覆盖 6 个组的工作流编排，单点 skill 解决不了跨组协作

### 1.3 为什么是现在

- OpenCode 2026 H1 趋于稳定，扩展机制成熟（plugin / tool / SKILL.md / Compose Mode 四件套）
- MimoCode 已开源 Memory / Checkpoint / Subagent / Goal / Dream / Distill，可 cherry-pick
- LLM 长上下文能力足够支撑 30 分钟以上的研究任务，配合 Pattern 2（Blackboard）可外化长状态
- 团队有真实痛点（模型组和风控组协作摩擦），有 6 人 agent 组可以建设

---

## 2. 目标用户

### 2.1 用户画像

| 组 | 人数 | 主要工作 | 对 QuantCode 的需求 |
|---|---|---|---|
| **基本面组** | 2-3 | 公司研究、行业研究、写研报 | 快速生成专业 PDF、point-in-time 检索研报 |
| **因子组** | 3-4 | 因子开发、因子评估 | 标准化因子评估、接 AutoFactorEvaluation、横向比较 |
| **模型组** | 3-4 | 策略建模、机器学习因子 | 提 PR 后自动风控反馈，无需反复同步风控组 |
| **风控组** | 2-3 | 风险评估、PR 审批 | 程序化阈值，24h 自动执行风控规则，HumanGate 兜底人审 |
| **策略组** | 2-3 | 组合构建、调仓决策 | 标的筛选、组合优化、回测 |
| **期权组** | 1-2 | 期权定价、波动率研究、对冲策略 | 期权数据处理、波动率曲面、Greeks 和组合风险 |
| **Agent 组**（我们） | 6 | 建设和维护 QuantCode | dogfood：每天用自己的工具 |

### 2.2 典型工作流变化（模型 → 风控）

**模型组同学的"今天"**：
1. 写完一个新的 ML 因子，提 PR
2. 微信群里 @ 风控组，问"我这个 max_drawdown 算得对吗"
3. 风控组同学有空了才看，可能 1-2 天
4. 来回讨论 3-5 轮，统一口径
5. 终于 merge

**模型组同学的"明天"**：
1. 在 QuantCode 用 `model` Compose 流（`model:pr-submit` skill 自动填风控元数据）
2. 自动触发风控组的 `risk` Compose 流（`risk:detect → analyze → schema-gen → ci-gate`）
3. 10 分钟内 PR 评论里出现 `RiskProfile` JSON + 自动结论
4. 越过阈值 → 走 `HumanGate`，等风控组同学人工审批；通过阈值 → 自动 approve 等人 review
5. 风控组只需要 review JSON，不用从 0 开始算

---

## 3. 产品范围

### 3.1 必做（P0，MVP）

**6 套 vertical Compose 流**（按组分发，详见 Design §4.3）：

| Compose 流 | 价值 | Owner |
|---|---|---|
| `fundamental` | 基本面研究 + 研报 PDF | 用户（Lead） |
| `factor` | 因子开发 → AutoEval → 主线 | 肖骥超 |
| `model` | 模型 PR 元数据 → 跨组发起 | 陈镇鸿 |
| `risk` | PR 风控门禁 → HumanGate | 杨欣琳 |
| `strategy` | 组合构建、回测、上线 | 待定 |
| `options` | 波动率曲面、Greeks、对冲 | 刘炽 |

**三大生产模式的契约**（所有 Compose 流的架构基石）：

| Schema | 对应模式 | Owner |
|---|---|---|
| `ComposeTask` | Pattern 1 (Orchestrator-Worker) | 用户（Lead） |
| `BlackboardState` | Pattern 2 (Stateful Blackboard) | 用户（Lead） |
| `HumanGate` | Pattern 5 (Human-in-the-Loop Gate) | 杨欣琳 |

**业务 schema**：`ModelSpec` / `RiskProfile` / `FactorSpec` / `ResearchSpec` / `PITQuery` + `PITResult`

**共用基础设施**：

- 验收 runner（公用，吃 JSON 吐 pass/fail + Goal/Judge）
- GitHub Actions CI gate
- `@dedupe_within` 副作用 tool 去重保险栓（约 30 行装饰器 + SQLite）
- 从 MimoCode cherry-pick（P0）：Memory FTS5、自动 Checkpoint、Dream 原型
- 从 MimoCode cherry-pick（P1，Week 2）：上下文重建、Subagent 监控、Distill 完整版

### 3.2 应做（P1，MVP 之后）

- **Compose 视图前端**（OpenCode desktop fork UI 改造：Compose 视图、任务树、Subagent 监控）
- **跨组通知中心**（HumanGate 触发后的统一通知面板）

### 3.3 不做（明确边界）

- ❌ **自建 IDE / 桌面端 / 终端 UI** —— OpenCode 已经提供，我们只改 desktop UI 加业务面板
- ❌ **Fork MimoCode 源码** —— 从 MimoCode cherry-pick 模块到我们的 OpenCode fork
- ❌ **多租户 SaaS / 对外服务** —— 我们是内部工具
- ❌ **自建 LLM 训练** —— 用 Claude / GPT
- ❌ **造数据基建** —— 让基建组负责，agent 组消费
- ❌ **Supervisor/Verifier 独立 agent**（Pattern 3） —— 量化验收天然量化，`assert` + Goal/Judge 已够
- ❌ **Event-Driven Pub/Sub**（Pattern 4） —— 6 人小团队 A→B 直接调用足够
- ❌ **完整 Idempotent Retry Chain**（Pattern 6） —— 副作用 tool dedupe 兜底，不做完整哈希链

---

## 4. 功能详述（核心 P0）

### 4.1 6 套 vertical Compose 流

每套流 = 一组 SKILL.md + 调度规则 + 默认 tool 集 + MEMORY.md。详细 skill 列表见 `docs/QuantCode_Design.md` §4.3。

#### 4.1.1 risk Compose 流（PR 风控门禁）

**用户故事**：
> 作为模型组研究员，我提交策略代码 PR 后，希望 10 分钟内自动得到风控分析 JSON，告诉我 max_drawdown / position_limit / 相关性 / 容量 / VaR 是否满足阈值，不用等风控组人工 review 就知道哪里要改。

**Available Tools**（Agent 可调用）：
- `read_blackboard(key)` - 读取 model 组写入的 ModelSpec
- `calc_risk(returns)` - 计算风控指标（VaR/MaxDD/Sharpe 等）
- `generate_risk_profile(metrics)` - 生成结构化的 RiskProfile
- `check_gate(profile)` - 判断是否需要触发 HumanGate
- `write_pr_comment(pr_number, comment)` - 写风控分析结果到 PR

**System Prompt**（核心指令）：
> 你是 risk 组的风控分析 Agent。当接到任务时，你需要：
> 1. 读取 model 组提交的模型元数据（从 Blackboard）
> 2. 调用风控计算工具获得各项指标
> 3. 生成符合 RiskProfile schema 的结构化报告
> 4. 如果 VaR/MaxDD 超阈值，触发人工审批
> 5. 最终把分析结果写回 PR

**输入**：任务描述（"分析 PR #123 的风控"）+ Blackboard key（`model.pr.123`）

**输出**：符合 `schemas/risk-profile.schema.json` 的 `RiskProfile`，写入 PR comment

**验收标准**：
```python
assert risk_json["max_drawdown"] <= 0.20
assert risk_json["position_limit"] <= 0.30
assert abs(risk_json["correlation_with_existing"]) <= 0.60
assert risk_json["tail_risk_var_99"] is not None
# 越过阈值时自动触发 HumanGate
```

#### 4.1.2 fundamental Compose 流（基本面 + PIT-RAG）

**Available Tools**（Agent 可调用）：
- `pit_rag_search(query, as_of_date)` - 时点安全的语料检索（强制 `published_at <= as_of_date`）
- `extract_financials(doc)` - 财报结构化提取
- `dcf_valuation(financials)` - DCF 估值计算
- `render_report(spec)` - 渲染研报 PDF（Typst）
- `request_human_review(pdf)` - 提交研究员人工验收

**System Prompt**（核心指令）：
> 你是基本面研究 Agent。围绕用户给定的公司/行业问题，检索时点安全的语料，提取财务数据，做估值，产出结构化研报。所有检索必须遵守时点约束，杜绝 lookahead bias。研报渲染后走人工验收。

**关键约束**：`pit_rag_search` 强制 `published_at <= as_of_date`

**输入**：`PITQuery`（query + as_of_date + corpus）
**输出**：`PITResult` → `ResearchSpec` → research.pdf

**验收标准**：
```python
for doc in result["documents"]:
    assert doc["published_at"] <= query["as_of_date"]
# 渲染 PDF 后人工验收：研究员愿意发出去 = 通过（走 HumanGate）
```

#### 4.1.3 factor Compose 流（因子评估）

**Available Tools**（Agent 可调用）：
- `match_main(idea)` - 匹配主线因子库，判断兼容性
- `gen_factor_schema(idea)` - 动态生成因子 Pydantic schema
- `run_autoeval(factor)` - 调用 AutoFactorEvaluation 执行回测
- `check_factor_gate(report)` - 判断因子指标是否达标
- `merge_to_main(factor)` - 合入主线（需 HumanGate）

**System Prompt**（核心指令）：
> 你是因子评估 Agent。接到因子 idea 后，匹配主线因子库，生成因子定义 schema，调用 AutoEval 回测，产出 IC/IR/换手率等指标报告。指标达标才建议合入主线。

**接入**：HKUST-QUANT-SOCIETY/auto_factor_evaluation

**输出**：符合 `schemas/factor-report.schema.json` 的 `FactorReport`

**验收标准**：
```python
assert abs(report["ic_metrics"]["ic_mean"]) >= 0.03
assert report["ic_metrics"]["ir"] >= 0.5
assert report["turnover"]["monthly"] <= 0.8
assert report["ic_metrics"]["t_stat"] >= 2.0
```

#### 4.1.4 model Compose 流（模型 / 跨组发起）

**Available Tools**（Agent 可调用）：
- `read_pr(pr_number)` - 读取模型 PR diff
- `extract_metadata(diff)` - 提取模型元数据（类型/超参/训练区间）
- `generate_model_spec(metadata)` - 生成 ModelSpec
- `write_blackboard(key, value)` - 写入共享状态层（PROJECT scope）
- `trigger_risk_flow(key)` - 触发 risk 组 Agent（跨组 handoff）

**System Prompt**（核心指令）：
> 你是模型组 Agent。当研究员提交模型 PR 时，你读取 PR 内容，提取模型元数据并填充风控所需信息，写入共享状态层，然后触发风控组的分析流程。

**关键**：写 Blackboard 时自动填风控元数据；`trigger_risk_flow` 发起跨组协作

#### 4.1.5 options Compose 流

**Available Tools**（Agent 可调用）：
- `build_vol_surface(market_data)` - 构建波动率曲面
- `calc_greeks(position)` - 计算希腊字母
- `run_options_backtest(strategy)` - 期权策略回测

**System Prompt**（核心指令）：
> 你是期权组 Agent。围绕用户的期权策略 idea，构建波动率曲面，计算风险敞口（Greeks），执行策略回测。

#### 4.1.6 strategy Compose 流

**Available Tools**（Agent 可调用）：
- `select_signals(candidates)` - 从候选信号中筛选
- `combine_signals(signals)` - 组合多信号
- `run_strategy_backtest(combined)` - 组合策略回测
- `deploy_strategy(strategy)` - 部署到生产（需 HumanGate）

**System Prompt**（核心指令）：
> 你是策略组 Agent。从多个候选信号中筛选、组合，回测组合策略表现，达标后建议部署到生产主线。

### 4.2 三大生产模式契约

详见 `docs/QuantCode_Design.md` §3.2 + §4.2.0。所有功能必须落到这三个契约之一。

| Pattern | 落地 | Owner |
|---|---|---|
| **1 Orchestrator-Worker** | Compose Mode 中心调度 + SKILL.md/Subagent 工人 | Lead |
| **2 Stateful Blackboard** | MEMORY.md / checkpoint.md / progress.md + SQLite FTS5 | Lead |
| **5 Human-in-the-Loop Gate** | HumanGate schema + OpenCode permission 系统 | 杨欣琳 |

**保险栓**：`@dedupe_within` 装饰器（陈镇鸿）覆盖 `github_pr_*` / `send_email` / `slack_notify` / `cross_team_notify`。

### 4.3 共用基础设施

- **验收 runner**（`runner/acceptance.py`）：吃 JSON 吐 pass/fail；阈值由 `pipelines/<flow>/config.yaml` 覆盖
- **Schema 校验**（`runner/schema_validator.py`）：所有 Compose 流的输入输出强制校验
- **CI gate**（`.github/workflows/risk-gate.yml`）：PR 触发 → OpenCode skill → schema → runner → PR 评论（去重）

### 4.4 核心引擎功能实现路线

> **背景**：QuantCode 需要 Memory、Checkpoint、Workflow 等引擎能力支撑长任务执行。MimoCode (`vendor/mimo-code/`) 已实现类似功能，我们参考其设计并实现 Python 版本。

| 功能 | 用户价值 | 技术实现 | 参考资源（MimoCode 路径） | 优先级 | 状态 | 负责人 |
|------|---------|---------|--------------------------|--------|------|--------|
| **Memory 全文检索** | 跨会话知识复用，搜索历史结论 | SQLite FTS5 + BM25 + CJK 分词 | `packages/opencode/src/memory/` | P0 | ✅ Day 2 | 尹一帆 |
| **Workflow 跨组编排** | model→risk 自动触发，无需手动协调 | 跨 flow 触发 + 状态传递 | `src/workflow/runtime.ts`<br>`src/workflow/events.ts` | P0 | 🔧 Day 3 | 尹一帆 |
| **Compose 模式声明** | SKILL.md 声明 node 拓扑，自动编排 | frontmatter + node 提取 | `src/skill/compose/` | P0 | 🔧 Day 3 | 陈镇鸿 |
| **任务树管理** | 并行任务监控、单独 kill | 任务 registry + gate 状态机 | `src/task/task.sql.ts`<br>`src/task/gate.ts` | P1 | 🔲 Week 2 | Lead |
| **自动 Checkpoint** | context > 70% 自动快照，长任务不丢失 | snapshot 触发器 | `src/snapshot/` | P1 | 🔲 Week 2 | TBD |
| **上下文重建** | context > 90% 从 Memory 重组，避免重头来过 | checkpoint + MEMORY 合成 | `src/session/` | P1 | 🔲 Week 2 | TBD |
| **Subagent 监控** | 查看子任务状态，单独中止失控任务 | subagent 生命周期追踪 | `src/agent/` + `src/task/` | P1 | 🔲 Week 2 | TBD |
| **Dream 知识提取** | 每周自动从 trace 提取知识到 MEMORY.md | trace 扫描 + LLM 总结 | 🔍 需自行设计 | P0 原型 | 🔲 Day 4 | 尹一帆 |
| **Distill 自动化识别** | 识别重复操作，自动生成 SKILL.md | 操作序列聚类 | 🔍 需自行设计 | P2 | 🔲 Week 3+ | TBD |
| **Goal + Judge** | 设定目标，自动评估任务完成度 | Goal DSL + Judge 模型 | 🔍 需自行设计 | P2 | 🔲 Week 3+ | TBD |

**图例**：
- ✅ 已完成 | 🔧 进行中 | 🔲 待开始 | 🔍 MimoCode 代码库未找到，需自行设计

**关键发现**（2026-07-03 代码库验证）：
1. ✅ Memory 功能已实现（Day 2），5-scope + FTS5 + CJK 分词完整
2. ✅ Workflow 编排机制在 MimoCode 有完整实现，Day 3 可参考设计
3. ✅ Compose 模式在 MimoCode 已验证，SKILL.md frontmatter 设计可复用
4. ❌ Dream/Distill/Goal 在 MimoCode 未找到独立模块（可能未开源），需自行设计原型
5. ⚠️ 风控统计（VaR/MaxDD/Sharpe）是 QuantCode 业务逻辑，MimoCode 是通用平台不含此类计算

**实现原则**：
- 功能语义对标 MimoCode（用户体验一致）
- Python 实现遵循 Python idiom，不逐字翻译 TypeScript
- 遇到依赖小米服务（MiMo Auto/ASR）的部分，手动重写
- 保持 MIT 协议，注明参考出处

---

## 5. 非功能性需求

### 5.1 性能

- 一次因子评估（CSI 1000，3 年回溯）< 30s
- pit-rag 检索 P95 延迟 < 500ms
- 研报 PDF 生成 < 5min（含 RAG + LLM + 渲染）
- 模型组 PR → 风控反馈 < 10min

### 5.2 可观测性

- 每次 agent run 落 trace（OpenTelemetry 或简易 JSON log）
- 每个 task 有 UUID，可追踪
- runner 验收结果持久化（SQLite 本地）
- 副作用 tool 调用进 dedupe 日志表，可审计

### 5.3 可重放（依赖 MimoCode 移植的 Checkpoint）

- 任何 task 带 ID 可以 `quantcode replay <task_id>`
- Checkpoint：context > 70% 自动 snapshot；> 90% 触发上下文重建
- 长任务（10h+）context 不丢失，可断点续跑

### 5.4 安全性

- 敏感配置（API key / 数据库密码）不入库
- `opencode.local.jsonc` 本地覆盖（`.gitignore` 排除）
- 高风险操作（删库、force push、修改 schemas/）permission 设为 deny / ask
- 跨组发邮件 / 写 PR 评论强制走 `@dedupe_within`，防止刷屏

---

## 6. 技术架构

### 6.1 三层架构（详见 `docs/Architecture_Spec.md`）

**语言边界即职责边界**：控制平面用 TypeScript（复用 OpenCode 生态），核心推理编排用 Python（LangGraph ReAct Agent + 自研运行时加固），执行层为 Python tools。三层跑在同一个 MimoCode/OpenCode 运行环境里。

```
        ┌──────────────────────────────────────┐
        │  控制平面（TypeScript / OpenCode fork）│
        │  SSH key⟶组绑定 · idea⟶模式分派        │
        │  触发 compose 流 · Agent 状态可视化    │
        └───────────────┬──────────────────────┘
                        │ 触发 compose 流
        ┌───────────────▼──────────────────────┐
        │  编排平面（Python / LangGraph）        │
        │  ★核心推理编排唯一归属，Node.js 不参与 │
        │  ReAct 循环（Agent 自主推理，非预设DAG)│
        │  复用 MimoCode 的 15 个 compose skill  │
        │  Tool Registry · Permission(allow/ask) │
        │  checkpoint · interrupt/resume         │
        │  自研加固：死循环/迭代上限/循环检测    │
        │  算法侧接入：RLHF / 微调 / 评估        │
        │  Memory FTS5 · Blackboard · 监控       │
        └───────────────┬──────────────────────┘
                        │ 调用 tool
        ┌───────────────▼──────────────────────┐
        │  执行平面（Python tools/ + 外部系统）  │
        │  解耦的独立 tool 函数                   │
        │  AutoEval · SSH · COS · GitHub · RAG   │
        └──────────────────────────────────────┘
```

**四条铁律**：
1. 核心推理编排只在编排平面（Python/LangGraph），TS 控制平面不承载推理调度。
2. **Agent 自主推理，不预定义工作流 DAG**：编排平面是 ReAct 循环（LLM 推理下一步→调 tool→观察→再推理），流程由 Agent 推理产生，不是执行预设拓扑。"6 套 Compose 流" = 同一个 ReAct 循环 + 6 套 system prompt(skill) + 6 套 tool 白名单 + 6 套 permission 规则。
3. **compose 落地口径**：编排层是我们自己的 Python/LangGraph 层，但**复用 MimoCode 的 15 个 compose skill**（brainstorm/plan/execute/tdd/review… 是 markdown 文本，引擎无关，直接喂给 LangGraph Agent）、**借鉴其 compose 设计**（skill 加载、tool registry、permission 人审）。我们不改 MimoCode 源码，是复用 + 借鉴。
4. LangGraph 是内核不是终点——其上自研运行时加固（死循环 / 迭代上限 / 循环检测）与算法侧接入（RLHF / 微调 / 评估），既保长任务鲁棒性，也沉淀组员 LangGraph 高级用法工程能力。


### 6.2 数据流

model→risk 跨组数据流详见 `docs/QuantCode_Design.md`（Compose 流拆解章节）。

### 6.3 Schema 契约

所有 skill 之间通过 Pydantic v2（SoT）+ `model_json_schema()` 导出 JSON Schema 通信。
Schema 改动需要走 PR review（`opencode.jsonc` 中已配 `"schemas/**": "ask"`）。

---

## 7. 里程碑（M1 / M2 / M3，具体日期由 Lead 编排）

> **时间线由 Lead 编排**，不在 PRD 内固化。下表只描述里程碑达成标准。

| 里程碑 | 达成标准 |
|---|---|
| **M1 地基冻结** | 三大模式契约（ComposeTask / BlackboardState / HumanGate）v1 通过；5 套业务 schema v1 通过；6 个 SKILL.md 草案存在；6 人能本地跑 OpenCode fork；`@dedupe_within` 上线 |
| **M2 端到端打通** | 一条 PR → model Compose → risk Compose → CI gate → 验收报告全链路跑通；至少 1 个非 agent 组同学用上 |
| **M3 横向接入** | ≥3 套 Compose 流跑在同一调度 + 验收框架上（risk / fundamental / factor）；投资人 demo 物料齐全（研报 PDF + CI log + 因子迭代数据） |
| **M4 闭环 + 自我进化** | Dream / Distill 上线；MEMORY/RAG 跨会话留存；前端 Compose 视图可用；6 个组全部接入 |

**节奏硬规则**：
- M1 完成前不允许业务 schema 不通过 review 就动工
- 每天必须有可运行产物，不用纯文档替代
- 每周 standup 把里程碑进度对齐到这张表

---

## 8. 团队和分工

分工详见 `docs/QuantCode_Design.md` §9.1。

---

## 9. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| OpenCode 上游升级 break 我们的 plugin | 中 | 中 | 锁定上游版本，CI 跑 smoke test，定期 `git pull upstream dev` |
| MimoCode cherry-pick 代码有隐含依赖 | 中 | 中 | 移植时遇到依赖就手动重写，避免引入小米服务（MiMo Auto / MiMo ASR） |
| 用户不愿意用（adoption 风险） | 高 | 高 | 每个里程碑强制找真实用户 review，拉进 Compose 流试用 |
| Schema 设计不当后期改造大 | 中 | 高 | M1 强制 schema 评审会，三大契约改动需 Lead + 起草人双签 |
| 6 人协作沟通成本爆炸 | 中 | 中 | Compose 视图把所有协作显式化，Memory 留痕，schema 异步评审 |
| 学生时间不稳定 | 高 | 中 | 每个 track 配主副 owner，主病了副可顶 |
| 数据基建依赖卡住 RAG | 中 | 高 | M1 就和基建组确认数据接入方式 |
| dedupe 装饰器没及时上线导致 PR 评论刷屏 | 低 | 中 | 陈镇鸿 Day 1 必须先出装饰器，CI 上线前 mock 不写真实评论 |

---

## 10. 成功指标

### M2（端到端打通）

- 一条 PR → model Compose → risk Compose → CI gate pipeline 跑通
- 一个模型组同事用上并认可输出
- `@dedupe_within` 在真实 GitHub Actions 中验证（同 commit 不重复评论）

### M3（横向接入）

- ≥3 套 Compose 流（risk / fundamental / factor）跑在同一调度 + 验收框架上
- 至少 1 个非 agent 组同事通过 Compose 流成功提交任务
- 投资人 demo 物料齐全（研报 PDF + CI log + 因子迭代数据）
- 一个新因子从 idea 到接入主线，因子组负责人认可

### M4 / 长期

- 6 个组全部接入
- 平均每组提效 > 30%（按节省的人工小时数衡量）
- Distill 自动生成的 skill 数量持续增长
- 监控、降级、性能优化等生产化加固

---

## 附录：术语表与决策日志

术语表和决策日志见 `docs/QuantCode_Design.md` §8（术语表）和 §11（决策日志）。

---

**文档维护**：本 PRD 持续迭代，重大变更需要团队评审。Design 文档（`docs/QuantCode_Design.md`）是工程实现细节的真理源，PRD 描述产品需求与里程碑标准。

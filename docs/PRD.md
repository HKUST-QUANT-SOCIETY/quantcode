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

**核心 skill**：`risk:detect → analyze → schema-gen → ci-gate → feedback`

**输入**：PR diff + `ModelSpec`（模型组 PR 元数据）

**输出**：符合 `schemas/risk-profile.schema.json` 的 `RiskProfile`

**验收标准**：
```python
assert risk_json["max_drawdown"] <= 0.20
assert risk_json["position_limit"] <= 0.30
assert abs(risk_json["correlation_with_existing"]) <= 0.60
assert risk_json["tail_risk_var_99"] is not None
# 越过阈值时自动触发 HumanGate
```

**Owner**：杨欣琳（T2）；统计公式由肖骥超提供

#### 4.1.2 fundamental Compose 流（基本面 + PIT-RAG）

**核心 skill**：`fundamental:brainstorm → fetch → extract → dcf → draft → render → review → publish`

**关键约束**：`pit-rag` 强制 `published_at <= as_of_date`，杜绝 lookahead bias

**输入**：`PITQuery`（query + as_of_date + corpus）
**输出**：`PITResult` → `ResearchSpec` → research.pdf

**验收标准**：
```python
for doc in result["documents"]:
    assert doc["published_at"] <= query["as_of_date"]
# 渲染 PDF 后人工验收：研究员愿意发出去 = 通过（走 HumanGate）
```

**Owner**：用户（Lead，T3a）；PDF 副手 刘炽

#### 4.1.3 factor Compose 流（因子评估）

**核心 skill**：`factor:brainstorm → match-main → gen-schema → execute → autoeval → risk-check → merge-main`

**接入**：HKUST-QUANT-SOCIETY/auto_factor_evaluation

**输出**：符合 `schemas/factor-report.schema.json` 的 `FactorReport`

**验收标准**：
```python
assert abs(report["ic_metrics"]["ic_mean"]) >= 0.03
assert report["ic_metrics"]["ir"] >= 0.5
assert report["turnover"]["monthly"] <= 0.8
assert report["ic_metrics"]["t_stat"] >= 2.0
```

**Owner**：肖骥超（T4）

#### 4.1.4 model Compose 流（模型 / 跨组发起）

**核心 skill**：`model:brainstorm → lit-review → plan → execute → pr-submit → cross-handoff`

**关键**：`model:pr-submit` 自动填风控元数据，`model:cross-handoff` 触发 risk Compose 流

**Owner**：陈镇鸿（T1）；同时实现 `tools/utils/dedupe.py` 装饰器（杨欣琳依赖）

#### 4.1.5 options Compose 流

**核心 skill**：`options:brainstorm → vol-surface → greeks → execute`

**Owner**：刘炽（T3b）

#### 4.1.6 strategy Compose 流

**核心 skill**：`strategy:brainstorm → select → combine → backtest → deploy`

**Owner**：待定（暂未分配）

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

#### 5.3.1 MimoCode 吸收模块盘点（2026-07-03 实际验证）

> **背景**：MimoCode (`vendor/mimo-code/`) 是小米开源的 agent 平台，我们从中 cherry-pick 7 个核心模块代码到 QuantCode，避免重复造轮子。

| 模块 | MimoCode 实际路径 | 功能描述 | QuantCode 实现 | 优先级 | 状态 | 负责人 |
|------|------------------|----------|---------------|--------|------|--------|
| **Memory FTS5** | `packages/opencode/src/memory/` | SQLite FTS5 全文检索 + BM25 排序 + CJK 分词 + reconcile 磁盘同步 | `runner/memory/` (1209 行) | P0 | ✅ Day 2 | 尹一帆 |
| **Workflow 编排** | `packages/opencode/src/workflow/runtime.ts`<br>`packages/opencode/src/workflow/events.ts`<br>`packages/opencode/src/workflow/persistence.ts` | 跨 flow 触发、workflow 持久化、事件系统 | `runner/compose_executor.py` (部分) | P0 | 🔧 Day 3 | 尹一帆 |
| **Task 系统** | `packages/opencode/src/task/task.sql.ts`<br>`packages/opencode/src/task/registry.ts`<br>`packages/opencode/src/task/gate.ts` | 任务树、gate 状态管理、子任务编排 | 待移植 | P1 | 🔲 Week 2 | Lead |
| **Compose 模式** | `packages/opencode/src/skill/compose/bundle.macro.ts`<br>`packages/opencode/src/skill/compose/extract.ts` | SKILL.md 的 Compose 模式声明和提取 | `.opencode/groups/*/skills/*/SKILL.md` (frontmatter) | P0 | 🔧 Day 3 | 陈镇鸿 |
| **Snapshot** | `packages/opencode/src/snapshot/` | context 占用自动 checkpoint | 待移植 | P1 | 🔲 Week 2 | TBD |
| **Session 重建** | `packages/opencode/src/session/` | 从 checkpoint + MEMORY 重组 context | 待移植 | P1 | 🔲 Week 2 | TBD |
| **Subagent 监控** | `packages/opencode/src/agent/` + `packages/opencode/src/task/` | subagent 生命周期追踪、单独 kill | 待移植 | P1 | 🔲 Week 2 | TBD |
| **Dream** 🔍 | （未找到专门模块，可能在 `session/` 或 `agent/` 里） | 扫描 trace 提取知识到 MEMORY.md | 待设计 | P0 原型 | 🔲 Day 4 | 尹一帆 |
| **Distill** 🔍 | （未找到，可能未开源或内部功能） | 识别重复操作打包成 SKILL.md | 待设计 | P2 | 🔲 Week 3+ | TBD |
| **Goal + Judge** 🔍 | （未找到 `/goal` 命令实现） | Goal 设定 + Judge 模型评估 | 待设计 | P2 | 🔲 Week 3+ | TBD |

**图例**：
- ✅ 已完成
- 🔧 进行中
- 🔲 待开始
- 🔍 MimoCode 代码库未找到，需进一步探索或自行设计

**关键发现**（2026-07-03）：
1. ✅ **Memory FTS5** 已完整移植（Day 2），路径验证正确
2. ✅ **Workflow 模块存在**，Day 3 尹一帆的跨 graph 触发可参考 `runtime.ts` + `events.ts`
3. ✅ **Compose 模式**在 MimoCode 里有完整实现，陈镇鸿写 SKILL.md 可参考
4. ❌ **Dream/Distill/Goal** 在 MimoCode 代码库未找到专门模块（可能未开源或分散在其他模块），需自行设计
5. ⚠️ **风控统计不在 MimoCode**：VaR/MaxDD/Sharpe 等量化金融计算是 QuantCode 业务逻辑，MimoCode 是通用 agent 平台不含此类计算

**移植原则**（从 Design §6.4）：
- 优先复用 MimoCode 已验证的工程化能力（Memory/Workflow/Task）
- 遇到依赖小米服务（MiMo Auto/ASR）的部分，手动重写，不引入外部依赖
- 保持 MIT 协议，注明出处
- Python 移植 TypeScript 时，保持接口语义一致，但遵循 Python idiom

### 5.4 安全性

- 敏感配置（API key / 数据库密码）不入库
- `opencode.local.jsonc` 本地覆盖（`.gitignore` 排除）
- 高风险操作（删库、force push、修改 schemas/）permission 设为 deny / ask
- 跨组发邮件 / 写 PR 评论强制走 `@dedupe_within`，防止刷屏

---

## 6. 技术架构

### 6.1 三层架构（详见 Design §3.1）

```
                  ┌────────────────────────┐
                  │       前端层（人）        │
                  │ OpenCode desktop UI fork│
                  │ + Compose 视图 + 任务树  │
                  └───────────┬────────────┘
                              │ HTTP / SSE
                  ┌───────────▼────────────┐
                  │     Agent 引擎层         │
                  │ Layer 1: OpenCode 原生  │
                  │ Layer 2: MimoCode 移植   │
                  │ Layer 3: QuantCode 自建  │
                  │   6 套 Compose 流        │
                  │   idea-router agent      │
                  │   Pydantic Schema 生成器  │
                  └───────────┬────────────┘
                              │
                  ┌───────────▼────────────┐
                  │       集成层             │
                  │ AutoEval · Server A/B   │
                  │ GitHub · ChromaDB · 爬虫 │
                  └────────────────────────┘
```

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

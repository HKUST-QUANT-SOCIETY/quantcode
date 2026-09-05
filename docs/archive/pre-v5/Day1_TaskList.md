# Day 1 任务清单

> **日期**：开发启动日（具体日期由 Lead 编排）
> **总体目标**：5 人能本地跑起 OpenCode fork（俞高磊暂不计入）；v1 Pydantic schema 评审通过（**8 套**：三大契约 + 5 套业务）；至少一个自定义 SKILL.md 被 OpenCode 成功加载并调用；副作用 tool 去重保险栓上线。
> **核心理念**：能 mock 就 mock，先把闭环跑通。今天不追求功能完整，追求**链路打通 + 三大生产模式各有契约**。
> **架构基石**：Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard) + Pattern 5 (Human Gate) + 副作用 tool dedupe 保险栓。详见 `docs/QuantCode_Design.md §3.2`。

---

## 0. 全员公共任务（Day 1 启动前必完成）

| 任务 | 验收 |
|---|---|
| 加入 GitHub 仓库 `HKUST-QUANT-SOCIETY/quantcode` | 能 push 一个空 commit |
| 加入 GitHub 仓库 `HKUST-QUANT-SOCIETY/opencode`（fork） | 同上 |
| 本地 clone 两个仓库 | `git status` 干净 |
| 本地能跑 OpenCode fork（`bun install && bun run dev`） | TUI 起得来，能跟内置 build agent 对话 |
| 试用一遍 Claude Code 工具 | 至少跑通一个 `/plan` + `/execute` 流程 |
| 读完 `docs/QuantCode_Design.md`（**重点 §3.2 三大生产模式**）和 `docs/PRD.md` | 在 standup 时能说出自己 Track 范围 + 对应哪个模式 |
| 配好 LLM API key（Anthropic / OpenAI 任选） | OpenCode 里能正常对话 |

---

## 0.5 Day 0 调研日（Day 1 前一天，每人读一个开源项目，1 小时汇报）

| 组员 | 读什么 | 汇报什么 |
|---|---|---|
| 用户（Lead） | [LangGraph](https://github.com/langchain-ai/langgraph) state machine + checkpoint **设计思路**（不引入运行时） | 我们的 `ComposeTask` 和 `BlackboardState` schema 怎么借鉴 |
| 陈镇鸿 | [Temporal](https://learn.temporal.io/tutorials/ai/durable-ai-agent/) durable execution（只学 checkpoint，不学 event log） | 怎么保证 Pattern 2 的状态恢复正确；同时学习如何写 `@dedupe_within` 装饰器 |
| 杨欣琳 | [barkain/claude-code-workflow-orchestration](https://github.com/barkain/claude-code-workflow-orchestration) | OpenCode 插件机制 + `HumanGate` 设计 |

---

## 1. Day 1 上午：Schema 评审 + 全员对齐

**主持**：用户（Lead）

### 全员 standup（30 分钟）

- 每人 3 分钟：自己 Track 的 Day 1 目标 + 阻塞点 + 需要谁配合
- 同步 Day 0 调研收获
- 确认本周节奏：每日早上 15 分钟 standup，其他时间异步

### Schema 评审会（90 分钟）

由 Lead 主持，全员参与。评审以下 **8 套 Pydantic schema** 草案：

#### 三大模式契约（必须先冻结，所有业务 schema 依赖它）

| Schema | 对应模式 | Owner 起草 | 用途 |
|---|---|---|---|
| `ComposeTask` | Pattern 1 | 用户（Lead） | Orchestrator 任务信封：task_id / status / parent / children / artifacts |
| `BlackboardState` | Pattern 2 | 用户（Lead） | 共享状态层：字段命名、隔离粒度、写入权限 |
| `HumanGate` | Pattern 5 | 杨欣琳 | 人审契约：触发条件、阈值、超时、通知 |

#### 业务 schema（依赖三大契约）

| Schema | Owner 起草 | 用途 |
|---|---|---|
| `ModelSpec` | 陈镇鸿 | model Compose 流的 PR 提交元数据契约 |
| `RiskProfile` | 杨欣琳 | risk Compose 流的输出契约 |
| `FactorSpec` | 肖骥超 | factor Compose 流的输入契约 |
| `ResearchSpec` | 用户（Lead） | fundamental Compose 流的输入契约 |
| `PITQuery` + `PITResult` | 用户（Lead） | pit-rag Compose 流的输入输出契约 |

**评审规则**：

- **三大契约先评审**（前 30 分钟），通过后业务 schema 才有依据
- 必填字段、字段类型、字段含义必须达成共识
- 任何字段后期"不兼容改动"必须重新走 review
- 评审通过后 PR merge 进 `schemas/` 目录

**验收**：8 套 schema 合并入主仓库，每个 Owner 在 PR 描述里写明"我代表 XX Track 接受这版字段"。

---

## 2. Day 1 下午：分头开干

> **暂未分配任务的成员**：俞高磊（后续根据其入组进度补充）

### 2.1 用户（Lead）· T0 地基 + T3a 基本面 / PIT-RAG

| 任务 | 说明 | 验收 |
|---|---|---|
| 完成全局协调 | 接收各 Track 的阻塞点并解决 | 当天无阻塞遗留 |
| 起草 `ComposeTask` schema | Orchestrator 任务信封：task_id / status / parent / children / artifacts | 通过 Schema 评审 |
| 起草 `BlackboardState` schema | 定义 MEMORY / checkpoint / progress 的字段命名规范 | 通过 Schema 评审 |
| 起草 `ResearchSpec` schema | 基本面研报输入契约 | 通过 Schema 评审 |
| 起草 `PITQuery` + `PITResult` schema | 必须强制 `published_at <= as_of_date` | 通过 Schema 评审 |
| 在 OpenCode fork 上验证 plugin 加载 | 写一个 hello-world plugin（输出 "hello"），放 `plugins/` 目录 | OpenCode 启动时能加载到 |
| 验证 Server A SSH 访问 | 用自己的 key 能 SSH 登录、能读到主线代码 | 截图证明 |
| 扒一份中金/华泰研报作为模板基准（与刘炽配合） | 找一份蜜雪冰城或别的成熟研报 | 文件落地到 `templates/typst/reference/` |
| 维护 `docs/PRD.md`，吸收 Day 1 评审结论 | 任何 schema 决策都要落文档 | PR 合并 |

### 2.2 陈镇鸿 · T1 模型 / 跨组发起 + dedupe 装饰器

| 任务 | 说明 | 验收 |
|---|---|---|
| 起草 `ModelSpec` schema | 模型组 PR 提交元数据：模型类型、训练数据范围、超参、依赖算子、风控元数据 | 通过 Schema 评审 |
| **写 `tools/utils/dedupe.py`** | `@dedupe_within(seconds=300, key=...)` 装饰器 + SQLite 去重表 + 单元测试（约 30 行代码） | 装饰器可用，重复调用第二次返回缓存结果 |
| 写 `model:pr-submit` SKILL.md 草案 | 描述模型组提交 PR 时自动填充 ModelSpec 元数据 + 触发风控 Compose 流 | 文件存在 `.opencode/groups/model/skills/model-pr-submit/SKILL.md` |
| 写 `model:lit-review` SKILL.md 草案 | 文献分享结构化（解决会议纪要散乱问题） | 文件存在 `.opencode/groups/model/skills/model-lit-review/SKILL.md` |
| 准备一个真实的模型组样本（自己写或从协会要）| 任意一个简单 ML 模型代码 + 元数据 | `tests/fixtures/sample_model/` 落地 |

### 2.3 杨欣琳 · T2 风控 / 跨组接收

| 任务 | 说明 | 验收 |
|---|---|---|
| 起草 `HumanGate` schema | 触发条件 / 风险阈值 / 超时 / 通知方式 | 通过 Schema 评审 |
| 起草 `RiskProfile` schema | 至少包含 max_drawdown / position_limit / correlation / VaR | 通过 Schema 评审 |
| 拿到一个**真实**模型组 PR 作为测试样本 | 跟陈镇鸿要 / 跟模型组同学要一个最近的 PR | PR URL 写进 `tests/fixtures/sample_pr.md` |
| 写 `risk-gate` SKILL.md 草案 | 描述输入、输出、调用流程，可以先用 mock 数据 | 文件存在 `.opencode/groups/risk/skills/risk-gate/SKILL.md` |
| 验证 GitHub Actions 写 PR 评论 + dedupe | 写一个最简单的 workflow，PR 触发时自动评论 "hello"，**测试同一 commit 5 分钟内不会重复评论**（依赖陈镇鸿的 dedupe.py） | PR 上只看到一条机器人评论 |

### 2.4 刘炽 · T3b 期权 + T3a 副

| 任务 | 说明 | 验收 |
|---|---|---|
| 与 Lead 一起拆中金研报版式 | 封面 / 章节 / 图表 / 脚注 / 免责声明 | 在 `templates/typst/research-layout.md` 写一份版式分析 |
| 搭 Typst 模板骨架 | 不求完整，先有一份能 `typst compile` 通过的 stub | `templates/typst/research-report.typ` 能渲染出空白 PDF |
| 起草期权 Compose 流的 SKILL.md 草案 | options:brainstorm / vol-surface / greeks 三个 stub | 三个 SKILL.md 文件存在 |
| 准备期权数据样本 | 跟期权组要近期的成交数据 | 落地到 `data/sample_options/` |

### 2.5 肖骥超 · T4 因子评估

| 任务 | 说明 | 验收 |
|---|---|---|
| 起草 `FactorSpec` Pydantic schema | name / formula / universe / 算子列表 / 估计耗时 | 通过 Schema 评审 |
| 验证 AutoFactorEvaluation 接口 | 跟 AutoEval 仓库 owner 确认调用方式（HTTP？SDK？） | 在 standup 报告"我能调通 AutoEval" |
| 准备一个测试因子（建议 PB-ROE 组合） | 简单 + 容易跑通 | `tests/fixtures/sample_factor.py` 落地 |
| 写 `factor:autoeval` SKILL.md 草案 | 描述如何把 FactorSpec 喂给 AutoEval 并取回结果 | 文件存在 `.opencode/groups/factor/skills/factor-autoeval/SKILL.md` |
| 协助杨欣琳：提供风控统计指标的计算逻辑 | max_drawdown / VaR 的标准公式 | 在 standup 给杨欣琳一份计算公式清单 |

---

## 3. Day 1 收工前：晚间 standup（30 分钟）

**主持**：用户（Lead）

### 议程

1. **Schema 评审结论**（10 分钟）：**8 套 schema** 是否全部通过？没通过的卡在哪？特别确认三大契约（ComposeTask / BlackboardState / HumanGate）已冻结
2. **各 Track 进展**（每人 3 分钟）：完成了什么、阻塞了什么
3. **Day 2 优先级确认**（5 分钟）：谁先做什么
4. **决策记录**（Lead 当场更新 `docs/QuantCode_Design.md` §11）

### Day 1 整体验收清单

- [ ] 5 人都能本地跑起 OpenCode fork（俞高磊暂不计入）
- [ ] **三大模式契约**（ComposeTask / BlackboardState / HumanGate）v1 评审通过
- [ ] **5 套业务 schema** v1 评审通过（ModelSpec / RiskProfile / FactorSpec / ResearchSpec / PITQuery+PITResult）
- [ ] **6 个 SKILL.md 草案**存在（model:pr-submit / model:lit-review / risk-gate / factor-autoeval / options × 3）
- [ ] AutoFactorEvaluation 接入方式确认
- [ ] Server A SSH 访问验证通过
- [ ] 第一个 hello-world plugin 在 OpenCode 上成功加载
- [ ] **`@dedupe_within` 装饰器实现 + 单元测试通过**（陈镇鸿）
- [ ] **dedupe 在真实 GitHub Actions 中验证**（杨欣琳，同一 commit 不重复评论）
- [ ] 1 个真实模型组样本（陈镇鸿提供）+ 1 个真实模型组 PR（杨欣琳拿到）就位

---

## 4. 风险与依赖

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| **三大契约评审分歧大，开 2 小时还没共识** | 中 | **高（业务 schema 全部阻塞）** | Lead 强制 "v1 先冻结，v2 再改"，给业务 schema 让路 |
| OpenCode 本地跑不起来（Bun / TypeScript 环境问题） | 中 | 中 | 陈镇鸿 / Lead 先跑通，做"踩坑笔记" |
| AutoEval 接口对接卡住（仓库 owner 没空） | 高 | 中 | 肖骥超先 mock 接口，先把 schema 走通 |
| 真实模型组 PR 拿不到 | 中 | 中 | 陈镇鸿用 fixture mock，不阻塞 |
| **dedupe 装饰器没及时上线，前期 PR 评论刷屏** | 低 | 中 | 陈镇鸿 Day 1 上午必须先出装饰器，下午杨欣琳才接 |
| 部分组员 Bun / TypeScript 完全不熟 | 高 | 中 | Lead 安排 1 小时共学时间，陈镇鸿带 |

---

## 5. Day 1 不做什么

明确**今天不碰**的事情，避免范围蔓延：

- ❌ Chroma 向量化样本研报（移到 Day 2，由 Lead 主导）
- ❌ MimoCode 模块完整移植（暂未分配 Owner）
- ❌ 前端 UI 改动（等 Compose 流跑通再说）
- ❌ Dream / Distill（后期）
- ❌ Dog Food 爬虫（后期）
- ❌ 跨组通知中心 UI（后期，逻辑层在 HumanGate 里）
- ❌ 完整的 AutoEval 接入（今天只验证可调通）
- ❌ Server B 集成（Day 1 先打通 Server A）
- ❌ **独立 Verifier agent**（不做 Pattern 3，验收靠 schema + assert）
- ❌ **事件总线 Pub/Sub**（不做 Pattern 4，A→B 直接调用）
- ❌ **完整 Idempotent Retry Chain**（不做 Pattern 6，副作用 tool dedupe 兜底）

---

## 6. 沟通约定

- **同步**：每日早 15 分钟 standup（线上即可）+ 晚 30 分钟收工 standup
- **异步**：所有问题先发 GitHub Issue 或 PR comment，**不在微信群里讨论代码**
- **阻塞**：超过 2 小时卡住 → 立即在 standup 频道 @Lead
- **Schema 改动**：必须走 PR，至少 1 人 review；**三大契约改动需要 Lead + 起草人双签**
- **不直接 push main**：所有改动走 PR

---

**文档维护**：Day 1 结束后，Lead 把"实际完成"和"延期项"更新到这份文档末尾，作为 Day 2 任务输入。

```
## 7. Day 1 实际完成情况（Day 1 结束时由 Lead 填写）

- 实际完成：
- 延期到 Day 2：
- 新发现的问题：
- 决策记录：
```

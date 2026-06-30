# QuantCode 设计文档

> **项目定位 · 架构 · 功能清单**
>
> Owner: Agent Group · HKUST QUANT SOCIETY

---

## 1. 项目定位

### 1.1 一句话定位

> **6 个组登录同一个 agent，每个组进入自己工作流的 Compose 流；流跑完自动接入生产主线。**

### 1.2 核心叙事

> **用 agent 把 5 人 agent 组的产能放大成 30 人投研团队——做大机构嫌人力成本不划算、单一精品店没有广度去做的事：全标的、低相关、高频迭代的策略工厂。**

真正的壁垒是把每个组的隐性工作流**编译成显式的 Compose 流**，把跨组协作从"微信群协商"换成"机器与机器的 Schema 校验"，让 Dream + Distill 持续自我进化。

### 1.3 与其他工具的差异

| 工具 | 定位 | 缺什么 |
|---|---|---|
| Cursor / Copilot | 个人编程助手 | 不懂团队工作流，没有跨组协作 |
| OpenCode / MimoCode | 通用编程 agent | 没有量化业务知识，没有按组分发 |
| Bloomberg / Wind | 数据终端 | 不是 agent，没法跑 idea |
| 自建 dashboard | 数据可视化 | 不能让 idea 自动接入主线 |

**QuantCode 独有**：**Idea → 主线匹配 → 动态 Schema → 程序化验收 → 接入生产**的连续集成范式。

---

## 2. 核心方法论

### 2.1 千组千流

每个组登录 QuantCode 后：

```
用户 SSH key 登录
   ↓
系统识别组身份（基本面 / 因子 / 模型 / 风控 / 策略 / 期权）
   ↓
加载该组的 Compose Pipeline 配置
   ↓
进入该组适配的 primary agent + skill 集合 + Memory
```

要点：

- **统一 UI**（不为每组写不同前端）
- **不同的 Compose 流**（每组的 SKILL.md 不一样）
- **不同的 Memory**（每组 `.quantcode/groups/<group>/MEMORY.md`）
- **不同的默认 tool 集**（基本面组默认有 `extract_financial`，因子组默认有 `autoeval_submit`）

### 2.2 任务拆分 + 确定性契约

- 长任务（10+ 小时）必然遇到上下文 compact，依赖 LLM 长程记忆不可靠
- 解法：
  1. 大任务拆成无状态子任务
  2. 子任务间用 **Pydantic Schema 通信**，不依赖自然语言
  3. 状态外化到 `MEMORY.md` / `checkpoint.md` / `progress.md`
  4. 每个子任务 idempotent（可重启、可重放、结果一致）

### 2.3 程序化验收

量化团队的天然优势：验收标准本就可量化。

- **因子**：IC、IR、换手、衰减（接 AutoFactorEvaluation 服务）
- **策略**：夏普、回撤、容量
- **PR**：测试通过率、风控阈值

**验收标准 = `assert` 语句 + Goal/Judge 模型**，不是"看一眼觉得行"。

### 2.4 把人从 loop 中拿出来

- 其他组不需要学 prompt engineering
- 接口是 YAML spec 或自然语言："我要做什么、输入是什么、目标是什么"
- 提交进 Compose 流，agent 自动编排
- 用户看到的：任务进队列 → 程序化验收报告 → 可复现 artifact

### 2.5 自我进化（Dream + Distill）

- **Dream**：每周扫描本组的会话 trace，把反复出现的知识提取到 `MEMORY.md`，删过期条目
- **Distill**：识别重复的手动操作，把高置信度候选打包成新的 SKILL.md
- 结果：**研究员只管手工跑业务，agent 在后台沉淀**，工作流自动生长

---

## 3. 架构

### 3.1 三层架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      前端层（面向人）                              │
│                                                                  │
│  桌面 App（Electron）+ Web UI                                     │
│  ★ Compose 视图（核心面板）                                       │
│  - Idea 输入 · Schema 卡片 · 任务树 · Subagent 监控               │
│  - Memory 浏览 · Dog Food · 跨组通知 · 会话 Resume                │
└──────────────────────┬───────────────────────────────────────────┘
                       │ HTTP / SSE / WebSocket
┌──────────────────────▼───────────────────────────────────────────┐
│            Agent 引擎层（OpenCode fork + 移植 + 自建）              │
│                                                                  │
│  Layer 1: OpenCode 原生                                          │
│    multi-agent / plugin / tool / 多 provider                     │
│                                                                  │
│  Layer 2: 从 MimoCode 移植                                       │
│    Memory 系统 · 自动 checkpoint · 上下文重建                     │
│    树状任务 · Subagent 编排 · Goal/Judge                          │
│    Compose Mode 的 15 个内置 skill                                │
│    Dream · Distill                                               │
│                                                                  │
│  Layer 3: QuantCode 自建（业务层）                                 │
│    6 套垂直 Compose 流（按组分发）                                 │
│    idea-router agent（核心）                                      │
│    Pydantic 动态 Schema 生成器                                    │
│    10+ 自定义 tool                                                │
└──────────────────────┬───────────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────────┐
│                       集成层（外部系统）                            │
│  AutoFactorEvaluation · Server A SSH · Server B SSH · GitHub     │
│  ChromaDB · 爬虫（GH Trending / Twitter / Reddit）                │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Compose Mode 是产品中枢

Compose 不是辅助工具，是**第三种 primary agent**：

```
build    → 默认编程模式（写代码）
plan     → 只读分析模式
compose  → specs-driven 工作流编排模式（QuantCode 的主战场）
```

每个组的工作流 = 一组 SKILL.md 文件 + 调度规则。Compose 自动按 skill 间的依赖关系编排，跑完一个进入下一个。

### 3.3 仓库结构

```
quantcode/
├── .opencode/
│   ├── config.yaml              # 全局配置 + 组身份识别
│   └── groups/
│       ├── fundamental/
│       │   ├── MEMORY.md
│       │   ├── skills/          # 基本面组的 SKILL.md 文件
│       │   ├── tools/           # 基本面组私有 tool
│       │   └── agent.yaml       # 该组 primary agent 配置
│       ├── factor/
│       ├── model/
│       ├── risk/
│       ├── strategy/
│       └── options/
│
├── plugins/                     # OpenCode plugin（跨组共享）
│   ├── memory-mimo.ts           # 从 MimoCode 移植的 Memory
│   ├── checkpoint.ts            # 自动 checkpoint
│   ├── subagent-mimo.ts         # Subagent 编排
│   ├── goal-judge.ts            # Goal + Judge
│   ├── dream.ts                 # /dream 命令
│   └── distill.ts               # /distill 命令
│
├── tools/                       # 跨组共享 tool
│   ├── autoeval_client.py       # 调 AutoFactorEvaluation
│   ├── server_ssh.py            # SSH 读 Server A/B 主线
│   ├── rag_search.py            # ChromaDB + 时点过滤
│   ├── github_pr.py             # GitHub PR 操作
│   ├── crawl_trending.py        # 爬虫
│   └── extract_financial.py     # 财报结构化
│
├── schemas/                     # Pydantic Schema 库
│   ├── factor.py
│   ├── research.py
│   ├── risk.py
│   └── ...
│
├── desktop/                     # OpenCode desktop fork 的 UI 改动
│   └── ...
│
└── docs/
    ├── QuantCode_Design.md      # 本文档
    ├── PRD.md
    └── 服务器接入.md
```

---

## 4. 功能清单（要实现的）

### 4.1 引擎能力（从 MimoCode 移植）

| 功能 | 描述 |
|---|---|
| **持久化 Memory** | `MEMORY.md` / `checkpoint.md` / `notes.md` / `tasks/<id>/progress.md`，SQLite FTS5 全文索引 |
| **自动 Checkpoint** | context 占用 > 70% 自动 snapshot；> 90% 触发上下文重建 |
| **上下文重建** | 抛弃旧消息，从 checkpoint + MEMORY + 最近 N 条消息重组 working context |
| **预算化注入** | token budget + importance ranking，决定哪些内容进上下文 |
| **树状任务** | T1 / T1.1 / T1.2 层级，与 checkpoint 联动；支持自动编排 + 人工 YAML 编排 |
| **Subagent 编排** | 按需创建、共享上下文、并行、生命周期追踪、可取消、后台执行 |
| **Goal + Judge** | `/goal "完成 X"` 设置停止条件，独立 judge 模型判定是否真的完成 |
| **Compose Mode** | 15 个内置 skill：brainstorm / plan / execute / review / tdd / debug / verify / merge / parallel / subagent / worktree / report / feedback / ask / new-skill |
| **/dream** | 扫描 trace，提取持久知识到 MEMORY.md，删过期条目 |
| **/distill** | 识别重复手动操作，封装成新 SKILL.md / subagent / command |

### 4.2 业务能力（QuantCode 自建）

#### 4.2.1 身份识别与组分发

| 功能 | 描述 |
|---|---|
| **SSH Key 登录** | 用户用 SSH key 登录，复用 Server A/B 现有的 key |
| **组身份解析** | 从 Linux group / GitHub team 推断用户所属组 |
| **Compose 流自动加载** | 进入对应组的 `.opencode/groups/<group>/` 配置 |
| **Memory 隔离** | 每组有独立 MEMORY.md，跨组只看共享部分 |

#### 4.2.2 idea-router（核心 agent）

任何 idea 进入系统后由 idea-router 决定：

| 路由动作 | 触发条件 |
|---|---|
| 进入因子 Compose 流 | idea 涉及因子定义、回测、IC 评估 |
| 进入研报 Compose 流 | idea 涉及公司、行业研究、估值 |
| 进入风控 Compose 流 | idea 涉及 PR 审批、风险评估 |
| 进入跨组 Compose 流 | idea 涉及多组协作 |
| 兜底：通用 Compose | 其他 |

#### 4.2.3 Schema 动态生成

不预设固定 Schema，而是：

1. agent 读 idea 文本
2. agent 读对应组的主线代码
3. LLM 输出一个 Pydantic Schema 类（代码字符串）
4. 前端用 `model_json_schema()` 渲染成卡片

#### 4.2.4 主线匹配（match_main）

- 通过 SSH 读 Server A/B 的主线代码（缓存到本地）
- 用 RAG 找与 idea 相关的主线模块
- 返回兼容性结论：`compatible` / `requires_extension` / `bypass`

#### 4.2.5 跨组协作触发

当 A 组某个 task 完成（agent 检测到），自动：

1. 创建 B 组的待办任务
2. 通知 B 组负责人（通知中心 + 可选邮件）
3. 等 B 组 ack 后传递 artifact
4. 全流程留痕到 `MEMORY.md`

### 4.3 6 套垂直 Compose 流

每套流 = 一组 SKILL.md + 调度规则 + 默认 tool 集 + MEMORY.md。

#### 4.3.1 基本面组（fundamental）

```
fundamental:brainstorm   →   聊清楚研究主题（公司/行业/宏观）
fundamental:fetch         →   拉年报、公告、纪要（含 RAG）
fundamental:extract       →   财报结构化提取（MD&A / 经营讨论 / 风险披露）
fundamental:dcf           →   DCF 估值
fundamental:draft         →   LLM 生成各章节
fundamental:render        →   Typst 渲染 PDF（中金风格）
fundamental:review        →   研究员人工 review
fundamental:publish       →   发邮件 / 上传内部
```

默认 tool：`rag_search` `extract_financial` `dcf_model` `typst_render`

#### 4.3.2 因子组（factor）

```
factor:brainstorm   →   聊清楚要测什么因子
factor:match-main    →   匹配主线代码，提取算子白名单
factor:gen-schema    →   动态生成 FactorSpec Pydantic 类
factor:execute       →   用户填代码 + 跑回测
factor:autoeval      →   调 AutoFactorEvaluation 服务
factor:risk-check    →   风控阈值验收
factor:merge-main    →   PR 自动接入主线
```

默认 tool：`autoeval_submit` `autoeval_query` `read_main_factor` `github_pr`

#### 4.3.3 模型组（model）

```
model:brainstorm    →   聊清楚要做什么模型
model:lit-review     →   文献分享结构化（解决会议纪要散乱问题）
model:plan           →   生成模型设计 spec
model:execute        →   实现 + 训练
model:pr-submit      →   提 PR（自动填风控元数据）
model:cross-handoff  →   触发风控组 Compose 流
```

默认 tool：`rag_search` `github_pr` `paper_extract`

#### 4.3.4 风控组（risk）

```
risk:detect         →   检测到模型组 PR
risk:analyze         →   分析策略代码 + 跑历史回测
risk:schema-gen      →   填充 RiskProfile Schema
risk:ci-gate         →   程序化阈值校验
risk:feedback        →   返回审批结论 + 改进建议
```

默认 tool：`github_pr` `backtest_run` `risk_metrics`

#### 4.3.5 策略组（strategy）

```
strategy:brainstorm  →   聊清楚组合方向
strategy:select       →   从因子池/策略池选标的
strategy:combine      →   组合权重优化
strategy:backtest     →   组合回测
strategy:deploy       →   接入 Server B 主线
```

默认 tool：`read_main_strategy` `portfolio_opt` `backtest_run`

#### 4.3.6 期权组（options）

```
options:brainstorm   →   聊清楚期权策略
options:vol-surface   →   隐波曲面 fitting
options:greeks        →   Greeks 计算
options:execute       →   下单 / 回测
```

默认 tool：`vol_surface` `greeks_calc`

### 4.4 前端功能（Compose 视图为核心）

#### 4.4.1 主视图

```
┌─────────────────────────────────────────────────────────────────┐
│  QuantCode · 因子组（基于 SSH key 自动识别）       [设置] [通知]   │
├──────────┬──────────────────────────────────────┬───────────────┤
│          │                                      │               │
│ 会话列表  │      主对话区 + Compose 视图          │  右侧面板      │
│          │                                      │               │
│ · idea-1 │  User: 我想测一个 PB×ROE 因子        │  当前 Compose │
│ · idea-2 │                                      │  ○━━━●━━━○━○ │
│ + 新会话  │  Agent: 已为你启动 factor 流         │  brain match  │
│          │                                      │  exec eval    │
│          │  [match-main] 检查主线兼容性...      │               │
│          │   ↓ 1 个 subagent 运行中             │  任务树       │
│          │   ✓ 完成：算子全在白名单             │  T1 PB×ROE   │
│          │                                      │  ├─ T1.1 ✓   │
│          │  [gen-schema] 生成 Schema...         │  ├─ T1.2 ●   │
│          │   ┌──────────────────────┐           │  └─ T1.3 ○   │
│          │   │ FactorSpec           │           │               │
│          │   │ formula: callable    │           │  Memory       │
│          │   │ universe: CSI1000    │           │  3 条新增     │
│          │   └──────────────────────┘           │               │
│          │   [复制] [改 Schema] [继续]          │  Subagent     │
│          │                                      │  ● rag-search │
│          │  ┌─输入框──────────────────┐         │  ● autoeval   │
│          │  │                         │         │               │
│          │  └─────────────────────────┘         │               │
└──────────┴──────────────────────────────────────┴───────────────┘
```

#### 4.4.2 关键面板

| 面板 | 功能 |
|---|---|
| **Compose 视图** | 当前 Compose 流走到哪一步、卡在哪、等什么 |
| **任务树** | T1/T1.1/T1.2 层级，可点击查看每个节点的 progress.md |
| **Subagent 监控** | 实时显示并行 subagent 的状态、log、单独 kill |
| **Schema 卡片** | agent 返回的 Pydantic schema 结构化展示，可一键导出 |
| **Memory 浏览器** | 查看 MEMORY.md / checkpoint.md / tasks/*.md |
| **Idea 输入区** | 文本框 + 文件拖拽 + 代码粘贴 |
| **会话历史 + Resume** | 解决 Cursor 卡死丢上下文，任意会话从任意 checkpoint 恢复 |
| **跨组通知中心** | "模型组 PR 等你审批" / "因子评估完成" |
| **Dog Food 面板** | 每周自动爬取的 GitHub Trending / Twitter / Reddit 量化内容 |
| **设置 / Provider** | LLM API key / 模型选择 |

#### 4.4.3 Compose 编排能力

- **自动编排**：用户提 idea，agent 自动按 SKILL.md 依赖关系跑
- **人工编排**：YAML 编辑器 + 拖拽预览，保存为 `.compose-pipeline.yaml`
- **人工干预**：任何 skill 节点可暂停、可手动改 Schema、可跳过

### 4.5 Memory + RAG（跨组共享 + 组内私有）

- **Project Memory**：`MEMORY.md` 项目级长期知识
- **Group Memory**：`.opencode/groups/<group>/MEMORY.md` 组内私有
- **Session Checkpoint**：每个 session 自己的 checkpoint.md
- **Task Progress**：每个 task 自己的 progress.md
- **向量库**：ChromaDB 存研报、主线代码 chunks、历史 session 摘要
- **Point-in-time**：所有文档带 `published_at`，检索时过滤 lookahead bias

### 4.6 Dog Food 模块

- 每周一自动跑爬虫：
  - GitHub Trending（Python / TypeScript 量化相关）
  - Twitter（关键账号 list）
  - Reddit（r/quant、r/algotrading 等）
- 用 Firecrawl / Jina Reader（免 API key）
- 落地 markdown，前端 Dog Food 面板展示
- 每周三 Agent 组 standup 时讨论

### 4.7 跨组协作自动化

| 触发 | 动作 |
|---|---|
| 模型组 PR 提交 | 自动触发 risk Compose 流，10 分钟内给反馈 |
| 因子组完成 AutoEval | 自动通知策略组"有新因子可用" |
| 基本面组完成研报 | 自动通知策略组 + 风控组 review |
| 基建组数据 schema 变更 | 自动通知因子组检查算子白名单 |

---

## 5. 集成与依赖

### 5.1 OpenCode 关系

- Fork：`HKUST-QUANT-SOCIETY/opencode`（来自 `anomalyco/opencode`）
- 改动：HTTP API 加 endpoint、Desktop UI 加面板
- 同步：定期 `git pull upstream dev`
- 业务代码全部在 `HKUST-QUANT-SOCIETY/quantcode`，通过 plugin / tool / skill 接入

### 5.2 MimoCode 关系

- 不依赖 MimoCode 运行时
- Cherry-pick 5-6 个模块代码到我们 fork（Memory / Checkpoint / Task / Subagent / Goal / Dream-Distill）
- 移除 MimoCode 私有依赖（MiMo Auto / MiMo ASR）

### 5.3 服务器集成

| 服务器 | 角色 | 接入方式 |
|---|---|---|
| Server A | 数据存储 + 因子评估 + 基建 | SSH 读主线 + HTTP 调 AutoFactorEvaluation |
| Server B | Agent / 期权 / Sentinel | SSH 读主线 + 部署 QuantCode 服务端 |

### 5.4 外部仓库依赖

| 仓库 | 用途 |
|---|---|
| `HKUST-QUANT-SOCIETY/auto_factor_evaluation` | 因子自动评估，被 `factor:autoeval` skill 调用 |
| `HKUST-QUANT-SOCIETY/fundamental-agent` | 年报爬取，被 `fundamental:fetch` skill 复用 |
| `HKUST-QUANT-SOCIETY/quant-research-fundamentals` | 基本面研究主仓 |
| 各组 `infra-*` 个人仓 | 用户身份识别参考 |

### 5.5 技术栈

| 类别 | 选型 |
|---|---|
| Agent 引擎语言 | TypeScript (OpenCode 原生) + Python (业务 tool) |
| 桌面框架 | Electron (OpenCode `packages/desktop`) |
| Web 框架 | SolidJS + Vite + TailwindCSS (OpenCode 原生) |
| Schema 系统 | Pydantic v2 |
| 数据库 | SQLite (会话 + Memory FTS5) + ChromaDB (向量) |
| HTTP | Hono (OpenCode) + FastAPI (业务后端) |
| 通信 | HTTP + SSE + WebSocket |
| 编排 | OpenCode Compose Mode（不引入 LangGraph） |

---

## 6. 验收标准与成功指标

### 6.1 工程验收

- 每个 Compose 流端到端可跑（一个真实 idea 进，一个 artifact 出）
- 每个 skill 通过 `compose:verify` 自动验收
- 跨组流程 PR 自动审批延迟 < 10 分钟
- 长任务（10h+）context 不丢失，可断点续跑

### 6.2 业务验收

- 一个 PR 走完全流程，**风控组认可输出**
- 一份 agent 生成的研报，**研究员愿意发出去**
- 一个新因子从 idea 到接入主线，**因子组负责人认可**
- 至少 1 个非 agent 组同事通过 YAML spec 成功提交一个任务

### 6.3 长期指标

- 4-6 个组全部接入
- 平均每组提效 > 30%（按节省的人工小时数衡量）
- Distill 自动生成的 skill 数量持续增长
- 投资人 pitch 物料齐全（研报 PDF + 风控 CI log + 因子迭代数据）

---

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| OpenCode 上游升级 break 我们的 plugin | 锁定上游版本，CI 跑 smoke test |
| MimoCode 移植代码有隐含依赖 | 移植时遇到依赖就手动重写，避免引入小米服务 |
| 用户不愿意用（adoption 风险） | 每个 sprint 强制找一个真实用户 review |
| Schema 设计不当后期改造大 | 用 Pydantic 动态生成，不写死 |
| 跨组沟通成本爆炸 | Compose 视图把所有协作显式化，Memory 留痕 |
| 学生时间不稳定 | 每个 track 双 owner，主副互备 |
| 数据基建依赖卡住 RAG | 提前和基建组确认数据接入方式 |

---

## 8. 附录

### 8.1 术语表

- **Compose**：OpenCode 的第三种 primary agent，specs-driven 工作流编排模式
- **SKILL.md**：一个 Markdown 文件描述一个能力，agent 自动调用
- **Subagent**：主 agent 动态创建的子任务执行者，共享上下文
- **Schema**：Pydantic 类，skill 之间通信的强类型契约
- **PIT**：Point-in-Time，时点正确性
- **Lookahead bias**：用了未来才能看到的信息，量化研究的大忌
- **AutoEval**：HKUST-QUANT-SOCIETY 的 AutoFactorEvaluation 服务
- **Dream / Distill**：MimoCode 的自我进化命令

### 8.2 角色

| 角色 | 职责 |
|---|---|
| **Lead** | 项目方向、PRD 维护、跨 track 协调、对外沟通 |
| **T0 / 地基** | OpenCode fork 维护、MimoCode 移植、CI/部署 |
| **T1 / 因子** | factor Compose 流 + AutoEval 接入 |
| **T2 / RAG + 研报** | RAG 引擎 + fundamental Compose 流 |
| **T3 / 模型 + 跨组** | model Compose 流 + 跨组协作引擎 |
| **T4 / 前端** | Compose 视图 + 任务树 + Subagent 监控 |

具体人员分配见 PRD。

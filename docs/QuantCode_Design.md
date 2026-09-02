# QuantCode 设计文档

> **项目定位 · 架构 · 功能清单**
>
> Owner: Agent Group · HKUST QUANT SOCIETY
> **版本**：v2（2026-09-01 功能定版对齐，依据与各组长的定版讨论）
> **修订说明**：产品口径唯一事实源 = `specs/FUNCTIONAL_SPEC.md` v0.2.1；本文 v1 章节保留作工程实现参考，与定版冲突处已就地标注。v2 四大变更：① **平台红线——QuantCode 不做业务层面的东西**（strategy/options/fundamental 业务流水线归组自研，引擎代码降级组内工具）；② **HumanGate 收窄为写操作门禁**（merge / SSH 生产写 / 跨组资源 / 预算四类触发点，产出与代码不 gate）；③ **"模型 PR"场景取消**（模型走 COS 传 PKL，代码 PR 由 GitHub Actions Multi-Agent Review 承接）；④ **新增四大平台支柱**：P-07 组织资产蒸馏（最大复用）、P-08 Admin 中枢、P-09 /deploy 黑盒部署、P-10 方案先行工作流（先方案后代码 + 一致性判定）。

---

## 1. 项目定位

### 1.1 一句话定位

> **v2 定版**：QuantCode 是研究面的 **Agent 平台与组织能力中枢**（不是业务系统）——6 个组登录同一个 agent，各走各的 Compose 流；平台负责能力蒸馏（最大复用，覆盖不全先问人）、写操作门禁、跨组语义查询与部署适配。**业务层面的策略/回测/组合/期权产品归各组自研与报告平台（可并入对外产品 2）。**

> v1 表述（历史）：6 个组登录同一个 agent，每个组进入自己工作流的 Compose 流；流跑完自动接入生产主线。

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

### 3.1 三层架构（控制平面 / 编排平面 / 执行平面）

QuantCode 采用**语言边界即职责边界**的三层设计：接入与交互层用 TypeScript（复用 OpenCode 生态），核心推理编排层用 Python（LangGraph 有状态图 + 自研运行时加固），两层通过 HTTP API 契约解耦。工具执行层同为 Python，作为编排层可调度的能力池。

```
┌──────────────────────────────────────────────────────────────────┐
│  控制平面 · Control Plane（TypeScript / OpenCode fork）            │
│                                                                  │
│  职责：身份与会话、意图分派、可视化、轻量编排                       │
│  - SSH key ⟶ 组身份长期绑定（会话内不可变）                       │
│  - Idea 文本 ⟶ 执行模式分派（compose / plan / build）             │
│  - Compose 视图：DAG 实时状态 · Schema 卡片 · 任务树 · HumanGate  │
│  - Memory 浏览 · 跨组通知 · 会话 Resume                          │
│  - 轻量编排：仅编排 API 调用与 UI 状态，不承载核心推理            │
└──────────────────────┬───────────────────────────────────────────┘
                       │ HTTP API（无状态请求 / SSE 状态流）
                       │ 语言与进程边界 —— 契约化解耦
┌──────────────────────▼───────────────────────────────────────────┐
│  编排平面 · Orchestration Plane（Python / LangGraph + 自研运行时） │
│                                                                  │
│  ★ 核心推理编排的唯一归属，Node.js 不参与                         │
│                                                                  │
│  运行时内核（基于 LangGraph ReAct Agent）                        │
│    ReAct 循环：LLM 推理→调 tool→观察→再推理（Agent 自主决策）    │
│    Tool Registry · Permission(allow/deny/ask) 人审               │
│    SqliteSaver checkpoint · interrupt/resume                     │
│                                                                  │
│  复用 MimoCode 的 15 个 compose skill（markdown）                │
│    brainstorm / plan / execute / tdd / review / debug ...       │
│    引擎无关的工作流知识，作为 prompt/context 喂给 Agent          │
│                                                                  │
│  自研运行时加固（MimoCode 有基础版，我们做更细）                  │
│    死循环检测 · 迭代步数上限 · 状态指纹循环检测                    │
│    RLHF / 微调 / 评估的算法侧接入点                               │
│                                                                  │
│  平台服务（Day 2 已建）                                           │
│    Memory FTS5 + 5-scope 权限 · Blackboard 共享状态               │
│    内部模型服务与资源权限（COS / 各组服务器）· 监控告警           │
└──────────────────────┬───────────────────────────────────────────┘
                       │ 进程内调用（编排平面调度能力池）
┌──────────────────────▼───────────────────────────────────────────┐
│  执行平面 · Execution Plane（Python tools/ + 外部系统）            │
│                                                                  │
│  职责：无状态的副作用执行，不参与决策                              │
│  AutoFactorEvaluation · Server A/B SSH · COS · GitHub PR         │
│  ChromaDB 时点检索 · 爬虫 · RLHF 训练数据收集                      │
└──────────────────────────────────────────────────────────────────┘
```

**三条架构铁律**：

1. **核心推理编排只在编排平面（Python/LangGraph）**。TypeScript 控制平面只做接入、可视化，不承载任何推理调度逻辑。
2. **控制平面与编排平面职责分离**，可独立演进——当前阶段团队集中于编排平面，控制平面复用 OpenCode 现有能力（session/tool/memory），互不阻塞。
3. **LangGraph 是内核不是终点**。我们在其 ReAct 循环之上做自研运行时加固（死循环 / 迭代上限 / 循环检测）、复用 MimoCode 的 15 个 compose skill、接入算法侧能力（RLHF / 微调 / 评估），既保证长任务鲁棒性，也沉淀组员在 LangGraph Python 高级用法上的工程能力。

### 3.2 三大生产模式（架构基石）

QuantCode 采用业界 2026 年生产生存率最高的最小组合（Pattern 1 + 2 + 5），加一颗轻量幂等保险栓。这三个模式是所有 Compose 流的**架构基石**，所有功能都必须落到这三个模式之一。

```
┌─────────────────────────────────────────────────────────────────┐
│  Pattern 1: Orchestrator-Worker（中心调度 + 工人 agent）         │
│  ─────────────────────────────────────────────                  │
│  Compose Mode = 中心 Orchestrator                               │
│  SKILL.md / Subagent = Workers（工人 agent）                     │
│  6 套 vertical Compose 流（按组分发）                            │
│                                                                 │
│  规则:                                                          │
│  - Workers 只向 Orchestrator 汇报，不互相直接通信               │
│  - Orchestrator 负责任务拆分、调度、合并结果                     │
│  - 路由可预测，日志线索清晰                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│  Pattern 2: Stateful Blackboard（共享状态层）                    │
│  ─────────────────────────────────────────────                  │
│  agent 不通过对话传递数据，全部读写共享状态层。                  │
│                                                                 │
│  存储:                                                          │
│  - 项目级 MEMORY.md（跨会话长期知识）                            │
│  - 组级 groups/<group>/MEMORY.md（组内私有）                     │
│  - 会话级 checkpoint.md（自动 snapshot）                         │
│  - 任务级 tasks/<id>/progress.md                                 │
│  - SQLite FTS5 全文索引                                          │
│                                                                 │
│  契约: BlackboardState schema 规定哪些字段进共享、命名规范        │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│  Pattern 5: Human-in-the-Loop Gate（人审断路器）                 │
│  ─────────────────────────────────────────────                  │
│  任何跨越风险阈值的动作自动暂停，等人审批后才继续。               │
│                                                                 │
│  触发场景:                                                       │
│  - 写主线 PR / 修改主线代码                                      │
│  - 发邮件 / Slack 通知给协会外部                                 │
│  - 调用付费 API 超过预算阈值                                     │
│  - LLM 自评信心 < 阈值                                           │
│                                                                 │
│  契约: HumanGate schema 规定触发条件、阈值、超时、通知方式        │
│  实现: 复用 OpenCode permission 系统 + 业务阈值                  │
└─────────────────────────────────────────────────────────────────┘
                              +
┌─────────────────────────────────────────────────────────────────┐
│  保险栓: 副作用 tool 去重（@dedupe_within）                       │
│  ─────────────────────────────────────────────                  │
│  对外副作用 tool（GitHub 评论、邮件、PR 创建）强制 5 分钟内去重。 │
│  实现: 装饰器 + SQLite 一张小表，30 行代码。                     │
│                                                                 │
│  覆盖范围:                                                       │
│  - github_pr_comment / github_pr_create                         │
│  - send_email / slack_notify / cross_team_notify                │
│  不覆盖（天然幂等）:                                              │
│  - AutoEval / RAG / 文件覆盖写                                   │
└─────────────────────────────────────────────────────────────────┘
```

> **v2 收窄（FUNCTIONAL_SPEC F-03）**：Pattern 5 的机械（interrupt/resume）保留，触发面收敛为**四类写操作**：① merge_to_main 主线入库；② SSH 写生产环境（普通 SSH 读/开发环境写不 gate，push 自动操作不 gate）；③ 跨组数据/资源访问；④ token/预算超限。研究面产出与代码变更**不再触发 Gate**（产出由报告平台承接、代码由 CI/PR 承接）；RiskThresholds 越限 → acceptance verdict 直接 fail。避免"每个动作都批准"把用户逼成完全访问的 Z code 式退化。

#### 为什么不做另外三个模式

业界另有三个模式（Supervisor/Verifier、Event-Driven Pub/Sub、Idempotent Retry Chains），我们选择不做：

| 不做的模式 | 理由 | 替代方案 |
|---|---|---|
| **Supervisor/Verifier**（独立审核 agent） | 量化验收本就量化（IC/IR/夏普），`assert` + Goal/Judge 已够 | 验收靠 schema + assert + 半程序化场景走 Pattern 5 |
| **Event-Driven Pub/Sub**（事件总线） | 6 人小团队 A→B 直接调用足够 | 跨组直接调用，扩展到 10 人后再加 |
| **Idempotent Retry Chains**（完整哈希链） | 多数操作天然幂等，完整实现成本过高 | 副作用 tool 用 @dedupe_within 兜底 |

---

### 3.3 Compose 流：编排平面的核心产品

Compose 不是辅助工具，是 QuantCode 的**主战场**——每个组的工作流（fundamental / factor / model / risk / strategy / options）均表达为一条 **Compose 流**，本质是编排平面（Python/LangGraph）的一个 **ReAct Agent 实例**。

控制平面（TS 前端）提供三种执行模式的入口：

```
build    → 默认编程模式（直接生成/修改代码）
plan     → 只读分析模式（不落地代码）
compose  → 工作流编排模式（QuantCode 主战场，调用编排平面 API）
```

用户选择 `compose` 时，控制平面通过 HTTP API 调起编排平面，传入组标识 + 流名称 + idea 文本。编排平面加载对应流的配置（system prompt + tool 白名单 + permission 规则），启动 ReAct 循环：**Agent 自己推理下一步该调哪个 tool**，执行后观察结果，再推理下一步，循环往复直到任务完成。全程 checkpoint，遇 permission 规则为 `ask` 的 tool 时 interrupt 等人审。

**关键点**：6 套 Compose 流 = **同一个 ReAct 循环 + 6 套不同配置**。流程不是预定义的 DAG，而是 Agent 在运行时推理产生。这是从 OpenCode 调研学到的核心设计——解耦和自主决策的根本。控制平面只负责触发调用与可视化 Agent 当前状态。这是 §3.1 第一条铁律（核心推理编排只在编排平面）的直接体现。

---

### 3.4 仓库结构

> **说明**：编排/引擎实现全部在 Python（`runner/`），不是 TS plugin。控制平面（TS）复用 OpenCode fork，通过 MCP 调 Python。以下为**实际落地布局**（2026-07-10 校准，替换早期 TS plugin 蓝图）。

```
quantcode/                       # 仓库根（Python 编排/执行 + 配置 + 文档）
├── .opencode/
│   ├── config.yaml / opencode.jsonc  # 全局配置 + 6 组 MCP server + permission
│   └── groups/                  # 每组：skills/（SKILL.md）+ tool_allowlist.yaml
│       ├── fundamental/  factor/  model/  risk/  strategy/  options/
│
├── runner/                      # ★ 编排平面（Python / LangGraph）
│   ├── agent_engine.py          # AgentRunner：自搭 StateGraph ReAct 引擎
│   ├── agent_nodes.py           # llm/tool/rlhf 节点 + 路由边 + truncate 节点
│   ├── agent_mcp_tool.py        # run_agent MCP 入口（start/resume 两阶段）
│   ├── langgraph_base.py        # StateGraph 工厂 + SqliteSaver checkpointer
│   ├── compose_executor.py      # 线性 flow 的 FLOW_REGISTRY 执行入口
│   ├── human_gate.py            # 确定性 HumanGate interrupt/resume + gate payload
│   ├── acceptance.py            # 程序化验收 runner（阈值检查）
│   ├── schema_validator.py      # JSON Schema 校验
│   ├── risk_agent.py            # risk 组 ReAct 装配
│   ├── memory/                  # Memory FTS5（service/fts/query/reconcile/paths）
│   ├── routing/                 # 路由函数 + 死循环/指纹加固 + rlhf_logger
│   └── blackboard.py            # Blackboard（PROJECT/GROUP scope 跨组共享）
│
├── flows/                       # 线性 Compose 流（预定义 StateGraph）
│   ├── factor_autoeval.py       # factor:autoeval
│   └── risk_gate.py             # risk:gate
│
├── tools/                       # ★ 执行平面（Python tool，按组）
│   ├── registry.py              # ToolDef + ToolRegistry + 按组过滤
│   ├── loop_detector.py         # 死循环检测
│   ├── common/                  # request_human_review / mark_task_done
│   ├── utils/dedupe.py          # @dedupe_within 副作用去重
│   ├── model/  risk/  factor/  fundamental/  strategy/  options/  # 各组 tool
│   └── skills/loader.py         # SKILL.md → system prompt（含 vendored meta-skill）
│
├── schemas/                     # Pydantic Schema 库（factor/risk/model/research/...）
├── dream/                       # dream_prototype.py（Distill：Day5 新增 distill_prototype.py）
├── quantcode/                   # mcp_server.py（MCP stdio JSON-RPC server 入口）
├── tests/                       # 全量测试（~48 文件）
├── vendor/                      # （v2：mimo-code 副本已移除；设计参考见 docs/mimocode-reference/）
└── docs/                        # PRD / QuantCode_Design / Architecture_Spec / DayN_TaskList
```

> 控制平面（OpenCode fork 的 desktop/UI 改动）在**独立仓库** `HKUST-QUANT-SOCIETY/opencode`（本机 `../opencode`），不在本仓库。

---

## 4. 功能清单（要实现的）

### 4.1 引擎能力（从 MimoCode 移植）

参考实现：`docs/mimocode-reference/memory/`（461 行 TypeScript，MIT license，已入库）。

| 功能 | 描述 | 优先级 |
|---|---|---|
| **Memory FTS5** | SQLite FTS5 表 + BM25 排序 + CJK 支持 + reconcile 机制（磁盘 ↔ 索引双向同步）。QuantCode 扩展：加 GROUP scope + GROUP 隔离权限 | **P0（Day 2）** |
| **树状任务** | T1 / T1.1 / T1.2 层级，parent/children，与 checkpoint 联动 | **P0（已完成）** ComposeTask schema 已支持 |
| **自动 Checkpoint** | LangGraph SqliteSaver + context 占用 > 70% 自动 snapshot | **P0（Day 3）** |
| **/dream 原型** | 扫描 checkpoints.db 的 execution trace，用 LLM 提取重复 pattern，写入 memory type | **P0（Day 4）** |
| **上下文重建** | context > 90% 抛弃旧消息，从 checkpoint + MEMORY + 最近 N 条重组 | P1（Week 2） |
| **Subagent 监控** | LangGraph subgraph 已可调用；补生命周期追踪、UI 监控、单独 kill | P1（Week 2） |
| **/distill 完整实现** | 识别重复操作 → 候选新 SKILL.md 草案 | P1（Week 2） |
| **预算化注入** | token budget + importance ranking 决定哪些内容进上下文 | P2（Week 3+） |
| **Goal + Judge** | `/goal` 命令 + 独立 judge 模型（Haiku）评估 | P2（Week 3+） |
| **Compose Mode 15 skill** | 我们只做 6 条业务 Compose 流，不照搬 MimoCode 的通用 skill | 不做 |

### 4.2 业务能力（QuantCode 自建）

#### 4.2.0 三大模式的契约 schema

每个生产模式对应一套 Pydantic schema，所有功能必须落到这三个契约之一。

| Schema | 对应模式 | 用途 | Owner |
|---|---|---|---|
| `ComposeTask` | Pattern 1 | Orchestrator 任务信封：task_id / status / parent / children / artifacts | 用户（Lead） |
| `BlackboardState` | Pattern 2 | 共享状态层契约：字段命名、隔离粒度（项目/组/会话/任务）、写入权限 | 用户（Lead） |
| `HumanGate` | Pattern 5 | 人审契约：触发条件、风险阈值、超时策略、通知方式、补救路径 | 杨欣琳 |

#### 4.2.0.1 副作用 tool 去重保险栓

任何"对外发送 / 创建 / 修改"的 tool 必须用 `@dedupe_within` 装饰：

```python
from quantcode.tools.utils import dedupe_within

@dedupe_within(seconds=300, key=lambda commit_sha, msg: f"{commit_sha}:{hash(msg)}")
def github_pr_comment(commit_sha: str, msg: str):
    ...
```

- 实现：装饰器 + SQLite 一张小表，约 30 行代码
- 覆盖：`github_pr_*` / `send_email` / `slack_notify` / `cross_team_notify`
- 不覆盖（天然幂等）：`autoeval_*` / `rag_*` / 文件覆盖写

#### 4.2.1 身份识别与组分发

| 功能 | 描述 |
|---|---|
| **SSH Key 登录** | 用户用 SSH key 登录，复用 Server A/B 现有的 key |
| **组身份解析** | SSH 指纹 → 组映射（`quantcode/identity.py`，fail-closed；本地 dev 逃生门 `QUANTCODE_ALLOW_UNAUTH=1`） |
| **Compose 流自动加载** | 进入对应组的 `.opencode/groups/<group>/` 配置 |
| **Memory 隔离** | 每组有独立 MEMORY.md，跨组只看共享部分 |

#### 4.2.2 组绑定与模式分派（控制平面）

组身份由 **SSH key 长期绑定**决定，不随 idea 文本动态路由——登录即确定用户所属组，会话内不可变，对应组的 Compose 流配置随之加载。

Idea 文本的作用是**在既定流内分派执行模式**，而非选择进入哪条流：

| 分派动作 | 触发条件 |
|---|---|
| `compose` 模式 | idea 描述多步骤工作流，需按 skill 依赖编排 |
| `plan` 模式 | idea 为只读分析、调研，不落地代码 |
| `build` 模式 | idea 为明确的代码实现 / 修改 |
| 新 idea 入流 | idea 为待验证的研究想法，走 Compose 流的 brainstorm 起点 |

**要点**：流由组（SSH key）决定，模式由 idea 决定。跨组协作通过 Blackboard PROJECT scope 达成，不改变组身份。


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

每套流 = **一个 ReAct Agent 配置**（system prompt + tool 白名单 + permission 规则 + MEMORY.md）。Agent 自己推理执行顺序，不预定义流程图。

> **v2 定位**：6 条流的产品口径以 FUNCTIONAL_SPEC v0.2.1 为准——risk/model（PR 链）降级 CI 基建维护模式；strategy/options/fundamental 业务归组自研、QuantCode 侧保留组内工具适配层；factor 为主战场（外部评估器注册 + 部署适配）。下文各节的 System Prompt / Permission 为 v1 参考。

#### 4.3.1 基本面组（fundamental）

**System Prompt 核心**：围绕公司/行业/宏观问题，检索语料（时点安全），提取财报，做估值，产出研报 PDF，走人工验收。

**Available Tools**：`pit_rag_search` `extract_financial` `dcf_valuation` `render_report` `request_human_review`

**Permission 规则**：`render_report` → ask（PDF 需人审），`publish` → ask（发邮件需审批）

#### 4.3.2 因子组（factor）

**System Prompt 核心**：接到因子 idea，匹配主线因子库，生成因子定义 schema，调用 AutoEval 回测，产出 IC/IR/换手率报告，指标达标建议合入主线。

**Available Tools**：`match_main` `gen_factor_schema` `run_autoeval` `check_factor_gate` `merge_to_main`

**Permission 规则**：`merge_to_main` → ask（合入主线需审批）

#### 4.3.3 模型组（model）

**System Prompt 核心**：围绕模型 idea，做文献综述，生成设计 spec，实现训练，提 PR 时自动填风控元数据，触发风控组 Agent（跨组 handoff）。

**Available Tools**：`read_pr` `extract_metadata` `generate_model_spec` `write_blackboard` `trigger_risk_flow`

**Permission 规则**：`trigger_risk_flow` → allow（跨组协作自动触发）

#### 4.3.4 风控组（risk）

**System Prompt 核心**：读取 model 组提交的元数据（Blackboard），调用风控计算，生成 RiskProfile，最终把分析结果写回 PR。**v2**：VaR 超阈值 → verdict 直接 fail 写入报告（产出门禁内化于评估流程，不触发 HumanGate，见 F-03）。

**Available Tools**：`read_blackboard` `calc_risk` `generate_risk_profile` `check_gate` `write_pr_comment`

**Permission 规则**：`check_gate` 为纯判定（无 ask）；**v2** 起仅写操作类 tool（如 merge_to_main）挂 ask。

#### 4.3.5 策略组（strategy）

**System Prompt 核心**：从因子池/策略池筛选标的，组合权重优化，回测组合表现，达标后建议部署到生产主线。

**Available Tools**：`select_signals` `combine_signals` `run_strategy_backtest` `deploy_strategy`

**Permission 规则**：`deploy_strategy` → ask（部署到生产需审批）

#### 4.3.6 期权组（options）

**System Prompt 核心**：围绕期权策略 idea，构建波动率曲面，计算风险敞口（Greeks），执行策略回测。

**Available Tools**：`build_vol_surface` `calc_greeks` `run_options_backtest`

**Permission 规则**：默认 allow（期权回测风险较低）

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

#### Memory System 架构（从 MimoCode 移植 + QuantCode 扩展）

**SQLite FTS5 表结构**（参考 `docs/mimocode-reference/memory/fts.sql.ts`）：

```sql
CREATE TABLE memory_fts (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,
  scope TEXT,        -- global | projects | groups | sessions | tasks
  scope_id TEXT,     -- project_hash | "fundamental" | thread_id | task_uuid
  type TEXT,         -- memory | checkpoint | progress | notes | feedback | project | reference | user
  body TEXT,
  fingerprint TEXT,  -- size-mtime for change detection
  last_indexed_at INTEGER
);
CREATE INDEX memory_fts_scope_idx ON memory_fts(scope, scope_id);
CREATE INDEX memory_fts_type_idx ON memory_fts(type);
CREATE VIRTUAL TABLE memory_fts_search USING fts5(body);
```

**Scope 分层**（QuantCode 5 层 vs MimoCode 3 层）：

| Scope | 路径 | 读权限 | 用途 |
|---|---|---|---|
| `global` | `.quantcode/global/` | 所有人可读 | 全局配置、项目约定 |
| `projects` | `.quantcode/projects/<hash>/` | 所有组可读 | 项目级长期知识（跨组共享） |
| `groups` | `.quantcode/groups/<group>/` | 只有 owner group 可读 | 组内私有知识（**QuantCode 新增**） |
| `sessions` | `.quantcode/sessions/<thread_id>/` | 只有 owner 可读 | 会话级 checkpoint |
| `tasks` | `.quantcode/tasks/<task_uuid>/` | 只有 owner 可读 | 任务级 progress（**QuantCode 新增**） |

> ⚠️ **Memory scope（5 层）≠ Blackboard scope（2 层），两套独立机制，勿混淆**：
> - **Memory**（`runner/memory/`）：上表 5-scope（`global/projects/groups/sessions/tasks`），FTS5 全文检索用，scope 名对应 `MemoryLocator.scope` 字段。
> - **Blackboard**（`runner/blackboard.py`）：只有 `PROJECT`（全组可读）+ `GROUP`（组私有）2-scope，跨组结构化数据 handoff 用（如 model→risk 的 `shared.pending_risk_reviews`）。
> - 两者都做"组隔离"，但 Memory 是知识检索层、Blackboard 是跨组状态传递层，实现和 API 各自独立。

**Type 分类**：

- `memory` - 长期语义知识（手动 + Dream 自动提取）
- `checkpoint` - 会话快照（自动）
- `progress` - 任务进度（自动）
- `notes` - 临时笔记（手动）
- `feedback` / `project` / `reference` / `user` - 元数据

**Reconcile 机制**：

磁盘 .md 文件 ↔ SQLite 索引双向同步：
- LangGraph node 可以直接写 `.quantcode/groups/factor/memory/last-run.md`
- reconcile 扫描文件 fingerprint（size + mtime），变化的自动重新索引
- SQLite 中已删除的文件自动 prune

**Search API**：

```python
memory.search(
  query="PB-ROE因子",
  scope="groups",
  scope_id="factor",
  type="memory",
  limit=5
)
# 返回: [(path, snippet, bm25_score), ...]
# BM25 排序 + 相对 floor (0.15 * top_score) 过滤噪音
# CJK 支持：Unicode regex \p{L}\p{N}_
```

#### RAG 补充

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

> **v2 注**："模型 PR"场景已取消（模型走 COS 传 PKL；代码 PR 风控由既有 GitHub Actions Multi-Agent Review 承接，risk 链降级为 CI 基建维护模式）。跨组协同真痛点由口径统一（F-06 契约遵守检测 + P-07 蒸馏）与进展透明（P-08 Admin 中枢）承接。

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

> **v2.2 更新**：外部组件全量分层、状态标注与 legacy 映射以 `docs/audit/ASSET_INVENTORY.md` v2（组长组件清单为权威）为准；下表为 v1 历史记录。

| 仓库 | 用途 |
|---|---|
| `HKUST-QUANT-SOCIETY/auto_factor_evaluation` | 因子自动评估，被 `factor:autoeval` skill 调用 |
| `HKUST-QUANT-SOCIETY/fundamental-agent` | 年报爬取，被 `fundamental:fetch` skill 复用 |
| `HKUST-QUANT-SOCIETY/quant-research-fundamentals` | 基本面研究主仓 |
| 各组 `infra-*` 个人仓 | 用户身份识别参考 |

### 5.5 技术栈

| 类别 | 选型 |
|---|---|
| 控制平面语言 | TypeScript (OpenCode fork：接入 / 可视化) |
| 编排平面语言 | Python (LangGraph ReAct Agent + 自研运行时加固) |
| 执行平面语言 | Python (业务 tool) |
| 桌面框架 | Electron (OpenCode `packages/desktop`) |
| Web 框架 | SolidJS + Vite + TailwindCSS (OpenCode 原生) |
| Schema 系统 | Pydantic v2 |
| 数据库 | SQLite (会话 + Memory FTS5 + Blackboard + checkpoint) + ChromaDB (向量) |
| HTTP / MCP | OpenCode ↔ Python 编排层通过 MCP (stdio JSON-RPC) 调用；业务后端可选 FastAPI |
| 通信 | MCP (stdio) + SSE 状态流 |
| 编排 | **Python / LangGraph ReAct Agent**（自研 StateGraph + 确定性 HumanGate + 死循环/迭代/指纹加固）；复用 MimoCode 15 个 compose skill（markdown，引擎无关） |

---

## 6. 验收标准与成功指标

### 6.1 工程验收

- 每个 Compose 流端到端可跑（一个真实 idea 进，一个 artifact 出）
- 每个 skill 通过 `compose:verify` 自动验收
- Admin 跨组语义查询 P95 < 15s（P-08）；方案先行首轮方案产出（不含代码）< 5min（P-10）
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

## 8. 附录：术语表

- **Compose**：OpenCode 的第三种 primary agent，specs-driven 工作流编排模式
- **SKILL.md**：一个 Markdown 文件描述一个能力，agent 自动调用
- **Subagent**：主 agent 动态创建的子任务执行者，共享上下文
- **Schema**：Pydantic 类，skill 之间通信的强类型契约
- **PIT**：Point-in-Time，时点正确性
- **Lookahead bias**：用了未来才能看到的信息，量化研究的大忌
- **AutoEval**：HKUST-QUANT-SOCIETY 的 AutoFactorEvaluation 服务
- **Dream / Distill**：MimoCode 的自我进化命令

---

## 9. 团队分工

### 9.1 Track 划分

| Track | 主 Owner | 副 Owner | 范围 |
|---|---|---|---|
| **T0 地基** | 用户（Lead） | — | OpenCode fork 维护、MimoCode 移植、Compose 流脚手架、Schema 引擎、Acceptance Runner、CI/部署、`@dedupe_within` 保险栓 |
| **T1 模型 / 跨组发起** | 陈镇鸿 | 肖骥超统计支持 | model Compose 流：文献结构化、ModelSpec、PR 提交（自动填风控元数据）、触发风控组 |
| **T2 风控 / 跨组接收** | 杨欣琳 | 肖骥超统计支持 | risk Compose 流：PR 审批、RiskProfile、CI gate、HumanGate 人审契约 |
| **T3a 基本面 / 研报 / PIT-RAG** | 用户（Lead） | 刘炽 | fundamental Compose 流、point-in-time RAG、研报 spec、Typst 模板、PDF 验收 |
| **T3b 期权** | 刘炽 | 用户（Lead） | options Compose 流：波动率曲面、Greeks、期权组合风险 |
| **T4 因子评估** | 肖骥超 | 用户（Lead） | factor Compose 流、IC/IR/换手/衰减、对接 AutoEval |
| **T5 前端 / Compose 视图** | 待定 | — | OpenCode desktop UI 改造：Compose 视图、任务树、Subagent 监控 |

> **暂未分配**：俞高磊（后续根据其入组进度补充任务）

### 9.2 Lead 职责

- 项目方向 + PRD/Design 维护
- 跨 track 协调 + schema 评审
- **多做基本面**：研报 spec、fundamental Compose 流验收口径（不只是协调）
- **承担 PIT-RAG**：基本面检索是主要使用方，由 Lead 维护契约
- 三大模式契约把控：ComposeTask + BlackboardState
- T0 基础设施：OpenCode plugin 验证、MimoCode 移植规划
- 对外沟通（投资人 / 协会其他组）

### 9.3 按 Compose 流 swimlane 对应

每个 Owner 对应一条 swimlane，所有 swimlane 最终汇入 QuantCode Platform 的 skill invocation、Python pipelines、schema validation、checkpoint/replay 和 acceptance gate。

| Owner | 对应 Compose 流 | Eraser workflow lane | 主要任务 |
|---|---|---|---|
| 用户（Lead） | fundamental + PIT-RAG + 全局 | Agent Group / Orchestrate + Fundamental Research Group + QuantCode Platform | 冻结产品范围；主持 schema review；定义 ComposeTask / BlackboardState 三大契约；fundamental workflow、RAG-PDF 验收口径；维护 PRD/design；盯 runner、checkpoint/replay 和 demo 串场 |
| 陈镇鸿 | **model** + 跨组发起 | Model Group | 文献结构化、PR 提交（含风控元数据）、触发风控组 Compose 流；写 `@dedupe_within` 装饰器 |
| 杨欣琳 | **risk** + 跨组接收 | Strategy & Risk Group | 实现 PR 风控审批 agent，生成 `risk.json`，接入策略风控阈值，配置 CI gate 写回 PR 评论；起草 HumanGate 人审契约 |
| 刘炽 | options + research-pdf 副 | Fundamental Research Group + Options Group + Artifacts | 实现研报 PDF 渲染和引用整理；期权组 workflow：数据处理、波动率曲面、Greeks、期权组合风险 |
| 肖骥超 | factor | Model Group + Factor Group | 实现 IC/IR/换手/衰减评估，输出 `factor-report.json`；为 risk-gate 提供统计指标支持；辅助 Typst 图表 |

---

## 10. 核心交付物

每个 Compose 流跑通后产出标准化 artifact，命名一致便于横向追踪：

| 交付物 | Owner | 用途 |
|---|---|---|
| `model-spec.json` | 陈镇鸿 | 模型组 PR 提交时的元数据契约 |
| `risk.json` | 杨欣琳 | PR 风控门禁输入 acceptance runner |
| `factor-report.json` | 肖骥超 | 因子组横向比较和验收 |
| `pit-results.json` | 用户（Lead） | 基本面组时点检索结果 |
| `research-spec.yaml` | 用户（Lead） | 基本面研报任务输入和验收口径 |
| `research.pdf` | 用户（Lead） / 刘炽 | 投资人 demo 和基本面研报样例 |
| `options-risk.json` | 刘炽 | 期权组 Greeks、波动率曲面和组合风险 demo |
| `ci-log.txt` | 杨欣琳 / 用户（Lead） | 证明 risk-gate 可 24h 自动执行 |
| `acceptance-report.json` | 用户（Lead） | 所有 Compose 流的 pass/fail 汇总 |
| `MEMORY.md` per group | 该组 Owner | Dream/Distill 沉淀的组内长期知识 |
| `handoff.md` | 用户（Lead） / 全员 | 阶段性交接与复盘 |

---

## 11. 决策日志

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-06-23 | 载体层不自建，做加法 | 避免被上游变更和合并冲突拖死 |
| 2026-06-27 | 仓库名 `quantcode`（小写） | `QuantumCode` 是旧拼写错误 |
| 2026-06-27 | 团队按 6 人 agent 组规划 | PRD 已确认当前 agent 组人数 |
| 2026-06-30 | Fork OpenCode（不是 MimoCode） | OpenCode 干净，MimoCode 的好特性可 cherry-pick |
| 2026-06-30 | Compose Mode 是产品中枢，不是辅助 | 6 套垂直流全部基于 Compose 实现，不重新发明编排 |
| 2026-06-30 | 千组千流（不是千人千面 UI） | 统一 UI + 按组分发 SKILL.md / MEMORY，降低前端工作量 |
| 2026-06-30 | 吸收 MimoCode 的 Memory / Checkpoint / Subagent / Goal / Dream / Distill | 这些是工程化长任务的必备底座，自建不划算 |
| 2026-06-30 | 采用业界生产模式 Pattern 1 + 2 + 5 + 副作用 tool dedupe 保险栓 | 6 人小团队不做 Verifier / Event Bus / Idempotent Retry，验收靠 schema + assert |
| 2026-06-30 | Track 调整：陈镇鸿 → 模型组，杨欣琳 → 风控组 | 陈擅长后端工程匹配 model PR 流程；杨擅长 LLM 评估匹配风控审批 |
| 2026-06-30 | Lead 接 PIT-RAG track（原杨欣琳的） | 基本面是主要使用方，由 Lead 维护契约 |
| 2026-06-30 | 俞高磊任务暂不分配 | 等其入组进度确认后再补；原 ComposeTask schema + dedupe 工具改由 Lead 和陈镇鸿承接 |
| 2026-07-10 | 编排层技术栈定型为 Python/LangGraph（删除 §5.5 旧"不引入 LangGraph"表述） | 与 PRD §6 / Architecture v2 / 实际代码对齐，6-30 定版前旧结论清理 |
| 2026-07-10 | trigger_risk_flow 定型为方式 2（Blackboard 队列标志） | 解耦 + 可观测 + 幂等；方式 1 同步 invoke 留作 Week 2 低延迟优化 |
| 2026-07-10 | Day5 引擎合并采用 PR#25 确定性 HumanGate + 移植 main 的 truncate | run_agent/IDE 依赖确定性 gate；truncate 保长任务鲁棒性（甲方案） |
| 2026-07-10 | demo 分组：factor/model/risk 走 AgentRunner(真ReAct)，options/strategy/fundamental 线性 flow 兜底 | 主菜展示自主推理，其余保可演，Week 2 迁 ReAct |
| 2026-09-01 | 功能定版：平台红线"不做业务层面"；HumanGate 收窄写操作门禁；"模型 PR"场景取消；fundamental 降级组内工具 | 2026-09-01 与各组长定版讨论（详见 specs/FUNCTIONAL_SPEC.md v0.2.1 §0 与 docs/PRD.md v2） |
| 2026-09-01 | 新增四大支柱：P-07 蒸馏（最大复用）/ P-08 Admin 中枢 / P-09 /deploy 黑盒 / P-10 方案先行（先方案后代码 + 一致性判定） | 痛点：库功能没进记忆导致重造、进展不透明、部署适配人工且需保密、一口气生成代码准确性与可审核性差 |
| 2026-09-01 | Admin 实现为角色而非第七组；回测/组合/并行 subagent 引擎代码保留 | 组枚举两仓不动；Subagent 用户拍板保留（平台能力）；引擎代码"万一有用" |
| 2026-09-01 | 组件开放四档制（主链 12 全员常驻/专项按组/纪律层/负面清单 legacy 映射）+ CapabilityCard 契约补 status/domain_authority/depends_on/consumed_by/deprecated_aliases；alpha_flow 标 SCAFFOLD；acceptance.py 因子评估阈值挂账待退役（评估权威=quant_evaluator） | 组长《常用组件清单》为权威源；文档先行；防 AI 用错近名死仓 |

---

**文档维护**：本设计文档跟随 `docs/PRD.md` 更新。PRD 变更产品范围时，设计文档同步工程实现与架构影响。时间线由 Lead 编排，不在本文档内固化。

# QuantCode 技术设计文档

> **项目定位 · 架构 · 功能清单 · 工程落位**
>
> **版本**：v4（2026-09-03，OpenCode/MimoCode 基线与运营边界重定版）
> **Owner**：Agent Group · HKUST QUANT SOCIETY
> **上位文档**：specs/FUNCTIONAL_SPEC.md 定义功能契约，docs/PRD.md 定义产品目标，docs/UI_DESIGN_SPEC.md 定义桌面端体验。
> **修订原则**：本版本保留原有 Agent 基础能力和工程设计，并把 OpenCode/MimoCode 的原生能力明确列为底座；只根据组长会议修正运营模式、职责边界和权限语义。不得把“领域产品不由 QuantCode 负责”误读为“QuantCode 删除 Agent 和 Compose 基础设施”。

---

## 1. 项目定位

### 1.1 一句话定位

QuantCode 是按业务组登录的研究 Agent 平台与组织能力中枢。它把组织已有的数据、因子、评估、模型、风险、组合、回测、报告和部署能力登记成可发现、可复用、可审计的能力，让 Agent 在真实任务中优先复用已有组件，并把运行结果、错误、决策和最佳实践沉淀到对应组的 Memory。

策略、组合、回测、期权定价和基本面报告的业务真相由各组及 canonical 组件维护，报告平台负责汇总展示，生产系统负责实际运行。QuantCode 提供接入、编排、契约检查、适配、可观测和组织协作。

### 1.2 产品原则

原设计的目标继续保留：用 Agent 放大研究组的产能，形成可持续迭代的投研团队。系统把各组的工作流写成 Compose 配置，把跨组交接写成 Schema 和 Blackboard 契约，并用 Dream + Distill 累积组织知识。

“最大复用”规定 Agent 的运行方式，属于平台纪律。Agent 先检索能力目录和组内 Memory；已有能力覆盖不全时先向用户说明缺口并征询，不静默创造与组织组件重复的实现。

### 1.3 与通用工具的差异

| 工具 | 定位 | QuantCode 的差异 |
|---|---|---|
| Cursor / Copilot | 个人编程助手 | 不知道组织的组、组件、契约和运行状态 |
| OpenCode / MimoCode | 通用编程 Agent 底座 | 提供通用 Agent 能力，但不知道本组织的组身份、组件权威、业务口径和工作环境边界 |
| Bloomberg / Wind | 数据终端 | 不负责研究任务的编排、验证、留痕和复用 |
| 自建 Dashboard | 固定状态面板 | 不能通过自然语言查询跨组运行、错误和组件状态 |

QuantCode 的连续集成范式仍为：

```text
Idea → 任务/模式识别 → 组内能力发现 → 主线匹配 → 动态 Schema
→ Agent 编排与组件调用 → 程序化验收 → artifact/trace/evidence
→ 组内 Memory 沉淀 → （由 Admin 发起生产操作时）受控部署入口 + 审计
```

---

## 2. 核心方法论

### 2.1 千组千流

每个用户使用同一个桌面入口，但登录后由认证会话自动加载唯一的业务组上下文。用户不在 UI 里选组，也不能通过任务参数切组：

```text
本地 SSH 身份登录
   ↓
服务端验证公钥并按 roster 匹配 actor / group / role
   ↓
加载该组可用的 SKILL.md、当前生效 Tool Catalog 与 Memory scope
   ↓
在既定组内按 idea 分派 compose / plan / build
   ↓
通过同一个 AgentRunner 执行，输出可追踪 artifact
```

要点：

- UI 统一，不为每个组复制一套前端；
- 六个业务组保留各自的 Compose 配置、Skill 和组级 Memory；工具集合由维护员后端的注册表动态生成；
- 组身份由登录会话决定，不由任务文本、普通参数或 UI 下拉框任意改写；
- 第一阶段可以让六组共用同一套研究/开发工具集合，后端保留按组或角色增加覆盖规则的兼容位；
- 工具和 Flow 只能由维护员后端注册、审核和发布，用户、前端和 Agent 不得动态注册能力；
- 跨组协作通过 Blackboard、公共契约、授权摘要和通知完成，不把会话临时切换成另一个组。

### 2.2 任务拆分与确定性契约

长任务会遇到上下文 compact、网络中断和工具失败，不能依赖 LLM 的隐式长程记忆。系统因此保留以下设计：

1. 大任务拆成有父子关系的无状态子任务（T1、T1.1、T1.2）；
2. 子任务之间使用 Pydantic/JSON Schema 传递数据，不用自然语言作为唯一协议；
3. 状态外化到 MEMORY.md、checkpoint 和 progress.md；
4. 每个工具调用记录输入、输出、版本和来源，副作用操作具备幂等或去重语义；
5. 任意 checkpoint 可以恢复、回放和审计，恢复时仍重新执行当前权限检查。

### 2.3 程序化验收

量化研究的验收标准应尽量表达为契约、assert、确定性检查和结构化报告。Agent 只负责识别应该调用哪个权威组件、传递输入、读取结果和展示来源；验收计算、风险判断和业务结论属于各组及其 canonical 组件：

- 因子证据由 QuantEvaluator 提供 RankIC、ICIR、换手、稳定性、衰减和置信区间等指标；
- 模型训练和时序泄漏检查由 Modeling 提供；
- 风险、组合和回测结果由 Barra、Riskfolio-QS、VectorBT-QS 等权威组件提供；
- Goal/Judge 可作为平台任务完成度判断，但不能替代领域验收、研究员判断或审批；
- 风险指标越限是评估结果或报告状态，不自动等同于 HumanGate。

### 2.4 人工介入边界

用户提交自然语言或 YAML 任务，Agent 自动完成能力发现、任务拆分、工具选择、契约检查和状态汇总。需要领域判断、需求补充或明确的共享写入时才询问人；风险结果、评估结果和报告由各组及外部平台按自己的流程处理。研究员仍负责问题、假设、算法调优和结果解释；系统不把每个普通动作都变成审批步骤。

### 2.5 知识沉淀与 Skill 候选

- Dream：定期扫描本组 session trace、错误和反馈，提取重复出现且有来源的知识，候选写入组级 Memory，并标记过期或 superseded 条目；
- Distill：识别重复操作和稳定工具组合，生成候选 SKILL.md 草案，经过维护者确认后才进入正式能力目录；
- Best Practice 沉淀：Python 版本、部署平台、模块职责、架构约定、数据口径和工程错误都可进入组级 Memory，下一次方案阶段优先检索；
- 自动沉淀不能把未经验证的模型猜测直接晋升为长期事实。

### 2.6 OpenCode/MimoCode 原生能力基线与 QuantCode 增量

QuantCode 运行在 OpenCode 控制平面之上，吸收 MimoCode 已验证的工作流与记忆设计，再叠加组织和量化场景能力。设计、实现和验收必须标明能力来源，避免把上游能力误报成 QuantCode 自研，也避免因领域产品归属不同而误删底座能力。

| 能力层 | OpenCode 原生底座 | MimoCode 原生/参考能力 | QuantCode 增量 |
|---|---|---|---|
| 交互与会话 | Desktop/TUI、会话、消息流、模型/Provider 配置、文件和 Shell 工作区、会话历史 | 通用命令和工作流入口的 Markdown 组织方式 | SSH 身份登录后的组页面、QuantCode 任务入口、统一量化工作区 |
| 工具与扩展 | MCP 客户端/服务端、工具调用、工具结果回流、插件/Provider 接入 | 工具编排和能力发现的组织方式 | 动态 Tool Catalog、组上下文、组件能力卡、量化适配器和契约检查 |
| 工作流 | 会话内连续 Agent 执行、命令和上下文管理 | `brainstorm/plan/execute/tdd/review/debug/feedback/report/parallel/subagent` 等 Compose Skill 形态 | 六组 Skill、ComposeTask、L0-L3 方案先行、主线匹配和跨组 handoff |
| 状态与长任务 | 会话历史、可恢复的执行上下文 | Memory FTS/BM25、reconcile、checkpoint/replay、任务树、Subagent、Goal/Judge、Dream/Distill | 组级共享 Memory、Blackboard 公共契约、量化 artifact/evidence、按 actor/group 的可见性 |
| 安全与治理 | OpenCode 的本地工作区、Provider 和 MCP 边界 | 通用权限提示与工作流纪律参考 | SSH roster 自动绑定、动态工具集合、GitHub 权限映射、Admin 中枢、GitGraph/Pop、Admin-only `/deploy` |

底座能力的归属规则：

1. OpenCode 负责桌面壳、会话交互、模型/provider、MCP 传输和本地工作区体验；QuantCode 不在 TypeScript 侧复制另一套 Agent loop。
2. MimoCode 的 Memory、Checkpoint、Task、Subagent、Goal/Judge、Dream/Distill 和通用 Skill 是设计参考和可复用工作流知识；QuantCode 使用自己的 Python/LangGraph 实现与数据契约，不把 MimoCode 私有运行时当作线上依赖。
3. QuantCode 新增组织能力：身份到组的自动绑定、组内知识共享、能力目录和最大复用纪律、跨组契约、Admin 管理视图、GitGraph/Pop、P-10 方案分级和量化组件适配。
4. 领域组件负责数据、因子、评估、模型、风险、组合、回测、报告和生产运行的业务真相。QuantCode 只发现、编排、调用、适配和记录，不重新实现这些事实。

#### 2.6.1 OpenCode 原生 Agent 能力清单

以下能力属于 OpenCode 控制平面和运行时底座，QuantCode 直接复用，不重复设计第二套实现：

| OpenCode 能力 | 底座行为 | QuantCode 的使用方式 |
|---|---|---|
| Session 生命周期 | 创建、继续、取消、重试、历史、标题和状态管理 | 一个用户身份对应一组可见 session；QuantCode trace 挂在原生 session 上 |
| Prompt/Context | 文本、文件、目录、图片和结构化输入；上下文裁剪和 compaction | 注入组上下文、能力摘要、Memory 摘要和任务契约；不注入私钥或生产凭据 |
| Agent loop | LLM 推理、工具调用、观察结果、继续或结束 | QuantCode Python AgentRunner 通过 MCP 接入，负责量化任务编排和运行时加固 |
| 原生工具 | `read`、`write`、`edit`、`apply_patch`、`grep`、`glob`、`shell`、`lsp`、`websearch`、`webfetch`、`todo`、`question`、`task`、`skill`、`plan`、`truncate` | 研究/开发工具作为公共工具集合的基础；具体组页面只展示当前 session 可用面 |
| Tool Registry | 工具发现、JSON Schema 参数、工具状态、结果和错误回流 | 叠加 QuantCode Tool Catalog、量化 ToolDef 和维护员发布流程 |
| MCP | stdio/HTTP/SSE 客户端、工具、资源、Prompt、OAuth/认证状态和变更通知 | 连接 Python 编排层、量化组件和外部服务；每次调用仍执行 session 与资源权限校验 |
| Permission | allow/ask/deny、权限提示、拒绝和重试 | QuantCode 只在明确的共享写入/跨组授权处接入；生产部署使用 Admin 管理面 |
| Workspace/Project | 本地工作区、目录边界、Git 快照、分支/Worktree 和终端 | SSH 登录后绑定用户个人工作目录；不把生产服务账号目录挂入研究 workspace |
| UI/状态流 | Desktop/TUI、消息时间线、工具状态、文件标签、终端、Diff/Review、通知 | 在原生 session UI 上增加 QuantCode Compose、Memory、能力目录、GitGraph、Pop 和 Admin 面板 |
| Provider/模型 | Provider 配置、模型选择、用量和错误归一化 | QuantCode 通过统一模型接口调用，不保存或回显 Provider 密钥 |
| 插件与命令 | 插件加载、命令模板、Slash command、配置和主题 | QuantCode 命令只负责把请求路由到对应 MCP/Agent 能力，不在命令层承载业务真相 |

OpenCode 原生工具仍遵守同一个工作区和 session 权限。`shell` 能力表示在已授权的研究/开发 workspace 内执行命令，不表示拥有生产 shell；`write/edit/apply_patch` 表示修改个人工作目录或当前开发仓，不表示可以写入生产服务账号环境。

#### 2.6.2 MimoCode 原生/参考 Agent 能力清单

MimoCode 的价值主要体现在可移植的 Compose 工作流和 Memory 设计。QuantCode 保留其能力语义，用自己的 Python/LangGraph 实现承接：

| MimoCode 能力 | 保留内容 | QuantCode 实现/边界 |
|---|---|---|
| Compose ReAct | `while` 式 thought → tool → observation → next thought 循环，不把流程硬编码成固定 DAG | `AgentRunner`/LangGraph；六组共用循环，组差异来自 session、Skill、Memory 和工具目录 |
| 通用 Compose Skill | `brainstorm`、`plan`、`execute`、`tdd`、`review`、`debug`、`feedback`、`report`、`parallel`、`subagent`、`worktree`、`verify`、`ask`、`new-skill`、`merge` | 以 `.opencode/meta-skills/*/SKILL.md` 形式加载；QuantCode 再叠加六组 Skill 和量化契约 |
| Memory | Markdown 文件作为事实载体，SQLite FTS5/BM25 作为检索索引，磁盘与索引 reconcile | `runner/memory`；增加 `groups` 组内隔离和 `tasks` 任务进度，具体 ACL 由 QuantCode session 决定 |
| Context 维护 | 长上下文裁剪、摘要、最近消息保留和可继续执行 | `truncate`、`rebuild_context`、checkpoint；重建后必须重新校验当前身份和工具权限 |
| Task/子任务 | 将复杂请求拆成有边界的任务，保留父子关系和状态 | `ComposeTask`、Subagent、任务 progress；子任务继承 actor/group/workspace 和预算 |
| Checkpoint/Replay | 把运行状态外置，支持中断后恢复、回放和审计 | LangGraph SqliteSaver + execution trace + evidence；不把旧 checkpoint 当作永久授权 |
| Goal/Judge | 任务完成度和结果质量的结构化判定 | 作为平台证据和用户提示，不代替研究员、领域组件或 Admin 决策 |
| Dream/Distill | 从历史运行、重复操作和反馈中提取 Memory/Skill 候选 | 候选需来源、验证状态和维护员确认，不能自动把猜测晋升为组织事实 |

#### 2.6.3 QuantCode 自有增量的判断标准

新增能力只有在解决“组织知道有什么、谁能看、如何复用、如何交接、如何管理”的问题时才进入 QuantCode：

- 身份与组织：SSH 公钥指纹 → 公司 roster → `actor/group/role/workspace` 自动绑定；登录后自动进入对应组页面；
- 组织知识：组内共享 Memory、公共契约、能力卡、数据口径、错误和 Best Practice；
- 组件复用：从 GitHub/`gh` 实读登记 canonical 组件，生成动态 Tool Catalog，缺口先向人询问；
- 协同治理：Blackboard 公共契约、跨组 handoff、artifact/trace/evidence、Admin 全组织查询；
- 运营可见性：全组 GitGraph、按 GitHub 权限过滤的 repo/branch/commit、repo/package Pop；
- 量化适配：DataAccess、FactorEngine、QuantEvaluator、Modeling、Barra、组合/回测和报告平台的契约化接入；
- 方案纪律：P-10 L0-L3 复杂度分级、SolutionDoc、冻结和 conformance verdict；
- 管理操作：Admin 专属部署和组织级管理。普通研究 Agent 不获得生产服务账号，不直接调用 `/deploy`。

以下不算 QuantCode 自有功能：重新实现 OpenCode 的文件/Shell/MCP/session 基础能力；重新实现 MimoCode 的 Memory/Task/Skill 语义；重新实现数据、因子、评估、风险、组合、回测、期权或报告业务系统。

---

## 3. 三层系统架构

### 3.1 控制平面、编排平面、执行平面

QuantCode 保留原有语言和职责边界：TypeScript 控制平面负责接入与可视化，Python 编排平面负责核心 Agent 推理和状态机，Python 执行平面负责工具和外部系统适配。

```text
┌──────────────────────────────────────────────────────────────────┐
│ 控制平面 Control Plane                                            │
│ OpenCode / opencode-lens（TypeScript + Electron/SolidJS）         │
│                                                                  │
│ OpenCode 原生 Desktop/TUI、会话、消息流、Provider、MCP 客户端   │
│ 本地 SSH 身份界面、自动组/角色展示、任务输入、Activity          │
│ Compose 视图、Schema 卡片、任务树、Memory、GitGraph、Pop、Admin  │
│ Gate 操作、通知和回放入口                                         │
│                                                                  │
│ 只负责接入、展示、用户交互和 MCP 调用，不承载领域计算或权限决策   │
└────────────────────────┬─────────────────────────────────────────┘
                         │ MCP stdio JSON-RPC / HTTP / SSE 状态流
┌────────────────────────▼─────────────────────────────────────────┐
│ 编排平面 Orchestration Plane                                     │
│ QuantCode Python runner/                                         │
│                                                                  │
│ AgentRunner ReAct · LangGraph StateGraph · Skill loader           │
│ 任务拆分 · 模式分派 · ToolRegistry · 方案阶段 · checkpoint/replay │
│ MimoCode Task/Memory/Checkpoint/Subagent/Goal/Dream 设计的实现    │
│ Memory FTS5 · Blackboard · permission · HumanGate · evidence      │
│ 循环检测 · 迭代上限 · context truncate · RLHF/评估接入点          │
│                                                                  │
│ 负责 Agent 如何行动，不重新计算领域组件已经提供的业务结果         │
└────────────────────────┬─────────────────────────────────────────┘
                         │ ToolDef / typed adapter / external API
┌────────────────────────▼─────────────────────────────────────────┐
│ 执行平面 Execution Plane                                          │
│ Python tools/ + 组织 canonical components + 外部服务              │
│                                                                  │
│ DataAccess · FactorEngine · QuantEvaluator · Modeling · Barra      │
│ FactorOptimizer · FactorAssets · FactorPreprocess                 │
│ Riskfolio-QS · VectorBT-QS · QuantPlatform · Report Platform       │
│ GitHub · COS · Server A/B · SSH gateway · AlphaFlow adapter        │
│ ChromaDB/PIT-RAG · 爬虫 · CI Actions · 通知服务                    │
└──────────────────────────────────────────────────────────────────┘
```

三条架构铁律：

1. 核心推理编排只在 Python/LangGraph 编排平面；TypeScript 不复制一套 Agent loop；
2. 控制平面与编排平面通过稳定契约解耦，可独立演进；
3. 执行平面工具是无状态能力和适配器，不能绕过编排平面的组权限、契约检查或写操作 Gate。

### 3.2 三大生产模式与幂等保险栓

原设计的 Pattern 1、2、5 继续作为所有 Compose 流的架构基石。Pattern 5 保留 interrupt/resume 机制，触发范围改为共享写入和跨组授权。

#### Pattern 1：Orchestrator-Worker

- Compose Agent 是中心 Orchestrator；
- SKILL.md 和 Subagent 是 Worker；
- Orchestrator 负责任务拆分、调度、合并结果和最终状态；
- Worker 默认只向 Orchestrator 汇报，通过 Blackboard/Schema 交接，不相互绕过权限直接写共享状态；
- 路由、工具调用和失败原因都写入 trace。

#### Pattern 2：Stateful Blackboard

Agent 将关键数据写入结构化状态层，避免只依赖对话内容：

- 项目级 Memory：跨组共享的公开结论和契约；
- 组级 Memory：该业务组共享的研究结论、错误、组件用法和 Best Practice；
- 会话级 checkpoint：支持 compact、断点续跑和 replay；
- 任务级 progress：记录父子任务和完成状态；
- Blackboard：契约层保留 GLOBAL/PROJECT/GROUP/SESSION/TASK 五级 scope；跨组 handoff 使用 PROJECT，组内私有状态使用 GROUP，会话快照和任务进度分别使用 SESSION/TASK。

Memory 的五层 scope 和 Blackboard 的五级 scope 是两个独立机制，不能混用。Blackboard 的权限、写策略和生命周期必须按 scope 单独实现，不能因为 PROJECT/GROUP 是当前主要路径就把其他三种 scope 当作不存在。

#### Pattern 5：Human-in-the-Loop Gate

HumanGate 是底座提供的 interrupt/resume 机制。QuantCode 当前把它用于共享写入和跨组授权，不把它扩大成风险、评估、报告或普通开发的审批器。

当前 QuantCode 允许进入 Gate 的动作只有：

- `merge`：主线或共享资产入库；
- `permission`：受限跨组资源的一次性授权。

生产部署由 Admin 专门负责，属于 Admin 的受控操作面，不进入普通研究 Agent 的 Compose 流。研究员可以通过 SSH 进入自己服务器上的个人工作目录并写代码，但不能取得生产服务账号、进入生产 shell 或直接操作生产运行环境。

风险指标、评估结果、报告、工具错误、预算耗尽、循环检测和 CI 结果由各组/外部组件的结果、报告或停止状态表达；它们不自动创建业务 HumanGate。若未来新增生产写动作，必须先在功能规格中定义 owner、资源范围、审计和回滚，再接入统一 Gate。

#### 幂等和去重保险栓

所有对外发送、创建或修改的副作用工具继续使用 dedupe_within 或外部幂等键。覆盖 github_pr_*、邮件、Slack、跨组通知和部署请求；AutoEval、RAG 查询和天然覆盖写不强行套用该装饰器。

#### 暂不引入的架构模式

| 模式 | 暂不引入的原因 | 当前替代 |
|---|---|---|
| Supervisor/Verifier | 量化验收已有契约和指标，独立审核 Agent 会增加复杂度 | Schema + assert + Goal/Judge + 领域负责人 |
| Event-driven Pub/Sub | 当前团队规模下直接 handoff 足够 | Blackboard 队列、通知和定期聚合 |
| 完整 Idempotent Retry Chain | 大多数查询天然幂等，完整链路成本高 | 工具幂等键、去重表、evidence |

### 3.3 Compose 流与三种执行模式

Compose 是 QuantCode 的编排核心。六个组共享 OpenCode/MimoCode 的 Agent 交互底座和同一个 ReAct 循环；组内差异先由 Skill、Memory 和任务上下文表达，工具集合由维护员后端动态生成。

控制平面入口：

```text
build    → 明确的代码生成/修改与开发工作
plan     → 只读分析、调研和方案输出
compose  → 按组加载工作流配置，由 Agent 自主编排多个 skill/tool
```

模式由 idea 和任务复杂度决定，组由认证会话决定。compose 使用动态 ReAct 路径；Agent 在运行时根据当前状态选择下一工具，同时保留可观察的任务树和执行轨迹。复杂任务可先进入 P-10 SolutionDoc；简单任务仍可直接执行。

工具集合的动态策略：

```text
维护员注册/审核 ToolDef 与 Flow
        ↓
生成版本化 Tool Catalog（默认公共研究/开发集合）
        ↓
登录 session 注入 actor / group / role / workspace
        ↓
计算 effective_tools，并绑定到 AgentRunner 与 MCP tools/list
        ↓
每次 tools/call 再按 session 和资源策略校验
```

第一阶段允许六组共用同一套研究/开发工具集合，以降低初期权限配置成本；以后出现数据、仓库或写操作权限需求，再由维护员增加 group/role/resource mask。Admin 工具和生产部署工具始终是独立管理面，不因“共用工具集合”而暴露给普通研究 Agent。

### 3.4 仓库结构与职责落位

```text
quantcode/
├── .opencode/
│   ├── config.yaml / opencode.jsonc
│   ├── authorized_groups.example.yaml
│   └── groups/<group>/
│       ├── skills/                 # 组内 SKILL.md
│       └── tool_allowlist.yaml     # 维护员配置的兼容覆盖（非用户权限源）
├── runner/
│   ├── agent_engine.py             # AgentRunner / StateGraph / ReAct
│   ├── agent_nodes.py              # llm/tool/rlhf/truncate 节点
│   ├── agent_mcp_tool.py           # run_agent start/resume
│   ├── langgraph_base.py           # graph factory + checkpointer
│   ├── compose_executor.py         # FLOW_REGISTRY 线性 flow 入口
│   ├── human_gate.py               # interrupt/resume 与 payload
│   ├── acceptance.py               # 程序化验收
│   ├── schema_validator.py         # JSON Schema 校验
│   ├── memory/                     # FTS5/BM25/reconcile/query
│   ├── routing/                    # 路由、循环和 RLHF 记录
│   ├── permission_engine.py        # allow/deny/ask 判定
│   └── blackboard.py               # PROJECT/GROUP handoff
├── flows/
│   ├── factor_autoeval.py          # 因子评估适配 flow
│   └── risk_gate.py                # CI 风控基建 flow
├── tools/
│   ├── registry.py                 # ToolDef / ToolRegistry
│   ├── loop_detector.py
│   ├── common/                     # handoff / task / 状态工具
│   ├── utils/dedupe.py
│   ├── model/ risk/ factor/
│   │   fundamental/ strategy/ options/
│   └── skills/loader.py
├── schemas/                        # Pydantic contracts
├── dream/                          # dream_prototype / distill_prototype
├── quantcode/mcp_server.py         # MCP stdio 入口
├── tests/
├── docs/mimocode-reference/        # 设计参考，线上不加载
└── docs/                           # 顶层、领域和运维文档
```

控制平面位于独立的 HKUST-QUANT-SOCIETY/opencode fork；本仓库通过 MCP 和契约接入，不把 TypeScript UI 逻辑当作领域真相。

---

## 4. Agent 运行时设计

### 4.1 AgentRunner 状态与 ReAct 图

AgentRunner 基于 LangGraph 自建 StateGraph，保留原有可中断、可重放和可加固设计。状态至少包括：

- messages、task_goal、iterations、当前模式和 flow；
- actor_id、认证 group、role、thread_id；
- parent_task、children、task_status、solution_phase；
- execution_trace、tool_calls、errors、artifacts、output_data；
- risk_metrics、budget_used、checkpoint_snapshot；
- 当前 gate_payload、human_decision 和 evidence。

基本图：

```text
load session/group context
        ↓
llm → tool → observe → context/checkpoint routine → route → llm
                                  ↓
                         rlhf/evaluation logger
                         ↓
                   merge/permission adapter → HumanGate interrupt/resume
                         ╲
                          ╲ Admin 管理面发起 /deploy → 生产服务账号受控接口
```

路由处理任务状态和运行安全：

- 最大迭代和最大树深度；
- 工具错误、重试和显式降级；
- state fingerprint、重复工具调用和死循环；
- context 占用超过阈值时 checkpoint/truncate/rebuild；
- 预算硬上限和停止状态；
- 共享写入的 Gate；Admin 生产部署走独立管理面和审计，不由普通 Agent 路由触发。

风险指标、研究产出和 CI verdict 不由路由器自动升级为 HumanGate。

### 4.2 Skill、模式与 ToolRegistry

每个组的 SKILL.md 记录工作流知识，Agent 在运行时加载，统一 Runner 负责执行。Skill 可描述 brainstorm、plan、execute、tdd、review、debug、数据契约检查、组件适配等步骤。OpenCode/MimoCode 的通用 Skill 作为底座能力保留，QuantCode 只增加组内和量化领域的 Skill。

ToolDef 统一声明：

```text
id / name / description
Pydantic input schema
executor / output contract
group visibility / permission metadata
side_effect / idempotency metadata
source / version / capability card reference
```

ToolRegistry 负责发现、参数校验、当前生效工具目录和 trace；服务端 session、外部 API 和资源层再次校验权限。第一阶段默认提供六组共用的研究/开发工具集合，静态 `tool_allowlist.yaml` 作为维护员配置的兼容覆盖，用户不能修改权限。_meta 工具用于能力目录、Memory、运行状态和诊断；Admin 工具与生产部署工具使用独立管理面，不进入普通 Agent 工具集合。

工具目录的生命周期由维护员后端负责：注册 → schema/副作用审查 → 发布版本 → 绑定可用环境 → 下线/回滚。Agent 只能消费已发布目录，不能注册、修改、提升或自授予工具权限。未来增加细粒度权限时，按 `actor → group → role → resource` 计算 effective tool set，并在 `tools/list` 和 `tools/call` 两端使用同一结果。

### 4.3 长任务能力

原有以下能力全部保留为平台基础设施：

| 能力 | 技术设计 |
|---|---|
| 树状任务 | ComposeTask 表达 parent/children/status/artifacts，与 checkpoint 关联 |
| 自动 Checkpoint | LangGraph SqliteSaver；context 占用超过策略阈值时 snapshot |
| Context 重建 | 从 checkpoint、组内 Memory、任务进度和最近消息重组上下文 |
| Subagent | 子图/子任务并行执行，预算隔离、组 allowlist、生命周期追踪和独立 kill |
| Replay/Resume | 从指定 checkpoint 恢复；恢复后按当前 actor/group/role 重新授权 |
| Goal/Judge | 独立 judge 评估目标完成度，结果作为 evidence，不替代领域负责人 |
| RLHF 记录 | 记录工具选择、反馈和失败模式，为后续评估/训练提供数据 |
| Dream/Distill | 扫描 trace，生成 Memory 候选和 Skill 候选，需验证/确认后晋升 |

### 4.4 三个核心契约

原设计的三大模式契约继续作为编排层和执行层之间的稳定边界：

| 契约 | 作用 | 关键字段 |
|---|---|---|
| ComposeTask | Orchestrator 的任务信封和任务树 | task_id、status、parent、children、goal、artifacts、owner_group |
| BlackboardState | 跨任务/跨组共享状态 | scope、namespace、producer、consumer、schema_version、payload_ref、updated_at |
| HumanGate | 受控写操作 interrupt/resume 和审批记录 | gate_id、kind、resource、reason、actor、approver、decision、evidence、expires_at |

所有契约使用 Pydantic/JSON Schema 校验并带版本。领域组件可以拥有自己的领域 Schema，但必须通过适配器转换，不能让自然语言成为唯一接口。

### 4.5 Agent 的核心工作动作

原有的动态 Schema、主线匹配和跨组触发继续保留：

1. **动态 Schema 生成**：Agent 读取 idea、已授权的组内主线和能力卡，生成 Pydantic Schema；系统校验类型、字段来源和版本，前端以 Schema 卡片展示。该 Schema 只约束当前任务，不构成未经确认的业务真相。
2. **主线匹配（match_main）**：通过授权的开发/研究 SSH 读取 Server A/B 主线代码或缓存，使用 RAG/结构化索引匹配相关模块，返回 compatible、requires_extension 或 bypass，并列出依据和缺口。
3. **能力优先复用**：方案阶段先检索能力目录、组内 Memory 和契约；已有组件不能完全覆盖时先询问用户是澄清需求、扩展适配器还是确认自定义实现。
4. **跨组触发**：A 组完成任务后可以创建 B 组待办、写入 Blackboard、发送通知并等待 ack；只传递被授权 artifact 引用，不改变当前会话 group。
5. **人工编排**：用户可以用 YAML 描述 pipeline、预览依赖、暂停节点、调整 Schema 和恢复任务；人工跳过只改变流程状态，不绕过权限或 Gate。

### 4.6 MCP 与控制平面契约

控制平面通过 MCP 调用 run_agent。开始和恢复是同一任务的两个阶段，组身份取自认证 session：

```text
RunAgentArgs:
  task / session group / skill_name / max_iterations
  thread_id / mode / decision(start|resume)

RunAgentResult:
  status / thread_id / gate
  execution_trace / output_data / artifacts / errors
```

控制平面不得根据输入框里的 group 字符串授予权限；UI 的组名只是服务端返回的会话信息。恢复请求必须携带原 thread_id 和当前权限上下文，不能利用旧 checkpoint 提升权限。

---

## 5. 任务分级与方案先行

### 5.1 SolutionDoc 状态机

P-10 继续保留，但不再把所有任务固定成相同讨论轮数。方案流程为：

```text
draft → discussion/revision → frozen → implementation → conformance verdict
```

SolutionDoc 至少包含 goal、背景、任务类型、预期文件面、依赖组件、数据契约、验收标准、风险、版本和 doc_hash。实现完成后由确定性检查比较代码变更与方案的 file_impact、接口和验收条件。

### 5.2 复杂度分级

| 级别 | 典型任务 | 技术行为 |
|---|---|---|
| L0 | 查询、查看状态、读资料、能力搜索 | 直接执行并记录 trace，不创建方案 |
| L1 | 一次评估、参数实验、单文件小修改 | 可生成轻量计划，不强制冻结 |
| L2 | 新模块、多文件修改、跨仓集成、复杂组件适配 | SolutionDoc draft，讨论并确认 frozen 后进入代码阶段 |
| L3 | 生产部署、主线入库、不可逆写 | L2 + evidence；merge/permission 进入 HumanGate，生产部署由 Admin 管理面发起 |

Draft 阶段允许读取资料、检索 Memory、查看组件和运行只读验证；代码生成和写入工具按阶段限制。阶段限制是工作流控制，不等同于 HumanGate。

---

## 6. 身份、组、角色与权限

### 6.1 本地公钥身份登录

桌面端提供完整的 SSH 身份登录界面，但私钥始终留在本机密钥链或 SSH agent 中：

```text
本地 SSH agent / Keychain
        ↓ 公钥证明，不上传私钥
服务端 SSH gateway 验证公钥并计算 fingerprint
        ↓
roster 按 fingerprint 匹配 actor_id / group / role
        ↓
创建不可变 session，注入 Skill / tools / Memory scope
```

服务端公司 roster/绑定表是权威源。它至少维护 fingerprint、actor_id、group、role、workspace 和允许的 GitHub/服务器资源。`quantcode/identity.py` 的本地解析只用于开发和测试；正式会话不依赖前端输入的组名，也不允许调用方通过 `run_agent(group=...)` 覆盖认证组。登录成功后，服务端直接返回组页面上下文，UI 不显示自由切组控件。

私钥不得进入 UI 普通文本请求、LLM 消息、Agent state、Memory、trace、artifact 或日志。界面可显示 fingerprint 摘要、连接状态、actor、组和角色；连接失败要区分密钥拒绝、主机不可达、roster 未命中和权限不足。

### 6.2 业务组与 Admin 角色

GroupName 继续保留六个业务组：fundamental、factor、model、risk、strategy、options。

Admin 是组织级全权角色，业务组仍为六组。Admin 在 QuantCode 平台拥有无限权限，不受业务组的可见性、管理、审批和部署发起范围限制，可以查看和管理所有组的任务、运行、错误、Memory、Blackboard、能力卡、仓库状态和 Gate。Admin 的访问、管理、审批和部署发起仍写审计记录；领域负责人继续对研究结论和业务口径负责。

普通角色：

- analyst：执行授权的研究、开发、查询和只读工具；
- approver：在被授权范围内处理对应写操作 Gate；
- admin：跨组全可见、全量查询、管理和审批。

研究员通过 QuantCode SSH 进入其被授权服务器上的个人工作目录，读写自己的开发/研究文件；该目录属于研究/开发环境。生产环境由独立服务账号和生产系统安全策略运行，研究员不能直接取得该服务账号、进入生产 shell 或直接控制生产进程。`/deploy` 是 Admin 专属的受控部署操作，普通研究 Agent 不调用、不展示生产底层结构。Admin 在 QuantCode 内拥有全组织可见性、管理和审批权，但仍不能把研究员会话变成生产服务账号。

### 6.3 GitHub 权限与资源可见性

GitHub/组织 Git 权限是 GitGraph 和仓库资源可见性的外部权威之一，业务组权限策略是 Memory、组件详情和数据字段的补充权威。普通用户只能看到当前身份实际有权访问的 repo；Admin 按组织权限查看全部 repo。

中心服务 token 不能在普通用户请求中无条件代替用户身份。后端返回权限上下文和 observed_at，前端不能通过隐藏/显示决定安全边界。跨组资源的临时访问采用 permission Gate，授权范围、时效和 actor 都进入 evidence。

---

## 7. 组织能力目录与标准组件

### 7.1 能力卡片

能力卡预置组织知识，记录组件如何使用。卡片来源以 gh 实读 HKUST-QUANT-SOCIETY 组织仓库、负责人确认和版本信息为准，不凭会议记忆写死数量。

每张卡至少记录：

```text
canonical_repo
status: PRODUCTION | STAGING | RESEARCH | SCAFFOLD | LEGACY | PLACEHOLDER
type: asset | contract | rule
domain_authority
inputs / outputs / public_api
depends_on / consumed_by
owner_group / visibility
deprecated_aliases
source_commit / observed_at
when_to_use / when_not_to_reinvent
```

摘要层在 Agent run 中常驻，包含 id、名称、用途、状态和“何时别自造”；详情层按 ACL 提供 API、字段、部署和实现约束。目录发现不代表运行时已经接通，STAGING、RESEARCH、SCAFFOLD 和 LEGACY 必须显式标识。

### 7.2 Canonical 主链

组件指南确认的主链在技术设计中保留为组织能力地图：

```text
DataAccess
  → FactorEngine
  → QuantEvaluator
  → FactorOptimizer / FactorAssets
  → FactorPreprocess
  → Modeling
  → Barra Engine / Riskfolio-QS
  → VectorBT-QS
  → QuantPlatform / Platform Web
```

关键选择规则：

```text
已有因子值 / FactorPanel  → QuantEvaluator
没有因子值               → DataAccess → FactorEngine → QuantEvaluator
优化结构或处理方案        → FactorOptimizer
身份、去重和生命周期      → FactorAssets
winsor/rank/neutralize     → FactorPreprocess
训练、切分和 OOS          → Modeling
风险暴露和协方差          → Barra Engine
组合约束和目标仓位        → Riskfolio-QS
真实成交、成本和公司行动  → VectorBT-QS accurate
平台 DTO、权限和工作流    → QuantPlatform
展示和报告门户            → Platform Web / Report Platform
```

### 7.3 组件职责边界

| 组件 | 权威职责 | QuantCode 的职责 | 不应越权承担 |
|---|---|---|---|
| DataAccess | 数据读写、PIT、快照、字段和权限 | 发现、调用、契约检查和记录 | 业务仓裸读生产数据、造第二套数据目录 |
| FactorEngine | DSL、算子、AST/IR 和因子值计算 | 发现、调用、适配和记录 | 重造因子语法或算子库 |
| QuantEvaluator | IC、ICIR、换手、稳定性和区间证据 | 发起评估、消费和展示 artifact | 自算第二套指标 |
| FactorOptimizer | 结构、参数和 treatment 搜索 | 编排试验、消费证据、记录 ledger | 把搜索结果伪装成最终结论 |
| FactorAssets | 因子身份、去重、聚类、生命周期和入库 | 适配入库入口和查询 | 维护第二套因子事实源 |
| FactorPreprocess | 预处理和 FeatureBundle | 选择策略和调用 | 各模型重复实现处理逻辑 |
| Modeling | walk-forward、purge/embargo、训练、OOS | 发现、调用和验收 | 自行决定时序切分口径 |
| Barra/Riskfolio/VectorBT | 风险模型、组合优化和成交回放 | 登记、编排和适配 | 在平台层重算业务结果 |
| QuantPlatform | DTO、RBAC、Job/Workflow、Outbox、Artifact | 作为平台契约入口 | 复制量化计算或第二套因子湖 |
| Report Platform | 汇总、展示、发布研究与策略表现 | 提供结构化 artifact、链接和状态 | 复制报告产品 |
| Admin | 组织可见性、管理、审批和运行治理 | 提供中枢查询和管理界面 | 代替各组做研究判断 |

### 7.4 组件分档与负面清单

组件清单的四档语义保留：

1. **主链全员常驻**：data_access、factor_engine、quant_evaluator、factor_optimizer、factor_assets、factor_preprocess、modeling、barra_engine、riskfolio_qs、vectorbt_qs、quant_platform、platform_web；
2. **专项按组**：AlphaProbe、CogAlpha/AlphaMining、Factor Research DB、Sentinel、earnings-flash、Barra 专项、期权组件、PaperRAG、Quant Knowledge Graph 等；
3. **纪律层**：quant-ops、backtest_repo_example 等只蒸馏规则或样板，不伪装成稳定 API；
4. **负面清单**：旧仓、测试仓、demo、placeholder 和 legacy alias 写入 deprecated_aliases，防止 Agent 误选近名死仓。

alpha_flow 当前只登记为 SCAFFOLD/部署目标接口。它的内部模块、生产格式和实现细节受黑盒边界保护，不能在普通能力卡或 Agent 回复中展开。

### 7.5 状态基线与复用硬纪律

| 组件类别 | 代表仓库 | 状态/可见性 |
|---|---|---|
| 主链数据、因子、评估 | data_access、factor_engine、quant_evaluator | PRODUCTION，全员摘要；评估器是唯一指标权威 |
| 主链优化、资产、预处理 | factor_optimizer、factor_assets、factor_preprocess | STAGING，全员一行，相关组可看详情 |
| 模型与风险 | modeling、barra_engine | PRODUCTION；模型/风控组深卡，他组按权限看摘要 |
| 组合与回测 | riskfolio_qs、vectorbt_qs | PRODUCTION；策略/风控或策略组深卡 |
| 平台集成与 Web | quant_platform、platform_web | quant_platform 为 DRAFT/WIP；platform_web 为展示镜像 |
| 因子挖掘与专项 | alphaprobe、AlphaMining-*、factor-research-db | STAGING/RESEARCH，默认因子组详情 |
| 基本面、期权、知识辅助 | sentinel、earnings-flash、option-*、PaperRAG、quant-knowledge-graph | 按组专项，状态以能力卡和 gh 观察记录为准 |
| 生产部署目标 | alpha_flow | SCAFFOLD，普通用户只见最小部署契约 |

所有主链卡片的 when_not_to_reinvent 至少包含以下纪律：

1. 生产数据必须经 DataAccess，禁止业务仓裸读 parquet/ClickHouse；
2. 因子定义和计算优先使用 FactorEngine DSL；
3. 因子评估一律调用 QuantEvaluator，NOT_COMPUTED 不等于 0；
4. 模型切分和泄漏防护复用 Modeling 的 walk-forward/purge/embargo；
5. 生产候选回测使用 VectorBT-QS accurate replay。

### 7.6 数据与标签契约

目标收益、前向标签、复权字段和 PIT 规则以数据层现有表与领域 SPEC 为唯一取值源。当前已冻结的 TargetReturnView/v1 包含 Horizon ∈ {1, 5, 10, 20}、后复权字段和 t+1 → t+2 的统一口径。Agent 应识别并调用数据契约，发现业务仓自行重算或使用未复权字段时给出明确 warning；不得在 QuantCode 再造一套标签实现。

---

## 8. 六组 Compose 配置与跨组边界

六组流是 Agent 的组内配置和工具组合。每个流可调用本组工具、组织标准组件和外部平台，并把结果落成 artifact；各组业务系统继续维护领域事实。

### 8.1 基本面组（fundamental）

**工作目标**：围绕公司、行业和宏观问题进行时点安全检索、财报提取、估值和研究资料整理。

**典型工具**：pit_rag_search、extract_financial、dcf_valuation、render_report、write_blackboard。

**边界**：研究员和基本面组负责研究判断；报告 PDF 和发布由报告平台承接。QuantCode 保留 PIT-RAG、契约检查、artifact 和组内工具适配，不把基本面报告做成第二个产品。

### 8.2 因子组（factor）

**工作目标**：接收因子 idea，检索主线与能力目录，生成 FactorSpec，调用 FactorEngine/DataAccess/QuantEvaluator，输出因子证据，并在需要时把已调试代码交给维护员/Admin 管理的入库流程。

**典型工具**：match_main、gen_factor_schema、factor_engine、eval_from_panel、quant_evaluator、check_factor_gate、merge_to_main。

**边界**：论文算法落地、研究调优和因子科学判断由研究员负责；QuantCode 负责让 Agent 知道已有组件、调用组织标准链、检测数据口径和适配开发工作环境。已有 FactorPanel 时直接走 QuantEvaluator；没有因子值时先 DataAccess，再 FactorEngine，再 QuantEvaluator。评估结果由组件返回，Agent 不审批；生产部署不属于因子 Agent。

### 8.3 模型组（model）

**工作目标**：文献和模型设计、训练实验、OOS 证据、模型 artifact 和代码协作。

**典型工具**：read_pr、extract_metadata、generate_model_spec、modeling、write_blackboard、trigger_risk_flow。

**边界**：模型静态 artifact 可上传 COS；代码仍走正常 GitHub PR/CI。原有 model→risk 的 handoff 和风险 CI 作为工程基建保留，不把“模型 PR 自动风控”继续包装成 QuantCode 的独立产品主流程。

### 8.4 风控组（risk）

**工作目标**：消费模型或策略的结构化输入，调用风险组件，生成 RiskProfile、暴露和组合约束结果。

**典型工具**：read_blackboard、calc_risk、generate_risk_profile、check_gate、write_pr_comment。

**边界**：风险指标越限返回 fail/warning 并进入报告或 CI 结果，不自动触发 QuantCode 产出 Gate；风险组的工具开发仍可使用标准开发工作流。

### 8.5 策略组（strategy）

**工作目标**：在组内使用因子、组合和回测组件进行策略研究与结果分析；生产部署由 Admin 管理面负责。

**典型工具**：select_signals、combine_signals、run_strategy_backtest、riskfolio_qs、vectorbt_qs。部署请求转交 Admin 管理面，不作为策略 Agent 的普通工具。

**边界**：策略业务产品和汇报页面由策略组与报告平台负责；QuantCode 保留组内工具适配、组件发现和契约检查。`/deploy` 不属于策略 Agent 的普通工具面，由 Admin 管理面单独发起。

### 8.6 期权组（options）

**工作目标**：在组内使用期权数据、波动率曲面、Greeks 和期权回测组件。

**典型工具**：build_vol_surface、calc_greeks、run_options_backtest。

**边界**：期权业务模型和专用引擎由期权组维护。QuantCode 不强推某一旧 options 引擎，只登记可用组件和状态。

### 8.7 跨组协作

跨组 handoff 采用 BlackboardState、artifact 引用、通知和可选 ack：

1. A 组任务完成并写入结构化 artifact；
2. 编排层创建 B 组待办或 Blackboard 队列项；
3. 按授权策略通知 B 组负责人；
4. B 组确认后读取被授权字段，不能因为 handoff 获得整个对方 Memory；
5. actor、时间、artifact hash、权限和状态写入 trace/evidence。

原有“模型触发风控”“因子评估完成通知策略组”“数据契约变更通知相关组”等自动化继续保留为能力，但具体业务由对应组和报告/CI 平台承接。

---

## 9. 前端控制平面

### 9.1 主视图

桌面端保留原设计的统一壳和 Compose 视图：

```text
┌─────────────────────────────────────────────────────────────────┐
│ QuantCode · 当前组/角色/连接状态                 [设置] [通知]   │
├──────────┬──────────────────────────────────────┬───────────────┤
│ 会话列表  │ 主对话 + Compose/Activity trace       │ 右侧工作区     │
│          │ User: 我想评估一个 PB×ROE 因子          │ Compose 状态   │
│ idea-1   │ Agent: 已加载 factor 能力摘要           │ 任务树         │
│ idea-2   │ [match-main] → [schema] → [evaluate]   │ Schema 卡片     │
│ + 新会话  │ 工具结果 / artifact / warning / error  │ Memory 摘要     │
│          │ 输入区：文本、文件拖拽、代码粘贴          │ Subagent 状态  │
└──────────┴──────────────────────────────────────┴───────────────┘
```

### 9.2 核心面板

| 面板 | 保留的能力 |
|---|---|
| 首页/任务提交 | 自然语言输入、组/身份状态、Skill 选择、模式入口、文件和代码输入 |
| Compose 视图 | 当前流、节点状态、等待原因、方案阶段、手动暂停/继续 |
| 任务树 | T1/T1.1/T1.2、progress、父子任务和子图状态 |
| Subagent 监控 | 并行任务、日志、预算、单独 kill 和失败重试 |
| Schema 卡片 | Pydantic/JSON Schema 字段、版本、来源、导出和修改入口 |
| Activity | trace 时间线、工具调用、错误、artifact、再次运行和回放 |
| Memory 浏览器 | 组内 Memory、公共契约、checkpoint、任务进度和来源 |
| 因子/PIT 面板 | 只渲染外部 artifact 和契约 warning，不在 UI 重算领域结果 |
| GatePanel | 普通用户只显示 merge/permission 写操作 Gate；Admin 管理面另有生产部署操作 |
| 通知中心 | Gate、跨组 handoff、repo/package Pop、系统状态 |
| 设置/SSH | 本地身份选择、fingerprint 摘要、roster 结果、连接失败和 provider readout |
| Admin 中枢 | 全组运行、错误、Memory/Blackboard、能力状态、报告/任务入口和 GitGraph |
| Dog Food | 组织内部研发素材和周期性外部研究内容 |

### 9.3 Compose 的自动与人工编排

- 自动编排：Agent 按组 Skill、能力目录和当前状态自主选择工具；
- 人工编排：保留 YAML pipeline 编辑器和预览，保存为 .compose-pipeline.yaml；
- 人工干预：用户可暂停节点、补充需求、修改 Schema、确认 handoff 或跳过允许跳过的节点；
- 所有人工操作都写入 trace；跳过节点不代表跳过权限或生产 Gate。

---

## 10. Memory、RAG 与组织知识

### 10.1 Memory 五层 scope

```sql
CREATE TABLE memory_fts (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,
  scope TEXT,
  scope_id TEXT,
  type TEXT,
  body TEXT,
  fingerprint TEXT,
  last_indexed_at INTEGER
);
CREATE INDEX memory_fts_scope_idx ON memory_fts(scope, scope_id);
CREATE INDEX memory_fts_type_idx ON memory_fts(type);
CREATE VIRTUAL TABLE memory_fts_search USING fts5(body);
```

| Scope | 路径 | 用途 | 默认权限 |
|---|---|---|---|
| global | .quantcode/memory/global/ | 全局工程规则和公开契约 | 登录用户可读 |
| projects | .quantcode/memory/projects/<hash>/ | 项目级跨组知识 | 项目授权用户可读 |
| groups | .quantcode/memory/groups/<group>/ | 研究结论、错误、组件用法和 Best Practice | 本组共享，Admin 全可见 |
| sessions | .quantcode/memory/sessions/<thread_id>/ | 会话记录和 checkpoint | 会话参与者，Admin 按审计访问 |
| tasks | .quantcode/memory/sessions/<sid>/tasks/<tid>/ | 任务 progress 和 handoff | 任务授权范围；写入 API 待补齐 |

Memory 是知识检索层；Blackboard 是结构化状态层，契约包含 GLOBAL、PROJECT、GROUP、SESSION、TASK 五级 scope。当前跨组协作主要使用 PROJECT，组内共享主要使用 GROUP；SESSION/TASK 由 checkpoint 和任务进度使用，GLOBAL 只放公开组织级配置。两者都支持组隔离，但 API、生命周期和写入语义不同。

### 10.2 类型、来源和晋升

保留 memory、checkpoint、progress、notes、feedback、project、reference、user 等类型。长期知识必须有来源、更新时间、适用条件、验证状态、owner 和 superseded 关系。

原始 trace、模型猜测和未验证输出只能标为候选。Dream/Distill 可以自动生成候选，但长期 Memory 或正式 Skill 必须经过确定性检查、领域负责人确认或显式候选标记。

### 10.3 Reconcile 与搜索

磁盘 Markdown 与 SQLite 索引双向同步：

- reconcile 通过 size/mtime fingerprint 识别变化；
- 变化文件自动 UPSERT，删除文件自动 prune；
- memory_search 必须走真实后端通道，未接通时返回明确空态，不能用 fixture 冒充结果；
- FTS5/BM25 支持中文和字段过滤，跨组查询先做 ACL Mask 再排序。

示例：

```python
memory.search(
    query="PB-ROE 因子",
    scope="groups",
    scope_id="factor",
    type="memory",
    limit=5,
)
```

### 10.4 RAG 与时点安全

ChromaDB 可存研究报告、主线代码片段和历史 session 摘要。所有文档带 published_at 或等价时间字段，检索时按 as_of 过滤，避免 lookahead bias。RAG 结果必须标来源、时间和置信状态，不能替代 DataAccess 或 QuantEvaluator 的权威输出。

### 10.5 组内共享与跨组 Mask

同一组成员共享该组的已知信息，包括研究结论、失败记录、组件细节、数据口径和开发 Best Practice。普通用户不能搜索其他组的详细 Memory；跨组只通过公共契约、脱敏摘要、授权 Blackboard 或一次性 permission Gate 暴露。Admin 可以查看和管理全部组内容，但敏感访问留痕。

---

## 11. HumanGate、生产部署与黑盒适配

### 11.1 Gate 触发与 resume

```text
Agent 请求副作用工具
        ↓
服务端检查 actor/group/role、资源和工具权限
        ↓
若为 merge/permission 写操作 → 创建 HumanGate；生产部署由 Admin 管理面单独发起
        ↓
interrupt，返回 payload 与 evidence 摘要
        ↓
授权 approver/Admin approve/reject
        ↓
resume 或 fail-closed 终止写操作
```

研究输出、报告生成、风险阈值、评估失败、普通代码修改和 CI review 不进入该流程。拒绝必须终止对应写操作，批准必须记录 actor、时间、理由、资源范围、artifact hash 和结果。

### 11.2 /deploy 黑盒适配器（Admin 专属）

```text
已调试开发/研究代码
        ↓
DeployAdapter(source_ref, manifest, contract_version)
        ↓
Admin 管理面确认并提交
        ↓
生产服务账号经受控接口/队列执行
        ↓
artifact + deploy_record_hash + evidence
```

研究员可以通过 SSH 写入自己的服务器个人工作目录，但不获得生产服务账号，也不进入生产 shell。`/deploy` 只在 Admin 管理面可见、可发起和可查询；普通研究 Agent 不调用该工具。适配器只接收最小字段，向 Admin 返回成功/失败、artifact 引用、记录哈希和可操作错误；不能返回 AlphaFlow 内部模块、路径、部署格式或生产拓扑。当前 staging adapter 只验证字段和契约，真实生产 adapter 等外部生产规格确认。

### 11.3 生产环境与权限边界

开发/研究环境的 SSH 读和开发写可由组权限允许；生产系统使用独立服务账号，研究员和普通 Agent 均不能直接进入。生产部署由 Admin 管理面提交到受控服务入口，生产系统负责人维护实际运行、容量、密钥和底层拓扑。QuantCode 负责 Admin 身份、适配请求、必要的审批记录、证据和结果状态，不把生产账号或底层拓扑交给研究员。

---

## 12. Admin、GitGraph、Pop 与可观测性

### 12.1 Admin 中枢

Admin 中枢是组织级管理工作台，保留原设计的自然语言查询和固定面板两种入口：

- “最近每个人/每组的工作情况怎么样”；
- “每个模块运行情况和失败依赖”；
- “各组错误记录和重复故障”；
- “某组件刚更新了什么，哪些任务受影响”；
- 报告管理、任务管理和外部 Report Platform/QuantPlatform 入口；
- 全组织运行、Memory、Blackboard、artifact、能力卡和仓库状态查询。

Admin 查询只能消费 metrics.jsonl、run registry、Memory/Blackboard、GitHub API 和组件观察记录等权威数据，不能从 UI 拼装“看起来合理”的状态。Admin 具有全部可见性和审批权，跨组查询、管理和审批仍保留审计。

### 12.2 GitGraph

GitGraph 保留为全组日常工作入口，并按 GitHub 权限增强：

- 普通用户：显示当前 GitHub 身份可见的全部组织 repo；
- Admin：显示组织权限范围内全部 repo；
- 每个 repo 显示默认分支、分支列表、HEAD、最新提交、提交树/时间线、活跃度、归档状态和依赖文件变化；
- 新提交、分支变化和 package/依赖版本变化节点高亮，可跳回 GitHub；
- API 错误、权限不足、仓库缺失和“确实没有更新”分别表达；
- 返回 observed_at、权限上下文、数据来源和基线版本，避免把错误伪装成空结果。

GitGraph 不按静态“属组 repo”猜测可见性；仓库属于哪个业务组只影响能力卡和业务上下文，repo 可见性遵守 GitHub/组织权限。

### 12.3 Pop 与通知

保留两类重要 Pop：

1. repo 新提交、分支或仓库状态变化；
2. 依赖库/package 版本变化。

Pop 和 GitGraph 使用同一权限边界。每条通知带来源 repo/库名、时间、变化摘要、跳转链接、去重键和已读/确认状态。目标增强包括服务端定期检查、基线保存、重复抑制、应用内通知和系统级通知；没有后台服务时手动检查是降级路径，不能生成示例更新。

### 12.4 Trace、Metrics、Evidence

- execution_trace：用户输入、Agent 思考摘要、工具调用/结果、节点状态、artifact、方案、Gate 和结束状态；
- metrics.jsonl：run、actor、group、flow、状态、耗时、工具数、预算和错误摘要；
- checkpoint 数据库：支持 list/show/resume/replay；
- evidence chain：对关键工具、artifact、Gate、决策和外部响应做哈希链，支持篡改检测；
- 敏感凭据和私钥永不进入 LLM 消息、trace、Memory 或 artifact；
- Admin、UI 和报告平台使用这些结构化记录，不自行推断成功状态。

---

## 13. Dog Food 与内部研发入口

Dog Food 保留为 Agent 组的内部研发能力，而非 QuantCode 领域产品：

- 周期性抓取 GitHub Trending、量化相关公开内容和团队关注源；
- 使用 Firecrawl/Jina Reader 等受控读取方式；
- 落地带来源和时间的 Markdown，进入 Agent 组 Memory 或 Dog Food 面板；
- 周期性 standup 讨论并决定是否蒸馏为能力卡或 Skill；
- 外部内容必须有来源、时间和许可说明，不能混入生产数据或未经验证的长期事实。

---

## 14. 集成与依赖

### 14.1 OpenCode 关系

- Fork：HKUST-QUANT-SOCIETY/opencode，基于 OpenCode 上游；
- 控制平面负责 Desktop UI、session、MCP 接入和可视化；
- QuantCode 业务代码位于本仓库，通过 MCP/tool/skill 接入；
- 上游升级需锁定版本并运行 UI、MCP 和回归 smoke test。

OpenCode 的实现边界以 fork 中的模块为准：`packages/opencode/src/session/` 提供 session、prompt、loop、compaction、retry 和 status；`packages/opencode/src/tool/` 提供文件、Shell、LSP、Web、Task、Skill、Plan、Todo、Question 和截断工具；`packages/opencode/src/mcp/` 提供 MCP client、tools/resources/prompts、连接状态和认证；`packages/opencode/src/permission/` 提供权限判定；`packages/opencode/src/control-plane/` 提供 workspace 路由和同步。QuantCode 只通过稳定接口接入这些底座，fork 升级时必须检查这些边界是否变化。

### 14.2 MimoCode 关系

QuantCode 不依赖 MimoCode 运行时，但保留吸收其成熟设计的路线：Memory、Checkpoint、Task、Subagent、Goal、Dream/Distill 和 15 个通用 Compose Skill 的 markdown 形态（brainstorm、plan、execute、tdd、review、debug 等）。这些 Skill 作为可复用工作流知识注入 Agent，不把 MimoCode 私有服务带入线上；docs/mimocode-reference/ 是设计参考，不能被当作线上依赖或权限权威。

MimoCode 参考代码的可执行边界仅限 `docs/mimocode-reference/memory/` 中的 FTS5 schema、路径解析、安全查询和磁盘/索引 reconcile 设计；其余运行时、账号、远程服务和私有配置不随 QuantCode 发布。移植或改写时保留 MIT attribution，并在 QuantCode 侧补充 group/task scope、ACL、actor 和审计语义。

### 14.3 服务器集成

| 服务器/系统 | 角色 | 接入方式 |
|---|---|---|
| Server A | 数据、因子评估和基础设施 | 研究/开发 SSH 读取主线；HTTP/MCP 调标准服务 |
| Server B | Agent、期权、Sentinel 等能力 | 研究/开发 SSH 读取授权主线；受控服务部署 |
| GitHub Organization | repo、分支、PR、Action 和权限 | 用户身份或组织权限上下文的 API |
| COS | 模型/静态 artifact 存储 | 最小字段 adapter，带版本和 hash |
| Report Platform | 研究与策略结果汇总 | artifact、链接、状态和版本契约 |
| AlphaFlow/生产平台 | 生产执行目标 | Admin 专属 /deploy 黑盒 adapter + 审计 |

### 14.4 技术栈

| 类别 | 选型 |
|---|---|
| 控制平面 | TypeScript、OpenCode fork、Electron、SolidJS、Vite、TailwindCSS；复用 OpenCode 的 Desktop/TUI、会话、Provider 和 MCP 客户端 |
| 编排平面 | Python、LangGraph ReAct、StateGraph、自研运行时加固；承接 MimoCode 的 Task/Memory/Checkpoint/Subagent/Goal/Dream 设计 |
| 执行平面 | Python tools、canonical component adapters、MCP/HTTP clients |
| Schema | Pydantic v2、JSON Schema |
| 数据库 | SQLite、FTS5、checkpoint、Blackboard、去重表 |
| 向量检索 | ChromaDB（带 PIT 过滤） |
| 通信 | MCP stdio JSON-RPC、HTTP、SSE 状态流 |
| 外部系统 | GitHub、COS、SSH gateway、Report Platform、生产 adapter |

---

## 15. 工程功能清单与优先级

### 15.0 F/P 功能映射

以下编号承接原设计和 FUNCTIONAL_SPEC，用于需求、实现和测试追踪。领域业务归属调整只改变 QuantCode 的接入方式，不删除编号对应的 Agent 平台能力。

| 编号 | 功能 | 当前技术位置 |
|---|---|---|
| F-01 | 首页新建研究、MCP run_agent、组内 Compose 路由 | 控制平面 + AgentRunner |
| F-02 | Activity、execution trace、artifact、再次运行和回放 | trace bridge + checkpoint |
| F-03 | HumanGate 写操作门禁（merge/permission；生产部署由 Admin 管理面） | human_gate + permission_engine |
| F-04 | Memory 与组织能力目录 | runner/memory + CapabilityCard |
| F-05 | 设置、供应商 readout、本地 SSH 登录和组绑定 | opencode-lens + identity/roster |
| F-06 | 外部组件登记、评估调用、数据契约检测、Admin 部署适配 | tools/factor + Admin adapters |
| F-07 | 跨组协同与模型风险 CI 基建 | Blackboard + GitHub Actions |
| F-08 | 策略/期权/基本面/组合工具适配层 | tools/* + flows/*，不复制领域产品 |
| F-09 | Monitor、Admin 中枢、GitGraph、Pop | metrics/run registry + Admin UI |
| P-01 | DataAccess 与 FactorPanel/ReturnsDataset 数据契约 | schemas/data_contracts.py + tools/market |
| P-02 | 回测引擎 | tools/strategy，组内工具保留 |
| P-03 | 组合层 | tools/portfolio，组内工具保留 |
| P-04 | 并行 Subagent | tools/subagent + LangGraph subgraph |
| P-05 | 实验管理 | tools/experiments，A/B、OOS 和 ledger |
| P-06 | Evidence Chain 报告 | schemas/evidence_chain.py + runner/evidence.py |
| P-07 | 组织资产蒸馏、能力卡、ACL/Mask 和常驻摘要 | configs/capabilities.yaml + Memory |
| P-08 | Admin 组与组织管理中枢 | admin scope、语义查询、GitGraph、Pop |
| P-09 | Admin 专属 /deploy 黑盒部署适配 | DeployAdapter + Admin 管理面 + evidence |
| P-10 | Solution-First 方案先行与一致性判断 | SolutionDoc、L0-L3、doc_hash |

### 15.1 Agent 引擎能力

| 功能 | 说明 | 优先级/状态 |
|---|---|---|
| Memory FTS5 | BM25、中文检索、reconcile、五层 scope 和组隔离 | P0，基础已存在 |
| 树状任务 | ComposeTask、parent/children、progress、checkpoint 联动 | P0，已存在 |
| 自动 Checkpoint | SqliteSaver、context 阈值 snapshot | P0，已存在/持续加固 |
| Context 重建 | checkpoint + Memory + progress + 最近消息 | P1 |
| Subagent | 并行、预算隔离、生命周期和独立 kill | P1，平台能力保留 |
| /dream | trace 扫描、知识候选和过期处理 | P0/P1，原型保留 |
| /distill | 重复操作识别、Skill 草案 | P1 |
| 预算化注入 | importance ranking 和 token budget | P2 |
| Goal + Judge | 目标完成度和结构化 verdict | P2，基础接口保留 |
| 循环检测 | frequency、error、state fingerprint 和迭代上限 | P0，已存在 |
| Evidence Chain | artifact、决策、Gate 和外部响应哈希链 | P1，已存在 |

命令层保留 /goal、/dream、/distill、/solution 和 compose:verify 等研究/工程入口；`/deploy` 只在 Admin 管理面提供。命令只是控制平面到编排层或管理面的调用协议；权限、状态和领域职责仍由服务端和对应组件决定。

### 15.2 组织能力与平台功能

| 功能 | 说明 | 状态 |
|---|---|---|
| 组身份与 Skill 加载 | SSH fingerprint → roster → group/role → allowlist/Memory | 基础已存在，真实 surface 待完善 |
| 组件能力目录 | gh 调研、CapabilityCard、状态、别名、摘要/详情分层 | 首批已存在，持续核验 |
| 组件调用与契约检查 | 主链选择、Data/PIT/版本/接口检查 | 逐组件接入 |
| 六组 Compose | 同一 ReAct + 六组 Skill/工具/Memory | 保留，逐流完善 |
| Admin 中枢 | 全组运行、错误、Memory、组件、报告和任务查询 | 基础已存在，持续聚合 |
| GitGraph | 权限范围内完整 repo/分支/提交树 | 基础状态已有，完整树增强 |
| Pop | repo/package 变化、基线、去重、已读和通知 | 基础 UI 已有，后台增强 |
| /deploy | Admin 专属黑盒适配器、生产写审计和 evidence | staging 已有，真 adapter 待规格 |
| P-10 SolutionDoc | L0-L3 分级、冻结、conformance verdict | 基础状态机已有，分级需审查 |

### 15.3 领域工具保留策略

tools/strategy/、tools/options/、tools/portfolio/、回测引擎和六组 flow 代码不删除。它们作为对应组的工具适配层和回归对象保留；QuantCode 不把它们重新包装为统一策略/组合/期权产品，也不让平台层复制业务事实。

### 15.4 原有设计的正确归类

| 原有能力/场景 | 在当前设计中的位置 |
|---|---|
| model→risk PR 链 | GitHub Actions/CI 基建和 Blackboard handoff，非独立产品主流程 |
| 风险阈值判断 | 领域评估 verdict、报告/CI 状态，不自动 HumanGate |
| 策略/组合/期权/基本面流水线 | 各组工具和外部报告平台，QuantCode 负责接入和编排 |
| 并行 Subagent、回测引擎、Memory、Checkpoint | QuantCode Agent 平台基础能力，完整保留 |
| 论文研究和算法调优 | 研究员职责；QuantCode 提供组件知识、契约检查和适配支持 |

---

## 16. 验收、测试与运行质量

### 16.1 测试分层

1. **契约测试**：Pydantic、JSON Schema、FactorPanel、LabelBundle、TargetReturnView、adapter 字段；
2. **权限测试**：SSH roster、组锁定、Admin 权威源、GitHub repo 可见性、Memory Mask、跨组 permission；
3. **运行时测试**：ReAct、ToolRegistry、checkpoint、replay、循环、预算、错误降级和去重；
4. **运营路径测试**：组内 Memory 写入/晋升、能力优先复用、缺口先问人、Admin 查询、GitGraph 和 Pop；
5. **六组回归**：各组 flow、外部组件 adapter、PIT/RAG、策略/期权/组合工具保持可运行；
6. **UI/E2E**：登录、组/角色显示、Activity、方案分级、普通 Agent Gate、Admin、GitGraph、Pop，以及 Admin 专属 /deploy 黑盒断言。

每个 Skill 和 Compose flow 可以通过 compose:verify 运行结构化验收。验收输出包括契约版本、工具调用、artifact 引用、通过/失败原因和可重放入口。

### 16.2 不应继续存在的测试前提

以下旧断言需要在后续审查中重分类、改写或删除：

- 风险指标越限必然触发 HumanGate；
- 预算耗尽等同于业务审批；
- 所有普通代码修改都必须 Gate；
- 模型 PR 风控是 QuantCode 的产品主流程；
- QuantCode 自己负责六条领域业务产品；
- 固定全局讨论轮数阻塞 L0/L1 任务；
- 用 mock、fixture 或 UI 拼装结果冒充真实组件接入。

测试通过数必须注明日期、环境和覆盖范围。pytest 全绿只说明当前测试与代码一致，不能单独证明顶层运营设计已经实现。

### 16.3 工程验收目标

- 六组都能完成身份绑定、Skill 加载、Memory 访问和基础任务提交；
- 典型任务能命中 canonical 组件并输出来源、版本和 artifact；
- 长任务可 checkpoint、恢复和回放，循环和错误可见；
- Admin 可跨组查询运行、错误、Memory、组件和 GitGraph；
- 普通用户的 GitGraph/Pop 遵守 GitHub 可见性，Admin 可查看组织范围；
- merge/permission 写操作可 interrupt、审批、拒绝和审计；生产部署只能由 Admin 管理面发起并审计；
- 生产 adapter 不暴露 AlphaFlow 内部结构；
- 组内 Memory 持续沉淀可复用结论、错误和 Best Practice。

### 16.4 质量指标

- Admin 语义查询目标 P95：15 秒以内（以真实数据源为前提）；
- 首轮 L2/L3 方案目标：5 分钟以内，不含代码实现；
- 任务恢复后状态和 artifact 可重现；
- Pop 去重、已读和跳转状态一致；
- 错误、降级和权限拒绝不伪装成成功或空结果。

---

## 17. 风险与对策

| 风险 | 对策 |
|---|---|
| OpenCode 上游升级破坏控制平面 | 锁定版本，CI 运行 MCP/UI smoke test |
| MimoCode 参考代码带入私有依赖 | 只吸收模块设计，移除私有服务依赖 |
| 组件近名仓导致 Agent 误选 | 能力卡 status、canonical_repo、deprecated_aliases 和负面清单 |
| 组身份被参数或前端覆盖 | 服务端 session 固定 group/role，后端二次校验 |
| 组内 Memory 泄露跨组细节 | scope + ACL Mask + Admin 审计 + 公共契约分层 |
| 生产底层信息泄露 | /deploy 最小字段和黑盒错误面；不开放研究员生产 shell |
| HumanGate 重新泛化为所有动作 | Gate kind 白名单和纯研究零 interrupt 回归测试 |
| 预算/循环导致长任务异常 | checkpoint、truncate、fingerprint 和显式停止状态 |
| 数据口径漂移 | DataAccess/TargetReturnView 唯一取值源和契约 warning |
| 真实组件未接通却显示成功 | status、_fallback、_is_mock、来源和 observed_at 显式返回 |
| GitGraph 权限被中心 token 放大 | 使用用户/组织授权上下文，返回权限来源 |
| 学生时间不稳定 | 关键 track 设置主副 owner，文档和 evidence 可交接 |

---

## 18. 术语表

- **AgentRunner**：QuantCode Python 编排层的 LangGraph ReAct 运行时。
- **Compose**：按组加载 Skill、Tool Allowlist 和 Memory 的工作流编排模式。
- **SKILL.md**：描述一个可复用工作流或能力的 Markdown 文件。
- **Subagent**：由 Orchestrator 创建的有界子任务执行者。
- **Schema**：Pydantic/JSON Schema 强类型契约。
- **Blackboard**：跨组结构化状态传递层，与 Memory 检索层分离。
- **Memory**：组织知识、会话、任务和进度的持久化检索层。
- **PIT**：Point-in-Time，保证研究只使用当时可见信息。
- **Artifact**：带来源、版本和 hash 的结构化结果或文件。
- **HumanGate**：对共享写入和跨组授权进行 interrupt/resume 的人审契约。
- **CapabilityCard**：组织组件的用途、接口、状态、权限和复用纪律摘要。
- **Canonical component**：某一领域唯一优先复用的权威组件。
- **Dream / Distill**：从 trace 提取组织知识和 Skill 候选的自我进化能力。
- **Pop**：repo/package/任务/审批等变化的应用内或系统通知。

---

## 19. 团队分工与交付物

### 19.1 Track 划分

以下分工沿用原设计，具体 owner 可在任务交接时更新；职责归属不能越过领域权威和组织权限边界。

| Track | 主 Owner | 副 Owner | 范围 |
|---|---|---|---|
| T0 地基 | 用户（Lead） | - | OpenCode fork、MimoCode 能力吸收、Compose 脚手架、Schema、Acceptance、CI/部署、去重 |
| T1 模型/跨组发起 | 陈镇鸿 | 肖骥超 | ModelSpec、Modeling 接入、COS artifact、Blackboard handoff、CI 元数据 |
| T2 风控/跨组接收 | 杨欣琳 | 肖骥超 | RiskProfile、风险计算、CI 风控基建、风险契约 |
| T3a 基本面/PIT-RAG | 用户（Lead） | 刘炽 | PIT-RAG、研究 spec、报告 artifact、基本面工具适配 |
| T3b 期权 | 刘炽 | 用户（Lead） | 期权工具、波动率曲面、Greeks 和组内回测适配 |
| T4 因子评估 | 肖骥超 | 用户（Lead） | FactorEngine/QuantEvaluator 接入、FactorReport、数据契约检查 |
| T5 前端/Compose 视图 | 待定 | - | Desktop UI、任务树、Subagent、Memory、GitGraph、Pop 和 Admin 面板 |

### 19.2 Swimlane 责任边界

每条业务 swimlane 最终都汇入 QuantCode 的 Skill invocation、Python runner、Schema validation、checkpoint/replay 和 acceptance。Owner 负责领域验收与组件契约，不因此获得其他组 Memory 或生产系统的隐含权限。

| Owner/角色 | 主要 swimlane | 负责内容 |
|---|---|---|
| 用户（Lead） | Agent Group / Orchestrate + fundamental + 全局 | 产品范围、公共 Schema、PIT-RAG、报告连接、跨组协调和 runner 基线 |
| 陈镇鸿 | model + 跨组发起 | 文献结构化、ModelSpec、COS artifact、Blackboard handoff、去重工具 |
| 杨欣琳 | risk + 跨组接收 | RiskProfile、风险计算、CI 风控基建和 HumanGate 契约 |
| 刘炽 | options + research artifacts | 期权工具、Greeks、波动率曲面、研报渲染和 artifact |
| 肖骥超 | factor + evaluation | FactorEngine/QuantEvaluator 接入、IC/IR/换手/衰减、FactorReport |
| T5 前端 | Control Plane | Desktop UI、Compose 视图、任务树、Subagent、Memory、GitGraph、Pop 和 Admin |

### 19.3 Lead 责任

- 维护 PRD、FUNCTIONAL_SPEC、QuantCode Design 和跨文档一致性；
- 主持 ComposeTask、BlackboardState、HumanGate 和公共契约评审；
- 维护 PIT-RAG、报告平台连接和跨组协作基线；
- 管理能力目录的 gh 调研、组件状态、legacy 映射和复用纪律；
- 监督 runner、checkpoint/replay、测试和生产适配的边界；
- 对外沟通和版本交接。

### 19.4 核心交付物

| 交付物 | 用途 |
|---|---|
| model-spec.json | 模型训练和 COS/CI 元数据契约 |
| risk.json | 风险计算和 CI/报告输入 |
| factor-report.json | 因子评估证据与横向比较 |
| pit-results.json | 时点检索和数据证据 |
| research-spec.yaml | 研究任务输入和验收条件 |
| research.pdf | 报告平台或外部展示 artifact |
| options-risk.json | 期权风险和 Greeks artifact |
| ci-log.txt | CI 风控基建执行记录 |
| acceptance-report.json | 结构化验收汇总 |
| .quantcode/memory/groups/<group>/MEMORY.md | 组内长期知识、错误和 Best Practice |
| handoff.md | 阶段性交接、决策和遗留 |
| CapabilityCard | 组织组件用途、接口、状态和复用纪律 |
| evidence | Gate、artifact、外部响应和关键决策的审计链 |

---

## 20. 决策日志

| 日期 | 决策 | 说明 |
|---|---|---|
| 2026-06-23 | 载体层不自建，做加法 | 避免被上游变更和合并冲突拖住 |
| 2026-06-27 | 仓库名为 quantcode | 统一项目命名 |
| 2026-06-30 | Fork OpenCode，吸收 MimoCode 好特性 | 不依赖 MimoCode 私有运行时 |
| 2026-06-30 | Compose 是产品编排中枢 | 六组共用 ReAct + 不同配置 |
| 2026-06-30 | 千组千流，不做千人千面 UI | 统一控制平面，组内 Skill/Memory/工具隔离 |
| 2026-06-30 | Pattern 1 + 2 + 5 + 去重保险栓 | 以 Orchestrator、Blackboard、Gate 和幂等为底座 |
| 2026-07-10 | 编排层定型为 Python/LangGraph | 自研 ReAct 加固、checkpoint、循环检测和算法侧接入 |
| 2026-07-10 | model→risk 采用 Blackboard 队列 handoff | 解耦、可观测、可幂等 |
| 2026-07-10 | 确定性 HumanGate + truncate | 保证写操作可审计，长任务可恢复 |
| 2026-09-01 | 领域产品归各组/报告平台 | QuantCode 保留工具适配和组织编排，不删除引擎代码 |
| 2026-09-01 | HumanGate 收窄到共享写入和跨组授权 | 研究输出、风险 verdict、普通代码和 CI 不作为产出 Gate；生产部署走 Admin 管理面 |
| 2026-09-01 | 增加组织资产蒸馏、Admin、/deploy、P-10 | 解决最大复用、进展透明、部署适配和工程质量问题 |
| 2026-09-03 | 按业务组登录，组内 Memory 共享 | roster 固定 group/role，跨组按 ACL 和公共契约共享 |
| 2026-09-03 | Admin 是组织级角色 | Admin 拥有全部可见性、管理和审批权；业务组仍保持六组 |
| 2026-09-03 | 桌面 SSH 使用本地公钥身份 | 私钥不出本机，服务端 fingerprint 匹配 roster |
| 2026-09-03 | GitGraph 按 GitHub 权限增强 | 普通用户看可见 repo，Admin 看组织范围，保留完整树和 Pop 目标 |
| 2026-09-03 | 组件主链以 gh 和组件指南为准 | 能力卡记录 canonical、状态、依赖、消费者和 legacy 映射 |
| 2026-09-03 | P-10 按复杂度分级 | L0/L1 不被固定讨论轮次阻塞，L2/L3 才强制方案与冻结 |
| 2026-09-03 | OpenCode/MimoCode 作为 Agent 底座 | Design 明确区分上游原生能力、MimoCode 可移植设计和 QuantCode 自有增量；不重复造 session/tool/MCP/Memory/Task 基础设施 |
| 2026-09-03 | SSH 身份自动进入组页面 | 公钥指纹命中公司 roster 后自动绑定 actor/group/role/workspace；UI 不提供自由切组，任务参数不得改组 |
| 2026-09-03 | 工具目录先共享后细分 | 维护员后端注册、审核和发布 Tool/Flow；第一阶段六组共用研究/开发工具集合，未来按权限策略生成 effective tool set |
| 2026-09-03 | 个人工作环境与生产服务账号分离 | 研究员可 SSH 写服务器个人目录；生产由独立服务账号运行，研究 Agent 不进入生产 shell |
| 2026-09-03 | /deploy 归 Admin 管理面 | 普通研究 Agent 不看到或调用部署工具；Admin 通过受控接口提交生产部署并保留审计 |
| 2026-09-03 | v4 文档校审 | 恢复原有 Agent/Compose 基础设计，补齐动态工具目录、任务契约、事件、组件卡和跨文档验收；收敛旧 Gate、自由切组和研究员生产访问语义 |

---

## 21. 多轮审计台账

### 21.1 审计结论

本轮按五个方向反复核对：

1. 原版技术设计的章节、F-01 到 F-09、P-01 到 P-10 和 Agent 基础能力；
2. 组长会议纪要中的运营模式、职责边界、HumanGate、Admin、SSH、Memory、GitGraph/Pop 和组件主链；
3. 当前 runner、tools、flows、schemas、configs、MCP 入口和六组 Skill；
4. `opencode-lens` 控制平面的 UI、结果契约、角色、组选择和通知；
5. PyTest、UI 测试、README、旧架构文档和用户手册的断言语义。

**结论**：已知产品功能和 Agent 基础能力在本设计中都有归位，但当前实现尚未达到“零漂移、零越权”的状态。下表是实现前必须保留的差距登记，不能用 `1021 passed` 或 UI 单测全绿替代。

### 21.2 P0：安全或核心语义阻断项

| 编号 | 位置 | 证据与影响 | 必须达到的设计行为 |
|---|---|---|---|
| P0-01 | `quantcode/mcp_server.py:548-575`、`tools/registry.py:162-178` | MCP `tools/call` 直接调用 `registry.call`，没有再次检查当前组 allowlist；调用者可构造未出现在 `tools/list` 的工具名，绕过组边界。 | MCP call 必须由服务端按 session 的 group/role、工具 allowlist 和资源 ACL 再授权；不存在于可见工具面的调用统一拒绝并留痕。 |
| P0-02 | `runner/agent_mcp_tool.py:177-185` | 当前优先级是 `args.group > ctx.group`，调用方可以把已认证会话改成另一组。 | `group` 只能来自认证 session；请求参数只能作为一致性校验，冲突即拒绝；resume 也必须核对原 session。 |
| P0-03 | `quantcode/mcp_server.py:135-151`、`515-530` | 无绑定且无组时会返回全部已注册工具；绑定存在但缺指纹时还可用 `QUANTCODE_ALLOW_UNAUTH=1` 以环境变量兜底。 | 生产模式无 roster/fingerprint 必须 fail-closed；全工具列表只能是显式本地开发模式，并在启动状态中标注，不得进入生产配置。 |
| P0-04 | `runner/routing/router.py:96-126`、`runner/agent_engine.py:256-327` | 风险阈值仍返回 `HUMAN_GATE` 并调用 interrupt；`runner/agent_nodes.py:1148-1196` 又把预算超限变成 `kind=budget` Gate；循环检测还会路由到自动 proceed 的 gate。 | 研究/评估/风险 verdict/预算/循环只产生结果或停止状态；普通 Agent 只保留 merge/permission 写 Gate，生产部署由 Admin 管理面独立执行。旧路径和旧测试必须迁移或删除。 |
| P0-05 | `tools/admin/_register.py:67-79`、`quantcode/mcp_server.py:561-570` | Admin roster 角色需要 `ctx.identity`，但 MCP context 只注入 group；GitHub 查询退化到全局 `GITHUB_TOKEN`，无法证明是当前用户可见范围。 | session 必须同时携带 actor、role、group、GitHub subject/token scope；普通用户 GitGraph/Pop 使用其 GitHub 权限，Admin 才使用组织范围。 |
| P0-06 | `opencode-lens/.../panels.tsx:502-512`、`roles.ts:8-23`、`panels.tsx:442` | UI 仍提供自由切组下拉；Admin/approver 用身份字符串启发式；Gate 按钮只对 `approver` 显示，Admin 无法审批。 | 组/角色由服务端 session 返回；普通用户不能切换未授权组；Admin 具备全部 Gate 操作；前端只渲染后端授权结果。 |
| P0-07 | `opencode-lens/.../ssh-login.tsx:91-126`、`panels.tsx:533-537` | 登录界面要求输入私钥，默认 connect 永远返回 unavailable；尚未使用本机 SSH agent/Keychain 的公钥证明。 | UI 只选择本地 SSH 身份并发起公钥证明；私钥不进入普通输入、后端、LLM、trace 或日志；真实 roster 认证失败要可区分显示。 |
| P0-08 | `runner/compose_executor.py:356-368`、`python -c 'from runner.compose_executor import list_registered_flows'` | 默认导入实际只注册 fundamental/model/options/strategy 四条线性 flow，factor:autoeval 和 risk:gate 不在 FLOW_REGISTRY；“六组流全部可执行”的设计承诺无法由默认入口实现。 | 六个 flow 必须有统一注册入口和启动自检；明确 factor/risk 的 ReAct 与 scripted flow 关系，缺流时启动失败或显式 BLOCKED，不依赖测试手工 import。 |
| P0-09 | `tools/deploy/_register.py:102-113`、`tools/strategy/deploy_strategy.py:22-53` | `/deploy` 和 `deploy_strategy` 当前仍以普通工具注册；前者没有 Admin 角色门禁，后者可直接返回 `deployed: True`。普通研究 Agent 因而可能看到或调用生产部署语义，越过“生产服务账号 + Admin 管理面”的边界。 | 生产部署工具从普通 Agent tool catalog 移出，只在 Admin 管理面注册和执行；服务端强制校验 Admin session，普通 Agent 调用统一拒绝；策略工具只能产出待部署 artifact/状态，不能宣称已部署。 |

### 21.3 P1：闭环、可见性和数据一致性缺口

| 编号 | 位置 | 证据与影响 | 必须达到的设计行为 |
|---|---|---|---|
| P1-01 | `runner/distill/cards.py:81-95,172-194`、`configs/capabilities.yaml` | 已认证组会收到全部卡片和完整 `api_surface`；当前只有 6 张卡，而设计主链要求 12 张并按组 Mask 详情。 | 能力目录按 card ACL 返回摘要/详情；主链 12 卡、专项卡、纪律卡和 legacy 映射都有状态与来源；详情只进授权 Memory scope。 |
| P1-02 | `opencode-lens/.../memory-query.tsx:20-36`、`panels.tsx:1063-1065` | Memory UI 默认 fetcher 恒为 `null`，后端没有真实 `memory_search` MCP surface；页面只能显示占位空态。 | 补真实只读 Memory 查询契约（query/scope/ACL/snippet/score/source），未接通时明确 unavailable，不把占位当已完成。 |
| P1-03 | `schemas/compose_task.py:99-119`、`runner/blackboard.py:107-111` | Blackboard 契约有 GLOBAL/PROJECT/GROUP/SESSION/TASK 五级，但服务只明确隔离 GROUP，其他 scope 读权限过宽或未定义。 | 为五级 scope 分别定义读写、生命周期、owner、公共 key 和跨组规则；PROJECT 只放脱敏公共契约，GROUP 只放组内知识。 |
| P1-04 | `runner/agent_nodes.py:379-448`、`runner/metrics.py:45-79` | tool 异常没有稳定追加到 `errors`；run/metrics 记录常以 `trace_events=None` 写入，metrics 没有 actor 字段，Admin 只能把 thread 当作人。 | 工具错误、降级和 actor/group/role 必须进入结构化 trace/metrics；Admin 的“按人/组”查询必须有真实 actor 映射。 |
| P1-05 | `runner/evidence.py:68-94`、`runner/agent_engine.py:67-83` | evidence append 和 metrics 都是静默 best-effort；关键共享写入或 Admin 生产操作可能成功但没有证据链。 | 查询类旁路可 best-effort；merge/permission 和 Admin `/deploy` 的 evidence 写失败必须阻止写操作或进入明确 `evidence_unavailable` 状态。 |
| P1-06 | `runner/agent_mcp_tool.py:301-321`、`tools/stream/_register.py:42-59` | `attach_stream` 会在整个 `runner.stream()` 返回后补写 JSONL，运行中不会增量显示事件。 | 定义流式语义：事件何时可见、cursor 如何推进、断连如何补读；若仍是 post-hoc，UI 和契约必须明确标注降级。 |
| P1-07 | `tools/admin/_register.py:250-301,336-409`、`gitgraph-panel.tsx:41-64,241-330` | 后端只返回默认分支最新提交和依赖文件 commit；UI 只画 repo 卡片，没有分支/提交树、基线、版本 old/new 或自动 Pop。 | GitGraph 数据契约必须覆盖 repo/branch/commit/tree/dependency diff/permission/observed_at；package Pop 要有版本比较、去重、已读和跳转。 |
| P1-08 | `configs/solution_workflow.yaml:7-16`、`runner/solution_workflow.py:347-438`、`instructions.ts:10-15` | 实现固定 `min_rounds=2`，且 `buildResearchInstruction` 只注入文字，没有真实 L0-L3 分类器；L0/L1 仍可能被全局方案纪律影响。 | 任务分类器、用户显式覆盖和安全兜底要有统一契约；L0/L1 轻量执行，L2/L3 才冻结方案，trivial 豁免要有可审计依据。 |
| P1-09 | `configs/capabilities.yaml:23-96`、组件指南和 `docs/audit/ASSET_INVENTORY.md` | 能力卡实现只覆盖 target-return、quant-evaluator、factor-engine、data-access、quant-platform、alpha-flow 六项，主链其他组件没有卡。 | 12 个主链组件、专项组件、纪律层和负面清单必须有生成/更新流程、source_commit、状态、owner、依赖和消费者。 |
| P1-10 | `tools/factor/autoeval.py:9-11,90-106`、`flows/factor_autoeval.py:94-116`、`specs/data/SPEC.md:75-87` | AutoEval 未配置时返回 mock；真实 panel 评估使用因子值变化代理收益；TargetReturnView 只登记元数据，真实目标收益表尚未接通。 | 所有结果必须标明 production/staging/mock/proxy；QuantEvaluator 是唯一评估权威；真实收益表接通前不得把 proxy 或 mock 当生产结论。 |
| P1-11 | `runner/compose_executor.py:356-368`、`flows/*.py`、`runner/agent_engine.py` | AgentRunner 是动态 ReAct，但四条 flow 仍是线性 StateGraph，factor/risk 还有独立路径；若不说明，代码会形成两套编排真相。 | 明确 ReAct 主路径、线性 flow 兼容/CI 路径和注册优先级；同一 flow 的输入、输出、checkpoint、Gate 和 artifact 契约必须一致。 |
| P1-12 | `pyproject.toml:36-39`、`README.md:221-260` | setuptools include 没有 `quantcode*`，构建包可能缺 `quantcode.mcp_server`；README 仍写 702 tests、可自由选组、风险超阈值审批等旧语义。 | 把 MCP/identity 包纳入发行物；定义 dev/source、desktop sidecar、版本发布和回滚；README/USER_MANUAL/旧 Architecture 标为历史或同步新契约。 |

| P1-13 | `runner/memory/paths.py:192-257`、`runner/memory/service.py:340-345,414-438`、本文 §10.1 | Memory 的 groups 实际路径是 `.quantcode/memory/groups/...`，tasks 的 build/write/get/delete 仍 `NotImplementedError`；路径文档与实现容易产生双写或查不到。 | 冻结唯一磁盘布局；补齐 tasks scope 或明确只由 checkpoint 管理；reconcile、search、get、delete 和 UI 浏览器必须使用同一 locator。 |
| P1-14 | `schemas/human_gate.py:36-55`、`runner/human_gate.py:109-125` | 设计要求的 kind/resource/actor/evidence/expires_at 不在 HumanGate/InterruptPayload schema；kind 由调用点动态塞入，严格 schema 校验时字段面不一致。 | 统一 Gate envelope 和 interrupt payload 的版本化 schema，明确哪些字段是展示扩展、哪些字段必须进 evidence；普通 Agent 校验 merge/permission，Admin 管理面单独校验 deploy。 |
| P1-15 | `schemas/compose_task.py:143-242`、`tools/model/write_blackboard.py:15-18,38-51`、`runner/compose_executor.py:240-248` | ComposeTask 是完整泛型任务契约，但 ReAct/flow 多使用裸 TypedDict，Blackboard 缺 task_id 时只能合成 T0 占位；任务树和 artifact 归属未真正接线。 | Orchestrator 创建真实 ComposeTask，所有 worker/Blackboard/artifact/metrics 传递 task_id、root_task_id 和 owner_group；T0 只能是明确的开发降级，不可成为生产默认。 |
| P1-16 | `schemas/capability_card.py:44-96`、本文 §7.1/§7.5 | Design 要求的 status、domain_authority、depends_on、consumed_by、deprecated_aliases、observed_at 等字段不在 CapabilityCard schema，`extra=forbid` 会直接拒绝这些字段。 | 先冻结 CapabilityCard v2 schema，再生成 YAML/JSON Schema/Memory/UI；没有字段就不能宣称能力目录已支持状态、依赖和 legacy 追踪。 |
| P1-17 | `tools/admin/_register.py:264-301,349-409` | GitGraph/依赖检查对每个 repo、每个依赖文件串行请求 GitHub，组织规模增长后形成 N+1 请求，无法保证 Admin P95 15 秒。 | 服务端批量抓取、缓存和限流；UI 显示 observed_at/partial 状态；后台巡检与用户查询分离。 |
| P1-18 | `runner/memory/service.py:187-192`、`runner/memory/reconcile.py:148-194` | 每次 Memory search 默认全量扫描磁盘并 reconcile，知识文件增多后查询延迟和 IO 线性增长。 | 改为写入触发/后台增量 reconcile，查询只读已维护索引；全量 reconcile 作为显式维护任务。 |
| P1-19 | `runner/metrics.py:87-104` | `read_recent` 每次把完整 JSONL 文件 `readlines()` 后再取尾部，长期运行会无界占用内存。 | 使用有界 tail、按日期分片或 SQLite run registry，并定义保留/归档策略。 |
| P1-20 | `runner/evidence.py:48-94`、`runner/blackboard.py:181-221` | evidence 每次追加先全量读链；Blackboard 先读后写的 append 不是原子事务，并发 handoff/通知可能丢更新或序号冲突。 | 为 evidence/Blackboard 增加文件锁或 SQLite 事务、并发重试和冲突测试；写操作完成条件包含持久化确认。 |

### 21.4 F/P 完整性检查

| 功能面 | 设计覆盖 | 当前实现判断 | 不能宣称完成的原因 |
|---|---|---|---|
| F-01 首页、run_agent、组内路由 | 已覆盖 | 部分 | group 可覆盖、未认证 fail-open、Skill 下拉仍硬编码 |
| F-02 Activity、trace、artifact、resume/replay | 已覆盖 | 部分 | stream post-hoc，tool error/actor metrics 不完整 |
| F-03 HumanGate | 已覆盖 | 不一致 | 风险、预算、循环旧 gate 仍在；权限隔离不足 |
| F-04 Memory、能力目录、蒸馏摘要 | 已覆盖 | 部分 | memory_search 未接，能力卡 ACL 和覆盖不足 |
| F-05 SSH、身份、组绑定、provider | 已覆盖 | 未完成 | UI 私钥输入、stub connect、真实公钥认证未接 |
| F-06 外部评估、契约检查、部署适配 | 已覆盖 | 部分 | mock/proxy 与真实组件状态混杂，TargetReturnView 未接表 |
| F-07 跨组 handoff、模型风险 CI | 已覆盖 | 部分 | CI/Skill 仍写风险超阈值必人审，需保留为基建但修语义 |
| F-08 六组工具和领域 flow | 已覆盖 | 部分 | 工具保留正确，但 ReAct/线性 flow 双轨需统一契约 |
| F-09 Monitor、Admin、GitGraph、Pop | 已覆盖 | 部分 | Admin identity、普通用户 GitHub scope、完整树和自动 Pop 未闭合 |
| P-01 数据契约/staging | 已覆盖 | 部分 | staging 可测，真实 COS/returns/TargetReturnView 接入未完成 |
| P-02 回测引擎 | 已覆盖 | 组内工具 | 不应删除；不属于 QuantCode 统一业务产品 |
| P-03 组合层 | 已覆盖 | 组内工具 | 不应删除；portfolio gate 需遵守新 Gate 语义 |
| P-04 并行 Subagent | 已覆盖 | 基础存在 | 子任务权限、预算、kill、可观测和端到端恢复需补齐 |
| P-05 实验管理 | 已覆盖 | 基础存在 | A/B、OOS、排行榜和 artifact 需接入统一 trace/Memory |
| P-06 Evidence Chain | 已覆盖 | 基础存在 | 生产写 evidence 不能静默缺失 |
| P-07 组织资产蒸馏 | 已覆盖 | 部分 | 六卡已落，主链全卡和自动晋升/审计未完成 |
| P-08 Admin 中枢 | 已覆盖 | 部分 | Admin role/session/GitHub token 权威链未接通 |
| P-09 /deploy 黑盒 | 已覆盖 | staging | 真适配器依赖外部生产规格；Gate/evidence 语义需统一 |
| P-10 Solution-First | 已覆盖 | 部分 | 真实复杂度分类缺失，固定轮数与新语义漂移 |

### 21.5 必须通过的验收闸门

在实现审查中，以下条件任何一项不满足，都只能标记 `PARTIAL` 或 `BLOCKED`：

1. 未认证请求不能看到或调用非公开能力；MCP call 和 tools/list 两边都 fail-closed；
2. group、role、actor、GitHub subject 和 Memory scope 来自同一认证 session，普通参数不能覆盖；
3. Admin 在 QuantCode 内拥有组织级全可见性、管理和审批权，Admin UI 和后端判定一致；
4. 普通 Agent 只有 merge/permission 才触发 HumanGate；生产部署由 Admin 管理面独立发起并审计；风险 verdict、预算、循环、研报和普通代码修改不触发业务 Gate；
5. 六组的 Agent、Skill、工具、Blackboard、Memory 和 artifact 路径都能按契约回放；
6. 所有 mock、proxy、staging、外部 API 不可用和权限不足状态都显式可见；
7. GitGraph 普通用户遵守 GitHub 可见范围，Admin 查看组织范围；分支/提交树、package diff、Pop 去重和自动检查都有明确数据契约；
8. 组内 Memory 能沉淀研究结论、错误、组件用法、数据口径和 Best Practice，跨组读取按 ACL Mask；
9. PyTest、UI 测试、Skill 文案和旧文档不再把旧 Gate、旧组选择或旧业务归属当成验收前提；
10. Python 包、MCP server、桌面端和外部组件的安装、升级、回滚和配置来源都有可执行的发布/运维说明。

### 21.6 本轮明确不偷偷扩大范围

以下事项属于外部依赖或后续工程，不在本轮技术设计中假装已经解决：

- AlphaFlow 真适配器的生产字段、队列、回滚和容量规格；
- Server A/B 的真实 roster、SSH gateway、硬件密钥和生产服务器策略；
- GitHub App/OAuth/token broker 的组织部署和密钥轮换；
- Report Platform、QuantPlatform 的最终 V1 契约和对外发布页面；
- COS 凭据服务化、真实行情/收益数据源和 staging 与生产数据漂移监测；
- Electron bundled Python sidecar、签名安装包和跨平台发布；
- OS 级系统通知、后台定时任务和长期在线 Pop 服务。

这些事项必须在对应的 deploy/admin/data/product/runbook 文档中有 owner、依赖、环境、回滚和验收，不得只留在本设计的“后续实现”一句话里。

**文档维护**：本文是技术设计基线，不替代领域 SPEC、组件 README、权限策略或生产 Runbook。任何新增功能必须说明所属层、权威组件、输入输出契约、权限边界、失败状态、测试和与四份顶层文档的关系。产品范围变化时，先更新 FUNCTIONAL_SPEC.md 和 docs/PRD.md，再在本文记录架构影响；不得以旧文档、代码或测试的既有行为自动推翻本设计。

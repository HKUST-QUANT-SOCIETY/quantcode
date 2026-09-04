# QuantCode 产品需求文档（PRD）

> **版本**：v5（2026-09-04，QuantCode v5 顶层设计同步）
> **Owner**：Agent Group · HKUST QUANT SOCIETY
> **产品状态**：研究 Agent 平台与组织能力中枢
> **唯一功能基线**：[FUNCTIONAL_SPEC.md](/Users/hendrixchen/Desktop/私募/QUANTcode/specs/FUNCTIONAL_SPEC.md)。本文件说明产品目标、用户和范围。旧版 PRD 与 Day1-5 任务表是历史材料；用户操作说明以当前 [USER_MANUAL.md](USER_MANUAL.md) 为准。

## 0. 产品定义

QuantCode 是按业务组登录的研究 Agent 平台与组织能力中枢，建立在 OpenCode 桌面端和 MimoCode 工作流设计之上。它把组织已有的数据、因子引擎、评估器、模型工具、风险组件和部署入口登记为可发现、可复用、可审计的能力，让 Agent 在研究和工程任务中优先使用已有能力，并把结论、错误、决策和最佳实践沉淀到对应组的共享 Memory。

各研究组和外部平台维护业务真相：报告平台汇总研究成果和策略表现，各组维护算法、回测、组合、期权和基本面业务，生产系统负责实际运行。QuantCode 把这些系统接入研究工作流，提供编排、契约、可观测和组织协作。

### 0.1 产品底座与自有能力

| 来源 | 本项目直接使用的能力 |
|---|---|
| OpenCode | Desktop/TUI、session、Prompt/Context、文件与 Shell 工具、MCP、Provider、Workspace、Permission、消息和状态流 |
| MimoCode | Compose ReAct、通用 Skill、Memory/FTS5、Task、Checkpoint/Replay、Subagent、Goal/Judge、Dream/Distill 的工作流设计 |
| QuantCode | SSH roster 自动绑定组、组内 Memory、动态 Tool Catalog、组件能力卡、Blackboard handoff、Admin、GitGraph/Pop、P-10 和量化组件适配 |

OpenCode 负责桌面和会话底座，MimoCode 提供可移植的工作流设计，QuantCode 负责组织规则和量化接入。三者的职责在设计、实现和验收中分开记录。

## 1. 要解决的问题

### 1.1 组织问题

- 每个组知道自己的资产，但其他成员和 Agent 不知道组织已经有什么，导致重复造轮子。
- 同一数据、标签、复权、评估或训练步骤在不同仓库重复实现，出现口径漂移。
- 研究结论、失败原因和工程决定散落在聊天记录里，下一次任务无法复用。
- 组间进展、错误和组件版本不透明，负责人需要手工询问或逐仓查看。
- 研究代码完成后，个人工作目录、组件仓库和生产服务账号之间缺少清晰的交接边界。

### 1.2 Agent 问题

通用 Coding Agent 可以写代码，但不知道：

- 哪个组件是组织的 canonical 实现；
- 组件当前是生产、测试、研究还是脚手架状态；
- 哪些数据字段和收益标签不能自行计算；
- 哪些内容属于当前组，哪些内容需要授权；
- 何时先向人确认，再决定是否需要自定义实现；
- 如何把已经调试好的代码送进受控部署入口。

### 1.3 运营问题的处理路径

| 问题 | QuantCode 的处理 | 结果归属 |
|---|---|---|
| 组件重复建设 | Agent 先查能力目录和组内 Memory，读取卡片的 `when_not_to_reinvent` | 组件负责人维护 canonical repo |
| 数据和标签口径漂移 | 使用 `DataAccess` 与 `TargetReturnView/v1`，发现裸读或自行计算时返回 warning | 数据仓和领域 SPEC |
| 长任务中断 | 使用 Task、Checkpoint、Context 重建和 Replay，恢复时重新校验权限 | QuantCode 运行时 |
| 跨组交接 | 通过 Blackboard、artifact 引用、通知和可选 ack 传递最小字段 | 发起组、接收组和 Admin 各自负责本域判断 |
| 生产交接 | 研究员写入个人工作目录，Admin 管理面把已调试 artifact 提交给受控部署入口 | 生产系统与服务账号 |

Model→Risk 的代码 PR 风控链继续作为 GitHub Actions 基建运行。它输出结构化报告或 CI 状态，QuantCode 不把它包装成研究员必须进入的产品流程。

## 2. 目标用户与权限角色

### 2.1 业务组

六个业务组使用同一个桌面入口，但登录后获得不同的 Skill、工具、Memory 详情和组件权限：

| 组 | 主要使用 QuantCode 的方式 | 领域真相归属 |
|---|---|---|
| 因子 | 发现因子能力、调用 FactorEngine/QuantEvaluator、组件适配 | 因子算法、评估口径和因子资产 |
| 模型 | 复用特征/切分/训练能力、检查模型契约 | 模型训练、OOS 与模型资产 |
| 风控 | 复用风险模型和风险工具、查看风险结果 | 风险模型、风险约束和风控判断 |
| 策略 | 使用组合/回测适配层和报告平台 | 策略、组合和绩效业务 |
| 期权 | 使用期权组件和适配层 | 期权定价、对冲和回测业务 |
| 基本面 | 使用 PIT 数据与研究资料能力 | 基本面研究和研报内容 |

### 2.2 Admin 角色

Admin 是组织级角色，在 QuantCode 平台拥有无限权限，包括全部可见性、管理、审批和部署发起权：

- 查看所有组的 Memory、Blackboard、任务、运行、错误、能力卡和仓库状态；
- 审批所有已定义的 HumanGate 写操作；
- 管理组织级能力目录、权限映射、通知和运行治理；
- 领域负责人仍对研究结论和业务口径负责；Admin 的管理、审批和部署发起动作必须记录 actor、资源、时间和结果。

### 2.3 游客/未认证

未认证用户只能看到标记为公开的契约和入口信息。组内 Memory、数据字段、内部 API 和生产底层结构需要认证；后端负责最终校验可见性。

## 3. 核心产品体验

### 3.1 登录与组绑定

用户在桌面端选择本地 SSH 身份。私钥留在本机密钥链或 SSH agent，不上传、不写入日志、不进入模型上下文。服务端验证公钥指纹，从公司 roster 匹配 actor、业务组、角色和个人工作目录；会话创建后组身份由服务端固定，任务文本和 `group` 参数不能改写。

研究员通过 SSH 进入被授权服务器上的个人工作目录，读写自己的开发/研究文件。生产环境使用独立服务账号，研究员不直接进入生产 shell；Admin 通过受控管理入口执行部署。

### 3.2 任务提交

用户用自然语言或模板提交任务。Agent 将业务模式、复杂度（L0-L3）、执行策略（plan/build/compose）和治理类别分开判断：

- **只读/查询**：直接查能力、状态、资料或报告（L0、read_only）；
- **有界研究/小修改**：可生成轻量计划，不强制冻结（L1、personal_workspace_write）；
- **架构/多模块**：先形成方案，讨论后冻结，再进入代码阶段（L2）；
- **共享高影响变更**：共享主线/共享资产的 L3 变更，使用 merge/permission Gate；生产部署独立归 `admin_deploy`，仅由 Admin 管理面提交。

用户不需要记住组件调用顺序。Agent 先查组织能力目录和组 Memory，再调用已有组件；能力覆盖不全时先说明缺口并询问用户。

### 3.3 结果与沉淀

每次运行产生结构化 trace、artifact、错误和 Runtime State（Checkpoint、Progress、Task 状态）；这些运行状态不进入长期 Group Memory。研究员看到可验证的结果来源；经确认的结论、失败和组件使用经验可以沉淀到本组 Memory。结果报告和策略表现由报告平台消费，QuantCode 不复制一套报告产品。

### 3.4 Admin 中枢

Admin 以自然语言询问组织状态，例如：

- 最近各组和各成员完成了什么；
- 哪些模块运行异常；
- 哪些组件刚更新；
- 哪些任务卡住或反复失败；
- 某个共享对象的当前状态和来源。

固定面板仍保留，用于快速浏览；语义查询用于跨资源组合和解释。所有跨组查询和审批均需可追踪。

### 3.5 六组 Compose 配置

六个组共享 OpenCode 的桌面、session、工具调用和状态流，也共享 MimoCode 的 Compose ReAct、Memory、Task、Checkpoint、Subagent、Goal/Judge、Dream/Distill 语义。每个组只通过登录会话、Skill、Memory scope 和当前生效工具目录获得差异。

| 流 | 主要步骤 | QuantCode 保留内容 | 业务边界 |
|---|---|---|---|
| `fundamental` | PIT 检索、财务提取、估值、研究资料整理 | `pit_rag_search`、契约检查、artifact、组内适配 | 研究判断和报告发布由基本面组/报告平台负责 |
| `factor` | 主线匹配、FactorSpec、因子计算、QuantEvaluator 证据、资产入库请求 | 能力发现、`FactorEngine`/`QuantEvaluator` 适配、`merge` Gate | 算法调优和最终因子判断由因子组负责 |
| `model` | 模型元数据、训练/OOS、ModelSpec、Blackboard 交接 | Modeling 契约、COS artifact、跨组 handoff | 代码 PR 和 CI 由 GitHub 流程负责 |
| `risk` | 消费结构化输入、风险计算、RiskProfile、CI 报告 | 风险组件适配、结果记录、CI 维护 | 风险 verdict 不触发 QuantCode 产出 Gate |
| `strategy` | 信号组合、组合优化、回测适配、结果分析 | Riskfolio/VectorBT 适配、契约检查 | 策略业务和生产部署由策略组与 Admin 管理面负责 |
| `options` | 波动率曲面、Greeks、期权回测适配 | 工具发现、调用、artifact | 期权模型和专用引擎由期权组负责 |

Compose 流采用同一个 ReAct 运行时。Skill 描述工作步骤，Agent 在运行时选择工具；线性 flow 只作为兼容入口和 CI 基建，输入、输出、checkpoint、artifact 与 ReAct 入口使用同一契约。

## 4. 组织标准组件

组件指南和 `gh` 实读结果是能力目录的事实来源。QuantCode 记录组件的公开 API 和职责，不复制组件内部实现。

### 4.1 Canonical 主链

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

职责边界如下：

| 组件 | 唯一职责 | QuantCode 如何使用 |
|---|---|---|
| DataAccess | 数据、PIT、快照、字段和权限 | 首选数据入口、记录契约 |
| FactorEngine | 因子 DSL 与因子值计算 | 生成/执行标准因子表达式 |
| QuantEvaluator | IC、ICIR、换手、稳定性、区间估计等证据 | 统一提交和消费评估 |
| FactorOptimizer | 因子结构、窗口和 treatment 搜索 | 编排搜索、保存试验关系 |
| FactorAssets | 因子身份、去重、聚类、生命周期 | 资产登记和查询 |
| FactorPreprocess | 清洗、标准化、中性化、FeatureBundle | 模型输入准备 |
| Modeling | 时间切分、purge/embargo、训练和 OOS | 模型训练与治理 |
| Barra Engine | 风险暴露和协方差 | 风险模型输入 |
| Riskfolio-QS | 组合约束和优化 | 组合适配层 |
| VectorBT-QS | fast/accurate 回测执行模拟 | 最终回测适配层 |
| QuantPlatform | DTO、RBAC、Job、Workflow、Artifact 和审计 | 平台集成正门 |
| Platform Web | 只读展示 | 统一研究门户 |

AlphaProbe、CogAlpha、FactorMiner、Factor Research DB、Sentinel、PaperRAG、Quant Knowledge Graph 等属于挖因子、研究智能或专项组件；它们可以被登记和复用，但不自动成为上述主链的权威。`alpha_flow` 在生产接口冻结前只按 scaffold/部署目标登记。

### 4.2 关键选择规则

```text
已有因子值 / FactorPanel → QuantEvaluator
没有因子值 → DataAccess → FactorEngine → QuantEvaluator
需要搜索优化 → FactorOptimizer
需要因子资产治理 → FactorAssets
需要模型输入处理 → FactorPreprocess
需要训练与 OOS → Modeling
需要生产组合回测 → Riskfolio-QS → VectorBT-QS accurate
```

目标收益等前向标签直接取数据仓表值，当前口径为后复权、`Horizon ∈ {1,5,10,20}`、`t+1 → t+2`。严禁业务仓自行重算。

## 5. 产品范围

### 5.1 QuantCode 负责

- 组身份、角色和权限边界；
- Skill、能力目录和组内 Memory；
- Agent 任务编排、上下文注入、Checkpoint、trace、回放和错误记录；
- 组件发现、调用、契约检查和适配；
- 方案先行工作流；
- Admin 中枢、GitGraph、Pop 和运行治理；
- Admin 专属生产部署黑盒入口和部署审计；
- 与报告平台、COS、GitHub、数据层和组件仓库的契约化连接。

### 5.1.1 保留的通用 Agent 基础能力

这些能力来自 OpenCode/MimoCode 底座，属于 QuantCode 的运行基础：

- Desktop/TUI、session、Prompt/Context、文件、Shell、LSP、Web、Task、Skill、Plan、Todo、Question 和状态流；
- MCP、Provider、Workspace、Permission、插件、命令和工具结果回流；
- Compose ReAct、15 个通用 Compose Skill、Memory FTS5/BM25、Task 树、Checkpoint/Replay、Context 重建、Subagent、Goal/Judge、Dream/Distill；
- Pydantic/JSON Schema 契约、动态 Schema、Blackboard、trace、metrics、evidence、幂等键和副作用去重；
- LangGraph AgentRunner 的迭代上限、循环检测、预算、降级、恢复和回放。

QuantCode 在这些能力之上增加 roster 组绑定、组内 Memory、动态 Tool Catalog、量化组件能力卡、Admin、GitGraph、Pop、跨组 handoff 和 P-10 方案分级。

### 5.2 各组/外部平台负责

- 领域算法和业务判断；
- DataAccess、FactorEngine、QuantEvaluator 等 canonical 组件的实现与发布；
- 策略、回测、组合、期权和基本面业务产品；
- 报告平台的展示和发布；
- 生产环境实际运行和容量治理；
- GitHub/服务器的底层认证和 repository 权限权威源。

### 5.3 明确不做

- 不做统一策略/回测/组合/期权定价产品；
- 不做报告平台的复制品；
- 不做论文复现和研究算法调优助手；
- 不做新的数据基建、评估器或因子 DSL；
- 不让研究员直接进入生产 shell；
- 不把所有任务强制变成人工审批或固定两轮流程；
- 不用前端隐藏、环境变量或模型自觉代替后端权限控制；
- 不把能力目录登记、仓库扫描误称为组件已经完成接入。

## 6. HumanGate 产品语义

HumanGate 只处理普通 Agent 发起的共享写入和跨组授权：

| 写操作 | 结果 |
|---|---|
| 主线/共享生产资产入库 | 等待有权限的负责人或 Admin 批准 |
| 受限跨组资源访问 | 按资源 ACL 申请批准 |

研究输出、风控结果、评估失败和 CI 代码审查通过报告或错误状态表达。Admin 可以处理全部 Gate，也可以在 Admin 管理面提交 `/deploy`。部署属于独立的 Admin 管理操作，不生成普通 Agent 的 HumanGate 卡片；Gate 和部署都记录 actor、时间、资源和结果。

## 7. GitGraph、Pop 与可观测性

GitGraph 展示当前用户 GitHub 权限范围内的组织仓库：repo、分支、HEAD、最近提交、变更节点、仓库状态和依赖文件变化。Admin 查看组织范围内的全部 repo。

Pop 分两类：

1. repo 有新提交或重要状态变化；
2. 依赖库/package 版本发生更新。

Pop 遵守同一 GitHub 可见性边界，并记录来源、时间、去重键、已读/确认状态和跳转入口。后台定期检查和基线保存是目标能力，手动检查用于后台服务不可用时的降级路径。

## 8. 成功指标

### 8.1 近期

- 六个组都能完成登录、组绑定和组内 Memory 访问；
- Agent 在典型任务中优先命中 canonical 组件；
- 目标收益和关键数据契约不再被业务仓重复计算；
- 复杂开发任务能留下方案、实现和一致性证据；
- Admin 能查看全组运行、错误和仓库状态；
- 共享写入经过可审计 Gate；生产部署由 Admin 管理面提交并记录。

### 8.2 中期

- 组件目录随真实仓库版本更新而更新，旧仓/别名不会被 Agent 误选；
- 组内 Memory 持续产生可复用条目，失败和错误可被检索；
- GitGraph/Pop 成为日常工作入口；
- `/deploy` 真适配器替换 staging 占位，Admin 可完成部署且不暴露生产底层；
- 测试按当前运营模型分层，旧语义不再被“全绿”掩盖。

### 8.3 里程碑与质量要求

| 里程碑 | 达成标准 |
|---|---|
| M1 地基 | OpenCode/MimoCode 底座接入；ComposeTask、BlackboardState、HumanGate 和领域 Schema 完成评审；六组 Skill 可加载；AgentRunner 可运行 |
| M2 端到端 | 至少一条研究链完成任务、组件调用、artifact、trace、Memory 和回放；GitHub Actions 风控基建保持可运行 |
| M3 横向接入 | 因子、模型、风控、基本面至少三组使用同一运行时；跨组 handoff、数据契约和权限审计可验证 |
| M4 组织闭环 | 六组登录和组内 Memory 可用；Admin 查询、GitGraph、Pop、能力目录和错误聚合进入日常工作台 |
| M5 生产交接 | Admin 管理面通过生产服务账号完成受控部署；部署结果、artifact、版本和证据可回放；普通研究 Agent 无生产 shell |

运行质量要求：一次因子评估（CSI 1000、三年回溯）目标 P95 小于 30 秒；PIT 检索目标 P95 小于 500 毫秒；研报 PDF 目标小于 5 分钟；Admin 跨组查询目标 P95 小于 15 秒；方案首轮输出目标小于 5 分钟。指标必须标注环境、数据规模、观察时间和降级状态。

可观测性要求：每次 run 有 `actor_id`、`group`、`thread_id`、task、工具、版本、耗时、错误、artifact、checkpoint 和状态；关键共享写入与 Admin 部署的 evidence 写入失败时，操作不得显示成功。

### 8.4 功能索引

| 编号 | 产品含义 | 归属 |
|---|---|---|
| F-01 | 新建任务与组内 Agent 路由 | QuantCode |
| F-02 | Activity、trace、artifact、checkpoint 和回放 | QuantCode |
| F-03 | `merge`/`permission` HumanGate；Admin 部署独立处理 | QuantCode 治理 |
| F-04 | 组内 Memory、公共契约和能力目录 | QuantCode |
| F-05 | 本地 SSH 公钥身份、roster 和个人工作目录 | QuantCode + SSH gateway |
| F-06 | 组件发现、调用、适配与契约检查（部署归 P-09） | QuantCode + canonical components |
| F-07 | Blackboard handoff 和 Model→Risk CI 基建 | QuantCode + GitHub Actions |
| F-08 | 策略、期权、基本面和组合工具适配 | 各业务组 |
| F-09 | Admin 中枢、GitGraph、Pop 和运行治理 | QuantCode Admin |
| P-01~P-06 | 数据契约、回测/组合组件适配、Subagent、实验和 evidence | 平台/各组按表执行 |
| P-07~P-10 | 组织知识候选蒸馏、Admin、Admin-only `/deploy` 和方案先行 | QuantCode |

## 9. 后续审查顺序

1. SSH 身份、组绑定、Admin 权威源和 GitHub repo 权限；
2. 组内 Memory、能力目录和组件状态同步；
3. Agent 组路由、P-10 复杂度分级和复用纪律；
4. HumanGate 收窄与生产部署边界；
5. 组件调用链和数据口径；
6. GitGraph、Pop、Admin 聚合和报告平台接口；
7. PyTest、Skill、README 和 UI 的旧版本遗留清理。

## 10. 修订记录

| 日期 | 变更 |
|---|---|
| 2026-09-01 | v2：平台红线、HumanGate 收窄、P-07/P-08/P-09/P-10 定版 |
| 2026-09-03 | v3：根据组长会议与组件指南重建运营模型、组件边界、SSH/生产边界、Admin 权限和 GitGraph 目标 |
| 2026-09-03 | v4：补齐 OpenCode/MimoCode Agent 底座，明确动态工具目录、个人工作环境、生产服务账号和 Admin 专属部署 |

# QuantCode 功能规格（FUNCTIONAL_SPEC）

> **版本**：v0.5（2026-09-04，QuantCode v5 顶层设计同步）
> **Owner**：Agent Group · HKUST QUANT SOCIETY
> **文档性质**：QuantCode 的活功能规格。`docs/PRD.md` 说明产品目标，`docs/QuantCode_Design.md` 说明技术设计，`docs/UI_DESIGN_SPEC.md` 说明桌面端体验；三者服从本文的运营边界。`docs/archive/pre-v5/` 下内容与旧版 PRD/Design 是历史材料。
> **实现状态说明**：本文的状态只表示当前实现证据，不代表设计已经完成。后续功能审查应以本文的“规范要求”逐项核对代码、UI 和测试。

---

## 0. 平台红线

1. **QuantCode 是研究 Agent 平台与组织能力中枢。** 策略、组合、回测、期权定价和基本面报告由各研究组及报告平台维护；QuantCode 负责让 Agent 认识、复用、编排、验证和记录这些能力。
2. **登录决定业务组。** 用户通过本地 SSH 身份登录，服务端按公钥指纹匹配公司 roster，绑定 actor、业务组、角色和个人工作目录。会话内组身份不能由任务文本或普通参数改写。每个组共享本组 Memory，跨组只通过公共契约、脱敏摘要和授权 Blackboard 条目协作。
3. **先复用组织能力。** Agent 制定方案前检索能力目录、组级 Memory 和数据/工程契约。已有能力覆盖不足时先说明缺口并询问用户。
4. **HumanGate 处理共享写入和跨组授权。** 研究结果、风险指标、评估失败、研报、普通代码修改和 CI 审查由各组或外部平台处理。主线资产入库和受限跨组资源访问需要明确确认并留痕；Admin 管理面使用独立服务账号执行生产部署，普通 Agent 不参与。
5. **方案先行按复杂度启用。** 架构性、多模块和跨系统任务先形成方案；查询、只读分析、小修改和实验直接执行。方案阶段不等同于审批流程。
6. **权限跟随权威身份。** 普通用户只能看到其 GitHub 身份和组权限允许的 repo、Memory、组件详情和任务；Admin 跨组查看组织内容。前端隐藏不构成安全边界，后端和外部服务必须再次校验。
7. **研究员使用个人工作环境。** 研究员可以 SSH 进入被授权服务器上的个人目录并写代码。生产环境使用独立服务账号，研究员不取得该账号、不进入生产 shell；Admin 管理面负责发起 `/deploy`。

### 0.1 v5 决策锁

| ID | 不变量 |
|---|---|
| D-001 | 一个 Session 只绑定 roster 签发的一个业务组。 |
| D-002 | 同组共享经确认的长期 Memory；其他组默认不可读详情。 |
| D-003 | Agent 制定方案前查询 Capability Catalog 与 Group Memory。 |
| D-004 | 部分/无能力覆盖时说明缺口并取得用户决定。 |
| D-005 | Agent 负责发现、编排、适配、契约检查和记录，不替代领域判断。 |
| D-006 | 普通 HumanGate 只有 `merge`、`permission`。 |
| D-007 | Admin 在 QuantCode 管理面拥有全组织权限且操作留痕。 |
| D-008 | 普通研究员和 Agent 不进入生产环境。 |
| D-009 | `/deploy` 只属于 Admin 管理面。 |
| D-010 | SSH 私钥只留在本机 Agent/Keychain。 |
| D-011 | GitGraph/Pop 保留完整图、基线、差异和提醒目标。 |
| D-012 | 领域业务真相由 canonical components 维护。 |
| D-013 | 数据与标签契约来自数据层唯一权威。 |
| D-014 | OpenCode/MimoCode Agent 底座能力继续保留。 |
| D-015 | 测试服从当前规范，旧断言不得反向定义设计。 |

### 0.2 底座能力与 QuantCode 增量

| 来源 | 功能边界 |
|---|---|
| OpenCode | Desktop/TUI、session、Prompt/Context、原生文件与 Shell 工具、MCP、Provider、Workspace、Permission、消息和状态流 |
| MimoCode | Compose ReAct、通用 Compose Skill、Memory/FTS5、Task、Checkpoint/Replay、Subagent、Goal/Judge、Dream/Distill 的可移植设计 |
| QuantCode | roster 组绑定、组内 Memory、动态 Tool Catalog、能力卡、Blackboard handoff、量化组件契约、Admin、GitGraph/Pop 和 P-10 |

功能规格只锁定 QuantCode 的行为和边界。OpenCode/MimoCode 的底座行为由各自实现和版本维护，QuantCode 不复制一套同名基础设施。

## 1. 当前运营模型

### 1.1 任务四维模型

业务模式、复杂度、执行策略和治理类别彼此正交：

| 维度 | 枚举 |
|---|---|
| 业务模式 | `research_analysis`、`engineering`、`component_adaptation`、`admin_operations`、`admin_deploy` |
| 复杂度 | L0 查询；L1 有界任务；L2 多文件/跨仓适配；L3 共享主线或共享资产高影响变更 |
| 执行策略 | `plan`、`build`、`compose` |
| 治理类别 | `read_only`、`personal_workspace_write`、`shared_write`、`cross_group_restricted_access`、`admin_production_action` |

L2/L3 必须形成 SolutionDoc；L0/L1 不得被固定讨论轮次阻塞。L3 不表示生产部署。

### 1.2 五种运行模式

| 模式 | 典型用户 | Agent/系统行为 | 治理方式 |
|---|---|---|---|
| 研究/分析 | 六组研究员 | 查资料、查能力、调用评估器、生成分析和报告引用 | 否 |
| 工程开发 | 六组研究员 | 按任务复杂度形成方案，复用已有组件，生成或修改个人工作环境代码 | 否 |
| 组件适配 | 因子/模型/策略相关成员 | 把已调试代码接到组织标准接口，报告契约违规 | 否；结果交给 Admin 管理面 |
| 生产变更 | Admin | 通过 Admin 管理面和生产服务账号执行受控部署 | Admin 操作审计，不进入普通 Agent Gate |
| 运营管理 | Admin | 查看所有组的任务、错误、组件、Memory、Blackboard、GitGraph 和通知 | 查询不需要；审批动作仍留 Gate 记录 |

### 1.3 Agent 参与边界

**Agent 应做**：识别任务类型；检索能力目录和组级 Memory；优先选择标准组件；在需要时询问人；组合只读工具和适配器；执行数据、PIT、版本和工程契约检查；把运行状态、错误、产物和决策写入可追踪记录；把需要生产处理的 artifact 交给 Admin 管理面。

**Agent 不做**：替研究员决定研究问题或投资结论；替研究员完成算法调优和科学判断；重写已有 `DataAccess`、`FactorEngine`、`QuantEvaluator`、`Modeling`、组合/回测组件；把内部评估器当作自己的实现；绕过权限或把生产 SSH 凭据交给模型；把一次性聊天内容自动当成长期事实。

**人和领域组件负责**：研究员负责问题、假设和结果解释；各组负责人负责本域算法、指标口径和业务验收；标准组件负责数据、计算、评估、优化、资产治理、模型、风险、组合和回测；报告平台负责面向研究员或外部产品的汇报；Admin 负责组织级可见性、权限、审批和运行治理。

### 1.4 领域职责边界

| 领域 | 权威职责 | QuantCode 的职责 | 不应越权承担 |
|---|---|---|---|
| DataAccess | 数据读写、PIT、快照、字段和权限 | 登记、选择、契约检查、调用 | 业务仓裸读生产数据或造第二套数据目录 |
| FactorEngine | 因子 DSL、算子和因子值计算 | 发现、调用、适配和记录 | 重造因子语法/算子库 |
| QuantEvaluator | IC、ICIR、换手、稳定性、置信区间等证据 | 发起评估、消费报告、展示来源 | 自算第二套指标 |
| FactorOptimizer | 因子结构和处理方案搜索 | 发现、编排、记录试验 | 把搜索结果伪装成最终因子结论 |
| FactorAssets | 因子身份、去重、聚类、生命周期和资产库 | 适配入库入口、查询 | 维护第二套因子事实源 |
| FactorPreprocess | winsor、rank、zscore、中性化和 FeatureBundle | 选择处理方案 | 各模型重复实现处理逻辑 |
| Modeling | walk-forward、purge/embargo、训练和 OOS | 发现和调用 | 自行决定时序切分口径 |
| Barra/Riskfolio/VectorBT | 风险模型、组合优化、准确回测 | 登记和适配 | 在平台层重新计算业务结果 |
| Report Platform | 汇总、展示、发布研究报告和策略表现 | 提供结构化产物、链接和状态 | 复制报告产品 |
| Admin | 全组织运行治理、权限和审批 | 提供中枢查询和管理视图 | 代替各组做领域研究判断 |

## 2. 共享契约与信息层

### 2.1 组内长期知识 Memory 与 Runtime State

- 同一组成员共享该组 Memory；它应沉淀已验证的研究结论、失败和错误、工程决策、组件用法、数据口径和 Best Practice。
- 全组织契约（例如目标收益 `TargetReturnView/v1`）进入 global/shared 层；不应把组内敏感实现写进公共层。
- `Memory` 在产品语义上只表示可复用、经确认的长期组织知识。会话/任务记录与长期知识分开；Checkpoint、Task Progress、Subagent 状态、原始 Trace、临时摘要、预算和循环状态统一属于 `Runtime State`，不得出现在长期知识列表。原始 trace 只能作为候选来源；经过确定性检查、领域负责人确认或明确标注后，内容才能晋升为长期 Memory。
- 每条可复用知识都应保留来源、时间、适用条件、验证状态和被推翻/替代关系。过期内容标记 superseded，不静默覆盖。
- Admin 拥有全部可见性，可读取和管理所有组 Memory；这类访问应有审计记录。普通组员只能读取本组详情和被授权的共享摘要。

### 2.2 能力目录与组件注册

组件清单以组织仓库实读和 `gh` 可验证信息为准，不能凭会议记忆手写数量。能力卡至少包含：`canonical_repo`、`maturity_status`（PRODUCTION/STAGING/RESEARCH/SCAFFOLD/LEGACY）、`integration_status`（CONNECTED/PARTIAL/UNAVAILABLE/UNVERIFIED）、领域权威、输入/输出、公开 API、依赖、消费者、属组和废弃映射。

当前标准主链：

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

挖因子和研究智能组件（AlphaProbe、CogAlpha、FactorMiner、Factor Research DB、Sentinel、PaperRAG、Quant Knowledge Graph 等）是上游或专项能力，不自动成为主链权威。`alpha_flow` 当前只能作为部署目标的接口/脚手架登记，不能当作成熟生产引擎宣传。

能力目录采用两层投放：

1. **摘要层**：每次 Agent run 注入可见能力的 id、名称、用途和“何时别自造”。
2. **详情层**：通过受 ACL 保护的 Memory/目录查询取得 API、字段和实现约束。

游客或未认证用户只看公开契约；普通组员按 GitHub/组权限看到摘要和被授权详情；Admin 看到完整目录。目录发现不代表运行时已经接入，卡片必须明确 `maturity_status` 和 `integration_status`。

工具目录由维护员后端维护：注册 Tool/Flow、检查 schema 和副作用、发布版本、绑定环境、下线或回滚。第一阶段六组共用研究/开发工具集合；后端保留按 group、role 和 resource 增加 mask 的接口。用户、前端和 Agent 只能消费已发布工具，不能注册或提升权限。`tools/list` 和 `tools/call` 使用同一份 session 计算结果。

### 2.3 数据口径契约

目标收益、前向标签和复权字段以数据仓现有表为唯一取值源。当前定版口径为：`Horizon ∈ {1, 5, 10, 20}`、后复权字段、`t+1 → t+2` 对齐；不得在业务仓自行重算。Agent 只做契约识别和违规提示，不替数据层生成第二套标签。`DataAccess`、`QuantEvaluator` 的实际标签约定必须在能力卡和领域 SPEC 中分别标明，名称相近但语义不同的接口不得混用。

### 2.4 Blackboard、Artifact、Trace

- **Blackboard**：传递结构化跨组状态和脱敏结果；项目共享条目使用 `shared.*` 命名；组私有条目不能因普通查询泄露。
- **Artifact**：保存报告、评估、方案、部署记录和其他二进制/大对象；Blackboard 只保存引用和必要摘要。
- **Trace/metrics**：记录 run、工具、错误、耗时、版本和状态，供 Activity、Admin 和回放使用。运行指标带脱敏的 `actor_id`/组信息，支持按人查看；`thread_id` 只标识会话。

## 3. 现有功能（F-XX）

### 3.0 功能状态和共用契约

`F-XX` 描述用户可见或运行时必须保留的能力，`P-XX` 描述扩展、增强或待接入能力。状态分为 `IMPLEMENTED`、`STAGING`、`PARTIAL` 和 `BLOCKED`。`IMPLEMENTED` 只表示代码和测试已有证据，不能替代身份、权限、外部服务和生产环境验收。

所有组流共用以下接口：

| 契约 | 最小字段 | 用途 |
|---|---|---|
| `ComposeTask` | `task_id`、`root_task_id`、`parent`、`owner_group`、`goal`、`status`、`artifacts` | 任务树、预算和回放归属 |
| `BlackboardState` | `scope`、`namespace`、`producer`、`consumer`、`schema_version`、`payload_ref`、`updated_at` | 组内状态和跨组 handoff |
| `RunAgentResult` | `status`、`thread_id`、`execution_trace`、`output_data`、`artifacts`、`errors`、`gate` | 控制平面与 AgentRunner 的结果回流 |
| `HumanGate` | `gate_id`、`kind`、`resource`、`actor`、`decision`、`evidence`、`expires_at` | `merge`/`permission` 写操作的 interrupt/resume |

契约由 Pydantic v2 维护，并导出 JSON Schema。子任务、artifact、metrics 和 Blackboard 条目必须携带任务归属；恢复 checkpoint 时重新校验当前 session 权限。

### F-01 新建任务与组内 Agent 路由

首页提交任务，服务端从已认证会话得到组身份，加载该组 Skill、能力摘要和可用工具。允许显式选择 Skill，但不能用 `group` 参数越权切换组；多组授权必须来自服务端 roster。`list_skills` 应来自真实目录。

**当前实现**：MCP `run_agent`、SSH challenge/roster 后端、会话组锁定和 `tools/list`/`tools/call` 共用的 effective catalog 已有；桌面身份选择与连接 surface 仍依赖外部 `opencode-lens`。

**验收补充**：提交请求只能使用认证 session 的 `group`；请求中出现不同组时拒绝；`tools/list` 与 `tools/call` 必须使用同一份 effective tool set；无 roster 的生产请求 fail-closed。Skill 列表来自维护员发布目录，不能由用户输入或 Agent 运行时注册。

### F-02 执行记录与回放

Activity 显示思考、工具调用/结果、产物、错误、方案状态、Gate 和 checkpoint；同一 `thread_id` 的事件可去重合并，支持从 checkpoint 回放。服务端历史应与本地缓存区分，避免跨用户泄露。

**当前实现**：trace、metrics、checkpoint、context rebuild 和 replay 后端已有；Admin 运行查询和 actor/role 记录已有，服务端历史的完整 UI surface 仍依赖外部桌面端。

**事件要求**：至少支持 `agent_start`、`skill_loaded`、`node_update`、`decision_summary`、`tool_call`、`tool_result`、`artifact`、`error`、`checkpoint_snapshot`、`human_gate` 和 `agent_end`。事件使用 `thread_id + iteration + seq` 去重，mock、proxy、staging、降级和权限拒绝必须保留原状态。

### F-03 HumanGate 写操作门禁

| 触发点 | kind | 规范 |
|---|---|---|
| 因子资产/主线登记等共享生产写 | `merge` | 评估结果只提供依据；实际写入需显式批准 |
| 跨组受限数据/资源访问 | `permission` | 只有权限策略允许的跨组请求可申请批准 |

生产部署由 Admin 管理面发起，生产服务账号通过受控接口执行。部署记录必须保留 actor、目标、artifact、版本和结果，但普通研究 Agent 不调用 `/deploy`。

预算是运行时资源限制：达到上限时告警、停止或进入预算耗尽状态。研究输出、RiskProfile 越限、组合评估失败和 CI 结果通过 `pass/fail`、报告或错误记录表达，不触发产出 Gate。

**当前实现**：`merge`/`permission` Gate、Risk CI verdict、预算/循环停止状态和 Admin staging 部署接口已有；真实生产队列、服务账号和桌面 Admin surface 仍是外部依赖。

**严格边界**：普通 Agent 的 Gate kind 白名单只有 `merge` 和 `permission`。风险、评估、报告、普通开发、CI、预算和循环检测分别返回领域结果、报告、错误或停止状态。Admin `/deploy` 使用独立管理接口和部署审计，不注册为普通 Agent 工具，也不在普通 Agent GatePanel 中生成卡片。

### F-04 组内 Memory 与组织能力目录

提供组级共享 Memory、公共契约、能力卡片、详情查询、来源和版本信息。Mask 按用户组/GitHub 权限执行，Admin 全可见。`memory_search` 必须有真实后端通道；UI 空态不得伪造结果。

**当前实现**：FTS5、Group ACL、显式 reconcile、14 张能力卡、摘要/详情分层和 `list_capabilities` 已有；专用 Memory MCP 查询、完整 Admin UI 和外部组件状态同步仍需接入。

**能力卡字段**：`canonical_repo`、`maturity_status`、`integration_status`、`type`、`domain_authority`、`inputs`、`outputs`、`public_api`、`depends_on`、`consumed_by`、`owner_group`、`visibility`、`deprecated_aliases`、`source_commit`、`observed_at`、`when_to_use` 和 `when_not_to_reinvent`。卡片状态不能用目录存在代替运行时接通。

### F-05 SSH 身份登录

流程为“本地 SSH 身份 → 服务端验证公钥指纹 → roster 匹配 actor/组/角色/个人工作目录 → 建立不可变会话”。私钥只留在本机密钥链或 SSH agent，不进入 LLM、Memory、日志或普通 UI 请求。登录后可读取授权主线、写入个人开发环境；生产环境由独立服务账号运行，不提供研究员直接登录。

**当前实现**：指纹映射、一次性 challenge/signing、SessionContext 和只读状态查询后端已有；桌面登录界面仍需接真实认证/连接 surface，当前 UI stub 不能视为完整登录。

**失败状态**至少区分密钥拒绝、主机不可达、roster 未命中、资源权限不足和身份接线未完成。研究员登录后拥有被授权服务器上的个人工作目录；该目录属于研究/开发环境。生产 shell、生产服务账号和生产进程控制不属于此功能。

### F-06 组件发现、调用、适配与契约检查

因子路径必须区分：

```text
已有因子值 / FactorPanel → QuantEvaluator
没有因子值 → DataAccess → FactorEngine → QuantEvaluator
需要寻优 → FactorOptimizer
需要资产治理 → FactorAssets
需要模型输入处理 → FactorPreprocess
需要训练/OOS → Modeling
```

QuantCode 负责发现、选择、调用、适配、契约检查和记录；评估器负责计算证据；研究员负责算法调优。已调试 artifact 如需生产处理，交给独立的 Admin Deploy（P-09），不属于普通 Agent 功能。论文复现和研究方向调优不属于 QuantCode 功能。

**当前实现**：`eval_from_panel`、真实数据契约、能力卡和 staging adapter 已有；组织组件逐一接入、真实 AlphaFlow adapter 和口径违规 warning 仍需后续接入。

**状态要求**：评估结果必须带 `source`、`environment` 和 `result_status`。`mock`、`proxy`、`staging` 结果不能冒充生产证据。QuantCode 负责选择和记录；QuantEvaluator 负责指标计算；研究员负责算法调优和科学结论；Admin 管理面负责把已调试 artifact 交给部署适配器。

### F-07 跨组协同

“模型 PR 自动风控”不再是 QuantCode 产品场景。模型静态产物走 COS/模型平台，代码走正常 PR 和 GitHub Actions review；保留的 Model→Risk 链是 CI 基建维护，不新增产品 UI。跨组协同由共享契约、能力目录、Blackboard 摘要、Admin 查询和报告平台承接。

**保留的 CI 链**：`read_pr → extract_metadata → generate_model_spec → write_blackboard → trigger_risk_flow → calc_risk → write_pr_comment`。该链在 GitHub Actions 中输出 CI 报告，不能把报告结果转换为 QuantCode HumanGate。

### F-08 组内业务工具适配层

策略、期权、基本面等领域的业务流水线由各组自研。QuantCode 可以保留工具适配、PIT 检索、组件调用和回归测试，但不把这些工具包装成统一业务产品，也不复制报告平台。相关实现状态以各域 SPEC 和组件权威仓为准。

策略、期权和基本面工具可以继续通过 Agent 调用、回归测试和 artifact 记录接入。QuantCode 不在这些工具之上新增统一业务页面、统一指标计算或统一发布流程。

### F-09 Admin、Monitor、GitGraph 与 Pop

Admin 是组织级角色，在 QuantCode 平台拥有无限权限，包括全组织可见性、管理、审批和部署发起权。Admin 可查询所有组的运行、错误、Memory、Blackboard、任务和组件状态；敏感访问、管理、审批和部署动作都要审计。普通组员只能看到其 GitHub/组权限范围内的信息。

GitGraph 的完整目标是：按当前用户权限列出全部可见 repo、分支、HEAD、最近提交和变更节点；Admin 按组织权限查看全部 repo。更新节点高亮，package/依赖版本更新单独显示。Pop 使用同一权限边界，全组可见不等于跨权限可见。

**当前实现**：Admin 元工具、actor/role 运行查询、GitGraph/Pop 契约、基线/去重/read/ack 和本地服务已有；GitHub 后台同步、完整分支树、系统级通知和报告/任务工作台仍依赖外部服务或桌面端。

**权限要求**：普通用户的 GitGraph 和 Pop 查询使用当前 GitHub subject/token scope；Admin 使用组织授权范围。业务组归属只影响能力卡和上下文，不能代替 GitHub repo 权限。错误、权限不足、仓库缺失和服务不可用必须分别返回。

## 4. 计划与扩展功能（P-XX）

计划功能沿用 OpenCode/MimoCode 的 Agent 基础设施，不因产品边界收窄而删除。每项扩展都必须说明所属层、权威组件、输入输出契约、权限边界、失败状态和验收证据。

| 编号 | 设计定位 | 当前口径 |
|---|---|---|
| P-01 | DataAccess/FactorPanel/ReturnsDataset 数据契约与 staging 接入 | 平台消费；真实数据接入仍依赖外部服务 |
| P-02 | 回测组件适配 | 组内工具，不做 QuantCode 产品 UI |
| P-03 | 组合组件适配 | 组内工具，不做 QuantCode 产品 UI |
| P-04 | 并行 subagent | 平台基础设施，必须继承组权限和预算 |
| P-05 | 轻量实验运行记录 | 记录 A/B、OOS、证据和复现关系 |
| P-06 | evidence chain | 运行、产物、Gate 和决策的可验证留痕 |
| P-07 | 组织知识与能力候选蒸馏 | 组件调研 → 能力卡 → ACL/Mask → 常驻摘要 + 详情 Memory；组件状态以实物为准 |
| P-08 | Admin 中枢 | 全权限角色的语义查询、错误沉淀、GitGraph、Pop 和运行治理 |
| P-09 | Admin-only `/deploy` 黑盒适配 | Admin 管理面提交已调试代码，生产服务账号经受控接口执行并留存部署记录 |
| P-10 | Solution-First 与复杂度分级 | 四维任务分类；L2/L3 先出方案，流程控制不改变 HumanGate 范围 |

### P-10 复杂度分级

| 任务级别 | 例子 | 规范 |
|---|---|---|
| L0 只读/查询 | 查组件、看状态、读报告 | 直接执行，记录 trace |
| L1 有界研究/小修改 | 单文件修复、一次评估、参数实验 | 可生成轻量计划，不强制冻结 |
| L2 架构/多模块 | 新模块、跨仓接入、较大功能 | 先产方案，讨论后冻结，再生成代码 |
| L3 共享高影响变更 | 共享主线或共享资产写入 | L2 方案 + evidence；merge/permission 进入 HumanGate。生产部署独立归 `admin_deploy`。 |

### 4.1 计划功能验收要点

| 编号 | 输入/输出契约 | 验收要点 |
|---|---|---|
| P-01 | `FactorPanel`、`ReturnsDataset`、`PITQuery` | 数据必须带 contract version、`as_of` 和来源；无权限请求 fail-closed |
| P-02 | 组内回测适配器 → 回测 artifact | 保留 A 股交易约束和准确回放；QuantCode 不提供统一回测产品页 |
| P-03 | alpha、risk、benchmark、previous positions → target positions/trades | 组合约束和结果由组内组件计算，平台只记录引用 |
| P-04 | `ComposeTask` parent/children → 子任务状态 | 子任务继承 actor、group、workspace、allowlist 和预算，并支持独立终止 |
| P-05 | A/B、OOS、trial ledger → 实验 artifact | 记录数据版本、切分、参数和复现关系，禁止把训练内结果当 OOS |
| P-06 | run、artifact、Gate、决策 → evidence chain | 哈希链可验证；关键写操作证据失败时阻止成功状态 |
| P-07 | 组织仓库实读 → 能力卡、ACL/Mask、组内摘要 | 卡片含 canonical、maturity/integration 双状态、依赖、消费者、别名和复用纪律；目录存在不代表已接通 |
| P-08 | Admin session → 跨组查询、错误聚合、GitGraph、Pop | 非 Admin 拒绝跨组查询；普通用户遵守 GitHub 可见范围；错误不伪装成空结果 |
| P-09 | Admin artifact + manifest → 受控部署请求/结果 | 生产服务账号执行；普通 Agent 不可见、不可调用；结果只返回状态、artifact、记录哈希和错误 |
| P-10 | `SolutionDoc` → frozen 实现 → conformance verdict | L2/L3 先冻结方案；L0/L1 不被固定轮次阻塞；偏离文件面必须报告 |

P-04、P-05、P-06 和 P-10 属于平台基础能力。P-02、P-03 继续保留为组内工具适配。P-09 依赖外部生产接口规格，staging 通过不代表生产完成。

## 5. 可见性与权限矩阵

| 资源 | 普通组员 | Admin | 游客/未认证 |
|---|---|---|---|
| 本组 Memory 详情 | 读写按组策略 | 全部可见/可管理 | 不可见 |
| 其他组 Memory 详情 | 不可见，除非明确授权 | 全部可见，访问留痕 | 不可见 |
| 公共契约/脱敏摘要 | 可读 | 可读写/管理 | 公开部分可读 |
| Blackboard PROJECT 摘要 | 读授权条目 | 全部可读/管理 | 不可见 |
| GitGraph repo | GitHub 身份可见范围 | 组织全部可见 | 不可见 |
| repo/package Pop | 同一可见范围 | 组织全部 | 不可见 |
| 生产写操作 | 无直接权限 | Admin 管理面提交，生产服务执行 | 拒绝 |

## 6. 后续功能审查顺序

先审身份与权限，再审信息沉淀，再审 Agent 运行边界，最后审业务适配：

1. SSH 本地公钥登录、服务端 roster、组锁定、Admin 权威源和 GitHub 权限映射；
2. 组内 Memory 写入/晋升/Mask、能力卡状态和 `memory_search` 通道；
3. HumanGate 收窄、预算语义、P-10 复杂度分级和 `run_agent` 组越权；
4. 组件注册与标准链调用，尤其是 DataAccess、FactorEngine、QuantEvaluator 和 TargetReturnView；
5. GitGraph 全量视图、Pop 基线/去重/自动刷新和 Admin 运行/错误聚合；
6. 最后清理旧 Skill、旧业务流、旧测试断言和文档示例。

PyTest 全绿只说明测试与当前代码一致。凡是断言风险越限 HumanGate、预算审批、研究产出 Gate、模型 PR 产品流、普通 Agent 调用 `/deploy` 或六条业务流属于 QuantCode 主产品的测试，都要重新分类：保留为底座回归、改写为新语义，或删除。

## 7. 设计变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-01 | HumanGate 收窄为写操作；模型 PR 降级为 CI；业务流水线归组内；新增 P-07/P-08/P-09/P-10 |
| 2026-09-03 | 根据组长会议与组件指南重建运营基线：组内 Memory、组件权威与复用纪律、Admin 全权限、GitHub 权限一致、SSH 不进生产、GitGraph 全增强、方案按复杂度分级 |
| 2026-09-03 | v0.4 文档校审：补回底座 Agent 能力、六组 Compose 契约、事件与任务归属、组件卡字段、CI 保留链和 P-01~P-10 验收；部署与普通 Agent Gate 分离 |

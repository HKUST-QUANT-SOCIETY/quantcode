# QuantCode 功能规格（FUNCTIONAL_SPEC）

> **版本**：v0.2（2026-09-01，功能定版会议）｜**Owner**：Agent Group
> **声明**：本文件是 QuantCode 功能规格的**唯一活文档**。`docs/PRD.md`（v2）描述产品方向与边界；`docs/Day1~5_*`、`docs/Day5_Feature_Checklist.md` 一律为**历史快照**，不再更新，状态以本文件为准。长期路线见 `docs/audit/ROADMAP_LONGTERM.md`，域级设计见 `specs/<域>/SPEC.md`（规范见 `specs/SPEC_GUIDE.md`）。
> **编号**：现有功能 F-01…F-09，计划功能 P-01…P-10。跨文档引用一律用编号。后端 = 本仓库根；UI 仓库 = `opencode-lens`（前端路径 `packages/app/src/components/quantcode/` 相对 UI 仓库根）。
> **修订记录**：v0.1 初始（F-01..F-09 / P-01..P-06）。v0.2 功能定版——F-03 HumanGate 收窄为写操作门禁；F-04 升级为组织能力目录；F-05 改为完整 SSH 登录界面；F-06 重定义（外部评估器注册 + 契约遵守检测 + 部署适配）；F-07 "模型 PR"场景取消（降为 CI 基建）；F-08 降级组内工具（引擎代码保留）；F-09 升级 Admin 中枢语义层；P-07/P-08/P-09 新增；P-02/P-03 降级组内工具。v0.2.1 补录 **P-10 方案先行工作流**（任务先出方案、2-3 轮讨论、冻结静态文档、代码按文档生成并做一致性判定——流程阶段约束，非权限门禁）。

---

## 0. 平台红线（2026-09-01 定版）

1. **QuantCode 不做业务层面的东西**：策略、回测、组合、期权定价等产品功能归各研究组自研与报告平台（报告平台可并入对外产品 2，非核心竞争力）。QuantCode 定位为研究面的 Agent 平台与组织能力中枢。
2. **最大复用原则**：能复用则复用。Agent 制定方案时首选已登记能力（P-07 能力目录）；已有能力覆盖不全时**先向人征询，不许直接跳自造方案**（"可能是表述不清，改完 Factor Engine 就能完整满足需求"）。
3. **HumanGate 只管写操作**：研究面产出不 gate（人本来就要看，报告平台承接）、代码不 gate（CI/PR 流程承接）；只有写操作进入生产面才 gate（见 F-03）。
4. **方案先行（P-10）**：任何非平凡任务先出完整解决方案，经 2-3 轮讨论冻结为静态文档，代码按文档生成并做一致性判定；冻结前代码工具不可用。流程阶段约束，不是权限门禁。

---

## 第一部分：现有功能（F-XX）

### F-01 新建多智能体研究（lens 首页 → run_agent）✅
**用户故事**：作为任一组研究员，我想在品牌壳首页输入研究任务、选组与 Skill 并一键提交，以启动本组 Multi-Agent 研究流，不必记忆 MCP 命令。

**契约**：UI `RunAgentResult`（`result-contract.ts`：status/thread_id/gate/execution_trace/output_data/artifacts）↔ 后端 `RunAgentArgs`（`runner/agent_mcp_tool.py`：task/group/skill_name/max_iterations/thread_id/decision，start/resume 两阶段）。组枚举 `GroupName`（`schemas/compose_task.py`）。

**数据流**：`panels.tsx::QuantCodePanel`（⌘⏎ 提交）→ `instructions.ts::buildResearchInstruction`（强制调 run_agent）→ `quantcode/mcp_server.py`（QUANTCODE_GROUP 过滤）→ `runner/agent_engine.py` ReAct 循环 → 组 allowlist 过滤 tool → trace 经 `result-contract.ts` 回流 `updateQuantCodeTrace`。

**验收**：
- Given 已选组=factor，When 点击"开始研究"，Then 提交指令含 `group="factor"` 且强制 run_agent 调用語句。
- Given 任务含关键词（如 "PR"），When `agent_mcp_tool._resolve_skill_name` 路由，Then 分派到执行器子 skill（`ORCHESTRATOR_DISPATCH`）。

**状态**：✅。缺口：Skill 下拉为硬编码 4 条常量，未读 `.opencode/groups/*/skills/` 真实目录。

### F-02 执行记录视图（Activity）✅
**用户故事**：作为研究员，我想按时间线查看 run 的推理/工具调用/产物/异常，并一键"再次运行"。

**契约**：`RunAgentResult.execution_trace: TraceEvent[]`（事件枚举 12 类：agent_start/skill_loaded/node_update/llm_thought/tool_call/tool_result/risk_metrics/human_gate/output_data/artifact/agent_end/error，另有 `checkpoint_snapshot` 扩展类型）。

**数据流**：agent_engine 产 trace → trace 桥（跨会话重置）→ `ActivityPanel`（timeline+artifacts）。`mergeTraceEvents` 按 `iteration:seq` 去重；缓存 localStorage `quantcode:thread_cache`（≤50）。

**验收**：同 `iteration:seq` 事件不重复；同 thread_id 结果合并 upsert。

**状态**：✅。缺口：无服务端 run 历史读取（未接 F-09 的 list_runs）。

### F-03 HumanGate 写操作门禁 ✅（收窄适配待办）
**用户故事（v0.2 重写）**：作为管理员，我想让 QuantCode 只在**写操作进入生产面**时强制人审，而研究面产出与代码审查不设 Gate——避免 Z code 式"每个动作都要批准"导致用户只能开完全访问、自动模式不可用的退化。

**触发点收敛为四类**（v0.2 收窄）：

| 触发点 | kind | 状态 |
|---|---|---|
| merge_to_main 主线因子入库 | merge | ✅ 已实现（`tools/factor/merge_to_main.py`，E2E `tests/test_factor_merge.py`） |
| SSH **写生产环境**（普通 SSH 读/开发环境写不 gate） | deploy | 计划（随 F-05 登录界面 + permission hook） |
| 跨组数据/资源访问 | permission | ✅ `runner/permission_engine.py` ask 态 → interrupt |
| token/预算超限 | budget | ✅ `QUANTCODE_TOKEN_BUDGET` 硬约束 |

**收窄语义**：`RiskThresholds` 越限 → acceptance verdict 直接 **fail**（gate 内化于评估流程，产出由报告平台承接，不设产出门禁）。现有代码 `RiskProfile.evaluate_verdict()` 仍返回 needs_human 触发 interrupt，**收窄适配为下轮代码待办**（governance SPEC G2-A8）。push 为自动操作不 gate；PR 合并与否由 GitHub owner 操作，PR 自动审核（Multi-Agent Review issue 报告：建议/不建议合并、冗余设计）由既有 GitHub Actions 承担，不进 QuantCode HumanGate；GitHub 侧未来出现需人审的场景可登记为新触发点。

**契约**：`HumanGate/HumanGateDecision/HumanGateInterruptPayload`（`schemas/human_gate.py` + `schemas/human-gate.schema.json`）；阈值 `RiskThresholds`（`schemas/risk_profile.py`）；契约锁定详见 [specs/governance/SPEC.md](governance/SPEC.md)。

**验收**：四类写操作触发 interrupt 且 `normalize_external_decision` fail-closed；merge 审批 E2E 通过；（收窄后）纯研究流零 interrupt。

### F-04 Memory 与组织能力目录 ✅（升级方向定版）
**用户故事（v0.2 升级）**：作为任一组研究员，我想让 Agent 知道组织已有哪些可复用的数据与代码（能力卡片），写代码时首选复用而不是另造一套；同时我不该看到的能力按我的组权限被 Mask。

**契约**：`MemoryService.search/write/get`（`runner/memory/service.py`，FTS5+BM25+CJK）+ 5-scope GROUP 隔离 [既有]；能力卡片 [新增，落地=P-07]——每 repo 一张（功能/接口面/何时用/**何时别自造**/权限属组），两层投放：**目录摘要常驻组上下文**（每次 run 可见，强保证）+ **细节走 FTS 检索**（弱保证）。蒸馏粒度：蒸 API 面，不蒸实现细节。

**权限 Mask**：按用户组 Mask Memory 内容（游客组不可见数据字段清单）；QuantCode 权限与用户组权限分配方案对齐（Git repo 权限 = QuantCode Memory 权限同源）。

**验收**：跨组读抛 `MemoryPermissionError`（fail-closed）；能力卡片常驻摘要进入组上下文；无权限组检索不到被 Mask 条目。

**状态**：✅ 后端完整 + 能力目录/查询视图已落地（memory-query fetcher 占位待 memory_search 后端通道，挂账 ACCEPTANCE #8）。

### F-05 设置（组/身份/供应商/SSH 登录）🔶
**用户故事**：作为研究员，我想通过完整的 SSH **登录界面**完成身份认证与组绑定，配置供应商与默认 Skill，使每次提交无需重复配置。

**契约**：组枚举 `QUANTCODE_GROUPS`（UI `instructions.ts`）↔ `GroupName`；身份 `quantcode/identity.py`（SSH 指纹→组映射，fail-closed）；tool 可见性 `registry.get_tools_for_group`。

**验收**：切组=options 后 tools/list 只返回 options allowlist 内 tool；断连时提交被阻断；登录界面完成 host/user/key → 连接状态 → 组绑定显示的完整流程。

**状态**：✅ 登录界面已建设（`ssh-login.tsx` 四态，数据层 stub 待 ssh_status 可查询 surface）；供应商 readout 已落地；SSH 完整认证面 = G4-B1（Q2）。

### F-06 外部评估器注册与部署适配（原 Factor AutoEval 流）✅（重定义）
**用户故事（v0.2 重定义）**：作为因子组研究员，我已用 Codex 把论文算法落成可运行代码并完成本地调优；QuantCode 要做的是——(a) 让我和 Agent 都知道组织有哪些现成评估能力并正确调用，(b) 把我调好的代码适配进 AlphaFlow 部署库，(c) 在我违反数据口径契约时及时发现。

**三项能力**：

1. **外部评估器注册**：Quant Evaluator（纯回测，**60 注册指标**——权威源 `METRIC_REGISTRY_COVERAGE.csv` 实测；README 口径一致）、Factor Engine（DSL，460+ 算子）、Data Access（PIT 数据层）以 MCP 工具描述/蒸馏文档登记——Agent **不参与评估过程**，但知道存在/能力/调用时机（"评估流程要嵌在哪个环节时，自动识别应调用哪个 package"）。数据桥已有：`tools/factor/eval_from_panel.py`（FactorPanel → 外部评估器）。
2. **契约遵守检测（口径统一）**：目标收益等口径以数据契约登记（见 [specs/data/SPEC.md](data/SPEC.md) §2.5：Horizon∈{1,5,10,20}、t+1→t+2、后复权表为唯一取值源，禁止自算）；Agent/Memory 能发现组员未遵守契约的用法并报告（背景：实测有组员把 t+1→t+2 算成 t→t+1 致收益虚高）。
3. **部署适配**：已调试代码 → AlphaFlow 部署库自动适配（= P-09 `/deploy` 黑盒命令）；**不做论文复现**（研究层调优是研究员自己的工作，Agent 无增益）。

**保留件**：merge_to_main / check_factor_gate（写操作 gate，F-03）；`FactorSpec`/`FactorReport` 契约（`schemas/factor.py`、`schemas/factor-report.schema.json`）与 acceptance verdict（`runner/acceptance.py`，阈值 `configs/acceptance.factor.yaml` 单源）。

**验收**：eval_from_panel 对真实 FactorPanel 出 FactorReport；merge 审批 E2E 通过；组员问"目标收益怎么取"时 Agent 指向契约表而非自算。

**状态**：✅ 管线已落地；评估器登记与口径契约落地 = P-07/P-09。

### F-07 跨组协同（PR 风控链降级为 CI 基建）✅（产品场景取消）
**v0.2 裁决**："模型 PR" 是伪场景——静态模型走 COS 上传 PKL，代码走正常 PR；PR 自动审核由既有 GitHub Actions Multi-Agent Review 承担（产出 issue 报告：建议/不建议合并、冗余设计），合并与否 owner 在 GitHub 操作。**PR 流不再作为 QuantCode 产品功能迭代。**

**保留为基建**：read_pr → extract_metadata → generate_model_spec → trigger_risk_flow → calc_risk → write_pr_comment（dedupe）链路与 `.github/workflows/risk-gate.yml` 继续运行（服务代码 PR 风控门禁），维护模式。

**跨组协同的真痛点转由**：口径统一（F-06 契约遵守检测 + P-07 蒸馏）与进展透明承接（P-08 Admin 中枢："模型组不知道因子组挖得怎么样" → 跨组语义查询）。

**状态**：✅ 代码与 E2E 存在（`tests/test_model_risk_handoff_e2e.py`、dedupe 防刷）；产品场景取消，基建维护。

### F-08 三条 Compose 流（降级为组内工具）✅（产品功能清单移除）
**v0.2 裁决**：策略/期权/基本面的业务流水线归各研究组自研（"策略内部的东西我们自己开"），QuantCode 不做业务层（平台红线 1）；策略层汇报归报告平台（可并入对外产品 2）。

**引擎代码保留**（用户裁决："万一有用呢"）：`tools/strategy/backtest_engine.py`（internal_v1）、`tools/options/backtest_engine.py`（options_v1）、`tools/portfolio/`、`flows/` 全部保留，降级为**组内工具适配层**——喂因子评估（eval_from_panel）与组内自用；不做 UI、不进产品功能索引。期权组自研引擎，不强推 options_v1。

**验收**：pytest 全量绿（引擎回归保护）；产品文档不再将其列为产品功能。

**状态**：✅ 代码+测试全绿（pytest 890）；定位降级为组内工具。

### F-09 Monitor 与 Admin 中枢语义层 ✅（升级方向定版）
**用户故事（v0.2 升级）**：作为 Admin 组成员，我直接问 QuantCode"最近每个人工作情况怎么样、每个模块运行情况怎么样、各组错误记录有哪些"，得到比固定面板更灵活的信息；同时保留 Git graph 面板与错误沉淀视图。

**Admin 组**：唯一跨组 scope（各组只见本组；blackboard/Memory 权限天然支持组隔离）。

**三层能力**：

1. **语义查询（管理面板的 AI 抽象化）**：跨组 list_runs（人/组/状态/错误聚合）+ blackboard 跨组只读 + 错误记录汇总——"问 AI 得到想要的，比看面板更灵活"（落地 = P-08）。
2. **Git graph 面板**：各 repo 最新树状态、更新节点标红高亮 + pop 提醒（GitHub API；落地 = P-08）。
3. **既有可观测**：`runner/metrics.py`（.quantcode/metrics.jsonl）、`list_runs`、`scripts/replay.py`、token 预算（已实现）。

**验收**：Admin 问"最近各组 run 状态"能跨组汇总；非 Admin 跨组查询被拒；repo 有更新时 pop 通知可见。

**状态**：✅ Admin 中枢全套已落地（admin-console/gitgraph-panel/双类 pop，AG-K+W4 打磨）；pop 自动推送 = Q2。

---

## 第二部分：计划功能（P-XX）

### P-01 数据接入（qsdata 组 + FactorPanel 契约）——P0，Q1（✅ 已实现：`schemas/data_contracts.py` + `tools/market/` 四工具，见 `specs/data/SPEC.md`）
**动机**：ROADMAP"最高优先级单点"。**契约**：`FactorPanel`（PIT calc_time<=as_of + `_contract:"FactorPanel/v1"`）、`ReturnsDataset`、工具 `list_factors/load_factor_panel/load_returns/pool_browse`；数据走 Blackboard `shared.datasets.*`。**验收**：GTJA191_M019 真实 IC 报告替换 mock；无权限组 fail-closed。

### P-02 回测引擎 ✅（已实现，降级组内工具）
`tools/strategy/backtest_engine.py` internal_v1（A 股 T+1/涨跌停/费用；vectorbt 升级路径见代码注释）；阈值 `configs/backtest.yaml` 单源。**v0.2**：产品功能清单移除，代码保留喂因子评估与组内自用（F-08）。

### P-03 组合层 ✅（已实现，降级组内工具）
`tools/portfolio/` construct/rebalance/gate（确定性数值，阈值 `configs/portfolio.yaml` 单源；复用 HumanGate interrupt）。**v0.2**：同 P-02 降级组内工具。

### P-04 并行 subagent ✅（已实现，平台能力）
`tools/subagent/` spawn/check/kill/list（任务树 MAX_TREE_DEPTH=4、预算隔离、组 allowlist）。**v0.2**：属 Agent 平台基础设施（非业务层），保留。

### P-05 实验管理 ✅（已实现）
`tools/experiments/ab.py`（A/B + OOS 纪律 + 排行榜）；`configs/experiments.yaml`。

### P-06 evidence chain 报告 ✅（已实现 JSON 契约）
`schemas/evidence_chain.py`（哈希指纹链，篡改可检）+ `runner/evidence.py::generate_evidence_report`；详见 [specs/governance/SPEC.md](governance/SPEC.md)。

### P-07 组织资产蒸馏管线——**P0** [新增 v0.2]（✅ 已实现：ASSET_INVENTORY 14 核心repo + 六卡 + Mask + 常驻摘要，tests/test_capability_cards.py 31 用例）
**动机**：最大复用原则的落地件。现状痛点：目标收益表已在数据仓却各自重算；库的功能没进 Agent 记忆（"我必须明确告诉它要用这个库，不说它就自己新造一个"）。

**契约草案**：**Step 0 资产调研（先行，2026-09-01 补——禁止凭会议记忆手写卡片）**：gh 只读扫描 `HKUST-QUANT-SOCIETY` org（实测 69 repo，核心层 14 个活跃），产出 `docs/audit/ASSET_INVENTORY.md`（每个核心 repo 一行：定位/语言/接口入口/活跃度/属组归属；归档层如 infra-*/test* 标注不蒸馏）→ repo → 蒸馏为**能力卡片**（功能/接口面/何时用/何时别自造/权限属组；**type 字段区分 资产卡/口径契约卡 两类**）→ **权限过滤**（用户组权限分配方案为权威源；游客组 Mask 数据字段清单）→ Memory GROUP scope + **常驻目录摘要**。蒸馏粒度：蒸 API 面，不蒸实现细节。

**首批蒸馏物（从调研清单出发，6 项）**：目标收益口径契约（Horizon 1/5/10/20、t+1→t+2、后复权，唯一取值源；已落 `TargetReturnView/v1`）、`quant_evaluator`（60 注册指标，权威源 METRIC_REGISTRY_COVERAGE.csv）、`factor_engine`（DSL 460+ 算子）、`data_access`（PIT 数据层）、`quant_platform`（纯 stdlib DTO 集成契约层——QuantCode 对接的正门）、`alpha_flow`（/deploy 部署目标底层）。

**第二类蒸馏物（工程约定，2026-09-01 补）**：项目工程决策沉淀——Python 版本、部署平台、架构约定、模块功能设计——进组 Memory，"搭架构时把细节沉淀进记忆，不需要二次对齐"；配套**开发 Best Practice**（架构先行→填细节）作为蒸馏类别（与 P-10 方案先行互为表里）。

**复用纪律**（运行时指令）：需求识别到已有能力覆盖不全 → 先向人征询，不许直接跳自造方案；**严格模式可配置**（`configs/capabilities.yaml`：strict_reuse=true 时禁止引入外部自造实现，仅允许已登记能力）。

**依赖**：F-04 Memory 底座；Git 权限 ↔ 用户组权限对齐。**验收草案**：组员问"目标收益怎么取"Agent 指向契约表而非自算；游客组检索不到被 Mask 的数据字段卡片；能力卡片常驻摘要出现在每次 run 的组上下文。

### P-08 Admin 组与中枢管理面——**P0** [新增 v0.2]（✅ 已实现：admin_scope + 六工具 + lens 全套 UI，tests/test_admin_scope.py 35 用例）
**动机**："中枢管理平台，不只是信息平台"——以前是直连后台数据的面板，现在把整个平台囊括进 AI：问 Agent 得到比面板固有信息更灵活的答案（各组进展、模块运行、错误沉淀）。

**契约草案**：Admin 组 = 唯一跨组 scope（**实现为角色而非第七研究组**——不进 `GroupName` 枚举，走 identity/permission role 判定，避免两仓组枚举联动）；跨组 list_runs（按人/组/状态/错误聚合）+ blackboard 跨组只读 + 错误记录查询（各组错误 Admin 可见）。

**GitGraph 与双类 Pop（2026-09-01 定版：用户点名关键设计，P0 本轮交付，自 Q2 提前）**：
1. **GitGraph 面板**：一键查看组织全部 repo 最新树状态，有更新的节点**标红高亮**（GitHub API：`admin_repo_status`）；
2. **Pop 提醒（两类）**：① repo 有新提交 → pop；② 各库（海威/浩海的库、各组开发环境）**package 版本更新** → pop，全组可见（数据：`admin_package_updates`）。"我们不可能一直盯着 repo，pop 起提醒作用。"
3. **日常工作台定位**：Admin 把它当日常任务管理界面打开（报告管理 + 任务管理入口）。

**依赖**：F-09 metrics、permission_engine（Admin 角色权威源）、GitHub API 只读客户端（复用 read_pr 通道）。**验收草案**：Admin 自然语言查询跨组汇总成功；非 Admin 查询他组被拒；GitGraph 更新节点标红；两类 pop 均可触达全组。

### P-09 AlphaFlow 部署适配命令（/deploy 黑盒）——**P1** [新增 v0.2]（✅ staging 已实现：黑盒字段面锁死 + kind=deploy gate + evidence 留痕；真适配器 blocked 待外部规格）
**动机**：研究员已调试代码与 AlphaFlow 部署库之间的适配是当前人工环节；同时 AlphaFlow 底层对普通研究员保密（"我能让他们部署，但不希望他们了解底层"）。

**契约草案**：`/deploy` 命令（lens 会话命令）→ 黑盒适配管线（已调试代码 → AlphaFlow 部署库格式适配 → 部署入库）；**黑盒约束**：过程中不向非授权用户暴露 AlphaFlow 底层结构（权限 Mask；正常询问 AI 时不得透露），部署转换只能经此指令进行；部署动作 = 写生产环境 → 挂 HumanGate（F-03 触发点 ②）。

**不做**：论文复现（研究层调优 Agent 无增益，用户裁决）。

**依赖**：F-05 SSH 登录界面、P-07 能力目录、permission_engine。**验收草案**：一份已调试因子代码经 /deploy 适配入库，全流程未向操作者泄露底层实现细节；无审批时部署被拦。

---

### P-10 方案先行工作流（Solution-First）——**P0** [新增 v0.2]（✅ 已实现：SolutionDoc 状态机 + draft 限流 + judge 一致性，冒烟 12 步绿）
**动机**：任何任务直接一口气生成代码，准确性与可审核性都差。定版纪律：**任务决定之前，先出完整解决方案，经 2-3 轮人机讨论，冻结为静态文档；代码按文档生成，验收以文档为基准做一致性判断。**

**契约草案**：
- `SolutionDoc`（`schemas/solution_doc.py` [新增]）：id / goal / rounds[]（每轮人反馈+方案修订）/ status∈{draft, frozen, superseded} / acceptance_criteria[] / file_impact[]（预期改动文件面）/ doc_hash；存 `artifacts/solutions/<id>-v<n>.md` + Blackboard `shared.solutions.*`。
- 状态机：draft →（≥min_rounds 轮讨论）→ frozen（**用户显式确认才冻结**）→ 按方案实现。冻结前**代码生成工具不可用**（复用组 allowlist 机制做阶段性工具限流，draft 态 deny 写类工具）。
- 一致性判定：实现完成后复用 `runner/judge.py` 做方案↔代码比对，verdict ∈ {conformant, deviation, needs_human}；偏离 file_impact 的改动必须列出。
- 默认开启（`configs/solution_workflow.yaml`：min_rounds=2、max_rounds=3，超轮数升级人裁；trivial 单点修复可显式豁免）。
- **语义边界**：本工作流是**流程阶段约束，不是权限门禁**——不新增 HumanGate 触发点（与 F-03 收窄一致，避免"每步都批"退化）。

**依赖**：F-01 run_agent（两阶段已有）、`runner/judge.py`、Blackboard、组 allowlist。**验收草案**：下达功能目标后 Agent 首轮只产方案不产代码；min_rounds 未满足时冻结被拒；frozen 后代码产出经一致性 verdict 可复核；偏离方案的文件改动被报告。

## 附：编号索引

| 编号 | 名称 | 类型 | 状态 |
|---|---|---|---|
| F-01 | 新建多智能体研究 | 现有 | ✅ |
| F-02 | 执行记录视图 | 现有 | ✅ |
| F-03 | HumanGate 写操作门禁 | 现有 | ✅（收窄适配待办） |
| F-04 | Memory 与组织能力目录 | 现有 | ✅（能力目录+查询视图已落地；memory_search 后端通道挂账） |
| F-05 | 设置 / SSH 登录界面 | 现有 | ✅（四态登录界面已建；SSH 完整认证面 G4-B1 延后） |
| F-06 | 外部评估器注册与部署适配 | 现有 | ✅（登记=P-07/P-09） |
| F-07 | 跨组协同（CI 基建） | 现有 | ✅（产品场景取消） |
| F-08 | 三条 Compose 流 | 现有 | ✅（降级组内工具） |
| F-09 | Monitor 与 Admin 中枢 | 现有 | ✅（Admin UI 全套已落地；pop 自动推送 Q2） |
| P-01 | 数据接入 | 已实现 | ✅ |
| P-02 | 回测引擎 | 组内工具 | ✅ |
| P-03 | 组合层 | 组内工具 | ✅ |
| P-04 | 并行 subagent | 平台能力 | ✅ |
| P-05 | 实验管理 | 已实现 | ✅ |
| P-06 | evidence chain | 已实现（JSON） | ✅ |
| P-07 | 组织资产蒸馏管线 | 已实现 | ✅（调研清单+六卡+Mask+常驻摘要） |
| P-08 | Admin 组与中枢管理面 | 已实现 | ✅（后端六工具+GitGraph/双类pop/查询台 UI） |
| P-09 | /deploy 黑盒部署适配 | 已实现(staging) | ✅（真适配器 blocked 待外部规格） |
| P-10 | 方案先行工作流（Solution-First） | 已实现 | ✅（状态机+限流+judge，冒烟12步绿） |

> 维护声明：本文件为功能唯一活文档；schemas/ 或 tools/ 每次改动必须同步更新状态列。历史快照不再修改。v0.2 定版依据 = 2026-09-01 功能定版会议（HumanGate 收窄 / PR 场景取消 / 引擎代码保留 / 平台红线 / 蒸馏与 Admin 双支柱）。
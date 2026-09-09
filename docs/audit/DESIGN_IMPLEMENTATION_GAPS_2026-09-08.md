# QuantCode 设计实现核对 · 2026-09-08

> **后续用户决策**：本审计保留当时双循环实现的缺口证据。用户随后确认采用同仓源码内化和统一执行引擎，见 [架构决策](../decisions/QUANTCODE_RUNTIME_INTERNALIZATION_2026-09-08.md)。A1 的长期解决方向改为迁移到统一执行链，而非给远程 Python Runner 再配置一份模型。其他身份、组织索引、共享知识和外部组件缺口仍成立；目标架构确认不代表代码已完成。


基线：specs/FUNCTIONAL_SPEC.md、docs/PRD.md、docs/QuantCode_Design.md，并纳入本次对话最新决策：仅桌面端；登录自动绑定 roster 组；模型 URL + API Key；GitHub 浏览器授权/本机凭据；GitGraph 六列缩略卡片与分支详情；Admin 分页签。旧文档中的自由选组、手机验收不作为待办。

本次为代码审计和当前开发接口只读抽查。没有提交研究任务、进行审批、部署或修改产品代码。读取接口可能按产品设计生成查询审计。未重新执行全仓测试，既有 fixture 测试不能视为多人或生产验收。以下结论覆盖当前工作区（包含未提交改动），不代表已发布安装包。

## 核心结论

目前完成的是相当一部分平台底座、桌面展示与本机接入；“研究任务可持续执行、组织状态统一汇总、知识形成共享资产、外部组件和生产执行”还未全部闭环。不能根据界面或旧台账的 IMPLEMENTED 直接宣布产品完成。

## 当前接口实查

当前开发页面 4744 对应宿主 4396。

| 读取项 | 结果 | 含义 |
|---|---|---|
| session_context | ssh_roster / admin / agent | 当前成员身份链可读；不代表所有成员验收 |
| list_capabilities | 14 张；5 PARTIAL、8 UNVERIFIED、1 UNAVAILABLE、0 CONNECTED | 组件自身 PRODUCTION 不代表 QuantCode 已接通 |
| search_memory(contract, limit=3) | CONNECTED，3 条命中 | 共享 Memory 查询已通 |
| admin_task_history / list_run_history | 均返回空 runs | API 存在，空结果不是全组织已汇总的证据 |
| list_distill_candidates / list_pending_gates | 均为空 | 队列入口存在，不能据此证明真实跨人审核闭环 |
| deployments | Management request rejected (503) | 当前管理服务未接通，不能操作真实生产部署 |

## A. 优先处理的未闭环功能

### A1. 远程 Compose 模型接入（F-01 / F-05，阻断研究主流程）

桌面供应商保存到宿主 Provider/Auth；Python MCP 只从 QUANTCODE_API_KEY 等环境变量创建模型。远端 sandbox 使用 env -i，只列入身份/Memory 等变量，没有模型凭据或模型代理。缺模型时 run_agent 明确返回 No LLM model configured。

缺：通过可信宿主/服务端模型代理或受控凭据配置，让桌面选定的模型与实际 Runner 可用模型对应，并有真实任务验收。当前用户设置模型不等于远端 Compose 可执行。本次没有发起真实 LLM 任务。

证据：[quantcode/mcp_server.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/quantcode/mcp_server.py:647>)；[quantcode/remote_mcp.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/quantcode/remote_mcp.py:79>)；[runner/agent_mcp_tool.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/agent_mcp_tool.py:273>)。

### A2. 桌面编辑器/终端与远程个人目录接入（F-05，部分）

roster workspace_path 已进入 Python 研究沙箱，但首页创建会话仍使用宿主最近项目/目录选择器，没有将该路径自动接成桌面远程文件系统和终端。SSH 身份登录、远程 MCP 与远程 IDE 工作区是不同链路。

缺：成员登录后可打开其远程个人工程、编辑/终端实际落在同一授权目录的完整工作流。不能把“显示个人目录”视为远程 IDE 已实现。

证据：[frontend/packages/app/src/pages/home.tsx](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/pages/home.tsx:1437>)；[quantcode/remote_mcp.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/quantcode/remote_mcp.py:79>)。

### A3. Admin 查询结果回流（F-09 / P-08，前后端未连全）

Admin 查询指令要求外层 Agent 直接调用 admin_list_runs/admin_errors；Admin 面板读的是 _trace.execution_trace 中的结果。当前 app/session-ui 的桥主要只消费完成的 run_agent 返回值，未看到直接 admin_* 工具结果进入该 store 的完整路径。

缺：直接管理查询 API 或 admin_* message-part 到面板的结果桥，并处理提交失败/加载/刷新。此前 Admin 浏览器数据布局验证用的是受控 fixture，不是这条真实查询链。

证据：[frontend/packages/app/src/components/quantcode/admin-console.tsx](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/components/quantcode/admin-console.tsx:221>)；[frontend/packages/app/src/pages/session.tsx](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/pages/session.tsx:1286>)。

### A4. Admin 全组织数据汇总与管理（F-09 / P-08，部分）

organization=True 可以扩大“同一个数据库内”的可见范围，但历史仍读取当前 runtime 的 checkpoints.db，运行统计读取当前 metrics.jsonl。Server C 每成员使用隔离 runtime/state，未看到跨成员索引/汇聚服务。跨成员 Blackboard、候选和审批也需要同一组织权威数据面，不能只解除组过滤。

缺：跨成员任务/报告/错误/审批/候选的共享索引及授权查询；Memory、Blackboard、能力、权限映射的管理操作面。目前 Admin 有导航和若干查询/审核能力，尚不是完整组织管理中枢。

证据：[runner/run_history.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/run_history.py:84>)；[runner/langgraph_base.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/langgraph_base.py:44>)；[runner/metrics.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/metrics.py:22>)；[quantcode/remote_mcp.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/quantcode/remote_mcp.py:79>)。

### A5. 组内共享 Memory 写入、确认与晋升（F-04 / P-07，部分）

共享 gateway 查询已通，底层 MemoryService 有读写方法，候选晋升可发布 Skill；但 gateway 当前提供的是 /memory/search，尚未形成成员研究结论“候选→确认→写入组织共享根→其他组员可读”的统一服务链。现有初始化脚本主要发布平台契约与能力卡。Skill 候选发布路径指向 .opencode/groups/...，也需解决远程只读 runtime 与共享发布落点。

缺：共享知识服务的受控写入/晋升/修订/替代、完整内容查看与来源/时间/验证状态展示，以及跨成员验证。不能把 Skill 草案批准与长期知识发布合并当成一项已经完成的能力。

证据：[quantcode/mcp_server.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/quantcode/mcp_server.py:506>)；[runner/distill/governance.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/distill/governance.py:66>)；[scripts/initialize_shared_memory.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/scripts/initialize_shared_memory.py:15>)。

### A6. 真实量化组件与数据主链（F-06 / F-08 / P-01~03，待外部接入）

组件目录、适配器和契约已存在，但当前接口 0 CONNECTED；local_components 配置仍为 local_checkout，部分路径是个人电脑绝对路径，多个关键组件 local_path 为空。market backing 默认仅 staging，收益源函数保留 no_source 路径。

缺：DataAccess→FactorEngine→QuantEvaluator、Modeling/Barra、Riskfolio-QS/VectorBT-QS 等真实输入、版本、输出、权限与 artifact 的逐组件接入验收。不是要求 QuantCode 自己再实现因子/回测/组合算法。

证据：[configs/local_components.yaml](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/configs/local_components.yaml:1>)；[tools/market/backing.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/tools/market/backing.py:37>)；本次 list_capabilities 实查。

### A7. 生产部署执行闭环（P-09，STAGING/待外部接入）

已有暂存、取消、哈希和可选外部 submit adapter；当前部署接口实测 503。生产执行器、队列状态回传、失败补偿和回滚尚未形成完整链路，不能按表单可点击记为已上线。list_deployments 仍固定报告 executor_status=UNAVAILABLE，配置接入后也需要同步状态语义。

缺：受控生产服务账号执行、状态跟踪、回滚与审计验收；保持 Admin 专属。

证据：[runner/admin_operations.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/admin_operations.py:31>)；[runner/deployment_executor.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/deployment_executor.py:32>)。

## B. 后端有基础，但桌面交互仍缺

| 功能 | 当前已有 | 尚缺 | 基线 |
|---|---|---|---|
| 运行中实时 Activity | Runner 持久事件、check_tool_stream、完成结果、历史游标 | 桌面运行中增量订阅；当前桥主要等待 run_agent completed | F-02 / Design 4.3、9.2 |
| 树状任务与 Subagent 监控 | ComposeTask、parallel_registry、spawn/check/kill 工具 | 树形父子任务、子任务日志/预算、单独停止和重试控件 | P-04 / Design 9.2 |
| 人工 Compose 编排 | 自动 ReAct、组 Skill、pipeline schema | YAML 编辑/预览、暂停节点、受控跳过与继续；未找到完整执行控制入口 | Design 4.5、9.3 |
| Schema 交互卡片 | schema_validator、JSON Schema 和产物展示 | 字段/版本/来源的专用编辑、导出和变更回传 | Design 4.5、9.2 |
| 跨组 handoff 工作台 | Blackboard、handoff 工具与契约 | 接收组待办、通知、ack 与跨成员闭环；当前通知主要是 Gate 与 GitHub | F-07 / Design 8.7 |
| 维护员 Tool Catalog 生命周期 | ToolDef、注册、静态组 allowlist、会话权限计算 | 可持久的发布版本、环境绑定、下线/回滚流程；不是必须新建 UI，但后端生命周期要有证据 | Spec 2.2 / Design 4.2 |
| Admin 报告管理 | 带 artifacts 的任务历史列表 | 与权威报告平台的检索/预览/跳转和报告状态同步；不自建报告平台 | P-08 |

实时事件证据：[tools/stream/_register.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/tools/stream/_register.py:29>)；[frontend/packages/app/src/pages/session.tsx](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/app/src/pages/session.tsx:1286>)。前端设计要求：[docs/QuantCode_Design.md](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/docs/QuantCode_Design.md:728>)。工具目录证据：[tools/registry.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/tools/registry.py:113>)。

## C. 已有实现但尚不能销项的验收

- **成员登录**：当前桥固定读取 QUANTCODE_PUBLIC_KEY_FILE，只暴露 host-default，没有完整的本机多身份发现/管理；失败原因较笼统。当前成员实连不代表八组成员与不同设备全部验收。证据：[frontend/packages/opencode/src/server/routes/instance/httpapi/handlers/quantcode-identity.ts](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/frontend/packages/opencode/src/server/routes/instance/httpapi/handlers/quantcode-identity.ts:18>)。
- **真实长任务恢复/跨人 Gate**：检查点、精确恢复、审批队列和回执核对有实现；当前队列为空，未在本轮重演真实运行故障、撤销和跨成员审批。它们应列为“实现已有、端到端待验”，不能说全部没有实现。
- **后台同步与提醒**：GitGraph 已有六列卡片、分支图、提交 diff、缓存和分批刷新；每分支历史仍是有限窗口，完整历史远端翻页未完成。页面定时刷新与有限后台批次不等于关闭桌面后的持续服务；正式 worker 托管及系统通知送达仍需验收。证据：[runner/github_sync.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/github_sync.py:18>)。
- **Dream/Distill**：有 consumer/worker/候选治理与审核 UI；跨成员原始运行汇聚、共享发布和正式服务托管仍待补齐。证据：[runner/dream_worker.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/dream_worker.py:12>)；[runner/distill/governance.py](</Users/hendrixchen/Desktop/私募/agent/QUANTcode/runner/distill/governance.py:66>)。
- **桌面发布**：本次会话验证的是本仓库 Dev 页面与类型/构建，未重新完成 Electron 安装包、升级和全员安装验收。不能把浏览器预览当成桌面发行完成。

## D. 设计中仍有，但不宜混入当前核心缺口

- Design §13 的 Dog Food 周期抓取、资料沉淀和独立研发视图：本次未找到完整产品入口与调度闭环，属于 Agent 组后续能力。
- 完整 YAML 人工编排、Schema 编辑、完整历史拉取若要调整范围，应修改设计并记录决策，而不是默认界面不显示就已取消。
- 不补“统一回测/组合/期权/研究报告业务页”、投资决策 Agent、普通研究员生产 shell、自由组切换或手机端；这些不属于当前授权设计。

## 建议处理顺序

1. 模型→远程 Runner 与个人工作目录，先验收一条真实研究任务。
2. Admin 结果桥与跨成员数据索引，避免仅对当前成员目录显示“全组织”。
3. 共享 Memory 写入/确认/发布和跨成员 Gate/handoff。
4. 实时事件、任务树、子任务监控及恢复交互。
5. 按组件服务可用性逐个接入量化主链；生产部署由外部执行器配合。
6. 收尾目录生命周期、人工编排等设计差项及正式桌面发行验收。

旧审计文档同时存在“已接通”和早期“未接通”的追加记录，需后续统一状态；这次没有擅自改写功能规格或实现状态。

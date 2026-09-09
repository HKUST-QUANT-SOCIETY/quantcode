# 组织工具发布与本机工作区登记

2026-09-09 静态复核补记：原生目录枚举复用 `quantcode/file_mutation.py` 的固定 `list` 动作，以目录句柄逐级读取并核对 inode/时间。该文件纳入来源摘要；没有新增模型工具、改变工具 effect 或发布在线目录。目录修复的桌面证据与尚未运行的用例见主迁移核验记录。

这是 M1 的宿主维护入口。2026-09-09 已逐项复核六处源码 pin 漂移并完成当前 schema 导出，工具权限策略未扩大，见[本轮 pin 审查与证据](../../docs/testing/CATALOG_PIN_REVIEW_2026-09-09.md)。每个研究宿主的配置绑定、发布和执行验收仍由部署流程分别记录；迁移开关由主流程控制。

`organization-tools.review.json` 将实际 Python 函数、源码 SHA-256 和准入策略放在一起。它不是第二份工具参数 schema，也不是在线组件状态目录。参数 schema 直接复用现有 `ToolDef`、`tool_def_to_mcp` 与 `pydantic_to_json_schema` 导出；服务名和服务配置 hash 在宿主生成候选发布文件时绑定。

当前审核了 22 项工具：9 项可进入候选目录，13 项明确禁用。未列出的工具继续默认拒绝。候选 `published` 表示经过本次静态权限分类、可供宿主审核发布；只有执行单独的 `publish` 后才改变运行时目录。它不表示工具已被真实调用，更不表示对应业务组件是 CONNECTED。

| 类别 | 实际工具 | 审核结果 |
| --- | --- | --- |
| 能力检索 | `list_capabilities` | `read` / `capability_catalog`；透传真实卡片状态，不调用组件 |
| 组 Memory 检索 | `search_memory` | `read` / `group_memory`；沿用会话 ACL、长期知识过滤与 Admin 披露审计 |
| 组织目录 | `session_context`、`list_skills`、`list_algorithms`、`describe_algorithm` | `read`；检索 Skill/算法不授予执行它们的权限 |
| 纯契约校验 | `generate_model_spec` | model 组 `read`；仅校验传入 ModelSpec，不读取 code_path、不调用 LLM |
| 已有 staging 数据读取 | `list_factors`、`pool_browse` | factor 组 `read`；仅宿主 staging 数据，缺数据仍报原错误 |
| 本地 PR 便利路径 | `read_pr`、`extract_metadata` | 禁用；`pr_path` 尚未复用统一执行器私有文件边界 |
| 动态函数/外部评估 | `run_algorithm`、`quant_evaluator` | 禁用；需要审核具体函数或远端副作用契约，不能从描述猜只读 |
| 共享状态/旧审批 | `load_factor_panel`、`write_blackboard`、`merge_to_main`、`freeze_solution` | 禁用；需绑定新任务身份、精确资源和当前审批/回执，不能保留旧布尔确认或不准确去重 |
| 原生共享条目读取 | `read_blackboard` | 已实现显式共享服务库、规范 key 和实际 version 读取；真实共享服务配置与最终验证前保持禁用 |
| Python 通用循环 | `run_agent`、`spawn_subagent` | `legacy_executor` / 禁用；不得作为新任务普通工具 |

各项理由和源码位置见 JSON 的 `review` 与 `source`。这份目录不会从函数名、MCP `readOnly` 注解或可发现列表自动扩权；组和角色也不会从参数推断。MCP 服务仍执行自身会话权限检查，原生执行器再检查发布目录，二者必须同时允许。

## 宿主准备

以下命令是实现完成后的维护用法，本次迁移实现期间未执行。由维护者在可信宿主终端运行，不能作为模型可调用的 Shell 帮助动作。使用仓库已安装的 Bun/Python 环境，不下载另一套 OpenCode。

在工作区外创建由当前宿主账户拥有、权限 `0700` 的控制目录，例如 `/absolute/private/quantcode-control`，再明确指定：

```sh
export OPENCODE_CHANNEL=quantcode
export QUANTCODE_TOOL_CATALOG_FILE=/absolute/private/quantcode-control/tool-catalog.json
export QUANTCODE_WORKSPACES_FILE=/absolute/private/quantcode-control/workspaces.json
```

不要把 `/tmp`、用户主目录或整个项目设为控制目录。两个环境变量的父目录也受原生文件/Shell 隔离保护，包括 `.publication-locks` 和历史归档。CLI 不会自动修改已有目录的权限，不会接收 API Key 命令行参数。默认位置仍为当前 QuantCode 宿主配置目录；若其权限不是 `0700`，需由维护者明确选择私有控制目录。

`QUANTCODE_BACKEND_ROOT` 指向正在运行的可信组织服务安装目录，整体属于控制路径。固定 Python helper 从此处导入代码，研究任务若可修改这些 `.py` 文件，就能绕过权限。宿主安装根必须与可写研究 checkout 分开；研究 QuantCode 自身时使用独立 checkout。登记 CLI 拒绝为运行中的安装根或其子目录授权，原生文件/Shell 也不通过普通工作区开放它。这个边界只在迁移模式生效，不改变仓库外部编辑器的权限。

当前 CLI 对 macOS/Linux 使用已有 POSIX 文件权限检查；Windows 分支因没有 ACL 验证而明确拒绝登记/发布。这是当前实现的安全限制。顶层迁移决策、功能规格、PRD 和技术设计没有明确逐操作系统验收清单，不能把这一限制解释为用户新增了 Windows 交付目标。

## 生成并发布工具目录

1. 在仓库根目录运行 `python -m quantcode.catalog.export --output /absolute/private/quantcode-control/schemas.json`。导出器校验固定审核清单的源码版本，复用实际注册表生成 wire schema，不执行工具、不获取组织身份、不启动模型、不连接远程服务。输出文件必须不存在。
2. 将**实际生效的一个 MCP 服务配置对象**保存到该目录的 `server-config.json`，权限 `0600`。内容须与执行器 `config.mcp[serverName]` 一致，包含配置解析后的字段；不是整个配置文件或展示用脱敏对象。配置文件可能含环境变量/headers 凭据，只留在私有宿主目录。候选发布文件仅保存其摘要。
3. 在 `frontend/packages/opencode` 下运行：

```sh
bun script/publish-quantcode-tools.ts prepare /absolute/QUANTcode/quantcode/catalog/organization-tools.review.json /absolute/private/quantcode-control/schemas.json quantcode /absolute/private/quantcode-control/server-config.json /absolute/private/quantcode-control/release.json release-1
bun script/publish-quantcode-tools.ts status
bun script/publish-quantcode-tools.ts publish /absolute/private/quantcode-control/release.json absent
```

`quantcode` 是该示例里的实际 MCP 服务键名，应替换为本宿主生效配置的键。`prepare` 只写新的私有候选文件；不启用迁移或连接服务。发布已有目录时，将 `absent` 换成 `status` 返回的完整当前摘要。源码变化、配置变化、实际 wire schema 变化，均须重新审核对应影响并生成候选，不得仅把旧 hash 更新成新值来“修好”校验。

每次发布保留不可覆盖的 `tool-catalog-history/<sha256>.json`。回滚命令为 `bun script/publish-quantcode-tools.ts rollback ARCHIVED_DIGEST EXPECTED_CURRENT_DIGEST`；它验证归档实际字节摘要和当前版本，不盲目覆盖新发布。普通模型即使获准一次工具调用，也无权调用此发布入口。

## 登记本机 checkout

先在桌面登录目标成员。登记使用 `QUANTCODE_IDENTITY_SESSION_FILE` 指向的宿主私有会话，并向网关重新核验；不接受 actor、group、role 或 workspace 参数。工作区请求本身不授予本机路径权限。

```sh
bun script/enroll-quantcode-workspace.ts status
bun script/enroll-quantcode-workspace.ts grant /absolute/canonical/checkout write absent
bun script/enroll-quantcode-workspace.ts revoke /absolute/canonical/checkout EXPECTED_CURRENT_DIGEST
```

checkout 须已存在、归宿主账户拥有、没有组/其他用户写权限，且使用真实绝对路径。只读 checkout 将 `write` 改为 `read`。登记不能指向凭据/控制目录、组织服务安装目录、主目录或其父级。记录绑定当前成员的 actor/group/workspace_id，发布前再次核验登录身份；切换成员后不能凭同一路径继承授权。普通写入对现有多硬链接文件也会拒绝，避免改写可信文件的别名；这不代表符号链接时序竞争等所有文件隔离问题已解决。

`revoke` 只撤销当前成员的精确本机映射，可用于已经删除的 checkout；不会移除其他成员记录。roster 自身授予的个人目录属于身份服务的独立授权，移除本机映射不撤销 roster 权限，需通过 roster 管理流程处理。历史保存在 `workspace-history`；恢复旧授权必须重新核验当前 roster，不能将旧 JSON 整体覆盖。

两个发布入口复用 OpenCode 的 `Flock`，比较当前原始字节摘要，落盘并同步归档后原子替换。锁不因超时而被自动抢走。若宿主发布进程崩溃，维护者先确认该进程已终止、核对当前摘要和归档，再处理对应遗留锁；不得在真实发布仍运行时删除锁。锁文件存在本身不证明进程仍在运行。

## 待最终验收

完成全迁移实现后，统一验证：真实 roster 登记与撤销；并发版本冲突；路径别名/符号链接/硬链接/私有目录拒绝；中途身份撤销；生成结果与 MCP wire schema 一致；旧 schema/config/权限失配时工具不可见且不可执行；归档回滚；任何未接入组件仍显示原 UNAVAILABLE/STAGING 状态。真实成员映射、私有服务配置、组件连接契约和发布决定均不能用示例值伪造。

## 原生共享 Blackboard 合同

`write_blackboard` 已补确定性服务接线，仍不发布。原生参数为 `{key, value, expected_version}`：`key` 必须完整匹配 `^shared\.model_entries\.[A-Za-z0-9_.-]+$`，不自动给裸 key 加前缀；`expected_version` 是当前版本，0 仅表示该 key 必须不存在。共享资源 ID 为 `blackboard:project:<key>`，审批的 `resource_version` 为该整数的十进制文本。不能把此工具用于 `shared.pending_*` 队列或其他共享命名空间。

读取复用现有 `read_blackboard` 工具，原生参数只接受 `{"input_data":{"blackboard_key":"shared.model_entries.example"}}`。返回实际 `project_entry`、`version` 和规范资源 ID；库不存在/未配置时报不可用，不把个人空库伪装成共享库返回 0。model/risk 组可按原生合同读取，写入仍限 model 组和真实角色，精确批准者由网关重新核验。

共享服务宿主必须明确配置 `QUANTCODE_SHARED_BLACKBOARD_DB`，指向已初始化的组织库；父目录规范、服务账户所有、权限 `0700`。原生调用不接受参数/ctx 内的数据库路径。现有远程个人 MCP 安装把 `.quantcode` 映射到每个成员个人目录，不能用它冒充跨成员共享库，因此 SSH 中继不会转发共享数据库路径。需要在真正承载组织共享服务的宿主配置此变量，并在最终验证中证明不同成员读取同一事实源。

原生绑定由 MCP 传输的 `_meta.quantcode` 提供，参数 schema 没有这些字段：`version=1`、`login_session_id`、`native_session_id`、`root_session_id`、`message_id`、`call_id`、`server`、`catalog_digest`、`arguments_json`、`arguments_digest`。共享写还需要 `gate_id`、`operation_digest`。摘要使用 `arguments_json` 原始 UTF-8 字节；服务将其解析结果与真实工具参数按类型逐项比较，不能把 `true` 当作数字 `1`。身份、组、角色、工作区始终来自网关会话，不来自 `_meta`。

写入前通过 `/native-gates/read` 校验当前批准事实：任务/消息/调用、工具/服务/目录版本、原始参数、规范资源及版本、owner 和审计回执都必须一致。复用 Blackboard 的现有 `BEGIN IMMEDIATE` 事务比较版本，在获得写锁后再次核验批准；过期、拒绝、取消、身份撤销或版本变化均拒绝写入。原生调用绕过旧 300 秒去重；同一已提交调用以旧版本重放时不会再次写入。通用执行状态和未知结果恢复仍由原生引擎回执负责，本工具不创建第二份运行日志或保证脱离原生回执的任意重放恢复。

为了保留历史数据契约，`written_by_task_id` 使用 `T0.<完整操作摘要的十进制整数>`，明确表示原生任务兼容署名；返回结果包含真实 native session/message/call 与批准回执供索引使用，不伪造 ComposeTask 编号。旧 Python 路径没有原生绑定时保留原有行为。迁移宿主的 `QUANTCODE_UNIFIED_RUNTIME=1` 模式拒绝省略原生元数据的 Blackboard 调用；桌面宿主在 channel=quantcode 且迁移开关明确开启时，才在固定 SSH 首包携带 `runtime=quantcode-native-v1`，远端据此注入两个固定环境变量，不能通过工具参数切换。

## M2 新任务目录

迁移模式的 Python 组织服务同时在发现与调用边界排除旧通用执行器、旧子任务状态工具、旧方案存储入口及独立模型工具。具体排除：`run_agent`、`spawn_subagent`、`spawn_agent_python`（保留名称拒绝）、`check_subagent`、`kill_subagent`、`list_subagents`、`draft_solution`、`revise_solution`、`freeze_solution`、`solution_status`、`match_main`、`gen_schema`。最后两项现已加入审核清单并明确disabled，不能凭名称或旧Skill强行调用。

普通组织工具调用始终不初始化Python模型，即使来自不带原生_meta的宿主只读查询；只有显式非迁移旧执行器调用保留旧模型工厂。迁移模式直接调用该工厂也会拒绝。新任务模型由宿主Provider统一提供，组Skill在当前任务执行并使用organization_solution/organization_reuse，子任务继承身份、预算和工作区。旧执行器源代码与历史仍保留，目录清理不等于旧数据删除或M4退役完成。

原生 `search_memory` 固定调用现有网关 `/memory/search`，不依赖额外设置 `QUANTCODE_SHARED_MEMORY=gateway`；原生调用存在时也不能强制回落本机个人 `.quantcode/memory.db`。查询前后比较私有宿主凭据和当前 roster 会话，核对原生登录绑定；切换身份、撤销授权或凭据变化时不释放结果。共享网关缺失/不可用或知识库未初始化时明确报告，不能把个人库结果登记为组 Memory 检索证据。非原生 legacy 本机 Memory 路径保持原行为。

## M3 宿主适配依赖审核

本轮来源校验补入任务投影、产物传输、旧投影归档及知识候选适配。它们是固定宿主接口的依赖，未增加模型工具声明；现有 22 项仍为 9 项候选发布、13 项禁用。

- `gateway.py` 的任务入口只分派固定 `/native-tasks/*` 路由。`native_tasks.py` 在原网关 SQLite 中保存完整 owner 绑定的单调版本投影，产物引用绑定原事件和结果摘要，内容按 64 KiB 分块核验，并在完整清单及全文摘要一致后开放下载。Admin 跨成员读取沿用披露审计；接收时间不表示任务仍运行。
- `native_task_migration.py` 是宿主终端维护入口。归档前比较精确预览摘要，在同一数据库保留不可覆盖的原始行及重建回执；不推算旧文件内容，不添加执行事件。旧记录在实际原 owner 重新发布前显示等待归档或重建。
- `run_history.py` 增加原检查点、pending writes、完整 owner 摘要和待审批调用的只读绑定；不同归档库不再混用默认库同名事件流。它不启动执行器，也不把 serializer 版本当作源码版本。
- `knowledge_host.py` 只接收宿主提供的成功工具名称序列和任务来源，复用 `dream_consumer.distill_new_runs`、`dream.distill_prototype.run_distill(write_files=False)` 与原候选索引。组和 owner 来自实时网关身份，提交前再次核验；不接收模型、任务正文、工具参数、结果或任意输入路径。候选存储和 Skill 发布根必须显式配置为私有目录。
- `distill/governance.py` 使用既有进程锁统一候选登记和人工审核，候选按组及工具序列去重，原生来源只能追加历史；草稿不自动转正。独立桌面审核要求精确草稿摘要，发布仍检查待补项，留下 intent 与决定审计，撤销后既有 Skill loader 拒绝加载。
- `tools/admin/_register.py` 与 `mcp_server.py` 的候选队列、审核和消费状态在原生模式读取同一显式宿主目录。`review_distill_candidate` 的旧 MCP 包装仍允许省略摘要且没有宿主提交前回调，未进入这份发布清单；桌面使用固定 knowledge host 接口。现有 `list_skills` 依赖同一 governed Skill loader，保持只读分类。

本次只更新实际审阅文件的 SHA-256，未运行导出器、生成候选发布文件或发布运行时目录。随后完成的旧恢复适配静态审阅也已固定下面列出的直接宿主依赖；原归档执行器自身仍须逐检查点登记，不能由当前宿主校验值代替。

### 旧任务恢复适配

`legacy_host.py`、`legacy_contract.py` 与 `legacy_executor.py` 仅接续已登记的原检查点。源码、Python/依赖版本、完整原 owner、原构造参数、图拓扑、待执行节点和 system prompt 摘要必须匹配；新登录仅在原 owner 授权字段相同时接续。原 graph/checkpointer/tool_receipts 保留，当前宿主不猜测历史缺失参数。撤权中止执行后，已生成检查点仍在原 writer lock 内记录其实际执行器来源。

`legacy_approval.py` 复用网关原生 Gate。原 owner 提交精确检查点、原 Gate、待执行参数、方案与执行器摘要，由当前授权审批人决定，再由原 owner 使用有效回执接续；不接收浏览器传来的 approve/reject 作为执行授权，不修改原任务角色。`legacy_usage.py` 保存恢复后的模型预留和实际结算，未知用量保留阻断；宿主终端的人工复核要求原请求摘要、当前检查点、停止证明及外部证据，沿用原任务锁并写审计。Admin 跨成员用量查看另留披露审计。

前端宿主 `legacy.ts`、`legacy-provider.ts`、`legacy-tools.ts` 与 `process-sandbox.ts` 使用现有 Provider、AppProcess 和 OS sandbox。每个模型帧只调用一次 generateText；业务工具在单次隔离进程中执行，原 graph 与控制数据库留在可信 controller。`legacy_tool_host.py` 只导入已登记源码的只读副本，普通数据路径复用已有 PROJECT_ROOT 绑定到原 owner 工作区，写权限限冻结方案精确文件；不传凭据，不开放网络或控制目录。跨隔离结果仅为纯 JSON 或 bytes/bytearray/null，禁止从 worker 返回数据构造任意 Python 对象。需外部凭据、网络、内部 GraphInterrupt 或不支持文件面的工具明确不可用，不以无限制进程回退。

本轮校验包含对应 legacy 与原生 Gate wire schema，未修改现有 22 项工具的准入策略，也未把旧恢复、来源登记或用量复核开放为模型工具。静态审阅不证明这些接口已完成运行验收。

## M4 旧入口退役

仅在 `OPENCODE_CHANNEL=quantcode` 与 `QUANTCODE_UNIFIED_RUNTIME=1` 同时生效时，installed `AgentRunner.run/stream/resume/build`、`SubagentRegistry.create_subagent`、`execute_compose_flow` 拒绝普通调用。真实旧恢复仅由已核验宿主为其归档模块的精确 runner/thread 绑定私有恢复准入；`resume=True` 不是授权。注册 Flow、查询既有子任务、Memory/Blackboard 和普通组件服务保留。详情及待验证边界见 `docs/decisions/RUNTIME_INTERNALIZATION_M4_RETIREMENT.md`。

`native_review.py` 与 `schemas/native_review.py` 已静态审阅并纳入依赖校验：固定网关接口重新核对原 owner 当前 roster 字段，区分本人回执读取与同组 approver/Admin 核对，保留授权和跨成员披露审计；它不执行任务、不重试工具或增加预算，应用决定仍以宿主原生事件为准。上述来源校验不改变任何工具的 published/disabled 状态。

审批提交结果查询复用 `native_gate.read`。仍有同一完整审批者权限的成员重新登录后，可以读取自己已记录的决定；其他历史记录不因这个入口扩大可见范围。原 owner 或原审批会话失效时返回 `valid=false`，历史回执不恢复执行权。桌面仅缓存按成员与宿主隔离的 Gate ID、记录摘要和操作摘要；提交响应丢失先核对原记录，只有当前仍有效且没有决定的 pending 请求才允许重提。此入口及修改后的来源校验仍待运行验收。

# M0：现状锁定、迁移映射与阶段交付

状态：M0 文档与代码静态核对完成；运行实现与最终验收未完成。

依据：[用户确认的内化决策](QUANTCODE_RUNTIME_INTERNALIZATION_2026-09-08.md)。用户随后强调必须按 M0 → M1 → M2 → M3 → M4 顺序执行，并要求全部实现后统一测试。本文落实该顺序，不把写出目标等同于实现完成。

本次依据为当前工作树（含早先未提交改动）。只读取源码和记录；未启动任务、执行测试、类型检查、构建或重启服务。初始代码审查不是运行通过证明。前一目标轮次推进了进度文件和草稿；本轮完成 M0 的缺失交付。

## 1. 规范优先级与冲突核对

| 主题 | 生效决策 | 现有旧内容的处理 |
|---|---|---|
| 业务边界 | QuantCode 只做组织服务、通用编排、契约和组件适配；领域算法仍归各组 | 不把 UI 内化变成重写业务引擎 |
| 执行器 | 同仓 TypeScript 执行链为唯一新任务引擎，Python 不再嵌套通用 Agent 循环 | Design 中旧 AgentRunner/SqliteSaver/F/P 表是迁移来源，不再约束未来必须用 LangGraph |
| 身份 | roster 签发 actor/group/role/workspace；桌面自动绑定组，无自由组选项 | 旧多组 CLI 接口只在兼容范围保留，不能为新任务绕过组绑定 |
| 模型 | QuantCode URL + API Key，一套 Provider/计量/错误状态 | 旧远程 QUANTCODE_API_KEY 不是长期待补配置；不得靠额外密钥维护两层推理 |
| 权限 | 原生文件/Shell、MCP、子 Agent、HTTP、事件都检查；前端/Skill 不是授权 | 旧 allow/ask/deny、Hint 和目录过滤不能替代执行准入 |
| UI | 桌面产品；GitGraph 六列缩略卡片，详情分支/diff；Admin 四页签 | 不新增手机范围；原生任务与组织页必须保持单一导航和状态 |
| Memory | 长期知识与 checkpoint/progress/trace 区分；共享写入有来源与确认 | Design §9.2 旧表将 checkpoint 列入 Memory 浏览器的描述不作为新 UI 要求 |
| 测试时间 | 按用户要求先实现，再集中测试 | M1/M2/M3 可以依次形成未启用实现，不能将“实现待验”标成行为已通过；实际入口启用/旧执行器退役排在最终验证之后 |
| 来源与命名 | 同仓维护，保留许可证和第三方协议；自身产品与发布命名统一 | 不做全仓替换，不覆盖既有配置、历史、凭据 |

已复核：FUNCTIONAL_SPEC D-001~D-017、PRD 产品边界与模型说明、Design §3/§4/§14、UI 规格、REPOSITORY_LAYOUT、设计缺口审计的后续决策说明。旧状态表保留时间与“迁移来源”标记，不能用旧 IMPLEMENTED 证明新执行器已满足约束。

## 2. 实际调用链与旁路清单

路径以下均为仓库相对路径，可由源码直接定位。此表记录现状与 M1~M4 修改落点，不声称所有入口已经保护。

| ID | 已读取的入口 → 实际实现 | 现有行为 / 迁移要求 |
|---|---|---|
| E01 | `frontend/packages/desktop/src/main/sidecar.ts` → `virtual:opencode-server`；`electron.vite.config.ts` 将其解析为本仓库 opencode/dist/node | 桌面确实使用内置宿主；需核对发布构建/来源，不另装上游产品 |
| E02 | `app/src/pages/home.tsx:QuantCodeHome` → tabs.newDraft → 原生 session composer → SDK `/session/...` | 首页目前仍通过 instructions.ts 强制转交 Python run_agent；M2 才切换 |
| E03 | `opencode/src/server/routes/instance/httpapi/handlers/session.ts` → SessionPrompt.prompt/promptAsync/loop/command/shell | 当前桌面默认执行链是 opencode/session/prompt.ts → SessionTools.resolve → LLM/Provider；同仓 Core SessionV2 不是该默认链 |
| E04 | `opencode/.../httpapi/server.ts:createRoutes` 同时挂载 instanceRoutes 与 serverRoutes；serverRoutes 绑定 `@opencode-ai/server` 的 Api/handlers | `/api/session` 等 Core V2 面仍可到达；QuantCode 模式下必须限制另一路写/执行入口，或让其明确兼容到同一执行路径。不能仅因桌面不调用就忽略 |
| E05 | `session/session.ts` create/get/list/listGlobal/children/fork/patch → EventV2Bridge → SessionTable | M1 草稿已绑定部分 owner；仍需区分用户读取、执行器内部持久化、Admin 只读和 legacy 读取。session metadata 更新、workspace 修改不能扩大授权 |
| E06 | `httpapi/handlers/session.ts:message` 直接 MessageV2.get；分页 messages 直接 MessageV2.page；updatePart 可写公开 Part | 单消息读取必须加 owner 校验；外部 updatePart 不能伪造工具完成、usage、方案批准或证据。审计不能信任可编辑消息作为授权事实 |
| E07 | `SessionPrompt.runLoop` → `SessionTools.resolve` → registry tools 或 MCP.tools | plugin.before 在工具前可变更 args；准入摘要必须在最终参数确定后产生。原生与 MCP tools 共用组织 policy，资源读工具也需要 ACL |
| E08 | `tool/tool.ts:wrap`、`tool/task.ts`、`prompt.ts:handleSubtask/createUserMessage` | 有直接工具执行路径不经过常规 SessionTools 包装；新约束应落在可覆盖所有路径的可信边界，不能只保护外层 wrapper |
| E09 | `tool/task.ts` → sessions.create(parentID) → promptOps.prompt；BackgroundJob + SessionRunState | 子任务使用同一引擎；继承 owner、workspace、预算树和父方案。恢复 task_id 不可接管其他父任务；取消应终止实际子进程/子 fiber |
| E10 | `prompt.ts:shellImpl/command`；`tool/shell.ts` 参数解析与 spawner；`tool/external-directory.ts` | slash 命令 shell 插值和直接 shell 也是执行入口；现有路径扫描/cwd/ask 不构成 OS sandbox。M1 必须提供实际文件写范围和秘密隔离，不能用命令 regex 保证任意程序行为 |
| E11 | `httpapi/handlers/file.ts` → Core FileSystem/Location/Ripgrep | 原生文件浏览可不带 session；需要认证工作区访问能力，不把请求 directory 当授权。路径 canonicalization/符号链接/附件原始读取一起检查 |
| E12 | `httpapi/handlers/pty.ts` → Core Pty + ticket；ptyConnectHandlers WebSocket；Core `/api/pty` 同时存在 | 创建 cwd/env、列举、读取、写入与 ticket 使用均需 actor/workspace 绑定；身份变化使已开连接失效。手动终端与 Agent Shell 的运行身份都不能拿到生产凭据 |
| E13 | `httpapi/handlers/event.ts` → EventV2 按 directory/workspace 过滤；`handlers/global.ts` → GlobalBus 全事件 | 现有目录过滤不等于用户过滤。SSE/全局事件/sync 回放需要按 actor、session 授权，长连接期间重新检查身份；不把敏感载荷先发到前端再隐藏 |
| E14 | `permission/index.ts` pending Deferred、approved 规则；permission/question HTTP handlers | 原生 once/always 不能成为共享写入的泛授权。Gate 精确绑定操作摘要/资源/版本/审批人，批准后执行前再核验；修订参数需新决定 |
| E15 | `session/llm.ts` AI SDK/native adapter → SessionProcessor → step-finish tokens/cost | 统一计量覆盖主/子模型、title/summary/compaction 等辅助请求；预算预留/结算必须防止并发子任务透支，不只事后相加 |
| E16 | `session/run-state.ts` → Runner、BackgroundJob；`compaction.ts/revert.ts` 与 SessionPrompt.loop | 通用停止/恢复应复用；需增加撤销后的停止、未知副作用回执阻断，不能删后端记录就视为取消 |
| E17 | `quantcode/mcp_server.py` list_tools/call_tool → effective catalog → run_agent/组织工具；`mcp_host.py` SSH relay → `remote_mcp.py` sandbox | MCP 身份来自 gateway。M2/M4 退出旧循环时，新的服务目录与遗留恢复分开；不能把 _model None 的业务工具伪装可用 |
| E18 | `tools/solution/_register.py`、`runner/solution_workflow.py`、`schemas/solution_doc.py` | 旧工具允许参数 confirm=True；新链不得把模型给的 confirm 当用户确认。保留文档契约/版本，重接可信 UI 冻结入口 |
| E19 | `app/.../quantcode/admin-console.tsx`、panels.tsx → instructions；`handlers/experimental.ts` → Admin/history 工具 | 目前 admin_* 结果回流仍依赖旧 trace。M3 改为直接消费任务事件/组织索引；不能把当前成员数据库的宽过滤视为跨成员汇总 |
| E20 | `runner/run_history.py` → 本 runtime checkpoints.db；metrics.py、Blackboard、候选目录 | 多成员 runtime 按个人目录隔离；需组织服务共享索引/授权投影，保留原生任务为状态事实源 |
| E21 | `quantcode/gateway.py` /memory/search、/deployments、/receipts/reconcile；`runner/admin_operations.py` | 管理通道与研究执行分离；真实外部 executor 仍属待接，不把统一 loop 当作生产部署权限 |
| E22 | `session-ui/.../quantcode-trace-bridge.ts`、app/session.tsx completed run_agent listener | M3 改为 session 原生消息/工具事件，不解析最终回答；旧 bridge 仅供 legacy 读取与兼容 |
| E23 | `core/global.ts`、opencode/config 与 auth、app settings、desktop packaging | 已有 QuantCode 独立目录改动；尚需旧数据导入与安装/升级验证，不复制旧个人 API key、默认供应商或隐藏上游账户入口 |

## 3. 旧 Runner 约束迁移表

| 约束 / 决策锁 | 原实现与事实源 | 目标执行接点与输出 | 不能丢失的边界 |
|---|---|---|---|
| 身份/组/workspace，D-001/007/010 | identity/gateway、SessionContext、remote_mcp；M1 identity.ts 草稿 | 会话准入生成不可伪造 owner；请求/执行/事件读取查 gateway | UI 参数和公开 metadata 不可授权；旧任务不能归给当前登录者 |
| Memory 隔离，D-002/013 | memory/service/grants、gateway.search_memory | 组织服务 RPC；统一任务引用授权查询结果及来源 | 同组共享不等于各人本地目录；Runtime State 不晋升长期事实 |
| 复用/缺口决定，D-003/004 | agent_nodes capability_catalog_checked、distill/cards、SolutionStore | 可信目录/Memory 查询回执、coverage proposal 和用户决定；工具前检查 | 模型声称 full coverage 不是已覆盖证明；引用必须来自当前可见目录，缺口结果修改使批准失效 |
| 方案，P-10 | task_classifier、solution_workflow、SolutionDoc、Blackboard | 复用分类/方案文档；任务→方案版本/摘要绑定；可信 UI 冻结，写工具校验 file_impact | L0/L1 不增加固定讨论；L2/L3 未冻结拒绝，子任务/后续请求不能弱化父方案 |
| Tool Catalog | registry.py、组 allowlist、permissions.yaml | 维护员发布的不可变工具元数据 → 定义过滤与调用使用同一计算结果 | 命名 read_ 前缀不等于可信 read effect；自定义工具默认不能凭名字自授权限 |
| Gate，D-006/008/009 | human_gate.py、permission_engine、受保护工具的精确输入/证据 | 组织 Gate 服务 + native permission UI 绑定精确 call/version；模型不持批准能力 | 仅 merge/permission；生产始终独立 Admin 面；拒绝/撤销/参数变化后不能重放 |
| Evidence/回执，P-06 | evidence.py、tool_receipts.py、receipt_reconciliation.py | 复用已存在执行前 intent、COMPLETED、未知结果、审核记录；原生 session/callID 映射 | 完成回执必须可重放结果；不可另存一个只标 failed/completed 的弱回执表 |
| 迭代/循环/预算 | agent_nodes/routing、loop_detector、parallel_registry；原生 Processor usage | 原生 run-state/LLM 请求准入及 usage 结算、root budget | 并发子任务不能每人独享全树额度；辅助模型调用必须计入 |
| 上下文/恢复 | 原生 compaction/messages、旧 LangGraph checkpoints | 新 session 用原生恢复；旧 checkpoint 保留 engine/version 标签与兼容适配 | 不迁移成新的 LLM 请求来“恢复”；不读取过期 checkpoint 恢复权限 |
| 子任务，P-04 | tools/subagent、parallel_registry；原生 TaskTool/BackgroundJob | 新任务只用原生 TaskTool，统一 parent/root/owner/model/budget | 兼容旧 spawn 不能成为新任务第二 loop；取消实际阻止后续动作 |
| 能力/计算，D-005/012 | canonical adapters、schemas、能力卡 | 单步组织/组件工具；共享 Provider 对专用推理请求供给模型 | 不新增通用 Python 思考循环；UNAVAILABLE/STAGING 不能变生产成功 |
| Admin/知识候选 | admin_tools、run_history、dream_consumer、distill/governance | 基于 native event 的跨成员授权投影，复用知识/Skill 审核 | 数据归属、来源、schema 版本与错误状态都保留；新旧事件不可重复消费 |

## 4. 数据兼容与持久化权威

| 数据 | 当前存储 / 读取 | 迁移规则 |
|---|---|---|
| 原生 session/messages/part/todo | core/session/sql.ts + EventV2 durable store / projections | 新任务唯一执行事实源。owner 由可信会话创建；公共 metadata/updatePart 不可写执行证据 |
| 旧原生 session 无 owner | 同上，metadata.quantcode 缺失 | 保留、标 legacy-unbound；需来源核对的显式导入，不自动附上当前 actor；不能全面隐藏后无恢复入口 |
| Python checkpoint、writes | .quantcode/checkpoints.db / LangGraph SqliteSaver | 原库只读保留；旧执行器身份/版本与 thread_id 固定；只支持原任务恢复，不接受新 task |
| trace/metrics/streams | 各成员 .quantcode 下 jsonl 与日志 | 旧历史不删；新事件统一按 native session/call/event ID 索引，组织视图为投影；新旧 key 不冲突 |
| SolutionDoc | artifacts/solutions 与 Blackboard shared.solutions | 复用 schema/version/hash；可信冻结记录与方案版本关联，避免在另一表复制完整方案成为双主 |
| Memory / FTS5 | 共享 gateway 根、各成员旧 memory/service 路径 | shared authority 不变；索引可重建，正文/来源/验证状态和 ACL 不丢；个人记录未经确认不批量晋升 |
| Blackboard | blackboard.db，scope/producer/consumer/schema | scope 契约不变；跨成员 handoff 转共享服务后旧引用可解析，不把组名或本机路径当授权 |
| Gate / 审核 | checkpoint interrupt + evidence | 旧 Gate 用原协议兼容；新 Gate 精确绑定操作，不将 once/always 规则导入为广泛共享写权限 |
| 副作用回执 | .tool-receipts.db 的 tool_receipts、receipt_reviews | 复用结果校验与未知执行态，必要时加 engine/schema 字段；不重放 UNKNOWN；保持确定性去重键 |
| Provider/Auth/SSH | QuantCode 宿主私有目录；gateway token/public key bridge | 新任务只用一个 Provider。不得自动复制 OpenCode 个人账号；密钥不进入模型、索引或审计正文 |
| GitGraph/Pop | 宿主 pops.db / branch/commit cache / actor receipt | 保留既有 six-column UI 与精确 GitHub subject/ACL，非执行状态机，不需迁入 native session 表 |
| 部署记录 | gateway deployments.db + external executor | Admin-only；不随普通任务恢复执行；保持幂等与产物摘要 |
| 发布源码/许可 | frontend/LICENSE、同仓 package/lock/SDK、desktop workflow | 来源保留、依赖锁定；内部旧 namespace 可兼容，不把源代码改名当完成功能 |

## 5. M1 草稿静态复核结论

### identity.ts 与已挂接的调用

可保留的基础：从私有文件读取 gateway token；重新查权威 session；前后 credential digest 防止登录切换；宿主创建 binding；metadata patch 保留 binding；子任务 parent_id 检查；MCP 定义复制避免跨 session 包装污染。

必须先修正的缺口：

- `enabled()` 目前只看 OPENCODE_CHANNEL，草稿会在 QuantCode 服务启动时直接生效；需要显式、宿主控制的迁移启用开关，在最终阶段验收前默认关闭，不能通过聊天或 config payload开启。
- `get()` 统一 requireOwner 会拒绝旧无绑定记录，且尚未提供 legacy view；读取、执行和 Admin 审计授权必须拆清楚，避免破坏旧历史读取。
- messages 单条读取、status、global SSE、sync、V2 API、文件/PTY 等入口未覆盖；不能把已挂的 wrapper 视为完整权限层。
- 凭据检查是 lstat→readFile，会有文件替换窗口；后续应使用已打开文件描述符 stat/read 与替换校验，并让 Windows ACL 有明确处理。
- 每工具前后多次验证还需收敛：不可缓存授权结果逃过撤销，但可以复用同次操作的身份快照并在边界重新校验。辅助模型与中途取消也需要覆盖。

### runner/runtime_governance.py

结论：**不进入目标调用链；以现有模块重构替代，不继续扩展这份实现。**

理由：runtime_policy 内嵌 SolutionDoc、runtime_reviews 自建冻结记录、runtime_operations 自建回执，分别与 SolutionStore、既有审核/证据和 tool_receipts 重叠。其 failed 结算无法区分“尚未执行”和“执行结果未知”；方案 proposal 改动后 coverage_decision 可能沿用，full coverage 也只校验模型文本，不能满足 D-004。文件列表由调用方声明，尚无 Shell 实际写范围隔离。没有正式入口调用这份草稿，不迁移任何生产数据即可将其撤回。

替代方式：组织服务复用 task_classifier/SolutionStore/Memory/Catalog/receipt/evidence 实现，只新增必要的 native session 与现有资源的绑定及可信调用接口，不拥有 LLM/run 状态或复制完整方案。必要 schema 扩展要有一个事实源。

## 6. 严格阶段顺序与启用条件

| 阶段 | 实现交付 | 进入下一阶段前的代码核对 | 最终测试证明 / 启用门槛 |
|---|---|---|---|
| M0 | 本文、顶层文档、迁移/兼容/调用链矩阵 | 已读取所有表列入口；冲突、草稿缺陷、外部依赖明确 | 仅静态基线，不需启动运行；完成后进入 M1 |
| M1 | 唯一组织准入层、原生工具/MCP/子任务规则、精确 Gate、预算/回执、文件/PTY/SSE/历史保护 | E01~E23 均有实施或明确禁止的旁路；服务端派生权限而非模型参数 | 未认证/越权/撤销/未冻结/缺口写入拒绝；正常只读可行；Shell 和子任务不能绕过。未测时只算实现待验，开关关闭 |
| M2 | 单 Provider、新任务 native session、组织上下文、单步工具，清理强制转交模板 | M1 约束实现核对无遗漏后，再编写新入口；兼容恢复与新任务相互隔离 | 单次配置下真实任务闭环；UI 提交、工具和停止同属一个 session；M1 通过前不启用 |
| M3 | 原生事件到 Activity/树/方案/Admin、跨成员索引、恢复/撤销、legacy 兼容 | M2 新模型和任务路径唯一；projection 不调度执行，旧记录来源明确 | 断线继续、实际取消、跨成员审批/汇总、legacy 回放无重复副作用；不得用 fixture 代替全套真实链路 |
| M4 | 最终目录/命名/旧执行入口收敛、迁移工具、打包发布说明 | M1~M3 实现依次核对后准备清理，不删除仍需兼容的历史/恢复 | 集中测试先验证 M1，再 M2/M3，最后开启新链并验收 M4；不满足时保持旧数据和回退路径、返回对应阶段修复 |

“先实现后测试”改变测试执行时机，不改变阶段实现顺序，也不允许测试前启用新执行入口或退役旧引擎。本次不新增产品层审批步骤；阶段验收是工程工作，不要求用户重复批准既已授权的迁移。

## 7. 原文七项标准逐项证明要求

| 原文标准 | 阶段覆盖 | 必须提供的最终证据 |
|---|---|---|
| 1 一份源码/发布 | M0/M4 | 从锁定源码构建 Electron/宿主/SDK，安装运行不另装 OpenCode；许可证和来源文件存在 |
| 2 一套产品入口 | M2/M3/M4 | 桌面任务、编辑器、终端、组织页共享导航/session；UI 截图与真实操作，六列 GitGraph、Admin 四页签不回退 |
| 3 一套模型配置 | M1/M2 | URL/API Key 一次配置后模型执行、工具调用、辅助推理；轮换/撤销失败状态；日志/事件/产物不含凭据 |
| 4 一套任务事实源 | M2/M3 | native session/call/event 父子链、用量、取消/恢复；组织索引可重建；无并行 Python 新任务 loop |
| 5 组织约束 | M1/M3 | 认证/ACL/方案/Gate/预算/回执/FS/PTY/SSE全路径正负例；包括直接 API 绕过和执行中撤销 |
| 6 可维护性 | M0/M4 | 架构映射、包边界、SDK 生成与回归、锁定依赖、同仓发布流程；无重复执行器与重复组织事实源 |
| 7 兼容边界 | M3/M4 | 原生无 owner 历史、旧 checkpoint/Gate/receipt/config 的导入/只读/恢复场景，旧调用不能创建新任务 |

## 8. 最终统一验证清单（现在不执行）

1. Python 全仓 pytest/Ruff；原生 app unit/browser，opencode、受影响 core/server/SDK 包的单元与类型检查；desktop 类型与打包检查。`scripts/verify_product_audit.sh` 只是现有入口，不足以覆盖新增安全旁路，需要补专项。
2. E01~E23 的身份/权限/API 绕过、任务取消、事件撤销、秘密隔离专项；至少两个不同成员身份加 approver/Admin，验证允许路径和拒绝路径。
3. 单一真实模型配置下的查询能力、读文件、组件调用、结果记录、恢复和子 Agent。组件不可用时只验证诚实错误，不能冒充成功调用。
4. 精确方案/缺口确认、shared-write/permission Gate 修改参数与重复提交、未知副作用回执及核对恢复。
5. 旧数据备份/只读/显式兼容，恶意/无身份记录不能自动认领；取消与历史浏览不产生新执行。
6. 桌面 1440/1920 等窗口的统一任务 UI、六列 GitGraph、Admin 页签、方案/Gate/子任务交互；不做手机适配。
7. 构建、安装、升级/旧配置兼容，核对未出现上游独立产品依赖；本地生产基准在最终验证时与保留的基线版本比较。用户要求实现期间不测试，因此不能声称已有新的性能验收结果。

真实外部条件：至少一个可用模型接口、一个已接入且可授权调用的组件、跨成员有效身份/凭据、必要的签名/平台构建环境和组织索引服务。当前源码已有不等于条件可用；验证时实查，缺项保持未完成，不能减少目标或伪造结果。

## 9. M0 关闭结论

M0 的六类交付已在本文逐项落实：规范冲突、调用链、旧能力映射、数据兼容、阶段矩阵、草稿复核。允许开始 M1 实现修正。**没有任何 M1 运行通过或 M2~M4 完成结论。**下一步先撤回未接线的重复治理草稿，并隔离未验收的身份改动，随后按 E01~E23 接组织约束。

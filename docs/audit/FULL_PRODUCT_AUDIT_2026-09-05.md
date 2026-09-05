# QuantCode 产品与工程复核 · 2026-09-05

本报告依据 FUNCTIONAL_SPEC v0.5.1、PRD v5.1、QuantCode_Design v5.1，以 UI_DESIGN_SPEC v4.1 补充界面验收。用户提供的 [HKUST 组件统计](../references/HKUST_QUANT_COMPONENTS_GUIDE.md) 是复用边界的补充资料，不覆盖三份顶层设计，也不视为 GitHub 实时状态证明。

## 当前目标与验收顺序

本文件是当前状态台账，后续实现直接更新本表，不以追加旧批次结论代替状态维护。

本阶段目标为本地 Dev 可初步使用。用户明确暂不验收 Mac/Windows 安装包，且要求先完成全部功能修复，再统一 pytest，最后 Headless UI 验收。本地功能增量已进入统一验收：后端全量 pytest → 前端类型/组件 → Headless UI 按顺序执行。当前自动回归通过，但真实身份、MCP 与外部服务闭环尚未通过。

后端工作区为 `QUANTcode`；前端为独立仓库 `opencode-lens`。已有修复已推送两仓库 main；本轮增量在自动回归后交付，真实服务接通仍须单独验收。未修改用户的 `AI_Agent_Group_未来发展思考.md`。

状态定义：**已有本地证据**表示之前的实现有相应测试；**实现待验收**表示代码已补入但尚未统一检查；**部分**表示仍有功能缺口；**待接入**表示真实外部系统未完成联调。任何一类都不能直接等同于产品全量验收通过。

## 本轮统一验收证据

2026-09-05 在当前两个工作区执行：

| 检查 | 结果 | 证明范围 |
|---|---|---|
| 后端全量 pytest | **1,125 passed / 4 skipped**，21.73 秒 | 当前后端回归；新增回执重放、崩溃拒绝重试、身份变更、摘要完整性、人工核对及目录即时回源。4 项真实 LLM 测试跳过，不算通过 |
| 前端与宿主类型检查 | 两个包 `bun typecheck` 均通过 | app 与 opencode 类型一致性 |
| QuantCode 组件测试 | **126 passed / 0 failed** | 当前 16 个组件测试文件；管理入口从占位改为实际任务/报告导航 |
| 本地 Dev Headless UI | **12 passed**，15.6 秒 | 复用 localhost:4444；身份/角色展示、Memory、两种尺寸、历史分页与未知回执阻止恢复、目录刷新、GitGraph 分页和通知确认。MCP 响应采用明确 fixture，不证明真实 SSH/服务权限 |
| 实读 localhost:4096 | **未通过真实接线** | `/experimental/quantcode/identities` 返回 HTML；`session_context` 返回 `QuantCode MCP is not connected`。当前宿主进程未加载新增身份路由 |

本轮发现并修复：候选错误分类与测试发布路径隔离；旧测试对身份切换/方案缺失/分页响应的错误前提；工具完成回执新增结果摘要，内容或类型损坏、旧回执无摘要时拒绝自动恢复。跨组回执核对被拒绝，审核保存不启动任务。Headless 的面板入场动画导致跨帧坐标测量不稳定，改为同帧测量，未降低内边距断言。

**台账尚未全通过。** 尚缺真实 roster/SSH gateway/MCP、GitHub subject 凭据与组件服务联调；新宿主接口需要由当前服务器加载。前端 `packages/app/AGENTS.md` 明令禁止代理重启应用/服务器，本轮未重启 4096 或 4444。以下逐项“待验收”还包括自动回归未覆盖的真实服务、长任务与跨进程故障场景，不因汇总数字通过而自动销项。

## 逐项功能台账

| 基线 | 当前证据与当前处理 | 尚未做到 / 验收边界 |
|---|---|---|
| F-01 任务与组路由 | `quantcode/mcp_server.py`、identity、effective catalog；八组 stdio 启动/发现/拒绝非法工具回归。UI 使用服务端组与 Skill；未认证不显示默认 factor；切服务清除旧会话引用 | 部分、待接入：本机公钥选择、SSH agent 签名、gateway 会话和 MCP 重连已接线，真实闭环未验收；浏览器角色测试使用明确 fixture |
| F-02 执行记录与恢复 | 服务端分页历史、checkpoint 消息/产物回放、普通恢复协议与 MCP 单任务进程锁；认证任务默认持久事件，恢复权限重验 | 实现待验收：新增事件分页、损坏提示、身份权限变更拒绝尚未统一检查；跨机器和真实长任务副作用恢复仍待验 |
| F-03 HumanGate | permission/merge 白名单、拒绝路径、审批 evidence；同组持久队列支持游标分页，提交绑定 Gate/checkpoint；跨人审批重验创建者身份 | 实现待验收：新增长队列和创建者撤销/过期路径尚未检查；真实 interrupt→审批→resume 待验。风险/预算/CI 不扩充 Gate |
| F-04 Memory/能力目录 | `runner/memory`、`runner/distill`；修复 LIMIT 前排除 Runtime State、坏索引报错、搜索竞态与输入失焦；Admin 跨组/项目读取留痕；卡片补输入输出依赖与别名 | 部分：项目检索已补 roster scope 与可撤销/过期 ACL 双重校验，默认无授权；当前实现待统一验收；卡片实时状态同步待接 |
| F-05 SSH | challenge/roster/session 后端及单测存在；UI 区分 HTTP 服务连通和身份认证，移除默认供应商“已配置”假象 | 待接入：本地 agent/keychain 签名、真实 SSH gateway、主机/密钥/roster 各失败状态的桌面闭环未完成 |
| F-06 组件适配 | `tools/factor`、FactorPanel、QuantEvaluator adapter 与状态契约；12 个主链组件已登记；移除 PIT 前端私算估值 | 部分、待接入：目录存在不代表组件已接通；DataAccess→FE→QE 等真实输入/输出/版本/artifact 尚需服务验收；不自建替代组件 |
| F-07 跨组协同 | Blackboard、Model→Risk CI、事务/去重及 handoff 测试存在；领域 verdict 不创建 Gate | 已有本地证据；真实 GitHub Actions/报告平台交付链未验收，维持 CI 基建定位 |
| F-08 领域工具 | 六组 flows 和 strategy/options/fundamental/portfolio 回归存在 | 部分、待接入：stub/proxy/本地引擎不能冒充 canonical；保留组内适配，不增加统一业务产品 |
| F-09 Admin/GitGraph/Pop | 明细/身份/快照适配；可见分支与 HEAD、近期提交 DAG、凭据映射、个人 Pop read/ack、含子目录的依赖版本解析及 Dev 每分钟同步已补入；管理页组织任务/报告查询 | 部分、待验收：真实 GitHub 凭据未配置；gateway 后台调度已补入待验收，实际服务未部署；部分动态依赖仍缺；本机系统提醒已接入待验收；现有图按 F-09 显示全部授权分支及近期提交窗口 |
| P-01 数据契约 | `schemas/data_contracts.py`、market/factor tests，缺源必须 no_source/UNAVAILABLE | STAGING：真实 ReturnsDataset/DataAccess 来源、PIT/交易日/label 版本一致性需真数据验收 |
| P-02 回测 | strategy adapter、backtest 回归；不扩充统一回测 UI | STAGING：VectorBT-QS fast/accurate 真组件回放及 A 股约束由组件证明 |
| P-03 组合 | portfolio adapter/verdict 测试、移除人审旧语义 | STAGING：Riskfolio-QS 的 alpha/risk/benchmark/previous_positions 到 target_positions/trades 闭环未验收 |
| P-04 Subagent | `tools/subagent`、parallel registry、预算/身份继承和 kill 回归 | 已有本地证据；真实跨进程、长时间并发负载未压测 |
| P-05 实验 | `tools/experiments`、OOS/ledger/artifact 测试 | 已有本地证据；外部实验平台消费与真实数据实验不在当前证据内 |
| P-06 Evidence | 哈希链与关键写入 fail-closed；已补 Admin 敏感读取审计、permission 决策结构、实际审批人和原 Gate 关联 | 已有本地证据；外部审计消费/长期归档需运营验证 |
| P-07 蒸馏与复用 | 候选生成/晋升/拒绝/supersede、strict reuse；摘要包含 maturity/integration 和“不重复造轮子”；提供组件交叉表 | 部分：定时消费入口不等于生产 timer 已启用；定期实读 GitHub、人工确认冲突、状态刷新未闭环 |
| P-08 Admin 中枢 | 全组运行/错误/Blackboard 查询与角色检查；新增敏感读取审计；UI 明细和错误状态已修复 | 部分：组织任务/报告查询已补入并要求跨组读取审计；后台 GitHub 汇聚、持久审批队列和异常调用人工核对已补入；角色隔离与真实服务仍待统一验收 |
| P-09 Admin Deploy | `runner/admin_operations.py` 黑盒 STAGING + required evidence；八组 MCP 不注册 deploy | STAGING：本地部署记录、幂等暂存/取消及 Admin 管理界面已补入待验收；生产执行队列、回滚协议与服务账号尚未接通；不会伪造生产成功 |
| P-10 Solution-First | 分级/工作流/一致性判定；执行前回源方案并核验摘要，废弃、缺失、读取失败均限制写操作，移除跨进程失效缓存 | 实现待验收：新增方案失效和恢复路径尚未检查；真实 L2/L3 冻结、执行、偏离检测端到端仍未验收 |

## 决策锁 D-001～D-015

| 决策 | 核验结论 |
|---|---|
| D-001 单 Session 单组 | 后端强制、UI 无自由切组；真实 gateway 待接 |
| D-002 长期组 Memory | 组隔离保留，Runtime 检索挤占修复；项目授权不能由组推定 |
| D-003 先查能力与 Memory | 生产 strict reuse、卡片摘要和缺口流程有回归；真实 LLM 行为测试未启用 |
| D-004 缺口由用户决定 | 既有 reuse/solution 约束保留；不得把 UNVERIFIED 自动提升为 CONNECTED |
| D-005 平台只发现/编排/适配 | PIT 组件取消本地估值重算；领域判断归组件/研究员 |
| D-006 Gate 仅两种 | merge/permission 测试通过；预算与风险结果不变成审批 |
| D-007 Admin 全组织且留痕 | 明细输出修复；敏感读取加入 required 审计；完整管理工作台仍部分 |
| D-008 不进入生产 | 普通 Agent 无生产操作入口；实际环境隔离须部署验收 |
| D-009 deploy 属 Admin | MCP 八组非法调用回归；部署 adapter 仍 STAGING |
| D-010 私钥留本地 | 当前 UI 无私钥输入/上传；真实 keychain/agent 签名未验收 |
| D-011 完整图与提醒 | 全部授权仓库/分支/HEAD、近期提交关系、依赖差异、个人提醒已补入待验收。按 F-09 定义保留近期提交，不把无限历史加载增加为验收条件 |
| D-012 canonical 业务真相 | 组件统计对照、卡片依赖与别名已补；无真数据不编造指标 |
| D-013 唯一数据/标签权威 | schema/缺源失败回归；真实来源待验 |
| D-014 保留底座 | 未替换 OpenCode 会话/编辑器/运行时基础设施；只改 QuantCode 增量 |
| D-015 测试服从规范 | 删除前端自行估值的旧测试前提；新增失败、权限、实际载荷和浏览器测试 |

## UI 断言 U1～U9

| 断言 | 当前证据 | 缺口 |
|---|---|---|
| U1 登录 | 未认证禁止提交，不把 HTTP 当 SSH，无私钥字段 | 真 SSH 三方联动与失败分类未验 |
| U2 组路由 | 三角色浏览器 fixture + 八组后端权限回归 | 实际 roster 会话未端到端运行 |
| U3 任务/方案 | 方案面板与后端分级测试 | 真任务冻结/恢复未做浏览器全链 |
| U4 执行记录 | 新增服务端历史与 checkpoint 只读回放界面；原有当前运行面板保留 | 实现待验收：刷新、隔离、错误状态、产物与真实任务恢复 |
| U5 Memory/能力 | 输入焦点、竞态、503、组 ACL、真实 SQLite、卡片元数据；两种尺寸滚动 | 项目 grant、知识审核及发布中恢复已补入待验收；能力目录刷新回源最新配置，真实组件接通状态仍需服务验收 |
| U6 Gate | 白名单、批准/拒绝证据、审批者 | 真浏览器跨角色审批待验 |
| U7 Admin/GitGraph/Pop | 授权 GitGraph 分支/HEAD 和近期提交、持久 Pop read/ack、组织历史入口已补入 | 新增功能待统一验收；gateway 后台同步已补入待验收，尚未部署；本机系统提醒已接入待验收 |
| U8 部署 | 普通 MCP 不存在 deploy；Admin 暂存、查询、取消与本地持久服务已补入 | UI 待统一验收；生产执行、状态回传与回滚仍未接入 |
| U9 外部结果 | HTTP/坏载荷显式失败；PIT 原样展示有来源的结果、缺失为 —、零值保留 | 其他领域结果的生产格式仍需各组件提供样本联调 |

视觉参照是现有对话主页的黑白、细线、克制文字层级。详情页统一纸面底色、内边距、小标题和滚动容器；短桌面保留设置入口；长列表滚动时关闭按钮保持可见。没有把主页面改成仪表盘。900×650 与 1440×900 的实测截图保存在前端 `packages/app/e2e/test-results/quantcode/`。

## 全量验收尚未关闭的事项

1. F-01/F-05：真实 SSH agent/keychain、gateway、roster 与桌面接通。八组已实现；人员表 46 条提交、39 个身份标识、31 条密钥绑定候选，10 人有待确认项。正式 roster 尚未激活，角色和真实工作目录不能根据姓名推断。
2. F-02/F-03/P-10：普通恢复预览绑定、审批队列分页、持久事件与方案失效限制已补入，待统一验收；已补认证 Agent 写工具的持久回执：调用前提交 STARTED，成功结果提交 COMPLETED，恢复同一调用时重放已完成结果；缺少完成回执时停止自动执行，不猜测外部结果。权限 interrupt 顺序保留，merge_to_main 继续使用领域 code_hash 幂等机制。历史页已补未确认调用 ID、工具名和摘要，并禁止恢复；回执库不可读时仍保留消息/产物回放，恢复入口再次拒绝。已补 gateway 专用人工核对接口：同组 approver/admin 绑定 checkpoint 和原摘要、提供证据引用与说明；可恢复原结果或确认未执行后标为 RETRY_ALLOWED。原回执和审核同事务保留，required evidence 先记录意图，不自动启动任务，也不加入模型工具目录。桌面历史页已补证据引用、核对说明、原始结果与明确确认表单，专用宿主路由核对同一 gateway/MCP 会话后转交，不向浏览器暴露凭据；完成后只刷新历史。历史详情还展示已提交审核人、时间、调用 ID、证据、结论与结果摘要，记录读取失败显式提示，不将审核成功等同于任务已恢复。接口客户端已重新生成；完整故障注入、角色隔离和 UI 操作仍待统一验收。
3. F-04/P-07：项目 grant 解析、过期/撤销校验和候选预览/晋升/拒绝/替代界面已补入，待统一验收。发布中恢复、撤销、来源摘要和过期加载校验已补入；目录排除非生效发布并返回不可用原因。目录读取与复用策略改为即时回源配置，重复 ID/坏配置显式失败；目录接口补输入输出、依赖、消费者、别名和来源字段，UI 可主动刷新。仍需统一故障验收；外部组件状态不可通过本地刷新伪造。
4. F-06/F-08/P-01～03：按组件复用表接通真实输入输出、版本和 artifact。真数据/组件缺失必须明确报告，不能由前端编造结果。
5. F-09/P-08/P-09：组织历史、个人 Pop read/ack、实时仓库权限重验、Dev 每分钟同步、可见分支/HEAD/近期 DAG、含子目录的依赖版本及 Admin 暂存/取消已补入，待验收。本机系统提醒已接入待验收；通知长列表分页与全量授权未读计数已补入；gateway 后台循环与状态查询已补入；静态组引用和 requirements 本仓库引用已补入；动态依赖仅可追踪声明，不执行构建代码；生产部署执行需要真实服务契约。
6. F-07/P-04～06：补齐真实交付、长时间并发与外部平台消费所需接线；保留权限和 evidence 约束。

## 统一验收执行与后续边界

前三项自动检查已执行，具体证据见上表；仍未证明真实服务闭环：

1. 后端 pytest 全量；覆盖新增历史分页与权限、普通恢复、进程竞争、通知持久化、项目授权与适配器失败路径。
2. 前端类型/组件与接口生成一致性检查；任何失败返回实现阶段修复。
3. 本地 Dev 的 Headless UI：登录、任务/方案、历史回放、跨角色 Gate、Memory/能力、管理/GitGraph/通知、部署入口和错误状态。
4. 已接入服务的真实端到端、长任务中断与恢复，记录来源、账号范围和产物。尚无外部配置的项目保持未通过，不能用 fixture 证明已接通。

Mac/Windows 安装包验收不属于用户当前要求。本地 Dev 已有启动基础，不重复把“能打开页面”作为功能完成。

此前最近一次已提交后端回归为 1,113 passed / 4 skipped；前端组件 126 项、Playwright 9 项通过。这些仅证明对应旧提交，**不覆盖当前工作区新增实现**。历史修复说明分别保留在 F01_ROSTER_ACCEPTANCE、EIGHT_GROUPS_GITHUB、F02_RECOVERY_STREAM 文档中，本台账为当前判断入口。


## 当前 GitHub 实现边界

`runner/github_sync.py` 读取授权 repo 全部分支、HEAD，以及每分支最近 30 条提交；窗口外的父节点明确标注。完整成功的仓库快照才更新 SQLite 基线，同一事务插入去重 Pop。首次观测不生成更新提醒。

依赖跟踪读取默认分支固定 HEAD 对应的完整 Git tree，覆盖根目录和子目录清单，不跟随符号链接或子模块。递归响应被截断时逐层获取子树；不完整响应不更新基线。旧根目录基线升级到递归范围时重新建立比较基线，避免把已有子目录误报为新增。

除 Git blob 差异外，已补 package.json、package-lock v1/v2/v3、Bun 文本锁 v1、uv.lock、poetry.lock、pyproject.toml 和简单 requirements 的解析与包级 Pop。声明与锁定版本分开标记，保留依赖分组、安装位置及同包多版本。未变化 blob 按解析器版本复用缓存；旧的无解析基线不会被当作全量新增。解析失败保留上次完整基线；dependency-groups 支持规范化名称和 include-group，拒绝循环、缺失或重复规范名；requirements 支持本仓库 -r/-c、续行和 hash 参数，引用读取固定 HEAD 的同一 Git tree，约束与依赖分别展示。引用文件变化会重新解析，不沿用父清单的单文件缓存；缺失或越界引用拒绝更新基线。动态 Python 依赖、远程 include、环境替换和安装选项未执行，明确展示为仅文件跟踪。不宣称服务器已安装或升级依赖。上述新增代码尚未统一测试。

Dev 工作台存活且身份就绪时每分钟同步。GitGraph 可开启/关闭本机系统提醒，浏览器权限由用户点击开启时申请；复用平台通知接口，单次只发送新更新条数汇总。偏好和已发现 ID 按身份/工作区保存在本机，首次加载不补发旧通知，发送失败保留持久列表并提示。通知列表按时间和 ID 游标分页，ACL 过滤先于分页；角标使用后端授权范围内完整未读总数，已读/确认操作也返回该总数。加载历史页不会发送系统提醒，刷新与状态写入互斥。上述实现尚未统一验收。gateway 已补独立后台循环，每轮重新验证有效会话、roster 和 GitHub 权限，按身份工作区去重；最近尝试状态持久化并可经认证接口读取。较旧并发响应不得覆盖更新基线；缓存按完整身份、角色、工作区和资源权限隔离。默认分支元数据变化触发刷新，非空分支列表缺少默认分支时拒绝更新依赖基线。服务实际部署及真实同步尚未验收，后台运行不延长会话，也不在客户端关闭时发送系统通知。旧 trace 派生的 repo/package 临时提醒已从主页面消费路径移除，Gate 通知保留独立语义。


## 项目 Memory 与知识审核接线

项目检索要求 roster `resource_scopes` 包含 `memory:project:<project_id>:read`，且 `configs/project_grants.yaml` 存在匹配 actor 的 enabled 条目和未来的带时区 expires_at。配置每次查询读取，过期/撤销立即影响后续检索；当前 grants 为空，不代表已有项目授权。Admin 组织读取继续 required audit。

候选队列新增服务端正文与 SHA256 预览、前端审核操作。晋升请求携带预览摘要，拒绝修改后的草稿和覆盖已有 Skill；审核写入使用跨进程锁，发布前保存审核意图。发布已改为 intent → publishing → 原子安装 → 审计决策 → promoted；加载器仅接纳已提交且摘要匹配的发布，中断后可重试同一候选或撤销。所有本阶段新增项尚未运行统一 pytest/Headless UI。


## 知识发布一致性（实现待验收）

受治理 Skill 带 `.governance.json` 指向候选权威索引。Skill 文件安装采用临时文件 fsync 后非覆盖原子 link；审核意图及发布中状态先持久化，最终决策审计先于索引激活。加载器检查 promoted、发布路径/摘要、草稿摘要及可选 expires_at；撤销和已发布替代通过索引停用，保留文件证据。MCP Skill 目录也应用同一校验，返回不可用项目及原因。用户可在候选界面恢复未完成发布或撤销发布。旧的无摘要治理发布不会被自动补签批准。进程中断各阶段的统一故障测试尚未执行。


## 身份 Gateway（实现待验收）

新增 `quantcode.gateway` 本地 HTTP 服务：challenge/verify/session/logout，签名仍由既有 OpenSSH verifier 验证，token 仅存哈希，会话每次查询重验正式 roster。旧 SSH 指纹接入也已补缓存上下文的逐次 roster 核验，指纹、角色、工作区或资源权限变化均要求重连，撤销后不得继续沿用缓存授权。新增 `quantcode.identity_login` 宿主 CLI，使用 `ssh-keygen -Y sign -U` 要求 SSH agent 签名，仅读公钥；会话凭据以 0600 文件保存，不打印 token。

MCP 可配置 `QUANTCODE_IDENTITY_SESSION_FILE` 使用 gateway 身份，每次调用重新验证会话，拒绝到期/撤销或上下文变化，不回退指纹猜测。当前尚未启动新服务或激活人员授权，未运行身份测试；桌面登录按钮已接宿主固定 CLI，MCP 重连后核对同一 session_id，待统一验收。已向用户询问真实 gateway/roster/部署服务配置，凭据不通过聊天接收。


## Admin 部署管理接线（实现待验收）

新增持久 SQLite 部署台账：按 actor/request_id 幂等暂存，相同 key 不同内容拒绝；查询与取消暂存请求要求 Admin 和 required evidence。Gateway 暴露专用管理接口；OpenCode 管理路由先校验当前 MCP Admin，再要求本机 gateway 凭据的 session_id 与其一致。部署不注册到 MCP 工具目录，浏览器只提交产物引用/目标/版本，不接触 bearer token。

界面有暂存、查看和取消入口。生产执行器尚未配置，因此结果仅为 STAGING 或 CANCELLED，不能宣称生产部署功能完成。真实执行队列/状态回传/回滚契约仍等待外部配置。所有新增代码尚未进入统一 pytest 和 Headless UI 阶段。


## 本地登录界面接线（实现待验收）

OpenCode 新增宿主身份查询和固定登录操作；仅接受宿主配置的 Python/后端目录/公钥/gateway/会话路径，浏览器无任意命令或 URL 输入。设置页使用这些身份，登录成功后重连 QuantCode MCP，核验 gateway 与 MCP 的 session_id 一致再刷新工作区。并发签名请求共用在途操作，有超时边界，不打印签名或 token；HTTP 登录入口另对签名、MCP 重连、会话核对整个流程进行互斥准入。身份查询的配置、连接和载荷错误在设置页明确显示，不再吞掉错误后展示空列表；宿主验证公钥 base64 格式。上述改动尚未统一验收。配置步骤见 [LOCAL_IDENTITY_GATEWAY.md](../LOCAL_IDENTITY_GATEWAY.md)。当前未启动 gateway、未签入真实人员、未运行测试。


## GitHub 身份凭据接线（实现待验收）

新增宿主 `QUANTCODE_GITHUB_CREDENTIALS_FILE`：按已认证 github_subject 映射私有 token 文件，要求绝对路径、服务账号所有和 0600；每次读取重验权限，不在 SessionContext/trace 保存 token。GitGraph/Pop 沿用 /user 与 Team/repo 范围检查；已认证 PR 读取也采用同一范围，普通角色不继承中心 GITHUB_TOKEN。Admin 环境降级仅留给无角色的可信旧宿主调用，不能覆盖已有 Session Context 的 analyst/approver 角色。PR 文件查询补分页，已知未完整返回时拒绝把部分差异当完整评估。MCP 调用保留 gateway 签发的 session_id，不再用进程 ID 替换。

真实 GitHub 凭据映射尚未配置，当前仅完成实现，未进行统一测试或真实服务联调。


## 普通任务恢复入口（实现待验收）

个人历史详情新增普通恢复按钮；后端返回 can_resume/pending_approval，只允许本人同工作区最新未完成记录，角色/GitHub 身份/resource_scopes 必须与当前会话一致。恢复指令携带 expected_checkpoint_id，MCP 在同任务进程锁内重验，不接受缺少预览版本的恢复。历史 checkpoint 保持只读，待审批任务不能用普通恢复跳过 Gate。

认证任务的 run/stream/普通恢复/Gate 恢复始终写入 JSONL 时间线，不依赖 attach_stream。每次执行有唯一 event_id 和时间戳，写入加锁并 fsync，失败停止后续执行；恢复遇到半行会保留并隔开损坏记录。历史详情按 100 条读取事件，支持继续加载，并提示损坏行或旧任务缺少事件文件；时间线覆盖整个任务，不伪装成所选 checkpoint 的当时快照。Admin 读取事件也要求审计。按钮表示请求提交，不表示执行完成。

方案回源不再沿用缓存；内容摘要不符、已删除、读取异常或 superseded 都限制写操作，仅保留只读与方案工具。新任务还把实际加载的 Skill 内容摘要、名称及元 Skill 组合保存在检查点；每次模型调用、工具执行和恢复前重新读取并核验治理状态与摘要。撤销、过期或内容变化后停止继续使用旧工作流。旧检查点没有绑定时，对已认证任务从保存的标准工作流头识别 Skill 和元 Skill，仅当完整来源文本与当前有效版本一致时放行；无来源或不一致则保留只读回放并明确显示恢复限制，不补写历史摘要。此兼容路径已补入，尚待统一恢复验收。真实中断恢复、磁盘失败和全部新增路径尚未统一测试。


## 持久审批队列（实现待验收）

新增 list_pending_gates 和 HumanGate 页同组审核队列，从最新 checkpoint 的持久 interrupt 写入读取 Gate，不依赖浏览器缓存。仅 approver/admin 访问并记录审计；不开放其他人员完整历史。按 checkpoint/thread 游标分页，界面可继续加载，无需先处理前 100 项。

审批绑定 expected_gate_id 和 expected_checkpoint_id；任务锁内拒绝已变化的审批。跨人员处理还须由 gateway 重验创建者原会话未过期/撤销，且当前 roster 与检查点权限一致；旧的受信 SSH 宿主要求本地正式 roster 有一致创建者授权。无从验证时拒绝恢复。界面提示仅表示请求发出，执行结果仍由任务反馈。新增路径尚未统一验收。

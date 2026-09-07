# QuantCode 产品与工程复核 · 2026-09-05

本报告依据 FUNCTIONAL_SPEC v0.5.1、PRD v5.1、QuantCode_Design v5.1，以 UI_DESIGN_SPEC v4.1 补充界面验收。用户提供的 [HKUST 组件统计](../references/HKUST_QUANT_COMPONENTS_GUIDE.md) 是复用边界的补充资料，不覆盖三份顶层设计，也不视为 GitHub 实时状态证明。

## 当前目标与验收顺序

本文件是当前状态台账，后续实现直接更新本表，不以追加旧批次结论代替状态维护。

本阶段目标为本地 Dev 可初步使用。用户明确暂不验收 Mac/Windows 安装包，且要求先完成全部功能修复，再统一 pytest，最后 Headless UI 验收。本地功能增量已进入统一验收：后端全量 pytest → 前端类型/组件 → Headless UI 按顺序执行。当前自动回归通过，但真实身份、MCP 与外部服务闭环尚未通过。

产品源码统一在 `quantcode` 仓库：Python 后端在根目录，UI/桌面/宿主工作区在 `frontend/`。此前双仓库测试证据保留其执行范围；迁移检查独立记录如下。后续代码统一在 quantcode/main 交付，真实服务接通仍须单独验收。未修改用户的 `AI_Agent_Group_未来发展思考.md`。

状态定义：**已有本地证据**表示之前的实现有相应测试；**实现待验收**表示代码已补入但尚未统一检查；**部分**表示仍有功能缺口；**待接入**表示真实外部系统未完成联调。任何一类都不能直接等同于产品全量验收通过。

## 单仓库验收

当前产品源码统一位于 QuantCode 仓库：Python 后端在根目录，完整前端工作区在 `frontend/`，位置与命令见 [仓库布局](../REPOSITORY_LAYOUT.md)。本次不重启已存在的 `4096/4444` 进程。

| 检查 | 当前结果 |
|---|---|
| 独立依赖安装 | `bun run install:frontend` 冻结锁文件安装成功；未复用旧仓库 node_modules |
| Python 全量回归 | 1,142 passed / 4 skipped；真实 LLM 跳过 |
| QuantCode 组件 | 126 passed / 0 failed |
| app / opencode / desktop 类型 | 三个包均通过 |
| 网页构建 | 从根目录 `bun run build:web` 成功，QuantCode 品牌 |
| 构建产物 Headless | 12 passed，12.4 秒；静态预览 127.0.0.1:48173 指向本仓库 frontend/packages/app/dist，测试通过保存的服务设置连接现有 4096；业务/身份响应为 fixture，不证明真实接线 |
| 打包路径 | 根 workflow 与 composite action YAML、工作目录和本地 action 引用检查通过；仅手动触发，默认不发布；本机已构建 macOS arm64 unsigned DMG/ZIP；本机 Linux RPM 尝试因缺少 `rpmbuild` 停止，正式 Linux x64 矩阵由 Ubuntu CI 构建 |

构建产物测试未执行依赖 Vite 源码模块的 2 项审批/恢复挂载测试；这两项由当前组件测试覆盖，不混算成静态产物的 12 项。静态预览必须通过 `PLAYWRIGHT_TARGET_SERVER` 指向后端，避免把服务选择页误判为产品回归失败。

2026-09-05 在单仓库 `main@f0ec06f` 复核：Python 3.12 全量回归 **1,142 passed / 4 skipped**，Ruff **0 errors**，QuantCode 组件 **126 passed / 0 failed**，app/opencode/desktop 三包类型检查通过，生产构建成功。当前仓库构建产物的独立静态预览 Headless **12 passed**；当前仓库 Dev 使用可配置端口 `4196/4544` 启动，Headless **16 passed**。真实宿主 `/experimental/quantcode/identities` 对未配置身份返回结构化 error，`session_context` 对未连接 MCP 返回明确 error，不伪装成功。统一脚本现已覆盖后端、Ruff、组件、三包类型、网页构建和 Dev Headless。未配置 provider 或正式身份时依旧保持 `UNAVAILABLE`/fail-closed。
与用户反馈的 `/agent` 500 对照验证：截图基线中的旧工作区 `4096` 曾对该请求返回 500；本次复核对有效目录已返回 JSON Agent 列表，但该进程仍来自 `opencode-lens`，不作为当前仓库证据。当前 `4544` 页面仍显示并连接 `127.0.0.1:4096`，因为它是在端口修复前启动的旧 Vite 进程；已修复 Dev 启动器传递 `VITE_OPENCODE_SERVER_PORT` 并在 QuantCode Dev 忽略过期的持久后端地址。Roster 激活只影响 `/experimental/quantcode/*` 身份/MCP 路由，不是 `/agent` 500 的根因。

## 迁移前统一验收证据

2026-09-05 在原先两个工作区执行：

| 检查 | 结果 | 证明范围 |
|---|---|---|
| 后端全量 pytest | **1,142 passed / 4 skipped** | 当前后端回归；新增真实隔离 SSH agent 签名、challenge 重放拒绝、凭据哈希持久化、退出/过期与权限变更撤销；回执重放、崩溃拒绝重试、身份变更、摘要完整性、人工核对及目录即时回源；知识发布跨进程单写、进程强杀恢复和跨人 checkpoint 创建者撤销重验。4 项真实 LLM 测试跳过，不算通过 |
| 前端与宿主类型检查 | 两个包 `bun typecheck` 均通过 | app 与 opencode 类型一致性 |
| QuantCode 组件测试 | **126 passed / 0 failed** | 当前 16 个组件测试文件；管理入口从占位改为实际任务/报告导航 |
| 本地 Dev Headless UI | **16 passed** | 当前复核使用独立 `localhost:4544`→`4196`；身份/角色展示、Memory、两种尺寸、历史分页与未知回执阻止恢复、目录刷新、GitGraph 分页和通知确认、Admin 部署暂存/取消、知识候选审核。其中 2 项直接挂载当前 Vite 编译的审批/恢复组件，验证提交失败可重试、受理后禁用及旧错误清除；其余 14 项为完整工作区流程。MCP 响应采用明确 fixture，不证明真实 SSH/服务权限 |
| 旧工作区 localhost:4096 | **不作为当前仓库证据** | 截图基线中的请求曾返回 500；本次对有效目录复核返回 JSON，但该进程仍来自 `opencode-lens`，`/experimental/quantcode/*` 也不是当前单仓库的宿主路由。
| 当前单仓库 localhost:4196 | **通过本地接线** | `/agent?directory=...` 返回 JSON Agent 列表；未配置身份时 `/experimental/quantcode/identities` 返回结构化 error，`session_context` 返回明确未连接错误。

本轮发现并修复：候选错误分类与测试发布路径隔离；旧测试对身份切换/方案缺失/分页响应的错误前提；工具完成回执新增结果摘要，内容或类型损坏、旧回执无摘要时拒绝自动恢复。跨组回执核对被拒绝，审核保存不启动任务。Headless 的面板入场动画导致跨帧坐标测量不稳定，改为同帧测量，未降低内边距断言。

**台账尚未全通过。** 正式 roster 已激活 37 条组员绑定和 1 条本机 Lead/Admin 运维身份；指纹-only、共用公钥和未确认身份仍拒绝登录。当前本机 gateway、身份 session、GitHub token 映射和 Dream consumer 已配置，生产部署服务、组件 API 和跨机器进程托管仍待外部环境。量化组件当前按“成员本地 checkout + Agent 预学习”运行，真实 API 等组件上线后再接入。当前仓库宿主已可通过独立端口加载，旧工作区的 `4096/4444` 不用于新仓库验收。前端 `frontend/packages/app/AGENTS.md` 明令禁止代理重启应用/服务器，本轮未重启用户已存在的服务。以下逐项“待验收”还包括自动回归未覆盖的真实服务、长任务与跨进程故障场景，不因汇总数字通过而自动销项。

## 逐项功能台账

| 基线 | 当前证据与当前处理 | 尚未做到 / 验收边界 |
|---|---|---|
| F-01 任务与组路由 | `quantcode/mcp_server.py`、identity、effective catalog；八组 stdio 启动/发现/拒绝非法工具回归。UI 使用服务端组与 Skill；未认证不显示默认 factor；切服务清除旧会话引用 | 部分、待接入：本机公钥选择、SSH agent 签名、gateway 会话和 MCP 重连已接线，真实闭环未验收；浏览器角色测试使用明确 fixture |
| F-02 执行记录与恢复 | 服务端分页历史、checkpoint 消息/产物回放、普通恢复协议与 MCP 单任务进程锁；认证任务默认持久事件，恢复权限重验 | 本地验收通过：事件分页、损坏提示、身份权限变更拒绝和未知回执恢复均有回归；跨机器和真实长任务副作用恢复仍待真服务验证 |
| F-03 HumanGate | permission/merge 白名单、拒绝路径、审批 evidence；同组持久队列支持游标分页，提交绑定 Gate/checkpoint；跨人审批重验创建者身份 | 本地验收通过：长队列、创建者撤销/过期、失败重试和跨人证据路径已覆盖；真实 interrupt→审批→resume 仍待 gateway/MCP 验证。风险/预算/CI 不扩充 Gate |
| F-04 Memory/能力目录 | `runner/memory`、`runner/distill`；修复 LIMIT 前排除 Runtime State、坏索引报错、搜索竞态与输入失焦；Admin 跨组/项目读取留痕；卡片补输入输出依赖与别名 | 本地验收通过：项目 roster scope、可撤销/过期 ACL、候选评审和卡片刷新均有回归；外部组件状态同步仍需真服务 |
| F-05 SSH | challenge/roster/session 后端及单测存在；UI 区分 HTTP 服务连通和身份认证，移除默认供应商“已配置”假象 | 待接入：本地 agent/keychain 签名、真实 SSH gateway、主机/密钥/roster 各失败状态的桌面闭环未完成 |
| F-06 组件适配 | `tools/factor`、FactorPanel、QuantEvaluator adapter 与状态契约；12 个主链组件已登记；移除 PIT 前端私算估值 | 部分、待接入：目录存在不代表组件已接通；DataAccess→FE→QE 等真实输入/输出/版本/artifact 尚需服务验收；不自建替代组件 |
| F-07 跨组协同 | Blackboard、Model→Risk CI、事务/去重及 handoff 测试存在；领域 verdict 不创建 Gate | 已有本地证据；真实 GitHub Actions/报告平台交付链未验收，维持 CI 基建定位 |
| F-08 领域工具 | 六组 flows 和 strategy/options/fundamental/portfolio 回归存在 | 部分、待接入：stub/proxy/本地引擎不能冒充 canonical；保留组内适配，不增加统一业务产品 |
| F-09 Admin/GitGraph/Pop | 明细/身份/快照适配；可见分支与 HEAD、近期提交 DAG、凭据映射、个人 Pop read/ack、含子目录的依赖版本解析及 Dev 每分钟同步已补入；管理页组织任务/报告查询 | 本地验收通过：GitGraph 分页、Pop read/ack、通知持久化和错误状态均已覆盖；真实 GitHub 凭据、gateway 后台调度和本机系统通知仍需部署验证；现有图按 F-09 显示全部授权分支及近期提交窗口 |
| P-01 数据契约 | `schemas/data_contracts.py`、market/factor tests，缺源必须 no_source/UNAVAILABLE | STAGING：真实 ReturnsDataset/DataAccess 来源、PIT/交易日/label 版本一致性需真数据验收 |
| P-02 回测 | strategy adapter、backtest 回归；不扩充统一回测 UI | STAGING：VectorBT-QS fast/accurate 真组件回放及 A 股约束由组件证明 |
| P-03 组合 | portfolio adapter/verdict 测试、移除人审旧语义 | STAGING：Riskfolio-QS 的 alpha/risk/benchmark/previous_positions 到 target_positions/trades 闭环未验收 |
| P-04 Subagent | `tools/subagent`、parallel registry、预算/身份继承和 kill 回归 | 已有本地证据；真实跨进程、长时间并发负载未压测 |
| P-05 实验 | `tools/experiments`、OOS/ledger/artifact 测试 | 已有本地证据；外部实验平台消费与真实数据实验不在当前证据内 |
| P-06 Evidence | 哈希链与关键写入 fail-closed；已补 Admin 敏感读取审计、permission 决策结构、实际审批人和原 Gate 关联 | 已有本地证据；外部审计消费/长期归档需运营验证 |
| P-07 蒸馏与复用 | 候选生成/晋升/拒绝/supersede、strict reuse；摘要包含 maturity/integration 和“不重复造轮子”；提供组件交叉表 | 部分：定时消费入口不等于生产 timer 已启用；定期实读 GitHub、人工确认冲突、状态刷新未闭环 |
| P-08 Admin 中枢 | 全组运行/错误/Blackboard 查询与角色检查；新增敏感读取审计；UI 明细和错误状态已修复 | 本地验收通过：组织任务/报告查询、跨组读取审计、持久审批队列和异常调用人工核对已覆盖；角色隔离和真实 GitHub/gateway 后台仍待部署验证 |
| P-09 Admin Deploy | `runner/admin_operations.py` 黑盒 STAGING + required evidence；八组 MCP 不注册 deploy | 本地验收通过：部署记录、幂等暂存/取消、Admin 管理界面和错误状态已覆盖；生产执行队列、回滚协议与服务账号仍未接通；不会伪造生产成功 |
| P-10 Solution-First | 分级/工作流/一致性判定；执行前回源方案并核验摘要，废弃、缺失、读取失败均限制写操作，移除跨进程失效缓存 | 本地验收通过：方案失效、恢复、摘要不一致和写限制均有回归；真实 L2/L3 冻结、执行、偏离检测仍需在真宿主与长任务中验证 |

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
| D-010 私钥留本地 | 当前 UI 无私钥输入/上传；临时 OpenSSH agent 真实签名已验，正式 keychain/人员接入未验 |
| D-011 完整图与提醒 | 全部授权仓库/分支/HEAD、近期提交关系、依赖差异、个人提醒的本地契约验收通过；真实 GitHub 同步与系统通知仍按 F-09 部署验证。按 F-09 定义保留近期提交，不把无限历史加载增加为验收条件 |
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
| U4 执行记录 | 新增服务端历史与 checkpoint 只读回放界面；原有当前运行面板保留 | 本地 Headless 验收通过：刷新、隔离、错误状态、产物与未确认回执阻止恢复均有回归；真实长任务恢复仍需真服务 |
| U5 Memory/能力 | 输入焦点、竞态、503、组 ACL、真实 SQLite、卡片元数据；两种尺寸滚动 | 本地验收通过：项目 grant、知识审核、发布中恢复和能力目录刷新均有回归；真实组件接通状态仍需服务验收 |
| U6 Gate | 白名单、批准/拒绝证据、审批者 | 真浏览器跨角色审批待验 |
| U7 Admin/GitGraph/Pop | 授权 GitGraph 分支/HEAD 和近期提交、持久 Pop read/ack、组织历史入口已补入 | 本地 Headless 验收通过：GitGraph 分页、Pop 确认和角色展示均已覆盖；gateway 后台同步、系统通知与真实 GitHub 仍需部署验证 |
| U8 部署 | 普通 MCP 不存在 deploy；Admin 暂存、查询、取消与本地持久服务已补入 | 本地组件与记录验收通过；生产执行、状态回传与回滚仍未接入 |
| U9 外部结果 | HTTP/坏载荷显式失败；PIT 原样展示有来源的结果、缺失为 —、零值保留 | 其他领域结果的生产格式仍需各组件提供样本联调 |

视觉参照是现有对话主页的黑白、细线、克制文字层级。详情页统一纸面底色、内边距、小标题和滚动容器；短桌面保留设置入口；长列表滚动时关闭按钮保持可见。没有把主页面改成仪表盘。本次在默认视口、900×650 和 1440×900 下实测检查截图；浏览器 E2E 报告保存在 `frontend/packages/app/e2e/quantcode-report/`。

## 全量验收尚未关闭的事项

1. F-01/F-05：真实 SSH agent/keychain、gateway、roster 与桌面接通。八组已实现；人员表 46 条提交、39 个身份标识，37 条组员绑定和 1 条本机 Lead/Admin 运维身份已激活；指纹-only、共用公钥和未确认项仍待处理。角色和真实工作目录不能根据姓名推断。
2. F-02/F-03/P-10：普通恢复预览绑定、审批队列分页、持久事件与方案失效限制已补入，本地验收通过；已补认证 Agent 写工具的持久回执、未确认回执阻止恢复、跨人核对和失败重试。真实 gateway/MCP 会话、长任务副作用和桌面恢复仍需部署验证。
3. F-04/P-07：项目 grant 解析、过期/撤销校验和候选预览/晋升/拒绝/替代界面已补入，本地验收通过；发布中恢复、撤销、来源摘要、过期加载校验和即时回源均有回归。外部组件状态仍不能通过本地刷新伪造。
4. F-06/F-08/P-01～03：按组件复用表接通真实输入输出、版本和 artifact。真数据/组件缺失必须明确报告，不能由前端编造结果。
5. F-09/P-08/P-09：组织历史、个人 Pop read/ack、实时仓库权限重验、Dev 每分钟同步、可见分支/HEAD/近期 DAG、含子目录的依赖版本及 Admin 暂存/取消已补入，待验收。本机系统提醒已接入待验收；通知长列表分页与全量授权未读计数已补入；gateway 后台循环与状态查询已补入；静态组引用和 requirements 本仓库引用已补入；动态依赖仅可追踪声明，不执行构建代码；生产部署执行需要真实服务契约。
6. F-07/P-04～06：补齐真实交付、长时间并发与外部平台消费所需接线；保留权限和 evidence 约束。

## 统一验收执行与后续边界

前三项自动检查已执行，具体证据见上表；仍未证明真实服务闭环：

1. 后端 pytest 全量与 Ruff；覆盖新增历史分页与权限、普通恢复、进程竞争、通知持久化、项目授权与适配器失败路径；当前 `uv run ruff check .` 通过。
2. 前端类型/组件与接口生成一致性检查；任何失败返回实现阶段修复。
3. 本地 Dev 的 Headless UI：登录、任务/方案、历史回放、跨角色 Gate、Memory/能力、管理/GitGraph/通知、部署入口和错误状态。
4. 已接入服务的真实端到端、长任务中断与恢复，记录来源、账号范围和产物。尚无外部配置的项目保持未通过，不能用 fixture 证明已接通。

2026-09-06 已按用户要求补做 UI 与安装包复核；本机 macOS arm64 unsigned DMG/ZIP 可生成并通过产物结构检查，但正式签名、公证、Windows/Linux 跨平台包和安装后真实 QuantCode MCP 连接仍需外部环境。

当前测试结果统一以本文件“本轮统一验收证据”表为准。F01_ROSTER_ACCEPTANCE、EIGHT_GROUPS_GITHUB、F02_RECOVERY_STREAM 保留各自实施记录，不作为本轮新增路径已经验收的证明。


## 当前 GitHub 实现边界

`runner/github_sync.py` 读取授权 repo 全部分支、HEAD，以及每分支最近 30 条提交；窗口外的父节点明确标注。完整成功的仓库快照才更新 SQLite 基线，同一事务插入去重 Pop。首次观测不生成更新提醒。

依赖跟踪读取默认分支固定 HEAD 对应的完整 Git tree，覆盖根目录和子目录清单，不跟随符号链接或子模块。递归响应被截断时逐层获取子树；不完整响应不更新基线。旧根目录基线升级到递归范围时重新建立比较基线，避免把已有子目录误报为新增。

除 Git blob 差异外，已补 package.json、package-lock v1/v2/v3、Bun 文本锁 v1、uv.lock、poetry.lock、pyproject.toml 和简单 requirements 的解析与包级 Pop。声明与锁定版本分开标记，保留依赖分组、安装位置及同包多版本。未变化 blob 按解析器版本复用缓存；旧的无解析基线不会被当作全量新增。解析失败保留上次完整基线；dependency-groups 支持规范化名称和 include-group，拒绝循环、缺失或重复规范名；requirements 支持本仓库 -r/-c、续行和 hash 参数，引用读取固定 HEAD 的同一 Git tree，约束与依赖分别展示。引用文件变化会重新解析，不沿用父清单的单文件缓存；缺失或越界引用拒绝更新基线。动态 Python 依赖、远程 include、环境替换和安装选项未执行，明确展示为仅文件跟踪。不宣称服务器已安装或升级依赖。已完成统一回归；各锁文件格式、截断树与真实 GitHub 同步的专项覆盖仍需补齐。

Dev 工作台存活且身份就绪时每分钟同步。GitGraph 可开启/关闭本机系统提醒，浏览器权限由用户点击开启时申请；复用平台通知接口，单次只发送新更新条数汇总。偏好和已发现 ID 按身份/工作区保存在本机，首次加载不补发旧通知，发送失败保留持久列表并提示。通知列表按时间和 ID 游标分页，ACL 过滤先于分页；角标使用后端授权范围内完整未读总数，已读/确认操作也返回该总数。加载历史页不会发送系统提醒，刷新与状态写入互斥。浏览器 fixture 已验证图分页与通知确认保存；完整后台同步和系统通知送达仍待验证。gateway 已补独立后台循环，每轮重新验证有效会话、roster 和 GitHub 权限，按身份工作区去重；最近尝试状态持久化并可经认证接口读取。较旧并发响应不得覆盖更新基线；缓存按完整身份、角色、工作区和资源权限隔离。默认分支元数据变化触发刷新，非空分支列表缺少默认分支时拒绝更新依赖基线。服务实际部署及真实同步尚未验收，后台运行不延长会话，也不在客户端关闭时发送系统通知。旧 trace 派生的 repo/package 临时提醒已从主页面消费路径移除，Gate 通知保留独立语义。


## 项目 Memory 与知识审核接线

项目检索要求 roster `resource_scopes` 包含 `memory:project:<project_id>:read`，且 `configs/project_grants.yaml` 存在匹配 actor 的 enabled 条目和未来的带时区 expires_at。配置每次查询读取，过期/撤销立即影响后续检索；当前 grants 为空，不代表已有项目授权。Admin 组织读取继续 required audit。

候选队列新增服务端正文与 SHA256 预览、前端审核操作。晋升请求携带预览摘要，拒绝修改后的草稿和覆盖已有 Skill；审核写入使用跨进程锁，发布前保存审核意图。发布已改为 intent → publishing → 原子安装 → 审计决策 → promoted；加载器仅接纳已提交且摘要匹配的发布，中断后可重试同一候选或撤销。安装、决策审计、索引激活失败恢复、跨进程单写和进程强杀恢复均通过专项测试；真实浏览器候选审核仍需带身份的 gateway/MCP 环境。


## 知识发布一致性（本地验收通过）

受治理 Skill 带 `.governance.json` 指向候选权威索引。Skill 文件安装采用临时文件 fsync 后非覆盖原子 link；审核意图及发布中状态先持久化，最终决策审计先于索引激活。加载器检查 promoted、发布路径/摘要、草稿摘要及可选 expires_at；撤销和已发布替代通过索引停用，保留文件证据。MCP Skill 目录也应用同一校验，返回不可用项目及原因。用户可在候选界面恢复未完成发布或撤销发布。旧的无摘要治理发布不会被自动补签批准。安装失败、决策审计失败、激活写入失败均验证保持 publishing 且不可加载，恢复同一候选后可发布；撤销、源文件/已发布正文变更、过期或无时区到期值会在下次读取被拒绝。跨进程单写和进程强杀恢复已通过专项验证。


## 身份 Gateway（隔离签名链路已验，正式接入未验）

新增 `quantcode.gateway` 本地 HTTP 服务：challenge/verify/session/logout，签名仍由既有 OpenSSH verifier 验证，token 仅存哈希，会话每次查询重验正式 roster。旧 SSH 指纹接入也已补缓存上下文的逐次 roster 核验，指纹、角色、工作区或资源权限变化均要求重连，撤销后不得继续沿用缓存授权。新增 `quantcode.identity_login` 宿主 CLI，使用 `ssh-keygen -Y sign -U` 要求 SSH agent 签名，仅读公钥；会话凭据以 0600 文件保存，不打印 token。

MCP 可配置 `QUANTCODE_IDENTITY_SESSION_FILE` 使用 gateway 身份，每次调用重新验证会话，拒绝到期/撤销或上下文变化，不回退指纹猜测。隔离临时 roster/数据库与真实 SSH agent 的 7 项测试已通过，未启动正式 gateway 或激活人员授权；桌面登录按钮已接宿主固定 CLI，MCP 重连后核对同一 session_id，待真实 gateway/roster 验证。已向用户询问真实 gateway/roster/部署服务配置，凭据不通过聊天接收。


## Admin 部署管理接线（本地验收通过，生产待接）

新增持久 SQLite 部署台账：按 actor/request_id 幂等暂存，相同 key 不同内容拒绝；查询与取消暂存请求要求 Admin 和 required evidence。Gateway 暴露专用管理接口；OpenCode 管理路由先校验当前 MCP Admin，再要求本机 gateway 凭据的 session_id 与其一致。部署不注册到 MCP 工具目录，浏览器只提交产物引用/目标/版本，不接触 bearer token。

界面有暂存、查看和取消入口。生产执行器尚未配置，因此结果仅为 STAGING 或 CANCELLED，不能宣称生产部署功能完成。真实执行队列/状态回传/回滚契约仍等待外部配置。统一回归已执行；部署管理的浏览器暂存/取消专项及真实生产执行仍未验收。


## 本地登录界面接线（本地组件通过，真身份待接）

OpenCode 新增宿主身份查询和固定登录操作；仅接受宿主配置的 Python/后端目录/公钥/gateway/会话路径，浏览器无任意命令或 URL 输入。设置页使用这些身份，登录成功后重连 QuantCode MCP，核验 gateway 与 MCP 的 session_id 一致再刷新工作区。并发签名请求共用在途操作，有超时边界，不打印签名或 token；HTTP 登录入口另对签名、MCP 重连、会话核对整个流程进行互斥准入。身份查询的配置、连接和载荷错误在设置页明确显示，不再吞掉错误后展示空列表；宿主验证公钥 base64 格式。类型检查与未认证界面测试已通过；完整宿主登录/MCP 重连尚未实测。配置步骤见 [LOCAL_IDENTITY_GATEWAY.md](../LOCAL_IDENTITY_GATEWAY.md)。当前未启动正式 gateway、未签入真实人员；隔离签名与 gateway 会话测试已通过。


## GitHub 身份凭据接线（本地契约通过，真凭据待接）

新增宿主 `QUANTCODE_GITHUB_CREDENTIALS_FILE`：按已认证 github_subject 映射私有 token 文件，要求绝对路径、服务账号所有和 0600；每次读取重验权限，不在 SessionContext/trace 保存 token。GitGraph/Pop 沿用 /user 与 Team/repo 范围检查；已认证 PR 读取也采用同一范围，普通角色不继承中心 GITHUB_TOKEN。Admin 环境降级仅留给无角色的可信旧宿主调用，不能覆盖已有 Session Context 的 analyst/approver 角色。PR 文件查询补分页，已知未完整返回时拒绝把部分差异当完整评估。MCP 调用保留 gateway 签发的 session_id，不再用进程 ID 替换。

真实 GitHub 凭据映射尚未配置，当前仅完成实现，未进行统一测试或真实服务联调。


## 普通任务恢复入口（本地验收通过，真长任务待验）

个人历史详情新增普通恢复按钮；后端返回 can_resume/pending_approval，只允许本人同工作区最新未完成记录，角色/GitHub 身份/resource_scopes 必须与当前会话一致。恢复指令携带 expected_checkpoint_id，MCP 在同任务进程锁内重验，不接受缺少预览版本的恢复。历史 checkpoint 保持只读，待审批任务不能用普通恢复跳过 Gate。

认证任务的 run/stream/普通恢复/Gate 恢复始终写入 JSONL 时间线，不依赖 attach_stream。每次执行有唯一 event_id 和时间戳，写入加锁并 fsync，失败停止后续执行；恢复遇到半行会保留并隔开损坏记录。历史详情按 100 条读取事件，支持继续加载，并提示损坏行或旧任务缺少事件文件；时间线覆盖整个任务，不伪装成所选 checkpoint 的当时快照。Admin 读取事件也要求审计。按钮表示请求提交，不表示执行完成。

方案回源不再沿用缓存；内容摘要不符、已删除、读取异常或 superseded 都限制写操作，仅保留只读与方案工具。新任务还把实际加载的 Skill 内容摘要、名称及元 Skill 组合保存在检查点；每次模型调用、工具执行和恢复前重新读取并核验治理状态与摘要。撤销、过期或内容变化后停止继续使用旧工作流。旧检查点没有绑定时，对已认证任务从保存的标准工作流头识别 Skill 和元 Skill，仅当完整来源文本与当前有效版本一致时放行；无来源或不一致则保留只读回放并明确显示恢复限制，不补写历史摘要。此兼容路径已补入，尚待统一恢复验收。统一回归已执行；真实长任务恢复、磁盘失败和旧检查点兼容的专项证据仍不完整。


## 持久审批队列（本地验收通过，真跨人会话待验）

新增 list_pending_gates 和 HumanGate 页同组审核队列，从最新 checkpoint 的持久 interrupt 写入读取 Gate，不依赖浏览器缓存。仅 approver/admin 访问并记录审计；不开放其他人员完整历史。按 checkpoint/thread 游标分页，界面可继续加载，无需先处理前 100 项。

审批绑定 expected_gate_id 和 expected_checkpoint_id；任务锁内拒绝已变化的审批。跨人员处理还须由 gateway 重验创建者原会话未过期/撤销，且当前 roster 与检查点权限一致；旧的受信 SSH 宿主要求本地正式 roster 有一致创建者授权。无从验证时拒绝恢复。审批/恢复界面等待提交回调返回受理结果；失败或忙碌时显示错误并可重试，受理后才禁用按钮，重试时清除旧错误。浏览器已验证失败→重试受理两条路径；gateway 后端已验证同组 approver 可处理且创建者会话撤销后立即拒绝。真实 gateway/MCP 跨人浏览器会话仍需部署验证。

## 2026-09-06 UI 与安装包复核

本次复核使用当前 QuantCode 工作区的独立 Dev 端口 `4196/4544`，没有重启用户已有的旧 `4096/4444` 服务。

| 范围 | 结果 | 说明 |
|---|---|---|
| QuantCode 浏览器 UI | **16 passed** | 首页、身份未配置、执行记录、因子评估、PIT、HumanGate、Memory、能力目录、方案、GitGraph/Pop、审批/恢复错误态、Admin 部署暂存/取消、知识候选审核、两种视口和 `infra/agent` 组展示；当前身份未配置时均按 fail-closed 空态呈现 |
| OpenCode 原生 UI | **22 passed** | 在 `OPENCODE_CHANNEL=dev` 独立 Vite 页面运行 regression/smoke；包含多服务器 tab、timeline、请求 dock、diff/comment、todo 和终端隐藏场景 |
| 前端性能单元 | **15 passed** | 导航、timeline、repaint 和 stream probe 单元检查通过；未把机器相关 benchmark 数字当作发布门槛 |
| QuantCode 组件 | **126 passed / 0 failed** | 16 个 QuantCode 组件测试文件 |
| Electron 桌面测试 | **101 passed / 0 failed** | updater、release workflow、renderer、sidecar、WSL、附件和深链测试；修复中文路径下 release workflow 测试使用 URL 编码路径的问题 |
| 网页生产构建 | **通过** | `bun run build:web`，仅有 Vite chunk/sourcemap 警告 |
| Electron 生产构建 | **通过** | `bun run build:desktop`，主进程、preload、renderer、updater bundle assertion 均通过 |
| 本机 macOS 安装包 | **通过（unsigned QA）** | `quantcode-1.17.11-mac-arm64.dmg` 与 `.zip` 已生成，并检查 `Info.plist`、QuantCode app id、`quantcode` URL scheme、app.asar 和 SHA-256；本机无 Developer ID，产物为 ad-hoc/unsigned，不能直接外发 |
| 本机 Linux arm64 交叉打包 | **部分通过** | 生成 `quantcode-1.17.11-linux-arm64.AppImage` 与 `.deb`；macOS 无法运行 Linux 包，RPM 因缺少 `rpmbuild` 未生成，因此 Linux 运行/完整安装矩阵仍须 Ubuntu CI 证明 |
| 统一验收脚本 | **通过** | `scripts/verify_product_audit.sh`：1,142 Python、Ruff、126 组件、三包类型、网页构建和 16 项 QuantCode E2E 全部通过；新增 `bun run check:deployment` 会在正式 roster/gateway 缺失时 fail-closed |
| 隔离身份/MCP 联调 | **通过（临时环境）** | 临时 Ed25519 key、roster、回环 gateway 和 SSH agent 完成 challenge/signature/login；页面显示 `fixture-analyst / factor / analyst`，`session_context` 返回 `identity_source=ssh_roster`；未读取或修改正式密钥/roster |
| 正式部署门禁 | **按预期失败；隔离 PASS 已验证** | 当前环境执行 `bun run check:deployment` 会因正式 roster 和五项身份变量缺失而拒绝宣称可部署；使用临时 owner-only roster、临时 SSH session、回环 gateway 和现有安装包运行同一脚本返回 `Deployment readiness: PASS` |

本次完整前端套件的 38 项测试必须按 channel 分组运行：QuantCode 页面运行 16 项，原生 OpenCode regression/smoke 运行 22 项。把原生测试直接指向 QuantCode channel 会出现 `Notification server not found` 或缺少原生导航，这是测试环境错配，不是产品回归。

当前仍未实现或未能在本机完成验收的功能：

1. **真实身份链路**：正式 `.opencode/authorized_groups.yaml`、SSH agent/Keychain、公钥 roster、gateway、MCP 重连和真实跨人审批尚未接入。
2. **真实量化组件**：ReturnsDataset/DataAccess、QuantEvaluator、VectorBT-QS、Riskfolio-QS 及其他 canonical 服务的真实输入输出、版本、artifact 和权限闭环仍为 `STAGING`/`UNAVAILABLE`。
3. **生产治理**：Admin deploy 仍只做持久化暂存/取消，生产队列、服务账号、状态回传和回滚协议未接入。
4. **GitHub 与通知运营**：真实 GitHub subject/token、后台同步、系统通知送达和外部报告平台消费未验收。
5. **安装包正式发行**：本机只验证 macOS arm64 unsigned 包；Windows x64、macOS Intel、Linux x64 需 CI 构建和 packaged smoke，正式外发还需要 Apple Developer ID/公证、Azure Trusted Signing、发布环境审批。安装包不会内置 Python QuantCode MCP、成员私钥或 GitHub token，安装后的研究链路必须连接已部署的 Server B/gateway。

因此当前结论是：**代码、网页和桌面壳已达到“可构建、可做 unsigned QA”的程度；尚未达到“配置齐全、签名完成、外部服务接通后可直接正式部署”的程度。**

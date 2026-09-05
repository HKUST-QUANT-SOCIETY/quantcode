# QuantCode 产品与工程复核 · 2026-09-05

本报告依据 FUNCTIONAL_SPEC v0.5.1、PRD v5.1、QuantCode_Design v5.1，以 UI_DESIGN_SPEC v4.1 补充界面验收。用户提供的 [HKUST 组件统计](../references/HKUST_QUANT_COMPONENTS_GUIDE.md) 是复用边界的补充资料，不覆盖三份顶层设计，也不视为 GitHub 实时状态证明。

## 判断与证据范围

已有运行时、权限、契约和六组测试基础，不能用文件数量或测试通过率证明“80% 产品完成”。主要差距集中在跨前后端契约、真实身份/组件接入和完整桌面工作流。本轮修复的是有代码与失败场景支持的问题；没有推倒重写已通过验证的运行时。

涉及两个独立 Git 仓库：

- 后端：`QUANTcode`，审查起点 `7fa768f`（2026-09-05 09:27:35）。
- 桌面前端：`opencode-lens`，审查起点 `2e3d51cb1`（2026-09-05 07:34:09）；改动位于 `packages/app`。
- 原有未跟踪文件 `AI_Agent_Group_未来发展思考.md` 未修改。本轮未提交、合并或部署。
- 上一轮提交确实保存在 Git 中。没有取得能证明意外退出原因的崩溃日志，不能断言是模型、桌面应用、进程还是系统故障。现有 checkpoint 测试通过也不等于昨天的实际任务已经恢复。

状态定义：**本地通过**表示实现及相应本地测试可证明；**部分**表示存在本地功能缺口；**待接入**表示真实外部系统尚未端到端验收。表内“代码证据”是定位入口，不是声明全部路径均已做生产验证。

## 逐项功能台账

| 基线 | 当前证据与本轮处理 | 尚未做到 / 验收边界 |
|---|---|---|
| F-01 任务与组路由 | `quantcode/mcp_server.py`、identity、effective catalog；六组 stdio 启动/发现/拒绝非法工具回归。UI 使用服务端组与 Skill；未认证不显示默认 factor；切服务清除旧会话引用 | 部分、待接入：真实 SSH 身份签发到桌面提交的闭环未验收；浏览器角色测试使用明确 fixture |
| F-02 执行记录与恢复 | `runner/agent_engine.py`、checkpoint/replay/trace 测试；缓存分区增加 server/actor/group/workspace；恢复携带当前审批者与原 gate_id | 部分：完整服务端历史、跨机器恢复、真实长任务崩溃后桌面恢复仍待验；本地缓存不是服务端历史 |
| F-03 HumanGate | permission/merge 白名单、拒绝路径、权限重验；修复决策 evidence 缺失和审批者归属；UI 拒绝把 SDK error 响应提示为发送成功 | 后端本地通过；真实桌面 interrupt→审批→resume 端到端待验。风险/预算/CI 不扩充 Gate |
| F-04 Memory/能力目录 | `runner/memory`、`runner/distill`；修复 LIMIT 前排除 Runtime State、坏索引报错、搜索竞态与输入失焦；Admin 跨组/项目读取留痕；卡片补输入输出依赖与别名 | 部分：普通用户项目级授权检索尚无完整 grant 解析，本次产品入口仅返回本组和 global，避免把组身份当项目授权；卡片实时状态同步待接 |
| F-05 SSH | challenge/roster/session 后端及单测存在；UI 区分 HTTP 服务连通和身份认证，移除默认供应商“已配置”假象 | 待接入：本地 agent/keychain 签名、真实 SSH gateway、主机/密钥/roster 各失败状态的桌面闭环未完成 |
| F-06 组件适配 | `tools/factor`、FactorPanel、QuantEvaluator adapter 与状态契约；12 个主链组件已登记；移除 PIT 前端私算估值 | 部分、待接入：目录存在不代表组件已接通；DataAccess→FE→QE 等真实输入/输出/版本/artifact 尚需服务验收；不自建替代组件 |
| F-07 跨组协同 | Blackboard、Model→Risk CI、事务/去重及 handoff 测试存在；领域 verdict 不创建 Gate | 本地通过；真实 GitHub Actions/报告平台交付链未验收，维持 CI 基建定位 |
| F-08 领域工具 | 六组 flows 和 strategy/options/fundamental/portfolio 回归存在 | 部分、待接入：stub/proxy/本地引擎不能冒充 canonical；保留组内适配，不增加统一业务产品 |
| F-09 Admin/GitGraph/Pop | 修复后端仅返回聚合而 UI 要明细的错配；保留 actor_id/ts；快照替换旧数据；每个用户的多条运行可展开；GitHub 分页、提交与依赖文件字段适配；普通角色可见授权 GitGraph 入口 | 部分：完整分支/HEAD 图、真实 GitHub token broker、后台同步、Pop 后端 read/ack 与桌面统一闭环、系统通知仍缺；管理页报告/任务入口仍为占位 |
| P-01 数据契约 | `schemas/data_contracts.py`、market/factor tests，缺源必须 no_source/UNAVAILABLE | STAGING：真实 ReturnsDataset/DataAccess 来源、PIT/交易日/label 版本一致性需真数据验收 |
| P-02 回测 | strategy adapter、backtest 回归；不扩充统一回测 UI | STAGING：VectorBT-QS fast/accurate 真组件回放及 A 股约束由组件证明 |
| P-03 组合 | portfolio adapter/verdict 测试、移除人审旧语义 | STAGING：Riskfolio-QS 的 alpha/risk/benchmark/previous_positions 到 target_positions/trades 闭环未验收 |
| P-04 Subagent | `tools/subagent`、parallel registry、预算/身份继承和 kill 回归 | 本地通过；真实跨进程、长时间并发负载未压测 |
| P-05 实验 | `tools/experiments`、OOS/ledger/artifact 测试 | 本地通过；外部实验平台消费与真实数据实验不在本轮证据内 |
| P-06 Evidence | 哈希链与关键写入 fail-closed；本轮补 Admin 敏感读取审计、permission 决策结构、实际审批人和原 Gate 关联 | 本地通过；外部审计消费/长期归档需运营验证 |
| P-07 蒸馏与复用 | 候选生成/晋升/拒绝/supersede、strict reuse；摘要包含 maturity/integration 和“不重复造轮子”；提供组件交叉表 | 部分：定时消费入口不等于生产 timer 已启用；定期实读 GitHub、人工确认冲突、状态刷新未闭环 |
| P-08 Admin 中枢 | 全组运行/错误/Blackboard 查询与角色检查；新增敏感读取审计；UI 明细和错误状态已修复 | 部分：报告/任务管理、完整组织后台汇聚及长期状态检索仍待实现；不能仅归因外部服务 |
| P-09 Admin Deploy | `runner/admin_operations.py` 黑盒 STAGING + required evidence；六组 MCP 不注册 deploy | STAGING：真实队列、幂等/回滚协议、生产服务账号与完整 Admin 部署面未接通；不会伪造生产成功 |
| P-10 Solution-First | task classifier/solution workflow、draft 工具限制、frozen hash、conformance、UI 状态测试 | 后端本地通过；真实 L2/L3 桌面方案冻结、执行、偏离检测和恢复端到端仍未验收 |

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
| D-009 deploy 属 Admin | MCP 六组非法调用回归；部署 adapter 仍 STAGING |
| D-010 私钥留本地 | 当前 UI 无私钥输入/上传；真实 keychain/agent 签名未验收 |
| D-011 完整图与提醒 | 明确未完成，不能把仓库状态列表与本地提醒当完整 GitGraph/Pop |
| D-012 canonical 业务真相 | 组件统计对照、卡片依赖与别名已补；无真数据不编造指标 |
| D-013 唯一数据/标签权威 | schema/缺源失败回归；真实来源待验 |
| D-014 保留底座 | 未替换 OpenCode 会话/编辑器/运行时基础设施；只改 QuantCode 增量 |
| D-015 测试服从规范 | 删除前端自行估值的旧测试前提；新增失败、权限、实际载荷和浏览器测试 |

## UI 断言 U1～U9

| 断言 | 本轮证据 | 缺口 |
|---|---|---|
| U1 登录 | 未认证禁止提交，不把 HTTP 当 SSH，无私钥字段 | 真 SSH 三方联动与失败分类未验 |
| U2 组路由 | 三角色浏览器 fixture + 六组后端权限回归 | 实际 roster 会话未端到端运行 |
| U3 任务/方案 | 方案面板与后端分级测试 | 真任务冻结/恢复未做浏览器全链 |
| U4 执行记录 | trace/checkpoint/replay 单测及原有桥接测试 | 服务端历史与 artifact 跨页面回放未全链 |
| U5 Memory/能力 | 输入焦点、竞态、503、组 ACL、真实 SQLite、卡片元数据；两种尺寸滚动 | 项目 grant UI、知识晋升 UI 和实时组件状态仍部分 |
| U6 Gate | 白名单、批准/拒绝证据、审批者 | 真浏览器跨角色审批待验 |
| U7 Admin/GitGraph/Pop | 普通角色可见 GitGraph；明细/来源/失败；列表不混合旧快照 | 完整图、后台同步、系统通知、持久化 ack UI 待补 |
| U8 部署 | 普通 MCP 不存在 deploy；Admin adapter STAGING | 真 Admin 部署管理 UI 与服务未完成 |
| U9 外部结果 | HTTP/坏载荷显式失败；PIT 原样展示有来源的结果、缺失为 —、零值保留 | 其他领域结果的生产格式仍需各组件提供样本联调 |

视觉参照是现有对话主页的黑白、细线、克制文字层级。详情页统一纸面底色、内边距、小标题和滚动容器；短桌面保留设置入口；长列表滚动时关闭按钮保持可见。没有把主页面改成仪表盘。900×650 与 1440×900 的实测截图保存在前端 `packages/app/e2e/test-results/quantcode/`。

## 本轮验证

- 初始后端：1,060 passed / 4 skipped；初始 QuantCode UI：114 passed。
- 最终后端及前端结果见本报告末尾验证记录。新增测试包括真实 SQLite 权限/索引问题、GitHub 多页与失败、Admin 审计、审批证据、六组真实 stdio MCP 子进程。
- 新增 Playwright 7 项全部通过：未认证 1 项、三角色 3 项、503 1 项、桌面尺寸/滚动 2 项。运行真实 branded app + HTTP server，但只读 MCP 响应由测试 fixture 提供。
- 未启用真实 LLM 的 4 项测试；未做 macOS/Windows Tauri 打包后的壳验收、真实 SSH/生产组件/部署 E2E，亦未做性能压力和通宵稳定性实验。stdio 测试不能称为原生桌面壳测试。
- 当前已知 Python 告警：`ToolDef.schema` 遮蔽 BaseModel 属性；未为去告警改动公共契约。

## 剩余工作优先级与验收标准

1. **身份接入（发布阻塞）**：本地 SSH agent/keychain → gateway → roster → 不可变 Session → 桌面；用真实账号验证错密钥/无 roster/断网/换服务/恢复时权限重验。
2. **研究主链（发布阻塞）**：从已授权 DataAccess 真数据跑一次 FactorPanel/LabelBundle → QuantEvaluator，产物携带版本、时点、来源与 evidence；组件缺失保持明确失败。复用组件详见交叉表。
3. **运行恢复（发布阻塞）**：真实 L2/L3 冻结后执行，制造进程退出，以同一 checkpoint 恢复，确认不重复写入；另一审批者处理 Gate 后 evidence 身份正确。
4. **管理工作台（本地功能缺口）**：服务端历史列表、报告/任务入口、Admin 部署交互、完整 GitGraph 分支/HEAD、Pop read/ack 统一服务契约。前端已存在不能作为免验理由。
5. **GitHub/通知（接入与本地工作并存）**：subject-scoped token broker、后台同步和错误/限流/缓存基线；系统通知使用真实权限与持久化 read/ack。
6. **组织 Memory 运维**：项目 grant 解析、确认/晋升界面、生产消费 timer、来源变更与过期撤销；普通用户未有项目 grant 前维持收紧查询。
7. **交付验证**：原生 macOS/Windows 壳、真服务 E2E、长时间任务/并发/性能测量。不能根据 fixture E2E 给出上线通过结论。

本次结果是跨仓库审查、可复现修复和未完成项清单；不是生产验收签字。

## 最终验证记录

2026-09-05，macOS，本地 Python venv、Bun 1.3.14、Chromium：

| 检查 | 结果 |
|---|---|
| 后端全量 pytest | **1,074 passed / 4 skipped**，16.81 秒；4 项真实 LLM 未启用 |
| QuantCode UI 组件回归 | **126 passed / 0 failed**，含 394 次断言 |
| App TypeScript typecheck | **通过** |
| Playwright branded app | **7 passed**，13.5 秒；fixture MCP 响应 |
| 两仓库 git diff --check | **通过** |
| 验证脚本 shell 语法 | **通过** |

复现入口：`bash scripts/verify_product_audit.sh`。设置 `QUANTCODE_TEST_PYTHON` 指定已安装项目依赖的 Python；设置 `QUANTCODE_UI_ROOT` 为 opencode-lens 根目录可同时运行 UI/typecheck/Playwright。首次浏览器运行需要在前端 app 包安装 Chromium（`bunx playwright install chromium`）。脚本使用正式品牌启动器，复用已有 dev server，不自动重启服务。

本轮通过验证脚本完整运行上述链路。改动仍保存在两个本地工作区，尚未提交或部署。


## 后续增量：F-02 恢复和事件通道

2026-09-05 后续实现及验证见 [F02_RECOVERY_STREAM_2026-09-05.md](F02_RECOVERY_STREAM_2026-09-05.md)。本批修复 checkpoint 恢复归属、已有 thread_id 覆盖、实时事件回调、跨进程事件文件保留及流读取授权。全量后端 **1,113 passed / 4 skipped**。服务端历史列表、完整回放和生产故障恢复仍未验收，不将 F-02 标记完成。前述初轮“尚未提交”只描述当时状态；此前批次已经推送 main。

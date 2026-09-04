# QuantCode 桌面端设计规格（UI_DESIGN_SPEC）

> **版本**：v4（2026-09-04，QuantCode v5 顶层设计同步）
> **Owner**：Agent Group · HKUST QUANT SOCIETY
> **UI 仓库**：`opencode-lens`，组件根目录为 `packages/app/src/components/quantcode/`。
> **上位规范**：[FUNCTIONAL_SPEC.md](/Users/hendrixchen/Desktop/私募/QUANTcode/specs/FUNCTIONAL_SPEC.md)；本文件只定义桌面端接入、展示和操作，不复制领域业务平台。

## 1. 设计目标

QuantCode 桌面端运行在 OpenCode 的 Desktop/TUI、session、Prompt/Context、MCP、Provider 和 Workspace 底座上。它提供按身份和权限运行的研究工作台：

```text
本地 SSH 身份
→ 业务组/角色绑定
→ 组内 Memory 与可见能力
→ 任务/方案/Agent trace
→ 结果、错误、组件状态
→ （共享写入）Gate；（生产部署）Admin 管理面与审计
```

界面统一，数据和操作随服务端 session 权限变化。普通用户使用自己的 GitHub/服务端可见范围；Admin 作为组织级角色查看和管理全组织内容。

### 1.1 UI 边界

- 策略、组合、回测、期权定价和基本面报告页面由对应业务平台提供；
- IC、风险、Greeks、组合和回测结果由权威组件计算，前端只展示 artifact 和来源；
- AlphaFlow 和其他生产系统的内部结构不出现在研究员界面；
- 研究结果、风险阈值失败和 CI 结果显示为结果或状态，不生成审批卡；
- 前端隐藏只负责体验，后端权限决定可见性和可操作性。

### 1.2 底座与新增界面

OpenCode 提供 Desktop/TUI、session、Prompt/Context、MCP、Provider、Workspace、文件/Shell 工具和原生状态流。MimoCode 提供通用 Compose Skill、Memory、Task、Checkpoint 和 Subagent 的工作流设计。QuantCode 在这些界面之上增加组身份、组内 Memory、能力目录、量化 artifact、方案面板、GitGraph、Pop 和 Admin 中枢。

UI 只消费服务端 session、工具目录、结构化 artifact 和外部平台链接。QuantCode 面板不复制 OpenCode 的会话逻辑，也不重算业务指标。

### 1.3 交互原则

- OpenCode 的会话、消息、工具状态、文件和终端仍是主工作区；QuantCode 面板提供身份、组织知识、量化 artifact 和治理入口。
- 组上下文由认证 session 提供。页面展示当前组，不提供任意切组控件；重新登录才会建立另一组 session。
- 结果页面优先展示来源、版本、时间、状态和下一步入口。`mock`、`proxy`、`staging`、权限拒绝和服务不可用都使用独立状态样式。
- 需要输入的动作使用文本区、文件选择、日期选择和结构化表单；审批、确认、停止和跳转动作必须有明确的操作结果。
- 生产服务账号、生产 shell 和 AlphaFlow 内部结构不出现在研究员 UI。Admin 的部署面只显示受控接口返回的最小结果。

## 2. 身份、组与角色

### 2.1 SSH 登录界面

登录界面只调用本地 SSH agent 或密钥链，不接收私钥文本。流程如下：

1. 选择本机 SSH agent/密钥链中的身份；
2. 发起公钥认证连接；
3. 服务端验证指纹，从公司 roster 匹配 actor、业务组、角色和个人工作目录；
4. 显示 fingerprint 摘要、连接状态、绑定组、角色和工作目录；
5. 服务端返回组页面上下文，页面不提供自由切组；需要另一个组时重新使用有权限的身份登录。

私钥不上传、不回显、不写入 localStorage、不发送给 LLM，也不进入 trace。研究员进入的是服务器上的个人工作目录；生产服务账号和生产 shell 不属于该登录会话。若平台暂时不能调用本地 SSH agent，UI 显示“身份接线未完成”，不显示假连接状态。

### 2.2 角色

| 角色 | 可见性 | 操作 |
|---|---|---|
| `analyst` | 本组和授权公共内容 | 研究、开发、查询；Gate 只读 |
| `approver` | 本组和授权公共内容 | 可批准被分配的写操作 Gate |
| `admin` | 全部组、全部 Memory/Blackboard、全部 repo 和运行 | 全部查询、管理和审批；仍保留 Gate/evidence 记录 |

角色必须来自服务端权威身份/权限数据。前端身份名启发式只能用于开发占位，不能决定 Admin 或审批权限。

## 3. 信息架构

| 视图 | 主要用户 | 数据源 | 状态 |
|---|---|---|---|
| 首页/任务提交 | 全部登录用户 | session + 组/Skill/能力目录 | 必须接真实组身份 |
| 会话/Activity | 全部登录用户 | `execution_trace`、artifact、错误 | 保留 |
| 方案面板 | L2/L3 任务 | `SolutionDoc`、方案事件 | 按复杂度出现 |
| Memory/能力目录 | 全部登录用户 | Memory、`list_capabilities` | 按 ACL Mask |
| 组件/评估结果入口 | 相关研究组 | 外部组件 artifact/链接 | 只展示，不重算 |
| Gate/审批 | approver/Admin | Gate payload、evidence | 只显示 merge/permission Gate |
| Admin 中枢 | Admin | 运行、错误、Memory、Blackboard、组件状态 | Admin 专属 |
| GitGraph | 普通组员/Admin | GitHub API/组织 Git 服务 | 权限范围不同 |
| 通知中心/Pop | 全部登录用户 | Gate、repo/package 变更 | 遵守同一 ACL |
| 设置/连接 | 全部登录用户 | 本地 SSH/provider 状态 | 私钥不出本机；组由 roster 返回 |

### 3.1 面板与数据契约

| 面板 | 组件文件 | 主要契约 | 关键状态 |
|---|---|---|---|
| 首页/任务提交 | `panels.tsx` | `RunAgentArgs` / session | 未认证、提交中、已提交、拒绝 |
| 会话/Activity | `panels.tsx`、`result-contract.ts` | `RunAgentResult` / `TraceEvent` | 运行中、checkpoint、降级、失败、完成 |
| 方案 | `solution-panel.tsx` | `SolutionDoc` | draft、discussion、frozen、verdict |
| Memory/能力目录 | `memory-query.tsx`、`capability-catalog.tsx` | Memory query / CapabilityCard | 空态、无权限、未连接、结果 |
| HumanGate | `panels.tsx`、`notifications.tsx` | `HumanGate` | 待处理、批准、拒绝、过期 |
| Admin | `admin-console.tsx` | admin query/run/error contracts | 全组织结果、部分失败、无权限 |
| GitGraph/Pop | `gitgraph-panel.tsx`、`notifications.tsx` | repo/package update contracts | 已观察、已更新、已读、确认、错误 |
| SSH/设置 | `ssh-login.tsx`、`settings-supplier.tsx` | identity/roster status | 未连接、连接中、已连接、失败 |

所有面板只渲染服务端返回的授权结果。前端状态不能推断或扩大 `group`、`role`、repo、Memory 和生产权限。

### 3.2 功能到界面映射

| 编号 | 界面承载 | 界面边界 |
|---|---|---|
| F-01/F-02 | 首页、会话和 Activity | 提交、状态流、trace、artifact 和回放 |
| F-03 | GatePanel、通知中心 | 仅 `merge`/`permission`；部署另走 Admin 面 |
| F-04/P-07 | Memory、能力目录 | 组内共享、公共契约、卡片状态和 ACL |
| F-05 | SSH/设置 | 本地公钥证明、roster 结果和个人工作目录 |
| F-06 | 因子评估、PIT、外部结果入口 | 只展示 QuantEvaluator、DataAccess 和报告 artifact |
| F-07/F-08 | 会话结果和外部链接 | CI/handoff 与组内工具，不新增业务产品页 |
| F-09/P-08 | Admin、GitGraph、Pop | Admin 全组织可见；普通用户遵守 GitHub 权限 |
| P-09 | Admin 部署入口 | 生产服务账号受控执行，普通 Agent 不可见 |
| P-10 | 方案面板 | L2/L3 方案冻结和一致性 verdict |

## 4. 首页与任务提交

首页提供自然语言任务、已绑定的组/角色、可用 Skill 和最近任务。组由认证会话提供，页面不提供组选择器。Skill 列表从维护员发布的 `list_skills` 目录获取，加载失败显示明确错误。

提交前显示当前可用能力的摘要：组件名、用途、成熟度、接入状态和“何时别自造”。首页提供提示和复用入口，详细 API 仍在能力目录中查看。

任务由后端分别判断业务模式、复杂度、执行策略和治理类别，再按复杂度处理：

- L0 查询/只读：直接提交；
- L1 有界研究/小修改：可生成轻量计划；
- L2 架构/多模块：展示方案面板，冻结后才进入代码阶段；
- L3 共享高影响变更：方案、共享写入和审计均可见；生产部署独立归 Admin 管理面，普通研究 Agent 不出现部署入口。

## 5. 会话与执行记录

Activity 按顺序展示：

```text
用户输入 → Agent 思考 → 工具调用 → 工具结果 → artifact/错误
→ 方案状态 → Gate（若为写操作）→ 结束状态
```

要求：

- 事件按 `thread_id + iteration + seq` 去重；
- 失败、降级、mock、proxy return 等必须显式标注；
- artifact 显示来源、版本、哈希和打开入口；
- 不在 UI 中从多个不一致数据源自行推断“成功”；
- 只允许用户访问自己有权限的会话和 artifact，Admin 可查看全部并保留访问记录；
- 支持 checkpoint/replay，但恢复操作仍按当前权限和 Gate 规则执行。

## 6. 方案面板

方案面板只服务 L2/L3 任务，不强制所有查询和小修改都出现。状态：

```text
draft → discussion/revision → frozen → implementation → conformance verdict
```

显示 goal、验收标准、预期文件面、讨论记录、版本和 `doc_hash`。draft 阶段提示代码工具不可用，但允许查能力、读资料和验证；该状态属于流程控制。`conformant`、`deviation`、`needs_human` 是一致性结果，不等同于生产审批。

## 7. Memory 与能力目录

### 7.1 组内 Memory

Memory 页面只展示已确认的长期 Group Knowledge（Checkpoint、Progress、Trace 等 Runtime State 留在 Work/Activity），默认展示当前组共享知识：研究结论、失败记录、组件用法、数据口径、工程决策和 Best Practice。公共契约单独标识。普通组员不能搜索其他组的详细 Memory；Admin 可以查看全部内容。

每条结果显示 scope、来源、更新时间、验证状态和 superseded 关系。未接通真实后端时显示空态/未连接，不展示假数据。

### 7.2 能力目录

能力卡至少展示：

- canonical repo、`maturity_status`（PRODUCTION/STAGING/RESEARCH/SCAFFOLD/LEGACY）和 `integration_status`（CONNECTED/PARTIAL/UNAVAILABLE/UNVERIFIED）；
- 公开用途、输入/输出摘要、领域权威、依赖和消费者；
- “何时用”和“何时别自造”；
- 属组、可见性和来源 commit/观察时间；
- 旧名称到 canonical repo 的映射。

详细 API、敏感字段和部署底层按 ACL 过滤。普通用户看到 GitHub/组权限允许的内容；Admin 看到完整目录；游客只看到公开契约。

## 8. HumanGate 页面

GatePanel 只显示普通 Agent 可以触发的共享写入和跨组授权：

| kind | 示例 | UI 行为 |
|---|---|---|
| `merge` | 主线/共享生产资产入库 | 显示变更、来源、风险和批准/拒绝 |
| `permission` | 受限跨组资源访问 | 显示资源范围和一次性授权 |

生产部署由 Admin 管理面单独展示和执行，不在普通研究员的 GatePanel 中出现。研究报告、风险指标越限、评估失败、普通代码修改和 CI 结果不显示 Gate 卡。预算耗尽显示预算告警或停止状态。

Admin 可以处理全部 Gate，并在管理面发起部署；approver 只处理授权 Gate；analyst 只读。界面显示 actor、时间、理由、资源和 evidence 状态；拒绝终止对应写操作。

## 9. Admin 中枢

Admin 中枢提供组织管理工作台：

- 自然语言查询各组、成员、任务、运行、错误和模块状态；
- 全部组 Memory/Blackboard 的只读或管理视图；
- 组件目录、版本、状态和失败依赖；
- 报告管理、任务管理入口（逐步接入外部报告平台/QuantPlatform）；
- GitGraph 和通知中心入口；
- 所有查询、修改和审批的审计记录。

Admin 的“全部可见性”覆盖普通组的 Memory Mask 和 repo 过滤。生产部署仍由服务端的 Admin 权限和生产服务账号控制，前端不能绕过。

## 10. GitGraph 完整目标

GitGraph 不按“属组仓库”静态写死，而按当前 GitHub 权限查询：

- 普通用户：显示其 GitHub 身份可见的全部组织 repo；
- Admin：显示组织全部 repo；
- 每个 repo 显示分支、HEAD、最新提交、提交树/时间线、活跃度、归档状态和依赖文件变化；
- 更新节点标红/高亮，可跳回 GitHub；
- API 错误、权限不足和仓库缺失要分别显示，不能伪装成“没有更新”；
- 后端返回权限上下文和 `observed_at`，前端只渲染授权结果。

## 11. Pop 与通知

### 11.1 两类更新 Pop

1. repo 新提交、分支或仓库状态变化；
2. 依赖库/package 版本变化。

Pop 与 GitGraph 使用相同可见性边界：普通用户只收到自己可见 repo 的消息，Admin 收到组织范围消息。每条 Pop 应有来源、时间、变化摘要、old/new 值、baseline、跳转、去重键、已读/确认状态。

### 11.2 完整增强目标

目标运营模式包含服务端定期检查、基线保存、变更检测、重复抑制、应用内通知和系统级通知。手动“检查更新”作为没有后台服务或调试时的降级路径。没有真实数据时显示未连接，禁止生成示例更新。

## 12. 外部业务平台入口

因子评估、PIT 研究、策略结果、组合和期权结果在 QuantCode 中只显示结构化 artifact、来源和跳转：

```text
FactorEngine / DataAccess → QuantEvaluator → Report Platform
Modeling / Barra / Riskfolio / VectorBT → Report Platform
```

QuantCode 不在 UI 重复实现这些平台的业务页面。`/deploy` 只在 Admin 管理面显示，结果包含成功/失败、artifact 路径、部署记录哈希和可操作错误，不暴露生产底层结构。

## 13. UI 验收重点

1. 本地 SSH 身份不上传私钥；服务端返回的 actor/组/角色/工作目录与 UI 一致；未认证不能提交任务；页面不提供自由切组；
2. 普通组员与 Admin 的 Memory、能力卡和 GitGraph 可见性符合 GitHub/roster 权限；
3. 复杂任务才出现方案面板，L0/L1 不被固定讨论轮次阻塞；
4. 研究输出、风险失败和 CI 结果不出现 Gate 卡；merge/permission 写操作能审批并回放；Admin 可从管理面提交 `/deploy` 并查看审计；
5. GitGraph 显示权限范围内完整 repo/分支/提交状态；repo/package 两类 Pop 可去重、确认和跳转；
6. 外部组件未接通、权限不足、mock 或 staging 必须在 UI 明示；
7. Admin 查询能覆盖所有组，并保留访问/审批审计；
8. UI 组件测试不再把旧版“风险越限必人审”“模型 PR 是产品主链”“六条业务流由 QuantCode 承担”作为验收前提。

## 14. 维护规则

- 本文与 `FUNCTIONAL_SPEC` 的编号和状态同步；
- UI 只消费后端契约和外部 artifact，不复制领域计算；
- 角色、组和 repo 可见性必须由权威服务/会话提供，不能长期依赖前端字符串启发式；
- 新增视图必须说明其业务归属、权限边界、数据源和失败空态；
- GitGraph/Pop 的自动刷新、系统通知、报告/任务工作台和真实 SSH surface 是增强项，未接通时必须标为未完成。

## 15. 组件清单与落位

| 组件 | 文件 | 责任 |
|---|---|---|
| 品牌壳、导航和任务入口 | `panels.tsx` | OpenCode session 接入、当前组/角色/连接状态和任务提交 |
| Activity、指标和 artifact | `panels.tsx`、`metric-cards.tsx`、`factor-screen.tsx` | trace 时间线、评估结果、来源和错误 |
| PIT 与外部平台入口 | `pit-screen.tsx` | 时点约束、artifact 和报告平台跳转 |
| SSH 登录和供应商 | `ssh-login.tsx`、`settings-supplier.tsx` | 本地公钥证明、roster 结果和 Provider 状态 |
| Memory 与能力目录 | `memory-query.tsx`、`capability-catalog.tsx` | 组内搜索、能力卡、ACL 空态和版本来源 |
| 方案与 Gate | `solution-panel.tsx`、`panels.tsx` | P-10 阶段、conformance verdict、`merge`/`permission` 审批 |
| Admin、GitGraph 与 Pop | `admin-console.tsx`、`gitgraph-panel.tsx`、`notifications.tsx` | 组织查询、GitHub 可见仓库、更新通知和审计入口 |

`/deploy` 仅在 Admin 管理面挂载独立组件或管理入口。普通研究员导航、任务输入和 GatePanel 不出现部署控件。

## 16. 文案与本地化

新增组件的文案使用 i18n key。中文和英文至少覆盖登录状态、权限拒绝、未连接、mock/proxy/staging、方案阶段、Gate kind、GitGraph 更新和部署结果；缺少翻译时显示稳定的 fallback key，不拼接敏感错误细节。`parity.test.ts` 检查各 locale 的 key 集合，领域组件返回的原始错误由后端做脱敏后再展示。

## 17. UI 验收断言

| 编号 | 场景 | 断言 |
|---|---|---|
| U1 | SSH 登录 | 只选择本地身份；连接成功显示 actor、组、角色、工作目录；失败原因可区分；私钥不出请求和页面 |
| U2 | 组路由 | 登录后显示服务端绑定组；页面没有自由切组；不同 `group` 请求被拒绝 |
| U3 | 任务与方案 | L0/L1 可直接执行；L2/L3 展示方案阶段；draft 阶段不生成代码；frozen 后显示 hash 和 verdict |
| U4 | 执行记录 | trace 去重；checkpoint 可回放；artifact 带来源、版本、哈希和状态 |
| U5 | Memory/能力目录 | 普通用户只见授权内容；Admin 全可见；未连接和无权限不展示假结果 |
| U6 | HumanGate | 仅 `merge`/`permission` 卡片进入普通 GatePanel；风险、评估、预算和 CI 不生成 Gate 卡；Admin 可处理全部 Gate |
| U7 | Admin/GitGraph/Pop | Admin 可查全组织；普通用户遵守 GitHub 可见范围；repo/package 更新可去重、确认和跳转 |
| U8 | 部署边界 | `/deploy` 只在 Admin 管理面可见；普通 Agent 调用被拒；结果不暴露生产拓扑、服务账号或 AlphaFlow 内部结构 |
| U9 | 外部结果 | mock、proxy、staging、权限失败和 API 错误有明确状态，不伪装为成功或空结果 |

UI 测试必须覆盖 analyst、approver 和 admin 三类 session，并用服务端授权结果作为 fixture。旧版“风险越限必人审”“自由切组”“普通 Agent 部署”和“六条业务流都是产品页”的断言应删除或改成边界回归。

## 18. 修订记录

| 日期 | 变更 |
|---|---|
| 2026-09-01 | v1：F/P UI 清单、方案面板、Admin/GitGraph/Pop 初版 |
| 2026-09-03 | v2：按业务组登录、组内 Memory、Admin 全权限、GitHub 权限边界、本地 SSH 身份、生产隔离、完整 GitGraph/Pop 和按复杂度方案先行 |
| 2026-09-03 | v3：补齐 OpenCode/MimoCode 底座映射、面板契约、组件落位、本地化和 U1~U9 验收；Admin 部署与普通 Agent Gate 分离 |

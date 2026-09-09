# QuantCode 产品验收测试计划

日期：2026-09-09  
状态：`DRAFT`  
依据：`docs/PRD.md`、`specs/FUNCTIONAL_SPEC.md`、`docs/QuantCode_Design.md`、`docs/UI_DESIGN_SPEC.md`。

本文定义当前版本的正式产品验收方式。它不以历史 pytest nodeid 数量、缓存列表或旧 Runner 行为作为需求来源。用例先按产品需求和风险建立，再生成 pytest、Bun、Playwright、Electron 和真实服务测试。

## 1. 验收范围

### 包含

- QuantCode 桌面入口、身份登录、服务器/公钥选择、个人工作区和模型配置；
- 统一任务执行、任务分类、Skill/能力目录、Memory、方案、子任务、预算、取消、恢复和回放；
- `merge`/`permission` HumanGate、未知回执核对、Blackboard、artifact、trace、evidence；
- 八组上下文、Admin、GitGraph、Pop、报告/产物和 Admin-only 部署入口；
- legacy 历史读取/恢复、迁移兼容、构建、安装和升级；
- 桌面可访问性、键盘、滚动、错误状态、性能和安全边界。

### 不包含

- 各业务组 canonical 组件内部算法正确性；
- 报告平台、生产系统和 GitHub 自身的可用性；
- 投资收益好坏；
- 把旧 Python AgentRunner 作为新任务执行器；
- 手机端产品验收。

## 2. 风险等级与通过规则

| 等级 | 定义 | 通过要求 |
|---|---|---|
| P0 | 身份、权限、生产边界、副作用、数据口径、任务状态 | 一个失败即不能发布 |
| P1 | 主要产品流程、恢复、Admin、GitGraph、模型配置、桌面交互 | 必须全部通过或有明确外部阻断 |
| P2 | 细节、兼容输入、可观测性和体验优化 | 允许带已登记缺陷发布 |

结果只允许：`PASS`、`FAIL`、`BLOCKED_EXTERNAL`、`NOT_RUN`、`N/A（有范围依据）`。跳过、收集成功、服务在线或静态代码存在都不能算 `PASS`。

## 3. 测试层级

### L1：单元与契约测试

覆盖 schema、状态机、路径边界、角色映射、去重、预算计算、错误映射、artifact 完整性和 UI 纯函数。运行快、无网络、每条断言稳定。

### L2：服务集成测试

使用隔离 gateway、临时数据库、临时目录和受控组件 fixture，验证身份、Memory、能力目录、Blackboard、Gate、artifact、task index、部署和 legacy API 的真实 HTTP 契约。

### L3：应用端到端测试

使用当前源码启动的 Vite 页面和隔离后端，验证页面导航、表单、状态、键盘、滚动、任务连续性和错误恢复。QuantCode 与通用 App E2E 分开统计。

### L4：桌面验收

使用当前源码构建的 Electron 应用，验证文件选择器、SSH Agent/Keychain、服务器切换、窗口生命周期、系统通知、下载、安装包和升级。旧安装包不能作为当前版本证据。

### L5：真实外部验收

使用专用测试成员、模型 key、SSH gateway、GitHub subject、已发布组件和临时资源，验证真实成功路径。外部条件不足时记录 `BLOCKED_EXTERNAL`。

## 4. 环境矩阵

| 环境 | 用途 | 必须隔离 |
|---|---|---|
| Unit | L1 单元、schema、纯逻辑 | 用户目录、真实 token、真实 SSH Agent |
| Service fixture | L2 组织服务和失败分支 | gateway、数据库、Memory、artifact、组件 |
| Browser fixture | L3 UI 与 API 路由 | 浏览器 profile、真实账号、生产服务 |
| Desktop QA | L4 Electron | 安装目录、sidecar、Keychain、窗口 |
| External QA | L5 真实成功场景 | 测试成员、测试 key、测试 repo、测试模型 |

## 5. 功能验收用例

### 5.1 启动、构建与安装（BOOT）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| BOOT-01 | 干净环境安装并启动 | 只出现 QuantCode，sidecar/renderer 来自当前源码 | L4 |
| BOOT-02 | 缺身份、gateway、Python、组件目录 | 分别显示明确错误，不假在线、不无限 loading | L2/L4 |
| BOOT-03 | 检查源码、产物、许可证和依赖 | 无第二套 OpenCode 安装要求；来源和版本一致 | L1/L4 |
| BOOT-04 | 安装包启动 smoke | 窗口、品牌、sidecar health 和基础交互通过 | L4 |
| BOOT-05 | 升级旧版本 | 配置、服务器、任务历史和 legacy 数据保留 | L4 |

### 5.2 身份与服务器（AUTH）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| AUTH-01 | 展示本机 SSH Agent 公钥指纹列表 | 只显示指纹/摘要，不显示私钥 | L2/L4 |
| AUTH-02 | 系统文件选择器导入私钥 | 通过 `ssh-add`/Keychain 导入；私钥不上传、不写 renderer/storage | L4 |
| AUTH-03 | 选择不同公钥登录 | challenge、signature、session 全部绑定选中 fingerprint | L2/L4 |
| AUTH-04 | 服务器列表选择 A/B | 只允许已保存且经 URL 校验的研究宿主 | L3/L4 |
| AUTH-05 | 切换服务器 | 清理旧 session/cache，重新读取公钥和授权工作区 | L2/L4 |
| AUTH-06 | 错误签名、过期 challenge、重放 | 拒绝且无任务/文件/Memory 副作用 | L2 |
| AUTH-07 | logout 失败与重试 | 显示未完成，可重试；成功后清理私有状态 | L2/L4 |
| AUTH-08 | 任务参数伪造 group/role/actor/workspace | 后端拒绝；组只由认证 session 决定 | L2 |

### 5.3 模型与工作区（MODEL/WORK）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| MODEL-01 | URL + API Key 添加模型 | 只保存合法配置，可获取模型列表 | L2/L3 |
| MODEL-02 | 编辑、留空 key、换 URL、错误 URL | 配置与凭据配对校验；不误报成功 | L2/L3 |
| MODEL-03 | 主任务、子任务、辅助请求用量 | 一份配置、用量去重、父子归属可追踪 | L2 |
| MODEL-04 | 401/403/429/5xx/超时/空列表 | 状态可区分，可重试，不把空列表当接通 | L2/L3 |
| MODEL-05 | 预算警告和耗尽 | `STOPPED_BUDGET`，不能由 Gate 放行或加额 | L2/L3 |
| WORK-01 | 首次列出授权根 | 只返回当前身份授权目录及 read/write | L2/L3 |
| WORK-02 | 子目录导航和自动补全 | 根外、`..`、软链接逃逸和其他成员目录拒绝 | L1/L3/L4 |
| WORK-03 | 选择、取消、关闭目录弹窗 | 选择需最终复核；取消不覆盖旧草稿 | L3/L4 |
| WORK-04 | 切换宿主/退出期间迟到响应 | 旧 roots/validation 响应丢弃 | L2 |
| WORK-05 | 个人目录写入 | 个人目录允许；生产目录、仓库外路径和逃逸拒绝 | L2 |

### 5.4 任务执行（TASK/RUN）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| TASK-01 | 首页、模板、续问、命令面板提交 | 进入同一原生 session/执行链 | L3/L5 |
| TASK-02 | L0 查询 | 直接执行，无不必要方案/Gate | L2/L3 |
| TASK-03 | L1 小修改 | 轻量计划后执行，结果有 trace/artifact | L2/L3 |
| TASK-04 | L2/L3 任务 | 方案先行；冻结前写工具不可用 | L2/L3 |
| TASK-05 | 八组 Skill/Tool Catalog | 按 session 加载；不存在/下线/未授权明确失败 | L2/L3 |
| TASK-06 | 事件实时回流 | thought、tool、artifact、Gate、error 未等最终消息即可见 | L2/L3 |
| TASK-07 | 终态集合 | completed/failed/error/cancelled/waiting/budget/loop/unknown 标签准确 | L1/L3 |
| TASK-08 | 父子任务树 | 父子关系、状态和预算准确；不伪全成功 | L2/L3 |
| TASK-09 | 单独停止子任务 | 只停止目标后代，兄弟任务继续 | L2 |
| TASK-10 | 停止整个任务树 | 活动孙任务也停止；迟到通知不重启 | L2/L4 |

### 5.5 复用、数据与组件（REUSE/DATA）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| REUSE-01 | 已有因子值 | 先选 QuantEvaluator，不重算业务指标 | L2 |
| REUSE-02 | 无因子值 | DataAccess → FactorEngine → QuantEvaluator | L2 |
| REUSE-03 | 部分覆盖/无覆盖 | 展示具体缺口并征询；拒绝/沉默不放行自造 | L2/L3 |
| REUSE-04 | 目录失败/空/权限拒绝 | 不把失败当“无能力” | L1/L3 |
| DATA-01 | PIT 资料 | 只返回 `published_at <= as_of` | L1/L2 |
| DATA-02 | FactorPanel | 日期、资产、有效行、PIT、版本戳通过 schema | L1 |
| DATA-03 | TargetReturnView | Horizon、后复权、`t+1 → t+2` 口径强制 | L1/L2 |
| DATA-04 | Modeling/OOS | 时间切分、purge/embargo、OOS 来源可追溯 | L2/L5 |
| DATA-05 | Risk/Portfolio/Backtest | 展示权威组件结果；失败、mock、staging 明示 | L2/L3 |
| DATA-06 | 期权/基本面 | 先澄清关键输入；stub 不冒充生产结果 | L2/L3 |

### 5.6 方案、Gate、回执与恢复（PLAN/GATE/RECOVERY）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| PLAN-01 | SolutionDoc 状态机 | draft/discussion/frozen/implementation/verdict 顺序正确 | L1/L2 |
| PLAN-02 | 未冻结写入旁路 | edit/Shell/MCP/子 Agent 全部拒绝 | L2 |
| GATE-01 | merge Gate | 仅共享写入触发，绑定资源、版本、actor、evidence | L2/L3 |
| GATE-02 | permission Gate | 仅授权列出资源和一次性范围 | L2 |
| GATE-03 | 非 Gate 结果 | 风险、预算、循环、CI、普通修改不出现 Gate | L1/L3 |
| GATE-04 | 审批授权 | analyst 拒绝；指定 approver/Admin 可处理；同组不自动获得资格 | L2/L5 |
| GATE-05 | 过期/撤销/退出 | resume 重新校验，不沿用旧权限 | L2 |
| GATE-06 | 审批响应丢失 | 显示未确认，只能核对，不盲重发 | L2/L3 |
| RUN-01 | compact 后继续 | 目标、身份、方案、Gate、未完成工具保留 | L2 |
| RUN-02 | 断线重开 | 原 session/checkpoint 恢复，不重复启动 | L2/L4 |
| RUN-03 | 工具执行三时间点崩溃 | 未执行/未知/已完成三态准确 | L2 |
| RUN-04 | 未知回执核对 | 外部证据绑定 call/digest；确认后才恢复 | L2/L5 |

### 5.7 Memory、协同与 Admin（MEM/XGR/ADM）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| MEM-01 | 组内 Memory 搜索 | 当前组可见；Admin 全组织；其他组私有内容隔离 | L2/L3 |
| MEM-02 | 空/未连接/拒绝 | 三种状态区分，不造假数据 | L1/L3 |
| MEM-03 | Runtime State 隔离 | trace/checkpoint/progress 不直接进入长期知识 | L2 |
| MEM-04 | Dream/Distill 候选 | 有来源、digest、状态；未审核不发布/不执行 | L2 |
| XGR-01 | Blackboard handoff | schema、owner、消费者、artifact 引用完整 | L2 |
| XGR-02 | 跨组未授权读取 | 拒绝私有正文，公共摘要可按 ACL 返回 | L2 |
| ADM-01 | Admin 自然语言查询 | 结果来自 admin 工具，不凭模型编造 | L2/L3 |
| ADM-02 | Admin 页签 | 概览、任务、报告与产物、部署均可用 | L3/L4 |
| ADM-03 | 组织索引部分失败/延迟 | 显示观察时间、缺失范围和部分状态 | L2/L3 |
| ADM-04 | Admin 审计 | 查询、访问、审批、部署都有 actor/resource/time/result | L2 |

### 5.8 GitGraph、Pop、部署与 legacy（GH/DEP/LEG）

| ID | 验收项 | 预期结果 | 层级 |
|---|---|---|---|
| GH-01 | GitHub 本机/浏览器连接 | authorizing/connected/cancelled/error 状态准确 | L3/L4 |
| GH-02 | repo 可见性 | 普通用户按 subject 权限；Admin 组织范围；组名不扩大权限 | L2/L5 |
| GH-03 | GitGraph | repo、分支、HEAD、提交树、依赖变化、缺父节点可解释 | L3/L4 |
| GH-04 | Pop | repo/package 两类、old/new、时间、去重、已读/确认正确 | L2/L3 |
| GH-05 | 撤权清理 | 缓存、详情、Pop、计数不能继续暴露 | L2/L5 |
| DEP-01 | 普通用户部署旁路 | UI/API/MCP/Shell/子 Agent 全部拒绝 | L2/L5 |
| DEP-02 | Admin 部署 | artifact、版本、target、manifest、服务账号和 evidence 完整 | L2/L5 |
| DEP-03 | staging/503/超时/畸形状态 | 不能显示生产成功 | L2/L3 |
| LEG-01 | 旧历史读取 | engine、owner、source、version、read-only 状态完整 | L2/L3 |
| LEG-02 | 旧 checkpoint 恢复 | 当前权限、来源、Gate、模型重新校验 | L2 |
| LEG-03 | 损坏/不兼容旧数据 | 原文件保护；不自动覆盖或伪造恢复成功 | L2 |
| LEG-04 | 新旧并存 | session、缓存、通知和副作用互不泄漏/重复 | L2 |

## 6. 桌面 UI 验收矩阵

| ID | 检查项 | 视口/方式 |
|---|---|---|
| UI-01 | 主导航和所有主面板 | 1440×900、1920×1080 |
| UI-02 | 设置、服务器、公钥、私钥导入 | Electron + 键盘 |
| UI-03 | Loading/empty/error/forbidden/stale/partial/unknown | fixture 路由 |
| UI-04 | 长路径、长错误、长 artifact、长任务列表 | 900/1440/1920 |
| UI-05 | Tab/Arrow/Home/End/Enter/Escape 焦点 | Playwright + Electron |
| UI-06 | 首页→任务→Activity→方案/Gate→Admin→返回 | 同一任务 |
| UI-07 | 通知、外链、复制、下载 | Electron |
| UI-08 | 390px 场景 | 仅按明确范围记录，不纳入桌面通过门槛 |

## 7. 缺陷与证据要求

每个失败必须保存：测试 ID、环境、源码 revision、命令、退出码、完整日志、请求/响应摘要、截图或 AX snapshot、trace/video（如有）、复现步骤和影响等级。

- P0：阻断发布，必须修复并回归；
- P1：必须有修复计划和回归证据；
- P2：可带缺陷发布，但必须记录 owner 和版本。

不得用以下方式关闭缺陷：删除/skip 用例、放宽断言、过滤失败 nodeid、用 mock 替代真实成功路径、用旧安装包或静态页面冒充当前版本。

## 8. 执行顺序

1. 冻结本文和 schema/功能编号；
2. 生成 L1 单元/契约测试；
3. 准备隔离服务和 L2 集成测试；
4. 启动当前源码开发 UI，完成 L3 UI 验收；
5. 构建当前源码 Electron 包，完成 L4 桌面验收；
6. 收集当前 pytest/Bun/Playwright nodeid，与本文 ID 建立双向映射；
7. 执行 L5 真实模型、SSH、GitHub、组件、审批、部署和升级场景；
8. 汇总结果，解释所有缺失、失败、跳过和外部阻断；
9. 只有 P0/P1 全部有证据、nodeid 无未解释缺口、安装和真实关键路径完成，才允许标记验收通过。

## 9. 首轮执行命令

```bash
# Python
.venv/bin/pytest --collect-only -q
.venv/bin/pytest -q

# App
cd frontend/packages/app
bun run typecheck
bun run test:unit
bun run test:browser

# 当前源码开发 UI 的 E2E，端口必须先核验
PLAYWRIGHT_EXTERNAL_SERVER=1 \
PLAYWRIGHT_BASE_URL=http://127.0.0.1:<frontend-port> \
PLAYWRIGHT_TARGET_SERVER=http://127.0.0.1:<backend-port> \
bun run test:e2e -- --config=playwright.quantcode.config.ts
```

命令成功不等于验收通过；必须结合本文用例矩阵、真实环境、退出码和证据目录判断。

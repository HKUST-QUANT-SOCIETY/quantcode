# QuantCode UI 设计规格（UI_DESIGN_SPEC）

> **版本**：v1（2026-09-01）｜**Owner**：Agent Group
> **依据**：`specs/FUNCTIONAL_SPEC.md` v0.2.1 · `docs/PRD.md` v2 · 定版讨论纪要
> **UI 仓库**：`opencode-lens`（组件真源 = `packages/app/src/components/quantcode/`，断言用 playwright 表达）
> **定位**：本文是 UI 层唯一活文档——每个 F/P 编号对应什么屏、什么组件、什么状态。UI↔功能一一对应是验收目标。

---

## 1. 设计原则

1. **品牌壳统一**：`OPENCODE_CHANNEL=quantcode` → qc-shell 设计 token（QUANTCODE 点阵光场 lens-field 背景）；dev 渠道保持 OpenCode 上游壳（开发逃生门）。
2. **千组千流，不是千人千面**：统一 UI，组身份只切换 skill / tool 白名单 / Memory scope，不切换前端。
3. **角色三态**：`analyst`（审批只读）/ `approver`（可批准拒绝）/ `admin`（跨组可见）——`roles.ts::resolveRole(readIdentity())`，单一来源。
4. **一屏一事**：每个视图锚定一个 F/P 编号；trace 事件是数据源的主干（屏跟着 run 走，不另造数据面）。
5. **不做的 UI**（平台红线 1）：无策略回测产品界面、无组合产品界面、无报告平台复刻（归报告平台/产品 2）、不展示 AlphaFlow 内部结构（P-09 黑盒约束）。

---

## 2. 信息架构（左侧导航轨视图清单）

| 视图 | 锚定编号 | 状态 |
|---|---|---|
| 首页（研究提交） | F-01 | ✅ |
| 会话（对话 + trace） | F-01/F-02 | ✅ |
| Activity（执行时间线） | F-02 | ✅ |
| Gate（审批） | F-03 | ✅ |
| 因子评估 | F-06 | ✅ |
| PIT 估值 | F-06（fundamental 组内工具） | ✅ |
| 通知中心（铃铛） | F-03/F-09 | ✅ |
| 设置（供应商只读 + SSH 登录） | F-05 | 🔶（登录界面待 AG-E） |
| **能力目录** | F-04/P-07 | ✅（trace 通道 + fetcher 占位） |
| **Memory 查询** | F-04 | ✅（视图落地；memory_search 通道挂账 #8） |
| **Admin 中枢（含 GitGraph/pop）** | F-09/P-08（仅 admin 角色） | ✅（AG-D 后端 + AG-K UI，21 条打磨） |
| **方案面板**（会话内嵌） | P-10 | ✅（状态机+verdict 徽章，冒烟绿） |

---

## 3. 已实现 UI 盘点（对应 v5 PPT slide20 四屏）

| 屏 | 设计稿内容 | 组件 | 数据源 | 状态 |
|---|---|---|---|---|
| 屏1 因子评估 | 研究流程节点 + 评估指标大数字/阈值条 | `factor-screen.tsx`（match_main→gen_schema→autoeval→HumanGate 四节点）+ `metric-cards.tsx`（QcBigNumber/QcProgress/QcChecklistItem） | `RunAgentResult.execution_trace` + `output_data` | ✅ |
| 屏2 审批/Gate | 风险越阈值专用面板、批准/拒绝 | `panels.tsx::GatePanel`（approver 按钮 / analyst 只读）+ `notifications.tsx` | `run.gate`（breached_thresholds 权威） | ✅（v2 收窄后仅四类写操作进此屏） |
| 屏3 PIT 估值 | 证据时间线 + DCF 估值卡 | `pit-screen.tsx`（published_at≤as_of 红色告警 + 滑条实时重算） | `output_data`（documents/fair_value/…） | ✅ |
| 屏4 通知中心 | 待审批提醒汇总 | `notifications.tsx`（铃铛 + badge + 跳转审批） | waiting_for_human 运行历史 | ✅ |

---

## 4. 每功能 UI 规格

### F-01 新建多智能体研究 ✅（一处待补）
- **屏**：首页 RunAgentPanel——任务描述输入 + 组选择器 + skill 下拉 + ⌘⏎ 提交。
- **待补（AG-G）**：skill 下拉接 `list_skills` 真目录（现为硬编码 4 条）。
- **状态**：提交中（禁用按钮）/ 已提交（跳转会话视图）。
- **数据**：提交 → `buildResearchInstruction`（强制 run_agent）→ trace 经 `result-contract.ts` 回流。

### F-02 执行记录视图 ✅（可选增强）
- **屏**：ActivityPanel——timeline（12 类事件）+ artifacts 区。
- **交互**：`mergeTraceEvents` 按 iteration:seq 去重；"再次运行"按钮。
- **可选增强（AG-G stretch）**：接 `list_runs` 服务端历史（跨设备恢复）。

### F-03 HumanGate 写操作门禁 ✅
- **屏**：GatePanel——gate 卡片 + 批准/拒绝按钮。
- **v2 变化**：只有**四类写操作**进此屏，卡片加 kind 徽章：`merge`（主线入库）/ `deploy`（SSH 生产写）/ `permission`（跨组资源）/ `budget`（预算超限）。研究流不再出现 gate 卡片。
- **角色**：approver 见按钮；analyst 只读提示"由负责人审批"。
- **拒绝语义**：fail-closed——显示"拒绝即终止该写操作"提示。

### F-04 Memory 与组织能力目录 🔲（AG-G）
- **能力目录视图（新组件 `capability-catalog.tsx`）**：
  - 卡片列表：名称 / 接口面摘要 / **何时用** / **何时别自造**（高亮）/ 权限属组徽章 / source_commit；
  - 顶部搜索（走 FTS）；游客组被 Mask 的卡片不出现（后端过滤，UI 无感知）。
- **Memory 查询（新组件 `memory-query.tsx`）**：
  - 搜索框 + scope 过滤（组内/共享）+ 结果 snippet 高亮 + BM25 分数条；
  - 跨组读取被拒时显示"无权限"空态（对应 `MemoryPermissionError` fail-closed）。
- **常驻摘要**：由后端注入 run 指令（强保证），UI 不重复渲染全量目录。

### F-05 设置 / SSH 登录界面 🔶（AG-E 交付）
- **屏**：设置页 SSH 分区——**完整登录流，不是只读卡片**：
  1. **表单态**：host / user / 私钥（密码框，不回显不落盘，交后端 identity）；
  2. **连接态**：spinner + 逐行连接日志；
  3. **已连接态**：指纹摘要 + **组绑定徽章**（如"factor 组"）+ 断开按钮；
  4. **失败态**：具体原因（密钥被拒/host 不可达）+ 重试。
- **供应商分区**：Provider/Model/BaseURL 只读 readout（已实现 `settings-supplier.tsx`）。
- **约束**：登录前首页提交按钮置灰提示"请先完成身份认证"（fail-closed 的 UI 面）。

### F-06 外部评估器注册与部署适配 ✅（两处待补）
- **因子评估屏**：已实现；评估走外部 Quant Evaluator（经 eval_from_panel 桥），UI 不感知评估内部。
- **待补 1（AG-G）**：能力目录中出现 Quant Evaluator / Factor Engine / Data Access 卡片（即 F-04 数据）。
- **待补 2（AG-G）**：**契约违规提示卡**——Agent 检测到口径违规（如自算目标收益）时，会话内以 warning 卡片呈现（复用 risk_metrics 卡样式）："检测到自算目标收益，契约要求取 Horizon 表（后复权 t+1→t+2）"。

### F-07 跨组协同（CI 基建）
- **无新 UI**：PR 风控结论由 GitHub PR comment 承载（Multi-Agent Review issue 报告）；lens 不做 PR 视图。

### F-08 三条 Compose 流（组内工具）
- **无产品 UI**：引擎降级组内工具；PIT 屏保留（基本面组工具入口）。

### F-09 / P-08 Admin 中枢 🔲（AG-D 后端 + AG-G UI + AG-K 面板，仅 admin 角色可见导航项）
- **语义查询入口（新组件 `admin-console.tsx`）**：
  - 顶部自然语言输入："最近每组工作情况 / 某模块运行情况 / 各组错误记录"；
  - 结果卡片按 **组 → 人 → 状态** 分组聚合（数据：admin_list_runs）；每组一行摘要 + 展开明细。
- **错误沉淀视图**：时间线 + 按组过滤 + 错误类型标签（数据：admin_errors）。
- **GitGraph 面板（新组件 `gitgraph-panel.tsx`，AG-K，本轮交付——用户点名关键设计）**：
  - 一键查看组织**全部 repo 最新树状态**，有更新的节点**标红高亮**；
  - 数据：`admin_repo_status`（GitHub API 只读）；Admin 中枢页挂 GitGraph 入口按钮。
- **双类 Pop 提醒（AG-K，接入通知中心）**：
  - ① repo 有新提交 → pop；② 依赖库 **package 版本更新** → pop；全组可见，"不可能一直盯着 repo，pop 起提醒作用"；
  - 复用 `notifications.tsx` 铃铛 + badge 通道，pop 卡片带来源 repo/库名 + 跳转。
- **日常工作台定位**：Admin 把中枢页当日常任务管理界面打开（报告管理/任务管理入口 Q2 深化）。

### P-09 /deploy 黑盒部署（命令 + 审批，AG-H 后端 + AG-G 注册）
- **入口**：会话命令 `/deploy <代码路径或描述>`。
- **流程 UI**：提交 → GatePanel 出现 `kind=deploy` 审批卡 → 批准后执行 → 结果卡。
- **黑盒约束的 UI 面**：结果卡只显示"适配成功/失败 + artifact 路径 + 部署记录哈希"——**任何环节不出现 AlphaFlow 内部结构信息**；对 /deploy 之外的自然语言询问，Agent 侧拒绝透露（prompt 层约束）。

### P-10 方案面板（P0，AG-J 后端 + AG-G UI）
- **新组件 `solution-panel.tsx`（会话内嵌，/solution 命令唤起）**：
  - **状态机可视化**：`draft`（可讨论，黄点）→ 第 N 轮讨论（轮次计数 + 反馈输入框 + 历史版本链接）→ `frozen`（锁定徽章 + doc_hash 尾号）→ 一致性 verdict 徽章；
  - **verdict 徽章**：conformant（绿"实现符合方案"）/ deviation（黄，点击展开**偏离文件清单**）/ needs_human（红，需人裁）；
  - **draft 态输入区提示**："方案未冻结——代码生成工具不可用，请先讨论并冻结方案"（对应后端阶段限流）；
  - **方案文档**：可展开查看 `artifacts/solutions/<id>-v<n>.md`（只读渲染）。
- **命令**：`/solution <goal>` 创建；`/solution status` 查看当前状态。

---

## 5. 组件清单与落位

| 组件 | 文件（opencode-lens/packages/app/src/components/quantcode/） | 状态 | 交付方 |
|---|---|---|---|
| 品牌壳 + 五视图路由 | `panels.tsx` | ✅ | — |
| 指标卡族 | `metric-cards.tsx` | ✅ | — |
| 因子评估屏 | `factor-screen.tsx` | ✅ | — |
| PIT 屏 | `pit-screen.tsx` | ✅ | — |
| 通知中心 | `notifications.tsx` | ✅ | — |
| 供应商设置 | `settings-supplier.tsx` | ✅ | — |
| 角色解析 | `roles.ts` | ✅（approver 权威源 Q2） | — |
| SSH 登录 | `ssh-login.tsx` | ✅ | AG-E→AG-G（stub 待查询 surface） |
| 能力目录 | `capability-catalog.tsx` | ✅ | AG-G(W3) |
| Memory 查询 | `memory-query.tsx` | ✅ | AG-G(W3) |
| Admin 中枢 | `admin-console.tsx` | ✅ | AG-G/AG-K(W3-4，数据源 AG-D) |
| GitGraph 面板 | `gitgraph-panel.tsx` | ✅ | AG-K(W4，数据源 AG-D) |
| 方案面板 | `solution-panel.tsx` | ✅ | AG-G(W3，状态机 AG-J) |
| GatePanel kind 徽章 | `panels.tsx`（小改） | ✅ | AG-G(W3) |

---

## 6. i18n

- 新组件所有文案走 i18n key，**18 locale 全补齐**；中文文案以定版讨论用语为准（如"何时别自造""方案未冻结"）。
- `parity.test.ts` 断言 en 全 key 遍历，防漂移。

---

## 7. UI 验收断言（playwright，U 域编号）

- U1-A1: quantcode 渠道启动 → qc-shell 渲染且导航轨含上表视图（已有像素验证）。
- U1-A2 [新增]: SSH 登录四态流转：表单→连接中→已连接（组徽章）→失败（原因可见）。
- U1-A3 [新增]: P-10 draft 态下提交代码生成请求 → 输入区显示"方案未冻结"提示且不产生代码产物。
- U1-A4 [新增]: 方案面板 frozen 后出现 doc_hash 徽章；judge 返回 deviation 时徽章黄色且展开偏离文件清单。
- U1-A5 [新增]: admin 角色导航轨出现"Admin 中枢"，analyst/approver 不出现；admin 查询返回跨组分组卡片。
- U1-A9 [新增]: GitGraph 面板渲染全部 repo 树且更新节点标红高亮；repo 新提交与 package 版本更新两类 pop 均在通知中心可见且可跳转。
- U1-A6 [新增]: GatePanel 卡片按 kind 显示四类徽章；研究流 run 全程不出现 gate 卡片（对应 G2-A8(a) 的 UI 面）。
- U1-A7 [新增]: 能力目录卡片含"何时别自造"字段且游客组不见被 Mask 卡片；Memory 跨组查询显示"无权限"空态。
- U1-A8 [新增]: /deploy 结果卡不包含 AlphaFlow 内部结构关键词（黑盒断言的 UI 面）。

> 测试文件 [新增测试] `packages/app/.../quantcode/ui-spec.test.ts`（或分组件），随对应 agent 交付落盘。

---

## 8. 维护声明

- 本文随 FUNCTIONAL_SPEC 编号变更同步；新增 F/P 必须在 §2/§4 补 UI 规格，否则 spec 评审打回。
- 已实现组件改动须同步 §3/§5 状态列。
- Q2 归属项（OS 级通知、approver 权威源、报告/任务管理工作台深化）不在本轮 UI 验收范围。

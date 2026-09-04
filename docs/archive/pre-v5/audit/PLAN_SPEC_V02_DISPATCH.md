# QuantCode 调度计划 — FUNCTIONAL_SPEC v0.2.1 / PRD v2 对齐落地

> 版本：v2（2026-09-01，并入 P-10 方案先行工作流）｜Owner: Lead（主 Agent 编排）
> 依据：`specs/FUNCTIONAL_SPEC.md` v0.2.1、`docs/PRD.md` v2、`specs/governance/SPEC.md`（G2-A8）、`specs/data/SPEC.md`（D1-A11/A12）、`docs/audit/ROADMAP_LONGTERM.md` v2。
> 基线：P 仓 pytest **892 passed / 5 skipped**（AG-B 落地 TargetReturnView 后，主 Agent 亲测）；F 仓 **543 pass / typecheck 0e**（HEAD b26198bb6）。

---

## 0. 目标与范围

把 v0.2.1 定版从文档落到代码，闭合五组缺口：

| # | 缺口 | 来源断言/条目 | 优先级 |
|---|---|---|---|
| 1 | HumanGate 写操作收窄（产出门禁取消） | G2-A8 (a)(b)(c)，(d) SSH 部分 | P0 |
| 2 | 目标收益口径契约（target_return 视图） | D1-A11/A12 | P0 |
| 3 | P-07 蒸馏管线 + 首批四张能力卡片 + 权限 Mask + 常驻摘要 | P-07 验收草案 | P0 |
| 4 | P-08 Admin 组 + 跨组语义查询 + **GitGraph 面板与双类 pop（repo/package，用户点名关键设计）** | P-08 验收草案 | P0 |
| 5 | F-05 SSH 登录界面（lens） | F-05 验收 | P0（用户点名） |
| 6 | F-03 触发点② SSH 写生产环境 gate（kind=deploy） | governance §2.3 | P0 |
| 7 | **P-10 方案先行工作流**（SolutionDoc 状态机 + 阶段限流 + 一致性判定 + lens 方案面板） | P-10 验收草案 | P0 |
| 8 | P-09 /deploy 黑盒命令骨架（staging 适配器） | P-09 契约草案 | P1 |
| 9 | lens 集成：复用纪律指令、能力目录视图、Memory 查询界面（F-04 缺口）、skill 下拉真数据（F-01 缺口） | F-04/F-06/P-07 | P0 |
| 10 | ACCEPTANCE 矩阵 v0.2 重排 + F-07/F-08 维护模式标注 | 文档 | 收尾 |

**本轮不做**（有明确归属）：SSH 完整认证面 G4-B1（Q2）、AlphaFlow 真适配器（外部依赖：世杰，本轮只锁契约+staging 占位）、OS 级通知（pop 为应用内通知）、实时风控 G1-L3、P-08 报告/任务管理工作台入口（Q2 深化）、P-10 的 SKILL.md 自动注册（Q2 A4）。

**关键架构决策（本轮固化）**：
- Admin 是**角色不是组**——不进六研究组枚举，走 identity/permission 的 role 判定 + 跨组 scope 授权。
- **P-10 是流程阶段约束，不是权限门禁**——不新增 HumanGate 触发点；"冻结前代码工具不可用"用组 allowlist 的阶段性 tool 过滤实现（draft 态写类工具 deny），与 F-03 收窄语义正交。

---

## 1. 依赖图（决定波次）

```
AG-A(G2-A8 收窄) ──┬──→ AG-F(SSH 生产写 gate) ──→ AG-D(Admin+ssh_status 注册)
AG-B(target_return) ┘                              ↑
AG-E(SSH 登录 UI 壳, F仓) ──────────────────────→ AG-G(lens 集成)
AG-C(蒸馏管线+四卡片+Mask+常驻摘要, 独占 mcp_server) ┘
AG-J(P-10 方案先行引擎: 状态机+限流+judge 判定, 独占 agent_nodes/allowlist 段) ──→ AG-G(/solution 面板+命令)
AG-H(/deploy 骨架) ←── AG-F(gate 规则)
AG-D(repo/package 状态工具) ──→ AG-K(GitGraph 面板+双类 pop, 独占 panels.tsx W4 窗口)
全部 ──→ AG-I(总验收 + 矩阵重排)
```

热点文件独占窗口：`quantcode/mcp_server.py` = AG-C（W2）→ AG-D（W3）串联；lens `panels.tsx`/`instructions.ts` = AG-E（W1）→ AG-G（W3）→ AG-K（W4）串联；`runner/agent_nodes.py` 组 allowlist 段 = AG-J（W1）独占（AG-A 不碰 agent_nodes）。

---

## 2. 波次总表（4 波，11 个 subagent）

| 波 | Agent | 仓 | 一句话 | 核心断言 |
|---|---|---|---|---|
| W1 | AG-A | P | HumanGate 收窄适配 | G2-A8 (a)(b)(c) |
| W1 | AG-B | P | target_return 口径契约 | D1-A11/A12 |
| W1 | AG-E | F | SSH 登录界面 UI 壳 | F-05 验收（UI 侧） |
| W1 | AG-J | P | P-10 SolutionDoc 状态机 + 阶段限流 + judge 一致性 | P-10 验收草案 |
| W2 | AG-C | P | P-07 蒸馏管线 + 四卡片 + Mask + 常驻摘要 | P-07 验收草案 |
| W2 | AG-F | P | SSH 生产写 gate + ssh 分级 | governance §2.3 ② |
| W3 | AG-D | P | Admin 角色 + 跨组语义查询 + repo/package 状态工具 + ssh_status 注册 | P-08 验收草案 |
| W3 | AG-G | F | lens 集成五件套 + /solution + /deploy 命令注册 | F-04/F-06/P-10 缺口闭合 |
| W3 | AG-H | P | /deploy 黑盒骨架（staging 适配器） | P-09 验收草案（blocked 真接入） |
| W4 | AG-K | F | GitGraph 面板 + 双类 pop（repo/package，用户点名） | P-08 GitGraph/pop 验收 |
| W4 | AG-I | 双 | 总验收 + ACCEPTANCE v0.2 矩阵 | 全量回归 |

---

## 3. Agent 卡片

### W1（4 并行）

**AG-A｜G2-A8 HumanGate 写操作收窄（产出门禁三处清零）**（P 仓）
- 文件集：`schemas/risk_profile.py`、`runner/acceptance.py`、`tools/risk/risk_tools.py`（check_gate 语义）、`tools/common/request_human_review.py`（研报审阅去阻断化）、`tools/portfolio/gate.py`（组合 gate 语义）、`tests/test_human_gate_narrowing.py`[新]、受影响既有测试（`tests/test_risk_profile.py`、`tests/test_human_gate.py`、`tests/test_model_risk_handoff_e2e.py`、`tests/test_fundamental_human_gate.py`、`tests/test_fundamental_agent_flow.py`、`tests/test_portfolio.py`）、`specs/governance/SPEC.md`（仅 §6 verdict 回填）
- 交付：
  ① `RiskProfile.evaluate_verdict()` 越限返回 `fail`（不再 needs_human）；
  ② **产出门禁三处清零（2026-09-01 测试审计发现，一次收干净）**：风控越限（①）+ 研报 `request_human_review` 改非阻断审阅标记（写 review_requested 状态/事件，不再 interrupt——"产出人本来要看，报告平台承接"）+ 组合 `check_portfolio_gate` 越限改 verdict=fail 不再构造 interrupt payload；
  ③ 研究流零 gate interrupt 断言；
  ④ 四类写操作触发点保留的回归证据：merge（test_factor_merge 原样）、跨组 ask（permission 既有测试）、预算（**QUANTCODE_TOKEN_BUDGET 为硬约束阻断，非 interrupt**，按此语义断言）；
  ⑤ PR comment 链（risk-gate.yml 语义）无 interrupt 断言固化。
- 明确不动：`runner/human_gate.py` 状态机、permission/merge 触发点实现、CI workflow、`deploy_strategy` 的 needs_human（**生产写 gate，v0.2 保留**，test_strategy_tools 对齐不动）。
- 断言：G2-A8 (a)(b)(c)；(d) SSH 留 TODO（AG-F 落地后 AG-I 回填）。**verdict 回填 governance SPEC §6。**
- 测试策略（后置条款）：开发中只跑 `pytest tests/test_risk_profile.py tests/test_human_gate.py tests/test_human_gate_narrowing.py tests/test_factor_merge.py tests/test_portfolio.py tests/test_fundamental_human_gate.py -q` 这类直接相关文件，**禁止跑全量**；全量回归由主 Agent 波末执行。基线 892 passed / 5 skipped。

**AG-B｜D1-A11/A12 target_return 契约**（P 仓）
- 文件集：`schemas/data_contracts.py`、`tests/test_data_contracts.py`
- 交付：ReturnsDataset 增 target_return 视图——`Horizon∈{1,5,10,20}` 枚举校验（A11）+ 后复权标记（t+1→t+2）元数据必填（A12）；qs-cold 无该表 → 数据源接线标注 `ponytail:` blocked（staging 假数据不造，契约先行）。**verdict 回填 data SPEC §6。**
- 依赖：无。

**AG-E｜F-05 SSH 登录界面（UI 壳）**（F 仓）
- 文件集：`packages/app/src/components/quantcode/ssh-login.tsx`[新]（+测试）、`panels.tsx` settings 分支挂载、i18n 新 key ×18 locale
- 交付：完整登录流状态机——host/user/key 输入 → 连接测试 → 连接状态展示 → 组绑定显示（读 identity 映射）；数据层先走 client config + 后端占位（`ssh_status` 元工具 W3 才有，本期 fetch 失败显示未连接态 + `ponytail:` 注释），W3 由 AG-G 接真。
- 依赖：无。**本波独占 panels.tsx。**

**AG-J｜P-10 方案先行工作流引擎**（P 仓）
- 文件集：`schemas/solution_doc.py`[新] + JSON schema、`configs/solution_workflow.yaml`[新]（min_rounds=2/max_rounds=3/trivial 豁免开关）、`runner/solution_workflow.py`[新]（状态机 + 阶段限流钩子）、`runner/agent_nodes.py`（组 allowlist 段：draft 态 deny 写类工具）、`runner/judge.py`（方案↔代码一致性判定入口）、`tests/test_solution_workflow.py`[新]
- 交付：① `SolutionDoc` 契约（id/goal/rounds[]/status∈{draft,frozen,superseded}/acceptance_criteria[]/file_impact[]/doc_hash，`extra="forbid"`），存 `artifacts/solutions/<id>-v<n>.md` + Blackboard `shared.solutions.*`；② 状态机：draft →（≥min_rounds 讨论）→ frozen（用户显式确认），min_rounds 未满足冻结被拒，超 max_rounds 升级人裁；③ 阶段限流：draft 态写类工具（edit/write 文件类）deny，方案类工具（draft_solution/revise_solution/freeze_solution）allow，frozen 后解除——**复用组 allowlist 钩子，不新增 HumanGate 触发点**；④ 一致性判定：实现完成后 `runner/judge.py` 比对方案 ↔ 代码，verdict∈{conformant,deviation,needs_human}，偏离 file_impact 的改动必须列出；⑤ `/solution` 后端支撑：draft/revise/freeze/status 四动作经 `tools/solution/_register.py` 走标准 registry 通道注册，**全程不触碰 `quantcode/mcp_server.py`**（若实现中确认必须改 mcp_server，该子项移交 AG-D W3 窗口并在波末报告注明）。
- 明确不动：`runner/human_gate.py`、`runner/permission_engine.py`（AG-F 文件集）、`quantcode/mcp_server.py`（AG-C/AG-D 窗口）。
- 断言（P-10 验收草案四条）：下达功能目标后首轮只产方案不产代码（draft 态写工具调用被 deny）；min_rounds 未满足冻结被拒；frozen 后代码产出经 judge verdict 可复核；偏离 file_impact 的文件改动被报告。
- 依赖：无（judge/allowlist 均为既有底座的增量接线）。**本波独占 agent_nodes allowlist 段。**

### W2（2 并行）

**AG-C｜P-07 蒸馏管线 + 调研先行 + 首批六卡片**（P 仓，**独占 mcp_server**）
- 文件集：`docs/audit/ASSET_INVENTORY.md`[新]、`schemas/capability_card.py`[新] + JSON schema、`configs/capabilities.yaml`[新]、`runner/distill/`[新]、`runner/memory/service.py`（Mask 钩子）、`quantcode/mcp_server.py`、`tests/test_capability_cards.py`[新]、`tests/test_memory_mask.py`[新]
- 交付：
  0. **Step 0 资产调研（先行，禁止凭会议记忆手写卡片——2026-09-01 审计修正）**：gh 只读扫描 `HKUST-QUANT-SOCIETY` org（主 Agent 已初扫：69 repo，核心层 14 个活跃），产出 `docs/audit/ASSET_INVENTORY.md`——核心 repo 逐个一行（定位/语言/接口入口/活跃度/属组归属猜测），infra-*/test*/旧 quant-* 标注归档不蒸馏；卡片内容以各 repo 真实 README/API 为准；
  1. CapabilityCard 契约（id/name/**type∈{asset,contract}**/api_surface/when_to_use/when_not_to_reinvent/owner_group/source_commit/distilled_at，`extra="forbid"`）；
  2. 首批六张（从清单出发）：目标收益口径契约（TargetReturnView/v1，AG-B 已落）、`quant_evaluator`（**51 注册指标**）、`factor_engine`（DSL 460+ 算子）、`data_access`、`quant_platform`（DTO 集成契约层）、`alpha_flow`（/deploy 目标底层）；
  3. 权限 Mask：游客组不可见数据字段清单类卡片，fail-closed（复用 Memory GROUP 隔离底座）；
  4. **常驻摘要后端注入**：run 指令组装时附能力目录摘要（强保证，限长：id+name+when_to_use 一行式）+ FTS 细节检索（弱保证）；
  5. 蒸馏粒度守则写入卡片 schema 注释（蒸 API 面，不蒸实现）。
- 依赖：AG-B（口径卡片引用 TargetReturnView/v1）。

**AG-F｜F-03 触发点② SSH 生产写 gate**（P 仓，不碰 mcp_server）
- 文件集：`runner/permission_engine.py`、`configs/permissions.yaml`（`ssh.read: allow / ssh.dev.write: allow / ssh.prod.write: ask`）、`runner/server_ssh.py`（读写/环境分级判定）、`tests/test_ssh_gate.py`[新]
- **机制说明（2026-09-01 审计核验）**：`kind` 不是 schema 字段，是**调用点注入的 payload 约定**（merge_to_main 注 `payload["kind"]="merge"`、permission_engine 注 `"permission"`）——AG-F 同款注入 `"deploy"`，**无需改 schemas/human_gate.py**。budget 为 QUANTCODE_TOKEN_BUDGET 硬约束（阻断而非 interrupt），断言按硬约束语义写。
- 交付：① 生产环境写 → interrupt(kind=deploy)；读与开发环境写放行；分级判定纯函数可测；② `ssh_status` 只读元工具的**后端实现**（注册归 AG-D W3 窗口）。G2-A8 (d) 断言在本轮实现后由 AG-I 回填。
- 依赖：AG-A（收窄语义稳定）。

### W3（3 并行）

**AG-D｜P-08 Admin 角色 + 跨组语义查询**（P 仓，**独占 mcp_server**）
- 文件集：`quantcode/mcp_server.py`、`runner/metrics.py`（聚合查询）、`runner/admin_scope.py`[新]、`tests/test_admin_scope.py`[新]
- 交付：① Admin 判定（identity role / `QUANTCODE_ADMIN=1`，fail-closed）；② `admin_list_runs`（跨组按人/组/状态/错误聚合）、`admin_errors`（错误沉淀汇总）、`admin_blackboard_read`（跨组只读）；③ 非 Admin 调用 → PermissionError；④ 注册 `ssh_status` 元工具（AG-F 实现）；⑤ **`admin_repo_status` / `admin_package_updates`**（GitHub API 只读：全部 repo 最新树/最近提交/更新检测；各库 package 版本更新检测）——GitGraph 面板与双类 pop（AG-K）的数据源。
- 依赖：AG-C（mcp_server 串行）、AG-F。

**AG-G｜lens 集成五件套**（F 仓，**独占 panels.tsx/instructions.ts**）
- 文件集：`instructions.ts`、`panels.tsx`、能力目录视图组件[新]、Memory 查询组件[新]、方案面板组件 `solution-panel.tsx`[新]、i18n、`use-session-commands`（/solution、/deploy 注册）
- 交付：① 复用纪律常驻指令（"覆盖不全先问人，不许直接跳自造"进 buildResearchInstruction）+ **方案先行指令**（非平凡任务先产方案，Goal 输入映射 /solution 流程）；② 能力目录视图（读 list_capabilities）；③ Memory 查询界面接真实 FTS（**F-04 缺口闭合**）；④ skill 下拉接 `list_skills` 真目录（**F-01 缺口闭合**）；⑤ **方案面板**：SolutionDoc 状态机可视化（draft→讨论轮次→frozen→一致性 verdict 徽章；conformant 绿 / deviation 黄列出偏离文件 / needs_human 红）；⑥ `/solution` 与 `/deploy` 会话命令注册；⑦ AG-E 的 SSH 登录数据层接线（ssh_status）。可选项：F-02 接 list_runs 服务端历史。
- 依赖：AG-E、AG-C、AG-D（ssh_status 已注册）、AG-J（SolutionDoc 契约 + /solution 后端）。

**AG-H｜P-09 /deploy 黑盒骨架**（P 仓）
- 文件集：`tools/deploy/__init__.py` + `adapter.py` + `staging_adapter.py` + `_register.py`[新]、`tests/test_deploy_blackbox.py`[新]
- 交付：① adapter 接口契约（输入=已调试代码路径+manifest，输出=部署结果，**不含 AlphaFlow 内部结构**——黑盒断言：输出/日志/错误信息 grep 不到底层实现细节）；② staging 适配器占位（真实适配器 blocked 待世杰）；③ 部署动作经 permission `ssh.prod.write: ask` → HumanGate kind=deploy（复用 AG-F 规则）；④ evidence chain 留痕挂钩（复用既有 runner/evidence.py）。
- 依赖：AG-F。

### W4（串行收尾）

**AG-K｜P-08 GitGraph 面板 + 双类 pop**（F 仓，**独占 panels.tsx** W4 窗口）
- 文件集：`gitgraph-panel.tsx`[新] + `notifications.tsx`（pop 接入）+ `panels.tsx`（导航注册 + Admin 中枢挂 GitGraph 按钮）+ i18n + 组件测试
- 交付：① **GitGraph 视图**——全部 repo 最新树状态，有更新的节点**标红高亮**（数据：`admin_repo_status`）；② **双类 pop**：repo 有新提交 → pop；依赖库 package 版本更新 → pop，全组可见（"不可能一直盯着 repo，pop 起提醒作用"，应用内通知中心承载）；③ Admin 中枢页挂 GitGraph 入口按钮。
- 依赖：AG-D（两个数据源工具）、AG-G（panels.tsx 窗口串行于其后）。

**AG-I｜总验收 + 矩阵重排**（只读测试 + 唯一写入=ACCEPTANCE 文件）
- 双仓全量：P 仓 pytest+ruff（预期 ≥950 passed）；F 仓 typecheck+test:unit。
- `docs/audit/ACCEPTANCE_WAVE123.md` 重排：新增 P-07/P-08/P-09/P-10 行、F-05 回 ✅（登录界面）、F-03 ✅（G2-A8 全系）、F-07 标"CI 基建维护模式"、F-08 标"组内工具适配层（代码保留）"、D1-A11/A12 与 G2-A8 verdict 回填对应 SPEC §6。
- 产出验收报告（含本轮 11 agent 的 PonyTail 审计记录）。
- **P-10 用户路径冒烟**：下达一个功能目标 → 收到方案文档 → 一轮反馈修订 → 显式冻结 → 观察代码产出 → 一致性 verdict 徽章可见；另测 trivial 豁免与 min_rounds 拒冻结两条负路径。

---

## 4. 调度纪律（继承既有约定）

1. **subagent 禁止一切 git 操作**；commit/push 只由主 Agent 在波末做。
2. **文件集互斥**：卡片所列文件不相交；热点文件（`mcp_server.py`、`panels.tsx`、`instructions.ts`、`agent_nodes.py` allowlist 段）按波次串联独占。
3. **每 agent 注入 PonyTail 全文**：懒阶梯（YAGNI→复用→stdlib→最短 diff）、删除优先、已知捷径标 `ponytail:` 注释；执行型用 general-purpose。
4. **并发上限 2**（W1 实测：4 并行触发 user concurrency limit，2 个 agent 被取消）——同波分两批派发，先 2 后 2。
5. **事实断言必须回实物核验**（2026-09-01 审计教训：会议口头"60 指标"实为 quant_evaluator 的 51 注册指标）——凡写入任务书的数量/路径/接口名，先 ls/grep/gh 只读核验再写。
6. **波间抽查**：每波结束主 Agent 跑受影响仓测试，绿了才放行下一波；W2/W3 之间加一次 commit 落库（防长链无检查点）。
7. **跨仓一致性**：组枚举本轮两仓都不动（Admin=角色）；instructions 双端（后端注入摘要 + 前端纪律文本）由 AG-C/AG-G 分工，plan 明确归属防重复实现。
8. **验收即用户路径**：AG-I 除单测外执行两条手动冒烟——①lens 登录 → 选组 → 能力目录可见 → 提交研究 → 无多余 interrupt → /deploy 触发审批；②P-10 全流程（方案→讨论→冻结→代码→一致性 verdict）。
9. **P-10 语义边界**：所有 agent 不得把阶段限流实现为 HumanGate interrupt；AG-J 与 AG-A 的文件集零交集保证两条线不互相污染。
10. **测试后置（2026-09-01 用户指令）**：开发过程中 subagent 只跑自己文件集直接相关的测试文件，**禁止跑全量 892**（耗时且无增量信息）；全量回归 = 主 Agent 波末抽查 + AG-I 终验。

---

## 7. 既有测试契合度审计（2026-09-01，87 文件 / 897 用例 vs v0.2.1）

| 分类 | 文件 | 裁决 |
|---|---|---|
| **老产出门禁语义（与新红线冲突）** | test_risk_profile / test_human_gate / test_model_risk_handoff_e2e / test_fundamental_human_gate / test_fundamental_agent_flow / test_portfolio（gate 部分）+ 3 处实现（risk_profile、request_human_review、portfolio/gate） | **AG-A 收窄清零**（见 AG-A 卡片②） |
| **对齐 v0.2 无需动** | deploy_strategy needs_human（生产写 gate ✓）、test_factor_merge（merge gate ✓）、permission/budget/dedupe/subagent/memory/blackboard/data_contracts/evidence/replay/metrics 等底座全套 | 保留 |
| **业务层测试（策略/期权/基本面 flows+tools+spec）** | test_strategy_* / test_options_* / test_fundamental_tools 等 | 保留为**组内工具回归**（F-08 引擎代码保留）；不删不改（除 AG-A 文件集内两个） |
| **demo/历史快照级** | test_day5_jerry_demos / test_demo_bridge / test_demo_scenario_4 / test_real_llm_integration（skip-gated） | 保留不投入；AG-I 终验时列清单请示是否删除 |
| **待新增（随各 agent）** | test_human_gate_narrowing / test_data_contracts 增量（已落）/ test_capability_cards / test_memory_mask / test_solution_workflow / test_ssh_gate / test_admin_scope / test_deploy_blackbox / lens UI 组件测试 | 各 agent 交付 |

---

## 5. 风险与缓释

| 风险 | 缓释 |
|---|---|
| `evaluate_verdict` 语义变更波及 E2E（needs_human 断言） | AG-A 文件集显式包含三个既有测试文件；波末全量回归 |
| mcp_server 双 agent 冲突 | 独占窗口：AG-C(W2) → AG-D(W3)，禁止越窗 |
| Admin 语义被误解为第七组 | plan 固化"角色非组"决策；AG-D 测试断言组枚举不变 |
| AlphaFlow 适配器无真实规格 | staging 占位 + 契约/黑盒断言锁定；验收标 blocked（外部依赖） |
| SSH 登录 UI 无后端认证面（G4-B1 在 Q2） | W1 只做 UI 壳+状态机（占位数据源），W3 接 ssh_status 只读；真认证 Q2 |
| 常驻摘要膨胀上下文 | 摘要限长（卡片 id+name+when_to_use 一行式），细节走 FTS |
| 蒸馏物过期 | 卡片带 source_commit/distilled_at；CI 校验留 Q2（ROADMAP R7） |
| **P-10 限流误做成权限门禁**（v2） | AG-J/AG-A 文件集零交集；plan 明示"流程阶段约束非 HumanGate 触发点"；AG-J 测试断言 research 流零 interrupt |
| **方案文档沦为形式**（每轮敷衍通过） | min_rounds=2 硬约束 + 冻结需用户显式确认 + judge 一致性判定让"方案↔代码"偏差可量化；超 max_rounds 升级人裁 |
| **agent_nodes.py 三方争用** | AG-J(W1) 独占 allowlist 段；AG-A 明确不动 agent_nodes；波末回归 |

---

## 6. 完成口径

- G2-A8 (a)(b)(c)(d)、D1-A11/A12 全 pass 且 verdict 回填 SPEC §6；
- P-07 验收草案三条可演示：问"目标收益怎么取"→指向契约；游客组检索不到被 Mask 卡片；摘要常驻每次 run 上下文；
- P-08：Admin 跨组查询成功、非 Admin 被拒；
- **P-10 验收草案四条全 pass**：目标下达后首轮只产方案不产代码；min_rounds 未满足冻结被拒；frozen 后代码经 judge 一致性 verdict 可复核；偏离 file_impact 的改动被报告；
- F-05：登录界面完整流程可走通（连接状态+组绑定展示）；
- F-01/F-04 两处历史缺口闭合（skill 真目录、Memory 真查询）；
- 双仓全量测试绿；ACCEPTANCE 矩阵以 v0.2 编号重排后无回退。
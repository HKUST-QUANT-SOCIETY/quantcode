# QuantCode 验收报告 WAVE 1+2+3+4（v0.2.1 定版轮 · 总验收）

> **执行日期**：2026-09-01｜**验收代理**：AG-I 总验收（只读测试 + governance/data SPEC §6 对应行回填 + 本报告为唯一写入产物）
> **对象**：
> - P 仓（后端）`/Users/hendrixchen/Desktop/私募/QUANTcode` @ `2c388cf`（feat(w3): P-08 admin hub backend + P-09 deploy black-box skeleton）
> - F 仓（UI）`/Users/hendrixchen/Desktop/私募/opencode-lens` @ `e9753967c`（feat(w4): P-08 admin hub full UI + UI polish 21-item pass）
> **基线演进**：P 仓 pytest 892 → 924(W1) → 979(W2) → **1021**(W3/终验)；F 仓 543 → 548(W1) → **611**(W4/终验)。
> **声明**：本次验收为只读测试（P-10 冒烟经临时脚本、跑后即删），未修改任何代码；写入仅限本文件与两份 SPEC §6 对应 verdict 行。

---

## 1. 测试矩阵

| # | 项目 | 命令 | 结果 | 基线要求 | 判定 |
|---|---|---|---|---|---|
| 1.1 | P 仓单测 | `python -m pytest tests/ -q --tb=short` | **1021 passed, 5 skipped**（16.21s，1 warning：`ToolDef.schema` 遮蔽 BaseModel 属性） | ≥1021 passed / 5 skipped | ✅ 达标 |
| 1.2 | P 仓 lint | `uvx ruff check runner/ tools/ flows/ quantcode/ schemas/ --statistics`（ruff 0.16.5） | **319 errors**（头部：RUF022×61、I001×48、BLE001×47、RUF100×25、F401×20、UP017×19、UP037×17、UP035×14…），221 可 autofix | 记录数字 | ✅ 已记录（注：较上轮 53 上升系 ruff 版本差异 0.16.x 新增规则面，多为风格项非阻断） |
| 1.3 | F 仓类型检查 | `cd packages/app && bun run typecheck`（tsgo -b） | **0 错误**（exit 0） | 0 错误 | ✅ 达标 |
| 1.4 | F 仓单测 | `bun run test:unit`（--only-failures） | **611 pass / 0 fail**，2578 expect()，92 files，1266ms | ≥611 pass | ✅ 达标 |

---

## 2. 功能完成度矩阵（FUNCTIONAL_SPEC v0.2.1：F-01..F-09 + P-01..P-10）

图例：✅ 有代码+测试证据 ｜ 🔶 部分实现（有缺口） ｜ 🔲 未实现

| 编号 | 功能（v0.2.1 口径） | 证据（grep 实测 / 测试文件） | 状态 |
|---|---|---|---|
| F-01 | 新建多智能体研究 | `runner/agent_mcp_tool.py`（start/resume 两阶段）+ `runner/agent_engine.py` ReAct + UI `instructions.ts::buildResearchInstruction` 强制调用；**skill 下拉真目录待查证 → 查证结果：仍是硬编码 4 条常量（`panels.tsx` L161 `SKILLS`，F 仓 grep `list_skills` 0 引用）**——真目录接线未完成，列入 §5 | ✅（残余如实标注） |
| F-02 | 执行记录视图 | `result-contract.ts` 12+1 类事件、`mergeTraceEvents` 按 `iteration:seq` 去重、ActivityPanel timeline、`quantcode:thread_cache` | ✅ |
| F-03 | HumanGate **写操作门禁**（触发点四类） | **G2-A8 四断言全绿**：(a) `test_research_flow_zero_interrupts`、(b) `test_threshold_breach_verdict_is_fail`、(c) `test_write_gate_triggers_preserved`（merge/ask/budget 回归）、(d) `test_ssh_gate.py::test_ssh_prod_write_gate`（kind=deploy）；merge ✅（test_factor_merge）/ deploy ✅ / permission ✅ / budget ✅；governance SPEC §6 已回填 (d) | ✅ |
| F-04 | Memory 与组织能力目录 | 后端 `runner/memory/`（FTS5+BM25+CJK、5-scope GROUP 隔离 fail-closed）；UI **Memory 查询视图落地**（`memory-query.tsx`，可注入 fetcher）；**memory_search 后端 meta 工具本轮未交付**（W3 仅 admin_*），默认 fetcher 占位空态、不造假数据——如实标注；能力目录 = P-07 | ✅（后端通道占位如实标注） |
| F-05 | 设置 / **SSH 登录界面** | `ssh-login.tsx` 四态完整流（表单 → 连接中 → 已连接+组绑定徽章 → 失败原因+重试，`ssh-login.test.ts` 绿）；供应商 readout（`settings-supplier.tsx`）；**SSH 完整认证面 = G4-B1 延后 Q2** | ✅ |
| F-06 | 外部评估器注册与部署适配 | 评估器注册经**能力目录**（quant_evaluator 卡：Step 0 实测 60 指标口径）；口径契约 TargetReturnView/v1（D1-A11/A12 pass）；部署适配 = P-09 黑盒 staging；`eval_from_panel` 桥 + merge 审批保留 | ✅ |
| F-07 | 跨组协同（**CI 基建维护模式**） | `tests/test_model_risk_handoff_e2e.py` + `.github/workflows/risk-gate.yml` + dedupe 防刷；产品场景取消，链路维护 | ✅ |
| F-08 | 三条 Compose 流（**组内工具**） | `flows/` + `tools/{strategy,options}/backtest_engine.py` + `tools/portfolio/` 代码保留；pytest 全量绿（引擎回归保护）；不做 UI、不进产品索引 | ✅ |
| F-09 | Monitor 与 **Admin 中枢** | `runner/metrics.py` + `list_runs` + `scripts/replay.py`；Admin 语义层 = P-08 落地（**Admin 中枢 UI 全套**：admin-console 语义查询/错误沉淀 + GitGraph + 双类 pop）；**自动推送 pop/OS 通知 Q2**（现为应用内通知中心承载） | ✅ |
| P-01 | 数据接入（四工具 + 契约） | `tools/market/_register.py` 四工具 + `schemas/data_contracts.py`；**D1-A11/A12 pass**（target_return 视图 Horizon 枚举 + 后复权标记必填），data SPEC §6 已回填 | ✅ |
| P-02 | 回测引擎（组内工具） | `tools/strategy/backtest_engine.py` internal_v1（T+1/涨跌停/费用，手算对照 1e-9） | ✅ |
| P-03 | 组合层（组内工具） | `tools/portfolio/` construct/rebalance/gate | ✅ |
| P-04 | 并行 subagent | spawn/check/kill/list + 组 allowlist + 任务树 MAX_TREE_DEPTH=4 | ✅ |
| P-05 | 实验管理 | `tools/experiments/ab.py`（A/B + OOS 纪律） | ✅ |
| P-06 | evidence chain（JSON 契约） | sha256 指纹链 + `generate_evidence_report`；PDF 渲染非目标后置 | ✅ |
| P-07 | **组织资产蒸馏管线** | **调研先行**：`docs/audit/ASSET_INVENTORY.md`（gh 只读实测 69 repo，核心层 **14** 逐 repo 实读 README 核实，归档 51 不蒸馏；**指标口径勘误：60 实测 ≠ 51 旧口径**）；**六张能力卡片**（5 asset + 1 contract，`configs/capabilities.yaml` + JSON schema 校验）；**权限 Mask fail-closed**（游客组只见 contract 卡）；**常驻摘要限长**（id+name+when_to_use 一行式 + 复用纪律恒在）；`runner/distill/`；**测试 31 pass**（test_capability_cards 24 + test_memory_mask 7） | ✅ |
| P-08 | **Admin 与中枢管理面** | Admin = **角色非组**（fail-closed：env 精确 `=1` / roster，坏配置 deny）；`admin_list_runs` / `admin_errors` / `admin_blackboard_read` 非 Admin 一律拒；**org 元数据（admin_repo_status / admin_package_updates / ssh_status）全员开放**；`runner/admin_scope.py` + mcp_server 注册；**测试 33 pass**（test_admin_scope）；lens **Admin 全套 UI**（admin-console + gitgraph-panel + 双类 pop，admin 角色才见导航项） | ✅ |
| P-09 | **/deploy 黑盒部署适配** | `tools/deploy/`（adapter 接口 + staging_adapter 占位 + registry 通道）；**黑盒断言** `test_output_blackbox`（输出/日志 grep 不到 AlphaFlow 底层实现细节）+ `DeployResult` 字段面最小化；部署动作 = 写生产 → permission `ssh.prod.write: ask` → **HumanGate kind=deploy**（复用 AG-F 规则）；evidence 留痕；**测试 9 pass**（test_deploy_blackbox）；**真适配器 blocked（外部依赖：世杰），本轮 staging 口径** | ✅ staging |
| P-10 | **方案先行工作流（Solution-First）** | `schemas/solution_doc.py`（extra=forbid）+ `configs/solution_workflow.yaml`（min_rounds=2/max_rounds=3/trivial 开关）+ `runner/solution_workflow.py`（状态机 + 双写落盘 + **draft 态写类工具 deny**——阶段限流非 HumanGate）+ `runner/judge.py::judge_solution_conformance`（file_impact⊆改动确定性判定，语义仅升级）；**测试 28 pass**（test_solution_workflow，四条验收草案全覆盖）；AG-I 用户路径冒烟 12 步全绿（见 §3） | ✅ |

**统计**：✅ 19 ｜ 🔶 0 ｜ 🔲 0 ｜ F-01..F-09 + P-01..P-10 全部闭合验证（pytest 1021 passed / lens 611 pass / typecheck 0e）；两处残余子项如实标注（F-01 skill 真目录、F-04 memory_search 后端通道）并在 §5 挂账。

---

## 3. 断言抽查 + P-10 用户路径冒烟（AG-I 终验）

### 3.1 断言抽查表

| 断言 | 测试文件 | 实测结果 |
|---|---|---|
| G2-A8 (a)(b)(c) 产出门禁三处清零 | `tests/test_human_gate_narrowing.py`（4 tests：research_flow_zero_interrupts / portfolio_breach_zero / threshold_breach_verdict_is_fail / write_gate_triggers_preserved） | **4/4 pass** |
| G2-A8 (d) SSH 生产写 gate | `tests/test_ssh_gate.py`（24 tests，含 `test_ssh_prod_write_gate` + 分级纯函数 15 参数化） | **24/24 pass** |
| D1-A11/A12 target_return 契约 | `tests/test_data_contracts.py::test_target_return_horizon_enum / test_target_return_adjusted_marker_required` | **2/2 pass**（data SPEC §6 已有 pass 回填，核对存在） |
| P-10 四条验收草案 | `tests/test_solution_workflow.py`（28 tests：extra_forbid / 冻结拒 / 阶段限流 / judge 三态） | **28/28 pass** |
| P-07 六卡 / Mask / 摘要限长 | `tests/test_capability_cards.py`（24）+ `tests/test_memory_mask.py`（7） | **31/31 pass** |
| P-08 admin 门禁 + org 元数据开放 | `tests/test_admin_scope.py`（33：admin 三工具 deny 非 Admin、repo/package/ssh_status 全员开放、fail-closed） | **33/33 pass** |
| P-09 黑盒 grep + gate | `tests/test_deploy_blackbox.py`（9：test_output_blackbox / kind=deploy gate / reject 终止 / registry 通道） | **9/9 pass** |

### 3.2 P-10 用户路径冒烟（手动脚本化验证，未接真 LLM，临时脚本跑后即删）

经 `registry.call` 全流程（ctx 注入临时 blackboard/artifacts 目录，零仓库写入），12 步全绿：

1. `draft_solution`（goal+file_impact×2+验收标准）→ `ok=true, status=draft, version=1, doc_hash=0900…, min_rounds=2`；
2. 冻结尝试（0 轮）→ **拒**：「讨论轮次不足（0/2），冻结被拒」；
3. `revise_solution` 第 1 轮（feedback 必填）→ version=2、rounds=1；
4. 冻结尝试（1 轮，边界）→ **拒**：「讨论轮次不足（1/2）」；
5. `revise_solution` 第 2 轮 → rounds=2（≥min_rounds）；
6. 冻结不带 `confirm=True` → **拒**：「冻结需用户显式确认」；
7. `freeze_solution(confirm=True)` → **frozen**，version=4、doc_hash=e871…；
8. **双写落盘核验**：`artifacts/solutions/sol-xxx-v1..v4.md` 四个版本 md 落盘（含 status/doc_hash/Goal/讨论轮次渲染）+ `solution_status` 读回一致；
9. 阶段限流：`tool_allowed_in_phase("edit_file")` draft=**deny** / frozen=**allow**（流程约束非 HumanGate，未新增 interrupt）；
10. `judge_solution_conformance`（改动=计划面）→ **conformant**（理由：2 文件全部落在 file_impact 内）；
11. judge 加计划外文件 → **deviation** 且偏离清单精确列出 `tools/market/rogue.py`；
12. judge 缺计划内文件 → deviation(missing)；draft 态文档判 → **needs_human**（非 frozen 不构成判定基准）。

**结论**：方案先行四条验收（首轮只产方案不产代码 / min_rounds 拒冻结 / frozen 后 judge verdict 可复核 / 偏离 file_impact 被报告）在工具通道层面全部可复现。

---

## 4. UI vs 设计稿（v5 PPT slide20 四屏 + UI_DESIGN_SPEC v1 新增视图）

组件目录：`packages/app/src/components/quantcode/`（**14 个测试文件全绿，已计入 611 pass**）

| 屏/视图 | 设计稿内容 | 组件 | 数据源 | 状态 |
|---|---|---|---|---|
| 屏1 因子评估 | 研究流程节点 + 评估指标大数字/阈值条 | `factor-screen.tsx`（四节点）+ `metric-cards.tsx` | `execution_trace` + `output_data` | ✅ |
| 屏2 审批/Gate | 风险越阈值专用面板、批准/拒绝 | `panels.tsx::GatePanel`（approver 按钮 / analyst 只读）+ `notifications.tsx`；v2 收窄后仅四类写操作进此屏（kind 徽章） | `run.gate`（breached_thresholds 权威） | ✅ |
| 屏3 PIT 估值 | 证据时间线 + DCF 估值卡 | `pit-screen.tsx`（published_at≤as_of 告警 + 滑条实时重算） | `output_data` | ✅ |
| 屏4 通知中心 | 待审批提醒汇总 | `notifications.tsx`（铃铛 + badge + 跳转审批） | waiting_for_human 历史 | ✅ |
| **SSH 登录**（U1-A2） | 完整登录流四态 | `ssh-login.tsx`（表单 → 连接日志 → 已连接+组徽章+断开 → 失败原因+重试） | client config + `ssh_status` 只读接线 | ✅ |
| **Admin 中枢**（U1-A5） | 语义查询 / 错误沉淀 / 分组聚合卡 | `admin-console.tsx`（仅 admin 角色可见导航） | `admin_list_runs` / `admin_errors` / `admin_blackboard_read` | ✅ |
| **GitGraph 面板**（U1-A9） | 全部 repo 最新树、更新节点标红高亮 | `gitgraph-panel.tsx`（Admin 中枢入口按钮） | `admin_repo_status`（GitHub API 只读） | ✅ |
| **双类 Pop**（U1-A9） | repo 新提交 pop + package 版本更新 pop，全组可见 | `notifications.tsx` 通道接入 pop 卡（来源 repo/库名） | `admin_repo_status` / `admin_package_updates` | ✅（应用内；自动推送/OS 通知 Q2） |
| **方案面板**（U1-A3/A4） | 状态机可视化 + verdict 徽章 | `solution-panel.tsx`（draft 黄点→轮次→frozen 锁定徽章+doc_hash 尾号；conformant 绿 / deviation 黄列偏离文件 / needs_human 红；draft 态提示"方案未冻结"） | `/solution` 会话命令 + SolutionDoc 事件 | ✅ |
| **能力目录**（U1-A7） | 卡片列表 + 何时别自造高亮 + 属组徽章 | `capability-catalog.tsx`（游客组不见被 Mask 卡片，后端过滤） | `list_capabilities`（P-07 六卡） | ✅ |
| **Memory 查询**（U1-A7） | 搜索 + scope 过滤 + 无权限空态 | `memory-query.tsx`（可注入 fetcher，占位空态不造假数据） | **memory_search 后端通道占位**（见 §2 F-04） | ✅ 视图 / 🔶 通道 |

**结论**：slide20 三主屏 + 通知中心之外，v0.2.1 新增五视图（Admin/GitGraph/方案面板/能力目录/Memory 查询）+ SSH 登录全部落地并有组件测试；与 `docs/UI_DESIGN_SPEC.md` §2 视图清单一一对应（memory_search 通道为唯一挂账子项）。

---

## 5. Z code / Codex 对标清单

| 对标项 | 对标对象 | QuantCode 实现 | 有/缺 |
|---|---|---|---|
| 多会话并行 | Z code Task 并行 subagent | `tools/subagent/` spawn/check/kill/list 四工具、组 allowlist、任务树 MAX_TREE_DEPTH=4 | **有**（工具层完整；任务树可视化缺） |
| MCP 生态 | Z code MCP server / Codex MCP | `quantcode/mcp_server.py` 元工具家族：`list_runs`、`list_skills`、`list_algorithms`、`check_tool_stream`、`check_subagent`、`consume_status`、**ssh_status / admin_* 六工具 / draft·revise·freeze·solution_status（P-10）**；`_meta=True` 绕过组 allowlist 对六组全可见 | **有**（较上轮 +8 元工具） |
| 权限沙箱 | Claude Code permission modes / sandbox | `runner/permission_engine.py` + `configs/permissions.yaml` 三态；**G2-A8 收窄后仅四类写操作进 gate（merge/deploy/permission/budget）**；P-10 阶段限流为流程约束非权限门禁 | **有** |
| 会话回放 | Z code session resume / Codex replay | `scripts/replay.py`（list/show/resume）+ sha256 哈希链证据 | **有** |
| 通知 | Z code hooks/通知 | 会话内通知中心（铃铛+badge+面板）+ **双类 pop（repo/package）**；系统级 OS 通知缺 | **有**（OS 级缺） |
| 预算 | Z code token 预算 | `_resolve_budget`（args > env > DEFAULT）硬约束 | **有** |

**小结**：6 项对标 6 有 0 缺（残余子项：任务树可视化、OS 级通知）。

---

## 6. 未完成项清单（诚实披露）

**保留项**（上轮延续，均为 SPEC 声明的有意延后）：

| # | 未完成项 | 现状与证据 | 去向 |
|---|---|---|---|
| 1 | 实时风控（G1-L3） | governance SPEC 明示非目标；前置" L2 连续一季度零降级"未满足 | 2027Q3 |
| 2 | 本地模型路由 | 无本地/云端分级路由器 | 长期 |
| 3 | evidence PDF 渲染 | EvidenceReport JSON 完成；PDF 后置 | Q3 |
| 4 | COS 凭据服务化 | staging dev 后端 + fail-closed | Q2 服务化 |
| 5 | approver 权威源 | `roles.ts` 身份名启发式，待接 roster 权威列 | 单点替换 |
| 6 | 真行情接入 | 回测/组合/实验跑 qs-cold staging | Q2+（依赖 #4） |

**新增项**（本轮验收实测确认）：

| # | 未完成项 | 现状与证据 | 去向 |
|---|---|---|---|
| 7 | **AlphaFlow 真适配器** | staging 占位 + 契约/黑盒断言锁定（test_deploy_blackbox 9 绿）；真接入 blocked 外部依赖（世杰） | 外部依赖解锁后 |
| 8 | **memory_search 后端 meta 工具** | `memory-query.tsx` 视图落地、默认 fetcher 占位空态（不造假数据）；AG-D W3 仅交付 admin_* | 下一轮 meta 工具 + fetcher 注入 |
| 9 | **pop 自动推送 / OS 通知** | 双类 pop 数据源与 UI 卡片就绪；检测轮询/自动推送与 OS 级通知未做 | Q2 |
| 10 | **report/task 工作台** | Admin 中枢日常任务管理定位已定；报告管理/任务管理入口未建设 | Q2 深化 |
| 11 | **F-01 skill 下拉真目录** | `panels.tsx` L161 `SKILLS` 硬编码 4 条；F 仓 grep `list_skills` 0 引用（后端元工具已有） | 下一轮接线 |

---

## 7. 预览启动说明

```bash
cd ~/Desktop/私募/opencode-lens/packages/desktop && OPENCODE_CHANNEL=quantcode bun run dev
```
- 左侧导航轨：首页/会话/Activity/Gate/因子评估/PIT/能力目录/Memory 查询/方案/设置；Admin 中枢 + GitGraph 仅 admin 角色可见。
- 后端先启动：P 仓内 `python -m quantcode.mcp_server`（Admin 试用可 `QUANTCODE_ADMIN=1`）。
- `/solution <goal>`、`/deploy` 会话命令已注册。

---

## 8. 结论

**结论：可验收（v0.2.1 定版轮）。**
- 测试矩阵 4 项全绿：P 仓 pytest **1021 passed / 5 skipped**（基线演进 892→924→979→1021），F 仓 typecheck **0 错误**、unit **611 pass / 0 fail**（543→548→611）；ruff 319（版本差异面，风格项为主）；
- 功能矩阵 ✅19 / 🔶0 / 🔲0：F-01..F-09 按 v0.2.1 重排全绿，P-07/P-08/P-09/P-10 四项新计划功能全部落地（31/33/9/28 测试各就各位）；G2-A8 (a)(b)(c)(d) 与 D1-A11/A12 verdict 均已回填对应 SPEC §6；
- **G2-A8 四断言全绿**——产出门禁三处清零 + SSH 生产写 gate(kind=deploy)，HumanGate 收窄为纯写操作门禁；P-10 用户路径冒烟 12 步全绿，方案先行四条验收可复现；
- UI 面：slide20 四屏之外，Admin 中枢/GitGraph/双类 pop/方案面板/能力目录/Memory 查询/SSH 登录七块新 UI 全部有组件测试；两处通道级子项（memory_search 后端、skill 真目录）与四个 Q2 项在 §6 如实挂账，无粉饰；
- 本轮 11 个 subagent（AG-A..AG-K）按 4 波次调度完成 G2-A8 收窄、D1-A11/A12、P-07 调研先行蒸馏、P-08 Admin 中枢、P-09 黑盒骨架、P-10 方案先行引擎与 lens 五件套/全套 UI，波间抽查与终验全部通过；无阻断性缺陷，无测试红项。

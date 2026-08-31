# QuantCode 偏差登记册（设计 vs 实现 vs UI）

> 生成：2026-08-30。方法：30 个只读审计 subagent（A01–A12 PRD 功能缺口 / B13–B24 UI 设计偏差 / C25–C30 冗余删减），方法论 PonyTail（YAGNI、删除优先、复用优先）。
> 原始发现 ≈ 363 条，去重合并为 **34 个根因簇**。每条簇保留原始编号（如 A04-1）以便回溯。
> 路径约定：P = 主仓 QUANTcode；F = 桌面端 fork（~/Desktop/私募/opencode，分支 feat/quantcode-day5-ui）。
> 行号以审计当日工作树为准，修复时如已漂移以文件内容为准。

## 状态更新 2026-08-30（修复轮收官）

> 逐簇标注是否已修复。✅=已实现（本轮合入工作树，commit 待补）；部分✅=关键面已修、遗留面如实列出；🔲=未动。测试基线：P 仓 pytest 702 passed / 5 skipped；桌面端 bun test 490 pass。详细逐条任务状态见 docs/Day5_TaskList.md §0 与 docs/Day5_Feature_Checklist.md。

### P0 簇

| 簇 | 状态 | 说明 |
|---|---|---|
| P0-1 桌面六面板数据管线断裂 | ✅ | run_agent tool result → `updateQuantCodeTrace` 接线完成；桌面端演进为七 Tab 面板（compose/tasks/gate/schema/memory/resume/monitor） |
| P0-2 Model→Risk handoff 双重断裂 | ✅ | import 修复 + session 固定 `PROJECT_SESSION_ID` + key 归一 `shared.model_entries.` 前缀（`runner/blackboard_keys.py`）；端到端测试 `tests/test_model_risk_handoff_e2e.py` 锁死 |
| P0-3 风控数据造假 + CI 假门禁 | 部分✅ | `calc_risk` 支持 returns 参数算真 VaR/MaxDD/Sharpe（无 returns 标 `_is_stub`）；CI workflow 用 stub data、scenario 可 workflow_dispatch、诚实标注；fixture→真 PR diff 未做 |
| P0-4 HumanGate 桌面端无闭环 | ✅ | gate 面板 Approve/Reject 按钮 → run_agent resume（promptAsync）；且有命令行等价 `scripts/replay.py resume` |
| P0-5 供应商绑定 UI 违反定案 | ✅ | 官方供应商/OAuth/免费模型入口已删除；唯一绑定面=第三方统一表单（显示名/Base URL/API Key）+「获取模型列表」实时拉 /models |
| P0-6 安装包用户链路不可用 | 部分✅ | 配置已收敛（MCP 链路只读 env：QUANTCODE_API_KEY/QUANTCODE_MODEL_*，config.json 主链路已删）+ key 进链路（proxy）；安装包打包未做（desktop 仍限 dev 模式） |
| P0-7 组身份 SSH 绑定零实现 | 真实化✅ | 最小闭环：`QUANTCODE_SSH_KEY_FINGERPRINT` → `.opencode/authorized_groups.yaml` 映射（`python -m quantcode.identity add/list`）→ 无绑定降级 env QUANTCODE_GROUP（warning）→ 有绑定无指纹 fail-closed（`QUANTCODE_ALLOW_UNAUTH=1` 逃生门）。SSH 完整认证面仍🔲 |
| P0-8 replay / 自动 Checkpoint 全缺 | 最小✅（原文标"🔲"） | `scripts/replay.py`（list/show/resume risk:gate）+ thread_id 含 task_id 段（`make_thread_id` 可传）+ 双 checkpoint db 统一 `.quantcode/checkpoints.db`；自动 Checkpoint：>70% 快照 / >90% 重建（`runner/agent_nodes.py`，字符/4 近似 token，`QUANTCODE_CONTEXT_TOKENS` 可调），messages reducer 翻倍 bug 已修 |
| P0-9 自进化"四头生产、零头消费" | 部分✅ | judge/Goal 消费端已建（桌面 `/goal` → run 结束 judge verdict met/partial/missed/unevaluated → `apply_judged_session` 回填 RLHF）；监控消费端已建（`.quantcode/metrics.jsonl` 完成钩子 + `list_runs` 只读 MCP tool + 桌面 Monitor 面板）；`dream_events` 仍未接入（🔲） |
| P0-10 Compose 承诺 6 流仅 2 注册 | ✅ | 六流全部注册 FLOW_REGISTRY（`runner/compose_executor.py` 统一 import）：factor:autoeval、risk:gate、model:submit、strategy:compose、options:compose、fundamental:research；契约归一层（黑板 key/session 归一）落地；SchemaTask 接线仍最小 |
| P0-11 主仓死重三刀 | ✅ | quantcode/schemas/v1.py、DEPRECATED 函数、pipelines/ 空壳等死重已清（阈值/mocks 单源化：阈值唯一来源 `runner/acceptance.py` + `schemas/risk_profile.RiskThresholds`） |
| P0-12 settings.open 双注册冲突 | ✅ | 统一单点注册 |

### P1 簇（有动作的）

| 簇 | 状态 | 说明 |
|---|---|---|
| P1-1 gen_schema 输出进 FactorSpec 必炸 | ✅ | operators / estimated_runtime_seconds / forward_return_horizon 契约字段补齐，失败降级 `_fallback` |
| P1-4 factor/risk/flows 双轨合并 | ✅ | 已删并（阈值/ mock 单源化，runner 为唯一实现侧） |
| P1-5 Blackboard 语义缺口 | ✅ | WritePolicy + MemoryService.get 组权限修复落地 |
| P1-6 幽灵 tool 清理 | ✅ | allowlist 中幽灵 tool 已清 |
| P1-11 trace 渲染 | ✅ | 事件渲染增强落地 |
| P1-12 组切换 UI | ✅ | 六组 segmented 切换接线 |

其余 P1 簇（P1-7/8/9/13/14 等）未在本轮修复，状态维持审计原文；P1-2（merge_to_main/check_factor_gate）仍为🔲（PRD 承诺未落地）。

### P2 簇

P2-1（README/USER_MANUAL 失真 12 处）由本轮文档任务完成（✅，见本仓 README.md + docs/USER_MANUAL.md 修改）。其余 P2 项维持原状。

### 本轮仍未完成项清单（不放走）

- 🔲 P0-3 遗留：CI fixture→真 PR diff
- 🔲 P0-6 遗留：安装包打包 / bundled Python sidecar
- 🔲 P0-7 遗留：SSH 完整认证面（最小闭环之外）
- 🔲 P0-9 遗留：dream_events 接入
- 🔲 P0-10 遗留：SchemaTask 接线仍最小
- 🔲 P1-2：merge_to_main / check_factor_gate
- 🔲 compose SKILL frontmatter 自动注册
- 🔲 P1-7/8/9/13/14 其余 P1 簇、P2-3..8

---

## 统计

| 优先级 | 簇数 | 说明 |
|---|---|---|
| P0 | 12 | 对外承诺失真 / 核心链路断裂 / 安装包不可用 |
| P1 | 14 | 闭环缺口 / 双轨冗余 / 安全缺口 |
| P2 | 8 | 死配置 / 文案 / 阈值口径 |

---

## P0 簇（12 个根因）

### P0-1 桌面六面板数据管线断裂（最大单点）
- 原始 ID：A01-1, A07-1, B16-1, B17-2, B19-1, B23-1, B24-8
- 设计：F/packages/app/src/components/quantcode/README.md:66-78（Step 2 监听 run_agent tool result）；QuantCode_Design.md:472-483
- 现状：`updateQuantCodeTrace`（panels.tsx:47）全 fork **零调用**；六面板永远停在"等待 run_agent 执行…"。commit 26ac8605d 自述 Step 2 未做。
- 处置方向：在 tool-result 渲染层接线：识别 run_agent MCP 结果 → 调 updateQuantCodeTrace。这是其他多个面板缺陷（P0-4/P1 簇）的前置。

### P0-2 Model→Risk 跨组 handoff 双重断裂
- 原始 ID：A03-1, A03-2, A03-6, A08-1, A08-5, A10-9
- 现状：① `runner/agent_mcp_tool.py:222` import 不存在的 `tools.blackboard.blackboard_service`（真实在 runner/blackboard.py 且无 get_blackboard_service），import 失败被 except 静默吞掉——risk 组永远收不到 pending_risk_reviews；② 写侧 session_id=thread_id、读侧=project_id/DEFAULT，主键对不上；③ SKILL.md 指引裸 key vs 写侧自动加 `shared.model_entries.` 前缀。
- 处置方向：修 import + 统一 session/key 归一化一层；加一条端到端 E2E 测试锁死。

### P0-3 风控数据造假 + CI 假门禁
- 原始 ID：A04-1, A04-2, A04-3, A04-4, A05-3（strategy 同型）
- 现状：calc_risk 两场景硬编码常量（statistics_stub.py:31-57），CI 固定 `--scenario normal` 用 fixture，从未读 PR diff，阈值在 CI 恒不 breach → HumanGate 在 CI 不可达；PRD 四段链路实际只有两段。以 "formal risk profile" 名义把虚构数据发真实 PR。
- 处置方向：calc_risk 接真实收益序列（哪怕从回测工件来）；CI 改 read-only dry-run 或明确标注 demo；阈值口径与 PRD 对齐。

### P0-4 HumanGate 审批在桌面端无闭环
- 原始 ID：B13-（否）B17-1/2/3/5/6/7/8, B16-2/8, B19-2, B23-3
- 现状：面板只渲染 reasons（无 risk_metrics/risk_profile/gate_id/decision_schema），**无 approve/reject 按钮**；唯一 resume 途径=用户手打 JSON 或让 LLM 代调 MCP（违反 fail-closed）；main 会话区对 waiting_for_human 无特化渲染。payload 本身完整（runner/human_gate.py）。
- 处置方向：HumanGatePanel 加按钮 → run_agent(resume, decision)；主对话区加 gate 卡片特化渲染。

### P0-5 供应商绑定 UI 违反产品定案（官方流未删）
- 原始 ID：B13-1/2/3, B14-2/3/4, B15-1/5/7/8/9, B20-03
- 定案：仅第三方供应商，统一「Base URL + API Key + 模型名称」一个表单，删官方直连/OAuth。
- 现状：popularProviders 硬编码 8 个官方 id（use-providers.ts:8-17）；settings-v2/providers.tsx:184-221 Connect → dialog-connect-provider（OAuth 全套 :173-207, 548-595）；"查看全部"开官方全量清单；DialogConnectProvider/DialogSelectProvider 共 8+5 个引用点（B14-2/3 全景清单）。
- 处置方向：删除两对话框 + 全部官方引导文案；改造 dialog-custom-provider 为唯一绑定面 + 第三方预设表（DeepSeek/StepFun/Kimi/GLM/OpenRouter 等，含 baseURL/模型预设，无凭据）；~45 死 i18n key × 18 locale 清理（B21）。

### P0-6 安装包用户链路 0% 可用
- 原始 ID：B24-1/2/3/4/5/6/7/12
- 现状：quantcode-lens-ui workflow 不在 fork 任何分支（由 PR 触发的 CI 产物）；桌面端 chdir 到 homedir + config loader 不认 opencode.local.jsonc → 六个 MCP server 拉不起来；安装包不含 Python 运行时/quantcode 包 → `python3 -m quantcode.mcp_server` 必 ModuleNotFoundError；config.json 的 key 进不了 `_get_model`；start 脚本与 USER_MANUAL 全部假设双仓源码环境。
- 处置方向：见 plan 模式第一批（配置收敛）+ 后续打包决策（bundled sidecar 或"仅 dev 模式"明确化）。

### P0-7 组身份 SSH 绑定零实现且无安全兜底
- 原始 ID：A01-2, A09-2, A09-3, C30-3/4
- 现状：设计=SSH key→组映射（Architecture_Spec §2.1）；实现=纯环境变量/文件，无任何认证；设计文档自身也没有凭据安全条款（双重缺失）。另有 set_group.py 幽灵引用、4 条并行解析路径。
- 处置方向：至少先做收敛（args.group > env，删文件通道）；SSH/MAC 绑定另立项。

### P0-8 replay / 自动 Checkpoint 全缺（PRD 标 P0 的未做，但清单虚标 ✅）
- 原始 ID：A06-1/2/3/4, A07-2, A11-8
- 现状：`quantcode replay` 无实现无入口（pyproject 无 console_scripts）；context>70%/90% 触发器零代码；thread_id 时间戳生成无法按 task_id 反查；双 checkpoint db 互不相通（checkpoints.db vs opencode-checkpoints.db）；compose_executor thread_id 秒级碰撞。
- 处置方向：P1 实现最小 replay（thread_id 带 task_id + list/replay MCP/CLI）；Day5 清单虚标 ✅ 改回 🔲。

### P0-9 自进化子系统"四头生产、零头消费"
- 原始 ID：A11-1/2/3/5/6/7, A07-6
- 现状：rlhf_data.jsonl 1678 条无消费者；apply_session_verdict 全仓零调用、reviewer 恒 None；distill 草案无注册路径（artifacts/distill 不存在）；dream_events.jsonl 从未产生；dream auto 模式把 mock 假教训写进 global memory；checkpoints.db 主源实际读出来是 bytes repr。
- 处置方向：Week2 不接消费端则整体标记待删（ponytail：删除优于空转）；至少阻断 mock 写 global memory。

### P0-10 Compose 编排层：承诺 6 流仅 2 注册，契约层零接线
- 原始 ID：A10-1/2/3/5, A10-8
- 现状：FLOW_REGISTRY 只有 factor:autoeval + risk:gate；ComposeTask/BlackboardState 契约在编排层零消费；thresholds config.yaml 文件不存在（acceptance.py docstring 承诺）；schema_validator 生产零调用；quantcode/schemas/v1.py 是 851 行孤儿重复。

### P0-11 主仓死重三刀（可立即执行）
- 原始 ID：C29-1/2/3, A10-8
- quantcode/schemas/v1.py 851 行零 import；agent_mcp_tool.py 两个 DEPRECATED 函数 235 行 + 3 个 skip 测试；pipelines/ 空壳树（4×1 行 __init__ + comment_hello 零引用，需同步 pyproject packages.find）。

### P0-12 设置页 settings.open 双注册冲突
- 原始 ID：C25-1/2
- 双注册（layout.tsx:940-944 vs settings-dialog.tsx:32-40）胜者随页面漂移；prod 构建侧栏走 v1、Cmd+, 走 v2，同一应用两套设置壳。
- 处置方向：统一 settings-dialog.tsx 单点；v1 七文件删除（见 P2 删减表）。

---

## P1 簇（14 个根因，简表）

| 簇 | 原始 ID | 一句话 |
|---|---|---|
| P1-1 spec 契约断裂：gen_schema 输出进 FactorSpec 必 ValidationError（operators/estimated_runtime_seconds 缺） | A02-2 | factor 主链在校验处断 |
| P1-2 factor 缺 check_factor_gate / merge_to_main 工具（PRD 承诺） | A02-1, A09-7 | 验收-合并闭环无处落地 |
| P1-3 autoeval 恒 mock（无 endpoint 配置段），"真API"名不副实 | A02-3, A09-1, A10-7 | mock 指标恰好满足阈值 |
| P1-4 factor/risk/flows 双轨合并（runner 为唯一实现侧，净删 ~900+ 行） | C26-1/2/3/7, C27-1/3/4/7/12, C28-1/2/3/5/6 | 阈值三套、mock 两套、幽灵 MCP server |
| P1-5 Blackboard 语义缺口：WritePolicy 全忽略、GROUP_APPEND 反语义、MemoryService.get 绕组权限、5-scope 只实现 2、requester_group 缺省全放行 | A08-2/3/4/6/7/8/9 | 安全语义未落地 |
| P1-6 幽灵 tool（search_memory/read_file/write_file/bash）在 3 组 allowlist，registry 静默跳过 | A01-7, C28-7 | 死配置误导 |
| P1-7 三组业务数据造假：extract_financial 按 ticker hash、calc_greeks 经验公式、run_strategy_backtest 公式推导 | A05-1/2/3 | 产品核心数字非真实计算 |
| P1-8 permission ask/deny 引擎未实现（render_report/deploy/publish 承诺 ask 均无），人审靠 Agent 自觉 | A01-6, A05-4/7 | fail-closed 缺失 |
| P1-9 PRD P1 承诺未达：任务树、subagent 监控、Goal+Judge、跨组通知中心、token budget、memory 只读 tool、truncate reducer 接线 | A07-3/4/5/7/8/9/10/11 | 已过 Week2 期限 |
| P1-10 Memory/Blackboard/checkpoint 前端可视化全无（面板静态占位，只读 tool 未建） | B16-3/4, B17-7, B18-1..6, B23-5/13 | 契约降级方案也未实现 |
| P1-11 trace 渲染：10 类事件 8 类裸渲染、非流式、全局单例跨会话泄漏、risk_metrics 从不渲染 | A01-5, B16-5/9/10, B19-3/4/5/6 | 接线后的第二层缺口 |
| P1-12 组切换 UI 零接线：setQuantCodeGroup 无调用、徽章恒 "model"、契约的 6 server 只有 1 | B16-6, B23-2, B24-13 | Day5 硬验收未达 |
| P1-13 路由分派靠中英文关键词子串（"pb-roe"/"期权"），TS 控制平面零参与 | A01-3/4, B23-10 | 静默错路由 |
| P1-14 明文 key + 配置文件三重错（F/opencode.local.jsonc 重复 environment 键、python vs python3、plugins 复数、F/.gitignore 不覆盖 *.local.jsonc） | B24-9/10, C30-1/2/5/6 | 泄漏面+死配置 |

## P2 簇（8 个根因，简表）

| 簇 | 原始 ID | 一句话 |
|---|---|---|
| P2-1 README/USER_MANUAL 失真 12 处：示例 IC/IR 数字、产物路径、jerry_demos CLI、/export、GLOSSARY、IR>1.5 自动合并、24h 超时 | A12-2..13, A02-6/9, C26-6 | 文档 404 或与实现矛盾 |
| P2-2 工具名/文档漂移：gen_factor_schema vs gen_schema、trigger_risk_flow 双口径、read_pr diff 承诺 | A02-8, A03-7/10, A05-8 | 调设计名找不到工具 |
| P2-3 阈值口径三套并存（risk 0.15/0.8 vs PRD 0.20/0.30；factor 0.02 vs 0.03） | A04-7, C26-4/5, C27-6 | 验收不可信 |
| P2-4 静默降级未标注：render_report typst 失败仍 typst_used=true、build_vol_surface mock 单点、demo fixture | A05-5/12/14, A05-15(citation 默认12) | 验收方不可辨真伪 |
| P2-5 杂项死代码：session_review 模块、DreamScheduler、demo_bridge（README 未承诺降级用途） | C29-4/5/6 | 归档或删 |
| P2-6 设置 v1 七文件删除 + i18n 死键（wayland/showNavigation 先迁 v2） | C25-3..12 | -1400 行 |
| P2-7 getting-started 引导在仅第三方世界行为失真（paid() 判断+无持久化 dismissed） | B20-4 | 引导卡最需要时消失 |
| P2-8 杂项：.mimosa 未 ignore、根目录投资人材料散落、usage-exceeded 死流程、图标 synthetic | B14-5/8, B15-14, C29-7/8 | 清理 |

---

## PonyTail 删减表（可独立执行，不依赖功能修复）

**删除（净 -2500+ 行 / -144MB）**

| 对象 | 证据 | 动作 |
|---|---|---|
| vendor/mimo-code（144MB，git 零跟踪，对 fork 零增量——B22 全量对比） | B22-1..9 | `rm -rf`，需要时从上游重拉 |
| quantcode/schemas/v1.py（851 行零 import） | C29-1 | 删 |
| _start/_resume_risk_gate_mode + 3 skip 测试（235+60 行） | C29-2, C26-2 | 删 |
| pipelines/ 空壳树 + pyproject packages.find 同步 | C29-3, A10-4 | 删 |
| flows/risk_gate.py shim + test_risk_flow.py（import 改 runner） | C26-3/7, C28-6 | 删，CI 脚本 import 改 1 行 |
| tools/risk_stub.py / risk_stub_mcp.py / calc_risk_stub 注册与 allowlist 行 | C28-1/3/5 | 删（阈值统一 RiskThresholds） |
| factor 三 *stub.py + 开关 + reload hack（默认注册改真版，真版自带降级） | C27-2/3/10/11 | 删（~190 行） |
| runner/factor_autoeval_demo.py 重复节点（351 行；tests 重定向，C27-12） | C27-4 | 二选一：删 demo 并迁移 memory 集成测试 |
| session_review.py + DreamScheduler（或 cli 二选一） | C29-4/5 | 删 |
| dialog-connect-provider.tsx / dialog-select-provider.tsx + 全部引用改道（B14-2/3 清单） | P0-5 | 删 + 预设化改造 |
| 官方 i18n 死键 ~45 × 18 locale + parity.test 强化 | B21-1..5/10/11/12 | 删 |

**归档**：根目录投资人材料收口 docs/investor/ 或移出工作区（C29-7）；demo_bridge.py（C29-6）。

**保留（核心真实资产）**：runner/ 引擎全家、blackboard、human_gate、memory、routing、MCP server、model 组 5 工具、fundamental pit_rag/Chroma、options BS/IV、github_comments + risk-gate CI、dream/cli。

---

## 与下一阶段的衔接（plan 模式修复批次建议）

1. **批次 A（先让本地链路通）**：C30 收敛（组身份 4→2、key 3→1、删幽灵 set_group 注释、F/.gitignore 补行、删 F/opencode.local.jsonc*）→ 支持 `bun run dev:desktop` 端到端联调。
2. **批次 B（删减表全量）**：P0-11 + P1-4 + P2-6 + vendor/vendor 之外全部死代码。
3. **批次 C（UI 与定案对齐）**：P0-5 供应商绑定重构（预设表 + 统一表单 + i18n），P2-6 同步。
4. **批次 D（面板接活）**：P0-1 接线 → P0-4 审批按钮 → P1-11 渲染增强 → P1-12 组切换。
5. **批次 E（后端闭环）**：P0-2 handoff 修复、P0-8 最小 replay、P1-1/2/5/6 语义修复。
6. **批次 F（文档真伪）**：P2-1/2/3 全量对齐。
## A3 配置单源 + 算法注册表（2026-09-01，ROADMAP Q3 A3 + 架构决策 3）

- 三处硬编码阈值收敛为 `configs/acceptance.{factor,risk}.yaml` 单源：`runner/acceptance.py`（RUNNER factor-eval 0.03/0.5/0.8/2.0、risk-gate 0.15/0.8/0.6 与 RiskThresholds 同源）、`flows/factor_autoeval._report_verdict` 同值删写。缺文件/缺键回退代码默认并 warning 一次，数值=现默认，行为零变化；新增 `runner/config_loader.py`（lru_cache、`QUANTCODE_CONFIG_DIR` 覆盖）。
- `configs/algorithms.yaml` 算法注册表首例 + `tools/algorithms/` 执行端（`_register.py` 三工具 + `score_demo.py` 真实 demo：Blackboard `shared.datasets.panel/*` → 等权 rank top_n 资产表）；`mcp_server` 以 `_meta` 通道注册 list_algorithms 等，六组 MCP server 的 tools/list 可见、不进组 allowlist（平台级工具，与 list_runs/list_skills 同款）。

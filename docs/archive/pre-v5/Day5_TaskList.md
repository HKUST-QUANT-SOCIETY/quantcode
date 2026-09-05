# Day 5 工作目标

> **里程碑**：IDE 初步上线 + PRD/Design 功能全部实现 + investor demo。
> **工作方式**：目标制。给功能目标 + 验收标准，怎么实现你自己判断。卡 30 分钟拉群。
> **⚠️ 重要：Lead 已在 Day 5 开工前提前完成大量基础工作，`git pull origin main` 后再看各自任务。**
>
> **状态更新 2026-08-30**：本轮（Wave 5）已将下列任务实现并合入工作树，文中已实现项标 ✅；对应 commit 待补（本轮禁止 git 操作，commit 后回填）。仍未实现项（SSH 完整认证面、compose SKILL frontmatter 自动注册、merge_to_main 等）保持 🔲 如实标注。

---

## 0. Lead 已完成项（无需重复，直接基于此开工）

以下工作已合入 **main**（2026-07-10），对应 commit `0549e7c` ← `71fcba8`：

| 完成项 | 说明 | 影响谁 |
|---|---|---|
| ✅ **PR#25 解冲突合入 main** | 俞高磊的 run_agent + stream trace；引擎升级为确定性 HumanGate；旧 `gate_tools` 参数已移除 | 全员 |
| ✅ **opencode.jsonc 补 risk/factor MCP server** | 6 组命名 server 齐全（原缺 risk/factor，demo 会失败） | 俞高磊 / 杨欣琳 |
| ✅ **引擎修复**：skill_loader vendored 路径、550 passed / 0 failed | 21 个测试从失败变绿 | 尹一帆 |
| ✅ **三处文档漂移修复** | §5.5 LangGraph 表述、§3.4 仓库结构、§4.5 Memory/Blackboard scope 区分 | 全员参考 |
| ✅ **trigger_risk_flow 机制定型** | Architecture §3.2 更新：Blackboard 队列标志（方式2）已文档化 | 陈镇鸿 |
| ✅ **Day5_Feature_Checklist.md** | PRD/Design P0 逐条结论 + 分组决策文档（`docs/Day5_Feature_Checklist.md`） | 全员 |
| ✅ **Distill 原型**（`dream/distill_prototype.py`） | 识别重复 tool 序列 → 候选 SKILL.md 草案，5 测试全通 | 尹一帆 |
| ✅ **Dream 跨 trace 聚合**（`dream/dream_prototype.py`） | 升级为聚合所有 rlhf 记录而非只读最后一条 | 尹一帆 |
| ✅ **IDE 骨架**：`/compose` 命令 + 六面板组件 | opencode fork `feat/quantcode-day5-ui` 分支；接口契约见 `docs/IDE_Python_Interface_Contract.md` | 俞高磊 |
| ✅ **demo bridge**（`runner/demo_bridge.py`） | Python CLI 降级路径，`--auto-approve` + `--jsonl` 两种模式，5 测试全通 | 全员 demo 兜底 |

---

## 1. Day 5 五大目标（更新后）

1. **IDE 上线**：`/compose` 真触发、6 组可切换、HumanGate 暂停点可见、六面板可用
2. **6 组 Compose 流全通**：每组至少一个真实 idea 进、valid artifact 出（PR#22/PR#24 先合入）
3. **跨组流端到端 demo 可演**：model→risk（含人审）是 demo 主菜
4. **PRD/Design 功能对照清单**：`Day5_Feature_Checklist.md` 已出，各降级项在 handoff 标注
5. **investor demo + 交付物齐全**：录屏 + PPT + handoff + Quick Start

---

## 2. 俞高磊 · IDE 前端集成（收尾 2 件 TS 事）

**背景**：Lead 已完成 `/compose` 命令注册、六面板组件（`packages/app/src/components/quantcode/panels.tsx`）、Python 侧接口契约。俞高磊只差最后两步把面板接进 OpenCode。

**从哪开始**：checkout opencode fork 的 `feat/quantcode-day5-ui` 分支，详细接法见 `packages/app/src/components/quantcode/README.md`。

**剩余任务**（2026-08-30：1/2/4 已完成，commit 待补）：

1. **✅ `session-side-panel.tsx` 加 QuantCode Tab**
   - 在 Tabs 数组里加一项，挂 `<QuantCodePanel />`（从 `@/components/quantcode/panels` import）
   
2. **✅ 监听 `run_agent` tool result → 更新面板**
   - 在 tool result 渲染处，若 `tool_name === "run_agent"` 且 result 含 `execution_trace`，调 `updateQuantCodeTrace(result)`

3. **🔲 compose SKILL frontmatter 自动注册**：flow 注册仍由 `runner/compose_executor.py` 统一 import，SKILL.md frontmatter 自动声明/注册未实现。

4. **✅ 桌面七 Tab 面板**（compose/tasks/gate/schema/memory/resume/monitor）：gate 面板 Approve/Reject 按钮 → run_agent resume；组切换六组 segmented；供应商绑定第三方统一表单 + 获取模型列表。

**Day 5 不做**（P1，Week 2）：跨组通知中心、Dog Food 面板、Subagent 监控 UI、人工编排 YAML 编辑器——handoff 标注。

**验收**：
- [x] OpenCode 启动 → `/compose "测 PB-ROE 因子"` 真触发 factor Agent，主对话区流式显示推理过程（commit 待补）
- [x] 七面板 Tab 可见（Compose 视图 / 任务树 / gate / Schema 卡片 / Memory / Resume / Monitor）（commit 待补）
- [x] HumanGate 场景：超阈值暂停 → gate 面板显示 reasons + thread_id，点 Approve 后恢复（commit 待补）
- [x] 六组 segmented 切换均可触发（commit 待补）

---

## 3. 尹一帆 · 6 组 Agent 全通收口 + Dream/Distill 接 IDE

**背景**：引擎已升级（PR#25 合入），`AgentRunner` 不再需要 `gate_tools` 参数（已移除）；`gate_tools=["check_gate"]` 的旧调用会报错，请清掉。Distill 原型 + Dream 补强已由 Lead 完成，尹一帆的任务是让它们在 IDE 里**可触发**。

**剩余任务**：

1. **6 组 ReAct 全通**
   - 逐组跑 `AgentRunner(group=X).run(task="...", skill_name="...")` ≥3 步自主推理
   - 关键：strategy/fundamental/options 三组走通用 AgentRunner 路径（不需要单独线性 flow）
   - 每组产出 artifact 通过 schema 校验

2. **Dream 接 IDE**
   - 在 OpenCode 里注册 `/dream` slash 命令（参考俞高磊的 `/compose` 做法）
   - 触发后调 `dream.dream_prototype.run_dream()`，产出 ≥1 条 memory 在 Memory 浏览器可见

3. **引擎稳定性**
   - demo 场景下跑通（无 context 爆 / 无挂死）
   - 死循环检测自动中止可演示（demo 场景 4）

**验收**：
- [ ] 6 组各跑通一个完整流程，artifact 通过 schema 校验
- [ ] Dream 在 IDE 可触发，产出 ≥1 条 memory 可检索
- [ ] demo 场景引擎稳定

---

## 4. 杨欣琳 · risk demo 场景打磨 + HumanGate UI 对齐

**背景**：risk 引擎已升级为确定性 HumanGate（不依赖 LLM 是否主动调工具），`check_gate` 返回 `requires_human=True` 时**必定** interrupt。PR#20（Day 4 ReAct readiness）请 rebase 到 main 后合入。

**剩余任务**：

1. **PR#20 rebase + 合入**：`git rebase origin/main`，确认 `gate_tools` 参数已移除（引擎不再用它）

2. **model→risk 跨组链路跑通**
   - 整条链：read_pr（真 GitHub）→ ModelSpec → write_blackboard → trigger_risk_flow → risk Agent 被触发 → 风控计算 → VaR 超阈值 → interrupt 暂停 → approve → 真写 PR comment
   - 与陈镇鸿对齐触发时机（陈负责 model 侧写 Blackboard，杨负责 risk 侧读取并处理）

3. **✅ HumanGate UI 对齐**（commit 待补）：gate 面板按钮 → `run_agent(resume, decision="approve/reject", thread_id=...)`（桌面 gate 面板 Approve/Reject）

4. **✅ 双场景验证**:正常（不超阈值，直接出 PR comment）+ 高风险（超阈值，人审后出 PR comment）；`calc_risk` 支持 returns 参数算真 VaR/MaxDD/Sharpe，无 returns 时结果标 `_is_stub`；CI workflow 用 stub data 且 scenario 可 workflow_dispatch，已诚实标注（fixture→真 PR diff 未做）

5. **✅ dedupe 验证**：同一 commit 触发两次，GitHub 上只有 1 条 comment

6. **✅ handoff 归一**（commit 待补）：session 固定 `PROJECT_SESSION_ID`、key 归一 `shared.model_entries.` 前缀（`runner/blackboard_keys.py`），端到端测试 `tests/test_model_risk_handoff_e2e.py` 锁死

7. **✅ replay**（commit 待补）：`scripts/replay.py list / show / resume risk:gate`，thread_id 含 task_id 段，checkpoint db 统一 `.quantcode/checkpoints.db`

**验收**：
- [ ] model→risk 人审场景端到端可演（含真 PR comment）
- [ ] HumanGate 暂停/approve 在 IDE UI 正确呈现
- [ ] 双场景可切换演示
- [ ] dedupe 现场验证（同 PR 触发 2 次 → GitHub 只 1 条 comment）

---

## 5. 陈镇鸿 · model→risk 跨组流 demo + Blackboard 可视化

**背景**：`trigger_risk_flow` 机制已定型为 Blackboard 队列标志（Architecture §3.2 已更新），数据链是 `write_blackboard(key="model.pr_X_spec")` → `trigger_risk_flow(blackboard_key=...)` → `shared.pending_risk_reviews`。PR#24（real GitHub read_pr + model-to-risk handoff）请 rebase 后合入。

**剩余任务**：

1. **PR#24 rebase + 合入**：`git rebase origin/main`，注意 `AgentRunner` 不再有 `gate_tools` 参数

2. **model→risk 整链跑通**
   - read_pr（真 GitHub PR） → extract_metadata → generate_model_spec → write_blackboard → trigger_risk_flow → 确认 `shared.pending_risk_reviews` 有新条目
   - 与杨欣琳对齐：model 侧写完 Blackboard 后，risk Agent 能读到并处理

3. **Blackboard 跨组可视化**（与俞高磊对齐）
   - 面板里能显示"model 写了 `shared.model_entries.model.pr_X_spec`，risk 读到了"
   - 跨组权限隔离：model 写 GROUP scope，risk 组读不到（演示隔离）

**验收**：
- [ ] PR#24 合入 main
- [ ] model→risk 跨组流录屏可演（5 步全部完成，见 SKILL.md 强制规则）
- [ ] Blackboard 数据流在 IDE 可见（谁写了什么、谁读了什么）
- [ ] ModelSpec + RiskProfile 双 schema 校验通过

---

## 6. Lead · factor demo 收口 + 验收闭环

**背景**：`match_main` 和 `gen_schema` 已有 fixture-backed 实现（契约稳定，backend 可换），`Day5_Feature_Checklist.md` 已产出，三大模式契约全部落地。Lead Day5 剩余核心任务是把 factor 链路从 stub 升级到真 LLM + 真 AutoEval，跑出完整 demo。

**剩余任务**（2026-08-30 收口状态）：

1. **✅ match_main 真 LLM 收口**（commit 待补）：`tools/factor/match_main.py` 真 LLM 读主线代码签名（SSH 主线读取见 `runner/server_ssh.py`，`pip install 'quantcode[ssh]'`，`config.example.json` ssh_mainline 段），恒注册，API 失败自动降级

2. **✅ gen_schema 真 LLM 收口**（commit 待补）：`tools/factor/gen_schema.py` 真 LLM 动态生成 FactorSpec（operators / estimated_runtime_seconds / forward_return_horizon 契约字段补齐），失败降级 rule-based `_fallback`

3. **🔶 AutoEval 真 API**（部分）：`tools/factor/autoeval.py` 真 API 恒注册，未配置/失败时降级 mock 并标 `_is_mock`（共享 `flows.factor_autoeval.MOCK_AUTOEVAL_PAYLOAD_V1`）；真实服务端点稳定接入仍待完成

4. **🔶 factor 验收闭环**：验收阈值为 `runner/acceptance.py`（|ic_mean| ≥ 0.03、ir ≥ 0.5、turnover ≤ 0.8、t_stat ≥ 2.0），产物 `artifacts/factor/{name}-report.json`；`merge_to_main`/`check_factor_gate` **未实现**（🔲），合并/拒绝人工决策，无 IR>1.5 自动 merge

**验收**：
- [x] factor 三工具恒注册 + 降级标注可演；`tests/test_factor_tools.py` 全绿（commit 待补）
- [ ] 🔲 AutoEval 真实服务端点稳定接入 + merge/reject 自动决策闭环

---

## 7. 刘炽 · strategy/fundamental/options demo 收口

**背景**：PR#22（strategy + fundamental tools）请 rebase 到 main 后合入。三组走通用 AgentRunner 路径（`run_agent(group=X)`），不需要单独线性 flow，工具链已在 tools/ 下。

**剩余任务**：

1. **PR#22 rebase + 合入**：`git rebase origin/main`

2. **strategy demo**：`select_signals` → `combine_signals` → `run_strategy_backtest` → `deploy_strategy`，产出 StrategyReport schema 校验通过

3. **fundamental demo**：`pit_rag_search`（真 Chroma，时点安全）→ `extract_financial` → `dcf_valuation` → `render_report`（Typst PDF，无 Typst 环境可降级为 markdown）→ 人审，时点约束 `published_at <= as_of_date` 在 demo 可验

4. **options demo**：`build_vol_surface` → `calc_greeks` → `run_options_backtest_stub`，产出 OptionsRisk

5. **fixtures 终验**：6 组 demo fixtures 齐全真实（不是占位），fallback 必须明确标注

**验收**：
- [ ] PR#22 合入 main
- [ ] strategy/fundamental/options 三组各跑通一个 demo 场景，artifact 过 schema 校验
- [ ] fundamental pit_rag 时点安全可验（demo 里能看到 `published_at <= as_of_date`）
- [ ] fixtures 齐全，降级项标注清楚

---

## 8. Demo 场景编排（investor demo 30 分钟）

**场景 1：因子评估 + 验收闭环（8 分钟，Lead）**
- `/compose "测 PB-ROE 因子"` → match_main（真 LLM 读主线）→ gen_schema（真 LLM 生成 FactorSpec）→ autoeval（真 API / `_is_mock` 降级标注）→ 验收阈值判定（阈值 `runner/acceptance.py`）→ 人工 merge/reject 决策（merge_to_main 未实现）
- 展示 IDE：Compose 视图面板 + Schema 卡片 + 任务树
- 展示 checkpoint 中断恢复

**场景 2：模型提交 → 风控审批（8 分钟，杨欣琳 + 陈镇鸿）**
- model Agent：read_pr（真 GitHub）→ ModelSpec → write_blackboard → trigger_risk_flow
- risk Agent 自动触发：读 Blackboard → 风控计算 → VaR 超阈值 → **IDE HumanGate 暂停** → 人审 approve → 恢复 → 真写 PR comment
- 展示 IDE：HumanGate 面板 + Blackboard 跨组数据流
- 展示 dedupe（同 PR 触发 2 次 → GitHub 只 1 条 comment）

**场景 3：基本面研报（7 分钟，刘炽）**
- `/compose "分析公司 X 估值"` → pit_rag（时点安全）→ 财报提取 → DCF → 渲染 PDF（或 markdown 降级）→ 人审
- 展示程序化验收（`published_at <= as_of_date`）

**场景 4：自研加固 + 自我进化（5 分钟，尹一帆）**
- 展示死循环检测自动中止
- 展示 `/goal` 命令 → run_started 后 judge verdict（met/partial/missed）回填 RLHF
- 展示桌面 Monitor 面板（`.quantcode/metrics.jsonl` 聚合）或 `list_runs` 只读 MCP 工具
- 展示 `.quantcode/rlhf_data.jsonl` 正在收集训练数据

**收尾（2 分钟，Lead）**：6 套流快速切换 + roadmap（Week 2 计划）+ Q&A

---

## 9. 交付物（Day 5 必须齐）

| 交付物 | 负责人 | 状态 |
|---|---|---|
| ✅ `docs/Day5_Feature_Checklist.md` | Lead | 已完成（2026-08-30 状态更新） |
| ✅ `docs/IDE_Python_Interface_Contract.md` | Lead | 已完成 |
| ✅ `runner/demo_bridge.py` | Lead | 已完成（demo 录屏兜底） |
| ✅ README Quick Start | Lead | 已完成（env 配置方式，2026-08-30 更新） |
| [ ] **Demo 录屏**（≥ 场景 1 + 场景 2） | Lead + 杨欣琳/陈镇鸿 | 待录 |
| [ ] **PPT deck**（8-10 页） | Lead | 待出 |
| [ ] **`docs/handoff.md`** | Lead | 待出 |
| [ ] **artifacts 整理**（FactorSpec / RiskProfile / research 报告等） | 各 Owner | 待整理 |

---

## 10. 收工验收 checklist（investor demo 前）

### IDE 上线（硬性）
- [ ] OpenCode fork 能起，`/compose` 真触发 Python Agent
- [ ] 至少 3 组（model/risk/factor）可切换并触发
- [ ] 六面板（Compose / 任务树 / HumanGate / Schema / Memory / Resume）可用
- [ ] 状态回流（thought / tool_call / tool_result）流式显示

### PRD/Design 功能实现（硬性）
- ✅ 三大模式契约落地（ComposeTask / BlackboardState / HumanGate）
- ✅ 共用基础设施（验收 runner / schema 校验 / CI gate / dedupe）
- ✅ Memory FTS5 + Checkpoint + Dream + Distill
- ✅ trigger_risk_flow 机制定型
- ✅ 6 套 Compose 流全部注册在 FLOW_REGISTRY（`runner/compose_executor.py` 统一 import：facto:autoeval、risk:gate、model:submit、strategy:compose、options:compose、fundamental:research）（commit 待补）
- ✅ Schema 动态生成 + match_main（真 LLM 收口，降级标注）（commit 待补）
- 🔶 AutoEval 真 API（工具恒真版已接，降级 `_is_mock`；真实服务端点稳定接入待完成）
- ✅ 自动 Checkpoint（Wave5 实现：70% 快照 / 90% 重建，字符/4 近似 token，`QUANTCODE_CONTEXT_TOKENS` 可调）
- ✅ 运行监控：`.quantcode/metrics.jsonl` + `list_runs` 只读 MCP tool + 桌面 Monitor 面板（commit 待补）
- ✅ /goal → judge verdict 消费端（`apply_judged_session` 回填 RLHF）（commit 待补）；dream_events 仍未接（🔲）

### Demo + 交付物
- [ ] 4 个 demo 场景可演（录屏兜底 ≥2 个）
- [ ] PPT + handoff.md + Quick Start + artifacts 齐全

### 质量
- ✅ 全量测试 702 passed / 5 skipped（2026-08-30 基线；桌面端 bun test 490 pass）
- [ ] CI 全绿
- [ ] demo 场景引擎稳定（无 context 爆 / 无挂死 / 无死循环）

---

## 11. 各人待合入的 PR（需 rebase 到 main）

| PR | 作者 | 状态 | 操作 |
|---|---|---|---|
| #24 feat(model): real GitHub read_pr + handoff | 陈镇鸿 | OPEN | rebase → merge |
| #22 feat(day4): strategy + fundamental tools | 刘炽 | OPEN | rebase → merge |
| #21 feat(agent): Day4 AgentRunner updates | 尹一帆 | OPEN | rebase → merge |
| #20 feat(risk): Day4 ReAct readiness + E2E | 杨欣琳 | OPEN | rebase → merge |
| #19 feat(day3): group schemas + SKILL stubs | 刘炽 | OPEN | 确认是否仍需要 |
| #12 feat: HumanGate pydantic + interrupt | 杨欣琳 | OPEN | 确认已被 main 覆盖，可 close |

> **注意**：rebase 时 `AgentRunner.__init__` 不再接受 `gate_tools` 和 `rlhf_collector` 参数（功能已内化），去掉即可。其余 tool 代码不受影响。

---

## 12. 降级方案（若某项 Day5 当天卡住）

| 卡住项 | 降级 |
|---|---|
| IDE TS 集成卡住 | `python scripts/demo_jerry_tracks.py --track all`（或 `python -m runner.demo_bridge --group X --task "..." --auto-approve`）+ 录屏，前端推 Week 2 |
| AutoEval 真 API 不通 | mock 数据跑 factor demo，结果标 `_is_mock`（真版工具自动降级，handoff 标注） |
| fundamental Chroma 不通 | fixture 替代，demo 里明确说"时点安全已验证，向量库 Week 2 接" |
| model/risk 跨组链路卡 | demo 主菜换场景 1（factor），场景 2 用录屏/截图兜底 |

**原则：demo 可以缩，不能假。** 宁可演 3 个真跑通的场景，不演 6 个 mock 的。

---

**Day 5 一句话**：地基已稳（Lead 提前打好），各组专注把自己的 demo 场景跑通、PR 合入、交付物产出——从"能跑"到"能上线、能演示、能交棒"。

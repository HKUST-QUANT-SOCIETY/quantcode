# QuantCode 功能规格（FUNCTIONAL_SPEC）

> **版本**：v0.1（2026-09-01）｜**Owner**：Agent Group
> **声明**：本文件是 QuantCode 功能规格的**唯一活文档**。`docs/PRD.md` 描述产品愿景（只读参考）；`docs/Day1~5_*`、`docs/Day5_Feature_Checklist.md` 一律为**历史快照**，不再更新，状态以本文件为准。长期路线见 `docs/audit/ROADMAP_LONGTERM.md`，域级设计见 `specs/<域>/SPEC.md`（规范见 `specs/SPEC_GUIDE.md`）。
> **编号**：现有功能 F-01…F-09，计划功能 P-01…P-06。跨文档引用一律用编号。后端 = 本仓库根；UI 仓库 = `opencode-lens`（前端路径 `packages/app/src/components/quantcode/` 相对 UI 仓库根）。

---

## 第一部分：现有功能（F-XX）

### F-01 新建多智能体研究（lens 首页 → run_agent）✅
**用户故事**：作为任一组研究员，我想在品牌壳首页输入研究任务、选组与 Skill 并一键提交，以启动本组 Multi-Agent 研究流，不必记忆 MCP 命令。

**契约**：UI `RunAgentResult`（`result-contract.ts`：status/thread_id/gate/execution_trace/output_data/artifacts）↔ 后端 `RunAgentArgs`（`runner/agent_mcp_tool.py`：task/group/skill_name/max_iterations/thread_id/decision，start/resume 两阶段）。组枚举 `GroupName`（`schemas/compose_task.py`）。

**数据流**：`panels.tsx::QuantCodePanel`（⌘⏎ 提交）→ `instructions.ts::buildResearchInstruction`（强制调 run_agent）→ `quantcode/mcp_server.py`（QUANTCODE_GROUP 过滤）→ `runner/agent_engine.py` ReAct 循环 → 组 allowlist 过滤 tool → trace 经 `result-contract.ts` 回流 `updateQuantCodeTrace`。

**验收**：
- Given 已选组=factor，When 点击"开始研究"，Then 提交指令含 `group="factor"` 且强制 run_agent 调用語句。
- Given 任务含关键词（如 "PR"），When `agent_mcp_tool._resolve_skill_name` 路由，Then 分派到执行器子 skill（`ORCHESTRATOR_DISPATCH`）。

**状态**：✅。缺口：Skill 下拉为硬编码 4 条常量，未读 `.opencode/groups/*/skills/` 真实目录。

### F-02 执行记录视图（Activity）✅
**用户故事**：作为研究员，我想按时间线查看 run 的推理/工具调用/产物/异常，并一键"再次运行"。

**契约**：`RunAgentResult.execution_trace: TraceEvent[]`（事件枚举 12 类：agent_start/skill_loaded/node_update/llm_thought/tool_call/tool_result/risk_metrics/human_gate/output_data/artifact/agent_end/error，另有 `checkpoint_snapshot` 扩展类型）。

**数据流**：agent_engine 产 trace → trace 桥（跨会话重置）→ `ActivityPanel`（timeline+artifacts）。`mergeTraceEvents` 按 `iteration:seq` 去重；缓存 localStorage `quantcode:thread_cache`（≤50）。

**验收**：同 `iteration:seq` 事件不重复；同 thread_id 结果合并 upsert。

**状态**：✅。缺口：无服务端 run 历史读取（未接 F-09 的 list_runs）。

### F-03 HumanGate 审批 ✅
**用户故事**：作为风控组研究员，我想在风险越过阈值时在专用面板看到原因与指标，并一键批准/拒绝，使研究继续或安全终止。

**契约**：`HumanGate/HumanGateDecision/HumanGateInterruptPayload`（`schemas/human_gate.py` + `schemas/human-gate.schema.json`）；阈值 `RiskThresholds`（`schemas/risk_profile.py`：max_drawdown≤0.15、position_limit_usage≤0.8、tail_risk_var_99≤0.05、correlation_limit≤0.6）；契约锁定详见 [specs/governance/SPEC.md](governance/SPEC.md)。

**数据流**：check_gate → `runner/human_gate.py` → LangGraph interrupt → run_agent 返回 waiting_for_human → UI GatePanel（导航轨红点）→ 批准/拒绝 → `buildResumeInstruction` → promptAsync → `run_agent(resume)` 恢复。

**验收**：max_drawdown=0.25 → breached_thresholds 含该键且 verdict=needs_human；拒绝路径 `normalize_external_decision` fail-closed。

**状态**：✅（E2E：test_model_risk_handoff_e2e / test_human_gate）。缺口：多 gate 排队 UI 未做。

### F-04 Memory 浏览 ✅（UI 只读）
**用户故事**：作为研究员，我想查看团队沉淀的研究结论与决策记录，让下一次研究从已知结论开始。

**契约**：`MemoryService.search/write/get`（`runner/memory/service.py`，FTS5+BM25+CJK `runner/memory/fts.py`）；5-scope + GROUP 隔离。

**验收**：跨组读抛 `MemoryPermissionError`（fail-closed）；写 ≥1 条后 dream 扫描可检索命中。

**状态**：✅ 后端完整。缺口：UI 面板为静态说明，未接真实 FTS 查询界面；dream_events 产生端未接（P0-9 遗留）。

### F-05 设置（组/身份/供应商）🔶
**用户故事**：作为研究员，我想选择研究组、查看 SSH 身份与连接状态、配置默认 Skill，使每次提交无需重复配置。

**契约**：组枚举 `QUANTCODE_GROUPS`（UI `instructions.ts`）↔ `GroupName`；身份 `quantcode/identity.py`（SSH 指纹→组映射，fail-closed）；tool 可见性 `registry.get_tools_for_group`。

**验收**：切组=options 后 tools/list 只返回 options allowlist 内 tool；断连时提交被阻断。

**状态**：🔶。缺口：LLM/AutoEval 供应商无 UI（仅环境变量）；SSH 完整认证面未建设。

### F-06 Factor AutoEval 流 🔶
**用户故事**：作为因子组研究员，我提交因子 idea 后系统自动匹配主线库、生成 FactorSpec、回测并产出 IC/IR/换手报告，用统一口径横向比较。

**契约**：入 `FactorSpec`（`schemas/factor.py`：formula/operators/universe/date_range/forward_return_horizon∈{1,3,5,10,20}），出 `FactorReport`（ic_metrics/turnover/decay/layered_backtest/verdict∈pass|fail|marginal；JSON 版 `schemas/factor-report.schema.json`）；阈值 `runner/acceptance.py::_check_factor_eval`。

**数据流**：match_main（真 LLM，可经 `runner/server_ssh.py`）→ gen_schema（LLM，失败降级规则生成并日志标注）→ autoeval（`AUTOEVAL_API_URL`；未配置降级 mock 标 `_is_mock`）→ acceptance verdict → UI output_data。

**验收**：API 未配置时 mock 报告带 `_is_mock` 且仍符合 schema；FactorReport 缺关键字段时校验失败记 fail_reasons。

**状态**：🔶。缺口：`merge_to_main`/`check_factor_gate` 未实现；真实 AutoEval 服务端点未稳定。

### F-07 Model→Risk 跨组 PR 流 ✅
**用户故事**：作为模型组研究员，我提交模型 PR 后希望 10 分钟内自动得到 RiskProfile 与 gate 结论，越阈值才进 HumanGate。

**契约**：`ModelSpec`（`schemas/model.py`）→ `RiskProfile`（`schemas/risk_profile.py`）；跨组队列 `shared.pending_risk_reviews`（`runner/blackboard_keys.py`，PROJECT scope + `PROJECT_SESSION_ID`）；防刷 `@dedupe_within`（`tools/utils/dedupe.py`）。

**数据流**：read_pr（真 GitHub）→ extract_metadata → generate_model_spec → write_blackboard（`shared.model_entries.*`）→ trigger_risk_flow → risk 组消费 → calc_risk/generate_risk_profile → write_pr_comment（dedupe）+ gate。CI：`.github/workflows/risk-gate.yml`。

**验收**：写读同 session 同 key（E2E `tests/test_model_risk_handoff_e2e.py`）；同 PR重复评论被 dedupe 拦截。

**状态**：✅ 全链路。缺口：factor→strategy 跨组消费（ROADMAP A1/Week2）。

### F-08 Strategy / Options / Fundamental 三条 Compose 流 🔶
**用户故事**：作为策略/期权/基本面研究员，我想以各自的确定性流水线完成信号组合回测、波动率曲面+Greeks、PIT 研报生成，用统一 artifact 契约沉淀结果。

**契约**：strategy：`StrategySpec`→`StrategyReport`（weights+BacktestSummary）；options：`OptionsSpec`→`VolSurfaceResult`→`GreeksProfile`（`schemas/options.py`）；fundamental：`PITQuery`（as_of_date 强约束）→`PITResult`→`ResearchResult`（`schemas/fundamental.py`）。

**数据流**：`flows/{strategy_compose,options_compose,fundamental_research}.py` → `runner/compose_executor.py::FLOW_REGISTRY`；tools 各组目录；acceptance `_check_{pit_rag,research_pdf}`。

**验收**：PIT 检索结果 `published_at` 全部 ≤ as_of_date（零违规）；StrategyReport.weights ⊆ selected_signals。

**状态**：🔶 可跑（test_flows_six）。缺口：options backtest、extract_financial 为 stub（strategy 回测已接真引擎 internal_v1，见 `tools/strategy/backtest_engine.py`）；deploy_strategy 仅建议；SKILL frontmatter 自动注册未实现。

### F-09 Monitor 可观测 ✅
**用户故事**：作为工程师，我想在 Monitor 面板查看每次 run 状态并用任务 ID 回放，以诊断失败与验证回归。

**契约**：`runner/metrics.py` 追加 `.quantcode/metrics.jsonl`；只读 MCP `list_runs`（`quantcode/mcp_server.py`）；replay `scripts/replay.py`（list/show/resume，thread 反查）。

**验收**：run 完成 → metrics 追加一行且 list_runs 可见；`replay show <task_id>` 可反查并 resume。

**状态**：✅。缺口：告警未做（token 预算已有 `QUANTCODE_TOKEN_BUDGET` 硬约束，见 `runner/agent_mcp_tool.py`；成本核算与告警剩 ROADMAP R2/G3）；Monitor 仅有列表视图。

---

## 第二部分：计划功能（P-XX）

### P-01 数据接入（qsdata 组 + FactorPanel 契约）——P0，Q1（✅ 已实现：`schemas/data_contracts.py` + `tools/market/` 四工具，见 `specs/data/SPEC.md`）
**动机**：ROADMAP"最高优先级单点"——回测/组合/真实评估全部空转的前置。qs-cold 已勘察（247 因子，长表 PIT 字段内建）。
**契约草案**：[新增] `schemas/data_contracts.py`：`FactorPanel`（dates/assets 值矩阵 + is_valid 过滤 + PIT calc_time<=as_of + `_contract:"FactorPanel/v1"`）、`ReturnsDataset`、`StrategyManifest`；工具 [新增] `tools/market/`：`list_factors/load_factor_panel/load_returns/pool_browse`。数据走 Blackboard `shared.datasets.*`（typed 对象），LLM 只见 key+摘要。详见 [specs/data/SPEC.md](data/SPEC.md)。
**依赖**：COS 凭据（Q2 服务化）；本地 staging dev 后端先行。**验收草案**：GTJA191_M019 因子跑出替换 mock 的真实 IC 报告；无权限组 fail-closed。

### P-02 回测引擎——P1，Q2 选型/Q3 落地
**契约草案**：`run_backtest(spec, data: ReturnsDataset, config) -> BacktestSummary`（A 股 T+1/涨跌停/费用模型）。依赖 P-01；验收：同 manifest 对账误差=0。

### P-03 组合层——P1，Q4
**契约草案**：`construct_portfolio(target, panel) -> PortfolioWeights`（风险平价/min-var/scipy 确定性优化，LLM 不参与数值）；`rebalance_plan`（成本模型）；`check_portfolio_gate`（复用 HumanGate，阈值 `portfolio.yaml`）。依赖 P-01/P-02/F-03。

### P-04 并行 subagent——P1，Q2
**契约草案**：`spawn_subagent(task, group, budget)`（预算隔离+共享 Blackboard 写策略）+ `kill(task_id)` + 任务树 registry（`MAX_TREE_DEPTH=4`）。依赖 token 预算硬约束（Q1）与沙箱 L1。

### P-05 实验管理——P1，Q3
**契约草案**：`run_ab_experiment(baseline, challenger, oos_range) -> ABReport`；acceptance 增 `oos_discipline` 检查；实验归档挂 trace 指纹。依赖 P-01 真实 IC/OOS。

### P-06 evidence chain 报告——P0，Q3（审计日志 Q1 前置）
**动机**：合规 must（合规脊柱终点：身份→权限→审计→指纹→报告）。
**契约草案**：`generate_evidence_report(run_ids) -> EvidenceReport`（哈希指纹链+产物指纹+决策署名，JSON→PDF）。详见 [specs/governance/SPEC.md](governance/SPEC.md) §2.2。**验收**：篡改任一产物可被指纹校验发现。

---

## 附：编号索引

| 编号 | 名称 | 类型 | 状态 |
|---|---|---|---|
| F-01 | 新建多智能体研究 | 现有 | ✅ |
| F-02 | 执行记录视图 | 现有 | ✅ |
| F-03 | HumanGate 审批 | 现有 | ✅ |
| F-04 | Memory 浏览 | 现有 | ✅（UI 只读） |
| F-05 | 设置 | 现有 | 🔶 |
| F-06 | Factor AutoEval 流 | 现有 | 🔶 |
| F-07 | Model→Risk 跨组流 | 现有 | ✅ |
| F-08 | 三条 Compose 流 | 现有 | 🔶 |
| F-09 | Monitor 可观测 | 现有 | ✅（告警未做） |
| P-01..P-06 | 数据接入/回测/组合/并行/实验/evidence chain | 计划 | P-01 ✅ 已实现；余项 Q1→Q4 |

> 维护声明：本文件为功能唯一活文档；schemas/ 或 tools/ 每次改动必须同步更新状态列。历史快照不再修改。
# Day 5 功能对照清单（PRD/Design P0 逐条清零）

> **用途**：对照 PRD §3.1 P0 + Design §4 功能清单，逐条核对实现状态。
> **图例**：✅ 已实现 / 🔶 降级实现（标注降级到什么）/ ❌ 未实现（标注原因 + Week 2 计划）
> **最后更新**：2026-07-10（Lead）

---

## 0. AgentRunner vs 线性 flow 分组决策（Day5 关键口径）

系统有两条执行路径，本节定型 Day5 demo 各组走哪条：

- **AgentRunner**（`runner/agent_engine.py`）：真 ReAct，LLM 自主推理调哪个 tool，符合架构铁律"不预定义 DAG"。经 `run_agent` MCP 入口触发，6 组通用。
- **线性 flow**（`flows/*.py` + `compose_executor.FLOW_REGISTRY`）：预定义 StateGraph 固定节点序，稳定但非自主推理。

| 组 | Day5 demo 路径 | 入口 | 理由 |
|---|---|---|---|
| **factor** | ✅ AgentRunner（真 ReAct） | `run_agent(group=factor)` | demo 场景 1 展示自主推理；Lead 收口 match_main/gen_schema/autoeval。线性 `flows/factor_autoeval.py` 作兜底 |
| **model** | ✅ AgentRunner | `run_agent(group=model, skill=model-pr-submit)` | 跨组发起，read_pr→extract→spec→trigger 自主编排 |
| **risk** | ✅ AgentRunner + 确定性 gate | `run_agent(group=risk, skill=risk-gate)` | ReAct 到 gate，人审后走确定性路径（PR#25），避免 approve 后空转 |
| **options** | 🔶 线性/通用 AgentRunner 兜底 | `run_agent(group=options)` | 工具独立（vol_surface→greeks→backtest），ReAct 收益低；Week 2 可切 |
| **strategy** | 🔶 线性/通用 AgentRunner 兜底 | `run_agent(group=strategy)` | select→combine→backtest 天然线性 |
| **fundamental** | 🔶 线性/通用 AgentRunner 兜底 | `run_agent(group=fundamental)` | pit_rag→extract→dcf→render 天然线性；重点是 PIT 安全 |

**口径**：demo 主菜（factor、model→risk）走 AgentRunner 展示自主推理；options/strategy/fundamental 用兜底路径保证可演，handoff 标注"Week 2 迁 ReAct"。守住架构铁律展示面，不赌 6 组一天全切 ReAct。

---

## 1. 六套 Compose 流（PRD §3.1 / Design §4.3）

| 组 | tools 状态 | Agent 装配 | artifact schema | 状态 |
|---|---|---|---|---|
| model | read_pr(真GitHub) / extract_metadata / generate_model_spec / write_blackboard / trigger_risk_flow | ✅ AgentRunner | ModelSpec | ✅ |
| risk | read_blackboard / calc_risk / generate_risk_profile / check_gate / write_pr_comment / request_human_review | ✅ AgentRunner + 确定性 gate | RiskProfile | ✅ |
| factor | match_main / gen_schema / autoeval | ✅ AgentRunner + 线性 flow | FactorReport | 🔶 match_main/gen_schema 真 LLM 收口进行中；autoeval 待真 API |
| fundamental | pit_rag_search / extract_financial / dcf_valuation / render_report | 🔶 通用 AgentRunner | ResearchSpec | 🔶 tools 部分 stub，pit_rag 需真 Chroma |
| strategy | select_signals / combine_signals / run_strategy_backtest / deploy_strategy | 🔶 通用 AgentRunner | StrategyReport | 🔶 tools 部分 stub |
| options | build_vol_surface / calc_greeks / run_options_backtest_stub | 🔶 通用 AgentRunner | OptionsRisk | 🔶 backtest 为 stub |

---

## 2. 三大生产模式契约（PRD §3.1 / Design §3.2）

| 模式 | 契约 schema | 实现 | 状态 |
|---|---|---|---|
| Pattern 1 Orchestrator-Worker | ComposeTask | `schemas` + compose_executor / run_agent | ✅ |
| Pattern 2 Stateful Blackboard | BlackboardState | `runner/blackboard.py`（PROJECT/GROUP scope 硬隔离） | ✅ |
| Pattern 5 Human-in-the-Loop Gate | HumanGate | `runner/human_gate.py`（确定性 interrupt/resume） | ✅ |
| 保险栓 | @dedupe_within | `tools/utils/dedupe.py`（SQLite 后端） | ✅ |

---

## 3. 共用基础设施（PRD §4.3）

| 能力 | 实现 | 状态 |
|---|---|---|
| 验收 runner | `runner/acceptance.py`（risk/factor 阈值检查） | ✅ |
| Schema 校验 | `runner/schema_validator.py`（jsonschema） | ✅ |
| PR Code Review | `.github/workflows/review.yml`（中央 Multi-Agent Review + Server B） | 🔧 接入中 |
| Risk Compose 业务 gate | `flows/risk_gate.py` + HumanGate；不再由 PR reviewer 直接安装并执行 | ✅ 业务实现，独立 CI 待补 |
| dedupe | `tools/utils/dedupe.py` | ✅ |

---

## 4. 引擎能力（PRD §4.4 / Design §4.1）

| 能力 | 实现 | 状态 |
|---|---|---|
| Memory FTS5（5-scope + BM25 + CJK + GROUP 隔离） | `runner/memory/` | ✅ |
| 自动 Checkpoint（SqliteSaver + resume） | `runner/langgraph_base.py` | ✅ |
| ReAct 引擎（自搭 StateGraph） | `runner/agent_engine.py` | ✅ |
| 死循环检测 / 迭代上限 / 状态指纹 | `tools/loop_detector.py` / `runner/routing/` | ✅ |
| RLHF 接入点（rules-only 重构） | `runner/routing/rlhf_logger.py` | ✅ |
| token 截断（长任务 context） | `runner/agent_nodes.py::make_truncate_node`（可选，已知 reducer 累积限制） | 🔶 Week 2 配自定义 reducer |
| Dream 知识提取 | `dream/dream_prototype.py` | 🔶 见 §5 |
| Distill 自动化 | `dream/distill_prototype.py` | 🔶 Day5 新增原型，见 §5 |
| Schema 动态生成 | `tools/factor/gen_schema_stub.py`（Pydantic 代码生成 + exec 校验） | 🔶 真 LLM 收口进行中 |
| match_main（主线匹配） | `tools/factor/match_main_stub.py`（fixture-backed，backend 可换真 LLM） | 🔶 真 LLM 收口进行中 |

---

## 5. Dream / Distill（Day5 §3 尹一帆 + §5 本计划）

- **Dream**（`dream/dream_prototype.py`）：扫 checkpoints.db/rlhf trace → LLM 提取 → 写 memory ≥1 条可检索。🔶 补强：改走 rlhf_data.jsonl 聚合多条 trace（见 阶段5）。
- **Distill**（`dream/distill_prototype.py`）：Day5 新增原型，识别重复 pattern → 候选 SKILL.md 草案。🔶 原型级，Week 2 完整化。

---

## 6. 跨组协作触发（PRD §4.7 / Design §4.2.5）

| 链路 | 机制 | 状态 |
|---|---|---|
| model → risk | trigger_risk_flow 写 `shared.pending_risk_reviews`（方式2 队列标志，Architecture §3.2 定型） | ✅ |
| factor → strategy | Blackboard PROJECT scope（因子池 → 策略消费） | 🔶 Week 2 |

---

## 7. 控制平面 / IDE（PRD §3.2 / Day5 §2）

| 能力 | 实现 | 状态 |
|---|---|---|
| MCP server（6 命名 server） | `opencode.jsonc` + `quantcode/mcp_server.py` | ✅ |
| run_agent 入口（start/resume 两阶段） | `runner/agent_mcp_tool.py` | ✅ |
| execution_trace 状态回流（10 事件类型） | `runner/agent_engine.py` | ✅ |
| Python 侧接口契约 | `docs/IDE_Python_Interface_Contract.md` | ✅ |
| OpenCode fork 六面板 UI | `../opencode/packages/app` | 🔶 见 阶段4 |

---

## 8. 已知降级项（写入 handoff.md）

- **truncate_node**：operator.add reducer 累积翻倍，demo 不触发，Week 2 配自定义 reducer。
- **fundamental/strategy/options tools**：部分 stub，demo 用 fixture，标注非真实接入。
- **factor autoeval**：待真 AutoEval API（肖骥超协助）。
- **Distill**：原型级，识别 ≥1 pattern 即达标，Week 2 完整化。
- **factor→strategy 跨组**：Week 2。
- **Memory 浏览器 / checkpoint 列表 MCP 只读入口**：Day5 前端先直接读 SQLite，Week 2 补只读 tool。

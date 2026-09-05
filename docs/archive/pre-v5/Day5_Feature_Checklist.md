# Day 5 功能对照清单（PRD/Design P0 逐条清零）

> **用途**：对照 PRD §3.1 P0 + Design §4 功能清单，逐条核对实现状态。
> **图例**：✅ 已实现 / 🔶 降级实现（标注降级到什么）/ ❌ 未实现（标注原因 + Week 2 计划）
> **最后更新**：2026-08-30（Lead；本轮已实现项转 ✅，commit 待补）

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
| factor | match_main / gen_schema / autoeval | ✅ AgentRunner + 线性 flow | FactorReport | ✅ 三工具恒注册真 LLM/API 实现，API 失败自动降级 `_is_mock`（commit 待补）；`merge_to_main`/`check_factor_gate` 仍未实现，验收止于 verdict |
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
| CI gate | `.github/workflows/risk-gate.yml`（GitHub Actions 真集成） | ✅ |
| dedupe | `tools/utils/dedupe.py` | ✅ |

---

## 4. 引擎能力（PRD §4.4 / Design §4.1）

| 能力 | 实现 | 状态 |
|---|---|---|
| Memory FTS5（5-scope + BM25 + CJK + GROUP 隔离） | `runner/memory/` | ✅ |
| 自动 Checkpoint（SqliteSaver + resume） | `runner/langgraph_base.py`（单 db：`.quantcode/checkpoints.db`） | ✅（context>70% 快照 / >90% 重建见下行） |
| 上下文自动快照/重建（PRD §4.4） | `runner/agent_nodes.py`（CONTEXT_SNAPSHOT_RATIO=0.7 / CONTEXT_REBUILD_RATIO=0.9，字符/4 近似 token，`QUANTCODE_CONTEXT_TOKENS` 可调；messages reducer 翻倍 bug 已修 `merge_messages`） | ✅（Wave5 实现，commit 待补） |
| replay（thread 反查 + list/show/resume） | `scripts/replay.py`（thread_id 含 task_id 段，`make_thread_id` 可传） | ✅（最小版，Wave5 实现，commit 待补） |
| 运行监控 metrics | `runner/metrics.py` 写 `.quantcode/metrics.jsonl`（agent_engine 完成钩子）；只读 `list_runs` MCP tool + 桌面 Monitor 面板 | ✅（Wave5 新增，commit 待补） |
| ReAct 引擎（自搭 StateGraph） | `runner/agent_engine.py` | ✅ |
| 死循环检测 / 迭代上限 / 状态指纹 | `tools/loop_detector.py` / `runner/routing/` | ✅ |
| RLHF 接入点（rules-only 重构） | `runner/routing/rlhf_logger.py`；judge/Goal 消费端已建（`/goal` → judge verdict → `apply_judged_session` 回填） | ✅（消费端 Wave5 实现，commit 待补） |
| token 截断（长任务 context） | `runner/agent_nodes.py::make_truncate_node` + 上下文快照/重建（见上行） | ✅（自动 Checkpoint 主路径已实现） |
| Dream 知识提取 | `dream/dream_prototype.py` | 🔶 见 §5（dream_events 仍未接） |
| Distill 自动化 | `dream/distill_prototype.py` | 🔶 原型级 |
| Schema 动态生成 | `tools/factor/gen_schema.py`（真 LLM 生成 + FactorSpec 契约补齐，失败降级 rule-based） | ✅（降级 `_fallback` 标注；commit 待补） |
| match_main（主线匹配） | `tools/factor/match_main.py`（真 LLM，API 失败自动降级；可经 `runner/server_ssh.py` SSH 读主线，`pip install 'quantcode[ssh]'`） | ✅（commit 待补） |

---

## 5. Dream / Distill（Day5 §3 尹一帆 + §5 本计划）

- **Dream**（`dream/dream_prototype.py`）：扫 checkpoints.db/rlhf trace → LLM 提取 → 写 memory ≥1 条可检索。🔶 补强：改走 rlhf_data.jsonl 聚合多条 trace（见 阶段5）。
- **Distill**（`dream/distill_prototype.py`）：Day5 新增原型，识别重复 pattern → 候选 SKILL.md 草案。🔶 原型级，Week 2 完整化。

---

## 6. 跨组协作触发（PRD §4.7 / Design §4.2.5）

| 链路 | 机制 | 状态 |
|---|---|---|
| model → risk | trigger_risk_flow 写 `shared.pending_risk_reviews`（方式2 队列标志，Architecture §3.2 定型）；session 固定 `PROJECT_SESSION_ID` + `shared.model_entries.` 前缀归一（`runner/blackboard_keys.py`），E2E 锁死 `tests/test_model_risk_handoff_e2e.py` | ✅ |
| factor → strategy | Blackboard PROJECT scope（因子池 → 策略消费） | 🔶 Week 2 |

---

## 7. 控制平面 / IDE（PRD §3.2 / Day5 §2）

| 能力 | 实现 | 状态 |
|---|---|---|
| MCP server（6 命名 server） | `opencode.jsonc` + `quantcode/mcp_server.py` | ✅ |
| run_agent 入口（start/resume 两阶段） | `runner/agent_mcp_tool.py` | ✅ |
| execution_trace 状态回流（10 事件类型） | `runner/agent_engine.py` | ✅ |
| Python 侧接口契约 | `docs/IDE_Python_Interface_Contract.md` | ✅ |
| 桌面端七 Tab 面板（compose/tasks/gate/schema/memory/resume/monitor） | trace 接线 `updateQuantCodeTrace`、gate 面板 Approve/Reject 按钮（→ run_agent resume）、组切换 segmented 六组、Monitor 面板、/goal 命令 | ✅（Wave5 实现，commit 待补） |

---

## 8. 已知降级项（写入 handoff.md）

- **SSH 完整认证面**：组身份 SSH 绑定已最小闭环（指纹→组映射→fail-closed），但 SSH key 级别的完整认证/审计面仍待建设。
- **compose SKILL frontmatter 自动注册**：flow 注册仍靠 `runner/compose_executor.py` 统一 import，SKILL.md frontmatter 自动声明未实现。
- **fundamental/strategy/options tools**：部分 stub，demo 用 fixture，标注非真实接入（风控 calc_risk 已支持 returns 真值，无 returns 时标注 `_is_stub`）。
- **factor autoeval 降级**：真 API 已接，未配置/失败时自动降级 mock 并标 `_is_mock`（真实服务端点仍待稳定接入）。
- **merge_to_main / check_factor_gate**：未实现，验收止于 verdict，合并人工决策。
- **Distill**：原型级，识别 ≥1 pattern 即达标。
- **factor→strategy 跨组**：Week 2。
- **Dream 消费端**：judge/review 消费端已建，dream_events 产生/接入仍未完成。

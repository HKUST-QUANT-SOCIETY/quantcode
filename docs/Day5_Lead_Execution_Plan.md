# Day 5 Lead 执行计划

> 目标：解决三处文档漂移 + 分组决策 + 补 MCP + 完成 IDE + 实现 Distill + 收口两小项。
> 分支策略：先把 PR #25（俞高磊 run_agent 入口）解冲突合入 main，作为 IDE 工作基座。

---

## 阶段 0：合并 PR #25 到 main（IDE 工作的前置）

PR #25 提供 `runner/agent_mcp_tool.py` 的 `run_agent` start/resume 入口 —— IDE 触发链依赖它。当前与 main 有 8 个文件冲突（agent_engine / agent_nodes / mcp_server / model SKILL / opencode.jsonc / test_agent_nodes 等），都是 Day 4 并行 PR 的叠加。

步骤：
1. 新建集成分支 `lead/day5-integration`（基于 main）。
2. merge `origin/gaolei/day3-routing-guards`（PR #25 head），逐个解冲突：
   - `agent_engine.py` / `agent_nodes.py`：保留 PR25 的 `stream()` 真实消费 `app.stream()` + 节点级 execution_trace（这是 IDE 状态回流的数据契约），与 main 的 gate/truncate 节点合并。
   - `mcp_server.py`：合并 PR25 的 `run_agent` 工具注册。
   - `opencode.jsonc`：**放弃 PR25 的单 server 方案，采用 6 命名 server**（见阶段 2）。
   - model SKILL.md / test_agent_nodes：取 PR25 较新版本，跑测试校验。
3. `python -m pytest -q` 全绿（skill_loader 21 个失败在阶段 4 一并修）后合入 main。

产出：main 上有稳定的 `run_agent` 入口 + stream trace 契约。

---

## 阶段 1：解决三处文档漂移

1. **Design §5.5 技术栈表** "编排：OpenCode Compose Mode（不引入 LangGraph）" → 改为 "编排：Python / LangGraph ReAct Agent（自研运行时加固）+ 复用 MimoCode 15 compose skill"。与 PRD §6、Architecture v2、实际代码对齐。
2. **Design §3.4 仓库结构** 的 TS plugin 蓝图（`plugins/*.ts`）→ 替换为真实 Python 布局：`runner/`（引擎/memory/blackboard/routing/human_gate）、`tools/`（6 组 + common + utils）、`flows/`、`schemas/`、`quantcode/mcp_server.py`、`dream/`。保留 `.opencode/groups/<group>/` 和 desktop fork 部分。
3. **Memory scope 命名不一致** Design §4.5 的 `global/projects/groups/sessions/tasks` → 与代码 `runner/memory/paths.py` 对齐（实际是 `global/projects/groups/sessions/tasks` 五层，代码里 sessions 也承载 checkpoint、tasks 独立）。核对后统一表述，并在 §4.5 标注 scope 名与 `MemoryLocator` 字段一一对应。

> 注：盘点时说的 `PROJECT/GROUP/threads/ephemeral` 是 Blackboard 的 scope（`runner/blackboard.py`），与 Memory 的 5-scope 是两套。文档需明确区分二者，避免继续混淆。

产出：三份顶层文档内部自洽，新成员照 Design 能找到代码。

---

## 阶段 2：Day5 风险① — 补 opencode.jsonc 的 MCP server

main 只有 model/strategy/fundamental/options 四个 `quantcode-<group>` server，缺 **risk 和 factor**（恰是 demo 主菜）。

- 采用 6 命名 server 结构（用户已定）：新增 `quantcode-risk`、`quantcode-factor`，各带 `QUANTCODE_GROUP` 环境变量。
- 校验 `quantcode/mcp_server.py` 的 `list_tools()` 按 group 过滤对 6 组都正确。
- 加一个 `scripts/verify_mcp_groups.py`（或测试）确认 6 组各自 list_tools 非空且只含本组白名单工具。

产出：6 组在 OpenCode 里都能作为独立 MCP server 被选中。

---

## 阶段 3：AgentRunner vs 线性 flow 分组决策（评估 + 落地）

### 评估结论

两条路径现状：
- **AgentRunner**（`runner/agent_engine.py`）：真 ReAct，LLM 自主选 tool，符合架构铁律。model/risk/factor 白名单已就绪。
- **线性 flow**（`flows/*.py` + `compose_executor.FLOW_REGISTRY`）：预定义 StateGraph 固定节点序，factor:autoeval / risk_gate 走这条。稳定但不是"自主推理"。

### 建议分组

| 组 | Day5 demo 路径 | 理由 |
|---|---|---|
| **factor** | ✅ AgentRunner（真 ReAct） | demo 场景 1 要展示"自主推理"，Lead 亲自收口 match_main/gen_schema/autoeval 真 LLM，必须走 ReAct 才对得上叙事 |
| **model** | ✅ AgentRunner | 跨组发起，read_pr→extract→spec→trigger 让 Agent 自主编排，展示自主决策 |
| **risk** | ✅ AgentRunner + 确定性 gate 后路 | PR25 已为 risk-gate 加确定性执行路径（approve 后不空转）。demo 走 ReAct 到 gate，人审后走确定性 artifact 生成 —— 兼顾自主性与可演示稳定性 |
| **options** | 🔶 线性 flow 兜底 | 工具相对独立（vol_surface→greeks→backtest），ReAct 收益低，线性稳定；handoff 标注 Week 2 可切 ReAct |
| **strategy** | 🔶 线性 flow 兜底 | 同上，select→combine→backtest 天然线性 |
| **fundamental** | 🔶 线性 flow 兜底 | pit_rag→extract→dcf→render 天然线性；PIT 安全是重点，非自主性 |

**口径**：demo 主菜（factor / model→risk）走 AgentRunner 展示自主推理；options/strategy/fundamental 用线性 flow 保证可演，在 handoff.md 和 Feature Checklist 明确标注"线性兜底，Week 2 迁 ReAct"。这样既守住架构铁律的展示面，又不赌 6 组一天全切 ReAct。

产出：一段写进 `Day5_Feature_Checklist.md` 的分组决策 + 各组 demo 入口确认（AgentRunner 或 execute_compose_flow）。

---

## 阶段 4：Day5 风险② — IDE 前端（OpenCode fork TS UI，替俞高磊做完）

在 `/Users/hendrixchen/Desktop/私募/opencode`（HKUST fork，dev 分支）的 `packages/app`（SolidJS，web+desktop 共用）做。

### 4.1 打通触发链
- OpenCode 通过 6 个 `quantcode-<group>` MCP server 暴露 `run_agent`。`/compose "..."` 命令 → 调对应组的 `run_agent`（start）→ 拿 `execution_trace` 流式渲染。
- 注册 `/compose` slash command：在 `packages/app/src/pages/session/use-session-commands.tsx` 用 `command.register()` 加 `slash: "compose"`。

### 4.2 六个面板（`packages/app/src/components/business-panels/`）
1. **Compose 视图**：读 execution_trace 的 skill_loaded / node_update 事件，展示流走到哪步。
2. **任务树**：读 ComposeTask schema（Day2 已有），T1/T1.1 层级。
3. **HumanGate 暂停点**：trace 出现 `human_gate` 事件 → 显示"⏸️ 等待人工审批" + approve/reject 按钮 → 调 `run_agent` resume（decision）。
4. **Schema 卡片**：trace 的 gen_schema 输出（json_schema 字段）→ 渲染卡片，可导出。
5. **Memory 浏览器**：读 `.quantcode/memory.db` / MEMORY.md（经一个只读 MCP tool 或本地文件桥）。
6. **会话 Resume**：列 checkpoints，从任意 checkpoint 恢复（调 resume）。

### 4.3 降级预案
若 TS 集成当天卡住：OpenCode spawn `python -m runner.agent_mcp_tool` + stdout JSONL 回流，面板读 JSONL。demo 用这条兜底，handoff 标注前端集成完成度。

产出：OpenCode 起 → 选组 → `/compose` 真触发 → 主区流式显示 → 六面板可用 → 人审可点。至少 model/risk/factor 三组在 UI 可切换触发（对齐 §10 硬性验收）。

> 范围声明：Day5 不做的面板（跨组通知中心 / Dog Food / Subagent 监控 UI / YAML 编辑器）不碰，handoff 标注 Week 2。

---

## 阶段 5：Day5 风险④ — 实现 Distill（+ 补强 Dream）

### 5.1 Distill（当前完全缺失）
新建 `dream/distill_prototype.py`，对齐 Design §4.1 "识别重复操作 → 候选新 SKILL.md 草案"：
- 输入：`.quantcode/rlhf_data.jsonl`（已有 state/action/reward）或 checkpoints trace。
- 逻辑：按 (tool_name, 参数模式) 聚类，统计高频操作序列（复用 `LoopDetector` 的签名思路，但阈值面向"跨会话重复"而非"死循环"）。
- 产出：识别 ≥1 个重复 pattern → 生成一份候选 `SKILL.md` 草案（markdown，写到 `artifacts/distill/candidate-<name>.md`），含 frontmatter + 步骤描述。
- 测试：`tests/test_distill_prototype.py`，喂构造的重复 trace，断言产出 ≥1 候选。

### 5.2 Dream 补强（现只读 checkpoint metadata）
- 现状：`_load_last_checkpoint_trace` 只取 thread_id/checkpoint_id，blob 粗解。
- 补强：优先走 rlhf_data.jsonl（结构化，已可用）聚合多条 trace 而非只读最后一条；real LLM 模式经 config.json 已接 DeepSeek。
- 达到 §3 验收："Dream 在 IDE 可触发，产出 ≥1 条 memory 可检索"。IDE 侧加 `/dream` 触发（阶段 4 的 Memory 浏览器能看到新条目）。

产出：Distill 原型能识别 ≥1 重复 pattern 出候选 SKILL.md；Dream 稳定产出可检索 memory。

---

## 阶段 6：收口两个小项

### 6.1 trigger_risk_flow 触发机制定型
现状：`tools/model/trigger_risk_flow.py` 已实现为**方式2（Blackboard 队列标志）**——写 `shared.pending_risk_reviews` 到 PROJECT scope，risk 组消费。但架构 §3.2 列了三种方式（直接 invoke / Blackboard 标志 / 队列），代码里没明确"就是方式2"。
- 动作：确认 risk 组 demo 消费这个队列的路径打通（model 写 → risk `run_agent` 读队列 → 处理）。在架构文档 §3.2 决策日志里标注"Day5 定型：采用 Blackboard 队列标志（方式2），直接 invoke 为 Week2 同步优化选项"。
- demo 里 model→risk 用这条链，陈镇鸿的 Blackboard 可视化对齐。

### 6.2 skill_loader 21 个测试失败（§10 要求全绿）
根因：meta-skill 实际在 `vendor/mimo-code/packages/opencode/src/skill/compose/.bundle/`，但 `tools/skills/loader.py` 找的是不存在的兄弟目录 `../MiMo-Code/`。
- 修复：在 `_find_meta_skill` 的搜索路径里加 vendored 路径 `PROJECT_ROOT / "vendor" / "mimo-code" / "packages" / "opencode" / "src" / "skill" / "compose" / ".bundle"`（放最前，优先命中）。
- 校验：`pytest tests/test_skill_loader.py` 21 个全过。

产出：trigger 机制文档定型 + 全量测试绿（§10 质量验收）。

---

## 执行顺序与验证

1. 阶段 0（合 PR25）→ 阶段 2（补 MCP）→ 阶段 6.2（修 skill_loader）：先让 main 测试全绿、基座稳。
2. 阶段 1（文档）+ 阶段 3（分组决策文档）：低风险，可并行穿插。
3. 阶段 5（Distill/Dream）：纯 Python，独立可测。
4. 阶段 4（IDE）：最大块，基于阶段 0 的 run_agent + 阶段 2 的 6 server。留降级预案。
5. 阶段 6.1（trigger 定型）：配合 model→risk demo。

每阶段结束跑 `python -m pytest -q`；IDE 阶段在 opencode fork 里 `npm run dev:desktop` 手验触发链。

产出物对齐 Day5 §9：Feature_Checklist（含分组决策、漂移修复记录、降级标注）、handoff.md（IDE 完成度、Week2 项）、更新后的三份顶层文档。

---

## 需要你注意的取舍

- **IDE 是最大不确定性**：TS 集成可能吃掉大半时间。计划里留了 JSONL 回流降级，建议阶段 4 开工先做 30 分钟 spike 验证 MCP 触发链能通，再决定投入深度。
- **risk 走 ReAct + 确定性后路**是折中：纯 ReAct 演示人审后容易空转（PR25 已识别并加了确定性路径），照此走。
- **options/strategy/fundamental 用线性 flow** 是有意降级，不是偷懒——demo 可以缩不能假，三组线性稳定 + handoff 标注 Week2 迁 ReAct，比赌 6 组全 ReAct 稳。

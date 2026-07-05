# Day 3 任务分配

> **里程碑**：多 Agent 自主协作 —— 引擎跑起来，5 个组的 Agent 各自能自主推理，跨组能协作，关键点能人审，长任务不失控。
> **工作方式**：任务导向，不规定时间线。下面给的是**功能目标 + 验收标准**，怎么实现、用什么方案、先做哪步，你自己判断。遇到设计选择先自己查资料/读源码做决定，卡住了（超过 30 分钟）就拉群讨论。

---

## 0. 先读文档，再动手

动手前把这三份读明白：
- `docs/PRD.md` —— 产品是什么、6 套流的功能
- `docs/Architecture_Spec.md` —— 三层架构 + §3.2 路由设计（重点）
- `docs/QuantCode_Design.md` —— 项目定位、三大模式、Compose 流

**一句话讲清我们在做什么**：QuantCode 是量化投研 Agent 系统，6 个组各有一套工作流（Compose 流），核心是"idea → 主线匹配 → 动态 Schema → 程序化验收 → 接入生产"。编排层用 Python/LangGraph，Agent 自主推理该调哪个 tool，不预定义流程图。

---

## 1. Day 3 要证明的五件事

1. **Agent 自主推理**：给任务 + tool + prompt，Agent 自己决定怎么做完，不是走写死的流程图
2. **跨组协作**：model 组把结果写进 Blackboard，risk 组能读到；组内私有数据别的组读不到
3. **人审断点**：风险超阈值时 Agent 暂停等人审批，批了再继续
4. **长任务不失控**：死循环 / 迭代过多 / 陷入循环时能自动中止
5. **主线匹配 + 动态 Schema**：Agent 读懂主线代码，判断一个 idea 该怎么兼容地接进去，现场生成校验 schema（核心壁垒，Lead 攻坚）

---

## 1.5 落地检验环节（必做，不是写完测试就算完）

**核心要求**：所有功能必须**在本地 OpenCode 里配置好并跑通测试**，不是"Python 里写个单测 mock 一下"就完事。

### 落地检验是什么
你写的 Python tools（如 model 组的 read_pr / extract_metadata）要能被 **OpenCode（TS）调起来**，在 OpenCode 的 compose 模式下，Agent 真的能调用你的 Python tools 完成任务。

### 具体步骤（每个人写完功能后都要做）

#### Step 1：配置你的 tools 到 OpenCode
根据你选择的解耦方式（MCP 或直接调用）：

**如果用 MCP Server**（推荐）：
```json
// .opencode/mimocode.json
{
  "mcp": {
    "quantcode_model_tools": {
      "type": "local",
      "command": ["python", "-m", "quantcode.tools.model"],
      "enabled": true
    }
  }
}
```

**如果直接写 TS wrapper**：
在 `.opencode/tools/` 下写 TS wrapper 调你的 Python 函数。

#### Step 2：启动 OpenCode
```bash
cd vendor/mimo-code/packages/opencode
npm run dev  # 或者你们的启动命令
```

#### Step 3：验证 tools 能被发现
- 启动后，OpenCode 应该能看到你注册的 tools
- 在 compose 模式下，Agent 能调用你的 tools

#### Step 4：跑一个端到端任务
**model 组举例**：
```bash
# 在 OpenCode CLI 或 UI 输入
/compose "处理 PR #123"

# Agent 应该：
# 1. 自主推理：我需要读 PR
# 2. 调用你的 read_pr tool（Python）
# 3. 自主推理：我需要提取元数据
# 4. 调用你的 extract_metadata tool
# 5. ...完成整个流程
```

**验证通过标准**：
- [ ] OpenCode 启动时能发现你的 tools（日志里有）
- [ ] Agent 能调用你的 tools（不报错）
- [ ] tools 返回的结果符合预期（schema 校验通过）
- [ ] 整个流程跑完，产出 artifact（如 ModelSpec.json）

### 常见问题排查
| 问题 | 可能原因 | 解决方案 |
|---|---|---|
| OpenCode 找不到 tool | MCP 配置路径错误 | 检查 `command` 能否在命令行直接运行 |
| tool 调用报错 | Python 环境不对 | 检查 virtualenv 是否激活 |
| Agent 不调你的 tool | tool description 不清楚 | 改 description，让 LLM 知道什么时候该调 |
| 返回格式不对 | schema 不匹配 | 用 Pydantic 严格校验 |

### 不及格的"伪落地"
❌ 只写了 Python 函数 + 单测，没配置到 OpenCode
❌ 配置了但没真的启动 OpenCode 验证
❌ 启动了但"好像不太对，算了先这样"
❌ 写了一堆 mock，实际 OpenCode 里跑不通

### 及格的"真落地"
✅ Python tool 写完 → 配置到 OpenCode → 启动验证 → Agent 能调 → 产出 artifact 符合预期
✅ 有 demo 录屏/截图证明"在 OpenCode 里真的跑起来了"
✅ 遇到问题了，排查日志，改配置，最终跑通

---

## 2. 尹一帆 · Agent 引擎 + Tool 系统 + 并发

**功能目标**：搭出能跑的 ReAct Agent 引擎——给定 system prompt + 一组 tool，Agent 能自主推理、调 tool、完成多步任务，中断能恢复，多个 Agent 能并发跑不打架。这是全组的底座，优先出一个能用的版本给大家接。

**自己去研究/决策的点**：
- `create_react_agent` 直接够用，还是用 `StateGraph` 自己搭以便插路由/gate？读 LangGraph 文档 + 试。
- tool 的统一接口怎么定义？可借鉴 MimoCode 的 `Tool.Def`（`vendor/mimo-code/.../src/tool/tool.ts`），也可直接用 LangChain tool。
- 怎么按组过滤 tool（model 组只看到 model 的 tool）？
- 拿一个 MimoCode 的 skill markdown（如 `plan`/`brainstorm`）喂进去当 system prompt，看 Agent 认不认——验证"复用 skill 作为工作流知识"这条路。
- checkpoint 怎么接（Day 2 已有基础）？
- **并发**：多个组的 Agent 同时跑，怎么隔离（thread_id？独立 state？），SQLite 会不会竞态（WAL 模式？）。

**验收标准（硬性）**：
- [ ] 一个 Agent 能自主完成 ≥3 步任务（自己决定 tool 顺序）
- [ ] tool 能按组隔离
- [ ] 至少 1 个 MimoCode skill markdown 能喂进去被使用
- [ ] Agent 中断后能从 checkpoint 恢复
- [ ] 多个 Agent 并发跑不冲突（至少 2 个同时跑通）
- [ ] 有测试覆盖

**交付**：能被 import 的 Agent 引擎 + 最小 demo + 一份"LangGraph 改写 MimoCode loop 缺了哪些配套"的清单（权限？gate？错误恢复？）。

---

## 3. 陈镇鸿 · Blackboard + model 组 Agent

**功能目标**：搭好跨组共享数据层（Blackboard），让 model 组 Agent 能完成"读 PR → 提取元数据 → 生成 ModelSpec → 写 Blackboard → 触发风控"。

**自己去研究/决策的点**：
- model 组需要哪些 tool？至少：read_pr / extract_metadata / generate_model_spec / write_blackboard / trigger_risk_flow，缺什么你补。
- Blackboard 用什么存？跟 Day 2 的 Memory 共用 SQLite 还是独立？
- 5-scope 怎么映射？PROJECT 跨组可读，GROUP 组内私有，权限检查在哪做？
- 跨组触发（trigger_risk_flow）怎么实现？直接 invoke risk Agent？还是写队列？
- **MCP 探索**（有余力）：TS 和 Python 怎么解耦？试试把 model tools 做成 Python MCP server，看 OpenCode 能不能调起来。

**验收标准（硬性）**：
- [ ] model 组 Agent 完整跑通：读 PR → 提取 → 生成 spec → 写 Blackboard
- [ ] Blackboard 跨组读：model 写 PROJECT，别组能读；写 GROUP，别组读不到
- [ ] Blackboard 持久化（重启还在）
- [ ] ModelSpec 通过 Day 1 schema 校验
- [ ] 有测试覆盖每个 tool + 集成

**交付**：Blackboard 服务 + model 组 tools + 端到端测试。有余力：MCP server 可行性验证报告。

---

## 4. 杨欣琳 · risk 组 Agent + 人审

**功能目标**：让 risk 组 Agent 完成"读 Blackboard → 算风控 → 生成 RiskProfile → 写 PR 评论"，并且风险超阈值时能暂停等人审。

**自己去研究/决策的点**：
- risk 组需要哪些 tool？至少：read_blackboard / calc_risk(用俞高磊的 stub) / generate_risk_profile / check_gate / write_pr_comment。
- permission 规则怎么定义（YAML？代码？）？参考 Architecture_Spec §3.5。
- `check_gate` 超阈值时怎么触发 interrupt？LangGraph 的 `NodeInterrupt` 怎么用？
- approve/reject 后怎么恢复（改 state + checkpoint 恢复）？
- 错误重试：tool 报错后 Agent 该重试还是换方案？设计一个策略。
- PR #12 的 eval() 顺便修了（改 match/case）。

**验收标准（硬性）**：
- [ ] risk 组 Agent 完整跑通：读 Blackboard → 算风控 → 生成 profile → 写 PR
- [ ] 人审场景：VaR 超阈值 → 暂停 → 日志"⏸️ 等待人工审批" → approve → 恢复 → 完成
- [ ] 正常场景：VaR 未超 → 直接写 PR，不暂停
- [ ] dedupe 生效：同一 PR 触发 2 次，只有 1 条评论
- [ ] RiskProfile 通过 schema 校验
- [ ] PR #12 eval() 移除，CI 通过

**交付**：risk 组 tools + permission 集成 + 两个场景测试（正常 + 人审）。

---

## 5. 俞高磊 · 路由函数 + 自研加固完整套件

**功能目标**：探索路由机制（代码规则 vs AI 路由，你自己研究判断），实现完整的自研加固套件（死循环 / 迭代上限 / 状态指纹 / RLHF 接入点）。

**为什么是你**：Day 2 你做过算法 stub，理解接口与实现分离。路由是个开放题，需要想清楚"控制流该怎么决策"。自研加固是差异化能力，需要探索。

**自己去研究/决策的点（开放探索）**：
- **路由函数是什么**？Architecture_Spec §3.2 写的是"代码规则"（permission 检查 / gate 检查 / 死循环检测），但你可以探索"AI 路由"可行性（用 LLM 判断下一步去哪）。读 LangGraph `add_conditional_edges` 文档，试两种方案，看哪个好。
- **死循环怎么检测**？滑动窗口统计同一 tool 高频调用？state 指纹重复？构造一个会死循环的 Agent 测试。
- **迭代上限**：MAX_ITERATIONS（100？200？），超了怎么办（中止？告警？）。
- **状态指纹循环检测**：state hash 重复 → 判定循环。怎么 hash？哪些字段纳入指纹？
- **RLHF 接入点**：每次 tool call 记录 `(state, action, reward)` 到 `.quantcode/rlhf_data.jsonl`，供后续微调/评估。reward 怎么定义（tool 成功=+1？gate 通过=+10？）。

**验收标准（硬性）**：
- [ ] 至少一种路由机制能跑（代码规则 or AI 路由，有对比更好）
- [ ] 死循环检测能识别明显死循环并中止
- [ ] 迭代上限生效（Agent 跑超步数自动中止）
- [ ] 状态指纹循环检测能识别重复 state
- [ ] RLHF 数据记录到 `.quantcode/rlhf_data.jsonl`，格式合法
- [ ] RiskTool stub 提供两组数据（正常 + 超阈值），杨欣琳能用
- [ ] 有测试覆盖每个加固机制

**交付**：路由函数实现 + 完整自研加固套件 + RiskTool stub + 一份"代码规则 vs AI 路由"对比报告（如果你试了两种）。

---

## 6. 刘炽 · Schema + SKILL.md（支持所有组）

**功能目标**：把 6 个组的 schema 定下来，给大家造测试数据，写至少 3 个组的 SKILL.md（参考 MimoCode 格式）。

**自己去研究/决策的点**：
- 6 个组各需要什么 schema？Day 1 有 ModelSpec，还缺 RiskProfile / FactorSpec / FundamentalSpec / OptionsSpec / StrategySpec。跟各组对接定字段。
- fixtures 准备什么？至少：sample_pr.diff / risk_metrics.json（两组：正常 + 超阈值）/ factor_backtest_result.json。
- SKILL.md 格式是什么？读 MimoCode 的 skill 文件（`vendor/mimo-code/.../skills/`），理解 frontmatter（name/description/tools）+ 正文（给 LLM 的指导）。
- 至少写 3 个组的 SKILL.md：model / risk / factor（其他 3 个组可后补）。描述各组 Agent 职责、可用 tool、工作流 tips。

**验收标准（硬性）**：
- [ ] 6 个组 schema 全部定义（用 Pydantic），各组能直接用
- [ ] fixtures 齐全：sample_pr.diff / risk_metrics.json / factor_backtest_result.json 等
- [ ] 至少 3 个组的 SKILL.md 完成（model/risk/factor），格式正确，能被 Agent 加载
- [ ] 所有 schema 有测试覆盖（校验能过）

**交付**：`schemas/*.py`（6 个）+ `tests/fixtures/*` + `.opencode/skills/{model,risk,factor}/SKILL.md`。

---

## 7. factor / fundamental / options 组的 Agent（分配待定）

**功能目标**：让这 3 个组的 Agent 也能各自跑通。早期可以用 stub 数据（Day 4 再接真实 API）。

**factor 组**：
- Tools：match_main_stub（简化版，读 fixture）/ gen_factor_schema / run_autoeval_stub / check_factor_gate / merge_to_main_stub
- 验收：Agent 能完成"idea → 生成 FactorSpec → 回测（stub）→ 阈值检查"

**fundamental 组**：
- Tools：pit_rag_search_stub（读 fixture）/ extract_financial / dcf_valuation / render_report_stub / request_human_review
- 验收：Agent 能完成"查语料（stub）→ 提取财报 → 估值 → 生成研报（stub）"

**options 组**：
- Tools：build_vol_surface / calc_greeks / run_options_backtest_stub
- 验收：Agent 能完成"构建波动率曲面 → 计算 Greeks → 回测（stub）"

**分配方案（你们商量）**：
- 陈镇鸿可以多做一个组（model + factor？）
- 杨欣琳可以多做一个组（risk + fundamental？）
- 新来的同学做 options
- 或者这 3 个组先做最小 stub，Day 4 补完整

**验收标准（硬性）**：
- [ ] 3 个组各有至少 3 个 tool（可以是 stub）
- [ ] 3 个组各能跑通一个完整流程（产出 artifact 通过 schema 校验）

---

## 8. Lead · match_main + gen_schema（核心壁垒）+ 跨组集成

**功能目标**：攻坚最初愿景的核心——让 Agent 能读主线代码，判断一个 idea 该怎么兼容地接进去，并现场生成校验 schema。第一阶段先做 factor 组（因子库相对简单）。

**match_main（主线匹配）**：
- Agent 读主线因子库代码（`factors/`），提取算子白名单
- 判断用户 idea（如"PB-ROE 因子"）是否兼容主线
- 给建议："可以接入，建议用 `fundamental_ratio` 算子"或"需要新增 `divide_fundamental` 算子"

**gen_schema（动态 Schema）**：
- 读了 idea + 主线后，LLM 现场生成一个 Pydantic schema（`PB_ROE_FactorSpec`）
- schema 包含参数定义（window / universe / numerator / denominator）+ validator（窗口太短拒绝）
- 生成的 schema 能校验用户后续填的参数

**跨组集成（有余力）**：
- 在各模块出来后，把 model→risk 跨组流打通
- 端到端测试：model Agent 写 Blackboard → risk Agent 被触发 → 算风控 → 写 PR

**验收标准（硬性）**：
- [ ] match_main 原型：Agent 能读 factor 主线库，判断"PB-ROE 因子"兼容性，给出接入建议
- [ ] gen_schema 原型：Agent 能为"PB-ROE 因子"现场生成 `FactorSpec` Pydantic 代码，代码合法、能 import
- [ ] （可选）model→risk 跨组流端到端打通

**交付**：match_main + gen_schema 原型（factor 组）+ demo + 技术报告（难点 / 解决方案 / 可扩展性）。

---

## 9. Dream 原型（有余力，可选）

**功能目标**：扫描 checkpoint 里的 execution trace，用 LLM 提取知识（重复 pattern / 教训 / 高频操作），写入 Memory。

**谁做**：有余力的人（或 Lead 协调）。

**验收**：
- [ ] 能扫一个 checkpoint trace，产出至少 1 条 memory 条目
- [ ] 写入的 memory 能被 `memory.search` 检索到

---

## 10. 收工验收（今晚汇报时对照）

### 核心里程碑（必须达成）
- [ ] **尹一帆**：Agent 引擎能跑，至少 1 个 MimoCode skill 能用，多 Agent 并发不冲突
- [ ] **陈镇鸿**：model 流端到端跑通，Blackboard 跨组权限正确
- [ ] **杨欣琳**：risk 流人审场景跑通（超阈值 → interrupt → approve → 恢复）
- [ ] **俞高磊**：完整自研加固套件（死循环/迭代上限/状态指纹/RLHF），至少一种路由机制能跑
- [ ] **刘炽**：6 个组 schema 冻结 + 至少 3 个组 SKILL.md
- [ ] **factor/fundamental/options**：3 个组各能跑通（可用 stub）
- [ ] **Lead**：match_main + gen_schema 原型（factor 组）

### 质量门槛
- [ ] **OpenCode 落地验证（硬性）**：所有功能必须在本地 OpenCode 里配置好并跑通，不是写完 Python 测试就算。至少 model/risk 两组能在 OpenCode compose 模式下真的调起 Python tools 完成任务。
- [ ] 全量测试通过（Day 1-3 累计 ≥80 个测试）
- [ ] CI 全绿
- [ ] 每个交付物有 README 或注释

### 加分项（有余力）
- [ ] model→risk 跨组流端到端打通
- [ ] MCP server 可行性验证
- [ ] Dream 原型能跑
- [ ] 代码规则 vs AI 路由对比报告

---

## 11. 自主发挥的边界

**鼓励的**：
- 查资料、读源码决定技术选型
- 设计你觉得合理的接口、数据结构
- 卡 30 分钟就拉群问，不要憋

**不鼓励的**：
- 闷头干一整天不说话，最后对不上
- 改了架构核心设计（如把 LangGraph 换掉）没确认

---

## 12. 今晚汇报（每人 5 分钟）

1. **功能达成**：用 demo 展示（能跑的代码 > PPT）
2. **最大坑 + 怎么解决**：技术坑还是协作坑
3. **明天继续什么**：未完成 / 要改进的
4. **对架构/文档反馈**：哪里不清楚、哪里有问题

---

**Day 3 一句话**：证明 Agent 能自主推理、能跨组协作、关键点能人审、长任务不失控，并攻坚核心壁垒（match_main + 动态 Schema）。


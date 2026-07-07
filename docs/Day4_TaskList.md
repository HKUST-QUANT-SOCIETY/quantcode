# Day 4 工作目标

> **里程碑**：主线接入 + 外部系统真实化 —— 把 Day 3 的 Agent 从"跑 mock/fixture/scripted pipeline"升级到"调真实 API、走真 ReAct、真实验收闭环"。
> **工作方式**：目标制，不规定时间线。给功能目标 + 验收标准，怎么实现你自己判断。卡 30 分钟拉群。

---

## 0. Day 3 收尾后的真实底座（动手前先认清）

Day 3 的 5 个 PR（#19/#17/#16/#18/#15）已全部合并入 main。当前底座：

**已就绪（别重做）**：
- 6 组 Pydantic schema 全有：model/factor/fundamental/risk(risk_profile)/options/strategy ✅
- options 组 3 tool + risk 组 5 tool + model 组 5 tool，已注册 + 按组隔离 ✅
- risk 全套：`tools/risk/` + `runner/risk_agent.py`（LangGraph interrupt/resume）+ HumanGate pydantic + 真实 GitHub PR comment（`tools/github_comments.py` urllib）+ dedupe ✅
- 路由加固：`runner/routing/`（guards/router/rlhf_logger/fingerprint）✅
- Blackboard 服务（5-scope + 跨组权限）✅
- AgentRunner（自搭 StateGraph ReAct）+ MCP server ✅

**已就绪但有 gap**：
- `risk_agent.py` 是 **scripted pipeline**（确定性 tool 序列），注释明说"待 AgentRunner 接入 route_gate"→ 不是真 ReAct
- `tools/model/read_pr.py` 是 **mock**（返回 fake diff）
- `flows/factor_autoeval.py` 的 `call_autoeval_api` 是 **mock**（`_mock_autoeval_result`）
- `tools/factor/` 的 match_main/gen_schema **没注册到 registry**（MCP factor 组暴露 0 tools），且是模板生成不是真 LLM
- `runner/acceptance.py` 有完整 check（IC/IR/pit_rag/research_pdf/risk_gate），但只被 `risk_agent`/`factor_autoeval_demo` 调，**没接成自动 merge/reject 闭环**

**完全没做**：
- strategy 组：无 group dir、无 tools、无 SKILL.md
- fundamental 组：有 group dir + 2 SKILL.md，但 **无 tools/ 目录**
- 控制平面（TS 侧）：组绑定 / compose 触发 / 状态可视化 全无

---

## 1. Day 4 五大目标

1. **真 ReAct**：risk/factor 两组从 scripted pipeline 接进 AgentRunner，Agent 自主决定 tool 顺序
2. **外部系统真实化**：read_pr / AutoEval / Chroma / Typst 至少 3 个从 mock 换真 API
3. **程序化验收闭环**：artifact → schema 校验 + assert 阈值 → 自动 merge/reject，不是人看
4. **补齐 strategy + fundamental**：strategy 从零搭起；fundamental tools 从无到有
5. **控制平面触发**：OpenCode（TS）里 `/compose` → 真调起 Python Agent

---

## 2. 尹一帆 · risk/factor 接进真 ReAct + MCP factor 注册 + 引擎 gap

**目标**：让 risk 和 factor 两组走 AgentRunner 自主推理（现在 risk 是 scripted、factor 压根没注册），并补 `day3_mimocode_loop_gaps.md` 的 Day 4 gap。

**功能目标**：
- **risk 接 AgentRunner**：`risk_agent.py` 的 scripted `run_tool_pipeline` 改成让 `AgentRunner(group="risk")` 自主调 `read_blackboard→calc_risk→generate_risk_profile→check_gate→write_pr_comment`。HumanGate interrupt 仍由 LangGraph 承载（route_gate 节点接 `should_interrupt`）。
- **factor 注册 + 接 AgentRunner**：把 `tools/factor/match_main`、`gen_schema` 注册进 registry（现在 MCP factor 组暴露 0 tools），让 `AgentRunner(group="factor")` 能跑"idea → match_main → gen_schema → autoeval → 验收"。
- **引擎 gap**（`day3_mimocode_loop_gaps.md` §2）：至少补 2 项——优先 **HumanGate interrupt 接 AgentRunner**（跟 risk 接入强耦合）+ **并行 tool call 或 token 裁剪**。
- **Dream 原型**（Design §4.1 P0 原型，Day 4）：扫 `checkpoints.db` 的 execution trace，用 LLM 提取重复 pattern / 教训 / 高频操作，写入 memory（`type=memory`）。优先级排在 risk/factor ReAct 之后——ReAct 是全组解锁项，Dream 是自我进化项，但今天必须有原型能跑出 ≥1 条 memory。
- **MCP 落地检验**：`QUANTCODE_GROUP=risk` / `=factor` 时 MCP 暴露对的 tool 集，OpenCode 能调起。

**验收**：
- [ ] risk 组经 AgentRunner 跑通人审场景（超阈值 → interrupt → approve → 恢复），不再是 scripted
- [ ] factor 组 tool 注册进 registry，`QUANTCODE_GROUP=factor` MCP 暴露 ≥2 tools
- [ ] factor 经 AgentRunner 跑通 match_main → gen_schema（≥3 步自主推理）
- [ ] ≥2 项引擎 gap 落地 + 测试
- [ ] Dream 原型：扫一个 trace 产出 ≥1 条 memory，能被 `memory.search` 检索到
- [ ] OpenCode 能经 MCP 调起 risk/factor tool（落地检验）

---

## 3. 杨欣琳 · risk ReAct 收尾 + GitHub 真实写入端到端

**目标**：#17 的 risk 全套已是真实 GitHub 接入，但走的是 scripted pipeline。Day 4 配合尹一帆把人审场景端到端真跑通（真 PR comment）。

**功能目标**：
- **人审场景真跑**：在测试 PR 上验证"VaR 超阈值 → interrupt → approve → 恢复 → 真写入 GitHub PR comment"全链路（不是 mock、不是 artifact 文件）。
- **正常场景**：未超阈值直接写 PR comment，不暂停。
- **dedupe 真实验证**：同一 PR 触发 2 次，GitHub 上只有 1 条评论（marker 去重）。
- **跟尹一帆对齐**：risk 接 AgentRunner 后，HumanGate 的 interrupt/resume 接口要和新 route_gate 节点对齐（`should_interrupt` + `build_interrupt_payload` + `Command(resume=)`）。
- **token 管理**：GitHub token 怎么注入（env var `GITHUB_TOKEN` / `GITHUB_REPOSITORY`）文档化，不入库。

**验收**：
- [ ] 测试 PR 上真出现 risk comment（截图/URL）
- [ ] 超阈值场景真 interrupt + approve 后恢复
- [ ] dedupe：同 PR 2 次触发 1 条评论
- [ ] token 注入方式有文档

---

## 4. 陈镇鸿 · read_pr 真实 GitHub + model→risk 跨组流端到端

**目标**：`read_pr` 从 mock 换真 GitHub API，model→risk 跨组流真跑通。

**功能目标**：
- **read_pr 真实化**：`tools/model/read_pr.py` 从返回 fake diff 改成真调 GitHub API 拉 PR diff（复用 #17 的 `tools/github_comments.py` 的 `github_request`，或抽公共 `tools/github.py`）。token 管理跟杨欣琳对齐。
- **model→risk 跨组流**：model Agent 经 AgentRunner 跑：read_pr（真 GitHub）→ extract_metadata → generate_model_spec → write_blackboard（PROJECT scope）→ trigger_risk_flow → risk Agent 被触发 → 读 Blackboard → 风控 → 人审/写评论。
- **跨组触发机制**：`trigger_risk_flow` 现状是 stub，Day 4 落地——直接 invoke risk Agent？写 Blackboard 待处理标志？还是队列？自己决策。
- **Blackboard 权限真验证**：model 写 PROJECT risk 能读，写 GROUP risk 读不到（在真实跨组流里验证，不是单测）。

**验收**：
- [ ] `read_pr` 真拉 GitHub PR diff（测试 PR 上验证）
- [ ] model→risk 跨组流端到端跑通（model 写 Blackboard → risk 触发 → 风控 → 人审/评论）
- [ ] Blackboard 跨组权限在真实流里正确
- [ ] ModelSpec 通过 schema 校验
- [ ] 集成测试覆盖跨组流

---

## 5. 俞高磊 · 控制平面 TS 侧接入 + 路由对比报告

**目标**：让 OpenCode（TS fork）能根据组绑定触发 Python 编排层、可视化 Agent 状态。这是 Day 5 IDE 上线的**硬前提**——Day 5 没时间再搭这条链路，Day 4 必须跑通"OpenCode 输入 → Python Agent 执行 → 状态回流"的最小闭环。

**功能目标**：
- **组绑定**（架构 §2.1）：登录后识别用户所属组。第一版可简化成配置/环境变量指定组（真 SSH key 绑定 Week 2 补），但文档标清简化了什么。**Day 4 至少要让 OpenCode 能把 `QUANTCODE_GROUP` 传给 Python AgentRunner/MCP**，否则组分发是空的。
- **触发 compose 流**（架构 §2.2）：OpenCode 里 `/compose "处理 PR #123"` → 调起 Python LangGraph Agent。解耦方式：经 MCP（尹一帆 server）还是 spawn Python？评估决策。**Day 4 必须能从 OpenCode 真触发一次完整 agent run 并拿到 artifact**，不是只在 Python 单测里跑。
- **Agent 状态可视化**（架构 §2.3）：显示 thought / tool_call / tool_result。Day 4 先做 `app.stream()` 按 node 流式日志回传 OpenCode（SSE 或 stdout），UI 美化 Day 5 补。**关键改进项**（架构标 ★）：显示当前加载的 skill / Blackboard 跨组数据流 / HumanGate 暂停点——这三项至少数据层接通（前端展示 Day 5）。
- **路由对比报告**（Day 3 待定）：代码规则路由（你 #16 已实现的 permission/gate/死循环）vs AI 路由（LLM 判断下一步）——可行性/延迟/可控性对比。

**验收**：
- [ ] OpenCode 登录后识别组并把组信息传给 Python（配置驱动即可）
- [ ] `/compose "..."` 触发 Python Agent 并拿到结果（端到端，非单测）
- [ ] Agent 执行过程流式回传 OpenCode（至少 thought/tool_call 日志）
- [ ] skill / Blackboard 流 / HumanGate 暂停点 三项数据层接通
- [ ] 路由对比报告完成
- [ ] 有测试或录屏证明控制平面→编排层打通

---

## 6. Lead · 程序化验收闭环 + match_main/gen_schema 接真 LLM

**目标**：把 Day 3 的 factor 原型从"模板生成"升级到"真 LLM"，并把验收接成自动闭环。

**功能目标**：
- **程序化验收闭环**：`runner/acceptance.py` 已有 `_check_factor_eval`（IC/IR/turnover/t_stat 阈值）。Day 4 接成：factor Agent 提交 → schema 校验 → 跑 acceptance → verdict=pass 自动建议 merge / fail 自动 reject。自动 merge/reject 怎么落地？GitHub PR review state？Blackboard 标志？
- **match_main 接真 LLM**：现在是 fixture + 关键词匹配（`tests/fixtures/factor_mainline/operators.py`）。Day 4 让 LLM 真读主线代码 + idea 给兼容性判断。主线代码怎么喂（全量？AST 提取算子签名？切片？）自己定。
- **gen_schema 接真 LLM**：现在是模板生成 Pydantic 代码。Day 4 让 LLM 现场生成 schema 代码，`exec` 隔离验证能 import + 能校验参数。**安全收口**：`exec` 生成代码的风险（沙箱？AST 白名单？只允许 Pydantic Field？）必须在报告里讲清。
- **跨组集成**：各模块出来后把 model→risk 跨组流端到端打通（跟陈镇鸿协作）。

**验收**：
- [ ] 程序化验收闭环：factor 提交 → schema 校验 + IC/IR 阈值 → 自动 merge/reject 决策
- [ ] match_main 接真 LLM：读主线代码判断"PB-ROE 因子"兼容性，给接入建议（不纯关键词）
- [ ] gen_schema 接真 LLM：为新 idea 现场生成合法 FactorSpec 代码，能 import + 能校验
- [ ] 技术报告：LLM 生成代码的安全收口 / 主线代码喂法 / 可扩展到其他组

---

## 7. 刘炽 · strategy 组从零 + fundamental tools 补完

**目标**：strategy 组从零搭起；fundamental 组从"有 SKILL.md 无 tools"补到能跑。

**功能目标**：
- **strategy 组**：
  - `.opencode/groups/strategy/`（group dir + tool_allowlist + SKILL.md）
  - `tools/strategy/`：`select_signals` / `combine_signals` / `run_strategy_backtest` / `deploy_strategy`（先 stub 能跑通流程）
  - 复用已合的 `schemas/strategy.py`（StrategySpec/StrategyReport/SignalCandidate）
  - 经 AgentRunner 跑通"候选信号 → 选择 → 组合 → 回测 → 产出 StrategyReport"
- **fundamental 组**：
  - `tools/fundamental/`：`pit_rag_search` / `extract_financial` / `dcf_valuation` / `render_report`（先 stub，Chroma/Typst 真实化见 §8）
  - 复用已合的 `schemas/fundamental.py`
  - 经 AgentRunner 跑通"查语料 → 提取财报 → 估值 → 生成研报"
- **fixtures 补充**：strategy 回测结果 fixture；真实 PR diff 样本给陈镇鸿 read_pr 用。

**验收**：
- [ ] strategy 组：group dir + SKILL.md + ≥3 tool + 能跑通产出 StrategyReport（schema 校验过）
- [ ] fundamental 组：≥3 tool + 能跑通产出 ResearchResult（schema 校验过）
- [ ] 两组 tool 注册进 registry，MCP 按组暴露正确
- [ ] fixtures 齐全

---

## 8. factor / fundamental / options 组外部系统真实化

**目标**：Day 3 是 stub/mock 的 tool，Day 4 接真实外部系统。

**factor 组**（Lead/肖骥超）：
- AutoEval API 真实接入（`flows/factor_autoeval.py` 的 `_mock_autoeval_result` 换真调 AutoEval，IC/IR 是真数）。
- 验收：Agent 提交因子 → 真回测 → IC/IR 阈值验收 → merge/reject（接 §6 验收闭环）。

**fundamental 组**：
- Chroma 向量库接入（`pit_rag_search` 从 stub 换真 Chroma）。
- Typst 渲染（研报 PDF）。
- 时点安全：pit_rag 强制 `published_at <= as_of_date`（接 `acceptance._check_pit_rag`）。

**options 组**（刘炽）：
- `build_vol_surface` / `calc_greeks` / `run_options_backtest` 至少 1 个从 stub 真实化。

**验收**：
- [ ] factor：AutoEval API 真实调通（不再 mock）
- [ ] fundamental：Chroma + Typst 至少一个真实接入
- [ ] options：至少 1 个 tool 真实化
- [ ] 真实接入的 tool 有端到端验证（产出 valid artifact）

---

## 9. 落地检验（同 Day 3，硬性）

所有功能必须在**本地 OpenCode 里配置好并跑通**，不是"Python 单测 mock 一下"。

**硬性**：至少 model + risk 两组能在 OpenCode compose 模式下真调起 Python tools（经 MCP）。Day 4 新增的 strategy 组也要能触发。

---

## 10. 收工验收（今晚汇报对照）

### 核心里程碑
- [ ] **尹一帆**：risk/factor 接进真 ReAct（AgentRunner）+ factor tool 注册 + ≥2 引擎 gap + Dream 原型
- [ ] **杨欣琳**：risk 人审场景真 PR comment 端到端 + dedupe 真验证
- [ ] **陈镇鸿**：read_pr 真实 GitHub + model→risk 跨组流端到端
- [ ] **俞高磊**：控制平面 TS 侧触发编排层（端到端，非单测）+ 路由对比报告
- [ ] **Lead**：程序化验收闭环 + match_main/gen_schema 接真 LLM
- [ ] **刘炽**：strategy 组从零搭起 + fundamental tools 补完
- [ ] **factor/fundamental/options**：≥3 个 tool 真实化（AutoEval/Chroma/Typst）

### 质量门槛
- [ ] **OpenCode 落地验证（硬性）**：model + risk + strategy 三组能在 OpenCode compose 下真调 Python tools
- [ ] **控制平面→编排层打通（硬性，Day 5 前提）**：OpenCode `/compose` 能真触发 Python Agent + 状态流式回流
- [ ] **外部系统真实接入**：GitHub + AutoEval + Chroma/Typst 至少 3 个真 API
- [ ] **程序化验收闭环**：至少 factor 组走通"提交 → 校验 → 阈值 → merge/reject"
- [ ] 全量测试通过（除已知环境性 skill_loader/registry 大小写问题）
- [ ] CI 全绿

### Day 4 是 Day 5 IDE 上线的硬前提
Day 5 要做"IDE 初步上线 + 6 组全通 demo"。下列 Day 4 产出**必须就位**，否则 Day 5 没东西可演示：
1. 控制平面→编排层链路通（俞高磊）— 否则 IDE 触发不了 agent
2. 6 组 tool 全注册 + 能经 MCP 调起（尹一帆+刘炽）— 否则 IDE 无 agent 可跑
3. risk 人审 + factor 验收两个标志性场景真跑通（杨欣琳+Lead）— demo 主菜
4. strategy + fundamental 补完（刘炽）— 否则 6 组只有 4 组

> 若 Day 4 收工时上述任一项未完成，Day 5 上线推迟，Day 4 未完成项优先级压过 Day 5 新功能。

---

## 11. 已知环境债

- `tests/test_skill_loader.py` 20 个失败：本机 `vendor/mimo-code` 目录名与 loader 期望的 `MiMo-Code`/`Mimo-code` 对不上。要么改 loader 路径匹配，要么 symlink。main 上一直失败。
- `tests/test_registry.py::test_project_root_points_to_quantcode`：断言 `PROJECT_ROOT.name == "quantcode"`，但本地仓库目录是 `QUANTcode`。测试改成大小写不敏感，或 CI 用小写目录名。

---

**Day 4 一句话**：把 Day 3 的 mock/scripted 换成真实——真 ReAct、真 GitHub、真 AutoEval、真验收闭环、真控制平面触发，并补齐 strategy + fundamental。Day 5 拿这个做 investor demo。

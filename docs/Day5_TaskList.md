# Day 5 工作目标

> **里程碑**：IDE 初步上线 + PRD/Design 功能全部实现 + investor demo。Day 4 的工程目标是 Day 5 的硬前提——若 Day 4 §10 的 4 项前置未完成，先补 Day 4，Day 5 新功能让位。
> **工作方式**：目标制。给功能目标 + 验收标准，怎么实现你自己判断。卡 30 分钟拉群。

---

## 0. Day 5 的定位：从"能跑"到"能演示上线"

Day 1-4 是把功能造出来；Day 5 是把功能**装进 IDE、跑成完整 demo、交付给投资人/新成员**。Day 5 不再开新业务能力（6 组 Compose 流 + 三大模式 + 引擎 + 验收闭环 Day 4 必须已就绪），只做三件事：

1. **IDE 上线**：OpenCode fork 里把控制平面→编排层链路、6 组分发、状态可视化、关键面板接成**可用产品**（Day 4 是数据层接通，Day 5 是 UI 层可用）。
2. **PRD/Design 功能收口**：对照 PRD §3.1 P0 + Design §4 功能清单，把 Day 4 还剩的尾巴清掉，确保**设计里写的功能全部实现**。
3. **Demo + 交付物**：investor demo（录屏兜底）+ handoff.md + Quick Start + artifacts 整理。

---

## 1. Day 5 五大目标

1. **IDE 初步上线**：OpenCode 里 `/compose` 真触发、6 组可切换、状态可视化可用、人审断点可见
2. **6 组 Compose 流全通**：每组至少一个真实 idea 进、valid artifact 出（Day 4 没 finish 的组 Day 5 必须收口）
3. **跨组流端到端 demo 可演**：model→risk（含人审）+ factor→strategy 两条跨组链路
4. **PRD/Design 功能对照清单清零**：逐条核对，未实现的补、降级的标注
5. **investor demo + 交付物齐全**：录屏 + PPT + handoff + Quick Start

---

## 2. 俞高磊 · IDE 前端集成（Day 5 核心）

**目标**：把 Day 4 接通的控制平面→编排层链路，在 OpenCode desktop fork 里做成**可用产品**。这是 IDE 上线的主体。

**功能目标**（对照 Design §4.4 前端功能）：
- **主视图 + 组识别**：登录后顶部显示当前组（基于 Day 4 的组绑定），可切换组（Day 5 可手动切换，Week 2 接 SSH key 自动）。
- **Compose 触发**：输入框 `/compose "..."` 真触发 Python AgentRunner，主对话区流式显示 thought / tool_call / tool_result（接 Day 4 的 stream 回流）。
- **Compose 视图面板**：当前 Compose 流走到哪一步、卡在哪、等什么（接 skill 加载状态 + 节点进度）。
- **任务树面板**：T1/T1.1/T1.2 层级，点击看 progress（接 ComposeTask schema，Day 2 已有）。
- **HumanGate 暂停点**：VaR 超阈值时 UI 显示"⏸️ 等待人工审批"，approve/reject 按钮接 Day 4 的 resume。
- **Schema 卡片**：agent 返回的 Pydantic schema 用 `model_json_schema()` 渲染成卡片，可导出（接 Day 4 gen_schema）。
- **Memory 浏览器**：查看 MEMORY.md / checkpoint / tasks（接 Day 2 Memory FTS5）。
- **会话 Resume**：任意会话从任意 checkpoint 恢复（接 Day 2 checkpoint）。

**Day 5 不做的面板**（P1，Week 2）：跨组通知中心、Dog Food 面板、Subagent 监控 UI、人工编排 YAML 编辑器——但要在 handoff.md 标清未做。

**验收**：
- [ ] OpenCode 启动 → 选组 → `/compose "测 PB-ROE 因子"` 真触发 factor Agent，主区流式显示推理过程
- [ ] Compose 视图 + 任务树 + HumanGate 暂停点 + Schema 卡片 + Memory 浏览器 + 会话 Resume 六个面板可用
- [ ] 人审场景在 UI 里可见：超阈值暂停 → 点 approve → 继续
- [ ] 至少 3 个组（model/risk/factor）能在 UI 里切换并触发

---

## 3. 尹一帆 · 6 组 Agent 全通收口 + Dream/Distill 接进 IDE

**目标**：确保 6 组都能经 AgentRunner 跑通，把 Day 4 的引擎能力（Dream/ReAct/gap）在 IDE 里跑起来。

**功能目标**：
- **6 组 ReAct 全通**：逐组验证 `AgentRunner(group=X)` 能跑 ≥3 步自主推理 + 产出 valid artifact。Day 4 没接完的组（strategy/fundamental/options）Day 5 收口。
- **Dream 接 IDE**：Day 4 的 Dream 原型做成可触发（`/dream` 或后台任务），扫 trace 提取 memory，在 Memory 浏览器里能看到新提取的条目。
- **Distill 原型**（Design §4.1 P1，有余力）：识别重复操作 → 候选新 SKILL.md 草案。Day 5 至少出原型，能识别一个重复 pattern。
- **引擎稳定性**：Day 4 的 gap（并行 tool / token 裁剪 / LLM 重试）在 demo 场景下不翻车——长任务不爆 context、抖动不挂。

**验收**：
- [ ] 6 组各跑通一个完整流程，产出 artifact 通过 schema 校验
- [ ] Dream 在 IDE 可触发，产出 ≥1 条 memory 可检索
- [ ] （有余力）Distill 原型识别 ≥1 个重复 pattern
- [ ] demo 场景下引擎稳定（无 context 爆 / 无挂死）

---

## 4. 杨欣琳 · risk demo 场景打磨 + HumanGate IDE 集成

**目标**：把 risk 人审场景做成 demo 主菜，并在 IDE 里完整呈现。

**功能目标**：
- **risk demo 场景**：model→risk 跨组流端到端可演——提交 PR → risk 触发 → 风控计算 → VaR 超阈值 → UI 暂停 → 人审 approve → 恢复 → 真写 PR comment。每一步在 IDE 可见。
- **HumanGate IDE 集成**：跟俞高磊对齐，HumanGate 暂停点在 UI 里正确显示，approve/reject 真接 resume。
- **正常 vs 超阈值双场景**：demo 能切换演示两种路径（未超阈值直接过 / 超阈值人审）。
- **dedupe demo**：现场触发 2 次同 PR，GitHub 上只 1 条评论。
- **RiskProfile 验收**：产出符合 schema + 通过 `acceptance._check_risk_gate` 阈值。

**验收**：
- [ ] model→risk 人审场景端到端可演（含真 PR comment）
- [ ] HumanGate 暂停/approve 在 IDE UI 正确呈现
- [ ] 双场景可切换演示
- [ ] dedupe 现场验证

---

## 5. 陈镇鸿 · model→risk 跨组流 demo + Blackboard 可视化数据

**目标**：跨组流做成可演 demo，Blackboard 数据流在 IDE 可见。

**功能目标**：
- **model→risk demo 主链路**：read_pr（真 GitHub）→ extract → ModelSpec → write_blackboard → trigger_risk_flow → risk 接力。整条链录屏可演。
- **Blackboard 跨组可视化数据**：跟俞高磊对齐，IDE 里能看到"model 写了 PROJECT scope 的 model_specs，risk 读到了"——谁写了什么、谁读了什么（架构 §2.3 ★ 改进项）。
- **跨组权限 demo**：演示 model 写 GROUP scope，risk 组读不到（权限隔离可见）。
- **trigger_risk_flow 机制定型**：Day 4 决策的触发机制（直接 invoke / Blackboard 标志 / 队列）在 demo 里稳定可演。

**验收**：
- [ ] model→risk 跨组流录屏可演
- [ ] Blackboard 跨组数据流在 IDE 可见
- [ ] 跨组权限隔离可演示
- [ ] ModelSpec + RiskProfile 双 schema 校验通过

---

## 6. Lead · factor demo 场景 + 验收闭环 demo + PRD/Design 功能对照清零

**目标**：factor 验收闭环做成 demo 主菜；对照 PRD/Design 把功能清单逐条核对清零。

**功能目标**：
- **factor demo 场景**：`/compose "测 PB-ROE 因子"` → match_main（真 LLM 读主线）→ gen_schema（真 LLM 生成）→ autoeval（真 API 回测）→ IC/IR 阈值验收 → merge/reject 决策。整条链录屏可演。
- **程序化验收闭环 demo**：现场展示"提交 → schema 校验 → assert 阈值 → 自动 merge/reject"，verdict 可见。
- **PRD/Design 功能对照清单**：逐条核对 PRD §3.1 P0 + §4 功能详述 + Design §4 功能清单，产出一份 `docs/Day5_Feature_Checklist.md`：
  - ✅ 已实现 / 🔧 降级实现（标注降级到什么）/ ❌ 未实现（标注原因 + Week 2 计划）
  - 重点核对：6 组 Compose 流、三大模式契约、共用基础设施（验收 runner / schema 校验 / CI gate / dedupe）、Memory FTS5、Checkpoint、Dream、Schema 动态生成、match_main、跨组协作触发
- **跨组集成兜底**：各模块出来后把 model→risk + factor→strategy 两条跨组流端到端打通。

**验收**：
- [ ] factor 验收闭环 demo 可演（真 LLM + 真 AutoEval + 自动 merge/reject）
- [ ] `docs/Day5_Feature_Checklist.md` 完成，PRD/Design P0 功能逐条有结论
- [ ] （可选）factor→strategy 跨组流打通

---

## 7. 刘炽 · strategy/fundamental/options demo 收口 + fixtures + schema 终验

**目标**：Day 4 补的 strategy/fundamental 两组 + options 真实化，在 Day 5 做成可演 demo。

**功能目标**：
- **strategy demo**：`/compose "组合 PB-ROE + 动量信号"` → select → combine → backtest → StrategyReport（schema 校验过）。
- **fundamental demo**：`/compose "分析公司 X 估值"` → pit_rag（真 Chroma，时点安全）→ extract_financial → dcf → render_report（Typst PDF）→ 人审。
- **options demo**：`/compose "GC 期权 Greeks"` → build_vol_surface → calc_greeks → backtest。
- **fixtures 终验**：6 组 demo 用的 fixtures 齐全 + 真实（不是占位）。
- **6 组 schema 终验**：所有 demo 产出的 artifact 通过对应 Pydantic schema 校验。

**验收**：
- [ ] strategy/fundamental/options 三组各跑通一个 demo 场景，artifact 过 schema 校验
- [ ] fundamental 的 pit_rag 时点安全在 demo 里可验（`published_at <= as_of_date`）
- [ ] fixtures 齐全真实
- [ ] 6 组 schema 全部终验通过

---

## 8. Demo 场景编排（investor demo 30 分钟）

**场景 1：因子评估 + 验收闭环（8 分钟，Lead）**
- `/compose "测 PB-ROE 因子"` → match_main（真 LLM 读主线，判兼容）→ gen_schema（真 LLM 生成 FactorSpec）→ AutoEval 真回测 → IC/IR 阈值验收 → merge/reject 决策
- 展示 IDE：Compose 视图 + Schema 卡片 + 任务树
- 展示 checkpoint 中断恢复

**场景 2：模型提交 → 风控审批（8 分钟，杨欣琳+陈镇鸿）**
- model Agent：read_pr（真 GitHub）→ ModelSpec → write_blackboard
- risk Agent 被触发：读 Blackboard → 风控 → VaR 超阈值 → **IDE 暂停** → 人审 approve → 恢复 → 真写 PR comment
- 展示 IDE：HumanGate 暂停点 + Blackboard 跨组数据流
- 展示 dedupe

**场景 3：基本面研报（7 分钟，刘炽）**
- `/compose "分析公司 X"` → pit_rag（真 Chroma，时点安全）→ 财报提取 → DCF → Typst 渲染 PDF → 人审
- 展示程序化验收（`published_at <= as_of_date`）

**场景 4：自研加固 + 自我进化（5 分钟，尹一帆）**
- 展示死循环检测自动中止
- 展示 Dream 提取知识写入 Memory（IDE Memory 浏览器可见）
- 展示 RLHF 数据收集（`.quantcode/rlhf_data.jsonl`）

**收尾（2 分钟，Lead）**：6 套流全通演示 + roadmap + Q&A

---

## 9. 交付物（Day 5 必须齐）

- [ ] **Demo 录屏**（兜底）：至少场景 1 + 场景 2 两个核心场景录好（防现场翻车）
- [ ] **PPT deck**（8-10 页）：问题定位 / 架构 / 精选场景 / roadmap
- [ ] **`docs/handoff.md`**：完成情况 + 已知问题 + Week 2+ 规划 + 技术债 + PRD/Design 降级项
- [ ] **`docs/Day5_Feature_Checklist.md`**：PRD/Design P0 功能逐条对照结论
- [ ] **artifacts 整理**：FactorSpec / RiskProfile / research.pdf / StrategyReport 等 demo 产出归档
- [ ] **README Quick Start**：新人 30 分钟跑起来（clone + 配 provider + pip install + 起一个 compose 流）

---

## 10. 收工验收（investor demo 前 checklist）

### IDE 上线（硬性）
- [ ] OpenCode fork 能起，`/compose` 真触发 Python Agent
- [ ] 6 组可切换，至少 3 组能触发并产出
- [ ] Compose 视图 / 任务树 / HumanGate 暂停点 / Schema 卡片 / Memory 浏览器 / 会话 Resume 可用
- [ ] 状态流式回流（thought / tool_call / tool_result）

### PRD/Design 功能实现（硬性）
- [ ] 6 套 Compose 流全通（各产出 valid artifact）
- [ ] 三大模式契约落地（ComposeTask / BlackboardState / HumanGate）
- [ ] 共用基础设施：验收 runner / schema 校验 / CI gate / dedupe
- [ ] Memory FTS5 + Checkpoint + Dream 原型
- [ ] Schema 动态生成 + match_main（真 LLM）
- [ ] 跨组协作触发（model→risk / factor→strategy）
- [ ] `Day5_Feature_Checklist.md` 逐条有结论

### Demo + 交付物
- [ ] 4 个 demo 场景可演（录屏兜底 ≥2 个）
- [ ] PPT + handoff.md + Quick Start + artifacts 齐全

### 质量
- [ ] 全量测试通过（除已知环境性 skill_loader/registry 问题）
- [ ] CI 全绿
- [ ] demo 场景下引擎稳定（无 context 爆 / 无挂死 / 无死循环）

---

## 11. 若 Day 4 前置未完成的降级方案

Day 5 开工前先核对 Day 4 §10 的 4 项前置。若未完成，按以下降级：

| 未完成的前置 | Day 5 降级 |
|---|---|
| 控制平面→编排层未通 | IDE demo 改用"Python 直接跑 + 录屏"，前端集成推 Week 2 |
| 6 组 tool 未全注册 | demo 只演已通组（model/risk/factor），其余用录屏/截图 |
| risk 人审 / factor 验收未通 | demo 主菜换 options/strategy，handoff 标注风险 |
| strategy/fundamental 未补 | 6 组演示改 4 组，handoff 标注 |

**原则**：demo 可以缩，但不能假。宁可演 3 个真跑通的场景，不演 6 个 mock 的。

---

**Day 5 一句话**：把 Day 4 造好的能力装进 IDE、跑成完整 demo、对照 PRD/Design 清零功能清单，交付给投资人和新成员——从"能跑"到"能上线、能演示、能交棒"。

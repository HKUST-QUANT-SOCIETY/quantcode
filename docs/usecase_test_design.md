# QuantCode 用例测试设计

> **目的**：从「用户/组怎么用 QuantCode」出发设计验收用例，而不是只堆 tool 单测。  
> **范围**：6 组 Compose 流 + 跨组协作 + 平台能力（HumanGate / Checkpoint / Schema / IDE 入口）。  
> **原则**：每个用例 = Actor + 目标 + 前置 + 步骤 + 期望产物/断言；能自动化的进 pytest / accept 脚本，不能自动化的标手工/录屏。  
> **更新**：2026-07-24

---

## 1. 测试分层（建议怎么跑）

```
L0  契约/单测        schemas · registry · tool 单步          每次 PR / CI
L1  组内流水线        一组 tool 链 → valid artifact          每次 PR / CI
L2  Agent 路径        ScriptedLLM AgentRunner / flow         每次 PR / CI
L3  跨组 / 人审       model→risk、interrupt/resume           每次 PR / CI（可 mock 外网）
L4  验收套件          accept / demo_bridge 一键绿             Day 收工 / release
L5  真环境 / IDE      真 LLM · 真 GitHub · OpenCode UI        手工 + 录屏（冒烟）
```

| 层级 | 谁跑 | 失败意味着什么 |
|------|------|----------------|
| L0–L3 | CI | 功能回退，不能合 |
| L4 | Owner / Lead | demo 不能交差 |
| L5 | Lead 串场 | investor demo 有风险，可用录屏兜底 |

已有基础：`tests/` 约 50+ 文件、`scripts/accept_jerry_day5.py`（Jerry 三组）、`runner/acceptance.py`（factor/risk 阈值）。  
缺口：缺少 **统一用例编号 + 全组 L4 验收套件 + IDE 冒烟清单**。

---

## 2. Actor（谁在用）

| ID | Actor | 诉求 |
|----|--------|------|
| A1 | 因子研究员 | idea → 回测报告 → 过/不过阈值 |
| A2 | 模型同学 | PR → ModelSpec → 自动进风控 |
| A3 | 风控同学 | 读队列 → 算风险 → 超阈人审 → 写 PR comment |
| A4 | 基本面研究员 | 时点安全检索 → 估值 → 研报 → 人审 |
| A5 | 策略同学 | 选信号 → 组合 → 回测 → 是否部署 |
| A6 | 期权同学 | 曲面 → Greeks → 风险摘要 |
| A7 | Lead / Demo 操作员 | IDE `/compose` 切换组、串场演示 |
| A8 | 系统本身 | Checkpoint 恢复、死循环中止、dedupe、Memory |

---

## 3. 用例总表（P0 必须绿）

优先级：`P0` = Day5/合入 blocker；`P1` = Week2；`P2` = 增强。

### 3.1 平台与入口

| 用例 ID | 标题 | Actor | P | 层级 | 期望 | 现状/建议落点 |
|---------|------|-------|---|------|------|----------------|
| UC-PLT-01 | 按组加载 allowlist tools | A7 | P0 | L0 | `get_tools_for_group(X)` 仅返回白名单 | `test_registry` / 各组 `test_*_tools` |
| UC-PLT-02 | skill 可加载 | A7 | P0 | L0 | 6 组 compose skill 文本含主工具名 | `test_skill_loader` + 补全 6 组 |
| UC-PLT-03 | run_agent 无 group 报错 | A7 | P0 | L2 | status=error，提示 QUANTCODE_GROUP | `test_agent_mcp_tool` |
| UC-PLT-04 | demo_bridge 可触发一组 | A7 | P0 | L4 | 退出码 0 或明确 waiting_for_human | `test_demo_bridge` |
| UC-PLT-05 | OpenCode `/compose` 触发 Python | A7 | P0 | L5 | 主区有 thought/tool 回流 | **手工清单**（见 §6） |
| UC-PLT-06 | Checkpoint 中断后续跑 | A8 | P0 | L2 | 同 thread_id resume 不丢状态 | `test_checkpoint_recovery` |
| UC-PLT-07 | 死循环检测中止 | A8 | P0 | L2 | 重复 tool 调用被 abort | `test_loop_detection` |
| UC-PLT-08 | Blackboard GROUP 隔离 | A8 | P0 | L1 | 组 A 写的 GROUP 数据组 B 读不到 | `test_blackboard_*` / `test_memory_group_isolation` |

### 3.2 Factor（场景 1）

| 用例 ID | 标题 | P | 期望 | 落点 |
|---------|------|---|------|------|
| UC-FAC-01 | match_main → gen_schema → autoeval 链 | P0 | 产出 FactorReport / 等价 artifact，schema 过 | `test_factor_autoeval_flow` |
| UC-FAC-02 | IC/IR 阈值验收 pass | P0 | `run_acceptance_checks("factor:...")` 过 | `test_acceptance` |
| UC-FAC-03 | 阈值不达标 → reject/不 merge | P0 | verdict/决策为拒绝类 | 补：acceptance 负例 |
| UC-FAC-04 | 真 AutoEval HTTP | P1 | 非 mock payload | 外网/token；CI 可 skip |
| UC-FAC-05 | `/compose "测 PB-ROE 因子"` IDE | P0 | L5 可演或录屏 | 手工 |

### 3.3 Model → Risk（场景 2，跨组）

| 用例 ID | 标题 | P | 期望 | 落点 |
|---------|------|---|------|------|
| UC-MOD-01 | read_pr → ModelSpec → write_blackboard | P0 | Blackboard 有 pending risk 队列项 | `test_model_tools` / flow |
| UC-MOD-02 | trigger_risk_flow 写入队列标志 | P0 | `shared.pending_risk_reviews` 非空 | Architecture 方式 2 |
| UC-RSK-01 | 读 Blackboard → calc_risk → RiskProfile | P0 | schema 过 | `test_risk_*` |
| UC-RSK-02 | 高风险 → HumanGate 暂停 | P0 | `waiting_for_human` / `__interrupt__` | `test_risk_flow` / mcp |
| UC-RSK-03 | approve 后写 PR comment | P0 | comment artifact 或 GitHub 1 条 | `test_risk_github_e2e`（可 mock） |
| UC-RSK-04 | reject 后不写 comment / status=rejected | P0 | 明确拒绝态 | mcp reject 用例 |
| UC-RSK-05 | 同 PR 触发 2 次 dedupe | P0 | GitHub/本地只 1 条副作用 | `test_risk_dedupe` / `test_dedupe` |
| UC-XGRP-01 | model 提交后 risk 可消费同一 blackboard 项 | P0 | 跨组 E2E（可 Scripted） | **建议新增** `tests/test_usecase_model_risk_e2e.py` |

### 3.4 Fundamental（场景 3 · Jerry）

| 用例 ID | 标题 | P | 期望 | 落点 |
|---------|------|---|------|------|
| UC-FND-01 | pit_rag PIT 过滤 | P0 | `filtered_count≥1`，无 DOC-LEAK | `test_fundamental_tools` |
| UC-FND-02 | backend=chroma（有 chromadb） | P0 | 返回 backend chroma | accept + tools |
| UC-FND-03 | extract → dcf → render filled | P0 | md 含 FCF/Fair value，非空 stub | day5 demos |
| UC-FND-04 | 人审 interrupt → resume approve | P0 | waiting → task_status=done | `test_fundamental_human_gate` |
| UC-FND-05 | ResearchResult schema | P0 | Pydantic 过 | schema final |
| UC-FND-06 | Typst PDF 可选 | P1 | 有 typst 则 pdf_filled | accept 软断言 |

### 3.5 Strategy（Jerry）

| 用例 ID | 标题 | P | 期望 | 落点 |
|---------|------|---|------|------|
| UC-STR-01 | select → combine → backtest → deploy | P0 | StrategyReport + verdict 字段存在 | `test_day5_jerry_demos` / strategy tools |
| UC-STR-02 | StrategyReport schema | P0 | 校验过 | schema final |
| UC-STR-03 | AgentRunner 多步 ≥2 iterations | P0 | ScriptedLLM | accept_jerry |

### 3.6 Options（Jerry）

| 用例 ID | 标题 | P | 期望 | 落点 |
|---------|------|---|------|------|
| UC-OPT-01 | vol_surface → greeks → backtest | P0 | OptionsRisk bundle 三块齐全 | day5 demos |
| UC-OPT-02 | surface points > 0，delta 非空 | P0 | 数值断言 | options tools |
| UC-OPT-03 | Options* schema | P0 | 校验过 | schema final |

### 3.7 自我进化（场景 4）

| 用例 ID | 标题 | P | 期望 | 落点 |
|---------|------|---|------|------|
| UC-DRM-01 | Dream 写入 ≥1 条可检索 memory | P1 | search 命中 | `test_dream_prototype` |
| UC-DST-01 | Distill 产出 skill 草案 | P2 | 文件或结构存在 | `test_distill_prototype` |

---

## 4. 推荐的「用例验收套件」结构

不要只靠散落的 `test_*.py`。建议加一层 **按 Actor 场景命名的套件**：

```
scripts/
  accept_quantcode_p0.py          # 编排全组 P0（或分 group flag）
  accept_jerry_day5.py            # 已有：STR/FND/OPT

tests/usecases/
  test_uc_platform.py             # UC-PLT-*
  test_uc_factor.py                # UC-FAC-*
  test_uc_model_risk_e2e.py       # UC-XGRP-01 + RSK/MOD
  test_uc_fundamental.py          # 可 thin-wrap 现有
  test_uc_strategy.py
  test_uc_options.py
```

每个 usecase 测试文件顶部用注释挂 ID：

```python
# UC-FND-01 / UC-FND-03
def test_uc_fnd_pit_and_filled_report():
    ...
```

**L4 一键命令（目标形态）**：

```bash
python3 scripts/accept_quantcode_p0.py --group all
# 或
python3 scripts/accept_quantcode_p0.py --group jerry   # strategy+fundamental+options
python3 scripts/accept_quantcode_p0.py --group factor
python3 scripts/accept_quantcode_p0.py --group model-risk
```

输出格式对齐 Jerry accept：`[PASS]/[FAIL] UC-xxx — detail`。

---

## 5. 单条用例模板（写新测试时照抄）

```text
ID:        UC-XXX-NN
标题:      …
Actor:     A?
优先级:    P0/P1/P2
前置:      fixture / chromadb / 无外网 / ScriptedLLM
步骤:
  1. …
  2. …
期望:
  - 状态: completed | waiting_for_human | rejected
  - 产物: path + schema
  - 业务断言: 如 published_at <= as_of_date
自动化:   pytest path::test_name | 手工
降级:     若依赖真 API，CI skip + 标注
```

### 示例（已实现口径）— UC-FND-01

| 项 | 内容 |
|----|------|
| 前置 | `tests/fixtures/pit_corpus_sample.json` 含 DOC-LEAK-2026 |
| 步骤 | `pit_rag_search(query=…, as_of_date=2025-01-01)` |
| 期望 | `filtered_count >= 1`；documents 中无 LEAK；可选 `backend in {chroma, fixture_json}` |
| 自动化 | `tests/test_fundamental_tools.py::test_pit_rag_filters_lookahead` |

### 示例（建议新增）— UC-XGRP-01

| 项 | 内容 |
|----|------|
| 前置 | 临时 Blackboard DB；Scripted model LLM + risk 确定性 gate |
| 步骤 | model 写 pending → risk start high_risk → interrupt → approve |
| 期望 | 同一 `review_id` 被消费；approve 后有 comment artifact；dedupe key 稳定 |
| 自动化 | 新建 `tests/usecases/test_uc_model_risk_e2e.py` |

---

## 6. IDE / 手工冒烟清单（L5，investor 前）

| # | 操作 | 期望 | 负责人 |
|---|------|------|--------|
| H1 | 启动 OpenCode fork | 无崩溃 | Lead |
| H2 | 切换 group=factor，`/compose` 测因子 | 流式 thought/tool；有 Factor 类产出 | Lead |
| H3 | group=model 提交 → 自动进 risk | HumanGate 面板出现 | 陈/杨 |
| H4 | Gate 点 approve | 恢复并写 comment | 杨 |
| H5 | group=fundamental 估值 | PIT 可解释；研报非空 | 刘炽 |
| H6 | 六面板点开 | Compose/树/Gate/Schema/Memory/Resume | Lead |
| H7 | 录屏场景 1+2 | 可播放兜底 | Lead |

手工也要留证据：截图或 `artifacts/` 目录清单 + 录屏链接写进 `handoff.md`。

---

## 7. 与现有测试的映射（避免重复造轮）

| 能力 | 已有测试（代表） | 用例覆盖 |
|------|------------------|----------|
| Jerry 三组 demo | `test_day5_jerry_demos` / `accept_jerry_day5` | UC-STR/FND/OPT P0 |
| Fundamental 人审 | `test_fundamental_human_gate` | UC-FND-04 |
| Risk gate | `test_risk_flow` / `test_agent_mcp_tool` | UC-RSK-02/03/04 |
| Schema 终验 | `test_schema_final_validation` | 各组 *\-02 schema |
| Dedupe | `test_dedupe` / `test_risk_dedupe` | UC-RSK-05 |
| Loop | `test_loop_*` | UC-PLT-07 |
| Dream | `test_dream_prototype` | UC-DRM-01 |

**优先补洞（建议本周）**：

1. `UC-XGRP-01` model→risk 端到端（现在多组分测，缺一条用例级 E2E）  
2. `UC-FAC-03` 因子验收负例  
3. `scripts/accept_quantcode_p0.py` 统一 L4 入口（内部调用 jerry accept + factor/risk 子集）  
4. `tests/usecases/` 目录，把 P0 ID 钉死，方便汇报「用例通过率」

---

## 8. 通过标准（什么叫「用例测试做完了」）

**工程完成**：

- [ ] 本文所有 **P0** 用例有自动化或明确手工步骤 + Owner  
- [ ] CI 跑 L0–L3；release 前跑 L4  
- [ ] L4 输出可粘贴进 standup（`[PASS] UC-...`）  
- [ ] 失败用例能指出是哪条 UC，而不是只报 assert 行号  

**产品完成（investor）**：

- [ ] 场景 1–3 至少各 1 条 P0 用例现场或录屏可演  
- [ ] 跨组 UC-XGRP-01 或等价录屏  
- [ ] 降级项写在 Feature Checklist / handoff，不假装全真  

---

## 9. 你（Jerry）可直接认领的子集

只对 strategy / fundamental / options：

```bash
python3 scripts/accept_jerry_day5.py
python3 -m pytest \
  tests/test_day5_jerry_demos.py \
  tests/test_fundamental_tools.py \
  tests/test_fundamental_human_gate.py \
  tests/test_strategy_tools.py \
  tests/test_options_tools.py \
  tests/test_schema_final_validation.py -q
```

对应 UC：`UC-STR-*`、`UC-FND-*`、`UC-OPT-*`、相关 `UC-PLT-01`。  
全组平台与 model→risk 由 Lead / 对应 Owner 认领 §3.1–3.3。

---

## 10. 下一步（若要落地代码）

1. 建 `tests/usecases/` + 把现有 P0 用 `@pytest.mark.usecase("UC-...")` 标记  
2. 写 `scripts/accept_quantcode_p0.py`  
3. 补 `UC-XGRP-01`  
4. 把 §6 手工表拷进 `docs/handoff.md`  

需要的话我可以按本设计直接开工实现 `accept_quantcode_p0.py` 和 `UC-XGRP-01`。

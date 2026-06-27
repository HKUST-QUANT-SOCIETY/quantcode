# QuantCode PRD — 产品需求文档

> **版本**：v0（today, 团队会议前框架）
> **Owner**：Agent Group · HKUST QUANT SOCIETY
> **最后更新**：2026-06-27

---

## 0. TL;DR

> ⚠️ 本节需要团队会议后填写最终版本

**一句话定义产品**：
> QuantCode 是 HKUST QUANT SOCIETY 内部使用的量化投研 Agent 平台，把投研流程编译成确定性 pipeline，让 5 人 agent 组放大整个量化团队的产能。

**一句话定义目标用户**：
> HKUST QUANT SOCIETY 的 5 个研究组（基本面、因子、模型、风控、策略），以及内部 agent 组本身。

**一句话定义核心价值**：
> 把"人与人的协商"换成"机器与机器的 schema 校验"，把验收标准从"看一眼觉得行"换成"assert 通过/失败"。

---

## 1. 背景与问题

### 1.1 当前痛点

- **跨组协作的隐性损耗**：模型组提 PR 后需要和风控组协商，风控判断标准不统一，流程慢
- **研报生产不可复用**：每份基本面研报都是手写，结构没法批量生成
- **因子评估口径不一**：每个人算 IC 用的样本和方法不同，难以横向比较
- **AI 工具孤立使用**：组员各自调 ChatGPT / Cursor，没有沉淀成团队资产
- **长任务上下文丢失**：10+ 小时的研究任务在 LLM 中跑会 compact 丢信息

### 1.2 现有方案为什么不够

- **直接用 MimoCode / Claude Code**：通用，没有量化业务知识，每次都要重新喂上下文
- **Fork MimoCode 改源码**：会被上游变更和合并冲突拖死，不是 5 人小组该做的事
- **完全自建一个 IDE**：和腾讯 Workbench 比拼端到端体验，必死

### 1.3 为什么是现在

- MimoCode 2026-06 开源，扩展机制成熟（skills / plugins / config 三件套）
- LLM 长上下文能力足够支撑 30 分钟以上的研究任务
- 团队有真实痛点（模型组和风控组协作摩擦），有 6 人 agent 组可以建设

---

## 2. 目标用户

### 2.1 用户画像

| 组 | 人数 | 主要工作 | 对 QuantCode 的需求 |
|---|---|---|---|
| **基本面组** | 2-3 | 公司研究、行业研究、写研报 | 快速生成专业 PDF、point-in-time 检索研报 |
| **因子组** | 3-4 | 因子开发、因子评估 | 标准化的因子评估流水线、横向比较 |
| **模型组** | 3-4 | 策略建模、机器学习因子 | 提 PR 后自动风控反馈、无需联系风控组 |
| **风控组** | 1-2 | 策略风控、组合管理 | 程序化阈值，24h 自动执行风控规则 |
| **策略组** | 1-2 | 组合构建、调仓决策 | 因子和策略的统一评估口径 |
| **Agent 组**（我们） | 6 | 建设和维护 QuantCode | dogfood：每天用自己的工具 |

### 2.2 典型工作流变化

**模型组同学的"今天"**：
1. 写完一个新的 ML 因子，提 PR
2. 微信群里 @ 风控组，问"我这个 max_drawdown 算得对吗"
3. 风控组同学有空了才看，可能 1-2 天
4. 来回讨论 3-5 轮，统一口径
5. 终于 merge

**模型组同学的"明天"**：
1. 写完一个新的 ML 因子，提 PR
2. CI 自动触发 risk-gate agent
3. 10 分钟内 PR 评论里出现风控 JSON + 自动结论
4. 不满足阈值 → 自动打回并附原因；满足 → 自动 approve 等人 review
5. 风控组只需要 review JSON，不用从 0 开始算

---

## 3. 产品范围

### 3.1 必做（P0，MVP）

四个核心 skill，每个独立可用：

| Skill | 价值 | 验收 |
|---|---|---|
| `risk-gate` | PR 风控门禁 | 一个真实 PR 走完流程，风控组认可输出 |
| `pit-rag` | Point-in-time 检索 | 时点过滤无 lookahead bias |
| `research-pdf` | 中金风格 PDF 研报 | 研究员愿意发出去 |
| `factor-eval` | 因子有效性评估 | IC/IR/换手自动算出，符合 schema |

加共用基础设施：

- JSON Schema 契约（4 套）
- 验收 runner（公用）
- GitHub Actions CI gate

### 3.2 应做（P1，MVP 之后）

- `data-fetch`：自动化数据拉取（依赖基建组的数据库）
- `factor-synthesis`：因子合成建议
- `ppt-gen`：投资人 pitch deck 自动生成
- `meeting-notes`：会议纪要结构化
- Web dashboard：观察所有 pipeline 跑状态

### 3.3 不做（明确边界）

- ❌ **自建 IDE / 桌面端 / 终端 UI** —— MimoCode 已经提供
- ❌ **Fork MimoCode 源码** —— 用扩展机制做加法
- ❌ **多租户 SaaS / 对外服务** —— 我们是内部工具
- ❌ **自建 LLM 训练** —— 用 Claude / GPT / MiMo Auto
- ❌ **造数据基建** —— 让基建组负责，agent 组消费

---

## 4. 功能详述（4 个核心 skill）

### 4.1 risk-gate（PR 风控门禁）

**用户故事**：
> 作为模型组研究员，我提交策略代码 PR 后，希望 10 分钟内自动得到风控分析 JSON，告诉我 max_drawdown / position_limit / 相关性 / 容量 / VaR 是否满足阈值，这样我不用等风控组人工 review 就知道哪里要改。

**输入**：
- PR diff（GitHub Actions context）
- 策略代码路径

**输出**：符合 `schemas/risk-profile.schema.json`

**验收标准**（程序化）：
```python
assert risk_json["max_drawdown"] <= 0.20
assert risk_json["position_limit"] <= 0.30
assert abs(risk_json["correlation_with_existing"]) <= 0.60
assert risk_json["tail_risk_var_99"] is not None  # 必须有 VaR
```

**Owner**：陈振宏（T1）

---

### 4.2 pit-rag（Point-in-Time RAG）

**用户故事**：
> 作为基本面研究员，我要在 2024-03-15 这个时点做蜜雪冰城研报，需要检索"当时能看到的"所有研报和公告。系统必须保证不会给我 2024-03-16 之后发布的信息（lookahead bias）。

**输入**：
```json
{
  "query": "蜜雪冰城 2023 年度财务分析",
  "as_of_date": "2024-03-15",
  "corpus": ["research_reports", "announcements"]
}
```

**输出**：
```json
{
  "documents": [
    {
      "id": "cicc-2097hk-2024-02-20",
      "source": "中金公司",
      "published_at": "2024-02-20",
      "snippet": "...",
      "score": 0.89
    }
  ]
}
```

**验收标准**：
```python
for doc in output["documents"]:
    assert doc["published_at"] <= input["as_of_date"]
```

**Owner**：杨欣琳（T2 主），刘驰（副）

---

### 4.3 research-pdf（研报 PDF 生成）

**用户故事**：
> 作为基本面研究员，我输入公司名 + 关注点，系统自动调研报 RAG、生成结构化章节、渲染出中金风格的 PDF。如果我愿意发给投资人，就算验收通过。

**输入**：符合 `schemas/research-spec.schema.json`

**工作流**：
1. 调 `pit-rag` 拉数据
2. LLM 生成各章节（markdown/JSON）
3. 填 Typst 模板 → 渲染 PDF

**输出**：
```json
{
  "pdf_path": "artifacts/research/2097HK-2026-06-27.pdf",
  "sections_generated": ["overview", "business", "financials", "valuation", "risks"],
  "citations_count": 23
}
```

**验收标准**（半程序化）：
- PDF 渲染成功（exit code 0）
- 所有章节非空 ✓
- 至少 10 条引用 ✓
- **人工验收**：研究员愿意发 = 通过

**Owner**：刘驰（T3 主），肖骥超（Typst 实现）

---

### 4.4 factor-eval（因子评估）

**用户故事**：
> 作为因子组研究员，我写完一个新因子函数，系统自动跑 IC / IR / 换手 / 衰减 / 分层回测，输出标准化 JSON。我能快速和历史 50 个因子横向比较。

**输入**：
```python
def my_factor(panel: pd.DataFrame) -> pd.Series:
    return panel["eps_ttm"] / panel["close"]
```

加上 universe / date_range / benchmark。

**输出**：符合 `schemas/factor-report.schema.json`

**验收标准**：
```python
assert abs(report["ic_metrics"]["ic_mean"]) >= 0.03
assert report["ic_metrics"]["ir"] >= 0.5
assert report["turnover"]["monthly"] <= 0.8
assert report["ic_metrics"]["t_stat"] >= 2.0
```

**Owner**：肖骥超（T4）

---

## 5. 非功能性需求

### 5.1 性能

- 一次因子评估（CSI 1000，3 年回溯）< 30s
- pit-rag 检索 P95 延迟 < 500ms
- 研报 PDF 生成 < 5min（含 RAG + LLM + 渲染）

### 5.2 可观测性

- 每次 agent run 落 trace（OpenTelemetry 或简易 JSON log）
- 每个 task 有 UUID，可追踪
- runner 验收结果持久化（SQLite 本地）

### 5.3 可重放

- 任何 task 带 ID 可以 `quantcode replay <task_id>`
- checkpoint 机制：长任务失败后不用从 0 重跑

### 5.4 安全性

- 敏感配置（API key / 数据库密码）不入库
- `.mimocode/mimocode.local.jsonc` 本地覆盖
- 高风险操作（删库、force push）permission 设为 deny

---

## 6. 技术架构

### 6.1 总体图

```
              ┌────────────────────────┐
              │     MimoCode（载体）     │
              │   TUI / Desktop / IDE   │
              └───────────┬────────────┘
                          │ skill 调用
              ┌───────────▼────────────┐
              │   .mimocode/skills/    │  ← QuantCode IP
              │   factor-eval          │
              │   risk-gate            │
              │   pit-rag              │
              │   research-pdf         │
              └───────────┬────────────┘
                          │ Python import
              ┌───────────▼────────────┐
              │     pipelines/         │
              │  （业务实现，Python）    │
              └───────────┬────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐      ┌─────────┐      ┌─────────┐
   │ schemas │      │ runner  │      │templates│
   │ 契约    │      │ 验收    │      │ Typst 等 │
   └─────────┘      └─────────┘      └─────────┘
```

### 6.2 数据流（以 risk-gate 为例）

```
PR push → GitHub Actions → MimoCode CLI invoke skill
       → pipelines/risk_gate/analyze.py → 输出 risk.json
       → runner.acceptance.run_acceptance() → pass/fail
       → 写回 PR 评论 + 决定是否阻塞 merge
```

### 6.3 Schema 契约

所有 skill 之间通过 JSON Schema 通信。schema 改动需要走 PR review（`.mimocode/mimocode.jsonc` 中已配 `"schemas/**": "ask"`）。

---

## 7. 里程碑（6 个 Sprint，每个 1 周）

| Sprint | 目标 | 关键产出 |
|---|---|---|
| **S0**（本周） | 仓库脚手架 + PRD 锁定 + schema v1 冻结 | 本仓库当前状态 |
| **S1** | `risk-gate` MVP | 一个真实 PR 触发 agent 输出风控 JSON，CI gate 跑通 |
| **S2** | `pit-rag` MVP | 一个研究问题能从向量库检索到结果，带时点过滤 |
| **S3** | `research-pdf` MVP | 输入公司名输出 Typst 渲染的 PDF |
| **S4** | `factor-eval` MVP | 输入因子代码输出 IC/IR/换手 JSON |
| **S5** | 4 个 skill 集成 + CI gate | 跑通完整 demo，对内分享 |

**每个 Sprint 的硬规则**：
- 周一定目标
- 周五必须有可演示的东西
- 周末 retro，下周再来

---

## 8. 团队和分工

| Track | 主 Owner | 副 Owner | 主要技能匹配 |
|---|---|---|---|
| **T0 地基**（schema / runner / 工具集成） | 俞高磊 | 用户（Lead） | Agent/Workflow 搭建 + 第一作者 IEEE + SFT/RL |
| **T1 risk-gate** | 陈振宏 | 肖骥超统计支持 | FastAPI + Docker + 部署 + RAG |
| **T2 pit-rag** | 杨欣琳 | 刘驰 | LLM 底层 + MLLM 长上下文（两人已合作过） |
| **T3 research-pdf** | 刘驰 | 肖骥超 Typst | IR 比赛 20 页研报 + LaTeX |
| **T4 factor-eval** | 肖骥超 | 俞高磊兼 | 数学/统计博士级 + 因果推断论文 |

**Lead（用户）的职责**：
- 项目方向 + PRD 维护
- 跨 track 协调 + schema 评审
- 对外沟通（投资人 / 协会其他组）

---

## 9. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| MimoCode 升级 break 我们的 skill | 中 | 中 | 在 CI 跑 smoke test，锁定 MimoCode 版本 |
| 用户不愿意用（adoption 风险） | 高 | 高 | S1-S4 每个 sprint 强制找一个真实用户，把 ta 拉进 review |
| Schema 设计不当导致后期改造大 | 中 | 高 | S0 schema 评审会，让所有 owner 都签字 |
| 6 人协作沟通成本爆炸 | 中 | 中 | 强制 standup（每日 15min）+ schema 异步协作 |
| 学生时间不稳定 | 高 | 中 | 每个 track 双 owner（主/副），主病了副可顶 |
| 数据基建依赖卡住 RAG | 中 | 高 | S0 就和基建组确认数据接入方式 |

---

## 10. 成功指标

### Day 30（S5 结束）
- [ ] 4 个 skill MVP 跑通
- [ ] 至少 1 个非 agent 组同事日常使用
- [ ] CI risk-gate 在 GitHub Actions 24h 自动执行

### Day 60
- [ ] 3 个用户组日常使用
- [ ] pipeline 模板库雏形，新 skill < 1 天上线
- [ ] 投资人 demo 物料齐全（研报 PDF + CI log + 因子迭代数据）

### Day 90
- [ ] 5 个用户组全部接入
- [ ] 平均每组提效 > 30%（用节省的人工小时数衡量）
- [ ] 监控、降级、性能优化等生产化加固

---

## 附录 A：术语表

- **Skill**：MimoCode 的扩展机制，一个 `SKILL.md` 描述一个能力
- **Pipeline**：业务流程的代码实现（Python 包）
- **Schema**：JSON Schema 契约，所有 skill 之间通信的格式
- **Runner**：验收 runner，吃 JSON 吐 pass/fail
- **PIT**：Point-in-Time，时点正确性
- **Lookahead bias**：用了未来才能看到的信息，量化研究的大忌

## 附录 B：决策日志

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-06-23 | 不 fork MimoCode，做加法 | 避免被上游变更和合并冲突拖死 |
| 2026-06-27 | 仓库名 `quantcode`（不是 QuantumCode） | 设计文档里 Quantum 是拼写错误 |
| 2026-06-27 | 团队 6 人确定（张梦婷退组） | 4 份新简历 + Lead |
| 2026-06-27 | 改超敏捷开发，6 个 sprint 每周一个 | 比 5 天集中冲刺更可持续 |

---

**文档维护**：本 PRD 持续迭代，每个 Sprint 末尾根据实际进展更新。重大变更需要团队评审。


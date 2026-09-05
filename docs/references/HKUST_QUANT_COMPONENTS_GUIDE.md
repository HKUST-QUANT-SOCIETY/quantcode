# HKUST Quant Society 常用组件清单与使用说明

> 扫描范围：`HKUST-QUANT-SOCIETY` GitHub Organization 当前可访问仓库。  
> 本文优先整理**真正会进入量化研究/生产主链的组件**，再列挖因子、模型、风控、回测、平台、知识库和基础设施组件。  
> 对明显处于 scaffold / placeholder / legacy 状态的仓库单独标注，避免团队以后“同一件事用两个库”。

---

# 1. 一张图先看懂

当前最值得作为团队**Canonical Components（标准组件）**维护的主链可以理解为：

```text
                    ┌──────────── alphaprobe / CogAlpha / 其他挖因子算法 ────────────┐
                    │                                                            │
                    ▼                                                            │
DataAccess
  │
  ▼
FactorEngine
  │
  ▼
QuantEvaluator
  │
  ├───────────────► FactorOptimizer
  │                     │
  │                     ▼
  └────────────────► FactorAssets
                          │
                          ▼
                  FactorPreprocess
                          │
                          ▼
                      Modeling
                          │
                  ┌───────┴────────┐
                  ▼                ▼
             LightGBM研究链      其他模型
                  │
                  ▼
             Riskfolio-QS  ◄──────── Barra Engine
                  │
                  ▼
             VectorBT-QS
                  │
                  ▼
            回测 / 绩效 / 组合结果

外层平台：
QuantPlatform → Platform Web

知识 / 研究辅助：
Factor Research DB / Sentinel / PaperRAG / Quant Knowledge Graph
```

这条链里最核心的思想是：

- **DataAccess 只负责数据**
- **FactorEngine 只负责因子定义与计算**
- **QuantEvaluator 只负责证据**
- **FactorOptimizer 只负责搜索**
- **FactorAssets 只负责因子资产治理**
- **FactorPreprocess 只负责模型输入处理**
- **Modeling 只负责模型训练与 OOS**
- **Riskfolio-QS 只负责组合优化**
- **VectorBT-QS 只负责执行回测**
- **QuantPlatform 只负责集成、权限、工作流和展示**

不要让这些职责重新重叠。

---

# 2. S 级：日常最重要、建议长期标准化的核心组件

| 组件 | 仓库 | 层级 | 主要职责 | 典型输入 | 典型输出 | 建议 |
|---|---|---|---|---|---|---|
| DataAccess | `data_access` | 数据层 | 全团队唯一数据读写入口、PIT/as-of、COS/Parquet/ClickHouse、快照与数据治理 | dataset + fields + date/universe | Arrow/DataFrame/ReadHandle/Snapshot | **必须统一使用** |
| FactorEngine | `factor_engine` | 因子计算层 | DSL→AST→IR→多后端执行，批量计算/物化因子 | DSL/FactorDefinition + DataAccess | FactorValue / factor lake | **必须统一使用** |
| QuantEvaluator | `quant_evaluator` | 评估层 | RankIC/ICIR/换手/稳定性/置信区间等评估证据 | FactorBatch + LabelBundle | EvaluationBundle / MetricArtifact | **唯一评估权威** |
| FactorOptimizer | `factor_optimizer` | 因子寻优层 | 参数/结构/处理 recipe 搜索，Pareto、不确定性、sealed test | candidate + QE evidence | optimized treatment / trial ledger | **搜索统一入口** |
| FactorAssets | `factor_assets` | 因子资产层 | 身份、去重、相似度、聚类、生命周期、入库、Factor Library | factor definition/value + QE evidence | FactorAsset/Library/Cluster/FeatureSet refs | **唯一因子资产事实源** |
| FactorPreprocess | `factor_preprocess` | 预处理层 | winsor/rank/zscore/中性化/平滑/缺失/新鲜度/representation | selected factor values | FeatureBundle / TreatmentRecipe | **模型前统一入口** |
| Modeling | `modeling` | 模型层 | walk-forward、purge/embargo、泄漏防护、模型 artifact/OOS | FeatureBundle + LabelContract | ModelArtifact / PredictionBatch | **模型训练 authority** |
| Barra Engine | `barra_engine` | 风险模型层 | 自研 Barra 风格/行业暴露、因子收益、F/D 协方差体系 | A股 PIT 数据 | B/F/D + factor returns | **风险模型基础件** |
| Riskfolio-QS | `riskfolio_qs` | 组合构建层 | cvxpy 组合优化、TE/行业风格/换手/成本约束 | alpha + risk + benchmark + prev position | target_positions / trades | **组合优化主组件** |
| VectorBT-QS | `vectorbt_qs` | 回测执行层 | A股/美股 fast + accurate 回测，涨跌停/T+1/费税/整手/公司行动 | target positions | trades/nav/report | **回测主组件** |
| QuantPlatform | `quant_platform` | 平台集成层 | DTO、权限、RBAC、Job/Workflow、Outbox、Artifact、存储、编排 | 各 domain artifacts | API/metadata/workflow | **外层平台边界** |
| Platform Web | `platform_web` | 展示层 | React/TS 平台页面，只读后端，不重算量化逻辑 | QuantPlatform API | Dashboard/UI | **统一研究门户** |

---

# 3. 核心组件详细介绍

## 3.1 `data_access` — 数据访问与 PIT 基础设施

这是全体系最底层、也是最容易造成“全系统口径漂移”的组件。

当前 README 将它定义为**全团队唯一数据读写入口**，覆盖 A 股、美股、因子湖、分钟/流式数据等，并提供 PIT/as-of、快照、成本路由、Filter AST、多引擎执行、COS/ClickHouse 等能力。

常用场景：

```python
store.read_frame(...)
store.read_arrow(...)
store.read_factors(...)
store.read_asof(...)
store.read_joined(..., strategy="pit_asof")
```

团队里以后应尽量禁止：

```python
pd.read_parquet(...)
pq.read_table(...)
duckdb.sql("select ... from some_path")
```

散落在业务仓里直接读生产数据。

**它解决的是：**

1. 数据源换了，下游不改。
2. 字段物理名换了，下游不改。
3. PIT 规则统一。
4. 快照可追溯。
5. 大规模读取自动选 Arrow / DuckDB / Polars / COS。
6. 权限、敏感字段、成本和数据质量统一治理。

---

## 3.2 `factor_engine` — 因子 DSL 与计算引擎

这是“因子是什么”和“因子怎么算”的权威。

当前仓库已经是一个比较完整的 DSL 系统：

```text
Factor DSL
→ AST
→ IR
→ Planner
→ CSE
→ SQL / Polars / Pandas 等后端
→ FactorValue
→ factor_lake
```

当前 README 记录约 **1737 个 canonical 算子**，覆盖：

- 时序
- 横截面
- 分组
- 技术指标
- 量价
- 微观结构
- 基本面
- 事件
- 分钟→日
- 研究统计算子

最重要的能力不是“算子数量多”，而是：

- 统一 DSL
- canonical factor identity
- run_many
- Common Subexpression Elimination（公共子表达式消除）
- 多后端
- production/research allowlist
- materialization

所以以后 AlphaProbe、CogAlpha、FactorMiner 等挖因子算法，最好全部生成 **FactorEngine DSL**，不要每个算法维护一套自己的因子语法。

---

## 3.3 `quant_evaluator` — 因子/预测证据中心

它回答：

> “这个因子到底行不行？”

目前覆盖 RankIC、Pearson IC、ICIR、HAC t/p、quantile spread、turnover、half-life、block bootstrap、coverage、stability 等证据。

核心接口应该长期保持这种形式：

```text
FactorBatch
+
LabelBundle
+
EvaluationContext
→
EvaluationArtifact / MetricArtifact
```

尤其要保留：

- LabelBundle 显式时序
- vwap-to-vwap 统一标签口径
- 不成熟 label ≠ 0
- NOT_COMPUTED ≠ 0
- reporting 只渲染已经计算好的 artifact
- batch / streaming / parallel evaluation

以后：

- 因子筛选
- Auto Treatment
- 因子入库
- 模型 OOS
- 因子失效监控

最好全部消费这一套证据。

---

## 3.4 `factor_optimizer` — 因子结构和 Treatment 搜索

它不是普通“超参数调优器”，而是研究搜索层。

已经包含：

- 参数窗口调整
- operator swap
- decay 调整
- linear combination
- threshold 调整
- tiered evaluation
- multifidelity
- Pareto
- desirability
- bootstrap uncertainty
- sealed test
- TrialLedger

它适合做两类工作：

### A. Factor Optimization

例如：

```text
ts_mean(close, 20)
→ window=10/20/40
→ EMA / KAMA
→ operator swap
→ expression mutation
```

### B. Treatment Optimization

例如：

```text
RAW
vs
winsor
vs
rank
vs
industry neutral
vs
industry+size neutral
vs
EWMA
vs
winsor→neutral→rank
```

然后由 QE 评估，FO 决定 Pareto frontier 和最终 winner。

---

## 3.5 `factor_assets` — 因子资产管理中心

这是“哪些因子存在于公司资产库里”的事实源。

它不是计算因子的库，而是做：

- Factor Identity
- SeenIndex
- 去重
- Similarity
- ANN
- Sparse Graph
- Leiden Clustering
- Cluster lineage
- Lifecycle
- Promotion
- Rollback
- Factor Library
- Representative Selection
- Novelty

非常重要，因为当你们因子到：

```text
1,000
10,000
100,000+
```

之后，最大问题不再是“还能不能再挖”，而是：

- 哪些其实重复？
- 哪些是同一个机制？
- 哪些只是参数变体？
- 哪些是真正新增信息？
- 哪些要退役？
- 哪些应该进入不同模型？

这些都应该由 FactorAssets 管理。

---

## 3.6 `factor_preprocess` — 模型输入处理

它负责从：

```text
Factor Value
```

变成：

```text
Model-ready Feature
```

已有变换包括：

- cs_rank
- cs_zscore
- winsor
- rolling mean/std
- EWMA
- trailing median
- robust EWMA
- KAMA
- one-sided IIR low-pass
- Kalman local level
- volatility scaling
- freshness-aware fill
- industry neutral
- size neutral
- industry+size neutral
- regime-related transforms

同时已经把 HP、wavelet、bandpass 等全样本非因果处理明确放到 OFFLINE/RESEARCH 侧。

这个库应和 FactorOptimizer 配套：

```text
FactorProfiler
→ Eligibility
→ Treatment Search Space
→ FO Search
→ QE Evaluation
→ Treatment Winner
→ FeatureBundle
```

---

## 3.7 `modeling` — 正式模型层

这个库最重要的不是 PCR/PLS/ElasticNet，而是：

**模型治理和防泄漏基础设施。**

主要包括：

- date-authoritative split
- walk-forward
- purge
- embargo
- train-only preprocessing
- negative controls
- model artifact
- prediction contract
- OOS enforcement
- feature schema hash
- model lineage

它应该成为以后：

- LightGBM
- XGBoost
- Transformer
- MoE
- Distributional Model
- Regime Model

等模型的共同“训练与治理底座”。

具体 learner 可以外接，不应该每个模型自己重写 walk-forward / purge / artifact。

---

## 3.8 `barra_engine` — 风险模型

自研日频传统 Barra 风险模型。

核心公式：

```text
Σ = B F B' + D
```

其中：

- B = 股票因子暴露
- F = 风格/行业因子协方差
- D = 特异风险

目前仓库已经做：

- 风格暴露
- 行业暴露
- 横截面 WLS 因子收益
- EWMA 协方差
- specific risk
- 增量计算

它的主要下游就是 Riskfolio-QS。

---

## 3.9 `riskfolio_qs` — 组合优化

输入：

```text
alpha
+
Barra risk
+
benchmark
+
previous positions
+
tradability/cost
```

输出：

```text
target_positions.parquet
trades.parquet
```

主要约束：

- Tracking Error
- Industry Neutrality
- Style Neutrality
- Turnover
- Single-name weight
- Cost
- Impact

以后模型输出不要直接：

```text
prediction → top30 equal weight
```

作为最终生产做法。

建议：

```text
prediction distribution / expected return
→ portfolio optimizer
→ target position
```

---

## 3.10 `vectorbt_qs` — 回测与执行模拟

是最终“目标权重到底能不能成交”的组件。

两套口径：

### Fast

适合：

- 大批量因子
- 参数扫描
- 初筛

### Accurate

考虑：

- A 股 100 股整手
- 停牌
- 涨跌停
- T+1
- 印花税
- 最低佣金
- 滑点
- 成交量参与率
- 分红送转
- 真实现金与持仓

最终所有准备进入 production candidate 的策略，至少应该经过 accurate replay。

---

## 3.11 `quant_platform` — 全系统“外壳”

它不负责产生 alpha。

负责的是：

- Artifact Registry
- Job
- Workflow
- Candidate Pipeline
- Authentication
- RBAC
- Audit
- Outbox/Inbox
- COS Artifact Storage
- FeatureSet / Model / Backtest DTO
- API

最重要的原则：

> Domain Package 负责业务真相，QuantPlatform 只负责 orchestration / metadata / access / projection。

例如：

```text
RankIC → QE 算
Cluster → FA 算
Treatment → FP/FO 算
Model → Modeling 算
```

Platform 不重新算。

---

## 3.12 `platform_web` — 研究管理前端

React + TypeScript 的研究门户。

现在已有约 20 个页面，覆盖：

- Factors
- Campaigns
- Treatments
- Clusters
- Libraries
- Feature Sets
- Models
- Backtests
- Optimizers
- Live Health
- Streaming
- Jobs
- Data Snapshots
- Artifacts
- Audit
- Users

这个仓库应该只做：

```text
API → visualization
```

不要做领域计算。

---

# 4. A 级：经常会用到的研究 / Alpha 组件

| 组件 | 仓库 | 用途 | 当前定位 |
|---|---|---|---|
| AlphaProbe | `alphaprobe` | Deep/RL/LLM 因子挖掘、knowledge pool、去重、连续挖掘 | 重要上游挖因子引擎 |
| CogAlpha | `AlphaMining-CogAlpha` | LLM 多 Agent 量价因子挖掘，A股+美股舰队 | 重要挖因子引擎 |
| AlphaFlow | `alpha_flow` | 模块化因子挖掘平台架构 | **目前更偏 scaffold** |
| LightGBM Research | `lightgbm_qs` | 因子矩阵→LGBM→组合→回测一键研究链 | 非库，研究脚本集 |
| FactorMiner | `AlphaMining-factorminer` / `Alpha-Mining--factor-miner-` | 自动因子挖掘 | 建议后续统一 canonical repo |
| AlphaSage | `AlphaMining-alphasage` | Alpha Mining 研究算法 | 算法组件 |
| AlphaSchema | `AlphaMining-alphaschema` | Alpha 结构/Schema 研究 | 算法/结构组件 |
| AlphaBench | `AlphaMining-AlphaBench` | Alpha Mining benchmark | Benchmark 组件 |

### AlphaProbe

当前最值得长期整合的自动挖因子组件之一：

```text
cold start
→ knowledge pool
→ LLM / RL search
→ FE DSL
→ dedup
→ IC/ICIR funnel
→ candidate_pool
```

它不应该自己成为最终评估或入库 authority。

最终应该：

```text
AlphaProbe
→ FactorEngine
→ QuantEvaluator
→ FactorOptimizer
→ FactorAssets
```

### CogAlpha

偏 LLM-Agent 的因子生成系统，已经支持：

- A 股
- 美股 S&P500
- 多 worker fleet
- industry+size neutralization
- train/valid/test
- COS 同步
- 进展报告

它更适合作为：

> “Alpha Candidate Generator”

而不是平台核心基础设施。

### AlphaFlow

README 明确说目前主要是 architecture-aligned scaffold，多个生产实现仍留给后续阶段。

因此现在：

- 可以借架构
- 可以借接口设计
- 不应把它当已经成熟的生产挖掘引擎

---

# 5. B 级：知识、基本面与 Research Intelligence 组件

## 5.1 `factor-research-db`

券商因子研报数据库。

当前包含约：

- 225 篇因子研报
- 788 个结构化因子
- 量价 / 基本面 / 情绪 / 微观结构 / 资金流 / 事件 六大域

它非常适合作为：

```text
Literature Alpha Library
```

用途：

- 冷启动因子来源
- 机制标签
- AlphaProbe/CogAlpha RAG
- 因子分类
- 因子解释
- Novelty 检查
- 论文/券商因子与自有因子映射

---

## 5.2 `sentinel`

基本面 Agent / 年报研究平台。

流程：

```text
年报 PDF
→ 下载
→ 转 Markdown
→ RAG Index
→ Fundamental Agent
→ Financial Agent
→ Industry Agent
→ Thesis Synthesizer
```

另有 deterministic Financial Fact DB。

它和量化主链的潜在结合：

```text
年报
→ structured financial facts
→ PIT factor source
→ DataAccess
→ FactorEngine
```

---

## 5.3 `PaperRAG`

AI / Agent 方向论文检索系统。

当前：

```text
arXiv
→ PostgreSQL
→ Semantic Scholar / HuggingFace metadata
```

后续规划：

```text
Embedding
→ Hybrid Retrieval
→ Reranking
```

适合服务：

- AI4Quant
- Agent Factor Mining
- Model research
- Paper Radar

---

## 5.4 `quant-knowledge-graph`

团队量化知识图谱。

五条主干：

```text
foundation
factor
model
agent
execution
```

八条 workstreams 覆盖：

- 数学统计
- 市场微观结构
- 因子
- ML/DL
- 回测/组合/交易
- Agent
- 低延迟
- 前沿论文

它不是 production runtime，而是：

**人才培养 + 研究知识管理组件。**

---

# 6. C 级：基础设施 / 治理组件

## `quant-ops`

组织级基础设施与治理仓。

主要包括：

- onboarding
- team access matrix
- secrets naming
- repository monitoring
- hard isolation

这类内容虽然“不算 alpha”，但对于多人团队很重要。

建议后续把：

```text
CI
Secrets
Permissions
Deployment
Monitoring
Runbooks
Incident Response
```

逐步统一在这一层。

---

# 7. 专门型组件

这些不一定每天所有人用，但属于重要专业能力：

| 仓库 | 作用 |
|---|---|
| `barra_research` | Barra 风险模型研究 |
| `barra_factor_evaluate_engine` | Barra 因子评估专项 |
| `size-factor-risk-model` | Size 风险因子专项研究 |
| `data-access----CTA` | CTA 数据访问 |
| `CTA-continuous-contract` | 期货连续合约 |
| `option-backtestengine` | 期权回测 |
| `option-pricing-line-code` | 期权定价 |
| `earnings-flash` | Earnings / 财报事件研究 |
| `backtest_repo_example` | 回测项目样板 |
| `quant-research-fundamentals` | 基本面研究资料/研究仓 |

这些适合作为：

```text
Specialized Domain Packages
```

不建议直接塞进主仓。

---

# 8. 当前建议视为 Legacy / Placeholder / Scaffold 的仓库

Organization 里目前同时存在一批名字和新组件非常相近、但仓库体量极小的 repo：

```text
quant-platform
quant-factor-engine
quant-factor-mining
quant-factor-platform
quant-factor-strategy
quant-risk
quant-agent-backend
quant-quantaalpha
```

从当前仓库列表看，这些 repo 很多体量只有 0～11 左右，明显不像现在真正运行的：

```text
quant_platform
factor_engine
factor_optimizer
factor_assets
...
```

因此建议团队形成**官方组件映射表**，避免新人误用。

推荐：

```text
旧 / 占位                → 推荐 Canonical Repo
-------------------------------------------------
quant-platform           → quant_platform
quant-factor-engine      → factor_engine
旧 factor evaluation     → quant_evaluator
旧 preprocess scripts    → factor_preprocess
旧 optimization logic    → factor_optimizer
旧 factor registry       → factor_assets
```

另外 Organization 同时有：

```text
AutoFactorEvaluation
auto_factor_evaluation
quant_evaluator
```

建议以后明确：

> 新平台统一以 `quant_evaluator` 为评估 authority。

旧仓库如果仍承担兼容/报告/历史数据职责，就标记：

```text
LEGACY_COMPAT
```

而不是继续作为第二套生产评估系统开发。

---

# 9. 团队成员最实用的“该找哪个库”速查表

### 我要读 A 股行情 / 财务 / 行业 / 分钟数据

```text
data_access
```

### 我要写一个新因子 / 新算子

```text
factor_engine
```

### 我要算 RankIC / ICIR / turnover / stability

```text
quant_evaluator
```

### 我要自动调因子窗口 / 结构 / Treatment

```text
factor_optimizer
```

### 我要做 winsor / rank / zscore / 中性化 / 平滑

```text
factor_preprocess
```

### 我要查一个因子是否已经存在 / 是否重复 / 属于哪个簇

```text
factor_assets
```

### 我要训练模型

```text
modeling
```

LightGBM 的现成研究链：

```text
lightgbm_qs
```

### 我要做 Barra 风险模型

```text
barra_engine
```

### 我要做组合优化

```text
riskfolio_qs
```

### 我要做真实 A 股回测

```text
vectorbt_qs
```

### 我要自动挖因子

优先候选：

```text
alphaprobe
AlphaMining-CogAlpha
```

### 我要看因子论文 / 券商研报里有哪些因子

```text
factor-research-db
```

### 我要做年报基本面 Agent

```text
sentinel
```

### 我要搭平台工作流 / 权限 / Artifact / Job

```text
quant_platform
```

### 我要做平台网页

```text
platform_web
```

---

# 10. 我建议你们正式固定的组件分层

未来最好直接在组织文档里固定这套：

```text
01 Data Layer
   data_access

02 Factor Definition & Compute
   factor_engine

03 Alpha Generation
   alphaprobe
   CogAlpha
   FactorMiner
   other miners

04 Evidence
   quant_evaluator

05 Search & Optimization
   factor_optimizer

06 Factor Asset Governance
   factor_assets

07 Feature Engineering
   factor_preprocess

08 Model
   modeling
   lightgbm_qs

09 Risk Model
   barra_engine

10 Portfolio Construction
   riskfolio_qs

11 Backtest & Execution Simulation
   vectorbt_qs

12 Research Platform
   quant_platform
   platform_web

13 Research Intelligence
   factor-research-db
   sentinel
   PaperRAG
   quant-knowledge-graph

14 Infra / Governance
   quant-ops
```

---

# 11. 对当前组织仓库结构的一个建议

现在的问题已经不是“组件不够”，而是**组件开始变多，容易重复造轮子**。

下一阶段建议维护一个：

```text
COMPONENT_REGISTRY.md
```

每个组件固定写：

```yaml
component_name:
canonical_repo:
owner_team:
status:
  - PRODUCTION
  - STAGING
  - RESEARCH
  - LEGACY
  - PLACEHOLDER

domain_authority:
inputs:
outputs:
depends_on:
consumed_by:
public_api:
artifact_types:
replacement_for:
deprecated_by:
```

例如：

```yaml
quant_evaluator:
  canonical_repo: HKUST-QUANT-SOCIETY/quant_evaluator
  status: STAGING
  domain_authority: evaluation_evidence
  depends_on:
    - data_access
    - factor_engine
  consumed_by:
    - factor_optimizer
    - factor_assets
    - modeling
    - quant_platform
  deprecated_aliases:
    - AutoFactorEvaluation
    - auto_factor_evaluation
```

这样以后 AI、新成员和不同组的人，不会再出现：

```text
“到底哪个 evaluation 是真的？”
“到底中性化写在哪里？”
“这个 cluster 是 platform 算还是 assets 算？”
“这个模型切分谁负责？”
```

这种架构漂移问题。

---

# 12. 最重要的 12 个仓库

如果只让一个新成员先记住 12 个，我建议就是：

```text
1. data_access
2. factor_engine
3. quant_evaluator
4. factor_optimizer
5. factor_assets
6. factor_preprocess
7. modeling
8. barra_engine
9. riskfolio_qs
10. vectorbt_qs
11. quant_platform
12. platform_web
```

如果是因子组，再额外记：

```text
13. alphaprobe
14. AlphaMining-CogAlpha
15. factor-research-db
```

这基本就覆盖了你们目前从：

```text
数据
→ 因子发现
→ 因子计算
→ 因子评估
→ 因子寻优
→ 因子资产
→ 特征处理
→ 模型
→ 风险
→ 组合优化
→ 回测
→ 平台
```

的完整体系。

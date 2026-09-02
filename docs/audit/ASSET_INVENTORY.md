# ASSET_INVENTORY.md — P-07 资产调研（v2，2026-09-01）

> **v2 权威源变更**：AG-C Step 0 调研（gh 只读）为基础，叠加**组长《HKUST Quant Society 常用组件清单》**（12 节，含组件分层、状态标注、legacy 映射、速查表）为定版权威。
> **v2 修正（对照组件清单）**：① barra_engine 由"归档"**更正为主链 S 级组件**（风险模型层，Riskfolio-QS 的上游）；② AlphaMining 家族、factor-research-db、sentinel、option-*、earnings-flash、quant-ops 等由"归档不蒸馏"**更正为专项/纪律层蒸馏**；③ lightgbm_qs 补 MISTAKES_AND_LEAKAGE_LESSONS.md 作工程约定蒸馏素材；④ alpha_flow 状态明确 SCAFFOLD。
> 下方 Step 0 原文保留（历史记录），与 v2 冲突处以本节及 §v2 分档表为准。

## v2 开放分档表（P-07 批次二权威，文档先行未实施）

| 档 | 仓库 | 卡片状态标注 | 属组/可见性 |
|---|---|---|---|
| **一档·主链全员常驻（12）** | data_access | PRODUCTION | 全员；56 语义字段清单 Mask |
| | factor_engine | PRODUCTION | 全员；写因子必走 DSL |
| | quant_evaluator | PRODUCTION（评估唯一权威） | 全员；禁自算 IC/ICIR |
| | factor_optimizer | STAGING | 全员一行 |
| | factor_assets | STAGING | 全员一行 |
| | factor_preprocess | STAGING | 全员一行 |
| | modeling | PRODUCTION（泄漏防护权威） | 全员一行；模型组深卡 |
| | barra_engine | PRODUCTION | 风控组深卡，他组一行 |
| | riskfolio_qs | PRODUCTION | 策略/风控 |
| | vectorbt_qs | PRODUCTION | 策略组深卡 |
| | quant_platform | **DRAFT**（未 V1_FROZEN 警示） | 全员一行 |
| | platform_web | PRODUCTION（前端镜像层） | 全员一行 |
| **二档·专项按组** | alphaprobe | STAGING（未产线跑通） | 因子组 |
| | AlphaMining-CogAlpha / factorminer / alphaschema / alphasage / AlphaBench | RESEARCH | 因子组 |
| | factor-research-db | PRODUCTION（225 研报/788 因子） | 因子组 |
| | lightgbm_qs | RESEARCH（脚本集非库） | 模型/因子 |
| | barra_research / barra_factor_evaluate_engine / size-factor-risk-model | RESEARCH | 风控组 |
| | option-backtestengine / option-pricing-line-code | RESEARCH | 期权组 |
| | sentinel | PRODUCTION（年报→结构化财务事实） | 基本面组 |
| | earnings-flash / quant-research-fundamentals | RESEARCH | 基本面组 |
| | PaperRAG / quant-knowledge-graph | RESEARCH | Agent 组 |
| **三档·纪律层（只蒸规则不蒸 API）** | quant-ops | — | 命名/权限/访问矩阵 → Agent 行为约束 |
| | backtest_repo_example | — | 项目样板 |
| **四档·负面清单（禁用+映射）** | quant-platform→quant_platform；quant-factor-engine→factor_engine；AutoFactorEvaluation / auto_factor_evaluation→quant_evaluator；旧 preprocess→factor_preprocess；旧 optimization→factor_optimizer；旧 registry→factor_assets | LEGACY | deprecated_aliases 写入卡片，防 AI 用错近名死仓 |
| | infra-* / test* / demo-repository / management-documents / workspace-* 等 | PLACEHOLDER | "不要用+不存在" |

**v2 硬纪律（进全部一档卡片 when_not_to_reinvent）**：① 读生产数据必经 data_access，禁止业务仓裸 `pd.read_parquet`/`pq.read_table`/`duckdb.sql` 直读；② 写因子必走 factor_engine DSL（挖矿算法产 DSL 不自造语法）；③ 评估一律调 quant_evaluator（NOT_COMPUTED≠0，禁自算）；④ 模型切分/泄漏防护必复用 modeling（walk-forward/purge/embargo）；⑤ 生产候选回测必过 vectorbt_qs accurate replay。

---

# 以下为 Step 0 原文（AG-C，2026-09-01，历史记录）



**方法**：`gh` 只读（`gh repo view --json` + `gh api repos/<org>/<repo>/readme` + `gh api .../commits/HEAD`），
逐 repo 实读 README 核实，不照抄初扫、不凭会议记忆手写。org `HKUST-QUANT-SOCIETY` 实测 **69 repo**（非 archived）。

**分层结论**（与主 Agent 初扫一致，已逐个 README 核实）：

- **核心层（14）**：全部 `pushedAt=2026-09-01`、非 archived、Python/TS 活跃开发 —— 逐节调研见下。
- **平台工程层（4）**：`quantcode` / `opencode` / `sentinel` / `hkust-quant-website` —— 平台自身的工程仓，
  不是研究员复用资产，**不进能力卡片**（P-08 Admin GitGraph 巡检对象）。
- **归档/历史层（51）**：`infra-*`（7）、`test*`（4）、旧 `quant-*` 系列（11，2026-05-17 后停更）、
  `AlphaMining-*`（5）、`barra_*` / 旧评估器（`AutoFactorEvaluation`/`auto_factor_evaluation`/`barra_factor_evaluate_engine`）、
  个人 workspace / demo / 文档仓等 —— **归档不蒸馏**。

---

## 核心层 14 repo 调研（每节：定位 / 语言 / 关键入口 / 对外 API 面 / 属组归属判断 / 蒸馏建议）

### 1. quant_evaluator —— 首批卡（asset）
- **定位**：批量因子评估器，返回类型化证据包；组织唯一评估能力（F-06 外部评估器登记的主对象）。
- **语言**：Python（v0.0.1a1，私有仓）。
- **关键入口**：`quant_evaluator.api`（`EvaluationRequest` / `EvaluationBundle` / `evaluate()`）、
  `quant_evaluator.contracts.label_bundle.LabelBundle`。
- **对外 API 面**：`LabelBundle`（显式前向标签，**硬口径 `price_convention="vwap_to_vwap"`**）、`FactorBatch`、
  `EvaluationBundle`（metric_values/diagnostics/grouped_metrics/series_refs/split_ref）、`SealedSplitRef`。
- **指标口径核实（Step 0 实测）**：README 自述"注册 60+ 指标"；权威清单
  `docs/METRIC_REGISTRY_COVERAGE.csv` 实测 **60 个 metric 行**。FUNCTIONAL_SPEC v0.2 的"51 注册指标"
  为旧口径，**卡片以实测 60 为准**（登记差异，spec 回填由主 Agent 裁决）。
- **属组归属判断**：factor（因子评估主用组；跨组经常驻摘要感知）。
- **蒸馏建议**：**首批六卡之一（asset）**。蒸 API 面（api/contracts 入口 + 指标注册表指针），不蒸指标实现。

### 2. factor_engine —— 首批卡（asset）
- **定位**：DSL 因子计算引擎——因子公式 → (日期×标的) 因子值，写因子湖。
- **语言**：Python（v0.3.x）。
- **关键入口**：`factor_engine.api`（`col/rank/ts_mean/Factor/parse_expr`）、
  `factor_engine.runtime.engine.FactorEngine`、`backend.factory.build_backend("auto")`、
  `storage.factory.build_data_source`（type=data_access）、`FactorEngine.run_from_config(yaml)`、`service/`（`factor-engine-serve` HTTP）。
- **对外 API 面**：DSL（仓库描述与 README 均口径 **460+ 注册算子**；架构表另注 cleaned_operators 单一实现源
  canonical 1737 / daily surface 1238——为算子实现态计数，注册口径以 460+ 为准）；执行后端 auto：
  SQL 下推 → Polars → Pandas；与 data_access 直连取数。
- **属组归属判断**：factor。
- **蒸馏建议**：**首批六卡之一（asset）**。蒸 DSL 入口 + backend/storage 工厂指针。

### 3. data_access —— 首批卡（asset，数据字段清单类 → Mask 语义适用）
- **定位**：全团队统一数据读写层——PIT 正确的 A 股行情 / parquet / 因子值读写唯一入口。
- **语言**：Python（v0.10.x）。
- **关键入口**：`data_access.get_store()` → `read / read_frame / read_uri / read_factors / read_joined / read_asof`；
  写 `write_arrow / upsert / publish_from_staging`；HTTP `data-access-server` + `DataAccessClient`。
- **对外 API 面**：注册表 `config/datasets.yaml`（**73 数据集**）+ `config/semantic_fields.yaml`
  （**56 语义字段**——**即"数据字段清单"，F-04 明文 Mask 对象**）；Filter AST 三编译器；成本路由 `read_auto`；
  PIT（`PITContract`/`read_cos_events_asof`/快照令牌）；COS mirror/remote/auto；ClickHouse 面板表；`QueryBudget` 治理。
- **属组归属判断**：factor（数据层属主组；字段清单细节对非属主/无权限组 Mask）。
- **蒸馏建议**：**首批六卡之一（asset）**。卡片只登记 `get_store` 门面与"别裸读"纪律；
  56 字段清单本体不进卡片正文（细节走属组 scope Memory，游客/无权限组 Mask）。

### 4. quant_platform —— 首批卡（asset）
- **定位**：平台集成/合同层——纯 stdlib DTO 契约 + auth/RBAC + outbox/worker/orchestrator 骨架；
  QuantCode 对接平台服务的正门。
- **语言**：Python（v0.1.0，**状态 DRAFT/WIP：未 V1_FROZEN，Control/Metadata 平面未建**）。
- **关键入口**：`app/contracts/*`（23 模块、`__all__` 135 项：artifact_ref/jobs/workflow/lifecycle(23 态)/
  rbac/backtest/factor_library/model_version/daily_snapshot...）、`app/adapters/data_access_storage.py`、
  `app/worker/` + `app/orchestrator.py`、`app/api/app.py`（FastAPI /auth /health）。
- **对外 API 面**：PURE-DTO 硬规则（contracts 禁止第三方依赖，零依赖可 import 有测试断言）；
  **平台不重算量化逻辑**（不算 RankIC、不落第二套因子湖）；域包不得 import 平台层；平台↔域翻译在 worker/adapters。
- **属组归属判断**：model（跨包 DTO 翻译与集成对接面）。
- **蒸馏建议**：**首批六卡之一（asset）**。卡片必须带 DRAFT/未冻结警示——契约以 reconcile 后版本为准。

### 5. alpha_flow —— 首批卡（asset，底层保密 → P-09 黑盒约束）
- **定位**：因子计算新底层（硬件性能控制与分配）；/deploy（P-09）部署适配的目标底层。
- **语言**：Python（uv 管理；模块脚手架态——生产实现 `NotImplementedError` 显式占位）。
- **关键入口**：模块边界 `alpha_core / alpha_data / alpha_mining / alpha_bus / alpha_materializer /
  alpha_eval / alpha_sink / alpha_monitor`；架构说明 `docs/quant_architecture.html`。
- **对外 API 面**：目前只有接口与契约面（脚手架），无稳定 API；uv 工作流（`uv sync --extra dev --extra gpu`）。
- **属组归属判断**：strategy（部署/生产执行侧；底层结构对普通研究员保密，P-09 黑盒约束）。
- **蒸馏建议**：**首批六卡之一（asset，最小卡）**。只登记存在性 + 模块边界 + "部署只能走 /deploy"，
  底层结构不进卡片正文（Mask 语义）。

### 6. alphaprobe —— 不进首批
- **定位**：torch 深/RL 因子挖掘框架（continuous miner、FE bridge 到 factor_engine、PPO/GFlowNet 基线）。
- **语言**：Python（v0.1.0）。**状态：代码完整、尚未产线跑通（阻塞=缺 cold-start 因子库 `COLD_START_LIBRARY_SRC`）**。
- **关键入口**：`python -m alphaprobe.runner`（单轮）、`deploy/run_continuous.sh`（7×24）、
  `fe_bridge.evaluate_via_factor_engine`、投递遵循 `factor_engine/docs/miner_delivery_spec.md`。
- **属组归属判断**：factor。
- **蒸馏建议**：暂不进首批（未跑通）；跑通后补卡。标签口径 vwap-to-vwap 与平台口径一致。

### 7. platform_web —— 不进首批
- **定位**：Quant Research Platform Web 前端（React 18 + TS strict + Vite 5，20 页面），前端只渲染后端数据。
- **语言**：TypeScript。`src/api/types.ts` 镜像 `quant_platform/app/contracts/*`（类型即合同）。
- **属组归属判断**：平台工程（P-08 Admin 中枢 UI 同源）。
- **蒸馏建议**：不进首批（前端镜像层，无可复用研究 API）。

### 8. factor_assets —— 第二批
- **定位**：因子资产注册表——身份/注册/去重/相似度/聚类/生命周期/入库治理的单一事实源。
- **语言**：Python（v0.1.0）。
- **关键入口**：`factor_assets.registry.factory.create_repository`、`identity.canonical.FactorIdentityProvider`、
  `create_factor_id`；适配器 QEEvidenceProvider/FEIdentityProvider/DACatalogReader（lazy、protocol-based）。
- **属组归属判断**：factor。
- **蒸馏建议**：第二批（因子入库治理链路成熟后）。

### 9. factor_optimizer —— 第二批
- **定位**：证据引导因子寻优——变异语法 + 搜索编排（sealed 切分）+ desirability/Pareto 验收。
  只经 adapter 协调 factor_engine 与 quant_evaluator，自己不算因子不产指标。
- **语言**：Python（v0.1.0）。
- **关键入口**：`factor_optimizer.search.runner.SearchRunner/SearchConfig/SearchSession`、
  `search.winner_selector.select_winner`、`search.uncertainty_winner`。
- **属组归属判断**：factor。
- **蒸馏建议**：第二批。

### 10. factor_preprocess —— 第二批
- **定位**：因子预处理/表示层——中性化（OLS/ridge/lasso/enet）、标准化、去极值、滚动/平滑、regime 检测，
  输出带 deep-freeze/因果契约的 `FeatureBundle`。
- **语言**：Python（v0.1.0）。
- **关键入口**：`registry.policies.get_default_policy_registry`（production_full/research_full/... 预设）、
  `registry.transforms.get_default_registry`、`contracts.feature_bundle.FeatureBundle`。
- **属组归属判断**：factor。
- **蒸馏建议**：第二批。

### 11. modeling —— 第二批
- **定位**：ML 模型层单一真相源——walk-forward 日期权威切分、purge/embargo、泄漏防护（含负向对照组）、
  `train_model → ModelArtifact`、预测评估。**所有时序泄漏防护都在本库执行**（`AUTHORITY.md`）。
- **语言**：Python（v0.1.0）。
- **关键入口**：`make_walk_forward_splits` / `date_bounded_split` / `assert_date_authoritative`、
  `TrainOnlyFitGuard`、`DecisionClock` / `LabelContract(return_basis="vwap_to_vwap")`、
  `train_model` / `predict_oos` / `evaluate_predictions`。
- **属组归属判断**：model。
- **蒸馏建议**：第二批（模型组核心资产）。

### 12. riskfolio_qs —— 第二批
- **定位**：cvxpy 配置驱动组合优化与风控——Barra 预计算/历史协方差、主动风险硬约束、行业/市值中性、PIT 契约。
- **语言**：Python（v0.3.0）。
- **关键入口**：`riskfolio_qs.adapters.BarraPrecomputedAdapter`、`runners.pipeline.OptimizationPipeline`、
  CLI `riskfolio-qs optimize`。
- **属组归属判断**：strategy（组合构建）/ risk（风控约束）——待权限分配方案定稿。
- **蒸馏建议**：第二批。

### 13. vectorbt_qs —— 第二批
- **定位**：A 股/美股组合回测（vendored vectorbt 1.1.0）——fast（因子筛选）/ accurate（真实成交，整手/费率/停牌拒单/公司行动）双口径。
- **语言**：Python（v0.4.0）。
- **关键入口**：`vectorbt_qs.mvp.engine.runner.run_backtest / portfolio_report`、
  `python -m vectorbt_qs backtest / run / batch / accurate-batch`。
- **属组归属判断**：strategy。
- **蒸馏建议**：第二批。

### 14. lightgbm_qs —— 不进首批（脚本集）
- **定位**：A 股因子研究主链路**研究脚本集（非库）**：因子矩阵 → LightGBM GPU walk-forward →
  vwap-to-vwap 标签 → vectorbt 回测。直接复用各平台库（factor_preprocess/vectorbt_qs/data_access）。
- **语言**：Python。
- **关键入口**：`build_adj_label.py`（后复权 10 日前向标签）、`train_lightgbm_gpu.py` 等脚本。
- **属组归属判断**：model。
- **蒸馏建议**：不进首批（非 API 库）；但 `MISTAKES_AND_LEAKAGE_LESSONS.md` 是
  **第二类蒸馏物（工程约定/Best Practice）**的现成素材，随 P-07 二类蒸馏入组 Memory。

---

## 平台工程层（4，不蒸馏，P-08 巡检对象）

| repo | 语言 | 说明 |
|---|---|---|
| quantcode | Python | 本平台仓（org 内 main 分支；本仓 feat/p0-production-readiness 分支的远端同步由主 Agent 管） |
| opencode | TypeScript | 载体层 fork（lens/panels/instructions） |
| sentinel | Python | 巡检/哨兵（初扫归平台工程层） |
| hkust-quant-website | JavaScript | 对外官网 |

## 归档/历史层（51，一行带过，归档不蒸馏）

`infra-rchenbq / infra-yejinxuan / infra-zhangjy699 / infra-2003yzhe / infra-allargandalf / infra-ebbtidexxx / infra-reclusion33`、
`test / test_risk / test_perm_check / workspace-sunhaiwei`、
旧 `quant-*` 系列（`quant-platform / quant-server / quant-risk / quant-factor-* / quant-agent-backend / quant-docs / quant-quantaalpha / quant-ops / quant-knowledge-graph`，2026-05-17 后停更）、
`AlphaMining-*`（AlphaBench/CogAlpha/factorminer/alphaschema/alphasage）、
旧评估器（`AutoFactorEvaluation / auto_factor_evaluation / barra_factor_evaluate_engine / barra_engine / barra_research / quant-factor-engine / size-factor-risk-model`）、
其余（`CTA-continuous-contract / data-access----CTA / option-backtestengine / option-pricing-line-code / option-*`、
`quant_resources / PaperRAG / earnings-flash / management-documents / demo-repository / backtest_repo_example /
multiagent_review_ci_standalone / factor-research-db / quant_benchmark_qinkailin / ashare_lqtp_kit / factor-frontend / quant-research-fundamentals`）。
共同特征：被核心层替代、停更或一次性产出 → **不蒸馏**。

---

## 首批六卡映射（→ configs/capabilities.yaml）

| 卡 id | type | 来源 | source_commit（Step 0 实测 HEAD） |
|---|---|---|---|
| target-return-view-v1 | contract | 本仓 `schemas/data_contracts.py::TargetReturnView/v1`（AG-B 已落） | （in-repo，空串+分支标注） |
| quant-evaluator | asset | quant_evaluator | `73223a4` |
| factor-engine | asset | factor_engine | `c374cbd` |
| data-access | asset | data_access | `b55656a` |
| quant-platform | asset | quant_platform | `45a8cc7` |
| alpha-flow | asset | alpha_flow | `5ea62c4` |

**蒸馏粒度守则**（写入卡片 schema 注释）：蒸 API 面（入口模块/门面函数/契约类型名），不蒸实现细节；
数据字段清单（data_access semantic_fields 56 字段）与部署底层结构（alpha_flow 模块内部）不进卡片正文。

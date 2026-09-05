# HKUST 组件复用交叉表

依据：用户提供的 [HKUST_QUANT_COMPONENTS_GUIDE.md](../references/HKUST_QUANT_COMPONENTS_GUIDE.md)，接收于 2026-09-05；主功能基线仍为三份顶层设计。2026-09-05 已只读核验 DataAccess、FactorEngine、QuantEvaluator 的私有仓 HEAD、打包声明和公开接口，详见 [F-06/F-08/F-09 台账增量](F06_F08_F09_LEDGER_2026-09-05.md)。以下 integration 为本地登记值；真实数据和真实授权尚缺，因此未升级为 CONNECTED。

| Canonical repo | 唯一职责 / 契约 | QuantCode 应复用的方式 | 本地 integration |
|---|---|---|---|
| data_access | PIT 数据、快照、Arrow/DataFrame/ReadHandle | 所有数据读取优先经此；记录版本/as_of，不自读另一套数据源替代 | PARTIAL |
| factor_engine | DSL/AST/因子计算 → FactorValue | 无因子值才调用计算；已有 FactorPanel 直接送 QE | PARTIAL |
| quant_evaluator | FactorBatch + LabelBundle + EvaluationContext → 评估证据 | 唯一指标权威；NOT_COMPUTED 不写成 0，不复制 IC/IR/成本公式 | PARTIAL |
| factor_optimizer | candidate/treatment + QE evidence → TrialLedger | 编排搜索与试验；搜索结果不能取代最终评估 | UNVERIFIED |
| factor_assets | 定义/值/证据 → 资产身份、去重、生命周期 | 复用身份/治理入口，禁止维护第二份因子真相 | UNVERIFIED |
| factor_preprocess | 因子值 + TreatmentRecipe → FeatureBundle | 中性化/标准化等处理归该组件，模型不再各自实现 | UNVERIFIED |
| modeling | FeatureBundle + LabelContract → ModelArtifact/PredictionBatch/OOS | 复用 walk-forward/purge/OOS，保留切分证据 | UNVERIFIED |
| barra_engine | PIT 输入 → B/F/D 与风险因子收益 | 风险模型权威；与组合构建分工 | UNVERIFIED |
| riskfolio_qs | alpha/risk/benchmark/previous positions/tradability/cost → positions/trades | 组合组件执行约束求解，平台仅传引用与记录 | UNVERIFIED |
| vectorbt_qs | positions + 行情/约束 → trades/NAV/report | 复用 fast/accurate 回测及 A 股执行约束 | UNVERIFIED |
| quant_platform | 领域 artifacts → API/metadata/jobs/RBAC/workflow | 复用业务 API/编排 DTO；不复制组件领域计算 | PARTIAL |
| platform_web | QuantPlatform API → 研究展示 | 作为外部研究门户，不在 QuantCode 前端另算业务结果 | UNVERIFIED |

已将 12 张主链卡片的 inputs/outputs/depends_on/consumed_by 补入本地目录，UI 显示并支持 canonical、别名及契约检索。保留成熟度与 integration 双状态；未因文档列出仓库而升级 CONNECTED。目录总计仍为 14 张：12 主链 + target-return 契约 + Admin 部署 scaffold。

## 名称与事实冲突

- `quant-factor-engine` 归 `factor_engine`；`AutoFactorEvaluation`/`auto_factor_evaluation` 归 `quant_evaluator`；`quant-platform` 是 `quant_platform` 的旧名称。别名用于检索，不能建立第二条调用路径。
- 统计写 FactorEngine 1737 个算子，旧本地目录写 460+。本轮去掉易过期数量承诺；只有真实版本的 manifest/API 能决定可调用算子集合。
- 统计的 QE 卡示例为 STAGING，本地旧 pinned-source 卡为 PRODUCTION/PARTIAL。保留原登记状态并在此记录冲突；后续应读具体 source_commit 与服务 smoke 证据再改，不能从示例推断上线状态。
- FactorMiner 出现两个名称，未擅自合并或选为 canonical。

## 其他可复用库如何落位

| 统计分组 | 处理 |
|---|---|
| alphaprobe、AlphaMining-CogAlpha、lightgbm_qs 研究脚本、FactorMiner、AlphaSage/Schema/Bench | 研究与验证增强候选；先查当前 repo/API/许可证/输入输出，再经候选治理登记。不取代 12 主链权威 |
| factor-research-db、sentinel、PaperRAG、quant-knowledge-graph | 研究信息/检索/监测候选；先验证数据权限与 PIT 约束。不得把检索内容自动晋升正式 Group Memory |
| quant-ops、CTA、期权等基础设施或专项库 | 对应组内部适配或部署基础设施；不新增统一领域产品，不暴露生产操作给普通 Agent |

下一次组件接入的最小证据：canonical repo + source_commit、版本化请求/响应 schema、授权方法、一个真数据成功 artifact、一个无权限/不可用失败样本、environment/result_status、调用及产物 evidence。取得这些证据后才能把 UNVERIFIED/PARTIAL 更新为 CONNECTED。

# Server C 业务组件接入核对

日期：2026-09-09。核对方式：本仓源码与配置、Server C 进程/监听器、只读健康接口、路径存在性与权限、指定进程环境变量的存在性。没有调用业务计算、写入正式数据、启动正式组件服务或发布新的业务工具。

## 结论与边界

Server C 已有 DataAccess、FactorEngine、QuantEvaluator、Modeling、Riskfolio-QS、VectorBT-QS 的源码副本。它们不是“仓库不存在”的外部阻断；需要由工程完成受控安装、契约适配和授权数据接入。源码存在不等于这些组件已经作为 QuantCode 可调用服务部署。

当前 QuantCode 的业务接线不完整：QuantEvaluator 只有一个未配置的 HTTP 适配器；DataAccess/FactorEngine 等配置主要是本地仓库位置提示；共享 Model-to-Risk Blackboard 未配置；策略、期权回测、财务提取和 DCF 的正常环境分支仍明确返回不可用。不能只把 QA 工具目录中的 disabled 改成 published 来解决。

进一步核对确认：`DATA_ACCESS_API_URL`、`FACTOR_ENGINE_API_URL` 在本仓仅作为 `future_api_env` 声明，没有实际请求消费者；QuantEvaluator 的 `spec` 仅为字典，响应任意字典即标记成功，尚未按 canonical EvaluationBundle 验证。`trigger_risk_flow` 仍是旧 PROJECT SQLite 队列操作，不包含 native 审批，也不在当前 22 项已审阅工具清单中。这些都是具体的适配实现工作，不能归因于缺少外部凭据。

八组模拟成员的原生 Agent 验收使用隔离 SSH 身份、真实 Qwen、真实文件读写、组织任务和产物接口，验证平台执行闭环。输入是明确标注的 QA 数据，不代表因子评估、风险模型、策略回测或估值业务已经验收。

## Server C 只读证据

| 核对项 | 观测结果 | 解释 |
| --- | --- | --- |
| 正式身份网关 | `quantcode-gateway.service` active，仍监听 `127.0.0.1:4097`，原 PID 与正式 roster/registry 摘要保持一致 | 正式身份服务未被本次 QA 替换 |
| QA 环境 | 独立 `5097` 网关、`qc-sim-*` 账号、`7101-7108` 原生宿主、独立状态与工具目录 | 这些端点属于模拟成员环境，不是正式业务组件 API |
| `127.0.0.1:8888` | 进程入口 `alpha_monitor.server:app`；`/healthz` HTTP 200，`status=ok`；OpenAPI 标题 `AlphaFlow Monitor`，仅 `/healthz`、`/readyz`、`/metrics` | 这是遥测监控，不是策略部署、评估或数据访问接口 |
| `9123` | 进程是 `python -m http.server`；`/health`、`/healthz`、`/openapi.json` 都为 404 | 不能把通用文件服务器当作领域 API |
| `8787` | 招募系统 Node 服务 | 与量化组件无关 |
| Canonical 源码 | `/srv/quant/research/evaluation/shared/data_access`、`factor_engine` 存在；研究员私有工作区另有上述六类源码副本 | 可用于后续版本审阅与安装，尚未核定这些可写 checkout 的正式发布版本 |
| 源码权限 | 共享 DataAccess/FactorEngine 目录为 `0770`、业务组 GID 1014；模拟 factor 账号不能读取。研究员私有副本同样不对模拟账号开放 | 需要受控安装或经授权服务访问，不应给 Agent 增加业务服务器附加组来绕过隔离 |
| 组件环境配置 | 正式 gateway 和已部署 QA factor 宿主都没有以下变量的有效值：`QUANT_EVALUATOR_API_URL/API_KEY`、`DATA_ACCESS_API_URL`、`FACTOR_ENGINE_API_URL`、`MODELING_API_URL`、`BARRA_ENGINE_API_URL`、`RISKFOLIO_QS_API_URL`、`VECTORBT_QS_API_URL`、`QUANTCODE_SHARED_BLACKBOARD_DB`、`QS_DATA_BACKEND`、`QS_DATA_STAGING_ROOT` | 本次只输出存在性布尔值，没有输出或记录凭据内容。这只说明被核对的 QuantCode 进程未配置，不推断全组织其他机器没有服务 |
| 默认 staging 输入 | `tools/market/backing.py` 默认路径下的 `selected_pool.csv` 在 Server C 不存在 | 当前 `list_factors/pool_browse` 的默认后端没有可用输入，不能把空数据当业务成功 |
| 报告工具 | `/usr/bin/typst`、`/usr/local/bin/typst` 均不存在 | Markdown 渲染与 PDF 编译须分别验收 |

本次没有发现上述领域组件的独立业务 API 监听器。此结论限定在实际检查的 Server C 监听器、进程与 QuantCode 配置，不排除组织在其他服务器或内部网关部署了服务。

## 分组业务前提

| 组/能力 | 当前实现依据 | 可以由工程补齐的部分 | 业务运行前必须确认的输入/授权 |
| --- | --- | --- | --- |
| factor：QuantEvaluator | `tools/factor/quant_evaluator_adapter.py` 读取 `QUANT_EVALUATOR_API_URL/API_KEY`，POST `/evaluate`，请求体为 `factor_spec + version`；缺配置返回明确 `UNAVAILABLE` | 核对 canonical `EvaluationRequest/FactorBatch/LabelBundle/EvaluationContext` 与当前 HTTP 请求的映射，安装受审版本或接现有 API，保留真实响应/版本/错误状态 | 确定 API 或本机包入口、调用身份，以及真实 FactorBatch、目标收益 LabelBundle、PIT/as-of、universe、日期范围。不能把模型猜测或 proxy returns 当标签 |
| factor：DataAccess/FactorEngine | `configs/local_components.yaml` 只有两个个人电脑绝对路径，其余为空；`scripts/check_local_components.py` 只检查目录，未导入或执行；Server C 有源码副本 | 形成管理员管理的只读版本安装，接 DataAccess 存储/快照与 FactorEngine DSL 执行接口，将结果翻译为既有 DTO；无需重写计算引擎 | 数据集 ID、字段/频率/复权/PIT 口径、数据源快照与访问权限、计算资源限额。存在源码不自动授予 COS/ClickHouse/共享目录访问权 |
| factor：既有 staging 工具 | `tools/market/backing.py` 只支持 staging；默认池文件不存在；`load_returns_impl()` 当前固定返回 `no_source`；`eval_from_panel` 在正常环境直接不可用 | 接 canonical 数据和评估链，修补返回契约与来源记录 | 真实池目录或授权数据服务，以及真实收益源；禁止开启 fixture 标志来制造 IC/回测结果 |
| model：ModelSpec/训练 | `generate_model_spec` 是真实 Pydantic 校验；Modeling 源码存在，但当前 QuantCode 无训练服务调用接线 | 直接保留纯契约校验；受控接入 Modeling 包/API与 OOS 结果引用，完成模型/特征/标签契约映射 | FeatureBundle、LabelContract、walk-forward/purge/embargo 口径、训练版本与算力授权。PR 读取另需与成员绑定的 GitHub 授权 |
| model → risk：共享交接 | Native `write_blackboard`/`read_blackboard` 已要求 `QUANTCODE_SHARED_BLACKBOARD_DB`、精确 `shared.model_entries.*` key、版本、实时身份与 Gate；当前没有共享 DB 配置；旧 `trigger_risk_flow` 仍写 PROJECT queue | 建立真正的组织权威共享服务与受控适配，绑定 native Gate/回执，审查队列消费与原生任务关系 | 由服务维护方确定共享库/服务身份与权限、真实 ModelSpec/PR/commit 关联及 model/risk 成员授权。不能把各成员私有 `.quantcode` DB 指成“共享” |
| risk | `risk_verdict` 对给定 RiskProfile/Thresholds 是确定性规则；`calc_risk` 提供真实 returns 时只替换回撤、VaR、波动率，其仓位/相关性/容量仍来自 stub 并有标注；无 returns 的生产调用被拒 | 保留契约与阈值规则；对接风险权威计算与收益输入，逐字段去除生产占位值；按具体 effect 发布 | 真实收益、持仓/限额、相关性、容量与风险模型输入；需要 Barra 时确认 B/F/D 等权威产物。未确认 Barra 服务端点或本机受控安装 |
| strategy | `select_signals/combine_signals` 只是权重排序/归一化；`run_strategy_backtest` 在正常环境固定返回 VectorBT-QS 未接通；本机内部引擎只在明确测试开关下使用合成价格 | 接已存在的 Riskfolio-QS/VectorBT-QS canonical 源码或服务，替换当前硬拒绝分支为受控真实调用，保留报告来源与成本口径 | alpha、风险矩阵、基准、前期持仓、可交易约束、成本、行情/公司行动、日期范围；不能把简化组合器与合成回测称为正式策略验收 |
| options | `build_vol_surface` 与 `calc_greeks` 有 BS 数值实现；曲面缺数据时仍可返回 `data_quality=mock`，默认 CSV 并非实时行情；期权回测正常环境固定不可用 | 对接期权 canonical 引擎和数据入口，先修明确缺数据状态与读写边界，再按真实 effect 审核发布；已有数值单测不能替代行情契约 | 授权期权链、时间戳、标的/远期价格、利率、到期日、合约乘数与真实持仓腿；需要组内确认适用模型和真实回测接口 |
| fundamental | PIT 检索有 `published_at <= as_of_date` 过滤，但 Chroma 初始化/回退仍围绕测试 fixture；QA backend 未包含该 fixture；财务提取与 DCF 正常环境固定 `STAGING/UNAVAILABLE` | 建立受控真实语料入库与来源/版本记录，接 canonical 财务和估值能力；报告 Markdown 可以独立接入，PDF 需工具安装和版面验收 | 真实已授权研报/公告、发布时间与 as-of、可核对财务数据、估值假设与责任人。不能用测试语料、按 ticker 生成的财务数字或简化 DCF 冒充研究结果 |
| infra / agent | Native Shell 平台原先缺 Bubblewrap，安装后还受到 AppArmor 用户命名空间策略约束；已在独立 QA profile 下用现有构造器验证隔离 | 将审核过的 OS 支持纳入正式宿主部署流程，再对具体工程仓库/命令做授权范围验收 | 明确可操作仓库/服务、只读或精确写入范围、资源限制；QA profile 的验证不等于可以访问生产服务账号或运维凭据 |

## 当前可执行的工程工作

1. 整理已有 canonical 仓库的正式版本、API/包入口与 DTO，采用受控只读安装或已有服务调用。`local_components.yaml` 的“未来环境变量名”目前并不构成真正适配器。
2. 完成 DataAccess → FactorEngine → QuantEvaluator 的真实契约接线。当前 `load_returns=no_source` 与旧 `factor_spec` HTTP 请求需要单独处理。
3. 部署组织权威 Blackboard 接口，补齐 native 审批、版本比较、回执与 risk 消费，保持成员进程隔离。
4. 把策略、期权、财务、估值的正常环境硬拒绝分支替换成实际 canonical 调用。测试替身保持明确测试限定，不作为生产降级。
5. 将每项工具的真实 effect、参数、源码版本、服务配置和授权范围纳入原有发布流程。未审阅的工具继续默认拒绝。

## 不能由测试替代的条件

- 数据与组件责任人需要确认实际服务入口或可部署版本、成员/服务账号权限、数据集与快照、PIT 与标签口径及验收参考结果。
- 研究任务需要具体且授权的业务输入。只有源码、示例数据或健康 HTTP 200，都不足以证明真实业务闭环。
- 当前八个模拟成员只有隔离 QA 输入和工作区，没有自动取得研究共享目录、业务 API、GitHub 或生产服务账号授权。
- Server C 根盘曾在本轮耗尽。本次仅去重已停止的 QA 二进制恢复空间；只读检查见 `/tmp` 约 980 GB，其他用户数据未清理。磁盘容量与并发资源仍是正式推广前的实际运营条件。

因此，基础 Agent 生命周期与领域业务验收必须分别记账：前者通过不能覆盖后者；后者未通过时应记录具体缺失的适配、输入或授权，不能仅写“工具未发布”或笼统归为外部环境阻断。

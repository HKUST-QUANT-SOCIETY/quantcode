# QuantCode 中长期总计划（对标 Z code，迈向工业级组合研究平台）

> 版本：v2（2026-09-01 功能定版修订）。v1（2026-09-01）方法：6 个域规划 subagent（R1 对标审计 / R2 引擎沙箱 / R3 数据回测 / R4 风控合规运维 / R5 产品协作 / R6 算法研究）各自只读调研 + 出规划，主 Agent 整合交叉依赖与协作机制。v2：并入功能定版会议三项裁决（平台红线 / HumanGate 写操作收窄 / 蒸馏+Admin 双支柱），季度归属补 P-07/P-08/P-09（新增 R7 蒸馏 / R8 Admin / R9 部署域）。
> 现状基线：后端 34 簇偏差修复收官（890 tests）、lens UI 品牌壳渲染成功（543 tests）、qs-cold 数据湖已勘察（247 因子池，PIT 字段内建）。

---

## 0. 对标结论（Z code 能力维度 × 量化独有域）

| 维度 | 现状评级 | 主要缺口 |
|---|---|---|
| 多会话/并行 agent | 无 | parallel_scheduler、spawn_subagent、任务树 |
| 终端/代码执行+review | 部分 | 幽灵 tool 清理、PR diff 只读 tool |
| MCP 生态 | 有 | SchemaTask 接线（最小） |
| 权限与沙箱 | 部分 | permission_engine、SSH 完整认证、三层沙箱 |
| 记忆与回放 | 有 | dream/RLHF 消费端闭环 |
| 可观测性 | 部分 | token 预算、告警、成本核算 |
| **行情数据接入** | **无** | tools/market/（**最高优先级，多域依赖**） |
| **PIT 因子面板** | 部分 | FactorPanel 契约（qs-cold schema 直接映射） |
| **回测引擎** | **无** | vectorbt/自研（A 股 T+1/涨跌停/费用） |
| **组合构建** | 部分 | Portfolio 层（construct_portfolio/风险预算/rebalance） |
| 实盘/模拟盘接口 | 无 | execution 组（模拟盘先行，permission 挂钩） |

**核心判断**：平台骨架（双形态执行+MCP+Blackboard+HumanGate）是对的；真正的差距在**数据→回测→组合这条量化主线完全空缺**。本计划以此为主轴。

---

## 1. 四季度总路线（跨域汇总）

### Q1（2026Q4——当前季度）：契约与地基础石
| 域 | 里程碑 |
|---|---|
| 数据 R3 | D1 数据契约层（FactorPanel/ReturnsDataset/StrategyManifest 真实 schema 映射）+ D2 本地 staging dev 后端 |
| 引擎 R2 | R0 三执行形态收敛（AgentRunner 唯一动态引擎 + compose_executor 声明态）+ R1 tiktoken 实测 + R2 token 预算硬约束 |
| 风控 R4 | G1-L1 组合级事前约束内建 + G2-A1 全链路审计日志★ + G3-A1 metrics 分组 + G4-A1 permission_engine 三态 + **G2-A8 HumanGate 写操作收窄（v0.2 定版：产出/代码不 gate，RiskThresholds 越限 verdict 直接 fail）** |
| 算法 R6 | A1 因子挖掘工具化（submit_candidate→真评估→入池治理），autoeval 去 mock |
| 产品 R5 | U1 会话页三栏化 + 指标卡组件族（BigNumber/ProgressGauge/Checklist）+ **F-05 SSH 登录界面（用户点名，完整登录流程非只读卡片）** |
| **蒸馏 R7（v0.2.2 修订）** | **P-07 调研先行 + 首批蒸馏**：Step 0 gh 只读资产盘点（org 69 repo→核心 14 活跃，产出 ASSET_INVENTORY.md，禁止凭记忆手写卡片）→ 六张能力卡片（目标收益口径契约 TargetReturnView/v1 + quant_evaluator 60 指标（METRIC_REGISTRY_COVERAGE.csv） + factor_engine 460+ 算子 + data_access + quant_platform DTO 契约层 + alpha_flow）→ 常驻组上下文 + 复用纪律（覆盖不全先问人，严格模式可配） |
| **工作流 R10（v0.2.1 新增）** | **P-10 方案先行（Solution-First）**：SolutionDoc 状态机（draft→2-3 轮讨论→frozen）+ 冻结前写类工具阶段限流（复用组 allowlist，非 HumanGate）+ judge 方案↔代码一致性判定 + lens 方案面板；`docs/audit/PLAN_SPEC_V02_DISPATCH.md` AG-J |
| **Admin R8（v0.2.2 提前）** | **P-08 本轮全量**：Admin 组建立（唯一跨组 scope）+ 跨组 list_runs 语义查询 + 错误记录汇总（非 Admin 被拒）+ **GitGraph 面板（repo 树/更新节点标红）+ 双类 pop（repo 提交 / package 版本更新，全组可见）——用户点名关键设计，自 Q2 提前** |
| 修复债 | replay.py bootstrap 自愈、三组 allowlist 幽灵 tool 注释化清理、consistency 断言测试 |

### Q2（2027Q1）：服务化与并行
| 域 | 里程碑 |
|---|---|
| 引擎 | R3 spawn_subagent（签名+预算隔离+共享 Blackboard 写策略）+ R4 kill/task registry + R5 会话树 |
| 数据 | D2a qs-data 只读服务（Server A，group 粒度 key）+ D2b COS 凭据服务化边界 + D3a 回测引擎选型 PoC |
| 算法 | A2 组合因子模型（正交化+XGB/LGBM 对比，产出 composite_score） |
| 风控 | G1-L2 模拟盘持续监控（cron 阈值扫描）+ G2-A2 产物不可变指纹★ + G3-B1 三机部署拓扑（A=dev/CI，B=主线+模拟盘 cron，C=对外+凭据宿主——首期文档落地：`deploy/README.md` + `deploy/quantcode.service.example`）+ G4-B1 SSH 全操作认证 + **F-03 触发点②：SSH 写生产环境挂 HumanGate（kind=deploy）** |
| **蒸馏 R7（v0.2）** | **P-07 扩面**：蒸馏粒度制度化（蒸 API 面不蒸实现细节）+ 能力卡片 CI 校验（接口面 vs 代码一致）+ 游客组 Mask 生效 |
| **Admin R8（v0.2.2）** | **P-08 深化**：报告管理/任务管理日常工作台入口（GitGraph 与双类 pop 已提前至 Q1 交付） |
| **部署 R9（v0.2）** | **P-09 /deploy 黑盒命令**：已调试代码 → AlphaFlow 部署库适配，全程不泄露底层（权限 Mask + 正常询问不透露）；依赖 F-05 登录界面 |
| **工作流 R10（v0.2.1）** | **P-10 深化**：solution 模板 SKILL 化 + 与蒸馏闭环（A4）联动消费；一致性判定接 OOS 纪律 |
| 产品 | U2 四屏逐屏落地（因子评估屏→审批屏），Linux 打包补齐 |

### Q3（2027Q2）：真实引擎与合规交付
| 域 | 里程碑 |
|---|---|
| 数据 | D3b 回测真算（vectorbt/自研，对账误差=0）+ D3c 因子评估真实化（IC/分层/换手，对齐 RQAlpha 基线）+ D3d sharpe 收尾 |
| 引擎 | R6 三层沙箱（L1 研究执行/L2 数据拉取/L3 生产部署）+ R7 qs-data 服务化 + R8 流式 trace（SSE，10 类事件+2 新类，向后兼容） |
| 风控 | G2-B1 evidence chain 合规报告生成★（给投资人/学校：run 指纹链+决策署名 PDF）+ G3-B2 告警与 token 成本 + G4-C1 Secret 管理（注入+90 天轮换） |
| 算法 | A3 算法实验管理（A/B 对比、排行榜、OOS 纪律由 acceptance 强制） |
| 产品 | U3 通知中心+artifact 分享+approver/analyst 权限差 |

### Q4（2027Q3）：组合与实时
| 域 | 里程碑 |
|---|---|
| 数据 | D4 组合层全量（TargetPortfolio/RiskBudget 契约、construct_portfolio 风险平价/min-var/scipy 优化、rebalance_plan 成本模型、check_portfolio_gate 复用 HumanGate，阈值进 portfolio.yaml） |
| 引擎 | R9 韧性全面化（崩溃恢复不重跑成功 tool）+ R10 跨机 checkpoint 共享（Server A 统一存储）+ R11 任务树前端化 |
| 算法 | A4 自进化闭环激活（distill→SKILL.md 转正 ≥3 个被实际调用；judge RLHF ≥200 条标注）+ A5 本地模型路由（qs-gpu 小模型 schema 合法率 ≥95% 且成本 <1/5 的任务切本地） |
| 产品 | U4 三平台发布+beta 通道热更+反馈回流闭环 |
| 风控 | G1-L3 实时风控（前置：L2 连续一季度零降级事故）+ G2-C1 审计日志 COS 冷归档（WORM）+ G3-C1 容量演练（RTO/RPO） |

---

## 2. 关键架构决策（已定案）

1. **执行形态收敛为两态**：AgentRunner（ReAct 动态，唯一引擎）+ compose_executor（声明式 DAG，仅确定性流水线）。risk_agent 固定 DAG 废弃为 skill 配置。
2. **数据进 Blackboard，不进 prompt**：typed 契约对象（`_contract: FactorPanel/v1` 版本戳）走 `shared.datasets.*`，LLM 只见 key+摘要+工件引用——防 stub 假数据再混入，新算法工具间即插即用。
3. **配置不喂 LLM**：阈值/算法注册表（portfolio.yaml / algorithms.yaml / acceptance.{group}.yaml）给引擎与 acceptance 读，带 schema 校验；LLM 白名单由注册表**生成**，根治 allowlist 漂移。组合权重等数值必须确定性代码，LLM 只表达意图且经 gate 校验。
4. **权限三态引擎**（ask/deny/allow）挂钩：render_report/deploy/publish/pit 链路 + 组合 gate；沙箱三级：L1 研究代码（容器/无网）→ L2 数据（只经 qs-data tool）→ L3 部署（仅 HumanGate approve 后专用 tool）。
5. **合规脊柱**（学校/投资人 must，优先于一切实时化）：组身份 → permission_engine → 全链路审计日志 → 产物不可变指纹 → evidence chain 报告。
6. **平台红线（v0.2 定版）**：QuantCode 不做业务层面的东西（策略/回测/组合/期权产品归组自研与报告平台）；回测/组合引擎代码保留为**组内工具适配层**（不做 UI、不进产品索引）。
7. **HumanGate 写操作收窄（v0.2 定版）**：产出不 gate（报告平台承接）、代码不 gate（CI/PR 承接）；四类写操作触发点（merge/SSH 生产写/跨组访问/预算）。避免 Z code 式"每个动作都批准"把用户逼成完全访问的退化。
8. **最大复用原则（v0.2 定版）**：能力卡片常驻组上下文（P-07）；Agent 方案首选已登记能力，覆盖不全**先向人征询，不许直接跳自造方案**。
9. **蒸馏粒度（v0.2 定版）**：蒸 API 面，不蒸实现细节；权限权威源 = 用户组权限分配方案（Git 权限同源对齐），游客组 Mask。

## 3. 交叉依赖主线（跨域硬依赖）

```
数据契约(D1) ──→ 回测真实化(D3c) ──→ 算法A2组合因子 ──→ 组合层(D4) ──→ 模拟盘(G1-L2) ──→ 实时(G1-L3)
     │
     └──→ qs-data 服务化(D2a) ──→ 跨机 checkpoint(R10) ──→ 沙箱(L2 数据访问)
审计日志(G2-A1) ──→ 不可变指纹(G2-A2) ──→ evidence chain(G2-B1）
trace 流式(R8) ──→ lens 四屏实时渲染(U1/U2)
token 预算(R2) ──→ spawn_subagent 预算扣减(R3)
蒸馏闭环(A4) ←── A3 实验归档（trace 来源）
```

**最高优先级单点**：`tools/market/`（qs-cold 数据接入）——R3/R4/R6 三域共同依赖，无它则回测/组合/真实评估全部空转。

## 4. Subagent 协作机制（每个域常驻协作代理）

| 代理 | 角色 | 协作触发点 |
|---|---|---|
| R1 对标审计 | 季度末对照 Z code 能力维度复评，产 delta 报告 | 每季度末 + 大版本后 |
| R2 引擎 | 执行层设计的 design review（并行/沙箱/流式接口草案评审） | 引擎 PR 前 |
| R3 数据回测 | 数据契约与选型评审（schema 变更/引擎选型对账口径） | 契约变更时 |
| R4 风控合规 | 合规 must 清单守护（每个里程碑出"合规红线检查"） | 每里程碑 |
| R5 产品协作 | 设计稿 vs 实现的像素级偏差 review（v5 PPT 四屏对照） | UI PR 前 |
| R6 算法 | 研究方法论审稿（OOS 纪律/过拟合风险/入池规则） | 算法入池前 |

**工作约定（继承既有纪律）**：执行 agent 只读改自己的文件集 + 禁 git 操作；每域产出必须带"数据依赖+验收标准"；PonyTail 方法论全文注入；每季度末跑一轮"对原始发现反查"的独立红队核验（吸取 P1-6/replay 两处遗漏的教训：**验收即用户路径 + 配置体必须有 consistency 测试**）。

## 5. 风险与缓释

| 风险 | 缓释 |
|---|---|
| COS 凭据权限解锁卡进度（root 拥有 .ro 配置） | 本地 staging 为 dev 后端先行；Q1 末凭据服务化 |
| qs-cold 无行情收益数据（只有因子值） | D2 Q2 增补行情接入项；先用 backend 现有行情表验证 D3 |
| 247 池过拟合风险（IC 是筛选期算的） | D3c 用 OOS 复核全池；acceptance 加 oos_discipline |
| 并行 agent 复杂度失控 | Q2 单季度只做 spawn/kill/树三件事，沙箱先于并行调度验证 |
| 实时风控过早启动 | 硬门槛：L2 模拟盘连续一季度零降级事故 |

## 5. 立即可启动（下一轮 3 件事）

1. **D1+D2-dev**：`schemas/data_contracts.py`（FactorPanel）+ staging dev 后端 + `load_factor_panel` 工具 → 一个入选因子（GTJA191_M019）跑通真实 IC 报告替换 mock；
2. **两处遗漏小修**（replay bootstrap + allowlist 注释化）+ allowlist 一致性断言测试（P1-6 教训制度化）；
3. **U1 前置**：lens 会话页三栏布局骨架 + metric-cards 组件（先渲染现有 output_data 字段）。
## 6. A3 首期落地（2026-09-01）：配置单源 + 算法注册表

- **三套阈值口径从 YAML 单源**（架构决策 3「配置不喂 LLM」）：`configs/acceptance.factor.yaml`（0.03/0.5/0.8/2.0）+ `configs/acceptance.risk.yaml`（0.15/0.8/0.05/0.6）为唯一真源；`runner/config_loader.py`（lru_cache + `QUANTCODE_CONFIG_DIR` 覆盖 + 极简 schema 校验）→ `runner/acceptance.py` yaml 优先 / 代码默认兜底（缺文件 warning 一次）；`runner/risk_agent._risk_acceptance_thresholds` 改引同一出口 `runner.acceptance.risk_thresholds()`。数值 = 现默认，行为零变化。
- **signal_algorithms 注册表首例**：`configs/algorithms.yaml` 两条目（equal_weight_composite_ranker 真实 demo 评分器 + pb_roe_ranker 占位→tools/factor PB-ROE 线注释映射）；执行端 `tools/algorithms/_register.py` 三工具 `list_algorithms` / `describe_algorithm` / `run_algorithm`，demo 评分器 `tools/algorithms/score_demo.py`（读 Blackboard `shared.datasets.panel/*` FactorPanel，最新截面等权 rank 合成，返回 top_n 资产表）；`quantcode/mcp_server.py` 经 `_meta` 通道六组 MCP server 可见（不进组 allowlist）。

## 7. 真实数据因子评估首例（2026-09-01）：panel_real_v1

- `flows/factor_eval_real.py`（engine=panel_real_v1）+ `tools/factor/eval_from_panel.py`：读 Blackboard `shared.datasets.panel/*` FactorPanel 契约，纯 numpy 算真实 Spearman rank IC / 换手（top decile Jaccard，21 交易日窗口）/ 5 分层多空差 → FactorReport 兼容 dict → verdict 按 `runner/acceptance.factor_thresholds()`（configs/acceptance.factor.yaml 单源）+ run_acceptance 复核 → 写 `artifacts/factor/{name}-report-real.json`。代理收益=次日因子值变化率（因子动量），已显著标注，R3 域接 StockDailyBar.Return 后在 build_returns_from_panel 单点替换。

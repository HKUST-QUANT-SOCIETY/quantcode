# QuantCode v5 实现审计

> 日期：2026-09-04
> 规范：FUNCTIONAL_SPEC v0.5 / PRD v5 / Design v5 / UI Spec v4
> 测试环境：macOS、Python 3.12、本地 Mock/fixture；外部生产服务未连接

## 1. 结论

| 模块 | 功能性 | 完整性 | 可维护性 | 结论 |
|---|---|---|---|---|
| Session Group / MCP Tool Catalog | 通过 | 生产 fail-closed；开发降级需显式 `QUANTCODE_ENV` | list/call 共用 effective set | 继续使用 |
| SSH Identity / Roster | 后端挑战签名、指纹和 SessionContext 已实现 | 桌面 Identity Picker 属外部 `opencode-lens`，本仓无法验收 | 私钥不进服务端；roster 字段版本化 | 外部 UI 待接 |
| AgentRunner / ReAct | 通过 | Run、Trace、Checkpoint、Resume、Context rebuild 可用 | 删除 risk/budget/loop Gate 分支；状态单一 | 继续使用 |
| Budget / Loop | 通过 | `stopped_budget` / `stopped_loop` | 不再混入 HumanGate | 继续使用 |
| HumanGate | 通过 | Schema 仅允许 `merge` / `permission` | 通用 Envelope；风险字段已移除 | 继续使用 |
| Admin Deploy | 管理面 API 与黑盒 staging Adapter 可用 | 真实生产队列/服务账号是外部依赖 | 普通 Catalog 不注册 Deploy；Evidence 必写 | 外部生产 Adapter 待接 |
| Group Memory | 通过 | FTS5、Group ACL、显式 reconcile 可用 | Runtime task 嵌套 session，不是顶层 Memory；查询不再默认全盘扫描 | 继续使用 |
| Capability Catalog | 通过 | 14 张卡（12 个 canonical 主链卡 + 契约/部署卡）；摘要/详情分层 | Pydantic/JSON Schema v2；成熟度和接入状态分离 | 继续使用 |
| Blackboard / Handoff | 通过 | Scope ACL、Artifact 引用和事务写入 | `BEGIN IMMEDIATE` 消除读改写竞争 | 继续使用 |
| QuantEvaluator Adapter | 通过 | canonical API Adapter 可用；断连返回 `UNAVAILABLE` | 删除 mock 指标 fallback；proxy evaluator 不进生产 allowlist | 继续使用 |
| Risk CI | 通过 | `risk_verdict` + CI 报告；高风险不阻断 | 旧 risk-gate/Resume 流删除并改名 `risk_ci` | 继续使用（CI 基建） |
| Portfolio | 通过 | 确定性 `portfolio_verdict` | 删除 requires_human/interrupt 字段和旧 Gate 名称 | 继续使用（Adapter） |
| Strategy deployment handoff | 通过 | 只生成 `deployment_candidate` | 删除 `deploy_strategy` 生产语义 | 继续使用 |
| Evidence / Metrics | 通过 | 哈希链、Artifact 绑定、actor/role、有限 tail 读取 | 并发文件锁；关键管理/合并写入 required | 继续使用 |
| P-10 Task Classification | 通过 | 四维分类与 L0-L3/Solution 要求已实现 | 复杂度不再代替权限 | 继续使用 |
| GitGraph / Pop | 契约、Baseline、依赖 diff、Dedupe/read/ack 已实现 | GitHub 后台同步和系统通知需部署环境 | SQLite Pop + 原子 baseline；错误/partial/stale 状态显式 | 外部同步服务待接 |
| 六组领域工具 | 可回归 | 非 canonical 的 stub/proxy 仅开发用途 | 不进入产品主线或生产 allowlist | 有条件保留 |

## 2. 本轮已删除的旧语义

- 风险越限、预算耗尽和循环检测创建 HumanGate；
- `kind=risk|budget|deploy`；
- 普通 Agent 注册或调用部署工具；
- `deploy_strategy` 返回生产成功；
- `check_gate` / `risk-gate` 产品主链；
- `check_portfolio_gate` 与 `requires_human`；
- QuantEvaluator 不可用时返回 mock IC/IR；
- 顶层 `tasks` Memory scope；
- 每次 Memory 搜索前全量磁盘 reconcile；
- metrics 读取整个无界 JSONL；
- Capability Card 用单一 `status` 混淆成熟度和接入状态；
- 长期技术设计内嵌易过期源码行号。

## 3. 保留但重新归类

- Model→Risk：GitHub Actions/CI compatibility flow；
- 线性 Flow：CI/兼容与确定性回归，ReAct 仍是产品主路径；
- 本地因子 proxy evaluator：开发回归工具，结果为 `PROXY`，不进入生产 allowlist；
- Strategy、Options、Fundamental、Portfolio：领域 Adapter 与契约回归，不是 QuantCode 业务产品；
- Dream/Distill：只生成候选，正式 Memory/Skill 仍需确认。

## 4. 外部依赖与不能伪装完成的项

1. `opencode-lens` 的 SSH Identity Picker、自由切组删除、Admin Console 和真实 Memory/GitGraph UI；
2. SSH gateway 的生产 roster、证书轮换与 Session 签发部署；
3. QuantEvaluator、DataAccess、Modeling、Barra、Riskfolio-QS、VectorBT-QS 的真实服务连接；
4. Admin Deploy 生产队列、服务账号和回滚协议；
5. GitHub App/OAuth token broker、后台同步进程和操作系统通知。

这些模块当前必须返回 `UNAVAILABLE`、`STAGING`、`PARTIAL` 或明确错误，不能显示生产成功。

## 5. 测试报告

```yaml
spec_version: v0.5
date: 2026-09-04
environment: macOS / Python 3.12
external_services: not connected
real_or_mock: local deterministic tests; external adapters mocked or unavailable
test_scope: full pytest + v5 contract suite
known_legacy_tests: migrated or deleted
```

本轮结果：`987 passed, 4 skipped, 1 warning`。4 个 skipped 均为需显式真实 LLM 凭据的集成测试；单独的通过数不构成生产验收。唯一 warning 是 Pydantic 的 `ToolDef.schema` 字段遮蔽 `BaseModel.schema`；该字段已被工具注册表和客户端广泛使用，暂保兼容，后续若迁移应通过版本化 alias 一次完成。

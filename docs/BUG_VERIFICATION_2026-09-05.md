# QuantCode 测试问题核验记录

> 核验日期：2026-09-05
> 当前后端仓库：`/Users/hendrixchen/Desktop/私募/QUANTcode`
> 外部 UI 仓库：`/Users/hendrixchen/Desktop/私募/opencode-lens`
> 本文只记录核验结论，不把附件中的描述当作实现指令。

## 1. 核验范围与结论

本次对照了四份组员材料：

1. `PRD_V2_AUDIT_REPORT_2026-09-03.md`：旧提交 `6da83ba` 的后端/规格审计；
2. `BUG_REPORT.md`：2026-09-02 Windows + v0.2.1 测试记录；
3. `report-quantcode-desktop.md`：2026-09-03 Desktop 四层 QA；
4. `QuantCode v0.2.1 产品探索报告 — Jerry（可读版）.html`：2026-09-03 Desktop 探索记录。

附件中的后端结论不能直接代表当前状态：当前后端已经迁移到 v5，风险越限、预算、循环和部署的语义均有收窄；UI 代码则位于独立的 `opencode-lens` 仓库，不能只用后端 pytest 代替 UI 验收。

当前核验结果：

| 类别 | 数量 | 说明 |
|---|---:|---|
| 当前确认的真实缺陷/缺口 | 2 + 1 部分 | SSH 实际连通性探测、ReturnsDataset 外部数据源；P-07 生产 timer 启用和候选人工转正仍待外部流程 |
| 当前确认的工程维护债 | 1 | UI 根节点全量重建，主要是性能/焦点风险 |
| 本轮已修复 | 13 | 服务端方案门禁、LLM adapter/权限/配置/跨平台、输入路径边界，以及 UI 目录、指标、算法和加载错误态 |
| 外部环境或旧附件无法确认 | 6 | Windows 锁、Desktop resume、外部 fixture、真实服务等 |
| 不是缺陷或不符合当前 v5 契约 | 7 | 闭包、局部状态、显式 token 错误、旧名称等 |

本轮已经落地的修复包括：L2/L3 任务服务端强制方案阶段；`match_main` 统一 callable/invoke 协议并在失败时返回 `UNAVAILABLE`；能力卡 visibility 服务端过滤；声明 `pyarrow` 并严格阻断坏 YAML 写路径；MCP stdio UTF-8 与 tiktoken 缓存异常降级；PR/实验/期权/PIT 输入路径 containment；QuantCode UI 接入受限的 OpenCode 只读 API（`list_skills`、`ssh_status`、`list_capabilities`、`list_algorithms`、`search_memory`、`session_context`），修复指标精度、共享指标标签、算法列表、动态模块错误反馈，并补充对应回归测试。

## 2. 当前确认的真实缺陷

| ID | 原报告 | 判定 | 证据与影响 | 建议 |
|---|---|---|---|---|
| B-01 | P-10 方案先行可绕过 | **已修复** | 分类结果现在写入 Agent state；L2/L3 在无 phase 时仍按 draft 白名单过滤，入口统一传递 `solution_required`。 | 继续用现有方案状态机；补真实 Desktop resume 回归。 |
| B-02 | `match_main` adapter `.invoke` 异常并乐观降级 | **已修复** | 同时兼容 callable/invoke，结构校验失败或 LLM 异常统一返回 `compatible=false`、`result_status=UNAVAILABLE`；新增 callable 回归。 | 保持不可用时 fail-closed。 |
| B-03 | P-07 自动蒸馏和 strict reuse 不完整 | **部分修复，仍有边界** | Dream consumer 生成候选、`distill_cards_to_memory()` 和 `review_distill_candidate` 已形成受控晋升/拒绝/supersede 审计闭环；生产运行时 strict reuse 已默认开启，`scripts/dream_consume.py --interval` 已提供定时消费入口；候选转正仍需 approver/admin，生产 timer 启用仍待部署确认。 | 启用生产 timer，并继续保留人工转正闸门。 |
| B-04 | AlphaFlow 卡的可见性与黑盒约束冲突 | **已修复** | `visible_cards()` 现在对普通研究组过滤 `visibility=admin`，Admin 保留全量目录；新增 ACL 测试。 | 继续检查 Memory 详情 API 的角色语义。 |
| B-05 | `pyarrow` 未声明 | **已修复** | 已加入项目依赖并同步 lock；parquet backend 可在干净安装中解析。 | CI 保持最小安装验证。 |
| B-06 | 坏 YAML 可能回退到默认生产写路径 | **已修复** | strict 配置读取区分缺失与解析失败，`factor_main` 损坏时 fail-closed。 | 继续将 strict 模式扩展到其他生产写配置。 |
| B-07 | Windows GBK 下 MCP stdout 编码崩溃 | **已修复，Windows 实机待验** | stdio 启动时显式重配置 UTF-8，并增加 GBK subprocess 回归测试。 | 在 Windows 矩阵确认真实 locale 行为。 |
| B-08 | tiktoken BPE 缓存 PermissionError 未兜底 | **已修复，Windows 实机待验** | 捕获 BPE cache `OSError` 并降级近似 token 计数；新增锁异常测试。 | Windows 并发锁定场景实测。 |
| B-09 | factor UI 指标精度丢失 | **已修复** | 极小非零值使用科学计数法；新增 `0.000123` 回归。 | 继续按指标类型优化展示口径。 |
| B-10 | factor-screen 与 panels 指标标签不一致 | **已修复** | 提取共享 `metrics.ts`，两个视图消费同一映射。 | 新指标先更新共享映射。 |
| B-11 | Skill 选择仍硬编码 | **已修复，外部 MCP 连接待验** | UI 通过 OpenCode `/experimental/quantcode/tool` 受限 surface 查询 `list_skills`，按组刷新；失败显示未连接并禁用提交。 | Desktop 启用 QuantCode MCP 后做 E2E。 |
| B-12 | lens-field 动态导入无错误反馈 | **已修复** | 动态导入增加 catch、控制台日志和非阻断可见降级提示。 | 保持降级提示不阻断研究流程。 |
| B-13 | SSH UI 未接真实 connect | **部分修复，仍有外部缺口** | UI 现在只选择本地 Agent/Keychain identity，不再渲染私钥输入；后端 `ssh_status` 只返回配置状态并明确“无网络探测”；真正 SSH 私钥认证/网络探测仍未实现。 | 需要独立安全设计和 SSH gateway，不把只读状态冒充连接成功。 |
| B-14 | settings 中 algorithms 有数据时不渲染 | **已修复** | 有数据时渲染算法 id 与描述，并接入 `list_algorithms` 查询；新增数据分支测试。 | 继续补充来源/版本字段时沿用同一列表。 |
| B-15 | ReturnsDataset 当前无收益源 | **确认，外部依赖缺口** | `tools/market/backing.py` 明确返回 `error: no_source`，当前 staging 没有 A 股收益表。因此真实 panel 评估不能在本地完整闭环。 | 接入 canonical StockDailyBar/ReturnsDataset 前保持 `no_source`，不要用代理收益冒充生产评估。 |
| B-16 | Memory ACL 在 LIMIT 后过滤可能漏结果 | **已修复** | ACL 条件已下推到 FTS SQL 的 WHERE，再执行 over-fetch/LIMIT；新增多组高命中噪声回归，授权组结果不会被其他组挤出。 | 新增 scope 时同步加入 SQL ACL 条件。 |
| B-17 | Windows 导入 `fcntl` 导致证据链启动失败 | **已修复，Windows 实机待验** | `runner/evidence.py` 改为 POSIX `fcntl`、Windows `msvcrt` 锁文件和进程锁回退；无 `fcntl` 回归通过。 | 在 Windows 并发写入矩阵确认文件锁时序。 |
| B-18 | evidence 中等待态/不完整 run 被 Dream 消费 | **已修复** | consumer 仅接受 `output_data.status=completed`，并要求每个 `tool_call_id` 有唯一对应 `tool_result`；瞬时消费失败会回滚增量 seen 集合。 | 继续保留 evidence 完整性校验。 |
| B-19 | merge 审批 evidence 无法生成 DecisionRecord | **已修复** | merge approve/reject 现在写入带 `gate_id`、`decision.action`、`decided_by` 的 HumanGate 环，`build_report()` 可重放审批署名。 | 外部审计消费仍需接入。 |
| B-20 | AgentRunner resume 没有恢复阶段 trace | **已修复** | resume 现在复用 `stream(Command(resume=...))`，恢复后的 tool/update/agent_end 写入 execution_trace、metrics 和 evidence；新增 resume trace 回归。 | 真实 Desktop Activity E2E 仍待验。 |
| B-21 | PR/实验/期权/PIT 路径参数可绕过仓库边界 | **已修复** | 统一 `resolve_input_path()` 做 NUL、`..`、symlink 和仓库 containment 校验；生产拒绝仓库外路径，显式 dev/test 才允许外部 fixture；实验 `exp_id` 采用安全标识符校验。 | 继续在 Windows 矩阵验证盘符和反斜杠输入。 |

## 3. 已由 v5 修复或语义已改变

| 原问题 | 当前结论 | 当前证据 |
|---|---|---|
| 风险越限触发 HumanGate | **已修复** | `route_next_step()` 对风险结果继续执行；Risk CI 输出 `risk_verdict`/报告。高风险 smoke 返回 `fail`，没有 `__interrupt__`；`tests/test_risk_github_e2e.py` 也覆盖无 Gate。 |
| MCP Admin 丢失 SSH fingerprint | **已修复** | `quantcode/mcp_server.py:624-640` 将 `identity`、`ssh_fingerprint`、`actor_id`、`role` 等写入 ctx；Admin roster 测试通过。 |
| QuantEvaluator 断连返回 mock IC/IR | **已修复** | `tools/factor/quant_evaluator_adapter.py:46-71` 断连返回 `UNAVAILABLE`，`output_data=None`，无 mock 指标。 |
| `merge_to_main` 未实现 | **已过时** | 当前 `tools/factor/merge_to_main.py` 有 contract validation、merge 写入和 `merge` HumanGate；测试覆盖 approve/resume。 |
| `check_factor_gate` 缺失 | **已过时/改名** | 当前由 `validate_factor_contract` + acceptance 契约承担，不再保留旧 Gate 名称。 |
| P-09 必须走普通 HumanGate resume | **不是当前 v5 契约** | v5 将部署移到 Admin management plane；`submit_deploy()` 只返回 `STAGING` 并要求 Admin/evidence。普通 Catalog 不注册部署工具。真实生产队列仍未接入，但不是“普通 Agent resume 失败”。 |
| pit-screen 首次范围条静态定位 | **已修复** | `pit-screen.tsx:180` 在有 FCF 时同步调用 `paint(compute())`；UI pit 测试通过。 |
| README/旧测试数量不一致 | **已修复（当前主仓）** | README、TEST_GUIDE 和 v5 审计已更新为当前 `1060 passed, 4 skipped`；附件中的 1021/1026 属旧提交或旧环境结果。 |

## 4. 无法在当前环境确认的事项

| 原问题 | 结论 | 原因 |
|---|---|---|
| Windows tiktoken 真实文件锁时序 | **代码路径确认，真实时序待 Windows 复测** | 本机 macOS 无法复现 Windows 文件锁竞争；已用注入 `PermissionError` 验证当前没有兜底。 |
| Desktop resume 后新增 tool calls 为 0 / MCP `-32001` 超时 | **待 Desktop E2E 复测** | 现有后端 resume 单测与 bridge 逻辑可运行，但附件使用的 UI session、服务端连接和截图不在本仓库测试范围。 |
| `empty_dataset` / `missing_columns` 两个 xfail | **待外部场景包复测** | 附件引用的 `tests/fixtures/factor_scenarios` 不在当前 QuantCode 仓库；当前 panel schema 对空 dates/assets 已 fail-fast，但不是同一场景包。 |
| Activity 显示旧状态、0 steps/0 artifacts | **待 Desktop E2E 复测** | lens 当前有 `thread_cache`、trace 合并和 session reset 逻辑；没有附件截图对应的可重放会话。 |
| Windows 反斜杠 artifact 路径是否导致现有 UI 断言失败 | **风险确认，实机待验** | 后端使用 `str(Path.relative_to(...))`，Windows 会产生反斜杠；当前 macOS 测试不能证明 UI 对路径格式的兼容性。 |
| evidence 连续 `datetime.now()` 相等 | **测试稳定性风险，未确认** | 当前实现使用系统时间；macOS 运行稳定，未在 Windows 时钟分辨率下重复验证。 |
| 真实 AlphaFlow / DataAccess / QuantEvaluator 生产链 | **未验真** | 外部服务、服务账号、队列和生产规格不在当前工作区；当前代码按 `STAGING`/`UNAVAILABLE` 诚实返回。 |

## 5. 不是当前缺陷或仅属于增强项

| 原问题 | 当前结论 |
|---|---|
| pit-screen 的 `params` 闭包会跨调用污染 | 不是缺陷。每次 `PitValuationView()` 都创建新的局部 `params`，并且现有滑条重算测试通过。 |
| Admin `sent` 跨视图泄漏 | 不是当前实现事实。`sent` 是 `AdminConsoleView()` 调用内局部变量，不是模块级共享状态。 |
| memory-query 搜索结果会无限累积 | 不是当前实现事实。每次搜索先 `render()`，而 `render()` 调用 `root.replaceChildren()`；结果不会跨搜索保留。 |
| notifications 必须自行加定时器 | 不成立。`panels.tsx` 使用 Solid signal/memo，trace bridge 更新 `_threadHistory`/`_trace` 时会重新计算 badge；定时器只是可选增强。 |
| GitHub token 缺失时静默失败 | 不成立。`read_pr` 和 Admin GitHub 工具明确返回 `GITHUB_TOKEN` 缺失/`UNAVAILABLE` 错误。 |
| `/solution` 缺少 revise 输入框 | 不是已锁定的 v5 后端缺陷。当前 UI 方案面板是 trace 展示面，反馈通过 `revise_solution`/会话命令提交；若要改为面板内编辑，应作为 UI 产品变更单独定案。 |
| Chroma 未初始化一定是 bug | 不成立。基本面路径允许真实 Chroma 或明确的 fixture backend；未连接时必须显示状态，不应伪造生产数据。 |

## 6. 工程质量与测试证据

### 后端

已执行：

```text
PYTHONPATH=. pytest -q tests/spec_v5 tests/test_solution_workflow.py tests/test_mcp_server.py \
  tests/test_admin_scope.py tests/test_factor_tools.py tests/test_market_tools.py \
  tests/test_config_loading.py tests/test_evidence_chain.py
135 passed, 1 warning

PYTHONPATH=. pytest -q tests/test_risk_github_e2e.py tests/test_admin_scope.py \
  tests/test_factor_tools.py tests/test_solution_workflow.py tests/test_market_tools.py \
  tests/test_config_loading.py tests/test_agent_truncate_node.py
98 passed, 1 warning
```

此前 v5 全量回归：`987 passed, 4 skipped, 1 warning`；本轮最新全量回归：`1060 passed, 4 skipped, 1 warning`。跳过项均为需要显式真实 LLM 凭据的测试。

当前 `.venv/bin/ruff check --exclude build .` 仍报告 `172 errors`，其中 `99` 项可自动修复；这与附件报告的 336 项不同，但说明 Ruff/Black 规范债仍未清零。此次没有批量格式化，避免把无关测试和历史兼容代码大面积改写。

### UI

在 `/Users/hendrixchen/Desktop/私募/opencode-lens/packages/app` 执行：

```text
bun test --preload ./happydom.ts ./src/components/quantcode
114 pass, 0 fail
bun run typecheck
passed
```

UI 单测通过证明组件当前输入下可渲染，不等于真实 MCP、SSH、Desktop session 和生产服务已经接通。附件中的 L4 截图问题仍需用真实 Desktop E2E 单独回归。

## 7. 建议处理顺序

1. 完成 B-03 剩余边界：启用生产 timer，并继续通过 approver/admin 完成候选转正。
2. 为 B-13 设计独立 SSH gateway：私钥不经普通 UI 查询 API，认证、连通性探测和证书轮换均需审计。
3. 接入 ReturnsDataset/QuantEvaluator/DataAccess 前，继续保留 `no_source`/`UNAVAILABLE`，不要用 fixture 通过替代生产验收。
4. 最后用真实 Desktop + Windows 矩阵复测附件中的 resume、Activity、空数据场景和路径/时钟问题。

## 8. 本轮补充核验（2026-09-05）

- 修正 `search_memory` 的 MemoryService 根目录：查询现在读取 `<project>/.quantcode/memory.db`，并通过回归断言阻止 `.quantcode/.quantcode` 路径漂移。
- AgentRunner resume 现在要求 approver/admin 只恢复同组、带有效创建者 `actor_id`/`session_id`/`role` 的 checkpoint；审批人作为不同主体可以正常恢复，创建者上下文仍保留在 checkpoint、metrics 和 evidence 中。
- AgentRunner resume 现在复用 `stream(Command(resume=...))`，恢复阶段的 tool/update/agent_end 会进入同一条 execution trace、metrics 和 evidence 链。
- 子 Agent 继承父 Session Context（actor、role、session、workspace、GitHub scope），并继续继承组、allowlist、预算和方案要求。
- Memory 组 ACL 已在 FTS SQL 的 LIMIT 前执行，避免其他组高命中噪声挤掉本组结果；evidence 链支持 POSIX/Windows 锁回退，并对坏 JSONL 行严格失败。
- P-01 因子载入对缺列、损坏 parquet、全部 PIT/invalid 过滤为空分别返回 `invalid_schema`、`data_read_error`、`empty_dataset`，不再把适配器异常伪装成 Agent 崩溃。
- merge approve/reject evidence 现在写入标准 `gate_id`、`decision.action`、`decided_by`，可由 `build_report()` 重放为 DecisionRecord；Dream consumer 仅消费完整成功 run，临时消费失败会回滚 seen 集合。
- Lens 普通会话删除 `/deploy` 命令；Compose 前缀不再携带可伪造的 group 参数。OpenCode 只读 API 的工具名集合去除重复声明。
- 四份顶层文档新增一致的 F/P 状态台账和外部待验边界；本台账仍不把真实 SSH gateway、ReturnsDataset 或生产部署队列视为完成。

本轮已修改后端与外部 `opencode-lens` UI，并为已修复项补充回归测试；未把外部服务依赖（SSH gateway、ReturnsDataset、生产队列）伪装成完成。

## 9. 本轮追加核验（2026-09-05）

| 候选问题 | 判定 | 修复与证据 |
|---|---|---|
| Blackboard 绑定组可被显式 `requester_group` 覆盖 | **已修复** | `BlackboardService` 现在拒绝与实例绑定组不同的 per-call 身份；写、读和空结果路径均有回归测试。 |
| `stream(resume_decision=...)` / `run(resume=True)` 可绕过恢复边界 | **已修复** | 所有 AgentRunner checkpoint 恢复统一经过组、HumanGate 和 Session Context 校验；带角色的恢复只允许 approver/admin，待处理 Gate 必须显式调用 `resume(decision=...)`。 |
| FactorPanel / ReturnsDataset 接受嵌套坏矩阵 | **已修复** | list/tuple 行现在要求列数一致；ragged rows 在 Pydantic 构造阶段失败，不再延迟到 `to_records()`。 |
| `calc_greeks` 忽略合约数量或静默回退坏曲面 | **已修复** | Portfolio Greeks 按腿数量缩放；显式曲面路径不存在、损坏或契约不符时返回错误，不使用默认 Greeks 冒充曲面结果。 |
| Typst 填充编译失败仍生成模板 PDF | **已修复** | 删除模板 fallback，编译失败只返回 `pdf_filled=false`；清理旧 PDF，避免 stale artifact 被报告为成功。 |
| fundamental flow 默认强制 fixture | **已修复** | 未显式传 `force_fixture` 时遵循 Chroma 优先；fixture 仅由测试/离线调用方显式启用。 |
| 期权标的 substring 过滤及腿输入 NaN/范围不足 | **已修复** | 标的按精确代码或期货合约后缀匹配；价格、数量、到期偏移、标的序列做 finite/range 校验。 |
| 实验 artifact 依赖当前 cwd | **已修复** | 归档与排行榜固定写入项目根 `artifacts/experiments`，对外返回仓库相对 artifact 引用。 |
| Agent 正常最终回答状态、工具错误链不完整 | **已修复** | 无 tool-call 的最终 AIMessage 返回 `completed`；run/stream 均回写 status，工具失败内容累计到 `errors`。 |
| Admin GitHub repo/package 查询权限描述不一致 | **不是实现缺陷** | 当前 v5 明确定义 org/package 元数据为全员只读发现面；GitHub token 仍按用户 ctx 或 Admin 中心 token 规则解析，缺失时返回 `UNAVAILABLE`。 |

追加回归后后端全量为 `1060 passed, 4 skipped, 1 warning`。仍未验证真实 Windows 文件锁、Desktop E2E、SSH gateway、canonical ReturnsDataset 和生产部署队列。

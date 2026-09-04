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
| 当前确认的真实缺陷/缺口 | 3 | P-07 自动晋升、SSH 实际连通性探测、ReturnsDataset 外部数据源 |
| 当前确认的工程维护债 | 1 | UI 根节点全量重建，主要是性能/焦点风险 |
| 本轮已修复 | 12 | 服务端方案门禁、LLM adapter/权限/配置/跨平台，以及 UI 目录、指标、算法和加载错误态 |
| 外部环境或旧附件无法确认 | 6 | Windows 锁、Desktop resume、外部 fixture、真实服务等 |
| 不是缺陷或不符合当前 v5 契约 | 7 | 闭包、局部状态、显式 token 错误、旧名称等 |

本轮已经落地的修复包括：L2/L3 任务服务端强制方案阶段；`match_main` 统一 callable/invoke 协议并在失败时返回 `UNAVAILABLE`；能力卡 visibility 服务端过滤；声明 `pyarrow` 并严格阻断坏 YAML 写路径；MCP stdio UTF-8 与 tiktoken 缓存异常降级；QuantCode UI 接入受限的 OpenCode 只读 API（仅 `list_skills`、`ssh_status`、`list_capabilities`、`list_algorithms`），修复指标精度、共享指标标签、算法列表、动态模块错误反馈，并补充对应回归测试。

## 2. 当前确认的真实缺陷

| ID | 原报告 | 判定 | 证据与影响 | 建议 |
|---|---|---|---|---|
| B-01 | P-10 方案先行可绕过 | **已修复** | 分类结果现在写入 Agent state；L2/L3 在无 phase 时仍按 draft 白名单过滤，入口统一传递 `solution_required`。 | 继续用现有方案状态机；补真实 Desktop resume 回归。 |
| B-02 | `match_main` adapter `.invoke` 异常并乐观降级 | **已修复** | 同时兼容 callable/invoke，结构校验失败或 LLM 异常统一返回 `compatible=false`、`result_status=UNAVAILABLE`；新增 callable 回归。 | 保持不可用时 fail-closed。 |
| B-03 | P-07 自动蒸馏和 strict reuse 不完整 | **仍是产品缺口** | Dream consumer 已能从 evidence 增量生成候选，但能力卡到 Memory 仍需显式 `distill_cards_to_memory()`，`strict_reuse` 仍主要是 prompt 纪律。 | 增加受控 job、晋升审计和服务端复用约束。 |
| B-04 | AlphaFlow 卡的可见性与黑盒约束冲突 | **已修复** | `visible_cards()` 现在对普通研究组过滤 `visibility=admin`，Admin 保留全量目录；新增 ACL 测试。 | 继续检查 Memory 详情 API 的角色语义。 |
| B-05 | `pyarrow` 未声明 | **已修复** | 已加入项目依赖并同步 lock；parquet backend 可在干净安装中解析。 | CI 保持最小安装验证。 |
| B-06 | 坏 YAML 可能回退到默认生产写路径 | **已修复** | strict 配置读取区分缺失与解析失败，`factor_main` 损坏时 fail-closed。 | 继续将 strict 模式扩展到其他生产写配置。 |
| B-07 | Windows GBK 下 MCP stdout 编码崩溃 | **已修复，Windows 实机待验** | stdio 启动时显式重配置 UTF-8，并增加 GBK subprocess 回归测试。 | 在 Windows 矩阵确认真实 locale 行为。 |
| B-08 | tiktoken BPE 缓存 PermissionError 未兜底 | **已修复，Windows 实机待验** | 捕获 BPE cache `OSError` 并降级近似 token 计数；新增锁异常测试。 | Windows 并发锁定场景实测。 |
| B-09 | factor UI 指标精度丢失 | **已修复** | 极小非零值使用科学计数法；新增 `0.000123` 回归。 | 继续按指标类型优化展示口径。 |
| B-10 | factor-screen 与 panels 指标标签不一致 | **已修复** | 提取共享 `metrics.ts`，两个视图消费同一映射。 | 新指标先更新共享映射。 |
| B-11 | Skill 选择仍硬编码 | **已修复，外部 MCP 连接待验** | UI 通过 OpenCode `/experimental/quantcode/tool` 受限 surface 查询 `list_skills`，按组刷新；失败显示未连接并禁用提交。 | Desktop 启用 QuantCode MCP 后做 E2E。 |
| B-12 | lens-field 动态导入无错误反馈 | **已修复** | 动态导入增加 catch、控制台日志和非阻断可见降级提示。 | 保持降级提示不阻断研究流程。 |
| B-13 | SSH UI 未接真实 connect | **部分修复，仍有外部缺口** | UI 已注入后端 `ssh_status` 查询并显示明确的“仅状态、无连通性探测”日志；真正 SSH 私钥认证/网络探测仍未实现。 | 需要独立安全设计和 SSH gateway，不把只读状态冒充连接成功。 |
| B-14 | settings 中 algorithms 有数据时不渲染 | **已修复** | 有数据时渲染算法 id 与描述，并接入 `list_algorithms` 查询；新增数据分支测试。 | 继续补充来源/版本字段时沿用同一列表。 |
| B-15 | ReturnsDataset 当前无收益源 | **确认，外部依赖缺口** | `tools/market/backing.py:430-457` 明确返回 `error: no_source`，当前 staging 没有 A 股收益表。因此真实 panel 评估不能在本地完整闭环。 | 接入 canonical StockDailyBar/ReturnsDataset 前保持 `no_source`，不要用代理收益冒充生产评估。 |

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
| README/旧测试数量不一致 | **已修复（当前主仓）** | README、TEST_GUIDE 和 v5 审计已更新为当前 `987 passed, 4 skipped`；附件中的 1021/1026 属旧提交或旧环境结果。 |

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

此前 v5 全量回归：`987 passed, 4 skipped, 1 warning`；本轮最新全量回归：`992 passed, 4 skipped, 1 warning`。跳过项均为需要显式真实 LLM 凭据的测试。

当前 `.venv/bin/ruff check --exclude build .` 仍报告 `172 errors`，其中 `99` 项可自动修复；这与附件报告的 336 项不同，但说明 Ruff/Black 规范债仍未清零。此次没有批量格式化，避免把无关测试和历史兼容代码大面积改写。

### UI

在 `/Users/hendrixchen/Desktop/私募/opencode-lens/packages/app` 执行：

```text
bun test --preload ./happydom.ts ./src/components/quantcode
105 pass, 0 fail
bun run typecheck
passed
```

UI 单测通过证明组件当前输入下可渲染，不等于真实 MCP、SSH、Desktop session 和生产服务已经接通。附件中的 L4 截图问题仍需用真实 Desktop E2E 单独回归。

## 7. 建议处理顺序

1. 完成 B-03：把能力卡蒸馏、候选晋升和 strict reuse 从显式 API/prompt 纪律升级为受控服务端流程。
2. 为 B-13 设计独立 SSH gateway：私钥不经普通 UI 查询 API，认证、连通性探测和证书轮换均需审计。
3. 接入 ReturnsDataset/QuantEvaluator/DataAccess 前，继续保留 `no_source`/`UNAVAILABLE`，不要用 fixture 通过替代生产验收。
4. 最后用真实 Desktop + Windows 矩阵复测附件中的 resume、Activity、空数据场景和路径/时钟问题。

本轮已修改后端与外部 `opencode-lens` UI，并为已修复项补充回归测试；未把外部服务依赖（SSH gateway、ReturnsDataset、生产队列）伪装成完成。

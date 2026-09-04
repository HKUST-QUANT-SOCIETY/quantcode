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
| 当前确认的真实缺陷/缺口 | 15 | 9 个后端/契约/外部服务接入问题，6 个 UI/集成问题 |
| 当前确认的工程维护债 | 1 | UI 根节点全量重建，主要是性能/焦点风险 |
| 已由 v5 修复或已改为新语义 | 8 | 旧 Risk Gate、Admin fingerprint、factor mock evaluator 等 |
| 外部环境或旧附件无法确认 | 6 | Windows 锁、Desktop resume、外部 fixture、真实服务等 |
| 不是缺陷或不符合当前 v5 契约 | 7 | 闭包、局部状态、显式 token 错误、旧名称等 |

## 2. 当前确认的真实缺陷

| ID | 原报告 | 判定 | 证据与影响 | 建议 |
|---|---|---|---|---|
| B-01 | P-10 方案先行可绕过 | **确认，P0/P1** | `tool_allowed_in_phase("write_blackboard", None)` 返回 `True`（`runner/solution_workflow.py:114-121`）。`classify_task()` 能把多文件任务判为 L2/`solution_required=True`，但 `run_agent` 只记录分类，不自动创建 draft；因此 L2/L3 仍可能在 `phase=None` 直接进入写工具。 | 在服务端入口按 classification 强制创建/绑定 `SolutionDoc`；保留 L0/L1 直接执行。 |
| B-02 | `match_main` adapter `.invoke` 异常并乐观降级 | **确认，P1** | `DeepSeekAdapter` 实现的是 `__call__`（`runner/llm_provider.py:96-116`），而 `tools/factor/match_main.py:143-148` 调用 `llm.invoke(messages)`。当前可稳定复现 `AttributeError`，随后 `match_main.py:174-180` 返回 `compatible=True`、空字段。 | 统一 adapter 调用协议；异常时返回明确失败/不可用状态，禁止 `compatible=True`。 |
| B-03 | P-07 自动蒸馏和 strict reuse 不完整 | **确认，P1/产品缺口** | `distill_cards_to_memory()` 存在，但当前代码搜索不到生产启动/调研管线调用；`strict_reuse` 默认为 `false`，`runner/distill/inject.py:82-85` 只注入提示词。能力目录仍由 `configs/capabilities.yaml` 静态加载。 | 明确 P-07 当前为静态目录 + 显式蒸馏 API；若要求自动管线，增加受控 job 和晋升审计，不要只靠 prompt。 |
| B-04 | AlphaFlow 卡的可见性与黑盒约束冲突 | **确认，P1** | `configs/capabilities.yaml` 将 `alpha-flow` 标为 `visibility: admin`，但 `visible_cards()` 对任意已认证研究组直接返回全部卡；实测 factor 组仍能看到 admin-only 卡及 `/deploy` 摘要。当前 `list_capabilities` 不返回完整 `api_surface`，因此“完整内部 API 已向所有组泄漏”尚未成立，但 `visibility` 字段确实没有被执行。 | 对 `visibility` 做服务端过滤；普通组最多看到脱敏的部署候选能力，不返回 AlphaFlow 内部模块。 |
| B-05 | `pyarrow` 未声明 | **确认，P1** | `tools/market/backing.py:63-73` 运行时导入 `pyarrow.parquet`，但 `pyproject.toml:15-23` 没有核心或 dev 依赖声明。当前环境因已安装依赖而通过，干净安装不能保证。 | 将 `pyarrow` 放入对应 extras，或把 parquet backend 单独拆成明确可选 extra，并在安装/启动检查中给出状态。 |
| B-06 | 坏 YAML 可能回退到默认生产写路径 | **确认，P1** | `runner/config_loader.py:32-65` 对坏 YAML 返回 `{}`；`tools/factor/merge_to_main.py:38-52` 随后使用 `.quantcode/mainline/factors.json` 默认路径。实测坏 `factor_main.yaml` 后仍解析到默认相对路径。 | 对生产写配置区分“缺失可默认”和“解析失败必须阻断”；至少 `factor_main` 解析失败应 fail-closed。 |
| B-07 | Windows GBK 下 MCP stdout 编码崩溃 | **确认，P1，跨平台** | 强制 `PYTHONIOENCODING=gbk` 运行 `quantcode.mcp_server`，返回含 Unicode 文案时在 `quantcode/mcp_server.py:701-730` 复现 `UnicodeEncodeError`。 | MCP stdio 进程统一使用 UTF-8 binary/text wrapper，或启动时显式重配置 stdout 编码；增加 Windows 子进程测试。 |
| B-08 | tiktoken BPE 缓存 PermissionError 未兜底 | **确认，P1，跨平台** | `runner/agent_nodes.py:965-986` 只捕获 `KeyError/ValueError`；注入 `PermissionError('locked cache')` 可直接向上抛出。Windows 并发锁定缓存时，truncate/checkpoint 相关路径会失败。 | 捕获缓存读取的 `OSError/PermissionError` 后退回近似计数；同时允许设置独立 `TIKTOKEN_CACHE_DIR`。 |
| B-09 | factor UI 指标精度丢失 | **确认，P2，UI** | `opencode-lens/.../metric-cards.tsx:9-12` 对非 IC/IR/Sharpe 指标只保留三位小数，`0.000123` 显示为 `0`。 | 使用有效数字/科学计数法下限；补充小数极小值测试。 |
| B-10 | factor-screen 与 panels 指标标签不一致 | **确认，P2，UI** | `factor-screen.tsx:56-65` 与 `panels.tsx:264-272` 各自维护 `METRIC_LABELS`，字段集合不一致（`ic_std/t_stat` 与 `ic/annualized_return` 分歧）。 | 提取共享指标字段/标签模块，两个视图只消费同一映射。 |
| B-11 | Skill 选择仍硬编码 | **确认，P1，UI/集成** | `opencode-lens/.../panels.tsx:161-166` 固定 4 个 Skill；没有从后端 `list_skills` 获取并按会话组刷新。当前 v5 规格要求 Skill 来自维护员发布目录。 | 接入真实 `list_skills` 通道；加载失败显示未连接，不静默使用过期列表。 |
| B-12 | lens-field 动态导入无错误反馈 | **确认，P2，UI** | `panels.tsx:733-755` 只有 `import(...).then(...)`，没有 `.catch()`；模块加载失败时粒子场静默消失。 | 添加可见的非阻断降级状态和日志，避免把加载失败伪装成正常空白。 |
| B-13 | SSH UI 未接真实 connect | **确认，P1，外部集成** | `ssh-login.tsx:31-34` 的默认 `stubSshConnect` 永远返回 `unavailable`；`panels.tsx:532-537` 没有注入后端连接实现。后端 `ssh_status` 已存在，但当前 SDK 面没有直接 tool invoke。 | 为 lens 提供只读身份/连接状态 API 或受控 fetcher；在接线前明确显示“身份接线未完成”，并联动禁用未认证任务提交。 |
| B-14 | settings 中 algorithms 有数据时不渲染 | **确认，P2，UI** | `settings-supplier.tsx:40-53` 只处理空数组；`algorithms.length > 0` 时没有生成列表。现有测试只覆盖空态。 | 增加有数据分支和对应测试，显示 id、描述、来源/状态。 |
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

此前 v5 全量回归：`987 passed, 4 skipped, 1 warning`。跳过项均为需要显式真实 LLM 凭据的测试。

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

1. 先修 B-01/B-02/B-04/B-06：它们会造成权限绕过、错误结论或错误生产写路径。
2. 接着修 B-05/B-07/B-08：保证干净安装和 Windows/并发环境的基础可靠性。
3. 在 `opencode-lens` 修 B-09~B-14，并补真实 `list_skills`、SSH 状态和任务提交联动。
4. 接入 ReturnsDataset/QuantEvaluator/DataAccess 前，继续保留 `no_source`/`UNAVAILABLE`，不要用 fixture 通过替代生产验收。
5. 最后用真实 Desktop + Windows 矩阵复测附件中的 resume、Activity、空数据场景和路径/时钟问题。

本记录没有修改外部 `opencode-lens` 仓库，也没有把上述缺陷自动修复；本次请求只完成整理和真实性核验。

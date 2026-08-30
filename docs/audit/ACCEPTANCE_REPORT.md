# QUANTcode 验收报告（ACCEPTANCE REPORT）

- 日期：2026-08-30
- 验收人：验收代理（只读 + 跑测试，未做任何代码修改 / git 写操作）
- P 仓（Python 平台）：`/Users/hendrixchen/Desktop/私募/QUANTcode`
- F 仓（桌面端 fork）：`/Users/hendrixchen/Desktop/私募/opencode`，分支 `feat/quantcode-day5-ui`
- ruff 工具版本：项目锁文件范围 `>=0.4`；实测 0.4.10 与 0.15.20 结果一致（33 errors）；最新 0.16.5 规则集更宽（185 errors），两版均记录供对照。
- P 仓工作树状态：约 104 个未提交改动（用户指示暂不 commit，全部改动在工作树中）。

---

## 1. 测试矩阵（P / F 两列 pass 数）

| 仓库 | 项目 | 结果 | 判定 |
|---|---|---|---|
| P | `python -m pytest tests/ -q --tb=short` | **702 passed, 5 skipped, 0 failed**（9.15s，预期约 702/5） | PASS |
| P | `ruff check runner/ tools/ flows/ quantcode/ scripts/replay.py --statistics` | **33 errors**（ruff 0.4.10 与 0.15.20 一致；128→161→131 基线趋势继续下降）。ruff 0.16.5 宽规则集下为 185 errors | 记录性指标，PASS |
| F | `packages/app` `bun run typecheck` | **0 错误**（tsgo -b，exit 0） | PASS |
| F | `packages/app` `bun run test:unit --only-failures` | **490 pass, 0 fail**（76 文件，2210 expect，905ms） | PASS |
| F | `packages/session-ui` `bun run typecheck` | **0 错误**（tsgo --noEmit，exit 0） | PASS |
| F | `packages/opencode` `bun run typecheck` | **0 错误**（tsgo --noEmit，exit 0） | PASS |

## 2. 冒烟结果表（P 仓，只读 / 未装包）

| 冒烟项 | 观察结果 | 判定 |
|---|---|---|
| `python -m quantcode.identity list` | 输出 `(no bindings)`，exit 0 | PASS |
| `PYTHONPATH=. python scripts/demo_routing_guards.py \| tail -3` | 正常输出三条路由判定：`[normal] route=finish reason=task_completed`、`[high_risk] route=continue reason=normal`、`[loop] route=abort_loop reason=loop_detected` | PASS |
| `PYTHONPATH=. python scripts/replay.py list \| head` | 真实 checkpoints.db 列表正常输出（`/Users/hendrixchen/Desktop/私募/QUANTcode/.quantcode/checkpoints.db`，含 t-stream、tid-lowic、factor-factor_null_mem 等条目），exit 0 | PASS |
| `FLOW_REGISTRY` 六流断言 | 见下方说明 | PASS（带备注） |
| `from runner.blackboard_keys import PROJECT_SESSION_ID; import runner.metrics, runner.judge, runner.server_ssh, quantcode.identity` | 输出 `modules ok` | PASS |

**FLOW_REGISTRY 备注（重要）**：直接 `import runner.compose_executor` 时 `FLOW_REGISTRY` 仅含 4 键（fundamental/model/options/strategy，由 compose_executor.py:365-368 底部 `import flows.*` 触发注册）。**factor:autoeval 与 risk:gate 不在任何主路径 import 时自动注册**：
- risk:gate 需显式调用 `runner.risk_agent.register_risk_gate_flow()`（runner/risk_agent.py:246）；
- factor:autoeval 仅由 `scripts/demo_factor_autoeval.py` 等脚本在运行时临时注册并注册后即注销（compose_executor.py:363 注释亦确认「factor:autoeval 沿用 demo 脚本注册方式」）。

显式装配两个入口后，六组齐全验证通过：
`['factor:factor:autoeval', 'fundamental:fundamental:research', 'model:model:submit', 'options:options:compose', 'risk:risk:gate', 'strategy:strategy:compose']` → **六键 PASS**。

风险：若生产调用方只 import compose_executor 而未分别触发 risk/factor 注册，按 group 查询 factor/risk 会走 `FLOW_REGISTRY.get` 落空并报「已注册：[4键]」（compose_executor.py:226-230）。属于装配约定而非缺陷，但建议在文档或 README 强化说明。

## 3. 关键修复抽查表（grep 验证，每项 PASS/FAIL + 证据行）

| # | 抽查项 | 证据 | 判定 |
|---|---|---|---|
| 1 | `tools/github_comments.py` 含 `_REPO_RE` | `tools/github_comments.py:14: _REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")`；`:31` 用于 fullmatch 校验 | PASS |
| 2 | `runner/routing/session_review.py` 的 `_rewrite_session_records` 无 `path: Path` 参数化 | `runner/routing/session_review.py:82: def _rewrite_session_records(thread_id: str, updated: list[dict[str, Any]], path: Any) -> None`；`:133` 唯一调用处固定传 `RLHF_PATH`。注意签名仍有 `path: Any` 形参（非 `Path` 类型参数化），行为上已收敛到常量 RLHF_PATH | PASS（备注：保留 `path: Any` 形参，非 `path: Path`） |
| 3 | `runner/blackboard_keys.py` 存在且 `agent_mcp_tool.py` 引用它 | 文件存在；`runner/agent_mcp_tool.py:202`（P0-2 修复说明注释）、`:211: from runner.blackboard_keys import KEY_PENDING_RISK_REVIEWS, PROJECT_SESSION_ID` | PASS |
| 4 | `tools/factor/` 无 `*_stub.py` | `ls tools/factor/ | grep -i stub` 为空 | PASS |
| 5 | `flows/` 含 factor_autoeval / model_submit / strategy_compose / options_compose / fundamental_research 五文件，且无 `risk_gate.py` | `ls flows/`：`__init__.py, factor_autoeval.py, fundamental_research.py, model_submit.py, options_compose.py, strategy_compose.py`；`flows/risk_gate.py` 不存在（`ls: No such file or directory`） | PASS |
| 6 | `.github/workflows/risk-gate.yml` 无 "formal" | `grep -in "formal" .github/workflows/risk-gate.yml` 为空 | PASS |
| 7 | README.md 无 "IR > 1.5" | grep 为空 | PASS |
| 8 | README.md 无 opencode.local.jsonc 配置指引 | grep 为空 | PASS |
| 9 | `config.json` 不存在，`config.example.json` 存在 | `ls config.json` → No such file；`config.example.json` 存在 | PASS |
| 10 | F 侧无 `dialog-connect-provider.tsx` / `dialog-select-provider.tsx` / `dialog-select-model-unpaid.tsx` | `find packages/app/src -name ...` 三个文件均不存在（git status 亦显示 `D packages/app/src/components/dialog-connect-provider.tsx`） | PASS |
| 11 | `panels.tsx` 含 monitor Tab 与 Approve/reject 逻辑 | `packages/app/src/components/quantcode/panels.tsx:785: type TabId = "compose" \| "tasks" \| "gate" \| "schema" \| "memory" \| "resume" \| "monitor"`；`:876` gate Match 分支；`:888` monitor Match 分支；`:97: type GateDecision = "approve" \| "reject"`；`:510: onClick={() => void sendDecision("reject")}`；gate reject/approve 按钮与 `quantcode.gate.reject` 文案齐全（注意：panels.tsx 实际路径为 `packages/app/src/components/quantcode/panels.tsx`，非 `components/` 直下） | PASS |
| 12 | `use-providers.ts` 无 `popularProviders` | `grep -rn popularProviders packages/app/src/` 为空 | PASS |

**抽查汇总：12/12 PASS，0 FAIL。**

## 4. 遗留风险（未处理项，仅记录）

| # | 风险 | 说明 |
|---|---|---|
| 1 | Mimosa L3 三个 medium 未处理 | read_pr / risk_tools 跨文件污点告警（taint cross-file warnings）未修复或豁免 |
| 2 | 旧 `opencode-checkpoints.db` 不迁移 | P 仓同时存在 `.quantcode/opencode-checkpoints.db`（旧）与 `.quantcode/checkpoints.db`（当前使用）；replay.py 只读新版，旧库无迁移逻辑，历史数据留在原地 |
| 3 | GITHUB_API_URL 已写死官方 | `tools/github_comments.py:35: api_base = "https://api.github.com"`，不再读 `GITHUB_API_URL` 环境变量；文件头注释（:28）明示 GHE 私有部署需恢复并配白名单 |
| 4 | proxy-models 14 个 pre-existing test failures 未定位 | 仓库内未找到名为 `proxy-models` 的包/目录（packages/ 下 30 个包无匹配），该失败项来自task预声明，本次验收未能定位其载体与复现路径，保持未定位状态 |
| 5 | FLOW_REGISTRY factor/risk 非自动注册 | 见第 2 节备注：仅 4 条流 import 即注册，factor:autoeval / risk:gate 需显式装配，调用方需知晓 |
| 6 | ruff 0.16.5 宽规则集 185 errors | 若未来升级 ruff 到 0.15+（默认规则集变宽），错误数将从 33 跳升，需另行治理或固定版本 |

## 5. Commit 待办

- 用户指示：**暂不 commit**。P 仓工作树含全部改动（约 104 个路径，含新增/修改/删除），F 仓工作树同样含全部改动（含 `D packages/app/src/components/dialog-connect-provider.tsx` 等删除项）。
- 后续 commit 时建议注意：
  - `config.json`、`.quantcode/*.db`、`data/` 等本地产物不入库；
  - F 仓 `bun.lock` / `package.json` 变更需与依赖裁剪一致；
  - ruff 建议在 CI 固定版本（如 `ruff>=0.4,<0.5` 或锁定 0.15.x），避免 0.16.5 宽规则集导致错误数跳变。

## 6. 总判定

- P 仓：702 passed / 5 skipped / 0 failed；ruff 33 errors（项目规则集，趋势自 161→131 继续下降）。
- F 仓：app typecheck 0 错误、490 pass / 0 fail；session-ui、opencode typecheck 均 0 错误。
- 冒烟：5/5 通过（FLOW_REGISTRY 六组需显式装配 risk/factor 后齐全，已备注）。
- 修复抽查：12/12 PASS。
- **验收结论：PASS（含第 4 节遗留风险，均不阻塞本次验收）。**
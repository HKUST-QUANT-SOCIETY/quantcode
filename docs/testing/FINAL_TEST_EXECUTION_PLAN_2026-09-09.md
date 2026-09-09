# 集中测试执行计划

日期：2026-09-09。状态：**NOT_RUN**。本文只核对当前源码、package scripts 与测试配置，未执行安装依赖、用例收集、测试、类型检查或构建，也未启动或重启任何服务。

用户要求的顺序保持为：**全部实现 → 桌面 UI 核验通过 → 集中用例测试 → 对照全部要求完成验收**。本计划不以脚本存在、测试源码存在或先前少量检查作为通过证据。当前 UI 工具审批超时属于 UI 核验阻断，不能作为绕过 UI 前置条件的理由。

## 1. 执行前提与隔离

1. 在 [桌面 UI 核验记录](DESKTOP_UI_REVIEW_2026-09-08.md) 明确记录当前源码版本对应的通过范围，不能把旧端口、旧构建或某次登录成功作为全部桌面交互通过。本文不硬编码正在使用的预览端口。
2. 使用独立测试系统用户、容器或已核验的隔离环境，以及包含**当前全部已跟踪和未跟踪源码改动**的测试副本。不能只复制 HEAD 而遗漏本轮新增模块。保留 git 来源及补丁摘要，不拷入真实 `.quantcode`、私有环境文件、正式 roster、个人 `config.json`、SSH/GitHub/模型凭据、用户数据库或浏览器登录资料。
3. 测试副本可以被测试写入；当前用户工作树、运行中应用及正式研究目录不作为测试临时目录。不要通过重启现有服务器来获得测试环境。需要外部服务的用例只能使用确认属于本轮测试的隔离服务。
4. Python 要求 3.12+；Bun 锁定版本来自 `frontend/package.json` 的 `bun@1.3.14`。Node 构建版本参照现有桌面 workflow 的 Node 24，桌面 Electron 版本来自 `packages/desktop/package.json`，不是根工作区另一份 Electron 的版本。
5. `tests/conftest.py` 只自动清除部分身份变量并替换默认 roster；它不是完整秘密隔离。Core preload 只配置内存数据库和模型 fixture，未隔离整个用户目录。Opencode preload 隔离 XDG/测试 home 并清理多种 provider key，但仍不能替代专用无真实凭据的测试环境。任何测试不应自动读取开发者现有 SSH agent、模型 key、GitHub token 或私有配置。

以下命令使用 Bash，路径需填为本轮的真实隔离位置。只展示命令，不在此文档编写新的测试调度器：

```bash
QC_TEST_ROOT=/absolute/isolated/QUANTcode
QC_RUN_DIR=/absolute/isolated/test-results/2026-09-09-run-01
QC_PYTHON=/absolute/isolated/QUANTcode/.venv/bin/python
export QC_TEST_ROOT QC_RUN_DIR QC_PYTHON
mkdir -p "$QC_RUN_DIR"
```

这些变量本身不提供隔离。执行 shell 必须来自上述专用测试用户/容器，不继承开发者的模型、SSH、GitHub、gateway、数据库或 `QUANTCODE_HOST_ENV_FILE` 配置。不修改 `HOME`、`CODEX_HOME` 等用户目录变量来假装完成隔离。使用 `QUANTCODE_HOST_ENV_FILE=` 只能阻止开发启动器加载文件，不能清除已经继承的秘密。

隔离副本依赖未安装时，先按原锁文件准备，不升级版本：

```bash
cd "$QC_TEST_ROOT"
uv sync --frozen --extra dev --extra roster --extra ssh
cd "$QC_TEST_ROOT/frontend"
bun install --frozen-lockfile
```

如果宿主没有 `uv`，先解决该依赖或使用已经与 `uv.lock` 对齐的隔离 Python 环境；不能用未锁定的安装掩盖差异。干净的 frontend 安装同时覆盖 Effect 等 `patchedDependencies` 补丁重放。缺包、补丁失败、native addon 缺失均记录为失败/环境阻断，不能通过 `importorskip` 将必需依赖的缺失算作通过。

现有 `scripts/ci/run_quantcode_review_tests.sh` 是特定 Linux CI 机器的隔离入口，绑定 `/srv/quant` 环境、旧源码版本的依赖与模型缓存及特定 tmpfs；不能直接搬到本机或修改其固定来源来凑通过。仅在该运行环境和当前源码覆盖已经重新核实时复用。

## 2. 日志与退出状态

每条命令保存：工作目录、完整命令（不含秘密值）、源码/锁文件摘要、开始结束时间、退出码、通过/失败/跳过数量和日志路径。每轮使用新的结果目录，不覆盖首次失败证据。

示例：

```bash
set -o pipefail
cd "$QC_TEST_ROOT/frontend/packages/core"
bun run test 2>&1 | tee "$QC_RUN_DIR/core-test.log"
printf '%s\n' "${PIPESTATUS[0]}" > "$QC_RUN_DIR/core-test.exit"
```

流水线必须保存测试进程的退出码，不能使用 `tee` 的成功码。日志中出现 `passed` 不代表命令成功；超时、崩溃、收集错误、unhandled rejection、后台测试进程未结束或日志截断都不能记 PASS。保留每次失败，再记录修复后的重验；不能只保留最后一行绿色摘要。

命令运行前可以记录 `git rev-parse HEAD`、源码 diff 和锁文件摘要；不得执行 `env` 全量打印、`set -x` 或将私有请求正文写入日志。真实服务验证仅保存脱敏结果和可核对的调用/事件 ID。

## 3. Python：保留 1300 个旧 nodeid 并核对当前全集

基线是 [PREVIOUS_PYTEST_CASES_2026-09-08.json](PREVIOUS_PYTEST_CASES_2026-09-08.json)，保留了原 pytest cache 的 **1300 个 nodeid**。它不是当前收集结果或通过报告，不能被本次缓存覆盖。当前正式入口由根 `pyproject.toml` 的 `testpaths = ["tests"]` 确定；全量命令为 `python -m pytest`，不是 `scripts/test_mcp_groups.py` 等单项诊断。

先在隔离副本收集全部用例，必须收集成功才能做差集：

```bash
cd "$QC_TEST_ROOT"
"$QC_PYTHON" -m pytest --collect-only -q --color=no -p no:cacheprovider tests \
  > "$QC_RUN_DIR/python-collect.log" 2>&1
printf '%s\n' "$?" > "$QC_RUN_DIR/python-collect.exit"
```

确认 `python-collect.exit` 是 `0`。下面只比较原生 pytest 输出与已保存的 JSON 清单，不注册插件或另造测试框架：

```bash
"$QC_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["QC_TEST_ROOT"])
run = Path(os.environ["QC_RUN_DIR"])
if (run / "python-collect.exit").read_text().strip() != "0":
    raise SystemExit("Collection failed; no completeness claim is allowed")
previous = json.loads((root / "docs/testing/PREVIOUS_PYTEST_CASES_2026-09-08.json").read_text())
current = sorted({line.strip() for line in (run / "python-collect.log").read_text().splitlines()
                  if line.startswith("tests/") and "::" in line})
if not current:
    raise SystemExit("No nodeids parsed; inspect the pytest collection format")
missing = sorted(set(previous) - set(current))
added = sorted(set(current) - set(previous))
(run / "python-current-nodeids.json").write_text(json.dumps(current, indent=2) + "\n")
(run / "python-nodeid-diff.json").write_text(json.dumps({
    "previous_count": len(previous), "current_count": len(current),
    "missing": missing, "added": added,
}, indent=2) + "\n")
print(f"previous={len(previous)} current={len(current)} missing={len(missing)} added={len(added)}")
if missing:
    raise SystemExit("Prior cases are missing; reconcile every nodeid before claiming full coverage")
PY
```

任何缺失 nodeid 都要定位：误删、文件移动、重命名、参数化 ID 改动或收集条件变化。真实重命名需记录旧 ID → 新 ID 与相同验收意图的证据；不能修改旧基线、降低预期数量或以新测试数量更多抵消遗漏。

运行当前全集：

```bash
cd "$QC_TEST_ROOT"
"$QC_PYTHON" -m pytest -q tests -rA --color=no \
  --basetemp "$QC_RUN_DIR/pytest-tmp" \
  --junitxml "$QC_RUN_DIR/python-junit.xml" \
  > "$QC_RUN_DIR/python-full.log" 2>&1
printf '%s\n' "$?" > "$QC_RUN_DIR/python-full.exit"
"$QC_PYTHON" -m ruff check . > "$QC_RUN_DIR/python-ruff.log" 2>&1
printf '%s\n' "$?" > "$QC_RUN_DIR/python-ruff.exit"
```

`--basetemp` 指向本轮新目录，pytest 会管理/清理它；不能指向已有用户数据。JUnit、完整日志和收集清单一同保存。不要使用 `--lf`、`-k` 或文件子集代替这次完整结果。

四个历史真实 LLM 用例在 `tests/test_real_llm_integration.py`，`tests/conftest.py` 的 `require_real_llm` 默认会 skip。默认 skip 必须登记，不能将“全部非真实 LLM 用例通过”写成“1300 多项全部通过”。在专用测试模型连接和隔离数据准备好后再运行：

```bash
cd "$QC_TEST_ROOT"
QUANTCODE_USE_REAL_LLM=1 "$QC_PYTHON" -m pytest -q tests/test_real_llm_integration.py -rA \
  --basetemp "$QC_RUN_DIR/pytest-real-llm-tmp" \
  --junitxml "$QC_RUN_DIR/python-real-llm-junit.xml" \
  > "$QC_RUN_DIR/python-real-llm.log" 2>&1
printf '%s\n' "$?" > "$QC_RUN_DIR/python-real-llm.exit"
```

这四项仍是旧 Runner/独立 Dream 的兼容测试，现有 fixture 会创建旧 DeepSeek adapter；它们不能证明原生统一 Provider 的单配置链路。只允许使用专用测试凭据，不读取用户现有 `config.json` 或隐式环境 key。缺测试授权/接口时登记 `BLOCKED_EXTERNAL` 并保留未完成状态；不能临时换为 mock、删除或 skip 来满足数量。原生真实模型场景还要按 §8 单独验证。

## 4. Bun 用例：按包运行，不从 frontend 根运行

`frontend/package.json` 和 `frontend/bunfig.toml` 显式禁止根目录跑测试。下面各行的工作目录都相对于 `QC_TEST_ROOT`；逐条进入对应目录运行原 package 命令，并按 §2 保存独立日志/退出码。不要全局开启 `QUANTCODE_UNIFIED_RUNTIME=1`：原/新模式应由各测试 fixture 分别设置，避免把整个旧兼容套件变成错误环境。

| 顺序 | 工作目录 | 真实命令 | 覆盖说明 |
|---|---|---|---|
| 1 | `frontend/packages/effect-drizzle-sqlite` | `bun run test` | 本轮 Event/SQLite 提交所依赖的存储层 |
| 2 | `frontend/packages/llm` | `bun run test` | 现有 LLM 适配/协议套件；不启动录制环境或导入真实 key |
| 3 | `frontend/packages/core` | `bun run test` | Core 全量，包括 session、Event、进程、锁、数据库和工具测试 |
| 4 | `frontend/packages/opencode` | `bun run test` | 默认 30000 ms timeout；包括 `test/session`、`test/tool`、`test/quantcode`、HTTP 与实际默认执行链 |
| 5 | `frontend/packages/opencode` | `bun run test:httpapi` | 仓库现有 coverage/auth/effect 三阶段 exerciser，带 `--fail-on-missing --fail-on-skip` |
| 6 | `frontend/packages/sdk/js` | `bun run test` | 桌面使用的 SDK 客户端契约 |
| 7 | `frontend/packages/client` | `bun run test` | 当前 `/api` client 兼容与协议测试 |
| 8 | `frontend/packages/ui` | `bun run test` | 已复用 UI 组件 |
| 9 | `frontend/packages/session-ui` | `bun run test` | 会话、消息与结果展示组件 |
| 10 | `frontend/packages/app` | `bun run test:unit` | 全部 `src` 单元测试，不只 QuantCode 子目录 |
| 11 | `frontend/packages/app` | `bun run test:browser` | `test-browser` + browser 条件 + Happy DOM；不是 Chromium/Electron 验收 |
| 12 | `frontend/packages/desktop` | `bun test --only-failures ./src ./scripts ./*.test.ts` | main/preload/renderer、打包配置、更新及发布脚本测试；此包没有 `test` package script |

Opencode 的 `bunfig.toml` 加载 `@opentui/solid/preload` 和 `test/preload.ts`；Core 使用自己的 `test/preload.ts`；App scripts 指定 `happydom.ts`。保留这些真实 preload，不用临时简化环境绕过失败。

需要定位失败时可补跑原子集，例如：

```bash
cd "$QC_TEST_ROOT/frontend/packages/opencode"
bun run test ./test/session ./test/tool ./test/quantcode
```

子集仅用于诊断，不代替全包结果，也不重复累计通过数量。取消、回执、身份、预算或状态用例不能因为难以通过而被删除、改为 skip 或从列表过滤。

HttpApi exerciser 的 `test/server/httpapi-exercise/environment.ts` 使用独立临时数据库并可能清理它。不要设置 `OPENCODE_HTTPAPI_EXERCISE_DB`、`OPENCODE_HTTPAPI_EXERCISE_GLOBAL` 为真实目录。新增路由若尚缺覆盖，应补实际场景；不能去掉 fail-on-missing/skip 开关。

## 5. 协议生成与类型检查

先在隔离副本完成同源码的生成一致性，保留生成前后 diff；生成成功不算类型或行为通过：

```bash
cd "$QC_TEST_ROOT/frontend/packages/sdk/js"
bun ./script/build.ts --generate-only
cd "$QC_TEST_ROOT/frontend/packages/client"
bun run generate
```

现有 client `check:generated` 会与 git HEAD 比较；当前迁移尚有未提交生成物时，直接运行可能因合法本轮改动返回非零。此时应与**本轮源码快照开始时的生成物**比较，不擅自提交、回退或清空差异来获得通过。发现再生成有新差异需定位并同步真实源码，不能手改生成文件补洞。

在下面各包目录依次执行 **`bun run typecheck`**，不用根 `tsc` 替代：

`schema → protocol → effect-drizzle-sqlite → llm → core → server → client → sdk/js → opencode → ui → session-ui → app → desktop`。

这是依赖诊断顺序，所有所列包都保留独立结果。基础 schema/storage 的失败解决后再解释下游连锁错误。不得只检查 App 就宣称原生引擎或桌面主进程通过。

## 6. Playwright：复用已核验的隔离服务

必须先确认测试网页 URL 和其目标后端属于当前源码、隔离测试账号与状态，不以 `/global/health` 成功代替版本和身份核对。现有用户预览如果连接真实成员账户，不可直接拿来跑会创建任务、修改设置或触发工具的 E2E。

两个配置默认都可能启动 dev server；以下明确禁止这种行为：

```bash
export PLAYWRIGHT_EXTERNAL_SERVER=1
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:CONFIRMED_TEST_FRONTEND_PORT
export PLAYWRIGHT_TARGET_SERVER=http://127.0.0.1:CONFIRMED_TEST_BACKEND_PORT
cd "$QC_TEST_ROOT/frontend/packages/app"
bun run test:e2e -- --config=playwright.quantcode.config.ts --list \
  > "$QC_RUN_DIR/quantcode-e2e-collect.log" 2>&1
bun run test:e2e -- --config=playwright.config.ts --project=chromium --list \
  > "$QC_RUN_DIR/app-e2e-collect.log" 2>&1
```

端口占位符必须换成已经核验的数字；当前没有被本计划授权启动新服务。收集成功后保存完整用例列表，再执行：

```bash
bun run test:e2e -- --config=playwright.quantcode.config.ts \
  --grep-invert 'workspace views have full layouts and preserve domain boundaries at 390px' \
  > "$QC_RUN_DIR/quantcode-e2e.log" 2>&1
printf '%s\n' "$?" > "$QC_RUN_DIR/quantcode-e2e.exit"
bun run test:e2e -- --config=playwright.config.ts --project=chromium \
  --grep-invert 'workspace views have full layouts and preserve domain boundaries at 390px' \
  > "$QC_RUN_DIR/app-e2e.log" 2>&1
printf '%s\n' "$?" > "$QC_RUN_DIR/app-e2e.exit"
```

唯一明确排除的是现存 `workspace.spec.ts` 的 390 px 手机场景，依据用户明确“只做桌面”；将该原始标题记为范围排除，不计为通过。900 px 为窄桌面保留，1440/1920 桌面需求不因已有用例只覆盖部分宽度而省略。不得追加其他 `grep-invert` 来屏蔽产品失败；默认 App E2E 中重复执行的 QuantCode 项不重复计数。

QuantCode 配置将报告写到 `e2e/quantcode-report`、失败截图/trace 写到 `e2e/test-results/quantcode`；通用配置使用 `e2e/playwright-report` 和 `e2e/test-results`。每轮结束复制到本轮结果目录再进行下一轮，避免报告覆盖。`workspace.spec.ts` 的部分场景动态导入 Vite 源文件并拦截后端响应，因此需要当前 Vite 测试页面；不能将静态产物页面的不支持误判为产品失败，也不能把这些 fixture 结果当作真实组织服务通过。

## 7. 构建、安装包与发布契约

只在隔离副本生成产物；不覆盖运行中应用的 `out`/`dist`，不启动 dev/preview 代替构建验收。构建阶段不应携带 `GH_TOKEN`、发布/签名秘密或 `OPENCODE_RELEASE`。后者在脚本里按非空值判断，设置字符串 `false` 也会启用发布分支，应当不设置。

| 工作目录 | 命令 | 注意事项 |
|---|---|---|
| 根目录 | `bun run build:web` | 原脚本固定 QuantCode channel，Vite 产物构建 |
| `frontend/packages/sdk/js` | `bun run build` | 原 SDK 生成及打包脚本；其成功不替代前述用例 |
| `frontend/packages/desktop` | `OPENCODE_CHANNEL=quantcode QUANTCODE_UPDATE_FEED=disabled bun run build` | 自动执行现有 prebuild（图标、metainfo、许可证、Node server）及 postbuild updater 检查 |
| 根目录 | `bun run build:desktop` | 上一行的根入口，二者不需要无理由重复跑 |
| `frontend/packages/opencode` | `OPENCODE_CHANNEL=quantcode bun run build -- --single --skip-install --skip-embed-web-ui` | 单机原生宿主 CLI 构建；脚本自身包含 `--version` smoke，必须归入测试/构建阶段；需要预先锁定依赖 |

本机 QA 包使用已有 package 命令，选择当前受支持平台之一：

```bash
cd "$QC_TEST_ROOT/frontend/packages/desktop"
OPENCODE_CHANNEL=quantcode QUANTCODE_UPDATE_FEED=disabled QUANTCODE_UNSIGNED_BUILD=true \
  CSC_IDENTITY_AUTO_DISCOVERY=false bun run package:mac
```

Windows 对应 `bun run package:win`，Linux 对应 `bun run package:linux`；通用入口为 `bun run package`，根入口是 `bun run package:desktop`。这些命令都有现成 prepackage，会先构建；不另造打包流程或全仓改名。只在对应平台执行，不将跨编译出来的文件存在当作安装成功。unsigned QA 包不能标为正式签名发布通过。

正式签名、公证、产物清单和安装 smoke 沿根 `.github/workflows/quantcode-desktop.yml` 及其既有 `build-quantcode-desktop` action 验证；本计划不自动 dispatch、publish 或上传 Release。该 workflow 的真实平台矩阵决定需要哪个运行环境；当前机器没有的目标记录 `BLOCKED_EXTERNAL`，不声称全部平台通过。

已安装的**隔离测试包**启动后，可复用现有只读 smoke 检查：

```bash
cd "$QC_TEST_ROOT/frontend/packages/desktop"
QUANTCODE_SMOKE_DEBUG_URL=http://127.0.0.1:CONFIRMED_DEBUG_PORT/json/list \
  QUANTCODE_SMOKE_PID=CONFIRMED_TEST_APP_PID bun scripts/verify-packaged-launch.ts
```

必须使用该独立测试进程的实际 debug 地址/PID；不得指向用户正在使用的应用。该脚本核对窗口、品牌、交互和 sidecar health，不覆盖本机 SSH/GitHub IPC、模型请求、权限与恢复，需要继续 §8。安装包还须核对未另装 OpenCode、许可证字节/来源 manifest、配套 native/worker 资产及原配置/历史保留。

## 8. 真实服务、场景和完成判定

自动化套件之外，对照 [最终验收场景](FINAL_ACCEPTANCE_SCENARIOS_2026-09-08.md) 与内化决策七项标准记录实际证据：一次 URL/API Key 的原生主/子任务；本机 SSH/GitHub 两种方式；真实已发布组件；跨成员 Admin/Gate；取消、重开继续、预算、未知副作用核对；旧 Python/无 owner 原生历史/旧组织投影兼容；安装与升级。

该场景文档的历史批次顺序不覆盖用户最新“先桌面 UI，再用例测试”的指令。列表中的场景编号用于追踪已承诺要求，不能把未实现项标为 N/A，或按当前代码的局部行为缩小原目标。

真实联调使用明确授权的测试成员、专用测试 key、临时新会话和测试资源；不复用开发者正在使用的身份/模型/审批记录，不撤销真实用户权限，不创建实际生产部署或向他人发送消息。没有必要测试资源时如实记录外部阻断。只有失败路径用 fixture 验证，不足以关闭真实成功路径。

`scripts/verify_product_audit.sh` / `bun run check:product` 可在上述条件满足后作现有汇总入口，但其范围只有 Python、Ruff、QuantCode 组件子集、三个包类型、web build 和单文件 E2E，**不能代替** Core/Opencode/App 全量、SDK、desktop unit、完整 E2E 与安装检查。`check:deployment` 读取真实宿主配置并检查 gateway/产物，只对专用部署测试环境使用，不把它混入无凭据单元套件。

最终状态保留：`NOT_RUN / PASS / FAIL / BLOCKED_EXTERNAL / N/A（有明确范围依据）`。跳过、缺失、超时及缺外部条件都不是 PASS；原 1300 个 nodeid、新增用例、桌面交互与真实服务要求必须分别可追溯。只有当前源码对应的全部要求均有充分证据，才可完成总目标。

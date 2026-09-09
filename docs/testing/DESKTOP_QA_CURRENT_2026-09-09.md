# 当前源码 Desktop / Playwright QA

日期：2026-09-09（Asia/Hong_Kong）。本记录只覆盖本轮实际执行的桌面构建、安装包启动、浏览器交互和初始化修复。Server C 真实模型、组件执行与跨成员审批不包含在浏览器 fixture 通过结论中。

最新桌面批次为 **09:15:12 HKT DMG / 09:15:16 HKT ZIP**，已包含审批后继续执行、服务器管理入口、新安装默认统一执行器和 bun-pty 补丁。新包的全新用户数据启动、实际 capability 检查和 Electron 截图已通过；此前安装包批次均为历史证据。独占 Server C 的实际桌面任务也已完成审批、一次继续执行、产物验证和退出登录。最终批次详见文末。

## 环境和来源

- 源码：当前 `QUANTcode/frontend` 工作树，HEAD 为 `009dde498d2393b6d185fc236af935ec04c10382`，包含未提交更改。没有使用旧 `/Applications/QuantCode.app`。
- 原预览 `5744` 为当前工作树 Vite，但 `4096` 的进程目录是旧 `opencode-lens/packages/opencode`，因此本轮另建独立环境。
- 当前 UI：[http://127.0.0.1:5844/](http://127.0.0.1:5844/)，当前源码后端 `127.0.0.1:5896`，fixture gateway `127.0.0.1:55731`。
- 环境由 `scripts/prepare_desktop_ui_review.py` 创建，隔离 roster、SSH agent、临时密钥、会话和 XDG 目录；无真实模型凭据。真实 `IdentityGateway` challenge/verify 生成 `ui-fixture-admin`（infra 组、admin 角色）身份。
- 10 条任务与配套产物为标有 `[UI FIXTURE · 无执行]` 的合成投影，不代表 Agent 执行。
- 私有证据目录：`/tmp/quantcode-browser-qa-20260909-current`。其中 control 含测试密钥，不作为可分享报告附件。
- 按主任务要求保留本轮预览服务，现有 `5744`、旧 `4096`、Server C 和 SSH 隧道均未重启。

## 实际结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| QuantCode Playwright 首轮 | 19 通过、9 失败 | `playwright-initial.log`、`initial-artifacts/`、`initial-report/` |
| 更新迁移后的 E2E fixture/断言 | 28 通过，33.4 秒，退出 0 | `playwright-current.log`、`current-artifacts/`、`current-report/` |
| 修复真实首页初始化后复验 | 28 通过，1.7 分钟，退出 0 | `playwright-after-bootstrap.log`、`final-artifacts/`、`final-report/` |
| 当前 Desktop 单元和脚本测试 | 106 通过、0 失败，19 文件 | `desktop-tests-final.log` |
| App 单元测试（含新初始化回归） | 660 通过、0 失败 | 执行 `bun run test:unit ./src/context/global-sync/bootstrap.test.ts`，原脚本同时包含整个 `./src` |
| App 类型检查 | 通过，退出 0 | `app-typecheck-after-bootstrap.log` |
| 无 API 拦截的真实首页初始化 | 无默认 `/path` 请求、无后端 4xx/5xx | `fresh-network-final.json` |
| macOS arm64 构建和打包 | 通过，退出 0，禁止发布 | `desktop-package-final.log` |
| ZIP 完整性 | 通过 | `zip-integrity-final.log` |
| 新 DMG 挂载后 packaged smoke | 通过，窗口/品牌/交互/sidecar 连续稳定 2039 ms | `dmg-mount-final.log`、`packaged-smoke-final.json`、`packaged-launch-final.log` |

29 条现有 Playwright 用例中，唯一未执行的是 390 px 移动端场景，沿用用户“只做桌面”的范围；不计为通过。保留 900、1440、1920 px 桌面覆盖。

## 修复和边界

首轮 9 个失败来自旧 E2E 与当前统一运行时不匹配：历史查询仍走旧工具路由、角色测试仍期待 Skill 下拉框、Admin 报告及供应商文案过期、浏览器测试点击仅桌面支持的本机 GitHub 凭据按钮、Admin 测试向已移除的旧组件替换 DOM。

`workspace.spec.ts` 已按当前契约修正：历史进入“归档任务”并查询 `/legacy/tasks`；角色验证自动加载组 Skill；Admin 通过原生组织任务接口 fixture 验证统计、组搜索及状态筛选；浏览器本机凭据场景验证禁用。未降低恢复阻断、身份失效、权限范围或错误状态预期。多数用例使用 API fixture，因此仅证明浏览器接线和展示。

CUA 随后在未拦截 API 的页面发现初始化错误。调查证明：裸 `/path` 请求由全局 bootstrap 发起，后端把默认服务目录作为请求目录，并按工作区授权正确拒绝；带真实授权目录的 `/session` 请求返回 200 和空列表。`src/context/global-sync/bootstrap.ts` 现在在 QuantCode 尚未选择目录时返回空 Path，选择目录后仍查询真实路径。新增单元回归并用真实首页网络确认不再发裸 `/path`，没有放宽后端工作区授权。

保存最终无拦截网络证据时曾有一次页面 `load` 等待超过 30 秒；重验使用 DOM 就绪加账号入口可见，随后观察 6 秒，退出 0。该等待失败不计为通过，也未归因为后端错误。

## 安装包批次

本批包含 bootstrap 初始化修复。其他子任务仍在修改 `legacy-provider.ts`、`snapshot-access.ts`、`write-policy.ts`；本记录不能证明本批包含其之后的修改。主任务应在这些源码稳定后核对或重建。Python 组织工具 helper 不内置在桌面包中，仍由配置的执行宿主提供。

| 产物 | 更新时间 | 字节 | SHA-256 |
| --- | --- | ---: | --- |
| `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.dmg` | 2026-09-09 05:57:37 HKT | 152846873 | `4710a5f2ade9f3be5f36d0939def64c93019e13da6d5904735c6802ff1a20dde` |
| `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.zip` | 2026-09-09 05:57:57 HKT | 151688327 | `532b6b8a5e3f05f18182a5c876827689e861c3cca04cbf856c5a062fdcbc8ce7` |

原生宿主 Node bundle 生成时间为 05:54:58 HKT，Electron 主进程与 bundled sidecar 输出时间为 05:56:06 HKT。Bundle ID `org.hkust.quantcode`，产品名 `QuantCode`，版本 `1.17.11`。使用 unsigned QA 模式；未签名、公证、发布或覆盖系统安装。

实际执行命令（各包目录内）：

```sh
# frontend/packages/app
PLAYWRIGHT_EXTERNAL_SERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5844 \
  PLAYWRIGHT_TARGET_SERVER=http://127.0.0.1:5896 bun run test:e2e -- \
  --config=playwright.quantcode.config.ts \
  --grep-invert 'workspace views have full layouts and preserve domain boundaries at 390px'

# frontend/packages/desktop
bun test ./src ./scripts ./*.test.ts
OPENCODE_CHANNEL=quantcode QUANTCODE_UPDATE_FEED=disabled \
  QUANTCODE_UNSIGNED_BUILD=true CSC_IDENTITY_AUTO_DISCOVERY=false \
  bun run package:mac --publish never
```

安装包 smoke 挂载新 DMG 为只读，从挂载目录启动 `QuantCode.app/Contents/MacOS/QuantCode`，使用 `OPENCODE_TEST_ONBOARDING=1`、新回环 DevTools 端口和仓库现有 `scripts/verify-packaged-launch.ts`。测试进程结束后卸载 DMG。

## Server C Linux CLI 构建

06:06 HKT 另行构建 Server C 使用的 Linux x64 完整 compiled CLI。`script/build.ts` 新增 `--target` 和 `--outdir`，继续使用既有 CLI、TUI worker、parser worker 和 native 资源入口；未使用 Node bundle 代替 compiled CLI。自定义输出目录必须不存在，避免清空已有桌面 `dist/node`。

```sh
# frontend/packages/opencode
OPENCODE_CHANNEL=quantcode bun script/build.ts --target linux-x64 \
  --outdir /tmp/quantcode-linux-x64-20260909-cli-v2 \
  --skip-install --skip-embed-web-ui
```

本机原先仅装有 macOS 可选原生依赖。补充下载并逐项核对 `bun.lock` SHA-512 后，安装 Linux 构建输入：`@opentui/core-linux-x64@0.3.4`、`@ff-labs/fff-bin-linux-x64-gnu@0.9.4`、`@parcel/watcher-linux-x64-glibc@2.5.1`、`@lydell/node-pty-linux-x64@1.2.0-beta.12`。没有修改 `bun.lock` 或 package 依赖声明。

不支持的目标、`--target` 与 `--single` 冲突、已有自定义输出目录三项拒绝检查通过；检查前后 `bun.lock` 和桌面依赖的 `dist/node/node.js` SHA-256 一致。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `/tmp/quantcode-linux-x64-20260909-cli-v2/opencode-linux-x64/bin/opencode` | 137656448 | `17705658a8a9803f983fb34325bf78f386ea5761de26df9d665f60101b68d61e` |
| `/tmp/quantcode-linux-x64-20260909-cli-v2/opencode-linux-x64.tar.gz` | 47861005 | `0693a7db6a8599274518e359719d445c0321034749bd254f2062170eb1021985` |

ELF 检查为 GNU/Linux x86-64，版本 `0.0.0-quantcode-202609082206`。压缩包包含 `bin/opencode` 和 `package.json`，已通过 `ubuntu@qs-gpu` 上传至 `/tmp/quantcode-qa-20260909-4bMCNF/opencode-linux-x64.tar.gz`，scp 退出 0。部署子任务随后在 Server C 核对 ELF，`--version` 返回上述版本，factor 原生宿主已通过 compiled CLI `serve` 启动，未认证身份接口返回 401。其余成员和真实成功场景由部署验收记录继续覆盖。

此 Linux 编译已包含 05:59:58 更新的 `legacy-provider.ts`、`snapshot-access.ts`、`write-policy.ts`；上面的 05:57 桌面包不包含这三项更新，最终桌面包仍需重建。

### Linux Release 2

06:28:16 HKT 以同一完整构建流程生成独立目录 `/tmp/quantcode-linux-x64-20260909-release2`，版本 `0.0.0-quantcode-202609082228`。本批包含构建前已完成的 MCP 按需连接、取消处理及类型契约修复。未覆盖 release1 或桌面缓存。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137660544 | `9ee765471fece32964eed459d064d9ff08a0dde601e30cec59f0c06859d34c31` |
| `opencode-linux-x64-release2.tar.gz` | 47861343 | `9e24130be56ef9e614384c385a6b7597c9bcbf1202a3d87b45d7dde19ee9555d` |

archive 已上传 `/tmp/quantcode-qa-20260909-4bMCNF/opencode-linux-x64-release2.tar.gz`，scp 退出 0。部署方使用 `/opt/quantcode-qa/artifacts/opencode-linux-x64-release2` 和 `e2e-20260909-02` 的新端口组 6301–6308 验证；实际服务器验证结果另由部署记录提供。

部署子任务回报：release2 远端 SHA-256 和 `--version` 一致，8 个新 native units 全部 active，身份接口匿名 401/Basic 200；22 个工具的候选目录已按各自有效配置绑定并发布，保持 9 published/13 disabled。8 个进程的 UID、CapEff、NoNewPrivs 和可写路径核对通过。实际模型任务仍在执行，这些检查不代替任务闭环结果。

### Linux Release 3

真实 factor 新任务随后暴露方案接口 400：Python 用 `solution: null` 表示没有方案，适配器却保留 `solution: undefined`，被 `optionalKey` 拒绝。`quantcode/solution.ts` 现在通过结构化解构真正省略空方案字段；已有方案、错误文档、版本、状态、宿主错误和返回任务 ID 校验均保留，SDK schema 未变。

新增 `test/quantcode/solution-response.test.ts`：修复前 **6 pass / 1 fail**，明确复现 `Expected QuantCodeSolutionDocument, got undefined`；修复后 **7 pass / 0 fail**。Opencode 全包类型检查退出 0。证据：`/tmp/qc-solution-empty-before.log`、`/tmp/qc-solution-empty-after.log`、`/tmp/qc-opencode-typecheck-release3.log`。

06:42:14 HKT 构建完整 Linux CLI 到 `/tmp/quantcode-linux-x64-20260909-release3`，版本 `0.0.0-quantcode-202609082242`。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137660544 | `8b745a59265994d2cf5265795db925b93504e239fdde2f49089f5e2b915bd63e` |
| `opencode-linux-x64-release3.tar.gz` | 47861346 | `4faa299c2e237657f14d16d71cd1d291b76ef77b4c96f454fd6521ed00e7f3b2` |

部署方使用新 artifact 和 `e2e-20260909-03`，先在 factor canary 6502 验证完整任务，后续才扩展 6501–6508 八组宿主。旧 release 证据保留；桌面包等待原生联调稳定后统一重建。

### Linux Release 4

真实 Qwen 调用进一步发现模型将 `organization_reuse.components` 输出为 JSON 字符串。`organization-reuse.ts` 和 `organization-solution.ts` 为模型提供顶层 object/action enum schema，分支字段重用原 Schema 定义；`components`、`acceptance_criteria`、`file_impact` 均为字符串数组。运行时仍使用原 `status/propose` 判别联合，不转换字符串、不放宽缺字段或审批校验。

新增 schema 回归 **18 pass / 0 fail**，覆盖两种合法 action、三个数组字段，以及字符串数组、非字符串元素、缺失字段、字符串版本、approve/freeze 的拒绝；全包类型检查通过。证据 `/tmp/qc-organization-schema-tests.log`、`/tmp/qc-organization-schema-typecheck.log`。

`qwen3.7-flash` 对照使用相同 description、prompt、temperature=0，6 次真实模型调用但不执行工具。reuse 的 none/empty、partial/one、status 三种输入：原 schema **1/3** 合法，候选 **3/3** 合法；原前两种 components 为字符串，候选为真正数组。两组都按未改变的运行时 schema 验证。报告 `/tmp/qc-organization-schema-ab/qwen-results.json`，两工具原/候选 schema 在同目录。该小样本支持修复当前已复现问题，不代表所有模型都已验收。

主任务另外修复英文写入任务分类，并让原生 write 返回真实产物元数据交给既有授权/快照/hash流程；相应分类 45 项、write 15 项测试由主任务验证通过。07:00:12 HKT 构建 release4 到 `/tmp/quantcode-linux-x64-20260909-release4`，版本 `0.0.0-quantcode-202609082300`。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137660544 | `c6e67baacab107323cb17ece11d50bc9f222e8f4526f019437655476b7fe2b31` |
| `opencode-linux-x64-release4.tar.gz` | 47862041 | `00e4b01e9375b3406d9f509c2b5a6c9726215ce32eb20d2ce7dc6a6ae1ab2149` |

归档上传同一 staging 目录的新 release4 文件，部署方使用 source `e2e-20260909-04` 和 factor canary 6702 继续验证；Python source4 已含分类修复。旧 artifact 和证据不覆盖。

### Linux Release 5

release4 的真实 factor 任务完成后，产物计数为 1，但标记 `original_not_captured`。原因是 built-in 写工具只在外层返回后以缺省非 fresh 模式捕获，文件路径从未作为本次执行的原始字节读取。

`tool/tool.ts` 现在在真正执行写入的回执回调中先补齐元数据、完成一次结果截断，再以 `fresh: true` 捕获快照，之后才记录完成回执。回执、产物事件与返回值共享同一最终结果摘要。外层 `SessionTools` 捕获逻辑保持不变，新回放命中已有事件，不重读变化后的文件，也不重新创建截断输出路径。非写工具不改变行为；旧回执没有快照时仍标记原始内容未捕获。

新增 `write-artifact-replay.test.ts` 使用真实 WriteTool、SessionTools、SQLite/Event、复用审核、Python 方案审批、文件写入和快照读取，仅外部身份 authority 为临时 fixture。修复前 1 pass/1 fail，明确复现实际写入后产物 unavailable；修复后 2 项新安全回归、15 项 write、5 项 Tool.define 共 **22 pass/0 fail**。全包 typecheck 退出 0。

覆盖证据包括：快照事件先于完成回执、两个结果摘要相同、强制截断只执行一次、回放结果及 outputPath 不变、外部改写工作文件后仍读取原始快照字节/哈希、旧回执不会把当前文件冒充原产物。日志 `/tmp/qc-write-artifact-before.log`、`/tmp/qc-write-artifact-after.log`、`/tmp/qc-write-artifact-typecheck.log`。

07:22:17 HKT 构建到 `/tmp/quantcode-linux-x64-20260909-release5`，版本 `0.0.0-quantcode-202609082322`。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137660544 | `a337886342b24e8da2bff0ea37b7e42930a13b57e10d40f2134ff340709fe7cf` |
| `opencode-linux-x64-release5.tar.gz` | 47862200 | `60d147c7d5b1d91f27d0bc8c838678370d4ffcc086cb7cc1095b6cc522affadd` |

归档已上传同一 staging 目录，scp 退出 0。部署方使用新 artifact、`e2e-20260909-05`、factor canary 6902 验证，Python 复用 source4。

### Linux Release 6

主任务修复成功的 native login、verify、logout 后跨工作区缓存失效：操作成功后处置宿主的所有旧实例，防止其他已登记目录继续使用旧 MCP 身份。真实两工作区回归和全 identity gateway 共 20 项通过，全包类型检查通过，证据 `/tmp/qc-identity-workspace-after.log`、`/tmp/qc-identity-gateway-full.log`、`/tmp/qc-opencode-identity-typecheck.log`。

07:50:56 HKT 构建 `/tmp/quantcode-linux-x64-20260909-release6`，版本 `0.0.0-quantcode-202609082350`，包含当前 reuse schema/说明、产物捕获和身份失效修复。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137664640 | `eade6adcff6a881c4c224c4dff86ad8d94e16fa4c8dc8dc9b828bd4dbb28e9f8` |
| `opencode-linux-x64-release6.tar.gz` | 47862608 | `6fd18cae7839e6fc9ad9fab2a52cb725a14f09d8b65b76156e95f73d22e1610b` |

归档上传同一 staging 目录，scp 退出 0。部署使用 `e2e-20260909-06`、factor canary 7102，Python 继续 source4；实际 canary 结果另由部署记录提供。

## 后续工具类型契约检查

编译后检查了 `tool.ts`、`read.ts` 和 HTTP 文件 handler 的类型错误。工具初始化定义现在允许内部执行依赖 `Database` 和 `AppProcess`，已有包装器提供它们后，公开 `execute` 仍为无环境依赖的 Effect；没有取消或放宽原生校验。读取流和文件内容分别注明公共 `Uint8Array` 类型，避免 `Buffer` 与 `Uint8Array` 的联合推断形成错误交叉类型，字节读取行为不变。

全仓未调用的旧 Promise 导出 `assertExternalDirectory` 已删除；其直接 `runPromise` 不能提供新增数据库上下文。实际调用的 `assertExternalDirectoryEffect` 与所有目录/身份校验保留。这是内部未使用包装的删除，应随下一次源码构建包含。

- `tool-define`、`read`、`external-directory`、`parameters`：107 通过，0 失败，证据 `/tmp/qc-tool-contract-tests.log`。
- HTTP 文件读取与搜索：2 通过，0 失败，证据 `/tmp/qc-file-http-contract-tests.log`。
- 全包类型检查仍失败：本次快照剩 46 条（30 条源码、16 条测试）；上述工具源码和文件 handler 已无错误。证据 `/tmp/qc-opencode-typecheck-tool-contract.log`，不标为整包通过。其他子任务继续处理剩余项。

随后继续修复数据库 Part 类型与预算/发布类型：`V1PartData` 使用分配律 `Omit`，保留各 Part 的 discriminator 和字段；预算审核使用已解码 Reviewed 对象，停止确认仍要求运行时严格为 `true`；本机任务摘要显式排除 gateway 才能添加的 `received_at`。发布队列保留已验证的 SessionID 品牌，工具事件使用实际解码类型。

`parsePatch` 的旧 `strict` 参数在当前 diff v8 已不存在，已移除被忽略的参数；库本身始终核对 hunk 行数，实际正反输入检查通过。`external-directory.test.ts` 补充真实 Database 测试 layer。

- VCS 与外部目录：17 通过、0 失败，`/tmp/qc-publication-type-fix-tests.log`。
- Core SessionProjector：8 通过、0 失败，`/tmp/qc-core-projector-type-fix.log`。
- 此次 Opencode 类型检查快照剩 21 条，预算、任务索引、任务发布器、VCS 与外部目录测试已清零；剩余由主任务处理，`/tmp/qc-opencode-typecheck-publication.log`。

## 严格 HTTP API 覆盖检查

执行现有 `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy bun run test:httpapi`，保留全部 `--fail-on-missing --fail-on-skip` 开关。coverage 结果为 **208 pass / 0 fail / 0 skip / 48 missing / 0 extra**，退出 1；后续 auth/effect 命令因原 `&&` 链停止而未执行。

48 条缺失覆盖为 27 GET 和 21 POST，包含模型代理及新增 QuantCode 身份、GitHub、legacy、组织/原生任务、产物、Gate、预算、执行锁、方案、回执和部署路由。准确 method/path 清单保存在 `/tmp/qc-httpapi-missing-routes.json`，完整日志 `/tmp/qc-httpapi-exercise-final.log`。本轮未更改场景或过滤缺失项，不能将该检查标为通过。

后续已补齐 51 个真实边界场景覆盖这 48 条路由，并修正测试隔离与旧换行断言。最终完整原命令退出 0：coverage、auth、effect 各 259 pass，0 fail/skip/missing/extra，覆盖全部 236 条路由。coverage 仅作登记检查，不将三阶段累计成 777 个独立场景。详见 [HTTP API 最终严格验收](HTTPAPI_EXERCISER_2026-09-09.md) 和 `/tmp/qc-httpapi-exercise-final-passed.log`。

## 审批后继续执行控件与 Linux Release 7

Server C 实际任务发现旧 UI 提示审批后“在对话中继续”，但新文字会触发新的任务意图哈希，从而撤销原能力审批。`task-review.tsx` 现在提供显式“继续执行”，使用 generated SDK `session.promptAsync` 提交 `parts: []`，保持原任务意图。提交前重新读取方案、复用审批、回执、执行锁、预算和服务端忙碌状态；从 `session.get` 读取该任务已保存的模型、Agent 和 variant，不使用输入框中尚未提交的选择。

提交中与已请求状态防止重复点击；切换任务或服务器取消旧 lifetime，迟到的预检和 HTTP 响应不能提交或覆盖新任务；HTTP 和异步 `session.error` 均保留错误且不自动重试。请求回应前收到任务执行错误，也不会随后被 204 成功提示覆盖。原后端权限、意图和审批哈希规则不放宽。

验证结果：

- App 单元测试：660 pass、0 fail，99 文件。
- App 响应式 browser 条件测试：17 pass、0 fail，8 文件。
- 新增 `e2e/quantcode/task-review.spec.ts`：9 pass、0 fail，实际 Chromium、Vite 编译控件和 generated SDK HTTP；上下文与 HTTP authority 为受控夹具，不作为 Server C 业务完成证据。
- App `bun typecheck`：退出 0。
- 截图：`frontend/packages/app/e2e/test-results/task-review-continue.png`，加载真实 App CSS 后核对无文本或控件重叠。

主任务同时补齐了宿主每轮可见的真实审批状态和可信空消息恢复语义，28 条 focused 回归与类型检查通过。08:10 HKT 构建完整 Linux CLI 到 `/tmp/quantcode-linux-x64-20260909-release7`，版本 `0.0.0-quantcode-202609090010`。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137664640 | `5bb5b9f6b845354d9fffceecdc4e270b4f7d325501a1924c378ed7b8be898fc3` |
| `opencode-linux-x64-release7.tar.gz` | 47862938 | `de65493a253c5a4394252cda89439a2ed3ea176f5e2767c9016a94b7c201d4d5` |

归档上传 `/tmp/quantcode-qa-20260909-4bMCNF/opencode-linux-x64-release7.tar.gz`，部署方使用 factor 7302 canary 验证审批后的真实继续执行。最终 macOS 安装包仍待该 canary 结果后统一构建；既有 05:57 HKT 桌面包不能代表本节新增修改。

## Linux Release 8 与最终桌面批次

release7 的实际 factor forced-pause 场景已通过一次空消息继续、真实文件写入、产物与下载哈希一致、重新登录后 native MCP 执行和退出撤销。报告 `/tmp/quantcode-serverc-factor-native-resume-release7.json` 明确使用合成整数输入，`domain_component_acceptance=false`、`desktop_ui_exercised=false`，不能解释为量化业务组件或桌面交互已完成。

主任务随后发现模型重复提交完全相同的能力方案时，时间戳改变会换 proposal hash 并丢失原批准。`reuse.propose` 现在只对原意图、原检查回执及完全相同内容复用既有方案；内容变化仍重新审批。29 条专项回归和类型检查通过后，构建 Linux Release 8，版本 `0.0.0-quantcode-202609090029`。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `opencode-linux-x64/bin/opencode` | 137664640 | `950a7e38ed78a1eef839ad6241ef7d4447bcb20892faff8b17e180405a17644e` |
| `opencode-linux-x64-release8.tar.gz` | 47863007 | `f8a427d7c24cbf37e3f6728c6bb4b942cd365c37ee866c62caf0d46c419dbd2d` |

归档 scp 退出 0，上传 staging 同名 release8 文件；部署方最终组合为 release09 / Python source08 / CLI8。Python helper 的修复由远端 source08 提供，并不嵌入 Electron 安装包。

### 构建问题与新安装回归

第一次最终打包在 electron-builder 的 unsafe-path 检查处失败：先前 Linux cross-build 补装的 4 个原生依赖通过 symlink 指向 `/tmp`。将已验证的原目录复制到 `frontend/node_modules/.quantcode-cross-build`，逐文件 SHA-256 校验后只更新这 4 条依赖链接；版本与 `bun.lock` 均未变。失败日志 `/tmp/qc-desktop-final-release7-package.log` 保留。

08:30 的中间包成功启动后，实际首次安装仍显示旧 Skill 选择流程。根因是桌面 `createSidecarEnv` 没有给 QuantCode 产品启用统一执行器。现在仅当 `CHANNEL === "quantcode"` 时设置 `QUANTCODE_UNIFIED_RUNTIME=1`；通用 OpenCode 默认不改。研究服务器或组织身份未配置时，保留明确未连接状态，不降级到旧执行 UI。

现有 `scripts/verify-packaged-launch.ts` 增强为检查实际 `/experimental/capabilities` 必须返回 `quantcodeUnifiedRuntime=true`。对 08:30 包运行新检查，退出 1 并准确报 `did not enable the unified runtime by default`，日志 `/tmp/qc-desktop-default-runtime-before.log`；这不是只检查源码字样的测试。修复后 Desktop 106 tests / 0 fail、typecheck 退出 0，再重建新包。

### 08:36 中间安装包

| 产物 | 更新时间 | 字节 | SHA-256 |
| --- | --- | ---: | --- |
| `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.dmg` | 2026-09-09 08:35:56 HKT | 153054419 | `0e78e7e7eee0bbf4de8b7d1493c4b490003a39f65b7287a0d1f679b9d154ef85` |
| `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.zip` | 2026-09-09 08:36:01 HKT | 151933388 | `9ad3c04e9eae3e09daa5d31730a7cc2b051a8c12c1b8ead332a63e72cc15e358` |

- 构建命令仍为上文 unsigned QA、disabled update feed、`--publish never`；日志 `/tmp/qc-desktop-final-native-default-package.log`，退出 0。
- ZIP 完整性检查通过；新 DMG 以 readonly 挂载到 `/tmp/quantcode-final-desktop-20260909/mount`，从其中的 `QuantCode.app` 启动，未使用或替换 `/Applications/QuantCode.app`。
- `OPENCODE_TEST_ONBOARDING=1` 创建全新用户数据，启动脚本不传 `QUANTCODE_UNIFIED_RUNTIME`。真实安装包回归通过：Electron 42.3.3、QuantCode 标记、交互控件、内置 sidecar 健康、`unifiedRuntime=true` 连续稳定 2029 ms。
- 首页文本为“组 Skill 自动加载”；设置中旧 `#qc-settings-skill` 不存在。1280×800 首页、900×650 与 1440×900 设置截图均非空，设置无横向溢出。
- 证据目录 `/tmp/quantcode-final-desktop-20260909`：`smoke.json`、`renderer.json`、`settings.json`、`home.png`、`settings-900.png`、`settings-1440.png`。首次 CDP HTTP 探测因 Electron 不接受 `/json/version/` 尾斜线返回 400；改读精确 `/json/version` 的 WebSocket 地址后截图成功，没有修改应用或关闭安全机制。
- Computer Use 已对新挂载应用路径实际调用，返回 Mac 锁屏，无法进行原生鼠标、键盘或文件选择对话框验收。该项不记通过；Electron renderer/CDP 验收独立完成。
- 包内连接 Server C 的真实 Continue 交互等待最终八组运行结束后的独占 QA 身份；此前 9 项真实 Chromium 控件回归仅覆盖受控 HTTP，不替代该桌面业务闭环。
- 服务器管理入口已补入设置页，复用现有 `DialogSelectServer`，新增浏览器回归覆盖用户可见的添加、编辑和选择操作。整组 38 条旧/新增桌面 Web 场景重跑时准确结果为 27 pass、2 条历史 `page.goto` load 超时、1 条中断、8 条未运行；超时日志 `/tmp/qc-app-quantcode-final-management-e2e.log` 均发生在测试断言前，不计为通过也未改成仅为过测而降低等待条件。
- 使用独占 Server C 7902 和专用 SSH agent 启动最新挂载包后，实际设置页显示 Server C、factor、QA 指纹，点击“连接”进入真实认证状态；随后任务发送在新会话页未形成预期任务路由，未把该段误报为 Continue 业务通过。安装包内的 renderer/CDP/fresh smoke 仍已通过；待 bun-pty 补丁及最终包重建后再进行一次明确的登录→任务→审批→Continue 闭环。

## 实际桌面任务完成与最终交付包

继续调查上一节未路由现象，取得真实网络和输入证据：编辑器存在完整任务文本、工作区为授权的 factor 目录、`/agent` 返回正常列表；但独占 7902 的 global/workspace `/provider` 全部返回 `all=[]`、`connected=[]`。点击发送没有发出任何创建或执行 POST，而是明确提示“请选择智能体和模型”。因此这是新 QA 宿主尚未配置模型，并非路由故障，也不是自动化未输入文本。证据 `submit-reproduction.json`。

随后通过安装包内正常界面完成“管理服务器”保存与选择、SSH Agent 登录、供应商 URL / QA token / 模型配置，再从首页提交任务。没有注入 store，也没有手工调用创建任务或执行 API 代替点击。真实流量为 `POST /session` 200、`POST /session/:id/prompt_async` 204，实际任务页正常出现。

任务 `ses_f7c4928cfffelAv0Z5keykx7Ua` 第一轮按要求停止并提交能力覆盖方案。通过界面填写说明并批准，`reuse/review` 返回 200；随后只点击一次“继续执行”，仅发送一次空 `parts` 的 `prompt_async`，返回 204。任务原 `intent_hash` 不变，批准仍有效，使用任务保存的 `build` / `qc-127-0-0-1/qwen3.7-flash` / `default` 选择。

任务最终为 `completed`，source revision 166，产物数 1，原始捕获和交付状态均为 `available`。从实际输入计算期望结果，文件精确包含 `group=factor`、`count=4`、`sum=21`、`min=2`、`max=9`、`input_file=qa-input.json` 六个字段。工作文件、下载的原始快照及 chunk SHA-256 均为 `b900df0e43306f4e4cff8b65900e251398c05e5b3e1df14b1c268e40cc4a90d2`。最后通过桌面“断开”操作验证身份清除。

相关证据位于 `/tmp/quantcode-final-desktop-20260909`：`real-login-success.png`、`provider-configured.json`、`reviewed-task.json`、`review-continue.json`、`approved-before-continue.png`、`desktop-task-completed.png`、`desktop-real-flow-result.json`、`desktop-logout.json`。报告明确 `desktop_ui_exercised=true`、`synthetic_input=true`、`domain_component_acceptance=false`。它证明真实桌面和 Agent 文件任务闭环，不代表市场数据或量化业务组件接通。

### Web 验收补跑

范围共 38 项：原 28 项桌面场景、新 Continue 9 项、服务器管理 1 项；390px 移动端场景仍不在本次范围。第一次整组运行的 27 项通过保留；原预览 5844 随后出现连首页 HTML 都不响应的间歇故障，独立 `curl /` 超时 HTTP 000，而 5896 后端健康仍为 200，因此没有修改 `waitUntil` 或降低控件断言。

对尚未通过的 11 项使用同一源码的 production App build 和新静态 preview 5964 补跑：10 项通过（12.5 秒）和设置 1 项通过（1.9 秒），没有跳过失败场景。日志 `/tmp/qc-app-static-remaining11.log`、`/tmp/qc-app-static-settings-e2e.log`。因此 38 项均有通过证据，但并非同一次测试进程输出 38 pass。完成后只关闭新增的 5964 QA preview，原 5844 服务未重启。

### 最终构建

主任务确认 bun-pty 构造期间早退出补丁、frozen 安装和全量测试通过后，重新构建 Linux CLI9 与 macOS Electron。CLI9 版本 `0.0.0-quantcode-202609090114`，归档已上传 Server C staging，scp 退出 0。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| CLI9 `opencode-linux-x64/bin/opencode` | 137664640 | `91fe0ee5aff763836ab46e88abc633398cbde95d5acb0e27b49a3b0ec5aa69e3` |
| `opencode-linux-x64-release9.tar.gz` | 47863090 | `bb50454c62f317fcfc1d58a4be0db28b49bec306ecfe799cef235638141316f4` |
| `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.dmg` | 153056029 | `aa6fb6315689d2095438c4b8e1a1314779a2c770afb23dc3e9e218683bbaff5b` |
| `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.zip` | 151934955 | `12fa6dcfc9cae63bf16d161e4c0a8843c82066bb9f8134ee3c39ec304fce1438` |

DMG 生成于 09:15:12 HKT，ZIP 09:15:16 HKT。构建日志 `/tmp/qc-desktop-final-pty-package.log` 退出 0，ZIP 完整性通过。再次只读挂载最终 DMG，以全新用户数据、不额外传入统一执行器开关启动，实际 smoke 通过：`unifiedRuntime=true`、sidecar 健康且界面稳定 2029 ms，证据 `smoke.json`、`/tmp/qc-desktop-final-pty-smoke.json`。最终首页及 900/1440 设置截图已更新，管理服务器可见，无旧 Skill selector 和横向溢出。

此包仍为未签名、未公证的本机 QA 包，更新 feed 禁用，未发布或覆盖系统安装。原生 Computer Use 文件选择对话框因 Mac 锁屏未完成；Electron/CDP 与上述真实业务操作的通过结果不替代该原生对话框验收。

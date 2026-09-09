# QuantCode QA 执行报告

日期：2026-09-09。结论：**平台基础验收通过；尚不能宣布全员量化业务正式上线。**

依据：[产品验收计划](QUANTCODE_PRODUCT_ACCEPTANCE_TEST_PLAN_2026-09-09.md)、PRD、功能规格与内化决策。源码为 `009dde498d2393b6d185fc236af935ec04c10382` 加当前未提交工作树。没有使用旧安装包，也没有提交或发布正式版本。

## 最终结果

| 检查 | 实际结果与证据 |
| --- | --- |
| Server C 八成员原生任务 | 8/8 PASS；每组独立 Unix 账号、SSH key、宿主状态，真实 Qwen 调用 |
| 暂停、审批、继续 | 8/8 实际发送空 parts 续跑；原意图和批准保留，完全相同提案不产生第二次审批 |
| 文件与产物 | 8/8 实际读写、任务完成、组织发布、产物下载和 SHA256 核对 |
| 重新登录 | 8/8 保留模型和历史，新原生任务重新执行能力目录与 Memory 查询 |
| 严格跨成员矩阵 | 112/112 PASS，0 请求重试、0 模型调用；同 URL/版本，224 次 owner 读取成功、112 次 reader 自读成功，最终 8 次登出及访问撤销通过 |
| Python 当前全集 | 1268 passed、4 skipped，1272 collected，exit 0；`/tmp/qc-python-final-verified.log`、`/tmp/qc-python-final-verified.xml` |
| 4 项真实 Qwen 兼容测试 | 另行 4 passed；`/tmp/qc-qwen-typed-schema.xml`。不把默认 skip 算通过 |
| Opencode 当前全集 | 3119 passed、25 skipped、1 todo、0 failed，3145 项/257 文件，exit 0；`/tmp/qc-opencode-pty-patched-full.log` |
| Opencode 按文件隔离全集 | 257 文件全部 PASS；`/tmp/qc-opencode-per-file-final-verified.log`，不与上一行累计 |
| App | 660 单元、17 browser 条件测试通过；类型检查和 build 通过 |
| Chromium UI | 原 28 + Continue 9 + 服务器管理 1，共 38 项分批通过；不是同一进程输出 38 pass |
| Electron | 106 单元通过；新 DMG 启动、原生默认模式、服务器管理、真实登录、模型设置、审批、Continue、文件/产物及退出登录通过 |
| 严格 HttpApi | 259 个场景、236 条路由；coverage/auth/effect 原命令 exit 0，各阶段无失败、skip、missing 或 extra，不累计为 777 个用例 |
| 其他包 | Core 原全集 1058、LLM 296（30 skipped）、Storage 7、SDK 1、Client 16、UI 4、Session UI 57 通过；本轮另验证 Core PTY 22、OpenAPI 18、codegen 66 |
| 类型与静态检查 | Opencode、App、Desktop、Core 类型检查通过；相关 Ruff 和 diff whitespace 检查通过 |

主要证据：[八成员生命周期](SERVER_C_NATIVE_ALL8_LIFECYCLE_RELEASE9_2026-09-09.json)、[最终同版本隔离矩阵](SERVER_C_NATIVE_ALL8_CROSS_ONLY_SOURCE11_VERIFIED_2026-09-09.json)、[矩阵独立核对](SERVER_C_NATIVE_MATRIX_FINAL_VERIFICATION_2026-09-09.json)、[桌面及构建记录](DESKTOP_QA_CURRENT_2026-09-09.md)、[严格接口记录](HTTPAPI_EXERCISER_2026-09-09.md)。

八成员任务使用明确标注的合成整数输入，验证平台执行全链路。真实模型、文件、审批、任务和产物都由原生执行器生成；未手工发布“完成”记录。**这不代表因子评估、训练、回测、风险和估值等 canonical 业务链路已接通。**

## 本轮修复

- 登录成功、重新认证及退出后，清理所有工作区的旧 MCP 连接；真实双工作区和客户端中断回归通过。
- 审批后提供显式“继续执行”，使用任务保存的模型/Agent；每轮加载真实审批状态。相同提案重试保留批准或拒绝，改变意图、检索依据或内容仍重新审批。
- 三个业务组缺失的 Memory 查询接入现有公共只读工具通道，原鉴权和 ACL 保留；修复前八组子进程测试为 3 failed/5 passed。
- 方案状态读取允许短时等锁，避免 UI 轮询与工具读取冲突；并发写入仍立即拒绝。
- 原生写入在完成回执前捕获一次产物快照，重放保留原字节、哈希与回执，不用当前文件伪造旧产物。
- 修复无方案状态的 null/optional 解码、模型工具参数展示、写文件意图分类、旧模式停止不存在任务，以及 legacy Provider 分块 UTF-8 读取。
- 新安装默认启用统一执行器；设置页可添加、编辑、选择研究服务器，切换后重新认证；本地密钥不作为私钥正文上传。
- 修复目录取消、未选目录首页请求、测试 Response 混用、缺失 Effect 依赖、类型和 SDK 契约错误。
- bun-pty 缓存真实退出事件，晚订阅只回放一次；受控调度下原 HTTP 失败已复现并修复。既有 Effect 补丁未被改写。
- 修复测试 worker 尚未结束即关闭 SQLite 的 fixture 清理顺序；保留原 segfault 日志，修复后 Python 全集通过。
- Server C 补齐官方 bubblewrap/ripgrep，并验证实际 QA UID 下的隔离与搜索。未关闭 AppArmor、全局 userns 限制或设置 setuid。
- Python 网关显式声明 Connection: close，消除 Bun 复用已关闭连接导致的随机 400。8 登录对照中默认连接曾 12 次失败 5 次，修复后全部成功，随后严格 112 矩阵通过。

## 环境与构建

全程按用户要求使用 `ubuntu` 免密 SSH/sudo。正式 4097 网关 PID、roster、registry 和 runtime 链接保持不变；改动仅部署至隔离 QA 服务。

成员验收使用 native release09 / Python source08 / CLI8，端口 7701–7708；独占桌面流程使用 7902。最终连接关闭修复仅更新 QA 5097 至不可变 source11，保留其数据库、名册和身份注册表。PTY 后续补丁由完整 Opencode/Core 回归验证，并包含在最终 CLI9 与 Electron 包；不把早先 CLI8 的成员流程说成 CLI9 重跑。

最终 macOS arm64 QA 包：

- `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.dmg`，SHA256 `aa6fb6315689d2095438c4b8e1a1314779a2c770afb23dc3e9e218683bbaff5b`
- `frontend/packages/desktop/dist/quantcode-1.17.11-mac-arm64.zip`，SHA256 `12fa6dcfc9cae63bf16d161e4c0a8843c82066bb9f8134ee3c39ec304fce1438`

安装包未签名、未公证、未发布；未覆盖 `/Applications/QuantCode.app`。测试应用已关闭并卸载测试 DMG。真实 Qwen key 仅用于内存代理，测试结束已停止代理；QA 宿主仅持有一次性代理凭据。

## 尚未关闭

1. [原 1300 nodeid 对账](PYTEST_BASELINE_RECONCILIATION_2026-09-09.json)：1201 EXACT_PRESENT、38 MAPPED、48 SUPERSEDED_BY_SPEC、13 UNRESOLVED；当前收集 1272、新增 71。不能声称原始 1300 项全部等价通过。
2. [真实业务组件接入](SERVER_C_COMPONENT_READINESS_2026-09-09.md)：已有组件源码，但适配、服务入口、共享 Blackboard、授权数据和输入口径不完整；当前平台任务通过不覆盖这些缺口。
3. 当前 Mac 锁屏，原生系统文件选择对话框的人工/CUA 验收尚未完成；Electron/CDP 已验证上述产品流程和截图。其他系统架构的正式安装与升级也不在本轮已通过范围。
4. 正式成员宿主、生产服务配置、签名分发和推广尚未执行。Server C 最后剩余约 1.76 GiB，需要完成容量安排后再推广。

## 历史证据

首次 Opencode 2900 passed/188 failed、默认内存模式挂起、PTY 退出 race、一次 HTTP 连接重置、Python fixture 崩溃，以及各轮模型/工具失败均保留。最后低内存全集和按文件全集分别提供通过证据，不用旧缓存覆盖失败。

旧矩阵曾只完成 54 项；另一份 112 项记录未严格保持产物版本且缺最终登出，随后两次严格矩阵又暴露运输失败。这些都不是最终通过依据。[复核小结](SERVER_C_NATIVE_MATRIX_RECHECK_2026-09-09.md) 保留完整更正和网关修复前后证据。

38 项 UI 的分批验证保留原 Vite 首页 HTTP 超时记录；剩余场景在同源码 production preview 通过，没有降低等待或控件断言。未执行、跳过、失败和外部阻断不计为通过。

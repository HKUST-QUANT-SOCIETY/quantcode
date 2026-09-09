# 执行引擎内化进度

目标：完整实现 QUANTCODE_RUNTIME_INTERNALIZATION_2026-09-08.md 中所有阶段与验收条件。用户最新要求的顺序为：全部实现 → 桌面 UI 核验通过 → 用例测试，且此前 1200 多项用例须全部通过。不能先跑用例测试再补桌面 UI；未验收项不能标完成。

## 当前阶段：桌面 UI 核验与发现问题回修；真实宿主迁移尚未切换

最新核验已在明确隔离的 UI 开发宿主启用统一开关；正式服务未切换。下文按轮次保存的“未启用”表示当时状态，不能覆盖最新记录。现有源码交付仍需返回相应 M1～M4 边界修复，再完成全部 UI 和集中用例验收。

| 内化阶段 | 当前状态 | 下一阶段的前置交付 |
|---|---|---|
| M0 锁定规范和现状 | 静态交付已完成 | 现状、调用链、权限迁移和兼容清单 |
| M1 组织约束进入统一引擎 | 源码接线形成阶段交付，尚未完成集中编译/测试/验收；见 M1 核对表 | 身份、能力复用、方案、精确审批、预算、副作用与入口约束的源码落点，最终行为验证仍待完成 |
| M2 新任务入口 | 源码接线已形成，未验收；见 M2 核对表 | 原生任务/组织上下文/单一模型连接已接线；实际启用须等 M1 行为验证 |
| M3 状态、恢复和组织视图 | 源码交付见 M3 核对表，运行待验 | 任务/组织投影、历史恢复、实际取消及核对的最终验证 |
| M4 旧循环和命名清理 | 源码交付形成，未执行真实退役，见 M4 核对表 | 准备当前源码的桌面 UI 核验，随后全部用例与发布验收 |

这里的 M0～M4 是执行引擎内化顺序；PRD §8.3 的产品路线 M1～M5 是另一套能力目标。不能把已有 GitGraph/Admin UI、旧 Runner 测试或后续阶段草稿算作本次迁移已通过。

**验证记录更正（2026-09-08）**：此前另一位 agent 已运行过有限的 Bun bundle、Prettier 检查和 Python `py_compile`，违背了用户“全部实现后统一测试”的顺序要求。不能再把整个工作区描述为“从未做过任何检查”，这些有限检查也不能证明类型、行为、权限、恢复或桌面安装验收通过。下方较早轮次的“未测试/未构建”仅记录当时该轮动作；最终集中验证尚未完成，所有阶段验收仍未证明。本轮只继续实现和静态阅读，不补跑检查。

**交叉任务材料更正**：[M0 简表](M0_IMPLEMENTATION_CHECKLIST.md)、[M1～M4 计划](M1_TO_M4_IMPLEMENTATION_PLAN.md)、[实施摘要](IMPLEMENTATION_SUMMARY.md)和[完成报告](MIGRATION_COMPLETION_REPORT.md)已标为不可执行的历史草稿，完整原文保留供追溯。其伪代码、虚构阶段环境变量、周数和完成声明不扩展用户要求，也不覆盖本进度与正式决策。原固定 localhost 测试已改写为直接调用真实 Identity 模块的隔离 owner/metadata 测试，仅写入，未运行；不声称覆盖 HTTP、gateway 撤销或 SSE。

**既有用例基线**：已保存 [1300 个缓存 nodeid 原清单](../testing/PREVIOUS_PYTEST_CASES_2026-09-08.json)，来源为现有 `.pytest_cache/v/cache/nodeids`，本轮未执行收集。这是防止旧用例遗漏的对照材料，不是当前收集结果或通过报告。桌面 UI 通过后，须将实际收集用例与该清单核对并验证全部适用用例，不能仅以较小测试集通过替代。Python 原入口由 `pyproject.toml` 的 `testpaths = ["tests"]` 和 `scripts/verify_product_audit.sh` 的 `python -m pytest -q` 确定。

**复用原则（用户再次确认）**：M1～M4 不是四次重写 Agent 内核。OpenCode 已有的 `SessionPrompt`、`SessionTools`、`Provider`、`SessionRunState`、`Runner`、`BackgroundJob`、`EventV2`、文件/进程/锁和 LSP 继续作为唯一执行基础。QuantCode 新代码只在这些扩展点接入 roster 身份、组/工作区授权、预算、HumanGate、写入回执、组织索引和 legacy 兼容；不能另建模型循环、任务状态机、Provider 或事实数据库。阶段名表示接入、验证和旧入口收敛的顺序，不表示替换底层实现。

本轮复用核对：M3 新增的任务索引从原生 `SessionTable`、`MessageTable`、`PartTable` 和 `EventTable` 派生，发布器只消费已有事件并调用网关；取消使用原有 `Runner` 与 `BackgroundJob`，legacy 适配只读旧 checkpoint。没有新增 Agent 循环或独立执行状态机。

2026-09-08 用户纠正：必须按 M0 → M1 → M2 → M3 → M4 顺序推进。之前只同步了目标文档并初步定位执行链，就开始 M1 修改，没有充分完成 M0 的现状和退出条件核对。现将上述代码标记为未验收草稿，停止追加 M1 实现直到 M0 清单核对完成。该清单现已按当前源码核对，结果见 [M0 基线](RUNTIME_INTERNALIZATION_M0_BASELINE.md)。

阶段顺序不以测试延后为由改变。用户要求实现完成后统一运行测试：各阶段实施前先核对上一阶段交付的代码/契约证据，阶段状态区分“实现待验”和“验收完成”。后续阶段可在未启用路径准备迁移代码，但不能在 M1 约束未验证时启用 M2 新入口，不能在 M1~M3 未验证时实际退役旧执行器。最终集中测试发现问题时，返回对应阶段修复。

## 2026-09-08 / 已有材料与草稿

- M0 部分：目标架构、功能约束和迁移阶段已写入顶层文档；现状清单与逐项迁移映射已补在 M0 基线，不把目标文档本身当运行验收。
- 执行链定位：桌面 SDK `/session` HTTP handler → `SessionPrompt.Service` → `SessionTools.resolve` → Provider；来自 `packages/opencode`。Core SessionV2 不是当前桌面默认调用路径，不能同时另建一套新任务循环。
- M1 身份基础（已编辑，未测试）：新增 `packages/opencode/src/quantcode/identity.ts`，从宿主私有身份文件查询 gateway，验证过期、角色、组、scope，并防止查询期间身份文件替换。会话创建生成宿主绑定，metadata 更新保留绑定；会话读取/列表、子任务创建与恢复开始接入所有者校验；每轮模型执行及工具前后重新核验。MCP 定义改为会话内复制，避免包装函数污染另一会话。
- 当前不会宣称 M1 完成：全事件/原始消息/PTY/文件 API、跨成员只读 Admin 投影、旧会话只读入口、P-10/复用/Gate/预算、动态撤销、Shell 工作区约束尚需接入。

## M0 已完成静态交付（证据：M0 基线 §1~§9）

- [x] 核对顶层文档冲突：将目标架构与旧实现证据逐项分开，确认用户最新桌面/UI/模型/组绑定决策一致。
- [x] 完整调用链清单：除了 prompt/model/tool，还包含 session create/read/list、原始消息、事件订阅、文件/PTY、后台子任务、取消、compaction、恢复、Admin 与部署入口。
- [x] 旧 Runner 能力迁移表：每项组织约束的原实现、新落点、输入输出、持久化权威和绕过风险。
- [x] 数据兼容清单：原生 session、Python checkpoint、trace、Memory、Blackboard、Gate、回执、凭据及配置的保留/迁移方式。
- [x] M1~M4 交付与验收矩阵：明确阶段进入条件、禁止提前启用的开关、最终测试范围及真实外部依赖。
- [x] M1 草稿复核：判断是否复用现有机制，有没有在组织服务里又造重复状态机；复核完成前不继续扩展该草稿。

## 后续实现（保持全部原始目标）

1. M1：确定性任务分类、目录/Memory 先查、缺口用户决定、SolutionDoc 冻结和文件面准入；为原生工具/MCP/子任务统一执行这些规则；精确 Gate、预算树和副作用回执；保护 raw message/events/PTY 访问及取消。
2. M2：QuantCode 统一输入/模型执行，移除首页/slash/组 Skill 的 run_agent 强制转交；Python 组织服务以单次工具调用工作，新目录不暴露旧通用 loop。模型专用服务不能偷用另一份 key。
3. M3：原生消息和工具事件直接映射 Activity/任务树/方案/Admin；建立跨成员任务授权索引；恢复/停止复用执行器；旧 checkpoint 标记 legacy 并提供受限兼容，拒绝创建新任务。
4. M4：退役旧任务循环入口、清理产品与内部接口命名、补迁移路径并维护许可来源；统一构建发布，保留稳定的第三方协议兼容。
5. 全部实现后：先核验桌面 UI（无手机任务），通过后再运行全套用例（包括此前 1200 多项用例）、真实模型与组件链路、身份撤销/跨成员权限/旧任务回放/取消场景及打包检查；逐条审计七项验收标准及 M1~M4 退出条件。现有通过数量仅是历史范围，须对照实际用例清单确认全部覆盖，不能用 README badge 或一次较小测试集代替。

## 不允许缩减的检查

- 不能仅删提示词就宣称统一执行；必须先移入组织约束。
- 不能仅凭本机 Admin 会话或 fixture 全绿代替跨成员验收。
- 不能将不同运行目录的过滤视图称为全组织索引。
- 不修改现有秘密凭据；不重启用户已有应用/服务器。
- 既有未提交的 UI/GitGraph/GitHub 接入改动全部保留。

本阶段未运行任何测试、类型检查或构建，遵守用户的最终统一验证要求。

本轮补充：M0 确认 `/api` 原生 V2、SSE/global event、原始消息和 PTY 都是可达旁路；`runner/runtime_governance.py` 草稿与现有 SolutionStore/回执存储重叠，不进入正式调用链。M1 先纠正这两项，再继续接线。未运行测试。

## M1 本轮实现增量（未启用、未测试）

- 已按 M0 复核结论删除本任务此前新增但未接线的 `runner/runtime_governance.py`，不删除原有 SolutionStore、权限、evidence 或回执实现。
- `QuantCodeIdentity.enabled()` 需要宿主环境 `OPENCODE_CHANNEL=quantcode` 与 `QUANTCODE_UNIFIED_RUNTIME=1` 同时满足；没有设置或修改运行进程的环境开关。产品 channel 本身不再激活未完成迁移。
- `quantcode/access.ts` 基于原生 SessionTable 做授权检查，避免在权限/事件代码里依赖 Session 服务形成循环；状态、问题与权限请求列表按 owner 过滤，回复核验实际 pending 请求所属 session。
- 原始单消息、diff、取消入口补 owner 检查；公开 updatePart 不得伪造 assistant/tool/usage 结果；session 路径上的 permissionRespond 校验 permission 与 session 是否匹配；删除助手执行记录不作为普通消息编辑能力开放。
- 身份文件读取改为打开文件描述符后 stat/read，核对读取前后及最终路径 inode/时间，拒绝符号链接或读取期间替换。Windows 文件 ACL 仍需最终平台验证，不能根据 POSIX 模式位宣称 Windows 私有性已证明。
- 后续 M1：事件与 V2 旁路、FS/PTY/shell 工作区执行隔离、任务与方案绑定、原有回执适配、树预算、执行中撤销与取消。还未切换首页、slash 或停用旧执行器。

上述均是源码实现进展，不是行为通过；按用户要求尚未运行测试、类型检查或构建。

## M1 第二轮：事件与执行期间身份（实现待验）

本轮前序分类：上一轮为 progress（完成 M0 基线并修改了 M1 接入代码），不是等待或无进展。继续 M1，未进入 M2。

- 新增 `quantcode/event-access.ts`：按订阅建立时的 gateway session 固定身份，逐事件重新验证；只从协议字段提取 sessionID，按 SessionTable owner 过滤。登录改变使订阅失败关闭；未登录仅保留无私有载荷的连接/心跳。删除事件在行已删除时只使用可信事件中的原 binding。
- `/event` 与 `/global/event` 接入同一规则，后者也检查 sync envelope 的原始事件；另一套 Core `session.next.*` 事件不混入当前执行链。文件/项目/PTY 等非 session 事件暂不放行，后续需要工作区 ACL 后恢复授权事件，而不是为 UI 刷新放开全局广播。
- 迁移模式下 `/sync/replay`、`/sync/steal` 拒绝客户端注入/接管执行记录；`/sync/history` 按当前 owner 过滤，`/sync/start` 不启动旧 workspace replay 机制。组织跨成员索引和显式历史导入另走可信服务。
- 新增全局路由策略 `quantcode-runtime.ts`：迁移模式阻止 `/api` Core V2 路径成为另一套未接组织规则的执行/数据入口。现有桌面调用链使用 `/session` 等已选路径；未来需要 V2 协议时必须有显式兼容方案，不能暗中启用第二引擎。
- `SessionRunState` 复用原有 Runner 取消机制，以 watchdog 定期检查登录 session，撤销/更换后中断现有工作并取消后台子任务；不创建第二执行状态机。检查间隔 2 秒，gateway 请求仍受其超时约束，不能宣称即时撤销。实际进程终止与异常回执将在最终测试证明。
- Permission/Question 服务层补所有者检查，覆盖直接服务调用而不仅是 HTTP handler。pending 请求记录发起时的登录 session；重新登录不能处理旧 pending。原生“always”权限缓存限定在 gateway session + native session，不跨账号或任务复用。组织精确 HumanGate 尚需后续专门接入，不能把该原生缓存当作共享写入授权。
- `visibleSessions` 对大批 ID 分块查询，忽略非 session aggregate，读取完成后核验身份未切换。

仍未完成：FS/PTY/Shell 实际隔离和授权事件，方案/目录/Memory/缺口决定，树预算与统一模型辅助请求，精确 Gate/回执，legacy 历史入口以及跨成员组织服务。所有改动仍在 `QUANTCODE_UNIFIED_RUNTIME` 宿主开关之后，默认未启用；未运行测试、类型检查、构建或切换已有服务。

## M1 第三轮：工作目录授权基础（实现待验）

- 新增 `quantcode/workspace.ts`：区分 roster 的远程个人目录和本机 checkout 映射。目录请求、最近项目和工具参数本身不授予权限；映射按 actor/group/workspace_id 绑定，包含 read/write 级别。默认配置位置为 QuantCode 宿主配置目录 `workspaces.json`，可由宿主 `QUANTCODE_WORKSPACES_FILE` 指定私有文件。尚未写入任何真实成员映射，也未启用迁移。
- 可存在的 roster 个人目录可在该宿主读取使用；不存在的远程路径不冒充本机路径。实际目标解析符号链接及尚未创建文件的已有祖先，拒绝逃出授权根、悬空符号链接和权限读取失败。
- 普通文件面排除 SSH、QuantCode 凭据/状态、组织 roster 等控制路径；该检查尚不是任意 Shell 程序的 OS 隔离，不能把它用于宣称 Shell 已满足方案文件面限制。
- 原生 session 创建先验证工作目录授权；子任务不得改变父任务目录。原生 external-directory 工具检查在 bypass 参数之前执行；edit/write/apply_patch 要求 write 级别授权，包含移动目标。
- 文件浏览/content/find 接入授权与结果前重验，列表过滤越界或受保护目标。文本搜索当前仍由已有 Ripgrep 执行后过滤返回结果；执行前秘密文件排除和竞态读取保护仍待完善，不能把返回值过滤当作进程级隔离。
- 提取 `private-file.ts` 供身份文件与宿主映射共用文件描述符读取，避免复制私有文件校验逻辑；未改变真实配置或凭据。

后续按 M1 清单继续：可信工作区登记入口（不接受模型自注册）、文件读取竞态/搜索隔离、PTY 身份归属与实际进程沙箱、Shell/格式化器等子进程隔离、方案/Gate/回执/预算。之后才能按顺序开始 M2。未运行测试、类型检查或构建。

本轮追加：文件 content 在迁移模式下通过已校验描述符读取，读后比较 inode/设备/长度/mtime/ctime 及 canonical 路径，再重验身份，防止检查后重开路径。保留文本原有空白而非 trim。file/find/pty 的实例中间件在加载项目配置前校验请求目录授权；此处只是入口工作区检查，不代表 PTY 已具备进程隔离。全套测试继续延后。

## M1 第四轮：PTY 进程隔离与登录归属（实现待验）

上一轮为 progress；本轮继续 M1，未进入 M2。

- 新增 `quantcode/process-sandbox.ts`，准备 OS 层 launch：macOS 使用系统 sandbox-exec 配置；Linux 使用 bubblewrap 的独立 namespace、只读运行库/工作区、显式 writable mounts、私有 scratch 和隔离网络。宿主环境通过 env -i 清空，不传递模型/GitHub/SSH 密钥。拒绝无法隔离的宿主，不回落无限制运行。
- writePaths 必须来自可信调用侧，空列表只允许 scratch 写入。Linux 对尚不存在的精确文件不扩大父目录挂载权限，要求先由受控文件工具创建；原生文件写入与 Shell 方案准入仍需后续统一接入。
- 该 OS launch 现接到手动 PTY 创建：只接受 Shell 选择器支持的系统 shell；用户传入 env 不再透传；每个终端关联认证工作区和创建登录。普通终端允许授权个人工作区写入；Agent Shell 的 file_impact 隔离尚未接完，不能把手动 PTY 授权解释成 Agent 的共享写权限。
- 新增 `terminal-access.ts`，仅附加 Core Pty 既有进程生命周期的 owner/grant，不拥有第二任务调度器。终端 list/get/update/remove、ticket 与 WebSocket 收发都按登录和目录校验；登录失效周期检查会移除既有 PTY，关闭后清理 scratch。退出进程也清理附件映射。
- sandbox 对 .git 只读，以防止修改 hook/config 后令宿主绕过隔离；普通文件/组织工具仍承担真正 git 写操作的专门准入。网络默认隔离，不能宣称终端内任意联网已支持。
- **待完成平台边界**：Windows OS 级进程隔离与 ACL 尚未实现；macOS/Linux profile、进程树终止、符号链接竞态和依赖运行需求均尚未实测。当前不能宣布跨平台 terminal 已完成。

所有变更仍位于默认关闭的统一执行迁移开关之后。未运行测试/类型检查/构建，未重启或更改用户已有服务；后续须完成 M1 其他约束再按顺序前进。

本轮追加：PTY 事件恢复为按创建登录/工作区映射核验的定向事件，而不是恢复全局广播；WebSocket 输入实际写入之前也加入异步身份检查。PTY 目录以创建请求所处的路由目录绑定，允许进程 cwd 位于其授权子目录，避免将 cwd 与路由混为一谈。后续最终测试需检查 created/deleted 事件与生命周期清理的时序。

## M1 第五轮：复用 SolutionStore 的宿主适配（实现待验）

- 新增 `quantcode/solution_host.py`：不调用模型或 Runner，复用已有 SolutionStore/Blackboard、SolutionDoc、task_classifier 与 evidence；存储放在宿主私有组织服务目录，按当前 owner 与 native session 分区。没有新建 runtime_policy/reviews/operations 表。
- native session 的用户需求决定方案绑定 ID；方案修改要求期望版本/hash，修改后重新进入 draft。file_impact 使用明确相对文件路径，拒绝通配符、越界与控制/凭据路径。
- `solution_workflow.review_solution` 是新的可信 UI 复核入口：核对精确 draft 版本/hash，记录真实用户反馈和 required evidence 后保存 frozen/superseded；不伪造多轮讨论。旧 freeze_solution 与 Python 工具保持兼容行为。
- 新增宿主 `quantcode/solution.ts`：先验证原生任务 owner，读取 native 用户消息，执行固定 Python 程序进行单次组织服务请求；清空不必要环境，不传模型 key。新增 solution status/propose/review HTTP 声明与 handler，只有迁移模式启用，review 不注册到模型目录。
- **尚未作为执行授权依据**：当前 taskContext 从压缩后的用户消息投影取需求。正式接工具前必须将需求版本锚定到不可修改的 native admission/event 记录，避免删除/编辑/压缩消息导致方案降级或更换绑定；父任务约束、目录检索证据与缺口决定也需接入。不因上述服务代码存在就切 M2。
- SDK 声明生成、UI 的方案查看/确认/错误展示在 M1 后续实现中统一补齐；本轮没有生成安装包或运行测试。方案服务在当前真实部署中尚未启用。

本轮追加：方案需求来源已改为原生 EventTable 的首次 user message/part 事件，按已存在的 durable 序列派生，避免 message edit/delete 或 compaction 抹去原始需求；不另建消息事实表。公开 sync replay 已由前一轮禁用。后续仍需覆盖文件附件需求、父任务 scope 和写调用的分类升级，不能仅靠这份文本派生视图完成 M1 准入。

## M1 第六轮：原生编辑/Shell 的方案准入（实现待验）

- 新增 `quantcode/write-policy.ts`：通过现有 native session binding 沿父任务链读取同一个 SolutionStore 服务，校验每层 owner/root/directory；原生 write/edit/apply_patch 从实际参数及 Patch parser 获取文件目标，不接受模型自报“已检查/只读”。
- 根任务及子任务共享进程内写锁，持有至工具执行结束。已准入文件由现有 native tool-progress durable events 派生；累计多文件操作传入现有分类器加强 L2 要求，不新增运行状态数据库。
- L2/L3 或已有草稿/废弃方案时拒绝写入；frozen 方案校验全部实际文件与祖先 file_impact。native permission 等待结束后重读方案，变更摘要使操作拒绝。仍需后续解决跨进程方案 review 与写执行的完整串行化及 unknown-outcome 回执。
- 原生工具包装处接入 write-policy，覆盖常规会话与直接 Tool.execute 路径；Database 依赖由工具构建时捕获。ShellTool 的进程启动使用前轮 OS sandbox，传入当前/父方案文件范围交集；没有 frozen 范围时只允许 scratch 写入，不扩大整个工作区。直接 SessionPrompt.shellImpl、slash shell 插值和格式化器等旁路尚需同样处理。
- 新增 native `organization_solution` 工具（仅迁移开关启用后可见）：status/propose 两个动作，复用宿主方案服务。没有 confirm/freeze/review 的模型参数或工具动作；可信用户复核只走专用 HTTP 路径。
- **未完成并保持为阻断项**：能力目录/Memory 成功检索证据与缺口用户决定尚未加到该准入；MCP trusted manifest 与 effects、父预算、精确 HumanGate、跨进程回执以及 Windows 隔离仍未实现。这里的方案检查不能被误报成 M1 全部完成。

本轮只做源码实现，没有测试、类型检查、构建或服务重启。M2 新任务入口保持原状，迁移开关保持默认关闭。

## M1 第七轮：直接 Shell、模板命令与宿主配置边界（实现待验）

上一轮为 progress；本轮继续 M1，未进入 M2。

- 原生 ToolRegistry.named 暴露同一个已构建 ShellTool，SessionPrompt.shellImpl 在迁移模式下直接复用它，不再另外构造未隔离的 ChildProcess。用户直接命令写入原生 user 文本事件，供原有方案需求派生；权限/方案/沙箱和结果 metadata 与模型 Shell 相同。
- 命令失败/中断在原生 shell tool part 标为 error，不再将失败结果标为 completed；没有另外建立任务或循环。模板命令插值在任务模型调用前只允许 OS 只读 sandbox，输出最多 100 KB、15 秒超时，非零退出不能伪装成有效上下文；身份与工作区在读取前后重新验证。
- 新增 `config-policy.ts`：迁移模式下桌面配置更新只接受 OpenAI-compatible URL、模型名和模型启停设置，拒绝 plugin/shell/MCP/permission 路径修改、宿主 env/file 插值。身份必须有效；Admin 产品角色也不等于宿主启动命令修改权限。
- MCP add 在迁移模式下禁用，连接/认证/断开原有维护员配置的 MCP 需重新认证。普通工作区文件访问将 .opencode 与 opencode 配置路径归为控制数据，避免通过改写配置文件间接越过 HTTP 配置限制。
- 仍需后续实现：MCP tool effect/能力发布元数据的可信目录、目录/Memory 检索证明、缺口决定、精确 Gate、跨进程回执/方案并发、预算树；格式化/LSP/插件加载等宿主子进程仍须逐一核对，不因 ShellTool 已隔离就宣称所有子进程安全。

当前源码实现尚未运行测试、类型检查或构建，且迁移开关未启用。用户已有服务未重启，新任务首页与 legacy 恢复入口仍未切换。

## M1 第八轮：维护员 MCP 发布目录（实现待验）

上一轮为 progress；继续 M1，未进入 M2。

- 新增 `quantcode/tool-catalog.ts`：私有宿主发布文件包含 release、服务名/原工具名、服务配置与 input schema 摘要、effect、组/角色/scopes、实际文件参数 JSON pointers 和 published/disabled。远端 readOnly 注解和命名前缀不作为授权事实；重复定义或缺失写入文件参数拒绝加载。
- MCP.tools 仅投放当前身份匹配且摘要一致的已发布工具；模型看不到 production/legacy_executor 类别。原始工具对象的来源通过 WeakMap 由宿主 transport 构造器绑定，不信任模型或插件附加的 JSON 元数据；规范化名称冲突拒绝覆盖。
- 每个工具来源捕获 transport、有效配置与 schema，执行时确认连接及声明未变；调用前后重新读取发布目录。personal_write 进入同一方案文件范围检查，共享写入/跨组受限作用仍等精确 Gate 接入，不由 ctx.ask 泛授权。
- MCP.callTool 的直接宿主路径没有 native plan/receipt 上下文，因此只允许已发布 read 类别；写操作须走原生任务或专门管理入口，不能绕过模型工具 wrapper 调用。此限制不影响开关关闭时的旧运行链。
- 显式将自定义目录路径列入私有控制文件，普通 workspace 工具不能读写发布权限。当前尚未发布真实 tool-catalog.json，不能把此实现描述为生产工具已全部可用。

后续 M1 必须完成维护员目录发布/回滚流程、实际组织工具逐项声明、可信检索证据与覆盖缺口决定、Gate/回执/预算，以及资源/插件旁路；再开始 M2。没有运行测试、类型检查或构建，没有启用迁移或重启服务。

本轮追加：新增仅供宿主维护员使用的 `script/publish-quantcode-tools.ts`，在预期当前摘要匹配时原子发布经过人工审查的 manifest，归档不可覆盖的按内容哈希版本，并支持回滚。发布锁遇到异常残留时要求维护员核对，不自动删除他人锁；CLI 只打印发布元数据，不打印服务配置或密钥。没有注册浏览器/模型调用入口；尚未实际运行发布操作或安装真实目录，最终验证阶段需覆盖并发/断电/回滚。

## M1 第九轮：真实检索回执与能力缺口决定（实现待验）

- 复核用户要求的阶段顺序，在本文顶部明确 M0～M4 的真实状态；PRD §8.3 将旧产品路线 M1～M5 与本次内化阶段分开，保留旧能力目标但不将其作为迁移完成证据。M1 尚未闭环，M2～M4 未开始。
- 新增 browser-safe `quantcode-governance` 契约：目录/Memory inspection、coverage proposal 和用户 review 都发布到既有原生 durable session 事件，不建立第二个执行数据库。共享过渡事件纳入统一 manifest。
- 提取 `intent.ts` 供 Solution 与 reuse 共用不可编辑的原始用户事件需求。MCP 检索开始时固定任务和登录摘要；调用结果返回、身份和目录重验后，在 plugin after/text formatting 前读取结构化结果。失败、无效结构及重复能力 ID 不产生有效检索回执；检索期间任务或身份变化使结果失效。
- 私有工具目录加入审核用途与可选 capability_id；发布和加载均拒绝将写入工具作为检索证据。旧回执随目录撤回、版本/权限变化或登录变更失效；新检索回执也使先前覆盖方案与决定失效。
- `organization_reuse` 原生工具只允许 status/propose，不能批准。full 只能引用真实目录中的 CONNECTED 组件，自动覆盖只适用于对应的已发布 capability_id；原生自定义写入和部分/无覆盖必须取得用户决定。能力检查接入原生 write/edit/apply_patch、可写 Shell、MCP personal_write 的现有方案边界，并沿父任务链检查；无写范围的 Shell 不要求覆盖批准。
- 新增类型化 `/experimental/quantcode/session/:sessionID/reuse` 与 `/reuse/review` 接口，公开视图不返回身份凭据或原始需求。用户决定绑定唯一 proposal hash，事件回放以第一个有效决定为准，冲突请求不能覆盖；模型目录没有 review 动作。
- **仍未形成完整交付**：桌面检索/覆盖决定 UI、SDK 生成、真实工具 manifest 发布、方案/覆盖与实际执行的跨进程同步、精确 HumanGate、unknown-outcome 回执、预算及辅助模型请求、资源/插件/格式化/LSP 旁路、Windows 隔离与工作区登记仍需完成。目录检索响应必须与实际服务逐项对齐；不能以接口或事件存在宣称真实任务已通过。

本轮仅实现和静态阅读，未运行测试、类型检查或构建；没有切换迁移开关、重启服务或退役旧循环。下一步仍在 M1 补齐缺口，不能进入 M2。

## M1 第十轮：桌面方案与能力决定接线（实现待验）

- 上一轮为实际进展，本轮继续 M1。新增 `task-review.tsx/css`：原生任务标题下显示可展开的方案与能力复用区域，现有 QuantCode 工作区的方案页复用同一组件。目标、文件范围、验收要求、讨论记录和能力缺口均来自当前任务的宿主接口；旧任务仍使用原有历史面板。
- 用户确认直接提交精确文档 version/hash 或唯一 coverage proposal hash，不发送批准提示词、不调用第二个 Agent。完整覆盖组件的直接复用不显示为必须等待审批；新增实现的处理决定仍单独展示。
- 表单提供保存中、成功、失败和刷新状态；请求随服务器/任务切换取消，迟到响应丢弃；文档变化清空旧意见并重新确认。两个决定共用提交互斥，读取失败清空可操作数据。原生事件更新及定时/窗口聚焦刷新用于读取其他窗口的修改，不另建任务状态机。
- 新增 `quantcode.solution.changed` 原生事件。SolutionStore 仍是方案服务事实源，Python 保留确定性文档处理；宿主在调用前后核对当前任务及登录。服务端与浏览器共用 SolutionState wire projection，取代宿主原有独立 Zod 响应定义。
- SDK 通过仓库生成器重新生成，未手改生成源码。生成脚本增加 `--generate-only`，跳过删除 dist 和 tsc 构建步骤，供本次先实现后统一验证使用。源码生成成功不是行为/类型/打包验收；本轮未运行测试、类型检查、性能基线、构建或视觉核验，未启动/重启已有服务器。
- **仍在 M1 的缺口**：确认/方案与写执行之间跨进程串行化、文件副作用回执、精确 HumanGate、预算树与辅助模型计量、资源/插件/格式化/LSP 边界、实际目录和工作区登记、Windows 隔离。方案持久化与原生事件之间的异常恢复也须纳入后续一致性处理。当前迁移开关仍默认关闭；M2～M4 未开始。

## M1 第十一轮：直接复用 OpenCode 的锁和进程管理（实现待验）

- 用户提醒成熟能力可以直接用 OpenCode/MimoCode，本轮按实际源码重新检查。采用已有 `core/util/flock.ts` 的 `Flock.effect`；删除本轮刚建、尚未接线的 Python 锁桥和通用宿主启动封装，撤回本轮对旧 Python execution_lock 的改动。保留旧 Runner 行为和历史。
- `task-lock.ts` 只负责受信任根任务键、私有目录及锁后身份重验。原生写入、可写 Shell、MCP personal_write 与方案/覆盖方案的修改和确认使用同一跨进程锁；移除原有只对一个进程有效的手写 semaphore Map。只读方案查询不取该执行锁。
- 长执行不能因心跳暂时停顿被另一个宿主抢占，因此该调用使用已有 staleMs 参数的非过期策略；为现有 Flock 补充非有限心跳间隔检查，避免 Infinity 被定时器变为 1 ms。**崩溃后的显式锁恢复和副作用回执核对仍未完成**，不能把本次锁接线当作恢复验收。
- 方案 Python 单次服务改为已有 `AppProcess.run`，复用 CrossSpawnSpawner 的退出等待、取消、超时与进程清理，删去手写 spawn/计时器/输出监听。保留固定程序、隔离环境、30 秒超时和 1 MB 输出上限；服务依赖由工具、会话与 HTTP 既有层统一提供。
- 任务忙碌和身份变化有明确 API 错误，桌面使用该错误提示；SDK 重新生成。未进行测试、类型检查、构建或服务重启，迁移未启用。M1 的 Gate、预算、回执及其他旁路仍需继续完成，M2～M4 未开始。

## M1 第十二轮：复用原生权限等待的精确审批（实现待验）

- 上一轮为实际进展，本轮继续 M1。复用 `Permission.Service` 的 pending/Deferred、事件和现有桌面 PermissionDock；没有新建 Gate 调度器或审批数据库。增加服务端专用 `askExact`，公开 metadata 或普通 ask 不能创建可信精确审批。
- 审批请求绑定 native session/message/call、当前需求及登录、工具发布版本和实际参数摘要。MCP 参数在 plugin before 之后复制，之后的准入与调用使用同一份；完整参数在既有提示框展示，超出展示上限拒绝请求，不截断后让人盲批。
- `expected_digest` 扩展现有 reply，SDK 保留原来的平铺参数兼容；旧 session permission respond 无摘要，不能放行精确请求。服务端禁止 always，忽略普通权限缓存的批量放行；桌面自动接受不响应精确请求，隐藏“始终允许”，只提交本次操作摘要。
- GateRequested/GateDecided 记入原生 durable 事件；决定先落事件再唤醒执行。回复前后、执行前后重新检查身份、任务、工具版本和取消/有效期。十分钟超时或取消清理原生提示，不把超时伪造成用户批准。同一 pending 回复互斥，普通 reject/always 不连带处理其他精确审批。
- 现接入已发布 `restricted_access` 工具：审批后通过同一根任务锁重验再调用。**当前审批仍限定任务所属登录中的 approver/admin，跨成员审批、挂起重启恢复和组织索引尚未接通。共享写入仍拒绝，须先完成副作用回执和完整方案/Gate 组合后才能放行。** 没有部署真实目录，也没有启用迁移。
- 增加桌面自动接受不能绕过精确审批的回归用例，按用户要求仅写入，未执行。SDK 已重新生成；未运行测试、类型检查、构建或桌面视觉验证。M1 未完成，M2～M4 未开始。

## M1 第十三轮：原生写入回执与人工核对（实现待验）

- 上一轮为实际进展，本轮继续 M1。检查现有 Python `tool_receipts.py/receipt_reconciliation.py` 与原生工具事件，沿用“执行前 STARTED、完整结果后 COMPLETED、缺结果不得自动重试”的规则；原生记录直接写入已有 EventTable，没有复制 Python checkpoint 或另建回执数据库。
- 新增 WriteStarted/WriteCompleted/WriteReconciled 契约与 `write-receipt.ts`。记录与工具调用的 session/message/call、实际参数、身份、文件范围、方案及目录版本摘要绑定；完成结果校验摘要，相同调用读取原记录。任一子任务存在未核实的开始记录时，根任务下其他写入拒绝。公开 raw message metadata 不再作为累计文件范围的权威来源。
- 原生 write/edit/apply_patch 的开始记录在现有 edit permission 成功和方案重验之后写入；拒绝权限不会产生写入开始回执。可写 Shell、MCP personal_write 在调用前记录。Shell 失败、取消或超时可能已部分写入，保留未确认回执；只读 Shell 不产生写入回执。完成记录在当前登录撤回时仍保存原操作结果，再拒绝向新身份释放结果。
- QuantCode 统一迁移模式的已有 SQLite 数据库改用 WAL synchronous FULL，避免电源故障丢失已确认的开始记录；旧模式保持原配置。该改动尚未经断电/崩溃验证。
- 新增宿主状态/核对接口，复用既有 confirmed_completed/confirmed_not_executed 决策词汇；核对要求审批员/Admin、准确原摘要、证据位置和说明。完成需保存验证后的原始结果；未执行关闭原调用，不自动重试，新调用仍重新校验权限和方案。模型没有核对工具。
- 桌面任务方案中显示未完成回执及核对表单，区分“仍执行中，请等待”与“执行停止后需核对”，沿用当前组件和样式；通过生成器更新 SDK。
- **尚未完成**：崩溃残留根锁的受控恢复、损坏完成记录的恢复、跨成员核对和审批、共享写入完整接线、预算及其他执行旁路。原生与宿主进程终止和回执一致性仍待最终验证；不能据此标 M1 完成。未运行测试、类型检查、构建或重启服务，M2～M4 未开始。

## M1 第十四轮：格式化与项目扩展加载边界（实现待验）

- 上一轮为实际进展，本轮继续 M1。逐项读取 Formatter、Plugin、ToolRegistry、Config 和 LSP 路径，确认 Shell 之外还有格式化子进程、探测命令、自动 npm 安装及 in-process 项目扩展入口。
- 保留已有格式化器列表、文件扩展名选择、配置与调用流程；为 Formatter.Context 加入可选受控探测/已安装二进制解析。统一迁移模式的 prettier/oxfmt/biome 不再通过 Npm.which 自动安装，air/uv 探测在只读沙箱运行。旧模式原行为不变。
- Format.file 接收 native session ID，通过同一方案与工作区检查确定当前文件；格式化用现有 AppProcess 和已有 OS sandbox，仅授予本次文件写范围，清空宿主环境并设置超时。write/edit/apply_patch 传递原任务 ID，格式化失败不标成功，已有写入回执保持未确认。
- 统一迁移模式不加载原有供应商认证插件、第三方 in-process hooks 或项目 tool/*.ts；配置加载也不启动插件依赖安装、不自动补写项目配置 schema/gitignore。组织能力继续走已发布 MCP 准入。第三方 in-process 扩展在新模式中尚无受控发布接入，不能声称插件兼容已验收。
- 项目 opencode JSON 不覆盖宿主统一模型/执行配置；宿主显式 OPENCODE_CONFIG/CONFIG_DIR 仍作为维护员入口。Markdown 命令/Agent 内容仍保留既有加载机制，执行权限不由这些内容授予。
- **仍未完成**：LSP 已定位到安装器、旧 Process.spawn、常驻 client 与返回路径，尚未改造；不得因格式化器已接沙箱就视为辅助进程全部受控。格式化器的真实依赖路径、原子替换文件行为、撤销期间进程清理和跨平台 profile 仍需最终验证。未运行测试/类型检查/构建或重启服务，M1 未完成，M2～M4 未开始。

## M1 第十五轮：LSP、预算、宿主登记与故障恢复（实现待验）

上一轮为实际进展。按当前协作指令将互不重叠的 M1 实现并行处理，未跳过阶段、未运行测试或重启服务。

- **LSP**：保留原 adapter、JSON-RPC、诊断和 client 生命周期；启动/探测通过当前授权工作区和现有沙箱，禁用自动下载，TypeScript/Biome 查找已安装工具。客户端记录原 grant，异步初始化后、复用前、请求和结果返回前重验；身份变化清退客户端和缓存，进程清理复用 Core Shell.killTree。新增治理模块只传授权上下文，不另建语言服务注册表。真实启动、旧缓存目录、迟到响应及进程树终止仍待验。
- **预算**：主/子会话共用根任务原生事件中的策略、预留、实际结算和未知用量。所有真实模型请求在既有 LLM 入口准入，覆盖标题与压缩；复用原 getUsage 计算并抽出纯 usage 模块。禁用受控调用下面的隐藏 HTTP/SDK 重试；身份变化和已确认耗尽取消请求。自定义模型复用现有默认输出上限，不新增第二份模型配置。输入预留是保守估计，不宣称任意兼容 API 的账单硬上限。
- **预算核对**：只对已结束或原本机进程已消失的请求开放证据核对，需审批员/Admin、请求摘要、停止确认、实际回执或明确未执行证明。没有有效用量回执不归零。预算锁恢复独立于用量核对，解除锁不返还预留。状态/check/核对/恢复均接宿主接口，桌面显示实际与预留并提供核对表单；工具准入也检查已确认耗尽。
- **执行锁与回执恢复**：在现有 Flock 增加 inspect/recover，核对准确 token/owner、本机进程确已死亡、当前证据记录后才退役旧锁；不按时间抢占，也不向进程发送终止信号。恢复进程自身异常退出留下的恢复互斥锁也按相同死亡证明逐层处理。子进程停止仍需真实人工证据；没有冒充自动证明。损坏的完成回执仅允许恢复原结果，不允许转为未执行；核对绑定当前回执内容摘要，保留旧事件。
- **宿主登记与目录发布**：新增 host-only workspace grant/revoke/status CLI，实时 roster 决定收件身份，校验 canonical 路径、所有者、权限和预期配置摘要。发布/回滚复用 Flock、私有文件检查、版本归档和原子替换。19 项工具有 source hash 与 effect 审核，其中 9 项为 published 候选、10 项 disabled；真实 wire schema 由现有 registry/converter 导出，尚未运行导出或发布。
- **控制文件**：保护自定义目录配置的整个父目录，以及固定 Python 服务所用的整个 QUANTCODE_BACKEND_ROOT。可信服务安装根与研究 checkout 必须分离；普通工具不能通过改写动态导入的宿主 Python 源码取得宿主执行。已有多硬链接文件禁止原地写入。符号链接时序竞争仍在独立收尾，不能用此检查代替实际写隔离。
- **平台范围复核**：内化决策、FUNCTIONAL_SPEC、PRD 和技术设计没有逐 Windows/macOS/Linux 的明确交付条款，早先记录的 Windows ACL 是实现风险而不是新增用户目标。当前无 ACL/sandbox 证明的平台明确拒绝相应操作；实际桌面构建目标和安装检查仍按原目标验收，不能宣称跨平台已验证。

仍未关闭 M1：原生文件写入竞态、共享写入真实工具的准确去重/参数契约、跨成员审批、目录/运行依赖的真实部署、全部旁路的最终复核。SDK nullable 兼容转换缺陷正在修复；所有上述代码及桌面交互均未测试，M2～M4 未开始。

本轮收尾补充（实现与源码生成，不是运行验收）：

- 原生文件 helper 已接线到 write/edit/apply_patch 的预览、写入/移动/删除及 BOM 二次写。固定标准库 Python 程序通过 dir_fd + O_NOFOLLOW 逐段打开目录，核对根 inode，独占创建新文件，使用新 inode 替换已存在文件，避免经调换链接就地截断外部 inode。复用既有 AppProcess、方案和回执，不新增执行状态机。取消信号贯穿文件操作、格式化，工具准入和编辑确认后也检查已取消状态。
- 文件 helper 提交前核对快照；这不是针对不合作外部编辑器的原子 CAS，也不是多文件事务。多文件中途失败保持未确认回执；单文件 32 MiB、平台 dir_fd 支持、ACL/xattr 与临时文件清理仍需最终边界验证。没有据此声称文件系统所有并发语义都已证明。
- OpenAPI 兼容转换原先无差别删除 null 分支。现有 Effect 依赖补丁新增可选择的 Undefined 来源标记，仅在 QuantCode PublicApi 生成时启用；兼容层只删除 Undefined 的近似分支，保留真正的 NullOr。修改已写入仓库 patchedDependencies 所引用的补丁，未升级依赖。SDK 由生成器重新生成，实际输出 budget token_limit/remaining 为 number | null。干净依赖安装重放及全面协议兼容仍待验证。
- 桌面预算与写回执核对、两类残留锁恢复均已接宿主接口。表单版本变化清空旧说明，未停止的请求不开放用量核对；折叠任务面板由事件刷新，只有展开时周期查询。该界面尚未进行视觉/交互测试。
- 全部并行子任务已回报本轮代码交付；没有发布真实 manifest、写入真实 workspace grants、修改运行凭据、启用迁移或重启现有服务。仍继续 M1，下一步需完成共享写入真实链路与跨成员审批等剩余项，再按顺序推进 M2～M4。

## M1 第十六轮：共享写入、跨成员审批与读取准入（实现待验）

上一轮为实际进展，本轮继续 M1，按互不重叠文件并行实现。仍无测试/类型检查/构建或运行服务切换。

- **跨成员 Gate**：gateway 新增 native-gates publish/read/list/decide/cancel，复用 roster、HumanGate、AuditEvent；请求绑定原登录、root/session/message/call、工具来源、目录版本、精确参数原文摘要、资源及预期版本。网关同事务保存授权投影与证据，读取时重验请求者和决定者当前权限，只有同组审批员/Admin 能批准。网关不持有任务循环；原生 Permission 服务继续等待、记录 durable 决定、重新校验并唤醒原工具。
- **原生审批接线**：Permission.askExact 发布宿主请求并等远端决定；不暴露浏览器 publish 接口或 Bearer。原任务取消/超时撤销投影；研究员任务内拒绝走 owner cancel，不调用审批员决定接口。参数大小和登录到期约束在发布前核对。桌面既有审批页新增原生队列，完整显示申请人、参数、资源、版本，审批说明随精确 request digest 提交。SDK 已从声明重新生成。
- **共享工具执行**：MCP transport 通过 WeakMap 接收宿主创建的 `_meta.quantcode`，模型 args 不能生成身份/批准。Python 验证参数字节摘要、原生调用标识与当前 gateway 登录；native 调用不创建 Python 模型。shared_write 在冻结方案、能力复用检查、精确 merge Gate 和现有根任务锁/回执之后调用；工具目录新增精确资源/版本契约。
- **Blackboard**：复用既有 put/write_value 的 SQLite 事务，新增可选 expected_version CAS 和锁内审批重验回调。native writer 仅支持规范 shared.model_entries.*，绕开旧300秒不准确去重，读取返回同一显式共享库的真实版本。必须配置私有 QUANTCODE_SHARED_BLACKBOARD_DB，缺少或未初始化则拒绝，不以个人目录空库假装共享。普通工具保护该库整个父目录及WAL/SHM；旧legacy调用保持原语义。
- **目录审核**：当前20项，9项可作为published候选、11项disabled，共享读写仍disabled等待真实组织服务配置和最终测试。实读并更新本轮相关源码后42个source pins无静态漂移；没有执行导出器、发布器或真实登记命令。
- **读取与事件**：原生read正文/图片/PDF复用授权稳定句柄；glob/grep和HTTP find复用Core Ripgrep解析，扫描本身先隔离，内容/路径返回再检查。事件恢复按可信来源目录授权的file/LSP/VCS/worktree/project通知；session仍按owner过滤。MCP资源、资源模板和prompt有独立的精确selector发布声明，发现和实际读取使用同一有效权限、固定client/config并在返回前重验。
- **上下文/附件**：宿主显式instructions与工作区Markdown分开；host公开文件使用稳定读取且不能被其他组写入；HTTP上下文只接受宿主配置HTTPS来源。@路径在stat前授权，本地附件通过同一ReadTool读取后保存内容，拒绝任意远程附件URL，批次返回重验原身份。Skill和Reference的独立自动下载/读取调用正在收尾，不把最终过滤误当作进程或目录授权。

M1 仍未验收。真实共享宿主、真实published工具声明、批准后撤销/取消/重启恢复的全链路场景，以及剩余入口的静态闭环仍需完成；最终统一验证还没有开始。M2～M4 未开始。

本轮收尾：Skill 服务在迁移模式按当前身份即时读取授权工作区和当前组宿主公开Markdown，禁用自动下载；Skill工具的附带文档只能在对应Skill内读取。Reference在调用Core自动clone之前改为检查宿主明确的本地配置与工作区授权。ReadTool回到已治理的instruction.resolve，删去重复加载实现。Config不再扫描项目Command/Agent Markdown作为宿主执行配置，保留明确宿主配置。

静态审查发现下一批仍可达入口，须继续 M1 处理，不能以该轮完成作为阶段退出：`command/index.ts` 长期缓存的Skill/MCP内容还需绑定原登录并刷新；Project bootstrap 的VCS/Snapshot/Project/ShareNext初始化，以及Project/Instance HTTP元数据、Git/VCS写接口需统一核验。真实目录/共享数据库尚未安装发布；所有runtime代码、依赖补丁重放、SDK兼容和桌面交互仍待全部实现后的统一测试。

## M1 第十七轮：Command、Project/Git、Snapshot 与阶段源码核对

上一轮为实际进展。本轮补齐上列静态入口后形成 [M1 源码交付核对表](RUNTIME_INTERNALIZATION_M1_IMPLEMENTATION.md)。该状态只允许依次准备未启用的 M2 源码，不代表 M1 行为已通过。

- Command 按当前登录刷新现有投影；懒模板消费前后重验。MCP instructions 按发布目录过滤，禁止保留已撤回工具说明。只读Shell不再要求不必要的写权限。
- 实例中间件在任何研究项目加载前检查目录，登录/模型/组织控制有独立宿主上下文，不需要先打开研究仓库。InstanceStore 的缓存投影重验当前授权，输入的旧project/worktree对象不绕过native resolver。项目列表/目录映射过滤授权，仓库内缓存ID不迁移他人会话，普通外观接口不能改启动脚本。
- Project 发现复用 Core resolver，但Git进程和FS向上搜索分别限制在当前授权工作区；Git根仍保留给相对路径/diff使用。新仓库初始化经固定文件操作独占创建.git和受控Git空模板初始化。非当前部署的workspace参数不再启动远程代理。
- VCS查询和快照接入同一边界；快照按owner/workspace保存私有Git树，读取源字节后写objects，恢复走原生方案、回执和binary mutator。ShareNext停止上游自动共享。旧worktree自动创建/重置/删除及未绑定任务的裸VCS写接口明确拒绝；不声称这些旧接口具有新的组织兼容能力。
- 复用原循环检测阈值，跨模型轮次识别同一真实请求的重复工具调用；检测结果为停止状态，不走HumanGate。压缩重放标synthetic，命令执行全程固定原登录并检查撤销。
- SDK由仓库生成器重生成成功；未运行测试/类型检查/构建，未启用迁移、发布目录或重启服务。M2源码本轮尚未开始；下一轮按已确认顺序继续 M2，实际启用仍等待最终验证。

## M2 第一轮：原生入口、组上下文与单一模型配置

上一轮为 M1 源码交付进展，本轮按顺序进入 M2，结果见 [M2 源码交付](RUNTIME_INTERNALIZATION_M2_IMPLEMENTATION.md)。没有启用新任务入口或运行测试。

- 前端确认服务端开关后，原文进入现有draft/composer；已有任务直接向原session提交当前agent/model/variant并返回原生任务。Compose/Goal/Solution不再强制第二个Runner。未知开关状态不猜测或回退旧模板。
- 后端新增确定性的 task-context 加载：当前组安装Skill、真实能力目录和组Memory读取进入原生ToolPart/inspection；复用相同身份、工具发布、预算和错误/取消链。引用内容不作为授权指令，原始用户需求不被改写；本轮明确禁用的工具不自动读取。
- Provider/Auth/Config仅以QuantCode宿主URL/API Key为模型来源，禁默认供应商环境和上游账号回填、内置ID碰撞继承、项目/env模型覆盖；配置撤回时旧SDK和响应流失效。公开配置按UI需要白名单返回，不泄露宿主内部凭据。
- 组/通用Skill移除旧Runner硬转交与mock指示，Python native模式发现与调用同时排除旧循环及尚未接入统一Provider的独立模型工具。普通组织工具不再初始化Python模型；旧恢复保留待M3专用适配，不能用旧prompt绕新链。
- 本轮只实现、阅读和核对源码，未运行测试/类型检查/构建、未发布真实目录或改动运行服务器。M3～M4未开始；接下来先完成M2源码收尾记录，再进入M3状态/恢复/组织视图实现。

本轮收尾：原生Memory读取已强制走gateway共享查询并核对调用前后的原登录，不回落个人库。前端已有任务提交明确传递当前composer选择的agent/model/variant；任务启动读取尊重本轮user.tools禁止项，安装根先realpath再识别当前组Skill。M2源码交付已形成，后续可按顺序准备M3未启用实现；真实运行验收仍整体未开始，不能宣布M2退出条件已通过。

## M3 第一轮：原生任务投影、恢复边界与组织视图（实现待验）

本阶段按 M0 → M1 → M2 → M3 顺序接线。此前交叉任务的有限检查见顶部更正；迁移仍未通过集中验收，也未据此启用或重启现有服务。

- `quantcode/task-index.ts` 直接从 OpenCode 原生 `SessionTable`、`MessageTable`、`PartTable`、`EventTable` 派生任务摘要；不复制消息、工具结果或执行状态机。索引分页使用稳定 session keyset，查询在输出限额前完成当前身份和工作区授权核对，任务摘要用量按来源会话统计。
- `quantcode/task-publisher.ts` 只订阅原生事件，维护可重建的投影投递队列并调用网关；网关只保存授权摘要，`received_at` 是接收时间，不冒充远程实时执行。普通成员读取需匹配完整原 owner 快照，Admin 读取沿用审计边界。
- Activity、任务树和 Admin 四页签改用原生任务/消息接口；详情分页在 SSE 或定时刷新后保持已加载窗口，不调用其他成员的本机消息接口。取消继续使用 OpenCode `SessionRunState`、`Runner` 和 `BackgroundJob`，先中断父任务再收集并取消后代。
- 原生任务的完成状态要求 assistant 已真正结束、无待处理工具调用、无未知写入回执和未确认用量；工具回合中断、恢复竞态或不确定结果保持 `paused`/`unknown`，不能误标 `completed`。崩溃核对使用已有 EventV2 事务和精确宿主锁，不按时间抢占。
- `quantcode/legacy_host.py` 与 `QuantCodeLegacyHost` 保留旧 checkpoint 查询、精确 owner/checkpoint/provenance 摘要和只读预检；不接受新的 task、模型 key、来源路径或浏览器注入。统一 Provider 恢复桥尚未交付，因此 `resumed:false` 是明确阻断状态，不能描述为已完成恢复。
- artifact/report 继续复用原生 ToolPart 的附件和受控 ToolOutputStore 内容，生成带 SHA-256 的不透明引用；列表只返回引用，详情才返回受限内容。网关沿用完整 owner 校验和 Admin 审计，不保存宿主路径或任意 URL。方案事件已保留在同一原生事件链；尚无可信知识候选事件时保持不可用，不伪造候选结果。

M3 仍未退出：知识候选和方案关系的完整组织投影、统一 Provider 的 legacy 恢复、断线后真实继续、跨成员 Gate/审批和投影投递健康状态仍需在最终集中验证中证明。artifact/report 已有受控引用与详情投影，但仍需验证跨成员读取和撤销场景。M4 命名/文案草稿已存在，阶段仍未进入或完成；OpenCode 的原生执行内核继续是唯一执行基础。

## M3 知识候选适配增量（源码待接线、待验）

- `quantcode/knowledge_host.py` 与 `quantcode/knowledge.ts` 增加固定宿主适配：只接受原生完成记录的真实工具名/调用 ID 与 source/session/root/revision；不接收任务原文、参数、结果正文、模型 key、组或目录。身份和组从当前 gateway 会话复核，TypeScript 调用者还须提供读取原 ToolPart 时的同一身份。
- 蒸馏复用已有 `runner.dream_consumer.distill_new_runs` 和 `dream.distill_prototype.run_distill`，不调用 LLM。结果进入既有候选 `index.json`，新增 source 游标仅作投递去重；候选状态仍为 draft，审核复用原 `runner/distill/governance.py`。
- 复用中修正了旧 consumer 在去重之前覆写候选文件的问题：先用原算法计算、在原审核进程锁下去重，再非覆盖写草案和原子更新 index；同首末工具的不同序列使用摘要后缀避免文件重名。原人工编辑、审核结果和已发布技能不因重新蒸馏被覆盖。新回归材料仅写入，未运行。
- 原候选查询、审核及消费状态改读同一宿主私有 `QUANTCODE_DISTILL_CANDIDATES_DIR`；native 发布还需要明确的 `QUANTCODE_DISTILL_PUBLISH_ROOT`。未配置时明确不可用，不创建个人目录假冒组织候选库。两处目录均纳入原生文件/Shell 私有路径排除；未登记真实目录或发布工具目录。
- 固定宿主另提供 list/review 管理动作，供现有候选 UI 的专用 API 接入；不用模型 MCP 调用管理写工具。它们复用原同组 approver/Admin 审核和 Admin 查询审计，所有 review 动作要求当前预览摘要，并在原审核锁内重验 gateway 身份。TS 导出 `QuantCodeKnowledgeHost.list/review`，不允许调用方指定 owner、group 或存储/发布路径。
- 原生事件 schema 已定义 `quantcode.knowledge.candidates.observed`；事件 manifest、publisher 的真实完成记录接线、组织投影和桌面展示仍须继续完成。该增量不代表 M3 退出，也未改变“全部实现 → 桌面 UI 通过 → 全部用例测试”的顺序。

## M3 旧组织投影兼容收尾（维护工具未执行）

新增 [旧组织任务投影归档与重建说明](NATIVE_TASK_PROJECTION_COMPATIBILITY.md)。无 `artifact_manifest_hash` 的实验版记录不再进入新 schema 解析；授权列表单独返回 `legacy_pending` 并沿相同 keyset 分页，详情返回明确的 `409 migration_required`，不伪造原生事件或 artifact 来源。

宿主 `quantcode.native_task_migration` 提供只读预检、携带精确预检摘要的事务归档、只读原文查看。完整旧行保存在同一 gateway SQLite 的不可变归档表，原 cache 行不删除。重发布必须符合原完整 owner/root/parent/created 及不回退的版本；缓存行消失也保留 owner 预留和递增发布回执。新 publisher 仍须从真实原生事件重建。

本轮仅写入维护工具和兼容接线，未运行命令、接触真实数据库或凭据、运行测试/编译/构建；对应桌面提示由既有任务列表接线。该兼容准备不代表 M3 验收完成，也不代表已进入 M4 或退役任何历史执行器。

## M3 无 owner 原生历史接入（源码待验）

新增 [无 owner 原生历史接入说明](UNBOUND_NATIVE_HISTORY_COMPATIBILITY.md)和宿主 CLI `import-quantcode-native-history.ts`。复核现有 CLI import/export 后，确认其不保存 EventTable 且会重定向目录；因此旧记录在原表原 ID 上登记，只复用现有 Session.fromRow、EventV2.publish 和事务提交，不复制对话或启动执行。

宿主可以只读列出、精确预览/导出完整旧任务树。绑定需要逐条来源摘要、人工归属声明和证据文件实际摘要，当前 gateway 完整 owner 与声明匹配、所有工作区授权仍有效；拒绝自动认领、遗漏子任务、已绑定/混合树和 Core V2 数据错当当前桌面历史。新增 `Database.layerFromExistingPath` 仅复用现有 SQLite 适配器，支持无自动 schema migration/WAL操作的只读检查。

提交仅给原 Session metadata 加宿主 owner 和不可变 `quantcode_legacy_import.read_only` 来源标记，并追加原生 Updated 事件；消息、Part、todos、原事件和任务关系完整保留。声明/来源/证据先在私有目录按摘要非覆盖归档。当前主任务已接只读标记的中央执行准入保护与现有历史 UI；静态核对确认宿主 CLI 直接使用独立 EventV2 + commit 回调，不经禁止普通写入的 Session.patch，也不初始化执行器。不将导入状态当作任务完成。本轮未读取真实数据库、执行维护CLI、运行测试/编译/构建或重启服务。

## M3 当前合并接线（实现进行中）

- 已核对另一任务的交付，保留其既有代码，四份伪代码/规划报告明确归档。它们不替代实际运行证据。
- 原生工具返回先完成授权复核，再捕获不可变产物快照；旧回执重放不会重新读取路径。组织发布先投引用清单，再分块传内容。桌面下载逐块及整文件核对摘要，授权读取失败会撤销旧预览 URL，同步中的产物会刷新状态。已接固定 API 与 SDK 声明，未实测。
- 发布健康状态、组织任务树和旧索引待重建提示已接入桌面；当前登录之外的观察数据不会沿用。正常任务完成不再因关闭 watchdog 误停后台子任务；实际取消遍历包含已完成中间任务的后代关系。
- 知识候选已接原生事件 manifest、发布器、组织摘要和现有人工审核 API；只有已完成且无失败组件结果的工具序列进入确定性蒸馏。候选生成不调用模型，不自动发布 Skill。
- 旧任务恢复的 Provider/AppProcess 桥及历史页控件已接线，支持完整 owner 一致时重新登录。独立静态复核发现的归档工具隔离、撤销后来源续写、未知用量核对、原图参数和跨成员旧 Gate 正在收尾；全部关闭前不宣称 M3 实现完成。
- 本次只进行源码修改、阅读和 SDK 声明生成，没有运行用例、类型检查或产品构建，也未重启现有服务。此前的有限 bundle/格式检查/Python 编译见顶部更正，不能计作验收。

最终验收按最新用户要求：全部实现后先完成桌面 UI 核验，UI 通过后再运行全部用例；保留的 1300 项旧缓存清单还须与当时真实收集结果逐项比对。

## 桌面 UI 核验第一轮与登录修复（2026-09-08）

已实际开始桌面预览检查，记录见 [桌面 UI 核验](../testing/DESKTOP_UI_REVIEW_2026-09-08.md)。发现并修复无参登录/退出接口与生成 SDK 空 body 的契约不一致；修正启动器未读私有宿主配置，并恢复原本机 gateway 隧道。在全新私有会话目录中，通过正式 gateway/SSH agent 的网页登录成功，页面自动显示名册账号、组和角色，退出已观察为未认证。原用户凭据文件未覆盖。

1440×900 下修复模型弹窗保存按钮被裁、原生审批未登录空白、原生默认 Skill 空下拉框和双模型配置旧文案。补齐 Electron 本机 SSH challenge 签名及 GitHub 主进程凭据桥源码；管理页面原生身份读取不再依赖旧 MCP。安装包和这些主进程新链路仍待运行验证。

当前真实 gateway 新版组织任务索引返回404，GitGraph及其六列详细页仍待核验；不能宣布 UI 通过或切换真实迁移。仍遵循 UI 通过之后才运行全部用例，未启动任何用例/类型检查套件。本轮 SDK 生成与网页交互是实现和 UI 核验过程，不是全量验收证据。

## 2026-09-09：登录、工作区入口与目录读取回修

上一轮通过真实 Electron 点击验证登录，并确认旧 `4844/4496` 仍缺身份配置。本轮继续从当前代码核对退出条件，不把旧审计清单直接当作新实现缺失清单。

- **M1/M2 工作区发现**：新增 `quantcode.workspaces.list` 宿主只读接口，复用 roster 和显式工作区授权。当前宿主不存在的远程目录不返回；缓存目录重新核对，其他成员/控制目录过滤，选择过程绑定登录并重验实际系统访问。默认 cwd 不成为授权依据。SDK 经现有生成器更新，未运行测试或类型检查。
- **M2 桌面新任务**：首页、打开项目、Composer 项目切换共用授权根发现及选择前校验。单根首次使用可默认进入，多根沿用现有 V2 目录选择器；原生模式不根据 loopback 推断本机文件系统。草稿/Session/Provider/编辑器/终端链继续复用。
- **M1 目录读取**：实际 UI 重现 macOS `scandir('/dev/fd/N')` 的 `ENOTDIR`。改用现有固定 Python 文件 helper 的 `scandir(fd)`，复用 AppProcess；目录和条目在返回前核对 inode/时间及当前授权。明确拒绝特殊路径、私密目录、符号链接和硬链接，保留 10000 条目/8 MiB 上限。当前 macOS UI 已能列出授权子目录；Windows 仍是明确未支持边界。
- **产品适配**：新任务草稿页删除上游 Wordmark，使用 QuantCode 研究任务标题；统一模式隐藏不能执行的旧 worktree 创建菜单，使用授权项目入口；未知分支不伪造为 main。新增任务输入/项目菜单/关闭标签的中文文案沿既有 i18n。
- **M3 取消回修**：静态发现旧 BackgroundJob 已完成但子 Session 重新运行时父取消漏停；实现沿真实 Session 父子关系取消 Runner，UI 依据完整后代活动显示停止任务树。进一步修正 Shell ready 等待、取消结果缓存、迟到后台通知和父子 workspace 一致性问题。原任务准入检查贯穿子任务创建、通知输入事件与 Runner 启动，普通子任务失败不撤销自身/兄弟的正常通知。两位 agent 完成限定静态复审；回归源码已补，未运行，不能宣称取消已通过。
- **M4 远程宿主准备**：新增 `scripts/install_native_host.py`，复用完整 compiled CLI `serve` 产物、已登记 Linux UID 和组织 Python 服务，默认只读计划，显式 apply 只创建新版本独立 unit/控制目录，不启动或切换。详见 [个人原生研究宿主](NATIVE_RESEARCH_HOST.md)。本轮未执行安装、构建或远端操作。

UI 运行证据仍集中在 [桌面核验记录](../testing/DESKTOP_UI_REVIEW_2026-09-08.md)。真实模型与组件任务、组织 gateway 新接口部署、全成员验收、取消/恢复完整行为、安装包及所有用例均未完成；此前 1300 项基线继续保留。

## 2026-09-09：模型保存、项目操作与审批结果核对

上一轮为有效源码/UI进展。本轮 UI 工具在读取当前状态和对原标签重试时均发生自动审批检查超时；端口检查确认预览服务仍在，未据超时重启。当前新增 UI 仍待工具恢复后核验，没有越过 UI 前置条件运行测试。

- **模型 URL/Key**：固定弹窗打开时的宿主及表单版本；密钥保存、模型列表请求禁止重定向。沿现有 Auth metadata 绑定密钥的 API URL，Provider 在配置不匹配时不开放；Config 修改 URL 要求匹配目标凭据，原两存储的部分保存不能把新密钥送给旧地址。导入也保留既有目标绑定。详见 [模型兼容说明](MODEL_CONFIGURATION_COMPATIBILITY.md)，未建第二 Provider。
- **项目 UI**：原生项目外观编辑不再发送已被宿主拒绝的 startup command；侧栏、快捷键和命令的旧 worktree 操作改为授权项目入口，未知模式不启用旧操作。非 QuantCode 及未切换的旧运行环境仍保留原行为；正式旧执行器退役仍等 M1～M3 验收。
- **审批结果**：新增固定 `nativeGate.read` HTTP/SDK 接线。提交响应不确定时先读原记录，只有确认同版本仍 pending 才能重试；已批准/拒绝/失效结果可展示，重新登录不重发。网关允许仍具同一完整审核身份的成员读取本人已记录决定，但不恢复过期执行授权；请求标识/摘要缓存不成为事实源。
- **集中测试准备**：新增 [最终测试执行计划](../testing/FINAL_TEST_EXECUTION_PLAN_2026-09-09.md)，核对 package 实际入口、Python 1300 项原清单、隔离、日志和失败记录。未执行收集、测试、类型检查或产品构建。

源码生成仅更新 SDK 声明，静态复审不能证明行为通过。UI 超时、真实服务部署、各场景和安装包验收继续列未完成。

## 2026-09-09：源码交付核对完成，等待 UI 工具恢复

本轮三位 agent 分别按主决策限定核对 M1/M2、M3、M4：未发现需要在 UI 阶段前继续补代码的新增明确阻断。没有据此宣称阶段行为通过，也不再用旧双循环审计不断扩张任务。七项标准的源码依据、未完成退出证明和恢复步骤汇总在 [源码交付与验证边界](RUNTIME_IMPLEMENTATION_READINESS_2026-09-09.md)。

当前 CUA 自动审批检查在连续三轮目标处理中超时。工具会话重置后，对原标签的只读检查仍超时；实际监听检查显示预览服务仍在，未重启。按“UI 通过后才能测试”的用户约束，下一步必须等待该工具服务恢复，不能用源码阅读或已成功的单页截图替代剩余桌面验收。目标未完成，当前标记为阻塞；尚未运行测试收集、用例、类型检查或构建。

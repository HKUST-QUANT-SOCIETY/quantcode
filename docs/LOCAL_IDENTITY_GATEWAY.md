# 本地 Dev 身份接入

这份说明描述已实现的宿主接线，不表示正式人员授权、远程任务闭环或安装包验收完成。桌面登录由 Electron 主进程使用成员电脑的 SSH agent 签名；renderer 只接收身份摘要。身份认证与组织工具、工作区和任务执行准备分别核验。

## 宿主配置

桌面原生身份桥只要求个人研究宿主配置以下三项。公钥与会话文件路径必须为绝对路径，凭据文件不提交 Git：

| 变量 | 含义 |
|---|---|
| QUANTCODE_PUBLIC_KEY_FILE | 个人研究宿主保存的已登记公钥；对应私钥加载在成员电脑的 SSH agent 中 |
| QUANTCODE_IDENTITY_SESSION_FILE | 该成员在个人研究宿主上独立保存的 0600 会话凭据文件 |
| QUANTCODE_GATEWAY_URL | 本地 `http://127.0.0.1:4097` 或受信任的 HTTPS gateway |

Electron 主进程调用宿主 challenge/verify 接口，本身不需要 Python checkout。成员电脑需要可用的系统 OpenSSH，且 `ssh-add -L` 能列出与宿主登记相同的公钥；私钥不上传给研究宿主。

Web 开发/旧本机登录辅助 `signInLocalIdentity` 仍调用 `python -m quantcode.identity_login`，额外需要 `QUANTCODE_HOST_PYTHON`（已安装依赖的 Python 绝对路径）和 `QUANTCODE_BACKEND_ROOT`（后端源码绝对路径），并使用该 Web 服务所在机器的 SSH agent。它不等同于远程网页可以访问成员电脑的 SSH agent。Python 组织服务及组件执行也需要相应宿主依赖，但缺少这些执行依赖不能据此判定原生桌面身份无法认证。

正式 roster 必须包含 actor_id、group、role、workspace_id、workspace_path；可选 `groups` 列表表示同一 actor 的多组授权。REVIEW_REQUIRED 候选会被拒绝。不得通过修改状态字段跳过人员冲突审核。

Roster 激活实际需要以下条件同时成立：

1. `.opencode/authorized_groups.yaml` 是正式绑定文件，不是 `authorized_groups.example.yaml`，且入选条目不能是 `REVIEW_REQUIRED`。
2. 绑定指纹对应的公钥文件可读，对应私钥已由本机 SSH agent 或 Keychain 加载。
3. Gateway 使用同一份已审核 roster 启动，个人研究宿主配置上述三项身份连接，且该宿主可以访问 gateway。会话文件属于个人研究宿主，gateway 通过自己的会话数据库验证 token，不共享该文件。组织 MCP 后续接入时须使用同一成员的有效凭据。
4. 入门身份条目必须包含 `actor_id`、`role`、`workspace_id` 和 `workspace_path`；只有 fingerprint/group 的简化条目可用于本地分组诊断，不足以签发 SessionContext。

同一 actor 可以在 roster 中声明多个授权组，例如 `group: model`、`groups: [model, factor]`。登录时可请求其中一个组（`identity_login --group factor`）；服务端签发的 SessionContext 仍只包含一个固定 `group`，任务参数不能切组。没有指定组时使用 roster 的主组 `group`。

2026-09-08 桌面登录改为自动绑定 roster 主组，不提供组选项，宿主接口拒绝组覆盖。CLI/gateway 的历史多组授权能力仍保留，普通桌面不暴露。“断开”会撤销 gateway token、清理宿主会话文件并断连旧 MCP；撤销失败时保留待处理记录以便重试，不显示已退出。重新打开设置时读取真实 gateway 会话并恢复身份展示。MCP 是否可连接不决定原生身份登录是否成功。

### 开发端口与旧连接

`bun run dev:quantcode` 与 `bun run dev:desktop` 共用 `frontend/script/dev-quantcode.ts`。启动器默认读取仓库 `.quantcode/quantcode.local.env`（若存在），只导入白名单内的宿主连接、控制存储、端口及迁移设置；启动进程显式提供的同名变量优先，包括显式空值。它使用环境文件解析器，支持 `KEY=value` 和 `export KEY=value`，不执行 `source`、shell 命令或 `$VAR` 展开。配置中的路径应直接填写绝对路径。

配置文件须归当前用户所有、权限为 `0600`，不能是符号链接或多硬链接；读取过程中变更或权限不合规会终止启动。默认文件不存在可继续打开预览；显式指定的文件不存在则报错。启动器不创建、改写或复制该配置与登录凭据，不从文件导入个人组别、账号或模型 API Key。

可用 `QUANTCODE_HOST_ENV_FILE=/absolute/private/quantcode.local.env bun run dev:quantcode` 指定另一份已有私有配置。设置 `QUANTCODE_HOST_ENV_FILE=` 则完全跳过文件加载，用于隔离预览；此时只保留本次进程显式继承的配置。排查时分别检查三项原生身份配置与 Python/组件执行配置；UI 可打开不能证明身份服务已连接，身份已连接也不能证明执行依赖已齐备。此开关不会清除已经由 shell 显式提供的变量。

QuantCode 单仓库的网页启动器默认使用后端 `4096`、前端 `4444`。如果这两个端口已被另一个 OpenCode 工作区占用，请使用独立端口：

```sh
cd /absolute/path/to/QUANTcode
QUANTCODE_BACKEND_PORT=4196 QUANTCODE_APP_PORT=4544 bun run dev:quantcode
```

开始后检查界面上的“服务”应为 `127.0.0.1:4196`。`GET /agent?directory=...` 是基础 Agent 列表路由；排查 500 时先确认请求是否发到旧工作区。QuantCode 身份检查为 `/experimental/quantcode/identities`；桌面登录走 `/experimental/quantcode/identity/challenge` 与 `/experimental/quantcode/identity/verify`，退出走 `/experimental/quantcode/identity/logout`。`/experimental/quantcode/identity/login` 保留 Web 开发/旧本机辅助路径。原生模式的 `/experimental/quantcode/tool?tool=session_context` 直接查询 gateway 当前身份，不依赖 MCP。前端不提供 `/api/auth/me`，不要用它判断登录状态。

启动独立 gateway 的命令模板（Server C 可用 Ubuntu 账号托管）：

```sh
python -m quantcode.gateway --roster /absolute/approved-roster.yaml --database /absolute/private/identity-gateway.db --port 4097
```

Server C 当前使用 `ubuntu` 账号的 systemd 验收模板 `ops/systemd/quantcode-gateway.service`，服务只监听 `127.0.0.1:4097`；客户端通过 `ssh -L 4197:127.0.0.1:4097 qs-gpu` 访问。正式生产仍建议将 `User=ubuntu` 替换为无 sudo 权限的专用 `quantcode-gateway` 服务账号；Ubuntu 账号可用于当前受控部署和验证。

2026-09-07 的历史实测记录：该 unit 为 `active/running`，启用 `NoNewPrivileges=yes`，GitHub/Dream 两个 interval 均为 0。它仅托管身份 gateway；完整 Python Agent/MCP 运行目录另由 root 管理，`/opt/quantcode/runtime/current` 当时指向版本 `272ab3b`。Roster 的 36 个工作目录已创建，分别归属无 sudo 的独立 `qc-<actor_id>` 研究账号，权限为 `0700`。当时的本机签名到 SSH 远程 MCP 凭据传递及 systemd 按需运行已验证身份一致、撤销拒绝和断连清理。这是旧路径的部署证据，不证明当前源码内化的远程原生任务闭环已通过。每位成员的研究宿主进程、会话文件和访问凭据仍必须隔离；共享 gateway 不等于共享同一个可被登录接口替换的宿主会话文件。完整证据与操作边界见 [Server C 运行环境](SERVER_C_RUNTIME.md)。

远程运行再配置 `QUANTCODE_REMOTE_SSH_HOST=qs-gpu`，MCP command 使用 `python -m quantcode.mcp_host`。未配置该变量时使用原本的本机 MCP。`qs-gpu` 必须是本机已配置且已核验 host key 的 Server C SSH host；用户名由认证 actor 推导，不能从浏览器改写。身份 gateway 仍可通过既有 `4197` 隧道访问。

## 登录路径

桌面设置页选择已保存的个人研究宿主 → Electron 主进程请求该宿主 challenge → 在成员电脑核对公钥并调用系统 SSH agent 签名 → 主进程把签名送到同一宿主 verify → 宿主向原 gateway 核验 challenge 与 roster → 个人研究宿主保存私有会话凭据 → renderer 接收包含有效期的身份摘要，界面显示已认证人员、组和角色。

主进程只接受已保存的宿主 key，不接受 renderer 指定 URL、密码、公钥路径、组或 actor；签名、challenge 正文及 token 不返回 renderer。签名前和 verify 前后检查同一宿主及当前身份，窗口关闭或取消可中止正在进行的操作。已经送达 verify 的请求不能保证因客户端取消而撤销，应刷新原宿主状态，必要时显式退出。完整协议见 [桌面 SSH 身份桥](decisions/DESKTOP_SSH_IDENTITY_BRIDGE_2026-09-08.md)。

宿主身份列表调用 `/auth/identity`，只读取登记公钥对应的授权信息及当前会话，不自动创建 challenge 或登录。登录、verify 与退出沿用进程级互斥准入；并发操作被拒绝，可在前一操作完成后重试。原生 verify 成功后断开使用旧身份的 MCP，不因 MCP 或组件不可用撤销已完成的身份认证。Web 开发/旧本机辅助与 CLI 仍使用 Python 签名路径；旧非原生模式保留其 MCP 重连和会话核对，此兼容步骤不是桌面原生登录条件。

认证成功明确返回 `status: connected` 和 `execution_status: disconnected`。这表示当前成员身份已经过 gateway 验证，尚未证明研究宿主、工作区、模型或组织工具已可执行。任务开始前仍须分别确认统一引擎已启用、工作区授权、一次 URL/API Key 模型连接及所需已发布组件；缺少组件应显示真实不可用状态。不能把登录成功、旧 MCP 可连或显示远程目录当作完整远程任务运行通过。

CLI 提供 `--inspect`（读取组与真实会话）及 `--logout --session-file /absolute/session.json`（撤销并删除凭据）；输出不包含 token 或签名。直接 CLI 续登会先撤销即将替换的旧凭据。gateway 每次查询重验 roster，撤销、角色变化或过期后要求重新登录；不能用手动注入 fingerprint、group 或 role 代替权威认证。

## 验收证据与剩余接入

`tests/test_identity_gateway.py` 已用独立临时 SSH agent 和临时密钥执行真实签名，验证一次性 challenge、会话哈希持久化、退出/过期、角色/组/权限/工作区变更撤销，以及待审核 roster 拒绝签入。当前全量结果见 [功能验收台账](audit/FULL_PRODUCT_AUDIT_2026-09-05.md)，避免在接入指南重复维护滚动数字。没有修改或加载用户实际密钥。

2026-09-07 新增真实签名的组绑定、单组 Memory scope、撤销第二组后会话失效及生产 MCP 子进程联调回归；同时删除依赖 `PYTEST_CURRENT_TEST` 的认证失败回退。Gateway 身份修复已同步 Server C，既有本机 Lead 公钥经 SSH agent 签名登录成功；这不代替成员设备或远程共享宿主验收。

旧路径的隔离环境曾通过宿主 HTTP → Python CLI → 临时 SSH agent → gateway → MCP 联调，覆盖第二组登录、未授权组拒绝、并发登录拒绝、会话一致性、退出撤销和断连。当时浏览器的组选项验证只作历史记录；当前桌面已取消组选项，不应恢复它。本机 Lead 的旧宿主接口实连也不能代替当前 Electron 主进程桥、其他成员设备、真实工作目录或安装包验收。

当前桌面 UI 登录证据与尚未通过项目统一记录在 [桌面 UI 核验记录](testing/DESKTOP_UI_REVIEW_2026-09-08.md)，本指南不另维护滚动端口或通过数量。未配置正式 roster、宿主三项身份连接或有效 SSH agent 时，应先排查具体身份错误；MCP 未连接则属于后续工具/执行接入状态，不能据此否定已认证的原生身份。远程任务闭环和发布安装仍按内化决策独立验收。

## GitHub 凭据绑定

宿主可配置 `QUANTCODE_GITHUB_CREDENTIALS_FILE`，指向服务账号拥有且权限 0600 的 JSON 映射：

```json
{"subjects":{"github-login":{"token_file":"/absolute/private/github-token"}}}
```

token 文件同样要求 0600、服务账号所有，内容为已有账号凭据。映射按正式 roster 的 github_subject（小写）读取，不从浏览器或 Agent 参数选择身份。每次查询重读，便于撤销或轮换；不把 token 写入 SessionContext、checkpoint 或日志。GitGraph/Pop 和已认证 PR 读取还会验证实际账号与 Team/repo 权限，映射存在本身不授予仓库权限。GitGraph 桌面查询、Pop 分页和个人已读状态统一在宿主通过 `quantcode.github_host` 复用现有 Python 图与通知服务，避免将本机凭据复制到远端研究沙箱。每次调用核验 gateway session_id 与 GitHub /user 的 subject，返回前再次检查会话。Server C 的 Agent GitHub 工具仍需要独立的凭据接入，不能据此标为已接通。

## Gateway 后台 GitHub 同步

gateway 启动时默认运行后台同步循环，每轮完成后等待 60 秒；`--github-sync-interval 0` 可禁用，非零值至少为 60。gateway 进程也必须继承 GitHub 凭据映射环境变量。

同步只针对仍有效的 gateway 会话，逐个重新验证会话、正式 roster 和 GitHub 授权范围。同身份和工作区的多个登录去重处理；退出登录、撤销、权限变化或过期后不再为该会话开启新一轮同步。不创建永久服务账号授权，不因浏览器关闭而延长会话。

同步复用 GitGraph 的 SQLite 基线与 Pop，不在浏览器关闭时发送 OS 通知。认证 `GET /github-sync` 返回当前身份的最近一次尝试状态和起止时间；STARTED 只表示曾开始，不能据此证明进程仍运行。失败记录只保存异常类型，避免泄漏传输凭据。worker 与手动刷新并发时，较早开始的响应不能覆盖已提交的更新基线。

GitHub worker 和 Pop 持久化已接入 gateway，默认同步间隔为 60 秒，但 Server C 部署显式禁用了同步。系统通知由在线客户端消费新 Pop 后调用本机通知接口，仅发送不含仓库详情的摘要；后台 gateway 不直接向已关闭的客户端推送系统通知。真实后台同步和系统通知送达仍待部署联调。

## 量化组件的本地 checkout 模式

量化组件暂按“组员本地拉取 canonical 仓库，Agent 先学习能力卡和 README”运行，不把本地代码当作生产 API。对应配置在 `configs/local_components.yaml`：为组件填写本机绝对路径后，可用下面命令检查状态；脚本只读取目录，不导入或执行组件代码。

```sh
python scripts/check_local_components.py
```

组件上线服务后，再把对应的 `*_API_URL` 环境变量和适配器接入；在此之前，QuantCode 对真实评估、回测和组合调用保持 `STAGING`/`UNAVAILABLE`，不会用合成结果冒充生产证据。

### GitHub 两种连接方式（2026-09-08）

GitGraph 提供「通过 GitHub 登录」和「使用本机凭据」两个入口。浏览器方式由宿主 GitHub CLI 发起 device flow，页面只显示 GitHub 官方授权链接和短期一次性代码；令牌留在 CLI 凭据存储，完成后按 roster subject 验证并写入 0600 的宿主映射。可取消，十分钟到期后需重试。本机方式使用已配置的账号凭据或 GitHub CLI 凭据，同样检查账号一致性；管理员也不能使用其他人的 token。

桌面通过 `/experimental/quantcode/github` 查询状态或选择 `local/browser/cancel`。GitGraph 首屏先按最新 GitHub ACL 过滤缓存与仓库摘要，标记 `refresh_pending`；宿主用独立、按会话互斥的有限后台批次刷新，每批最多两个仓库。失败不会替换有效基线，也不会阻塞后续仓库的刷新顺序。

QuantCode 桌面与开发启动器使用独立的 `quantcode` 配置、凭据、缓存和状态目录，不导入 OpenCode 个人供应商配置。模型供应商仅接受 OpenAI 兼容 URL 与 API Key，内置目录和 OAuth 供应商入口停用；GitHub 授权与模型接入是独立功能。

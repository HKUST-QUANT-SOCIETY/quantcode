# 本地 Dev 身份接入

这份说明描述已实现的宿主接线，不表示正式人员授权或真实服务验收完成。私钥由 SSH agent 保存，浏览器仅选择宿主提供的公钥身份。

## 宿主配置

OpenCode 后端与它启动的 QuantCode MCP 需要继承以下环境配置。所有路径必须为绝对路径，凭据文件不提交 Git：

| 变量 | 含义 |
|---|---|
| QUANTCODE_HOST_PYTHON | 已安装 QuantCode 依赖的 Python 可执行文件 |
| QUANTCODE_BACKEND_ROOT | QuantCode 后端仓库路径 |
| QUANTCODE_PUBLIC_KEY_FILE | 本机公钥文件；对应私钥必须已加载到 SSH agent |
| QUANTCODE_IDENTITY_SESSION_FILE | 登录后写入的 0600 会话凭据文件；MCP 使用同一路径 |
| QUANTCODE_GATEWAY_URL | 本地 `http://127.0.0.1:4097` 或受信任的 HTTPS gateway |

正式 roster 必须包含 actor_id、group、role、workspace_id、workspace_path；可选 `groups` 列表表示同一 actor 的多组授权。REVIEW_REQUIRED 候选会被拒绝。不得通过修改状态字段跳过人员冲突审核。

Roster 激活实际需要以下条件同时成立：

1. `.opencode/authorized_groups.yaml` 是正式绑定文件，不是 `authorized_groups.example.yaml`，且入选条目不能是 `REVIEW_REQUIRED`。
2. 绑定指纹对应的公钥文件可读，对应私钥已由本机 SSH agent 或 Keychain 加载。
3. Gateway 使用同一份已审核 roster 启动，宿主传入五个 `QUANTCODE_*` 变量，并且 MCP 与 gateway 使用同一个 `QUANTCODE_IDENTITY_SESSION_FILE` 。
4. 入门身份条目必须包含 `actor_id`、`role`、`workspace_id` 和 `workspace_path`；只有 fingerprint/group 的简化条目可用于本地分组诊断，不足以签发 SessionContext。

同一 actor 可以在 roster 中声明多个授权组，例如 `group: model`、`groups: [model, factor]`。登录时可请求其中一个组（`identity_login --group factor`）；服务端签发的 SessionContext 仍只包含一个固定 `group`，任务参数不能切组。没有指定组时使用 roster 的主组 `group`。

截至 2026-09-07，网页、宿主和 CLI/gateway 已接通登录前组选择。选项来自 gateway 的正式 roster，登录后显示当前固定组和授权组列表；再次选组须退出后重新登录。网页“断开”会撤销 gateway token、清理宿主会话文件并断连当前工作区的 MCP；撤销失败时保留凭据以便重试，不显示已退出。重新打开设置时会读取真实 gateway 会话并恢复身份展示。

### 开发端口与旧连接

QuantCode 单仓库的网页启动器默认使用后端 `4096`、前端 `4444`。如果这两个端口已被另一个 OpenCode 工作区占用，请使用独立端口：

```sh
cd /absolute/path/to/QUANTcode
QUANTCODE_BACKEND_PORT=4196 QUANTCODE_APP_PORT=4544 bun run dev:quantcode
```

开始后检查界面上的“服务”应为 `127.0.0.1:4196`。`GET /agent?directory=...` 是 OpenCode 的基础 Agent 列表路由，对当前仓库会返回 JSON；如果它返回 500，先确认请求是否发到旧工作区的 `4096`。QuantCode 身份路由是 `/experimental/quantcode/identities` 、`/experimental/quantcode/identity/login` 和 `/experimental/quantcode/tool?tool=session_context`。前端不提供 `/api/auth/me`；该路由返回前端 SPA HTML 是预期的，不用它判断 roster 或 MCP 状态。

启动独立 gateway 的命令模板（Server C 可用 Ubuntu 账号托管）：

```sh
python -m quantcode.gateway --roster /absolute/approved-roster.yaml --database /absolute/private/identity-gateway.db --port 4097
```

Server C 当前使用 `ubuntu` 账号的 systemd 验收模板 `ops/systemd/quantcode-gateway.service`，服务只监听 `127.0.0.1:4097`；客户端通过 `ssh -L 4197:127.0.0.1:4097 qs-gpu` 访问。正式生产仍建议将 `User=ubuntu` 替换为无 sudo 权限的专用 `quantcode-gateway` 服务账号；Ubuntu 账号可用于当前受控部署和验证。

2026-09-07 实测该 unit 为 `active/running`，启用 `NoNewPrivileges=yes`，GitHub/Dream 两个 interval 均为 0。它仅托管身份 gateway；当前虚拟环境未安装完整 Agent/MCP 所需的 LangGraph/LangChain Core。Roster 的 36 个工作目录在 Server C 上均不存在，其中包含本机运维身份路径，须先落实个人目录映射和隔离，再部署完整运行环境。上述五项变量目前是本机宿主配置，不能直接复用为 Server C 多人配置。宿主移到服务器后仍须保留成员本机签名，并按成员隔离凭据和会话文件。

## 登录路径

设置页 → 本机公钥身份 → 选择授权组 → 连接 → 宿主调用 SSH agent 签名 → gateway 验证一次性 challenge 与 roster → 本机保存会话凭据 → 重连 QuantCode MCP → 核对同一会话 → 刷新组、角色、工作区和目录。

宿主身份列表调用 `/auth/identity`，仅读取该公钥对应的授权组，不创建 challenge 或会话。登录与退出共用进程级互斥准入，覆盖签名、会话文件变更、MCP 重连/断连和身份核对；并发操作被拒绝，可在前一操作完成后重试。CLI 提供 `--inspect`（读取组与真实会话）及 `--logout --session-file /absolute/session.json`（撤销并删除凭据）；输出不包含 token 或签名。直接 CLI 续登也会先撤销即将替换的旧凭据。

界面不接收任意命令、可执行路径、私钥、签名或 token。服务端只执行宿主预先配置的固定命令。gateway 每次查询重验 roster，撤销/角色变化/过期要求重新登录。

## 验收证据与剩余接入

`tests/test_identity_gateway.py` 已用独立临时 SSH agent 和临时密钥执行真实签名，验证一次性 challenge、会话哈希持久化、退出/过期、角色/组/权限/工作区变更撤销，以及待审核 roster 拒绝签入。当前全量结果见 [功能验收台账](audit/FULL_PRODUCT_AUDIT_2026-09-05.md)，避免在接入指南重复维护滚动数字。没有修改或加载用户实际密钥。

2026-09-07 新增真实签名的组绑定、单组 Memory scope、撤销第二组后会话失效及生产 MCP 子进程联调回归；同时删除依赖 `PYTEST_CURRENT_TEST` 的认证失败回退。Gateway 身份修复已同步 Server C，既有本机 Lead 公钥经 SSH agent 签名登录成功；这不代替成员设备或远程共享宿主验收。

隔离环境已通过真实宿主 HTTP → Python CLI → 临时 SSH agent → gateway → 生产 MCP 的完整联调，覆盖第二组登录、未授权组拒绝、并发登录拒绝、会话一致性、退出撤销和 MCP 断连。浏览器已验证组选项、重新打开设置、退出失败重试和成功后的未认证状态；本机 Lead 另已通过真实宿主登录接口连到 Server C 并核对 MCP 会话。其他成员设备、共享服务器签名桥及真实工作目录仍待部署验收。未配置正式 roster 时，`/experimental/quantcode/identities` 会返回结构化的 `identities: []` 与错误，MCP `session_context` 会返回未连接错误；这些是 fail-closed 行为，不是 `/agent` 500 的原因。

## GitHub 凭据绑定

宿主可配置 `QUANTCODE_GITHUB_CREDENTIALS_FILE`，指向服务账号拥有且权限 0600 的 JSON 映射：

```json
{"subjects":{"github-login":{"token_file":"/absolute/private/github-token"}}}
```

token 文件同样要求 0600、服务账号所有，内容为已有账号凭据。映射按正式 roster 的 github_subject（小写）读取，不从浏览器或 Agent 参数选择身份。每次查询重读，便于撤销或轮换；不把 token 写入 SessionContext、checkpoint 或日志。GitGraph/Pop 和已认证 PR 读取还会验证实际账号与 Team/repo 权限，映射存在本身不授予仓库权限。目前仅本机宿主配置了真实凭据映射；Server C 的 token broker/成员凭据映射尚未配置。

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

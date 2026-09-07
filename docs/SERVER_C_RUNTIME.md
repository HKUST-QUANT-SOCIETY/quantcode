# Server C 研究运行环境

本文件记录 2026-09-07 的实际部署。当前已完成 Python 运行依赖、独立研究账号、本机签名到远程 MCP 的会话传递、systemd 按需运行和隔离验收。共享组 Memory、后台 worker、正式 provider 和外部服务仍待接线，不代表全产品发布。

## 已落地状态

| 项目 | 状态 |
|---|---|
| Python 源码基线 | `272ab3b1b12b488fec56833523c0eda6695f8f4b` |
| 运行目录 | `/opt/quantcode/runtime/current` 指向上述完整 commit 目录，root 所有；用户源码视图为 `users/<uid>` |
| Python | 3.12.3，Linux x86_64 |
| 依赖 | `uv.lock` 冻结安装，含 SSH extra，共 114 个包；`uv pip check` 通过 |
| Gateway | 继续由 `ubuntu` 托管，监听 `127.0.0.1:4097` |
| 研究账号 | 36 个，每个 actor 一个 `qc-<actor_id>`；仅私有主组，没有 sudo 或业务服务组 |
| 个人目录 | 与正式 roster 的 `workspace_path` 一致，均为独立属主、`0700` |
| 账号注册表 | `/etc/quantcode/research-identities.json`，root 所有、`0600`；不提交仓库 |
| SSH 身份 | 从已审核 roster 导入完整公钥；账号未设置可用密码，服务器禁用密码认证 |
| 研究进程 | 注册表为 `AVAILABLE_ON_DEMAND`；SSH 连接按需创建 systemd 用户服务，断连清理，最长运行到身份会话过期，不自动重放任务 |

实际 SSH 公钥匹配显示，现有实名账号仅能对应 11 个 roster actor，且部分账号有服务器管理权限。因此本次按独立研究账号方案准备，不把现有账号的组权限继承到 Agent 进程。业务组和 Admin 权限继续由 Gateway 的 SessionContext 决定，Linux 账号不授予 QuantCode Admin 身份。

已激活成员的公钥用于各自新建研究账号。张博睿、李卓和叶易涵的未激活记录不在本次开通范围。原有实名账号、生产服务账号和服务器 sudoers 未修改。

## 复现运行依赖

只从已提交源码导出 Python runtime 所需文件；正式 roster、会话、GitHub/provider 凭据和 `.quantcode` 运行数据不进入归档。

```sh
git archive --format=tar --output=/tmp/quantcode-runtime.tar 272ab3b1b12b488fec56833523c0eda6695f8f4b \
  pyproject.toml uv.lock README.md LICENSE quantcode runner schemas tools flows configs .opencode dream \
  scripts/verify_server_runtime.py scripts/install_remote_mcp.py ops/remote-mcp
```

在目标目录解包后，以独立工具环境中的 `uv 0.10.9` 安装：

```sh
uv sync --frozen --no-dev --extra ssh --no-install-project --link-mode copy --python /usr/bin/python3.12
uv pip check --python .venv/bin/python
```

采用源码布局运行，避免当前 Python wheel 不包含配置、Skill 和 Dream 源文件的边界问题。完成安装后将运行目录交给 root 管理，并移除所有组/其他用户写权限；git archive 和 uv 目录可能保留 `0775`，部署脚本会明确拒绝。使用 copy 模式可避免修改运行目录属主时影响 uv 缓存中的硬链接。当前源码版本复用已锁定且由 root 管理的 `07eacd7` 依赖环境，两个版本的 `uv.lock` 哈希一致；新版本不能覆盖旧源码目录。

服务器运行目录内的 `runtime-manifest.json` 保存源码 commit、归档/锁文件/入口脚本 SHA-256、解释器和完整包版本。当前归档 SHA-256 为 `db6a9ca53c21c33dc7d68c8c8479baa2c69c38e7472b09a80d912bd53047dadd`，锁文件 SHA-256 为 `59765736c83690f45030d9511f5bced5a4ae78f6772d5f7f0c4d8e1caafdbcd2`。

## 远程 MCP 安装与连接

管理员以目标版本的 Python 运行 `scripts/install_remote_mcp.py --runtime-root /opt/quantcode/runtime/<commit> --roster /absolute/approved-roster.yaml`。它重验 Unix UID、个人路径、组和正式 roster，创建 root 管理的每 UID 源码视图及 `.quantcode` 到个人目录的映射，然后原子更新固定入口和运行配置。重复向已有版本安装会拒绝；回滚需恢复旧版的 `current` 指针及 `remote-runtime.json`，不删除用户数据。

每 UID enrollment 保存于 `/opt/quantcode/enrollments/<uid>.json`，只含账号、actor、workspace 元数据，不含公钥/token。普通成员不能修改它。固定 SSH 入口为 `/opt/quantcode/ops/remote-mcp`，其配置和代码均由 root 管理。

本机启动配置增加 `QUANTCODE_REMOTE_SSH_HOST=qs-gpu`；MCP 入口为 `python -m quantcode.mcp_host`。变量缺省时保留本机 MCP 模式。远程 host 只能由本机配置提供，浏览器没有自由输入账号/命令/路径的入口；账号从 Gateway 已验证的 actor 推导为 `qc-<actor_id>`。本机公钥文件和 SSH agent 仍用于登录，严格校验已知主机，禁用 agent 转发。

链路为本机 SSH agent 签名 → Gateway 会话 → SSH stdio 首帧传递短期 token/session_id → 远端 Gateway 再验证 → actor/UID/工作目录核对 → systemd 用户服务 → MCP。token 不放 argv、环境变量、日志或浏览器响应，只写到 `/run/user/<uid>/quantcode-session-*/identity.json` 的 `0600` 临时文件，连接结束后清理。每次 MCP 调用继续重验 Gateway；退出撤销后存活进程也拒绝新调用。

真实用户级 systemd 不支持所需 BindPaths/PrivateDevices 配置，因此最终实现使用 root 管理的每 UID 代码硬链接视图和独立私有状态路径，不依赖这些不可用属性。最终运行启用 `NoNewPrivileges`、`PrivateUsers`、`ProtectSystem=strict`、`ProtectHome=read-only`、隐藏 `/home` 与 `/root`、私有 `/tmp`，限制 2 GiB 内存、128 tasks 和 200% CPU；只允许个人 workspace 写入。MCP 启动前检查实际非 root UID、零有效 capabilities 和 NoNewPrivileges，不能仅凭 systemd 属性存在宣称隔离。

Lead 已完成真实 SSH MCP 联调：42 个工具可发现、身份与本机会话一致、会话撤销后拒绝后续调用、EOF 后服务清理。最终用户级启动方式的 17 项系统隔离检查通过；本机网页预览已通过宿主 `/mcp` 接口使用该远程链路并显示真实 Lead 身份。该证明只覆盖传输/身份/隔离及工具发现，不包含真实模型推理或其他成员私钥验收。

`scripts/verify_remote_mcp.py` 可对独立测试会话验证上述生命周期；`--revoke` 会撤销传入会话，勿用于仍需保留的工作会话。当前证据为 `.quantcode/serverc-remote-mcp-lifecycle-20260907.json`、`.quantcode/serverc-remote-sandbox-20260907.json` 和 `.quantcode/remote-mcp-ui-20260907.png`。全量 Python **1,177 passed / 4 skipped**，包含 14 项远程传输回归；真实宿主 HTTP/CLI/MCP 测试也通过新入口的本机模式。

## 账号开通工具

`scripts/provision_research_accounts.py` 默认只输出计划，`--apply` 仅能由 Linux 管理员执行。它验证完整公钥、指纹、actor、业务组、个人目录 containment 和重复绑定；共用公钥、路径逃逸或未审核 roster 会被拒绝。

```sh
python scripts/provision_research_accounts.py --roster /absolute/approved-roster.yaml
sudo install -d -m 0700 /etc/quantcode
sudo python scripts/provision_research_accounts.py --roster /absolute/approved-roster.yaml --apply
```

实际执行须使用已安装依赖的 Python 和可信源码目录。脚本不会接管碰巧同名的已有账号/目录，不覆盖旧 SSH 密钥；再次执行会核对注册表、Linux UID、目录属主/权限及公钥集合。漂移、密钥轮换或部分开通失败须由管理员核对后处理，不能通过删除注册表绕过检查。

离组时 Gateway roster 撤销负责应用会话；Linux SSH 账号须由服务器管理员另行停用和归档。此工具不自动删除账号或用户文件，也不作为普通研究 Agent 的工具发布。

## 早期系统级隔离验收

`scripts/verify_server_runtime.py` 在真实 systemd 沙箱中执行，不把配置文件存在视为已隔离。已验证 17 项：非 root UID、NoNewPrivileges、零有效 capabilities、Python 版本、核心依赖实际导入、私有状态读写、源码不可写、Gateway roster/数据库不可读、其他隔离目录不可读，以及未认证 MCP 拒绝启动。

本次沙箱采用 `DynamicUser=yes`、`ProtectSystem=strict`、`ProtectHome=yes`、`PrivateTmp=yes`、`PrivateDevices=yes`、`PrivateNetwork=yes`，清空 capabilities。systemd `StateDirectory` 作为私有写入源，单独 bind 到源码目录的 `.quantcode`，由此保留现有状态路径约定并隔离进程数据。

随后以实际研究账号 `qc-chenyuanheng` 运行同一 17 项预检，将其个人 `.quantcode` bind 到运行目录，改用另一个真实成员目录作为拒绝读取目标，亦全部通过。这证明静态研究 UID 可运行该沙箱，不仅是临时 DynamicUser 示例。

此预检的 PrivateNetwork 只用于不联网的依赖/隔离验证；真实研究服务还须按 Gateway 和组件访问需求配置网络。不能直接把该预检单元当成已完成的生产服务。

另外，对 36 个研究账号逐一核对 UID、目录属主/权限、仅私有组、本人目录可写、另一个成员目录不可读及 sudo 授权，共 216 项通过。管理员执行 `sudo -l -U <user>` 即使显示“不允许 sudo”也可能退出 0，因此检查实际策略输出。Lead 使用现有本机 SSH agent 与公钥登录 `qc-chenyuanheng` 成功，当前目录和可写目录均为其个人 workspace。

本地验收记录保存在忽略目录：`.quantcode/serverc-runtime-preflight-20260907.json`、`.quantcode/serverc-research-runtime-preflight-20260907.json`、`.quantcode/serverc-runtime-manifest-20260907.json`、`.quantcode/serverc-research-accounts-verification-20260907.json`。开通计划的 9 项回归及全量 Python 1,163 passed / 4 skipped 通过。

## 后续接线

1. 对其他成员设备逐人验收，补齐一键连接所需的 SSH host、公钥路径和本地 agent；当前 Lead 验收不代表全员已签入。
2. 对共享组 Memory、跨人审批、组织历史和后台消费确定服务端权威存储；每人私有状态目录不能替代共享知识库。
3. 配置正式 provider、GitHub broker、后台同步与 Dream；生产部署仍由 Admin 受控接口承接。

安装包、签名和量化组件 API 继续按用户要求暂缓。

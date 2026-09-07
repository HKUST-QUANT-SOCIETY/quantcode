# Server C 研究运行环境

本文件记录 2026-09-07 的实际部署。当前完成 Python 运行依赖、独立研究账号和隔离预检，尚未完成成员端到远程 MCP 的会话传递及常驻服务，不代表全产品发布。

## 已落地状态

| 项目 | 状态 |
|---|---|
| Python 源码基线 | `07eacd752b4bcb8063b89b5687b44e2fb7168e12` |
| 运行目录 | `/opt/quantcode/runtime/07eacd752b4bcb8063b89b5687b44e2fb7168e12`，root 所有 |
| Python | 3.12.3，Linux x86_64 |
| 依赖 | `uv.lock` 冻结安装，含 SSH extra，共 114 个包；`uv pip check` 通过 |
| Gateway | 继续由 `ubuntu` 托管，监听 `127.0.0.1:4097` |
| 研究账号 | 36 个，每个 actor 一个 `qc-<actor_id>`；仅私有主组，没有 sudo 或业务服务组 |
| 个人目录 | 与正式 roster 的 `workspace_path` 一致，均为独立属主、`0700` |
| 账号注册表 | `/etc/quantcode/research-identities.json`，root 所有、`0600`；不提交仓库 |
| SSH 身份 | 从已审核 roster 导入完整公钥；账号未设置可用密码，服务器禁用密码认证 |
| 常驻研究进程 | 注册表明确记录 `NOT_CONFIGURED`，不伪装运行中 |

实际 SSH 公钥匹配显示，现有实名账号仅能对应 11 个 roster actor，且部分账号有服务器管理权限。因此本次按独立研究账号方案准备，不把现有账号的组权限继承到 Agent 进程。业务组和 Admin 权限继续由 Gateway 的 SessionContext 决定，Linux 账号不授予 QuantCode Admin 身份。

已激活成员的公钥用于各自新建研究账号。张博睿、李卓和叶易涵的未激活记录不在本次开通范围。原有实名账号、生产服务账号和服务器 sudoers 未修改。

## 复现运行依赖

只从已提交源码导出 Python runtime 所需文件；正式 roster、会话、GitHub/provider 凭据和 `.quantcode` 运行数据不进入归档。

```sh
git archive --format=tar --output=/tmp/quantcode-runtime.tar 07eacd752b4bcb8063b89b5687b44e2fb7168e12 \
  pyproject.toml uv.lock README.md LICENSE quantcode runner schemas tools flows configs .opencode dream
```

在目标目录解包后，以独立工具环境中的 `uv 0.10.9` 安装：

```sh
uv sync --frozen --no-dev --extra ssh --no-install-project --link-mode copy --python /usr/bin/python3.12
uv pip check --python .venv/bin/python
```

采用源码布局运行，避免当前 Python wheel 不包含配置、Skill 和 Dream 源文件的边界问题。完成安装后将运行目录交给 root 管理。使用 copy 模式可避免修改运行目录属主时影响 uv 缓存中的硬链接。

服务器运行目录内的 `runtime-manifest.json` 保存源码 commit、归档/锁文件/验证脚本 SHA-256、解释器和完整包版本。当前归档 SHA-256 为 `ca8ba3f30ddb52032c512b8e8d38b613e4076aa86c7334dbf6236db80269c179`，锁文件 SHA-256 为 `59765736c83690f45030d9511f5bced5a4ae78f6772d5f7f0c4d8e1caafdbcd2`。

## 账号开通工具

`scripts/provision_research_accounts.py` 默认只输出计划，`--apply` 仅能由 Linux 管理员执行。它验证完整公钥、指纹、actor、业务组、个人目录 containment 和重复绑定；共用公钥、路径逃逸或未审核 roster 会被拒绝。

```sh
python scripts/provision_research_accounts.py --roster /absolute/approved-roster.yaml
sudo install -d -m 0700 /etc/quantcode
sudo python scripts/provision_research_accounts.py --roster /absolute/approved-roster.yaml --apply
```

实际执行须使用已安装依赖的 Python 和可信源码目录。脚本不会接管碰巧同名的已有账号/目录，不覆盖旧 SSH 密钥；再次执行会核对注册表、Linux UID、目录属主/权限及公钥集合。漂移、密钥轮换或部分开通失败须由管理员核对后处理，不能通过删除注册表绕过检查。

离组时 Gateway roster 撤销负责应用会话；Linux SSH 账号须由服务器管理员另行停用和归档。此工具不自动删除账号或用户文件，也不作为普通研究 Agent 的工具发布。

## 隔离验收

`scripts/verify_server_runtime.py` 在真实 systemd 沙箱中执行，不把配置文件存在视为已隔离。已验证 17 项：非 root UID、NoNewPrivileges、零有效 capabilities、Python 版本、核心依赖实际导入、私有状态读写、源码不可写、Gateway roster/数据库不可读、其他隔离目录不可读，以及未认证 MCP 拒绝启动。

本次沙箱采用 `DynamicUser=yes`、`ProtectSystem=strict`、`ProtectHome=yes`、`PrivateTmp=yes`、`PrivateDevices=yes`、`PrivateNetwork=yes`，清空 capabilities。systemd `StateDirectory` 作为私有写入源，单独 bind 到源码目录的 `.quantcode`，由此保留现有状态路径约定并隔离进程数据。

随后以实际研究账号 `qc-chenyuanheng` 运行同一 17 项预检，将其个人 `.quantcode` bind 到运行目录，改用另一个真实成员目录作为拒绝读取目标，亦全部通过。这证明静态研究 UID 可运行该沙箱，不仅是临时 DynamicUser 示例。

此预检的 PrivateNetwork 只用于不联网的依赖/隔离验证；真实研究服务还须按 Gateway 和组件访问需求配置网络。不能直接把该预检单元当成已完成的生产服务。

另外，对 36 个研究账号逐一核对 UID、目录属主/权限、仅私有组、本人目录可写、另一个成员目录不可读及 sudo 授权，共 216 项通过。管理员执行 `sudo -l -U <user>` 即使显示“不允许 sudo”也可能退出 0，因此检查实际策略输出。Lead 使用现有本机 SSH agent 与公钥登录 `qc-chenyuanheng` 成功，当前目录和可写目录均为其个人 workspace。

本地验收记录保存在忽略目录：`.quantcode/serverc-runtime-preflight-20260907.json`、`.quantcode/serverc-research-runtime-preflight-20260907.json`、`.quantcode/serverc-runtime-manifest-20260907.json`、`.quantcode/serverc-research-accounts-verification-20260907.json`。开通计划的 9 项回归及全量 Python 1,163 passed / 4 skipped 通过。

## 后续接线

1. 将成员本机签发的 Gateway 凭据安全传递到对应远程 MCP，绑定 actor 与注册表 UID；不能接受客户端任意指定 Linux 用户或共享一个会话文件。
2. 用受控运行入口落实每成员/会话的状态挂载、生命周期和资源限制；研究源码与凭据保持不同权限面。
3. 对共享组 Memory、跨人审批、组织历史和后台消费确定服务端权威存储；每人私有状态目录不能替代共享知识库。
4. 配置正式 provider、GitHub broker、后台同步与 Dream；生产部署仍由 Admin 受控接口承接。

安装包、签名和量化组件 API 继续按用户要求暂缓。

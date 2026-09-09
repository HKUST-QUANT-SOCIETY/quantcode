# 个人原生执行宿主安装准备

状态：源码已提供计划与安装准备入口，尚未执行安装、构建、测试或远端操作。安装成功状态是 `INSTALLED_NOT_STARTED`，不是运行验收通过。本工具不启动、重启、enable 服务，不执行 daemon-reload，不改变已有 `current` 指针或覆盖成员历史。

## 复用范围

`scripts/install_native_host.py` 使用现有 `frontend/packages/opencode/script/build.ts` 产出的 Linux CLI，并以其已有 `serve` 命令运行 Session/Prompt/Tools/Provider 引擎。原构建将 parser worker 和 TUI worker 列入 compile entrypoints，但发布打包的是整个 `bin/`；安装器因此核对并复制完整 `--artifact-root` 资产集、保留相对文件名，不能仅凭可执行文件存在推断所有 native/worker 资产齐全。没有新增 Agent 循环、HTTP 服务实现或任务调度器。

成员身份来自 `scripts/provision_research_accounts.py` 已保存的研究账号 registry 和已审核 roster。工具复用现有 `trusted_path` 管理员路径检查与公钥 fingerprint 计算，核对实际 Linux UID/GID、用户名、工作目录、附加组、公钥集合和选定 fingerprint。默认计划仅读取文件和账号/端口元数据，不调用用户创建、密钥工具、Python import 探测或 systemctl。

现有 `install_remote_mcp.py` 只部署 Python MCP，不能当作原生宿主。新入口沿用它的管理员管理源码、成员独立源码视图及 `.quantcode` 状态映射方式，但真正启动目标是同仓 compiled CLI。Python 继续承担组织服务与确定性适配，不配置另一份模型 key。

## 准备输入

- 已在可信构建环境生成并审阅的当前平台 Linux CLI、完整 SHA-256、明确 release 名和来源 commit；本脚本不构建、下载或执行该文件。
- 管理员持有的组织服务源码 release，含 `quantcode/runner/schemas/tools/flows/configs/.opencode/dream`、`pyproject.toml`、`uv.lock`、原许可证及已安装 `.venv`。源码不能含真实 roster、成员 `.quantcode` 或运行凭据。依赖环境须已单独按锁文件安装和审阅；本脚本不安装依赖，也不把静态检查当作依赖可运行证明。
- root 私有的已审核 roster、研究账号 registry，明确原 actor 和所选已登记公钥 fingerprint。
- gateway 的 HTTPS 或回环 HTTP origin，以及一个未监听、未被既有安装清单预留的非特权回环端口。
- 与研究根、源码 release 互不重叠的安装、XDG 控制和 unit 目录；默认分别为 `/opt/quantcode/native-hosts`、`/var/lib/quantcode-native`、`/etc/systemd/system`。

来源 commit 是维护者提交的构建来源声明；实际复制的二进制与组织源码各自有摘要，不能仅凭 commit 字符串断言构建可复现。compiled CLI 保留的 OpenCode 原许可证默认为 `<runtime-root>/frontend/LICENSE`；如果组织 release 不带 frontend，可显式提供同一来源的 `--cli-license` 文件。

## 计划与安装（命令示例，本次未运行）

```sh
python scripts/install_native_host.py \
  --runtime-root /opt/quantcode/runtime/reviewed-source \
  --artifact-root /opt/quantcode/artifacts/opencode-linux-x64/bin \
  --binary /opt/quantcode/artifacts/opencode-linux-x64/bin/opencode \
  --binary-sha256 REVIEWED_64_HEX_SHA256 \
  --source-commit REVIEWED_SOURCE_COMMIT \
  --cli-license /opt/quantcode/artifacts/OPEN_CODE_LICENSE \
  --release native-20260909 \
  --actor REGISTERED_ACTOR \
  --fingerprint REGISTERED_PUBLIC_FINGERPRINT \
  --roster /etc/quantcode/approved-roster.yaml \
  --gateway http://127.0.0.1:4097 \
  --port 6096
```

默认输出计划摘要、原成员绑定、目标路径、unit 预览及 `execution: not_started`、`catalog: not_published`、`model: not_configured`。不会输出或读取现有 token/访问密码。

维护者核对计划后，以 Linux 管理员身份对同一组参数增加 `--apply --expected-plan <完整plan_digest>`。apply 在原有文件锁下重新核对计划；输入、账号、源码、端口或目的路径变化则拒绝。只创建一个原 actor/release 的新安装和独立 unit，不能以同名重跑覆盖上一份安装。部分失败留下新目录供维护者核对，不自动删除用户数据或回退已有服务。

## 新安装内容

- `<install-root>/<actor>/<release>/bin/`：完整已审核构建资产，管理员所有，CLI 与配套文件保留原相对名；unit 使用该 CLI 的固定 `serve --hostname 127.0.0.1 --port ... --no-mdns`，不从模型参数选择命令。
- `backend/`：管理员管理的组织源码副本、原许可证和原 `.venv` 引用；`.quantcode` 映射至本次新控制目录的 `python/`。工作区内的研究修改不能覆盖安装源码。
- `identity.pub`：选定已登记公钥，不是私钥。`host.env` 只含本次隔离服务的固定宿主路径和迁移开关；账号/组/角色仍由 gateway 登录确定，不以环境变量伪造。
- `access.env`：新生成的随机访问密码，只写入 root `0600` 文件，由 systemd `EnvironmentFile` 读取。密码不出现在 unit 的 `ExecStart`、命令参数、报告或日志；维护者通过既有安全渠道向该成员提供连接凭据。本工具不做分发。
- `<state-root>/<actor>/<release>/`：成员拥有的 `0700` XDG 配置/数据/状态/缓存、身份、GitHub、Python 历史和知识候选目录，全部在研究根之外。当前发布不会复用或覆盖旧 session/auth/checkpoint。
- 新 `quantcode-native-<actor>-<release>.service`：以已登记 UID/GID 执行，保留 systemd 权限隔离和原引擎的文件/Shell sandbox；仅研究目录和本次控制目录可写。`Restart=no`，安装动作不启动它。

unit 必须在后续已授权的运行验收中再由维护者加载和启动。客户端使用组织配置的 HTTPS 入口或已核验 SSH 隧道连接回环端口，不能直接暴露未认证端口；桌面仍用本机 SSH agent 完成成员登录。共享 gateway 可服务多成员，但每个原生宿主进程、会话文件及访问密码必须按成员隔离。

## 任务开始前仍需完成

1. 检查已安装依赖、平台 sandbox 和 gateway 的当前原生任务/Gate/审核 API；不能把旧 Python MCP 可连视为它们已就绪。
2. 复用现有 `quantcode.catalog.export`、`publish-quantcode-tools.ts` 与真实 MCP 配置发布审核目录。初始配置只有本机组织 MCP 定义，使用当前 `ConfigMCPV1.Local` 的 `type/command/cwd/environment/enabled` 字段，没有伪造 published 目录或共享 Blackboard 数据库。
3. 通过当前 gateway 登录核对 roster 工作区；额外 checkout 复用 `enroll-quantcode-workspace.ts` 显式登记。共享知识/Blackboard 需真正组织服务的配置，不能将本次成员私有目录当作共享事实源。
4. 桌面选择这个个人宿主，在同一 Provider 中保存一次 URL/API Key/模型；本安装不接受或生成 `QUANTCODE_API_KEY`。随后验证授权文件、实际已接入组件、事件、用量、取消及重开继续，才可判断远程原生任务闭环。

上述步骤属于剩余集中验收与真实部署工作。本轮只写入安装准备脚本、说明和隔离测试源码；不声称服务已安装或任务已运行，也不把现有桌面登录成功当作远程研究执行通过。

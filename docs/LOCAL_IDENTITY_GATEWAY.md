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

正式 roster 必须包含 actor_id、group、role、workspace_id、workspace_path；REVIEW_REQUIRED 候选会被拒绝。不得通过修改状态字段跳过人员冲突审核。

启动独立本地 gateway 的命令模板：

```sh
python -m quantcode.gateway --roster /absolute/approved-roster.yaml --database /absolute/private/identity-gateway.db --port 4097
```

此服务默认仅监听回环地址；远程使用需要受控 TLS 入口。本轮没有代用户启动服务、改动正式 roster 或重启现有 Dev。

## 登录路径

设置页 → 本机公钥身份 → 连接 → 宿主调用 SSH agent 签名 → gateway 验证一次性 challenge 与 roster → 本机保存会话凭据 → 重连 QuantCode MCP → 核对同一会话 → 刷新组、角色、工作区和目录。

界面不接收任意命令、可执行路径、私钥、签名或 token。服务端只执行宿主预先配置的固定命令。gateway 每次查询重验 roster，撤销/角色变化/过期要求重新登录。

## 验收证据与剩余接入

`tests/test_identity_gateway.py` 已用独立临时 SSH agent 和临时密钥执行真实签名，验证一次性 challenge、会话哈希持久化、退出/过期、角色/组/权限/工作区变更撤销，以及待审核 roster 拒绝签入。当前全量结果见 [功能验收台账](audit/FULL_PRODUCT_AUDIT_2026-09-05.md)，避免在接入指南重复维护滚动数字。没有修改或加载用户实际密钥。

宿主错误配置、并发登录与 MCP 会话一致性的完整链路，以及浏览器身份选择→签入→工作区更新仍待专项验收。现有 4096 进程未加载新增身份接口，MCP 未连接；正式人员授权及外部研发 SSH 环境也仍需正确配置。

## GitHub 凭据绑定

宿主可配置 `QUANTCODE_GITHUB_CREDENTIALS_FILE`，指向服务账号拥有且权限 0600 的 JSON 映射：

```json
{"subjects":{"github-login":{"token_file":"/absolute/private/github-token"}}}
```

token 文件同样要求 0600、服务账号所有，内容为已有账号凭据。映射按正式 roster 的 github_subject（小写）读取，不从浏览器或 Agent 参数选择身份。每次查询重读，便于撤销或轮换；不把 token 写入 SessionContext、checkpoint 或日志。GitGraph/Pop 和已认证 PR 读取还会验证实际账号与 Team/repo 权限，映射存在本身不授予仓库权限。当前没有创建或导入任何真实凭据。

## Gateway 后台 GitHub 同步

gateway 启动时默认运行后台同步循环，每轮完成后等待 60 秒；`--github-sync-interval 0` 可禁用，非零值至少为 60。gateway 进程也必须继承 GitHub 凭据映射环境变量。

同步只针对仍有效的 gateway 会话，逐个重新验证会话、正式 roster 和 GitHub 授权范围。同身份和工作区的多个登录去重处理；退出登录、撤销、权限变化或过期后不再为该会话开启新一轮同步。不创建永久服务账号授权，不因浏览器关闭而延长会话。

同步复用 GitGraph 的 SQLite 基线与 Pop，不在浏览器关闭时发送 OS 通知。认证 `GET /github-sync` 返回当前身份的最近一次尝试状态和起止时间；STARTED 只表示曾开始，不能据此证明进程仍运行。失败记录只保存异常类型，避免泄漏传输凭据。worker 与手动刷新并发时，较早开始的响应不能覆盖已提交的更新基线。

当前仅已补入代码，未启动服务或验证真实 GitHub 同步；操作系统级进程托管仍需在部署时配置。

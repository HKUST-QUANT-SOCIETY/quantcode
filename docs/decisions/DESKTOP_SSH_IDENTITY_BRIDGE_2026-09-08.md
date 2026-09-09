# 桌面 SSH 身份桥

这是运行时内化的首次登录接线说明。认证复用已有 gateway challenge/verify 和系统 OpenSSH；没有新增 Agent 执行器。源码交付后仍需完成桌面 UI 核验，再进入用户要求的完整用例测试。

## 固定链路

1. renderer 只提交已经保存的研究宿主 `server` key。Electron IPC 在主进程用 `resolveResearchConnection` 取得该连接，不能由 renderer 指定 URL、密码、公钥路径、gateway、组或 actor。
2. 主进程调用该宿主固定 `/experimental/quantcode/identity/challenge`。宿主用管理员配置的 `QUANTCODE_PUBLIC_KEY_FILE` 和 `QUANTCODE_GATEWAY_URL` 调已有 `/auth/challenge`。
3. 宿主返回 `{challenge_id, public_key, fingerprint, nonce, ttl_seconds, gateway_origin}`，不返回 token。挑战在宿主绑定配置摘要、原凭据摘要和最多 60 秒有效期。
4. Electron 检查公钥指纹、`quantcode-login` nonce 格式及本机 `ssh-add -L` 中的相同公钥，在专用临时目录调用固定参数 `ssh-keygen -Y sign -U -f <public-key> -n quantcode <challenge>`。只访问 SSH agent，不读取私钥或转发 agent。临时目录在结束或错误时清理。
5. 主进程只向同一已保存宿主的 `/experimental/quantcode/identity/verify` 发送 `{challenge_id, signature}`。宿主消费一次性挑战，重验配置和原凭据，再向原 gateway verify。
6. token 由个人研究宿主保管。先写入同目录的私有 `.pending` 记录，重验网关会话，撤销并删除旧 token，再原子替换当前记录。失败时保留待撤销记录；下一次连接或退出先撤销该记录。凭据文件为 0600，既有 0755 目录可继续使用，但目录必须属于宿主账户且其他账户不可写入。

## 返回与取消

主进程公开 `inspect(connection, options)`、`connect(connection, options)`、`disconnect(connection, options)`。`options` 可传 `signal` 和 `checkTarget`；窗口销毁、主 frame 导航和 renderer 崩溃可中止网络请求和 OpenSSH 子进程，签名前、verify 前及返回前检查已保存的目标连接。renderer 的 `identity.cancel({server})` 只取消同一窗口且宿主 key 相同的进行中请求；不影响另一宿主的新请求。

取消已经送达 verify 的请求不能保证撤销登录。界面会提示刷新原宿主的实际身份状态，已登录时由明确退出操作撤销，不伪称回滚。

renderer 仅接收 `actor_id`、`session_id`、公钥指纹、roster 业务组、有效期等摘要。认证成功返回 `status: connected`，同时明确 `execution_status: disconnected`。执行宿主、MCP、工作区就绪必须单独确认，不能由登录结果推断。

## 部署边界

本桥要求一个成员独立的研究宿主进程、身份文件和访问凭据。多个成员不能共用一个可被登录接口替换的进程级 `QUANTCODE_IDENTITY_SESSION_FILE`。共享 gateway 可以处理多成员，原生执行进程仍须隔离；本变更没有交付通用远端进程启动器，也没有把现有 remote MCP 服务当成原生执行服务器。

`localIdentity` 和退出已不依赖 Python checkout。原 `signInLocalIdentity` 仅保留开发/旧本机路径；桌面远端登录使用上述主进程握手。主进程不提供独立的“签任意 nonce”IPC。

本次未执行测试、构建、真实登录、凭据读取或服务重启；验收不能据此记为通过。

已补回归源码：Desktop HTTP 边界用例覆盖 base path、nullable sidecar 凭据、摘要剔除凭据字段、有效期和执行状态分离、请求前取消、禁止任意签名；既有隔离 gateway/独立 SSH agent 夹具新增调用实际 Electron 主进程模块与宿主 HttpApi 的登录、轮换、撤销和签名前取消流程。它们仍需在 UI 通过后的测试阶段执行，不能替代实际打包 Electron 登录核验。

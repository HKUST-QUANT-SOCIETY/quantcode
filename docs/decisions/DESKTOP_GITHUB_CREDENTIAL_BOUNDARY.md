# 桌面 GitHub 凭据与研究宿主连接

状态：内部接线已实现，未操作真实账号、读取真实凭据或执行测试。本变更只覆盖 GitHub，不改变组织 SSH 登录流程。

桌面提供“通过 GitHub 登录”和“使用本机凭据”。两种方式均由 Electron 主进程 `src/main/github.ts` 执行。前者复用本机 `gh auth login --web` 的设备授权与系统凭据存储；后者先查询当前组织账号的 `gh auth token`，再尝试本机 Git credential helper。所有查询固定为 `github.com`，不接受模型或网页提供的命令、路径、token、账号或任意服务器地址。

renderer 通过 platform/preload 只发送已选择的 `server` key 和 `mode`，只收到状态、GitHub 用户名、目的宿主名及短时授权码。主进程从既有保存的 server 配置或内置 sidecar 的初始化结果取得连接，复用 `quantcode-connection.ts`；仅允许 HTTPS 或本机回环 HTTP，禁止跟随跳转。GitHub token 不经 renderer、IPC 返回值、工具参数或日志。UI 明确显示凭据将用于哪个研究宿主。

## 固定接入协议

- `GET /experimental/quantcode/github/credential/prepare`：当前 gateway roster 登录确定完整 owner、GitHub subject，返回一次性 nonce、登录 ID、owner 摘要与过期时间。
- `POST /experimental/quantcode/github/credential/import`：只接受桌面主进程直送的对应 nonce/login/owner digest/token，不接受带浏览器 Origin 的请求。nonce 使用后移除，过期或身份变化拒绝；该接口不注册为 Agent 工具。
- 主进程先向固定 GitHub `/user` 验证账号，再重新准备同一宿主/同一 owner 的导入；宿主也独立验证 GitHub `/user` 和前后 gateway 身份。不同账号、撤销、连接改动、宿主协议缺失都明确失败，不转用远端已有账号。

宿主继续使用 `quantcode/github_host.py` 和原有 `subjects → token_file` 凭据映射。已验证 token 写入私有、非覆盖、按摘要命名的文件，映射在原进程锁内原子替换；后验身份失败时只回滚本次准确映射，保留原 token 与原连接。状态查询和 GitGraph 使用已接入映射，不再偷偷寻找研究宿主上的其他 gh 凭据。

现有 `0755` 凭据父目录继续兼容：必须为当前宿主所有者、规范无符号链接目录，且组和其他用户均不可写（`mode & 022 == 0`）。目录可列文件名不授予读取 `0600` 凭据正文或替换目录项的权限，因此不强制将现有目录改为 `0700`。映射与 token 仍须为宿主私有普通文件，无符号链接或额外硬链接，读取使用 `O_NOFOLLOW` 句柄并重验文件和父目录身份；创建 token 和替换映射仍使用私有临时文件及原有锁，不修改用户已存在目录的权限。

## 兼容与限制

浏览器版可继续在研究宿主完成 GitHub 浏览器授权，但会说明授权保存在该宿主；“使用本机凭据”被禁用，不能将远端凭据称为此电脑凭据。桌面本机缺少 gh 时，浏览器方式明确报告缺少本机 CLI；本机凭据方式仍可使用已安装 Git 的 credential helper。不会自动下载安装程序、读取其他域凭据或回落到远端账号。

中途取消、窗口关闭、选择其他宿主或当前组织登录变化会取消本次授权进程，停止后续凭据传输。网络响应丢失不能作为“宿主未保存”的证据；客户端要求刷新连接状态，不自动重复写入或声称旧状态必然未变。

待验证：桌面 main/preload/platform 接线、两个本机登录方式、缺 gh/Git/helper、错误 GitHub subject、TLS/跳转拒绝、取消和换宿主、nonce重用、身份撤销、映射失败回滚、SDK 生成与真实 GitGraph 读取。以上源码交付不等于这些验收已通过。

# QuantCode Test V1.0 安装与连接

成员的完整教程见 [README 首次使用](../README.md#首次使用)，下载入口为 [Test V1.0 Release](https://github.com/HKUST-QUANT-SOCIETY/quantcode/releases/tag/quantcode-v1.0.0-test.1)。

## 安装包

| 平台 | 文件 |
| --- | --- |
| macOS Apple Silicon | `quantcode-1.0.0-test.1-mac-arm64.dmg` |
| macOS Intel | `quantcode-1.0.0-test.1-mac-x64.dmg` |
| Windows x64 | `quantcode-1.0.0-test.1-win-x64.exe` |

这是公开仓库中的内部测试预发布，安装包未做平台代码签名，自动更新关闭。下载后使用同一 Release 的 `SHA256SUMS` 和 `release-manifest.json` 核对来源、版本和平台信任状态。正式签名版的发布门槛保持独立，详见 [发布说明](../frontend/packages/desktop/QUANTCODE_RELEASE.md)。

Mac 打开 DMG 并将 QuantCode 拖入应用程序；Windows 运行当前用户安装器。成员不需要安装 Python、Bun、Node.js 或另一套 OpenCode。

## 服务端

Test V1.0 需要 Server C 上的常驻组织网关和个人研究宿主。每位成员使用已有 SSH 公钥登记，由名册绑定组、角色和工作目录；个人宿主的状态与访问凭据相互隔离。桌面中的本机服务不能替代组织的身份、共享 Memory 和远程工作区。

模型由组织测试服务统一提供。模型 Key 不随安装包分发；成员如需自定义模型，可以在个人宿主的模型设置中保存一份 URL/API Key 配置。

## 第一次连接

1. 准备已登记私钥，并加载到本机 SSH Agent。Windows 需先启用系统 SSH Authentication Agent 服务。
2. 用管理员分配的 SSH 用户名登录 Server C，读取本人 `~/.quantcode/test-v1/connection.json`。
3. 按 README 建立 SSH 隧道，保持窗口开启。
4. 在 QuantCode“设置与登录 → 管理服务器”添加本机隧道地址和个人访问凭据。
5. 选择对应公钥连接，确认身份、组和授权目录。
6. 新建任务，按方案面板确认后使用“继续执行”。

连接文件包含个人访问凭据，不应提交 GitHub。私钥正文不上传给研究宿主或模型。

## 任务与升级

任务、文件和产物由研究宿主持久保存。重新连接后可查看自己的历史任务；停止执行使用任务的停止操作，退出登录撤销当前会话。

测试版采用手动升级：退出应用，下载同架构新包并核对后安装。不要在没有备份的情况下用旧版本覆盖新版本。桌面产品数据使用独立身份 `org.hkust.quantcode`，不与 OpenCode 共用更新状态。

Test V1.0 的实际验收范围和已知限制见 [验收摘要](TEST_V1_ACCEPTANCE.md)。真实量化数据和组件仍需对应服务及权限，界面显示未连接时不会伪造业务结果。

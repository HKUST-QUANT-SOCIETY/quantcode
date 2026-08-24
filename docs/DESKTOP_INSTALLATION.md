# QuantCode 桌面端安装与升级

QuantCode 桌面端复用 OpenCode 的 Electron 桌面壳，并使用 QuantCode 自己的产品身份、界面和发布通道。普通组员安装正式包后不需要安装 Bun、Node.js 或完整 OpenCode 源码。

> 当前状态（2026-08-19）：macOS Apple Silicon、macOS Intel、Windows x64、Linux x64 的 QuantCode 安装产物已由 GitHub Actions 实际构建成功；Linux 产物包括 AppImage、DEB、RPM。它们均为 unsigned 测试 artifact，正式 Release 尚未发布。正式外发仍需 Apple Developer ID 签名与公证、Azure Trusted Signing，以及私有 Release 仓库的自动更新访问方案。当前测试包不能当作正式安装包外发。Linux ARM64 尚未纳入正式矩阵。

正式安装包完成验收后将发布在 [QuantCode Releases](https://github.com/HKUST-QUANT-SOCIETY/quantcode/releases)。当前发行矩阵覆盖 macOS、Windows 和 Linux x64：

| 平台 | 安装文件 | 适用场景 |
| --- | --- | --- |
| macOS Apple Silicon | `quantcode-<version>-mac-arm64.dmg` | M1/M2/M3/M4/M5 Mac |
| macOS Intel | `quantcode-<version>-mac-x64.dmg` | Intel Mac |
| Windows x64 | `quantcode-<version>-win-x64.exe` | Windows 10/11 64 位 |
| Linux x64 | `quantcode-<version>-linux-x86_64.AppImage` | 便携运行；生成完整性 metadata，自动更新当前关闭 |
| Linux x64 | `quantcode-<version>-linux-amd64.deb` | Debian/Ubuntu 手动安装 |
| Linux x64 | `quantcode-<version>-linux-x86_64.rpm` | Fedora/RHEL 系手动安装 |

## 安装前准备

组员需要：

1. Agent Group 分配的组别与 Server B 账户。
2. 已登记公钥对应的 SSH 私钥；私钥只保存在成员设备上，不提交到 Git，也不上传到 QuantCode Release。
3. 如需直接调用模型，按组内规范准备对应 API 凭据。

QuantCode 桌面端包含 Electron 运行时和本地 OpenCode 服务，不会在每次启动时重新创建 Python virtual environment，也不会重复安装 OpenCode。研究任务所需的集中式运行环境由 Server B 维护。

## macOS

1. 根据 CPU 下载 `arm64.dmg` 或 `x64.dmg`。
2. 打开 DMG，将 `QuantCode.app` 拖入“应用程序”。
3. 从“应用程序”启动 QuantCode。

正式版本必须经过 Developer ID 签名和 Apple 公证。内部未签名测试包只用于开发验收，出现 Gatekeeper 提示时不要向外部分发。

## Windows

1. 下载 `quantcode-<version>-win-x64.exe`。
2. 运行安装程序。QuantCode 默认安装到当前用户，无需管理员权限。
3. 从开始菜单启动 QuantCode。

正式版本必须使用 Azure Trusted Signing，并校验签名证书 Subject 与 updater 的 `publisherName` 一致。未签名的内部测试包可能触发 Microsoft Defender SmartScreen，不应作为正式版本传播。

## Linux x64

1. AppImage 可直接赋予执行权限后运行。`latest-linux.yml` 会记录 SHA-512 完整性信息，但它不是独立的来源签名；在客户端实现签名 metadata 或等价信任锚之前，Linux 自动更新保持关闭。
2. Debian/Ubuntu 使用 `.deb`，Fedora/RHEL 系使用 `.rpm`；这两类包作为手动安装资产发布，升级时重新安装新包。
3. 当前正式矩阵只覆盖 x86_64；ARM64 包仍需独立 runner 和桌面会话验收。

## 首次启动

1. 选择所属研究组。
2. 选择 `Server B`。
3. 选择或确认本机 SSH 私钥。
4. 等待右上角状态变为“已连接”。
5. 新建研究任务，确认 Skill、Memory 和 HumanGate 状态可用。

应用数据与 OpenCode 隔离保存：

- macOS：`~/Library/Application Support/org.hkust.quantcode`
- Windows：`%APPDATA%\org.hkust.quantcode`
- Linux：`~/.config/org.hkust.quantcode`

## 自动升级

macOS/Windows 升级代码已配置为每十分钟检查一次 QuantCode GitHub Release 的 `latest*.yml`，并在用户确认后下载和重启。这个能力目前尚未完成生产验收：Release 仓库是 Private，浏览器登录不会自动把 GitHub 权限交给桌面 updater。正式启用前必须将更新资产公开，或实现不内置长期 PAT 的受控更新服务/用户授权方案。Linux 即使以后使用公开 feed，也必须先增加独立的签名 metadata 或等价信任锚，不能只依赖可与安装包一起被替换的 SHA-512 文件。

以下情况需要手动下载安装包：

- 从未签名的内部测试版切换到正式签名版。
- 自动更新元数据尚未发布。
- Release 仓库仍为 Private，桌面 updater 没有读取权限。
- 企业网络阻止访问 GitHub Release。

## 开发者源码运行

只有参与桌面端开发的人才需要 Bun 和 OpenCode fork：

```bash
git clone https://github.com/HKUST-QUANT-SOCIETY/opencode.git
cd opencode
bun install
bun run dev:desktop
```

源码开发模式与正式安装包使用不同的数据目录，不应拿开发模式替代组员安装验收。

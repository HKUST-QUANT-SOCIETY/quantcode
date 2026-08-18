# QuantCode 桌面端安装与升级

QuantCode 桌面端复用 OpenCode 的 Electron 桌面壳，并使用 QuantCode 自己的产品身份、界面和发布通道。普通组员安装正式包后不需要安装 Bun、Node.js 或完整 OpenCode 源码。

正式安装包发布在 [QuantCode Releases](https://github.com/HKUST-QUANT-SOCIETY/quantcode/releases)。每个版本包含下列文件：

| 平台 | 安装文件 | 适用场景 |
| --- | --- | --- |
| macOS Apple Silicon | `quantcode-<version>-mac-arm64.dmg` | M1/M2/M3/M4/M5 Mac |
| macOS Intel | `quantcode-<version>-mac-x64.dmg` | Intel Mac |
| Windows x64 | `quantcode-<version>-win-x64.exe` | Windows 10/11 64 位 |
| Linux x64 | `quantcode-<version>-linux-x64.AppImage` | 无需系统安装 |
| Debian/Ubuntu x64 | `quantcode-<version>-linux-x64.deb` | 受系统包管理器管理 |
| Fedora/RHEL x64 | `quantcode-<version>-linux-x64.rpm` | 受系统包管理器管理 |

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

正式公开版本应经过 Developer ID 签名和 Apple 公证。内部未签名测试包只用于开发验收，出现 Gatekeeper 提示时不要向外部分发。

## Windows

1. 下载 `quantcode-<version>-win-x64.exe`。
2. 运行安装程序。QuantCode 默认安装到当前用户，无需管理员权限。
3. 从开始菜单启动 QuantCode。

正式公开版本应使用 Azure Trusted Signing。未签名的内部测试包可能触发 Microsoft Defender SmartScreen，不应作为正式版本传播。

## Linux

### AppImage

```bash
chmod +x quantcode-<version>-linux-x64.AppImage
./quantcode-<version>-linux-x64.AppImage
```

### Debian / Ubuntu

```bash
sudo apt install ./quantcode-<version>-linux-x64.deb
```

### Fedora / RHEL

```bash
sudo dnf install ./quantcode-<version>-linux-x64.rpm
```

Linux 桌面入口、可执行文件和窗口身份均使用独立的 QuantCode 标识，不会覆盖系统中已经安装的 OpenCode。

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

正式安装包每十分钟检查一次 QuantCode GitHub Release 的 `latest*.yml` 更新元数据。发现新版本后，用户确认下载和重启；不会静默替换正在运行的研究任务。

以下情况需要手动下载安装包：

- 从未签名的内部测试版切换到正式签名版。
- 自动更新元数据尚未发布。
- 企业网络阻止访问 GitHub Release。

## 开发者源码运行

只有参与桌面端开发的人才需要 Bun 和 OpenCode fork：

```bash
git clone https://github.com/HKUST-QUANT-SOCIETY/opencode.git
cd opencode
bun install
OPENCODE_CHANNEL=quantcode bun --cwd packages/desktop dev
```

源码开发模式与正式安装包使用不同的数据目录，不应拿开发模式替代组员安装验收。


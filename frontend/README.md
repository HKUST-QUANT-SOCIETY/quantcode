# QuantCode 前端与桌面工作区

本目录是 quantcode 单仓库的一部分，无需克隆 opencode 仓库。

- `packages/app`：研究工作区 UI。
- `packages/desktop`：Electron 桌面壳及安装包构建。
- `packages/opencode`：本地宿主服务。
- 其余工作区包：共享协议、SDK、组件与底座依赖。

在 quantcode 根目录执行 `bun run install:frontend`，随后 `bun run dev:quantcode` 或 `bun run dev:desktop`。类型检查和测试仍在各 package 目录运行，避免触发全底座无关用例。

详见 [单仓库说明](../docs/REPOSITORY_LAYOUT.md) 和 [当前台账](../docs/audit/FULL_PRODUCT_AUDIT_2026-09-05.md)。原 OpenCode 说明保存在 [README.upstream.md](README.upstream.md)，版权保留在 [LICENSE](LICENSE)。嵌套 `.github/workflows` 是历史来源资料，产品 workflow 以仓库根目录为准。

# QuantCode 单仓库开发

只需克隆 `HKUST-QUANT-SOCIETY/quantcode`，无需第二个 Git 仓库或子模块。

- 根目录 `quantcode/`、`runner/`、`tools/`、`schemas/`：Python 后端。
- `frontend/packages/app/`：研究工作区 UI。
- `frontend/packages/desktop/`：Electron 桌面壳与安装包构建。
- `frontend/packages/opencode/`：本地宿主服务；其余 frontend 工作区保留底座依赖。
- `.github/workflows/quantcode-desktop.yml`：本仓库手动构建与发布入口，默认不发布。

```sh
git clone https://github.com/HKUST-QUANT-SOCIETY/quantcode.git
cd quantcode
uv sync --extra dev
bun run install:frontend
bun run dev:quantcode
```

`bun run dev:desktop` 启动桌面开发；`bun run build:web` 构建网页；`bun run build:desktop` 构建桌面代码；`bun run package:desktop` 生成当前平台安装包。源码迁移不等于签名/安装包验收，现有服务不会因迁移自动重启。

默认开发端口为后端 `4096`、网页 `4444`。端口已被占用时可使用 `QUANTCODE_BACKEND_PORT=4196 QUANTCODE_APP_PORT=4544 bun run dev:quantcode`，并确保前端会同步连接到该后端端口，无需停止其他工作区。

## 来源与边界

完整受版本控制的前端工作区源自 `HKUST-QUANT-SOCIETY/opencode@d81ed480bc1d2c7976cc96b6f8bb964a7e1220c5` 并已纳入当前 QuantCode 单仓库。保留 `frontend/LICENSE`、上游版权和配套源码；未导入上游仓库 Git 元数据、node_modules、本机密钥或构建产物。后续产品修改统一提交当前仓库。

`frontend/.github/workflows/` 是保留的上游工作流资料，GitHub 不会执行嵌套工作流；本仓库只启用根目录 `.github/workflows/`。桌面 workflow 已适配 frontend 路径，跨平台安装包仍需单独签名和发布环境。

统一回归入口：`QUANTCODE_TEST_PYTHON=.venv/bin/python PLAYWRIGHT_BASE_URL=http://localhost:4544 bun run check:product`。URL 必须指向从本仓库启动的 QuantCode Dev；脚本使用 `playwright.quantcode.config.ts`，不会自动启动或重启服务。启动器优先使用根目录 `.venv` 中的 Python。

当前验收：Python 1,142 项通过、4 项跳过；Ruff 0 错误；组件 126 项通过；app/opencode/desktop 类型检查和网页构建通过；新构建产物 12 项 Headless 通过；Dev 使用独立端口时 16 项 Headless 通过。详见 [验收台账](audit/FULL_PRODUCT_AUDIT_2026-09-05.md#单仓库验收)。真实身份与组件服务仍按台账单独验收。

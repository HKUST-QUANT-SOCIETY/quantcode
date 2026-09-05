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

## 来源与边界

完整受版本控制的前端工作区导入自 `HKUST-QUANT-SOCIETY/opencode@d81ed480bc1d2c7976cc96b6f8bb964a7e1220c5`。保留 `frontend/LICENSE`、上游版权和配套源码；未导入原仓库 Git 元数据、node_modules、本机密钥或构建产物。旧仓库保留为历史来源，后续产品修改统一提交本仓库。

`frontend/.github/workflows/` 是导入的上游工作流资料，GitHub 不会执行嵌套工作流；本仓库只启用根目录 `.github/workflows/`。桌面 workflow 已适配 frontend 路径，尚未执行迁移后的跨平台安装包矩阵；签名服务/环境需在 quantcode 仓库配置。

统一回归入口：`QUANTCODE_TEST_PYTHON=.venv/bin/python PLAYWRIGHT_BASE_URL=http://localhost:4444 bun run check:product`。URL 必须指向从本仓库启动的 Dev；脚本不会自动启动或重启服务。启动器优先使用根目录 `.venv` 中的 Python。

迁移验收：Python 1,139 项通过、4 项跳过；组件 126 项通过；app/opencode/desktop 类型检查和网页构建通过；新构建产物 12 项 Headless 通过。详见 [验收台账](audit/FULL_PRODUCT_AUDIT_2026-09-05.md#单仓库迁移验收)。真实身份与组件服务仍按台账单独验收。

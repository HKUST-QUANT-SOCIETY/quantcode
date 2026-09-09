# 独立桌面 UI 验收宿主

当前 Server C 网关可能尚未部署 `/native-tasks/*`，返回 404 不能靠浏览器假接口补齐。UI 验收使用当前源码的真实 `IdentityGateway` 和 HTTP handler，在本机新端口运行；现有 Server C、本机宿主、真实 roster、凭据和数据库均不更改。

`scripts/prepare_desktop_ui_review.py` 已编写，本文命令尚未执行。它不是测试用例运行器，也不证明真实任务执行、模型、GitHub或 Server C 部署通过。

## 启动方式

以下只打印方案，不创建文件或进程：

```sh
cd /absolute/path/to/QUANTcode
.venv/bin/python scripts/prepare_desktop_ui_review.py plan
```

UI 验收阶段需要真正启动时，明确选择一个**不存在的新绝对目录**和两个未占用端口，例如：

```sh
.venv/bin/python scripts/prepare_desktop_ui_review.py serve \
  --directory /tmp/quantcode-ui-review-unique-run \
  --backend-port 4596 --app-port 4944
```

端口只是示例。脚本会拒绝已占用的前后端端口；网关默认绑定 `127.0.0.1:0`，由系统分配新的空闲端口，也可显式传入一个新的 `--gateway-port`。目录已存在即拒绝，不复用空目录或真实目录，也不接管、关闭或重启旧进程。

脚本生成独立的 `ui-fixture-admin`、`ui-fixture-analyst` 公钥和私钥、测试 roster、独立 SSH agent、会话文件和数据库。测试身份名称固定包含 `fixture`，没有真实成员名、GitHub subject、API Key 或额外资源授权。私钥只加载到本脚本新建的 SSH agent，真实 SSH agent 保持原状。

脚本输出一条 `env -i ... bun ... dev:quantcode` 命令，并保存到新目录中的 `launch-ui-command.txt`。在另一个终端运行这条命令才会启动新前后端。命令显式选择 fixture 宿主配置、SSH socket 和独立 HOME/XDG 目录，避免继承真实模型凭据、宿主配置或会话数据库。本轮只启动 admin UI；analyst 有独立配置和独立桌面目录，后续若需另一 UI 进程必须使用该 actor 的配置、目录以及另一组新前后端端口，不能在 admin 进程中换掉会话文件。

该脚本需保持运行。`Ctrl+C` 只停止它创建的网关和 SSH agent，并撤销本次生成的测试 bearer 会话。前后端由另一终端启动，需在其自己的终端结束；脚本不管理其他服务。新目录保留种子说明和数据库用于复核，包含测试私钥，仍按私有数据保管。

## 实际使用的契约

1. `/auth/challenge` 和 `/auth/verify`：使用新 SSH agent 对真实一次性 challenge 签名，取得真实 SessionContext；不直接写造身份表，也不跳过正式 roster 校验。
2. `/native-tasks/publish`：两个 fixture owner 分别发布默认 104 个带 `[UI FIXTURE · 无执行]` 标题的任务摘要，含主子关系与各状态，覆盖组织列表分页。`source_id` 也带 `ui-fixture`。不设置迁移 `read_only` 标记，不暗示存在原生执行记录。
3. `/native-tasks/artifacts/publish`：每个 owner 的首个任务含 35 项明确命名的 fixture 报告，覆盖产物分页；一个报告超过 64 KiB，按真实块长度、块 SHA-256 和全文 SHA-256 上传。一项仅投递引用，保留 `pending`；一项明确 `original_not_captured`。清单摘要按实际引用数组计算，使用网关原验证逻辑。
4. 桌面继续调用正式 `/experimental/quantcode/organizationTasks`、组织产物读取、身份和审批接口；没有额外的假 UI 路由，也不更改生产 handler。

`fixture-native-projections.json` 保存完整种子契约，并明确 `native_execution_evidence:false`。其中来源事件 ID、用量和任务状态是用于布局的合成值，不是实际模型或工具执行证据；不能计入 M1–M4 行为验收或真实模型用量。这个环境可核对桌面布局、加载状态、分页、产物字节传输、空态与身份切换边界；真实引擎、GitHub、外部组件及生产部署仍需独立验收。

普通研究任务不应在该 UI 环境执行。fixture 配置没有模型供应商或已发布工具目录，创建样例数据也从未启动 Agent。GitGraph 未配置真实 GitHub 凭据时应显示其真实未连接状态。

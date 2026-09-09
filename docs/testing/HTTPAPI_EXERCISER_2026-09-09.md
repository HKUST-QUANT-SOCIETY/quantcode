# HTTP API 严格验收

日期：2026-09-09。最终状态：**PASS**。完整原命令退出 0，未移除 `--fail-on-missing` 或 `--fail-on-skip`。

```sh
# frontend/packages/opencode
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy bun run test:httpapi
```

| 阶段 | 结果 | 含义 |
| --- | --- | --- |
| coverage | 259 pass / 0 fail / 0 skip / 0 missing / 0 extra | 236 条 OpenAPI 路由全部有登记场景；此阶段本身不发请求 |
| auth | 259 pass / 0 fail / 0 skip / 0 missing / 0 extra | 对真实路由验证 Basic 认证边界 |
| effect | 259 pass / 0 fail / 0 skip / 0 missing / 0 extra | 执行真实 middleware、参数解码、handler 与隔离存储断言 |

这是三个检查阶段，不计作 777 个互不重复的产品场景。完整最终日志：`/tmp/qc-httpapi-exercise-final-passed.log`。Opencode 全包 typecheck 亦通过，日志 `/tmp/qc-httpapi-scenarios-typecheck.log`。

## 补齐的覆盖

首轮有 48 条路由缺少场景。本轮在 `test/server/httpapi-exercise/quantcode-scenarios.ts` 新增 51 个场景覆盖全部 48 条，另含同一路由的关键拒绝分支。

- 模型代理拒绝回环目标，不发外部请求。
- 新宿主无身份配置时不展示身份；未签发 challenge、组选项覆盖和未配置退出均被拒绝。
- 工作区列表绑定实际 fixture 身份，仅返回明确授权根目录；缺少身份时返回声明的拒绝响应。
- 缺少任务、检查点、Gate 和产物资源时，实际 handler 返回声明的域错误；不把 500 视作通过。
- Analyst 不能通过 payload 中伪造 Admin 角色取得部署或回执核对权限。
- GitHub 未配置时返回明确错误；浏览器 Origin 不能导入凭据，本机凭据入口明确要求桌面。
- 能力审核拒绝 `model_approved`，方案拒绝把数组编码成字符串，执行锁恢复要求停止确认。
- 只读工具接口拒绝任意 `write` 工具名称，身份结果忽略调用者提供的 group 覆盖。

外部身份 authority 使用临时 loopback fixture，组织资源请求明确拒绝。目标路由本身没有被 mock；使用真实应用 HTTP handler、独立数据库与独立 Git 工作区。以上主要证明接口边界、拒绝路径及空态，不等于真实模型、跨成员审批和组织产物成功流程；阳性流程以独立 Python/Server C E2E 证据为准。

## 夹具修复

原 runner 先以旧模式创建项目，再由新 fixture 启用 native 模式。无 Git 项目会缓存为全局 `/`，随后按原生授权被拒绝。新 native fixture 使用明确的独立 Git 工作区，保留真实授权检查。

原 `file.read` 场景写入 `hello\n` 却断言 `hello`，已改为断言 `type=text` 和完整字节 `hello\n`。

认证 probe 不运行 scenario seed。原 probe 使用默认源码目录，实际创建源码实例并在一次 teardown 中挂起；本次保留 sample `/tmp/qc-httpapi-auth-cleanup.sample` 后停止该测试进程，未记为 PASS。现在认证 probe 复用一个独立 Git 临时项目，明确传入目录，并在探测结束后 abort controller，最终正常退出。旧两轮 probe 留下的四个本轮测试 worktree/branch 已核对并清理，其他已有 worktree 保留。

启动环境也清除继承的 `QUANTCODE_*`、SSH agent、GitHub 凭据与 channel，防止认证 probe 接触调用者真实宿主。每个 native fixture 仅在其 scope 内安装临时身份配置并自动恢复。

历史失败和复验日志保留：`/tmp/qc-httpapi-exercise-final.log`（48 missing）、`/tmp/qc-httpapi-quantcode-effect.log`（夹具问题）、`/tmp/qc-httpapi-exercise-final-complete.log`（旧换行断言）、`/tmp/qc-httpapi-exercise-final-verified.log`（认证 teardown）、`/tmp/qc-httpapi-effect-final.log` 和 `/tmp/qc-httpapi-auth-isolated-final.log`（分阶段复验）。

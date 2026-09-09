# Organization Catalog Pin Review

日期：2026-09-09。范围：`quantcode/catalog/organization-tools.review.json` 的六个源码 pin 漂移。仅更新逐项审阅的六个哈希；71 个源码条目与 22 个工具声明的集合不变。

## 原版本证据

六个原版本均已通过 SHA-256 精确匹配原 `reviewed_sources` 值，逐行差异基于这些匹配的原内容，不把 Git HEAD 差异误当作审核基线。`identity_login.py` 原 pin 对应 Git HEAD；其余通过撤销已识别的少量修改重建，匹配后才保存为 before。

完整旧/新哈希及重建方法见同目录 `CATALOG_PIN_REVIEW_2026-09-09.json`。旧/新源内容和六份补丁保存在 `/tmp/quantcode-catalog-pin-review-20260909/{before,after,patches}`。

## 逐项结论

| 文件 | 相对于原 pin 的实际变化 | 权限和效果结论 |
| --- | --- | --- |
| `.opencode/groups/model/tool_allowlist.yaml` | 仅两行注释调整；`read_blackboard` 已存在于原 pin 中 | 工具集合完全相同。`read_blackboard` 的 model/risk 组限制和 catalog `disabled` 状态不变 |
| `frontend/packages/opencode/src/quantcode/legacy-provider.ts` | `Stream.splitLines()` 改为当前 Effect API 的 `Stream.splitLines` | 修复 stdout 帧解析启动；帧 schema、序列/重放检查、当前身份与工作区复验、Provider 绑定、用量回执、无自动模型重试均保留 |
| `quantcode/identity_login.py` | 空的预置会话文件首次登录时不尝试撤销不存在的 token；失效错误增加 `AUTHENTICATION_REQUIRED` 前缀 | 有内容的既有会话仍先要求 gateway 确认退出；SSH agent 签名、gateway verify、私有临时文件和原子替换不变。空文件不包含可撤销凭据，未增加身份/组/角色输入 |
| `schemas/native_tasks.py` | 增加可选 `read_only` 归档标记 | 允许保留宿主已确认的只读状态；该标记不授予执行权限。Gateway 仍从有效会话注入 owner，保持 lineage、版本、摘要和授权校验；任务执行权限仍由宿主 metadata 决定 |
| `tools/admin/_register.py` | 删除未使用的 `Path` 导入 | 工具实现、审核角色门槛、组作用域、审计和晋升动作均无变化 |
| `tools/risk/_register.py` | risk profile/thresholds 从任意 dict 改为 `RiskProfile`/`RiskThresholds`，包装器直接使用已校验模型 | 将既有执行前校验前移到参数 schema，限制无效/多余字段；判定和评论函数、默认阈值、GitHub/dedupe 参数不变。未给 risk_verdict 或评论工具增加 catalog 发布声明 |

## 策略不变证明

删除每个工具条目的说明字段 `review` 和实现定位字段 `source` 后，序列化策略列表 SHA-256 为：

`5719e7cbf79c73b6abea3774be7333efb1c7db982af29dfb41c14086199511aa`

更新前后相同，包含全部 `effect`、`groups`、`roles`、`resource_scopes`、`path_arguments`、`purpose`、`status` 和资源约束。仍为 **9 published / 13 disabled**；未新增工具、未扩大角色或资源授权、未把不可用工具标成已连接。

## 验证与交付

验证使用现有风险参数、Admin 权限、真实临时 SSH agent 登录/重登/撤销测试，以及 legacy provider 流测试。日志保存在 `/tmp/quantcode-catalog-pin-review-20260909/`。

- Risk registry + 真实 host 登录/重登/撤销：7 通过，`risk-identity-isolated.log`。
- Admin 权限单文件：35 通过，`admin-isolated.log`。
- Legacy provider stdout 分块解析：1 通过，`legacy-provider-tests.log`。
- 最初组合运行有 41 通过、1 失败，保留 `tests.log`：前置 risk 测试留下无组开发会话缓存，Admin fixture 没有清除 `_SESSION_GROUP`/`_SESSION_CONTEXT`，随后切换环境变量不会改变固定会话。已报告主任务补齐测试隔离；没有放宽生产会话不可变规则来使测试通过。

审核后使用当前工作树的正式 exporter 生成 `/tmp/quantcode-serverc-e2e-20260909/schemas.json`；exporter 在导出前后复查全部 71 个 pin、工具实现 symbol 和审核文件内容。此操作仅生成 schemas，实际绑定各研究宿主有效配置与发布由 Server C 部署子任务继续完成。

导出成功，22 个工具，文件权限 `0600`，SHA-256：`f48ea01e05c3586164c6927a7aad33962549917610d14643f1726dd8b538e6a1`。

# 服务账号与 QuantCode 接入边界

来源：`服务器/docs/current/操作手册/服务账号管理员操作手册-V1.0.md`，仅作为外部运维参考。本文不把手册中的命令、路径或账号操作变成 QuantCode 的执行指令。

## 结论

服务账号是**生产进程身份**，不是 QuantCode 的实名用户，也不是新的业务组。QuantCode 可以识别某次 Admin 部署由哪个研究员发起、最终由哪个受控服务账号执行；不能让研究员或普通 Agent 取得服务账号、进入生产 shell、读取 CAM 密钥或绕过网关调用 `coscli`。

这与顶层文档保持一致：

- Session 的 `actor/group/role/workspace` 仍来自 SSH roster；服务账号不替代实名 Session。
- 普通 Agent 仍不能调用 `/deploy`；部署只能从 Admin 管理面提交。
- QuantCode 只负责发现、编排、契约检查、适配、状态和 evidence；生产系统负责实际运行、容量、密钥和底层拓扑。
- 量化 canonical 组件仍由各组维护。服务账号只表示某个受控生产进程，不代表组件已经接通。

## 可以沉淀进 QuantCode 的内容

### 1. 服务执行主体目录

可以在 Admin-only 的能力/运行目录中登记非敏感元数据：

| 字段 | 示例 | 作用 |
|---|---|---|
| `service_principal_id` | `qsvc-factor-prod` | 外部服务账号标识 |
| `server` | `server-c` | 执行位置标签 |
| `purpose` | factor production write | 业务用途 |
| `capabilities` | `factor-prod-cos` | 可调用的网关 capability |
| `workspace_ref` | `/var/lib/...` 的脱敏引用或稳定 ID | 工件落点引用；不向普通用户暴露真实拓扑 |
| `executor_status` | `ACTIVE/EMPTY/REVOKED/UNKNOWN` | 当前观察状态 |
| `observed_at` | UTC 时间 | 状态新鲜度 |
| `policy_revision` | 策略版本或 hash 前缀 | 防止静默漂移 |

手册中的当前事实可以登记为：

- `qsvc-data`：`raw-cos`、`clean-cos`，分别对应 raw/clean 数据前缀的 RWD 面；
- `qsvc-factor-prod`：`factor-prod-cos`，只覆盖 factors 五个子树的读写面，禁止删除；
- `qsvc-compute`：账号存在但没有 sudoers capability 和 COS 权限，应登记为 `EMPTY/UNAVAILABLE`，不能显示为可部署执行器。

这些是能力状态，不是授权凭据。账号是否真实可用仍要由外部 gateway/CAM smoke 验证。

### 2. Admin 部署请求中的执行契约

QuantCode 的 Admin deploy 请求可以增加或保留以下最小字段：

```json
{
  "artifact_ref": "artifact://...",
  "target": "factor-prod",
  "manifest": {
    "contract_version": "...",
    "component": "...",
    "version": "...",
    "executor_principal_id": "qsvc-factor-prod"
  }
}
```

QuantCode 只把请求交给受控生产部署服务，并接收：

- `SUBMITTED/STAGING/RUNNING/SUCCEEDED/FAILED/CANCELLED` 状态；
- artifact 引用；
- 版本和部署记录 hash；
- 可操作错误；
- 外部 evidence 引用。

服务账号实际执行、COS 路径检查、CAM 授权、systemd 调度和回滚仍在外部部署服务完成。QuantCode 不应该直接实现 `sudo -H -u`、`coscli` 或 root 命令。

### 3. 双轨审计关联

QuantCode 可以在 evidence 中记录一条脱敏关联：

```text
request_id
actor_id / actor_role
service_principal_id
capability_id
target / artifact_ref / version
policy_revision
submitted_at / finished_at
external_audit_ref
result_status
```

这样可以把“谁发起了部署”“哪个进程执行了部署”“CAM 实际记录了什么”串起来。Linux 网关 JSONL 和腾讯云 CloudAudit 仍是外部权威日志，QuantCode 只保存引用和摘要，不复制密钥或完整底层日志。

### 4. 预检与漂移报告

Admin 中枢可以提供只读的服务执行器健康报告：

- `nologin` 是否仍成立；
- 是否意外配置 SSH 公钥；
- 是否出现额外业务组或 sudoers capability；
- 网关 capability、principal、local root 和动作白名单的策略 hash；
- 工作目录 owner/mode 是否符合要求；
- `whoami`、`limits`、允许读写和删除拒绝 smoke 的最近结果；
- CAM 403、网络错误、网关拒绝和路径越界分别计数。

报告状态应使用 `CONNECTED/PARTIAL/UNAVAILABLE/DRIFTED`，不能把“目录中登记了账号”显示成生产可用。

### 5. 生命周期和提醒

可以沉淀为 Admin checklist 和 evidence：

- 新账号：需求、用途、COS 前缀、动作、负责人、回滚方式；
- 开通：网关策略、sudoers、CAM 子账号、systemd、smoke；
- 轮换：新旧 key 的 hash 前缀、观察期、禁用和删除时间；
- 注销：停调度、撤 capability、禁用 CAM、归档工作目录；
- 到期提醒：90 天轮换建议、长期未使用、策略漂移和 smoke 失败。

QuantCode 只提醒和留痕，不能自行生成、复制、启用或删除 CAM 密钥。

## 必须留在外部运维系统的内容

以下内容不进入 QuantCode 的普通 Tool Catalog、Memory、LLM prompt、artifact 或 UI 详情：

- SecretId、SecretKey、SSH 私钥、完整 token、专用 coscli YAML 内容；
- `/etc/sudoers.d` 的直接修改和 root shell；
- `sudo -H -u <svc>`、`coscli`、`systemctl`、`useradd` 等生产执行命令；
- CAM 策略 JSON 全文、bucket 内部拓扑、真实密钥路径和 root 配置路径；
- 生产服务账号的 shell、SSH 登录和交互式代跑；
- 以服务账号身份伪造实名 actor、roster 或 GitHub subject；
- 直接从 QuantCode 访问 COS 或绕过生产网关的 fallback；
- 把 `qsvc-compute` 空壳账号显示成可用部署执行器。

服务账号也不能进入组内长期 Memory。Memory 可以保存“某组件需要某 capability、最近一次 smoke 状态和外部文档引用”，不能保存钥匙、完整策略或可复制的生产命令。

## 与现有 QuantCode 模块的落位

| 手册事实 | QuantCode 落位 | 边界 |
|---|---|---|
| qsvc 账号台账 | Admin-only service principal/catalog | 只读元数据和状态 |
| COS capability | Capability Card / deploy manifest | 记录用途、前缀摘要、版本和状态；不执行 coscli |
| sudoers 白名单 | 外部 policy revision + drift report | QuantCode 不渲染或安装 sudoers |
| Linux 网关 JSONL | evidence external reference | 保存 hash/时间/request_id，不复制原始敏感日志 |
| CAM CloudAudit | evidence external reference | 不替代腾讯云审计 |
| 新账号/轮换/注销 | Admin operation checklist | 人或外部运维系统执行 |
| systemd timer/service | executor health observation | 不由普通 Agent 创建或修改 |
| 生产部署 | Admin `/deploy` handoff | 服务账号执行，QuantCode 只记录结果 |

## 当前手册暴露的待接项

1. `qsvc-compute` 尚未配置 capability，QuantCode 应保持 `EMPTY/UNAVAILABLE`。
2. PaperRAG daily bot 仍挂个人 crontab，迁移到服务账号和 systemd 前不能标为生产闭环。
3. `run_top30_cron.sh` 的明文 webhook key 应先在外部运维系统迁移到受管配置；QuantCode 只接收通知状态和外部引用。
4. CAM 子账号、密钥、capability 和策略版本台账尚未完全核对；QuantCode 可以显示 `UNVERIFIED`，不能自行补齐。
5. 手册中的 smoke 和回滚流程可以作为 Admin deploy 的验收 checklist，但不能因此扩大普通 Agent 的权限。

## 建议的下一步

优先建立一个只读的 `service_principal_status` 外部接口，返回上述非敏感字段和 evidence 引用；然后把它接到 Admin 中枢和 `/deploy` 状态查询。待服务账号台账、网关策略、CAM 权限和 systemd smoke 在 Server A/B/C 上完成核对后，再把对应 executor 从 `UNAVAILABLE/STAGING` 提升为 `CONNECTED`。

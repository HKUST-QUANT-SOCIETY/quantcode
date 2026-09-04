# SPEC — Governance 与 Evidence

> 版本：v0.3（2026-09-04）
> 上位规范：`specs/FUNCTIONAL_SPEC.md` v0.5

## 1. 范围

本域只负责：

- `merge`：共享主线或共享资产真实写入；
- `permission`：受限跨组资源的一次性访问；
- Run、Artifact、Gate 和 Admin Operation 的 Evidence Chain。

风险、评估、报告、CI、预算耗尽、循环检测、个人目录写入、生产部署和生产 SSH 均不创建普通 HumanGate。

## 2. HumanGate 契约

```yaml
gate_id:
kind: merge | permission
resource:
actor:
message:
reasons: []
evidence: {}
expires_at:
decision: approve | reject | null
```

`kind` 是严格白名单。新增类型必须先修改顶层功能规格。批准绑定 actor、资源、用途和时效；Resume 时重新校验当前 Session Context。

## 3. 运行停止与生产边界

| 情况 | 状态/路径 |
|---|---|
| 风险越限 | `risk_verdict` 的 `fail`/`warning` |
| 预算耗尽 | `STOPPED_BUDGET` |
| 循环/迭代上限 | `STOPPED_LOOP` |
| CI 失败 | CI status/Error |
| 生产 SSH 写 | 拒绝；QuantCode Session 无生产 shell |
| 生产部署 | Admin 管理面 → 独立生产服务账号；不经过 HumanGate |

## 4. Evidence Chain

事件种类：`tool_call`、`tool_result`、`risk_verdict`、`human_gate`、`artifact`、`output_data`。每环包含 `seq`、`at`、payload hash、previous hash 和 entry hash。Artifact 绑定路径、字节数和 SHA-256。

关键 `merge`、`permission` 与 Admin Deploy 的 Evidence 写入失败时，操作不得显示成功。普通只读查询和诊断记录可 best-effort。

## 5. 验收

- HumanGate Schema 拒绝 `risk`、`budget`、`deploy`、`ci`；
- Risk/Portfolio verdict 不产生 interrupt；
- Budget/Loop 返回停止状态且不可通过 Gate 加额/放行；
- 普通 Session 不能列出或调用 Deploy；
- merge/permission 可 interrupt、approve/reject、Resume 并审计；
- Evidence 篡改、乱序或 Artifact 替换会校验失败。

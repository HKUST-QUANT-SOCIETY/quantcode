# B 线：任务恢复与审批可靠性台账更新

基线：`f0ec06fa80c9ffad28753827ce9533b080ea5f30`

分支：`feat/task-recovery-and-approval-reliability`

范围：F-02 / F-03 / P-10

本文记录 F-02 / F-03 / P-10 的本轮专项实现与验收细节；结论摘要已同步到
[主审计台账](FULL_PRODUCT_AUDIT_2026-09-05.md)。本文不替代主台账，也不把本机
隔离验证表述为组织生产环境已经联调。

## 结论

F-02 的真实进程死亡与恢复、外部写回执不确定态、重复/并发恢复已形成可复现测试；
F-03 补齐 Gate 服务端到期、直接恢复防绕过、跨人恢复时创建者授权重验及并发决策；
P-10 补上 checkpoint 对冻结方案摘要的决策锁，并在每次工具调用前从 Blackboard
回源核验。四类方案失效（撤销、删除、摘要篡改、同 ID 有效替换）均收紧为只读与
方案工具，未执行写探针。

## F-02 执行记录与恢复

- `scripts/repro_checkpoint_sigkill.py`：节点执行中收到真实 `SIGKILL`，新进程从
  SQLite checkpoint 恢复。已完成 `step_a` 不重复；被杀死的 `step_b` 从节点边界
  重试后继续 `step_c`。
- `scripts/repro_tool_receipt_crash.py`：
  - 外部写调用前 `SIGKILL`：尚未建立 STARTED 回执，恢复后安全执行一次，写入总数为 1；
  - 外部写完成且 COMPLETED 已提交：恢复只重放结果，外部写总数为 1；
  - 外部写已发生但 COMPLETED 未提交：恢复返回 unknown 并停止，外部写总数保持 1；
  - 并发恢复：持锁方之外的请求返回 `RUN_BUSY`，不执行第二次写入。
- MCP `run_agent` 普通恢复使用真实 `tools/call` 入口验证：同一 checkpoint 并发恢复
  只允许一个请求进入，另一请求返回 `RUN_BUSY`；任务完成后的重复恢复在模型调用前
  被拒，恢复模型总调用次数为 1。
- STARTED 未知结果与结果摘要/载荷损坏的 COMPLETED 回执都在 MCP 普通恢复入口阻断，
  不调用模型或工具；本轮没有将“缺回执/读失败”自动解释为可重试。
- Gateway `/receipts/reconcile` 两条真实 HTTP 路径已验：
  - `confirmed_completed`：审批者为损坏 COMPLETED 回执提供外部证据和已验证结果，
    后续调用只重放该结果，外部写次数为 0；
  - `confirmed_not_executed`：审批者确认 STARTED 调用未执行，状态变为 RETRY_ALLOWED，
    后续调用只执行一次，完成后无未决回执。
  两条路径均先落 required evidence 和持久 review，接口返回 `execution_started=false`。

证据：`docs/audit/evidence/b-recovery-2026-09-06-run-001/` 与
`docs/audit/evidence/b-recovery-2026-09-06-run-003/`。

## F-03 HumanGate

- 新 Gate 由服务端按 `configs/human_gate.yaml` 生成 24 小时 TTL；无时区、损坏和
  已过期 `expires_at` 均 fail-closed。
- `AgentRunner.resume(decision=...)` 没有 pending HumanGate 时直接拒绝，普通
  checkpoint 不能伪装成审批恢复。
- MCP 恢复在锁内同时校验 `expected_gate_id` 和 `expected_checkpoint_id`，过期或
  已变化 Gate 不会被旧页面提交绕过。
- 跨人审批通过本机真实 HTTP Gateway 和持久 IdentityGateway 数据库验证：创建者
  session logout、session 过期、从实时 roster 删除、角色/工作区/GitHub subject/
  resource scopes 变化均拒绝。
- 同一 Gate 的 approve/reject 并发请求只有一个进入恢复边界，另一个得到 `RUN_BUSY`。

说明：上述 Gateway 测试使用本机隔离端口、真实 HTTP 请求和真实持久身份表，但由
测试种子构造账号；尚不等于组织线上 roster/SSH gateway 已完成联调。

## P-10 Solution-First

发现的缺口是：solution 工具已返回 `doc_hash`，但 AgentState/checkpoint 未保存它；
恢复时只要同一个 `solution_id` 当前仍是 `frozen`，另一份摘要自洽的替换文档可能
继续触发原任务写操作。

修复后：

- `solution_doc_hash` 只在方案成为 frozen 时绑定，避免草案在 `/solution` 正常冻结
  后被误判失效；首次跨进程观察到 frozen 也会立即建立绑定。
- 工具执行边界用一次 Blackboard 读取同时取得阶段与摘要；绑定后摘要变化返回
  `invalid`，不进入权限/Gate/registry 写调用。
- 没有摘要字段的旧 checkpoint 保持兼容，但仍校验当前文档自身摘要与阶段。
- `scripts/repro_solution_invalidation.py` 通过真实 `SIGKILL`、SQLite checkpoint 和
  新进程恢复复现同 ID frozen 方案替换。结果：原摘要 `a880960cb32f543c`，替换摘要
  `6636a9765e56f197`，恢复阶段 `invalid`，写副作用列表为空。

证据：`docs/audit/evidence/b-recovery-2026-09-06-run-002/`。

## 回归结果

- P-10 定向：35 passed。
- B2 最终定向验收：88 passed；去标识化机器结果见 run-003 `observations.json`。
- 后端全量：1167 passed / 4 skipped；相对基线 1139 passed 新增 28 项。
- B 线变更文件 Ruff：通过。
- `git diff --check`：通过。

## 本 PR 验收范围外

- **跨机器恢复明确不在本 PR 验收范围。** 本 PR 验证同一持久 SQLite checkpoint/
  receipt 存储可访问域内的进程死亡、新进程恢复、重复与并发控制。跨机器恢复需要共享
  checkpoint/receipt 存储、分布式互斥、主机身份与部署级 failover 配置，应另立验收项，
  不以本地新进程测试替代。

## 仍缺外部条件

- 组织真实 roster、SSH agent → gateway → MCP 的账号与服务联调由 A 线协调；本轮未
  重启现有 Dev 服务，也未使用生产凭据。
- 真实第三方写操作的故障窗口只能用受控测试探针验证；在没有沙箱账号和回滚方案前，
  不应对生产外部系统主动制造“写成功后强杀”。
- 跨角色浏览器审批、P-10 完整 L2/L3 UI 流程和录屏属于 D 线 Headless UI 验收范围。

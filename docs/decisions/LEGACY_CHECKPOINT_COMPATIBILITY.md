# 旧检查点兼容边界

状态：M3 已接入旧执行器、统一 Provider、原任务用量核对及现有组织审批队列；代码尚未经过桌面核验和测试，不作为已验收能力。

旧 Python 检查点保留在原数据库，独立标为 `legacy-python`。原生任务索引不会将其改写为新 session，也不会因为历史状态未完成就认定仍有进程运行。查询复用 `runner.run_history`，以当前 roster 的 actor/group/workspace 过滤；Admin 的组织查询继续复用既有审计记录。

宿主适配为 `quantcode/legacy_host.py`；桌面服务调用 `QuantCodeLegacyHost.list/detail/requestApproval/resume`，wire 契约位于 `frontend/packages/schema/src/quantcode-legacy.ts`。查询输入没有任务文本、模型配置、身份覆盖、源码路径或数据库路径。只读详情保留消息、artifact、检查点列表、未知写入回执与来源说明。

详情中的 `checkpoint_digest` 同时绑定原始检查点字节、序列化类型和该版本的 pending writes；`owner_digest` 绑定检查点保存的原身份。查看旧版本时还返回当前 `latest_checkpoint_id`，防止把历史选择视为当前恢复授权。LangGraph 检查点内部 `v` 仅作为 `serializer_version` 展示，不能冒称执行器版本。

默认读取原 `.quantcode/checkpoints.db`。维护者可用 `QUANTCODE_LEGACY_CHECKPOINTS_DB` 指定另一个已经存在的绝对归档路径，不接受浏览器选择。该路径的父目录整体受原生工作区隔离保护，包括 SQLite WAL/SHM。独立归档库不会混用默认库中同名 thread 的事件流；缺少单独登记的流时只展示检查点内保存的消息和证据，并明确说明。

## 来源登记

已有检查点没有保存足以证明源代码版本的字段，不能用当前代码 hash 补写成“原版本”。维护者必须先找到可信归档源码及任务记录，核对后提交显式来源声明；登记本身不是恢复或批准业务副作用。

`QUANTCODE_LEGACY_PROVENANCE_FILE` 指向工作区之外的宿主私有 JSON，父目录由宿主账户拥有、权限 `0700`。未设置时使用旧检查点目录中的 `legacy-provenance.json`。登记动作只从维护终端执行，不注册为 MCP 工具或 HTTP 操作：

```sh
python -m quantcode.legacy_host --action enroll --source /absolute/private/reviewed-legacy-source.json --expected absent
```

以上为维护命令，本次实现期间未运行。后续登记使用前次命令返回的完整 registry digest，替换 `absent`。来源声明文件本身须为宿主 `0600` 文件，并包含：

- `thread_id`、`checkpoint_id`、`checkpoint_digest`、`owner_digest`，来自当前授权历史预览。
- `executor_version`，维护者核对的归档版本名称，不使用序列化版本代替。
- `source_root`，实际保留的规范绝对源码根。
- `source_files`，完整审核范围内的相对文件名到 SHA-256 的映射，至少包含 agent_engine、agent_nodes、agent_mcp_tool、langgraph_base、permission_engine 和 tool_receipts。
- `python_version` 与 `dependencies`，原执行器的 Python 和依赖版本；至少登记 langgraph、langgraph-checkpoint、langgraph-checkpoint-sqlite、langchain-core、pydantic。
- `runtime`，原构造和图状态的明确记录，结构见 `quantcode/legacy_contract.py`。`constructor` 必须显式包含 `registry`（当前仅支持已登记的 default registry）、`max_iterations`、`truncate_tokens`、`retry_max_retries`、`retry_base_delay`、`budget_tokens`、`blackboard_db_path`、`allowed_tool_ids` 及 `loop_detector.window/threshold`。不得用当前缺省值补全旧记录。
- `runtime.system_prompt_digest`、`nodes`、`edges`、`next_nodes` 和 `pending_tasks`，分别绑定原提示词、节点、含条件与标签的边、所选检查点的待执行节点及其任务 ID。恢复前用登记参数构建原 LangGraph，再逐项比较；不能将缺少旧节点的图当作可恢复。
- `note`，说明归档来源、原身份核对依据及审阅结论。

当前 Admin 身份来自私有登录文件和网关重验，不接受声明文件里的 reviewer 或 owner 参数提升权限。登记复用既有跨进程锁、比较 registry digest、再次核对原检查点及 owner，然后原子写入。已登记的同一 checkpoint 不覆盖、不批量修改旧记录。归档源文件发生变化时，详情将来源标为 `changed`。登记损坏不会让已授权历史无法查看，但恢复继续拒绝。

## 恢复与审批

`resume` 只接受原 thread、checkpoint、checkpoint digest、登记的 executor_version 和 provenance digest，以及可选的审批记录 ID。符合条件时由原 `AgentRunner.stream` 在原检查点上继续。归档模块从登记的源码字节加载，拒绝混入当前源码或未登记的本地模块；模型请求通过固定 stdio 协议交给现有 OpenCode Provider，Python 不接收模型 URL 或 API Key，也不创建新的原生 session。

当前登录通过网关证明 SSH 身份。恢复比较完整原 Owner：actor/group/role/workspace/GitHub subject/resource scopes；原 session_id 保留审计而不阻止同一身份重新登录。原字段缺失或当前授权改变时拒绝。执行过程中反复核验当前登录，取消、注销或撤权会停止执行；已经形成的新检查点仍按入场核验的 Owner 和执行器记录来源事实，下次恢复重新检查权限。

待审批操作由原所有者调用 `requestApproval`，发布到既有 `native_gate`，复用现有审批队列。请求绑定实际工具参数、原 Gate 资源及证据、方案文件范围与版本、检查点和执行器摘要；审批记录在十分钟窗口内有效。详情会读取当前窗口的记录，刷新后无须手工输入 ID。客户端不能直接提交 approve/reject 来恢复；原所有者须携带精确 `approval_gate_id` 和 `expected_gate_id`，由宿主重新核验网关决定。原 Runner 和工具始终保留所有者角色；原 Command 的决策者单独记录为真实审批者。拒绝也通过原 Command 回放，使原 Gate 结束；接口返回 `status: rejected`，不代表批准其他操作。

普通业务工具交给现有 OS sandbox 和 AppProcess 运行一次组件调用。归档源码为只读副本，工作目录为所有者研究目录，写范围来自原冻结方案；组件不接收凭据、检查点、用量或来源登记数据库。需要未提供网络能力、图内 interrupt 或无法安全序列化返回值的组件会明确拒绝，不回退到宿主直接执行。只保留经审阅的图控制工具在控制进程中运行。

## 模型用量核对

兼容恢复后的模型请求写入原 checkpoint 旁的 `.legacy-usage.db`，保留原 thread/Owner，先预留再按 Provider 实际用量结算。原检查点既有 `budget_used` 作为一次基数保存，避免恢复后重复累计。未知用量不自动释放；普通恢复遇到未结算请求会停止。

维护终端提供以下两个动作，均读取宿主 `0600` JSON 文件，本轮未执行这些命令：

```sh
python -m quantcode.legacy_host --action usage-read --source /absolute/private/usage-read.json
python -m quantcode.legacy_host --action usage-review --source /absolute/private/usage-review.json
```

`usage-read` 输入仅含 `thread_id`，返回原请求明细、`reservation_digest`、当前检查点摘要及既有审核记录。当前 Admin 或同组 approver 可核对；`usage-review` 输入包括 `thread_id`、`checkpoint_id`、`checkpoint_digest`、`request_id`、`expected_digest`、`request_stopped: true`、`decision`、`evidence_ref` 和 `note`。`usage_confirmed` 必须带 `receipt`（`input_tokens`、`output_tokens`、`tokens`、`cost`）；`confirmed_not_executed` 不带 receipt，并以零用量结算。

审核持有原任务执行锁，不能与正在运行的模型请求并发；只修改精确的未结算记录，原预留值和人工证据另行保存。已结算记录不可覆盖。审核不会启动执行，下一次恢复仍需检查原任务归属、来源、审批及工具回执。

原生模式下直接调用旧 `run_agent` 入口会被拒绝，即使绕过 MCP list。旧非迁移运行路径保留到明确兼容退出阶段。原生 Session 删除应转为归档并保留事件、子任务和回执；HTTP 删除入口先取消实际执行，不能删除审计事实源来隐藏未确认写入。

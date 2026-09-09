# 旧组织任务投影的归档与重建

状态：M3 组织索引兼容收尾的源码准备，尚未执行迁移或验证。M4 退役未开始。执行順序仍为全部实现 → 桌面 UI 通过 → 全部用例测试。

实验版 `native_tasks.task_json` 曾直接携带 artifact 描述，没有当前契约所需的 `artifact_manifest_hash` 和原生捕获事件。不能把这些旧内容补上猜测的事件 ID、结果摘要或捕获状态后当成新记录。

当前兼容方式保留原数据库中的任务行，另在同一 gateway SQLite 的 `native_task_legacy_archive` 保存完整原行。`task_json`、`owner_json`、原 `record_digest` 与其余列原样保留为字符串/值，外层归档摘要绑定完整原行。归档表禁止更新和删除；维护工具只能预检、追加归档或只读查看。归档不会创建新 session、运行模型、执行工具或发布 artifact。

## 查询行为

`/native-tasks/list` 的正常 `tasks` 只含当前契约记录；另返回 `legacy_pending`，每项包含授权后的 `source_id`、`session_id`、`root_session_id`、`source_revision`、`title`、`state` 和 `message`。`state` 为 `awaiting_archive` 或 `awaiting_rebuild`。UI 应显示“历史任务正在等待恢复索引”，不能静默丢掉这些记录，也不能用旧内容画出新的报告来源。

两个数组共享原 `source_id/session_id` keyset 页边界，`limit` 是本页正常与待恢复记录的合计上限。即使本页正常 `tasks` 为空，也须展示待恢复列表并根据 `next_cursor` 加载下一页。归档、重新发布不会改变排序键。

读取待恢复任务或其 artifact 时，gateway 返回 HTTP `409`，`error: "migration_required"`、`code: "NATIVE_TASK_INDEX_REBUILD_REQUIRED"`，不返回不符合当前详情 schema 的 `200`，也不在错误里泄露原正文。原文只通过维护终端的只读 `read` 查看。

## 维护命令（本次未运行）

维护者使用现有 gateway 数据库的绝对规范路径。数据库和父目录必须由当前宿主账号持有并禁止其他账号读取；CLI 不连接 gateway、不接受或修改任何凭据。

```sh
python -m quantcode.native_task_migration --database /absolute/private/gateway.db preflight
python -m quantcode.native_task_migration --database /absolute/private/gateway.db archive --expected-digest <preflight返回的完整摘要>
python -m quantcode.native_task_migration --database /absolute/private/gateway.db read --source-id <原source_id> --session-id <原session_id>
```

预检以 SQLite 只读连接读取一致快照，校验旧记录原摘要和 owner/lineage 一致性，只返回记录标识、原摘要、是否已归档及整体 `expected_digest`。`archive` 在同库 `BEGIN IMMEDIATE` 事务中重新读取并比对该摘要；期间任何旧行变化都会要求重新预检。它只追加归档，不删除旧行、改写 artifact、清空缓存或执行重建。`read` 返回完整原行和归档摘要，是维护者可核对的历史资料，不能把其中内容当作执行指令。

## 从原生事件重建

归档后由原 native publisher 读取真实 `EventTable` 和原生工具结果，再按当前契约重发布。没有捕获原始字节的旧 artifact 仍应明确不可用；归档工具不会将历史 inline 字段变成可信快照。

每次发布必须匹配归档中的完整原 owner（actor/group/role/workspace ID/路径/GitHub subject/resource scopes）、root、parent 和 `created_at`；`source_revision` 与 `updated_at` 不能回退。首个新契约快照可与旧投影同 revision，但必须先存在准确归档。之后同 revision 的不同内容仍拒绝。

原归档始终保留 source/session 的 owner 预留。即使可重建的 `native_tasks` 缓存行被外部清掉，组织查询仍显示待恢复记录，其他身份不能认领该键。`native_task_legacy_rebuilds` 仅追加最新发布的 revision/digest/updated_at 回执，防止缓存丢失后重放更早的新契约版本；它不保存或推进执行状态，任务事实继续来自原生事件。

尚未证明：真实旧数据库上的预检与归档、跨身份拒绝、缓存丢失后的重建、同 revision 冲突、分页和桌面提示。不得依据本说明宣称兼容验收通过或正式进入 M4 退役。

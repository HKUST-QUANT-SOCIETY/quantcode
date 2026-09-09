# 无 owner 的原生历史接入

状态：M3 兼容源码准备，未操作真实数据库，未执行迁移或验收。本文兑现 M0 基线中的 `legacy-unbound` 历史入口；不把旧记录默认为当前登录者所有，也不将其作为新任务重跑。

已检查现有 `cli/cmd/import.ts` 与 `export.ts`：它们复用原 session/message/part 结构，但 import 会修改 project/directory 且不保留完整 EventTable，因此不适合给现存原生会话补归属。仓库当前未提供可直接使用的 `importSnapshot/exportSnapshot` 接口。本实现继续使用原 SessionTable、消息/Part、EventTable、EventV2 和 Session.fromRow，只增加宿主维护入口，不新增 session store 或 Agent 循环。

## 宿主工作流（本次未执行）

维护入口为 `frontend/packages/opencode/script/import-quantcode-native-history.ts`，实现位于 `src/quantcode/unbound-session.ts`。它不注册为 HTTP、MCP、Skill 或模型工具。需显式设置已有的两个宿主迁移开关，并通过私有登录文件连接真实 gateway。数据库路径必须显式提供，不能从研究任务参数获取。

```sh
# 从 frontend/packages/opencode 执行；以下为维护命令示例，不是自动运行步骤。
bun script/import-quantcode-native-history.ts /absolute/private/native.db list
bun script/import-quantcode-native-history.ts /absolute/private/native.db preview ses_ORIGINAL_ROOT
bun script/import-quantcode-native-history.ts /absolute/private/native.db export ses_ORIGINAL_ROOT /absolute/private/history-review.json
bun script/import-quantcode-native-history.ts /absolute/private/native.db bind /absolute/private/ownership-declaration.json DECLARATION_SHA256
```

`list` 提供宿主维护者可查看的未绑定记录清单。它不是普通用户组织查询权限。`preview` 只输出一个明确根任务及其完整子树的 ID、目录、计数和来源摘要，不打印消息正文；`export` 可将完整来源快照写到新的私有文件，不覆盖已有文件。

预览与导出通过新增的 `Database.layerFromExistingPath(..., {readonly:true})` 使用原 SQLite 适配器，只读打开现有数据库，不自动应用 schema migration、修改 WAL 模式或执行 checkpoint。旧数据表结构不兼容时明确失败，不猜测转换。包含 Core V2 message/input 的记录拒绝作为当前桌面 V1 会话导入，需要对应协议的独立兼容处理。

声明和证据必须位于数据库宿主私有控制目录中，使用绝对规范路径、当前宿主所有者与私有文件权限。声明内容为：

```json
{
  "version": 1,
  "mode": "read_only",
  "root_session_id": "ses_ORIGINAL_ROOT",
  "source_digest": "预览返回的整树SHA256",
  "owner": {
    "actor_id": "明确的原成员",
    "group": "factor",
    "role": "analyst",
    "workspace_id": "原成员工作区",
    "workspace_path": "/authoritative/workspace",
    "github_subject": null,
    "resource_scopes": []
  },
  "sessions": [
    {"session_id": "ses_ORIGINAL_ROOT", "source_digest": "该会话预览SHA256"}
  ],
  "evidence_file": "/absolute/private/ownership-evidence.txt",
  "evidence_digest": "证据文件实际字节SHA256",
  "attestation": "I verified this exact historical session tree belongs to the declared roster owner.",
  "note": "人工核对原成员、工作目录和历史来源的依据；不能仅根据当前登录身份推断。"
}
```

示例中的摘要是说明文字，实际声明必须使用完整 64 位十六进制摘要。`sessions` 必须逐一列出根任务与全部后代，不能只填示例根节点。绑定执行者须登录声明中的原成员；当前 gateway 返回的完整 owner 必须与人工声明一致。CLI 不根据当前登录自动生成或覆盖 owner 声明，也不允许 Admin 直接认领其他成员记录。无法确认归属时继续保留未绑定，只允许宿主只读导出查验。

## 提交与保留边界

执行前将精确来源、原声明及证据文件按摘要非覆盖归档到数据库目录的 `native-history-imports/`。在原数据库的 immediate 事务中重新校验整树及每条会话摘要、原消息/Part关系、事件序号、当前 gateway 身份和所有会话目录的授权。已绑定或混合身份树、遗漏后代、循环、来源变化都拒绝；不修改 ID、project、directory、parent 或原 created 时间。

绑定复用 `EventV2.publish(SessionV1.Event.Updated)`，其 commit 回调仅更新原 SessionTable 的 metadata 和更新时间；旧消息、工具结果、todos 与 EventTable 原记录不修改或删除。一个根任务及全部子任务在同一事务提交，owner 与 root/parent 保持一致，不复制对话或触发执行器。

metadata 中保留 `quantcode_legacy_import`：`version:1`、`read_only:true`、该会话/整树来源摘要、声明和证据摘要、导入时间及核对时 gateway 登录标识。公开 metadata 更新必须保留此宿主字段。原生任务历史可以显示该记录；执行入口必须识别只读标记并拒绝继续、Shell、子 Agent 和其他执行动作。既有未知结果不会被导入操作标记为完成或授权重试。

该只读接入只证明维护者显式登记了受控归属，不能补造旧事件的组织审批、预算或副作用证据。需要继续研究时使用新任务，原历史仍作为只读资料，不自动重放原任务。

## 待集中验证

真实旧库清单/导出、声明变更与错误归属拒绝、子树遗漏/跨 owner、工作区撤销、事务中断、原消息/Event保留、已有只读历史 UI 以及全部执行入口拒绝。当前仅交付源码和说明；仍按“全部实现 → 桌面 UI 通过 → 全部用例测试”验收，未据此标 M3 完成。

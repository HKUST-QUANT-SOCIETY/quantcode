# M4：旧 Python 通用执行入口退役

本记录只说明源码交付。UI 验收、全量测试和桌面打包尚由主迁移流程统一执行，不能据此声明 M4 验收完成。

## 生效范围

仅当 `OPENCODE_CHANNEL=quantcode` 且 `QUANTCODE_UNIFIED_RUNTIME=1` 时启用本轮入口限制。未同时设置这两个宿主开关的旧环境保留既有行为，没有删除历史、检查点、凭据、Memory、Blackboard、组件服务或第三方许可。

## 新任务入口

新任务继续使用已选定的原生 Session/Prompt/Tools/Provider 执行链。原 Python `AgentRunner.run`、`stream`、`resume` 不能因为调用者提供了 `resume=True`、角色或已有 thread ID 而获得迁移模式执行权。`build` 同样受限，避免从旧实例取得图后用 `invoke` 创建新任务。

`SubagentRegistry.create_subagent` 在生成 ID、建立 registry 条目或启动线程前拒绝迁移模式调用。原子任务查询和停止方法保留，便于查看或清理既有非迁移状态。`execute_compose_flow` 在构造输入、注入 Memory、调用前置钩子和执行图前拒绝；异步包装复用这个判断。Flow 注册和元数据查询保留，但注册并不赋予执行权限。

已有 MCP `run_agent`、旧子任务与独立模型工具的禁用继续由原组织目录和 MCP 边界负责，本轮没有新增开关或另一套任务服务。

## 历史恢复入口

历史继续通过固定 `quantcode.legacy_host` 恢复。它先在原任务 writer lock 内核验最新检查点、原 owner、源码/依赖、构造参数、图拓扑及所需精确 Gate，再加载归档执行器。当前宿主默认 `AgentRunner` 不获得恢复权限。

对包含退役判断的新归档源码，`legacy_executor` 只在其已加载的归档模块中设置私有 admission callback，绑定一个原 runner 实例、精确数据库及原 thread。callback 只允许原图构造与无新增任务正文/Skill 的恢复型 `stream`，并重新核验宿主身份；退出时恢复原模块状态。旧归档源码没有这个 callback 也不重写其字节，仍由相同固定宿主及已审核恢复链控制。客户端参数不能创建这个模块绑定。

恢复仍复用原 graph/checkpointer/tool receipts、统一 Provider 和业务工具隔离宿主；此权限不传播给新实例、并行子任务或 Compose 新流程。不能通过退役例外执行新的业务任务。

## 人工核对授权依赖

本轮静态核对了 `native_review.py` 和 `schemas/native_review.py`。固定网关接口只核验原 owner 当前 roster 授权、当前审核者及精确核对范围，并留下授权/披露审计；原登录过期不等于原 owner 被删除。普通 owner 仅可读取自己的回执，写入核对需要同组 approver 或 Admin。该接口不启动任务、不重试操作、不追加预算，实际应用结果仍由原生事件日志记录。

## 待主流程验证

最终验证需覆盖双开关组合、所有直接入口及异步 Compose 包装、新旧归档恢复、不同 runner/thread 拒绝、取消或撤权后清理、原回执复用与未知结果阻断，并确认组织组件与知识服务未受退役限制误伤。此阶段没有执行测试、类型检查、编译、构建或服务启动。

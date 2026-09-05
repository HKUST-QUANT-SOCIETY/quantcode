# F-02 恢复与事件通道修复

日期：2026-09-05。范围：后端运行恢复、实时事件通道及其读取权限。

## 已修复

- 已认证普通恢复按原 checkpoint 的 group、actor_id、workspace_id、workspace_path 校验。允许同一人员在新 session 恢复；禁止同组其他人员或其他工作区恢复。缺少创建者身份的 checkpoint 不接受已认证恢复。
- HumanGate 同时检查 StateSnapshot.interrupts 与 tasks.interrupts，不能通过普通恢复绕过待审批状态。保留同组 approver/admin 显式审批他人任务的流程。
- 已认证新任务不能使用已有 checkpoint 的 thread_id 覆盖旧任务。检查发生在发送 agent_start 事件之前。
- attach_stream 直接接入 AgentRunner.stream 的事件回调。LLM 尚未返回时已可读取 agent_start，不再在整个任务完成后补写全部事件。
- 事件文件重开不截断，跨进程重开保持已有事件和游标。轮询不消费未写完的 JSON 行，后续完整写入后继续读取。
- 已认证 check_tool_stream 从持久 checkpoint 校验读取范围。普通人员仅能读取自己的同组同工作区事件；Admin 可读取已有归属记录的任务。无 checkpoint 时明确拒绝，不根据知道 thread_id 授权。

## 验证

- 后端全量：**1,113 passed / 4 skipped**，16.94 秒。
- 新增回归：跨人员/工作区/缺失身份恢复拒绝、新 session 合法恢复、snapshot task Gate、防止覆盖已有 checkpoint、模型执行期间读取事件、独立 Python 进程重开通道、半行追加游标、事件读取范围。
- ruff（stream_channel 和 stream 注册模块）、git diff --check 通过。
- 本批没有修改前端，不把后端测试当成 UI、原生桌面壳或生产端到端验收。

## 未完成与边界

F-02 仍为部分完成，不能标记全量验收通过。服务端历史列表和浏览器刷新后的完整回放尚未接入；MCP 普通故障恢复入口仍需显式协议，当前已有决策恢复入口针对 HumanGate。生产 L2/L3 写入中断后不重复写入仍需真实组件验收。

事件通道仍是 best-effort 旁路，不承诺掉电级持久化；本次验证进程重开保留文件，不等同于整项业务故障恢复。首次 checkpoint 写入前，已认证事件读取会明确拒绝，后续可重试。已有 thread_id 检查防止顺序覆盖；并发运行的原子占用和执行租约仍需补齐。

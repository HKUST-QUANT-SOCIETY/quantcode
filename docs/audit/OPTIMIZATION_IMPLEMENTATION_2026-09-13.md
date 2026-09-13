# QuantCode 优化实施记录

日期：2026-09-13。依据同日架构审计，完成任务入口与连接恢复、后台重复工作和旧测试宿主清理。保留任务、知识、账号隔离及用量回执；未添加 Redis 或替换当前执行引擎。

## 已上线的改动

### 任务入口和 SSH

- SSH 子进程意外退出后按有界退避自动重建，同一通道保持原地址；关闭窗口会取消恢复，身份或服务器指纹异常则停止自动重试。
- 通道必须同时通过 SSH 自身的转发就绪信号和 TCP 检查，避免把其他进程占用的端口误判为连接成功。
- 管理连接使用稳定的宿主 ID，临时端口不再决定任务标签身份；兼容旧 URL 和项目偏好的迁移，新核验过的连接配置优先。
- 旧地址键使用 Solid `produce` 真正删除，修复迁移反复执行的问题，并加入删除与幂等回归测试。
- 界面接收连接状态，提供恢复进度和手动重连。提示跟随当前任务所属宿主，旧请求结果不会覆盖切换后的宿主状态。
- 任务入口先显示加载状态；元数据和消息读取有 8 秒超时，失败可重试原任务。确认不存在时才移除标签，短暂失败不创建新任务。
- 未使用的服务器不再预先创建全部同步 context；连接配置改变时释放旧 context。

主要代码：`frontend/packages/desktop/src/main/ssh-tunnel-supervisor.ts`、`quantcode-org-login.ts`、`quantcode-identity-ipc.ts`；`frontend/packages/app/src/context/server.tsx`、`server-session.ts`、`global.tsx`、`src/app.tsx`、`components/quantcode/connection-notice.tsx`。

### 身份核验与任务摘要

- 仅合并同时进行、凭据内容相同的身份核验。请求完成立即清除共享结果，后续检查仍向组织网关验证撤权；每个调用方分别检查凭据是否变化并取得独立副本。
- 名册按当前文件内容缓存解析结果，容量上限 8；每次仍读取当前内容，不依赖过期时间或 mtime。保留旧 mtime 的内容变更也会重新解析，调用方修改返回值不会污染其他授权结果。
- 组织网关限制为最多 64 个 HTTP worker，读取超时 15 秒，超过容量直接返回 503。
- 任务摘要最多并发处理 4 项；发布器先检查当前任务与根任务的版本，未变化时跳过昂贵摘要重建。
- 发布失败按任务退避，新的任务事件可唤醒重试；无脏数据时减少轮询，失效身份不持续高频请求。实际执行前的身份和预算检查保留。

这里优化的是读取、并发合并与发布调度，事件账本仍为真值。没有引入新的权威任务存储，也没有跳过写入授权和未知用量核对。

### 旧测试宿主

19 个 `quantcode-native-sim-*` 旧 e2e 实例均通过了范围、路径、子进程及最新执行事件检查，确认空闲后备份 SQLite 并停止服务。原数据库、配置与产物目录保留。正式的 37 个成员/管理员宿主继续运行。

新增维护脚本 `scripts/retire_idle_qa_hosts.py` 默认只输出计划；应用时需匹配计划摘要，再逐个复核状态。它拒绝正式成员、过新的测试、路径漂移与仍有活动任务的实例。

备份位置：`/var/lib/quantcode-qa/maintenance/retire-20260913/`。

## 实测与验证

|检查|结果|
|---|---|
|真实 SSH 故障注入|中断专用测试 SSH 进程后约 **1.6 秒**恢复；地址不变，generation 1 → 2，健康检查通过|
|任务列表读取基准|实施前 279 / 242 / 212 ms；实施后 147 / 70 / 70 ms|
|任务索引|审计时约 593 ms；实施后约 220 ms|
|三个历史任务的元数据|实施后 80 / 83 / 82 ms，均为 200，原 ID 和目录保留|
|旧任务继续对话|原验证任务正确记住“竹林42”和 `/srv/quant/users/quantadmin`；新增任务数 0，未确认预留 0|
|首页内存|JS 堆约 16.2 MiB、约 1005 个 DOM 节点；之前图谱问题的约 805 MiB 高占用未再出现|
|旧 e2e 常驻内存|停止前 cgroup 合计约 5505 MiB；停止后这些 cgroup 占用为 0|
|原有功能|知识 15 条全文、能力 14 项、算法 2 项、GitHub 连接保持正常|
|前端测试|678 通过|
|桌面测试|139 通过，1 跳过|
|原生测试|3127 通过，25 跳过，1 待办|
|Python 测试|1312 通过，4 跳过|

相关类型检查、桌面构建及差异检查通过。最终启动日志未再出现迁移循环的 RangeError。性能数字是此环境下的样本，不代表所有工作负载的固定加速倍数；GUI 点击与长期交互由用户验收。

## 部署与回退资料

- 原生 artifact：`/opt/quantcode-test-v1/artifacts/optimization-20260913`。
- 二进制 SHA256：`425c2411eb13f63034e66140968f3322ddaa8893c3772651933660be3fc67266`；37 个宿主已核对一致。
- 网关版本目录：`/opt/quantcode-test-v1/runtime/optimization-20260913`，通过 `99-optimization.conf` 激活。
- 网关 DB 备份：`gateway.db.before-optimization-20260913`；原生 DB/安装清单备份使用 `before-optimization-20260913` 后缀。旧 artifact 与之前两次备份保留。
- 桌面已构建并重启。没有提交或推送 Git 变更。

本轮证据位于 `.quantcode/`：`ssh-recovery-verification.json`、`optimized-continuation.json`、`task-read-audit-optimization-after.json`、`feature-recovery-benchmark-optimization-before.json`、`feature-recovery-benchmark-optimization-after.json`、`qa-retirement-plan.json`、`qa-retirement-applied.jsonl`、`server-runtime-after-qa-retirement.json`、`runtime-profile-20260913-optimization.json`。

## 用户验收

1. 从“我的任务”点开一个已有任务，确认进入对话并显示原工作目录。
2. 在同一任务连续发送两条消息，再切换出去返回；任务数量、目录和历史应保持一致。
3. 打开 GitHub 页面后返回任务页，检查切换、输入和滚动是否流畅。

历史未确认的用量继续保留原核对流程，未为了通过验证而抹除账本。正式成员的按需启停、Core v2 的整体迁移属于后续独立改造，未与本轮可验证的修复混合。

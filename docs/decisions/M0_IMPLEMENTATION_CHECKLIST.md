# M0 核对草稿（已归档）

归档日期：2026-09-08。状态：已被源码交付记录取代；不作为当前实施、验收、启用或部署依据。

旧表未逐项反映当前 E01～E23 接线，不能据其中“已完成”或“待修复”判断当前阶段。完整调用链和阶段依据见 M0 基线。

当前目标与证据入口：

- [用户确认的内化决策](QUANTCODE_RUNTIME_INTERNALIZATION_2026-09-08.md)：完整范围、复用边界和退出条件。
- [M0 基线](RUNTIME_INTERNALIZATION_M0_BASELINE.md)：调用链、能力迁移和兼容清单。
- [M1 源码交付](RUNTIME_INTERNALIZATION_M1_IMPLEMENTATION.md)与[M2 源码交付](RUNTIME_INTERNALIZATION_M2_IMPLEMENTATION.md)：实际接线及待验项目。
- [当前进度](RUNTIME_INTERNALIZATION_PROGRESS.md)：M3 尚未闭环；M4 命名/文案草稿不代表阶段完成；集中验收仍待全部实现后进行。

当前执行基础是现有 OpenCode Session/Provider/Tools/Runner/Event；组织边界接在 `quantcode/identity.ts`、`access.ts` 等实际路径。迁移开关只在 `OPENCODE_CHANNEL=quantcode` 与 `QUANTCODE_UNIFIED_RUNTIME=1` 同时满足时生效；旧稿中的阶段完成环境变量不能开启迁移或证明验收。

原 `identity-validation.test.ts` 使用未核实路由和固定本机服务地址，不能支撑其声称的 HTTP/撤销/SSE 覆盖。该文件已改为直接调用实际 Identity 模块的隔离 owner/metadata 测试，尚未运行，也不替代最终集成验收。

<details>
<summary>保留原稿全文，仅供追溯；其中命令和伪代码不应执行</summary>

````text
# M0 实现状态核对表

日期：2026-09-08
状态：M0核对完成，进入M1实施

## E01-E23 入口实现状态核对

| ID | 入口路径 | 当前实现状态 | 待修复项 | 验证方法 |
|---|---|---|---|---|
| E01 | Desktop → opencode-server | ✅ 已接线 | 需验证发布构建不另装OpenCode | 构建&安装测试 |
| E02 | QuantCodeHome → newDraft | ⚠️ 仍强制run_agent | M2切换到native session | 代码审查 |
| E03 | SessionPrompt.prompt → Tools | ✅ 默认执行链 | 需确保Core V2不绕过 | 路径追踪 |
| E04 | /api/session V2路由 | ⚠️ 可达但未限制 | M1添加owner校验 | API测试 |
| E05 | Session CRUD → EventBridge | ⚠️ 部分owner绑定 | 补全所有入口校验 | 单元测试 |
| E06 | Message.get/updatePart | ❌ 缺owner校验 | M1添加权限检查 | 单元+集成测试 |
| E07 | SessionTools.resolve → registry | ⚠️ before可变更args | 精确审批在最终参数后 | 工具调用测试 |
| E08 | MCP.tools调用 | ⚠️ 与原生工具需统一policy | M1统一准入层 | MCP集成测试 |
| E09 | 子任务创建 | ⚠️ 需继承identity/budget | M1添加继承逻辑 | 子任务测试 |
| E10 | Provider模型调用 | ⚠️ 需单一配置源 | M2统一Provider | 模型配置测试 |
| E11 | 文件/PTY操作 | ⚠️ 工作区约束不完整 | M1补全边界检查 | 文件操作测试 |
| E12 | SSE事件订阅 | ❌ 缺跨身份隔离 | M1添加owner过滤 | 事件订阅测试 |
| E13 | 取消&恢复 | ⚠️ 需验证原owner | M1/M3完善 | 恢复测试 |
| E14 | Admin跨成员查询 | ⚠️ 投影需ACL过滤 | M3补充权限 | Admin API测试 |
| E15 | Compaction压缩 | ⚠️ 需保持owner | M1验证 | 压缩测试 |
| E16 | HTTP API直接访问 | ❌ 可能绕过session | M1统一认证 | API安全测试 |
| E17 | MCP初始化 | ⚠️ 动态工具未过滤 | M1按目录过滤 | MCP初始化测试 |
| E18 | MCP工具调用 | ⚠️ 需与原生统一 | M1统一policy | MCP权限测试 |
| E19 | Skill/Command加载 | ⚠️ 需绑定原登录 | M1刷新机制 | Skill加载测试 |
| E20 | 后台子任务 | ❌ 可能继承错误身份 | M1修复继承 | 后台任务测试 |
| E21 | Git/VCS操作 | ⚠️ 需工作区约束 | M1边界检查 | VCS操作测试 |
| E22 | 快照捕获/恢复 | ⚠️ 需按owner隔离 | M3完善 | 快照测试 |
| E23 | 旧worktree入口 | ✅ 已明确拒绝 | M4完全退役 | 兼容测试 |

## 关键风险项汇总

**🔴 高风险（必须M1修复）**
- E06: 消息修改可伪造工具完成/审批
- E12: 事件订阅无身份隔离
- E16: HTTP API可能绕过session认证
- E20: 后台任务身份继承错误

**🟡 中风险（M1/M2修复）**
- E02: 旧run_agent强制转交
- E04: Core V2路由未限制
- E10: 模型配置未统一
- E11: 文件操作边界不完整

**🟢 低风险（M3/M4处理）**
- E14: Admin查询ACL
- E22: 快照owner隔离
- E23: 旧入口兼容

## M0退出条件确认

- [x] 规范冲突核对完成
- [x] E01-E23调用链清单完整
- [x] 旧Runner能力迁移表完成
- [x] 数据兼容清单完成
- [x] M1-M4交付矩阵完成
- [x] M1草稿复核完成

## 下一步行动

1. 进入M1实施阶段
2. 优先修复高风险项（E06, E12, E16, E20）
3. 编写最小验收测试
4. 准备双路径隔离开关

---
生成时间：2026-09-08

````

</details>

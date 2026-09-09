# QuantCode 工作区说明

> QuantCode 桌面工作区复用仓库内的 OpenCode 会话、Provider、工具和事件实现；本文件只记录 QuantCode 的产品接线。

> 2026-09-08 迁移说明：以下 Day5/run_agent 内容是旧执行链记录，不能作为统一引擎已完成的依据。M1 已增加 `task-review.tsx`，原生任务与方案页复用宿主方案/能力决定接口；显示条件是原生 session 的 QuantCode binding，后端迁移开关仍默认关闭。确认直接绑定文档版本或覆盖方案摘要，不发送批准提示词。源码与 SDK 已接线，桌面视觉、性能、运行行为仍按用户要求留到所有实现后的统一验证阶段。

---

## 已完成部分（Lead 交付）

### 1. `/compose` slash 命令

文件：`packages/app/src/pages/session/use-session-commands.tsx`

- 在 `composeCmds()` 里注册 `slash: "compose"`。统一运行模式下它使用当前 QuantCode session 的原始文本，进入现有 `SessionPrompt → SessionTools → Provider` 链，不包装成第二个 Runner 调用。
- 组别由服务端 roster Session Context 决定，页面不提供切组控件。旧 `run_agent` 仅保留在明确的 legacy 兼容路径中，不能创建统一模式的新任务。

### 2. QuantCode 六面板组件

文件：`packages/app/src/components/quantcode/panels.tsx`

完整的 SolidJS 组件，Tab 切换六个面板：

- **Compose 视图**：渲染 `execution_trace` 事件流（图标 + 类型 + 摘要）
- **任务树**：按 tool_call 事件线性列出步骤
- **HumanGate**：`waiting_for_human` 状态时显示暂停提示 + reasons + thread_id
- **Schema 卡片**：渲染 `output_data`（JSON）+ artifacts 路径列表
- **Memory 浏览器**：通过受限 `search_memory` 只读通道查询组内长期 Memory；未连接和空库显示明确状态
- **会话 Resume**：最近 20 个 thread 的状态历史

导出接口：

```ts
import { QuantCodePanel, updateQuantCodeTrace, setQuantCodeSessionGroup } from "@/components/quantcode/panels"
```

**关键函数**：

- `updateQuantCodeTrace(result: RunAgentResult)` — 当 run_agent 返回 execution_trace 时调用，更新所有面板
- `setQuantCodeSessionGroup(group: string)` — 仅由服务端认证上下文桥接调用；页面不提供手动切组

### 3. 旧 Python 历史兼容

旧 checkpoint 通过受控宿主适配器只读展示，标记为 `legacy-python`。恢复必须绑定原 thread、checkpoint、owner、执行器来源、Gate 和回执；当前 Provider 桥未满足前，恢复明确返回不可用，不创建新任务，也不要求第二份模型密钥。

---

## QuantCode 首页入口

当 `OPENCODE_CHANNEL=quantcode` 时，QuantCode 工作区直接占用 `/` 首页；上游
OpenCode channel 仍保留原来的项目/会话首页。首页提交流程如下：

1. 在 Compose 区填写任务，或先套用任务模板。
2. 登录后自动绑定组、加载组 Skill，点击 **开始研究**（也支持 Command/Ctrl+Enter）。
3. 统一模式由当前研究宿主重新核对最近项目的授权；首次使用默认选中唯一可用根，
   多根时打开宿主目录选择器，没有授权根时明确提示配置问题。回环地址不代表桌面本机文件系统。
4. 选择项目后，应用创建 draft 并自动提交；模型和 agent 列表就绪前不会重复提交。

草稿页使用 QuantCode 的研究任务标题。统一模式不提供尚未接上组织授权的旧“创建 worktree”动作，目录通过授权项目选择入口变更；未知 Git 分支不会显示为 `main`。

如果研究服务器未连接或健康检查失败，首页会保留任务内容并显示连接错误，不会创建一个
无人消费的 draft。

## 当前集成状态

QuantCode 的统一模式不要求安装或启用另一个产品的 MCP。首页和 session-side-panel
都把用户原文提交给当前 QuantCode session；服务端沿用现有 Session、Provider、工具、
权限和事件链，并在边界接入 roster、工作区、预算、Gate 和回执策略。能力目录、Skill、
Memory、任务历史和产物通过受控 API 返回；组别永远由登录身份决定。

Activity、任务树、报告/产物和 Admin 页面读取原生任务事件及组织摘要投影。旧
`run_agent` 结果监听和 Python checkpoint 接口只服务兼容历史，统一模式不会把它们当作
新任务入口，也不会从中读取第二份模型配置。

### 外部能力状态

- **真实 SSH gateway**：当前 `ssh_status` 只读配置和绑定状态，不执行网络探测或私钥认证；桌面 bridge 不可用时显示 unavailable。
- **Checkpoint 列表**：已通过 legacy 宿主适配器提供受控只读列表和详情。

---

## 兼容接口说明

旧 Python 接口仅用于兼容历史记录，不能作为统一模式的新任务入口：

```json
// start（group 由已认证 Session Context 注入）
{ "name": "run_agent", "arguments": { "task": "..." } }
// resume
{ "name": "run_agent", "arguments": { "thread_id": "...", "decision": "approve" } }
```

返回：包含 `status` / `thread_id` / `gate` / `execution_trace` / `output_data` / `artifacts`

execution_trace 的 10 种事件类型：
`agent_start` / `user_input` / `llm_thought` / `tool_call` / `tool_result` /
`risk_metrics` / `human_gate` / `output_data` / `artifact` / `agent_end`

---

## 当前接线

- [x] `/compose` slash 命令进入 QuantCode 原生 session
- [x] Activity、任务树、报告/产物和 Admin 任务视图读取原生任务事件与授权投影
- [x] 旧 checkpoint 通过只读 legacy 适配器展示，并拒绝未经证明的恢复
- [x] QuantCode channel 的 `/` 首页直接挂载工作区，组别来自 roster
- [x] provider、session、权限、进程、锁和事件继续复用仓库内现有实现
## Native workspace entry

QuantCode native directory entry uses `quantcode.workspaces.list` on the selected research host. The host resolves the live member's roster workspace and explicitly enrolled local roots; frontend project history supplies a preference only. Home reuses a host-confirmed preference, defaults to the only available root, or opens the existing V2 directory picker for multiple roots. An empty result explains that a personal host or workspace enrollment is required.

The common `useDirectoryPicker` routes native QuantCode project browsing through the host's file API even for loopback connections. V2 browsing starts inside the returned roots, and selection calls discovery again with the original `login_session_id` as `expected_session_id`. Switching hosts, replacing a connection, closing the picker or disposing its owner discards pending results. The composer project selector also revalidates explicitly selected cached projects; revoked paths are rejected instead of replaced with a different project. Existing draft, Session, editor and terminal implementations remain the execution path.

Regression sources cover cached-path authorization, empty/single/multiple roots, unavailable discovery, changed login, asynchronous cancellation and root-bounded directory search. These sources have not yet been run; desktop UI review precedes the requested full test phase.

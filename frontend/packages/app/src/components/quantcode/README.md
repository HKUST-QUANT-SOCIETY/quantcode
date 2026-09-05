# QuantCode IDE 集成说明（给俞高磊）

> 本文件说明 QuantCode Day5 UI 改动的集成方法，以及俞高磊需要完成的剩余 TS 工作。

---

## 已完成部分（Lead 交付）

### 1. `/compose` slash 命令

文件：`packages/app/src/pages/session/use-session-commands.tsx`

- 在 `composeCmds()` 里注册了 `slash: "compose"`，选中后会预填 prompt：`"请用 run_agent 完成以下任务："` 并聚焦输入框。
- `.opencode/opencode.jsonc` 配置了一个名为 `quantcode` 的本地 MCP server，默认保持禁用；启用后，**`/compose` 选完用户填任务，agent 就会自动调用 `quantcode_run_agent` MCP tool**。组别只能来自服务端 Session Context，不接受任务或 UI 参数覆盖。

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

### 3. Python bridge（demo 降级路径）

文件：独立的 [QuantCode Python 仓库](https://github.com/HKUST-QUANT-SOCIETY/quantcode) 中的 `runner/demo_bridge.py`

```bash
# 在 QuantCode Python 仓库根目录运行；demo fallback 不依赖 TS 前端
cd /path/to/quantcode
python -m runner.demo_bridge --group risk --skill risk-gate \
  --task "run risk_stub high_risk" --auto-approve
# JSONL 模式（供 OpenCode spawn 消费）：
python -m runner.demo_bridge --group factor --task "测 PB-ROE 因子" --jsonl
```

---

## QuantCode 首页入口

当 `OPENCODE_CHANNEL=quantcode` 时，QuantCode 工作区直接占用 `/` 首页；上游
OpenCode channel 仍保留原来的项目/会话首页。首页提交流程如下：

1. 在 Compose 区填写任务，或先套用任务模板。
2. 确认服务端绑定的组并选择 Skill，然后点击 **Start Research**（也支持
   Command/Ctrl+Enter）。
3. 如果 Server B 已记录最近项目，任务会绑定到该项目；首次使用且没有项目时，
   会打开原生目录选择器。
4. 选择项目后，应用创建 draft 并自动提交；模型和 agent 列表就绪前不会重复提交。

如果研究服务器未连接或健康检查失败，首页会保留任务内容并显示连接错误，不会创建一个
无人消费的 draft。

## 当前集成状态

本仓库的 `.opencode/opencode.jsonc` 将 QuantCode MCP 保持为默认禁用，避免公开 OpenCode fork 在没有 Python 后端时启动失败。开发者需要设置 `QUANTCODE_ROOT` 指向 QuantCode Python 仓库，并在个人/项目配置中启用 `mcp.quantcode`。桌面安装包不会嵌入成员私钥、GitHub PAT 或 Python 仓库路径；正式 Server B 连接由 OpenCode 的服务器配置和成员本机凭据管理。

### 已完成（接入 OpenCode 桌面会话）

**Step 0 — 只读目录/状态接线**

OpenCode server 提供受限的 `GET /experimental/quantcode/tool` surface。它只允许
`search_memory`、`list_skills`、`list_algorithms`、`list_capabilities`、`ssh_status`、`session_context` 六个固定只读工具，
不会把任意 MCP tool invoke 暴露给浏览器。Skill 下拉按认证组动态刷新，算法目录在
Settings 渲染；查询失败显示未连接，不回退到过期硬编码目录。`ssh_status` 仅报告本地
配置摘要，真实 SSH 私钥认证和网络连通性探测仍需独立 gateway。

**Step 1 — 根首页和 session-side-panel.tsx 的 QuantCode 工作区**

`packages/app/src/pages/home.tsx` 的 `QuantCodeHome` 和
`packages/app/src/pages/session/session-side-panel.tsx` 都接入同一套全屏 QuantCode
工作区，并仅在 QuantCode channel 暴露入口。根首页负责创建 draft/session；已有会话则
继续从 session route 打开工作区。

**Step 2 — 校验并消费 run_agent tool result**

`packages/app/src/pages/session.tsx` 监听完成的 tool result，先通过 `result-contract.ts` 校验嵌套结构，再调用 `updateQuantCodeTrace`。畸形或双重包装失败的 MCP 输出不会进入面板状态。

```tsx
import { updateQuantCodeTrace } from "@/components/quantcode/panels"
import { parseRunAgentOutput } from "@/components/quantcode/result-contract"

const result = parseRunAgentOutput(toolResult.content)
if (result) updateQuantCodeTrace(result)
```

**Step 3 — 切组与 HumanGate resume**

组由服务端认证 Session Context 提供，页面不提供自由切组控件；HumanGate 的批准/拒绝按钮会提交精确的 `thread_id + decision` resume 指令，而不是广播无人消费的 UI 事件。

```tsx
import { buildResumeInstruction } from "@/components/quantcode/instructions"
const prompt = buildResumeInstruction(threadID, "approve")
```

### 尚未接通的外部能力

- **真实 SSH gateway**：当前 `ssh_status` 只读配置和绑定状态，不执行网络探测或私钥认证；桌面 bridge 不可用时显示 unavailable。
- **Checkpoint 列表**：仍需从 `.quantcode/checkpoints.db` 读取 thread 列表（或增加受控只读工具）。

---

## Python 侧接口契约（完整版见 [IDE_Python_Interface_Contract.md](https://github.com/HKUST-QUANT-SOCIETY/quantcode/blob/main/docs/IDE_Python_Interface_Contract.md)）

运行格式：

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

## 验收确认（Day5 §2）

- [x] `/compose` slash 命令已注册
- [x] 六面板组件已实现（Compose/任务树/HumanGate/Schema/Memory/Resume）
- [x] Python bridge 可独立运行（demo 兜底）
- [x] QuantCode channel 的 `/` 首页直接挂载工作区，并支持首次选择项目后自动提交
- [x] session-side-panel.tsx 接入 QuantCode 工作区并按 channel 隔离
- [x] run_agent tool result 监听、结构校验与 HumanGate resume

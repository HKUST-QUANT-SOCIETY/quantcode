# IDE ↔ Python 编排层接口契约（Day 5）

> **用途**：俞高磊的 OpenCode fork TS 前端与 Python 编排层对齐的唯一接口面。
> **Owner**：Lead 定义接口，俞高磊按此实现 TS 侧；两边只认这份契约，不口头约定。
> **来源**：`runner/agent_mcp_tool.py`（`run_agent` MCP tool）+ `runner/agent_engine.py`（stream trace）+ `runner/human_gate.py`（gate payload）。**这些是已合入 main 的真实代码，不是设想。**

---

## 0. 总原则

前端**不直接调 AgentRunner**，只通过 MCP tool `run_agent` 调 Python 编排层。切组 = 选不同的 `quantcode-<group>` MCP server（6 个：model/risk/factor/fundamental/strategy/options）。

一次 compose 交互 = **两阶段调用**：
1. `run_agent(start)` → 要么跑完返回 `completed`，要么撞到风险阈值返回 `waiting_for_human`（带 `thread_id`）。
2. 若 `waiting_for_human`：前端展示 gate → 用户点 approve/reject → `run_agent(resume)` 用同一 `thread_id` 恢复。

---

## 1. 入口：MCP tool `run_agent`

### start 模式（无 `decision`）
```json
{
  "name": "run_agent",
  "arguments": {
    "task": "测 PB-ROE 因子",          // 必传
    "group": "factor",                 // 可选，不传读 QUANTCODE_GROUP
    "skill_name": "factor-evaluation",   // 可选，不传用默认 prompt
    "max_iterations": 50,              // 可选，默认 50
    "thread_id": "可选：指定则用该值"
  }
}
```

### resume 模式（有 `decision`）
```json
{
  "name": "run_agent",
  "arguments": {
    "thread_id": "<start 返回的 thread_id>",  // 必传
    "decision": "approve"                     // approve|reject（内部兼容 proceed|abort）
  }
}
```

---

## 2. 返回结构（前端按 `status` 分支渲染）

`status` 有 4 种：`completed` / `waiting_for_human` / `rejected` / `error`。统一带这些字段（缺省为空）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | str | completed / waiting_for_human / rejected / error |
| `thread_id` | str | resume 用；waiting_for_human 时必看 |
| `gate` | obj | 仅 waiting_for_human：见 §3 |
| `execution_trace` | list | 状态回流事件流，见 §4（**前端主区渲染的数据源**） |
| `output_data` | obj | 最终产出（如 FactorReport / RiskProfile dict） |
| `artifacts` | list[str] | 产物文件路径（可下载/展示） |
| `risk_metrics` | obj | 风控指标（risk 流有值） |
| `human_decision` | str | resume 后回填 approve/reject |
| `error` | str | 仅 error：错误原因 |

---

## 3. `gate` 结构（waiting_for_human 时）

```json
{
  "kind": "human_gate",
  "gate_id": "<uuid>",
  "reasons": ["max_drawdown (0.22 > 0.20)", "tail_risk_var_99 ..."],
  "risk_metrics": { "max_drawdown": 0.22, "tail_risk_var_99": 0.08, ... },
  "decision_schema": { "allowed": ["approve", "reject"], "default": "reject" }
}
```

前端：显示"⏸️ 等待人工审批" + reasons + risk_metrics 卡片 + approve/reject 按钮。按钮回调 → `run_agent(resume, thread_id, decision)`。

---

## 4. `execution_trace` 事件类型（stream trace 契约）

前端主对话区按事件类型逐条渲染。已实现的 10 种 type：

| type | 渲染建议 |
|---|---|
| `agent_start` | 流开始 |
| `user_input` | 用户任务文本 |
| `llm_thought` | Agent 推理气泡 |
| `tool_call` | 工具调用卡片（tool 名 + args） |
| `tool_result` | 工具结果卡片 |
| `risk_metrics` | 风控指标面板 |
| `human_gate` | 触发人审暂停点（配合 §3 gate） |
| `output_data` | 结构化产出（Schema 卡片可用它渲染） |
| `artifact` | 产物条目（可下载） |
| `agent_end` | 流结束 |

每个事件含 `thread_id` + `data`，前端可按 thread_id 归组。

---

## 5. 六面板数据来源映射

| 面板（Day5 §2）| 数据来源 |
|---|---|
| Compose 视图 | `execution_trace` 的 agent_start / tool_call / agent_end 序列 |
| 任务树 | ComposeTask schema（Day2 已有）；Day5 可先用 trace 的 tool_call 线性列 |
| HumanGate 暂停点 | `status==waiting_for_human` + `gate`（§3） |
| Schema 卡片 | `output_data`（factor 流的 json_schema 字段） |
| Memory 浏览器 | 只读 `.quantcode/memory.db` / MEMORY.md（需一个只读桥，见 §6） |
| 会话 Resume | checkpoints.db 列表 + `run_agent(resume)` |

---

## 6. 待补的接口（Lead 需再给 / 降级方案）

- **Memory 浏览器**：目前无只读 MCP tool 暴露 memory。降级：前端直接读 `.quantcode/memory.db`（SQLite），或 Lead 补一个 `search_memory` 只读入口。Day5 可先读文件。
- **checkpoints 列表**：resume 需要能列出某会话的 checkpoint。降级：前端读 `.quantcode/checkpoints.db` 的 thread_id/checkpoint_id。
- **降级总方案**（Day5 §2）：TS 集成卡住时，OpenCode spawn `python -m runner.agent_mcp_tool` + stdout JSONL 回流，前端读 JSONL 渲染同样的 execution_trace。

---

## 7. 本地验证（俞高磊可直接跑）

```bash
# high-risk → waiting_for_human
python -c "from runner.agent_mcp_tool import _run_agent_execute, RunAgentArgs; \
import json; print(json.dumps(_run_agent_execute(RunAgentArgs(task='run risk_stub high_risk', group='risk', skill_name='risk-gate'), ctx={'group':'risk','_model':lambda m,tools=None:None}), ensure_ascii=False, default=str)[:400])"
```
（需配 provider key 才能跑真 LLM；结构性验证用 mock model 即可看到 waiting_for_human + gate。）

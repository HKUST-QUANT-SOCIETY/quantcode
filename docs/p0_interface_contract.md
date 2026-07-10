# P0 IDE 接口契约（Day 5 尹一帆 → 俞高磊）

> **目标读者**：俞高磊的 IDE 前端集成（含其 AI 协作者）
> **目的**：把 Day 5 主链路 5 件 P0 的 Python 侧接口契约**写死**，避免 IDE 端靠猜 → Day 6 返工
> **状态**：4/5 已可对接，1/5（checkpoint list/resume）需要 Day 6 补一个最小 API
> **配套**：PR 同名 commit 引入本文件；本文档 = Python 侧真实接口的"事实来源"

---

## 1. /compose 真实触发 Python 的入口

### 1.1 入口：`run_agent` MCP tool

IDE 通过 MCP（Model Context Protocol）stdin/stdout JSON-RPC 调用 Python。一切的"门"是 `run_agent` tool。

**MCP 启动配置**（已写在 `opencode.jsonc`，你无需改）：

```jsonc
"mcp": {
  "quantcode": {
    "type": "local",
    "command": ["uv", "run", "python", "-m", "quantcode.mcp_server"],
    "enabled": true
  }
}
```

**MCP 协议要点**：
- 客户端发起 `tools/call` with `name="run_agent"`, `arguments={...}`
- 服务端返回 `{"content":[{"type":"text","text":<JSON string>}], "isError":false}`
- `text` 字段是**JSON 字符串**（MCP 规定），需要再 `JSON.parse` 一次拿到结构化结果

### 1.2 `run_agent` 输入 schema

定义在 `runner/agent_mcp_tool.py::RunAgentArgs`（Day 7 已支持 start/resume 两阶段）：

```typescript
// IDE 侧 TS 类型定义参考
type RunAgentArgs = {
  task?: string;              // start 模式必传：自然语言任务
  group?: string;             // 可选：model/risk/factor/fundamental/options/strategy
                              //  不传则从 QUANTCODE_GROUP 环境变量读
  skill_name?: string;        // 可选：要加载的 skill（如 "model-pr-submit"）
  max_iterations?: number;    // 默认 50

  // ── Day 7: resume 协议字段 ──
  thread_id?: string;         // resume 模式必传：要恢复的已暂停 thread_id
  decision?: "approve" | "reject" | "proceed" | "abort";  // 有值=resume，无值=start
}
```

### 1.3 调用样例（TS 侧）

```typescript
// start: 启动一个新任务
const startResp = await mcp.callTool("run_agent", {
  task: "测 PB-ROE 因子",
  group: "factor",
  skill_name: "factor-autoeval",
  max_iterations: 30,
});

// resume: 恢复已暂停的 gate
const resumeResp = await mcp.callTool("run_agent", {
  thread_id: "factor-mcp_compose-1719876543-a1b2c3d4",
  decision: "approve",
});
```

### 1.4 路由决策（Day 5 新增）

`run_agent` 会根据 `group + task 关键词` 自动分派到执行器子 skill（避免加载通用编排器 prompt）：

| group | task 含... | 路由到 skill |
|---|---|---|
| model | pr / submit / pull request / handoff | `model-pr-submit` |
| model | lit review / paper / arxiv | `model-lit-review` |
| risk | pr / risk / gate / review | `risk-gate` |
| factor | factor / autoeval / ic / ir | `factor-autoeval` |
| options | options / vol / greeks / backtest | `options-compose` |

代码：`runner/agent_mcp_tool.py::ORCHESTRATOR_DISPATCH`（line 76-90）

---

## 2. 主区 stream event schema

### 2.1 输出结构

`run_agent` 的最终输出含 **`execution_trace: AgentTraceEvent[]`**，是给 IDE 主区流式渲染的事件流。

```typescript
type AgentTraceEvent = {
  schema_version: "agent_trace.v1";   // 当前固定 v1
  seq: number;                       // 单调递增，1-based
  type: TraceEventType;               // 见 §2.2
  node: string | null;               // LangGraph 节点名
  thread_id: string;
  group: string;                     // model/risk/factor/...
  flow_name: string;                 // 如 "mcp_compose" / "risk:gate"
  iteration: number | null;
  data: Record<string, unknown>;     // type-specific payload
}
```

代码：`runner/agent_engine.py::stream()` line 442-455 的 `emit()` 函数。

### 2.2 event type 清单

| type | 何时产生 | data 字段 |
|---|---|---|
| `agent_start` | run 开始 | `{task: string}` |
| `skill_loaded` | skill 加载完成 | `{skill_name, summary}` |
| `llm_thought` | LLM 产生文字内容（非 tool_call） | `{content: string}` |
| `tool_call` | LLM 决定调用 tool | `{tool, args, tool_call_id}` |
| `tool_result` | tool 执行完 | `{tool, tool_call_id, result, is_error}` |
| `risk_metrics` | 风险指标计算完 | `{metrics: {...}}` |
| `output_data` | 输出数据 ready | `{output_data: {...}}` |
| `artifact` | 文件产物 ready | `{path: string}` |
| `human_gate` | HumanGate 触发 | `{gate: {...}}` |
| `node_update` | 通用 node 状态 | `{keys: string[]}` |
| `agent_end` | run 结束 | `{status: "completed"\|"stopped"\|"rejected"}` |
| `error` | 异常 | `{error: string}` |

代码：`runner/agent_engine.py::_append_trace_from_update()` line 613-676 + `emit()` 散落 line 457-557。

### 2.3 ⚠️ loop_detected 单独 event（**待补**）

俞高磊要求"`loop_detected` 需要单独 stream event，不要混成普通 error"。**当前状态**：
- `tools/loop_detector.py` 检测到 loop 会触发 `human_gate` routing（进入 interrupt 路径），不会产出 `loop_detected` 事件
- `error` event 是异常类，不是 loop 类

**Day 6 计划**（5 行改动）：在 `runner/agent_engine.py::_append_trace_from_update()` 里加一个 `trace_emit("loop_detected", ...)` 分支，当 `update["routing"] == "state_loop" or update["routing"] == "loop"` 时发出。

```typescript
// 期望的 type（Day 6 加）
type LoopDetectedEvent = {
  type: "loop_detected";
  data: {
    tool: string;          // 重复调用的 tool
    args: Record<string, unknown>;
    count: number;         // 触发时的累积次数
    threshold: number;     // LoopDetector 配置
    action: "human_gate";  // 当前行为：转人审
  };
}
```

**当前 workaround**：IDE 端可以通过 `human_gate` event + `gate.reasons` 含 "loop detected" 推断。但显式 `loop_detected` event 更干净。Day 6 补。

### 2.4 输出顶层字段

```typescript
type RunAgentOutput = {
  status: "completed" | "stopped" | "rejected" | "waiting_for_human" | "error";
  iterations: number;
  thread_id: string;
  final_message: string;            // 最后一条 AI 消息的 content
  tool_calls: Array<{tool, args, result}>;  // 简化版（每条 tool 的名字+参数+结果）
  execution_trace?: AgentTraceEvent[];       // ★ 主区 stream 渲染用这个

  // 可选：风险场景专用
  risk_metrics?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  artifacts?: string[];
  errors?: string[];

  // resume 模式返回时附
  human_decision?: "approve" | "reject";
}
```

代码：`runner/agent_mcp_tool.py::_format_result()` line 578-640。

---

## 3. HumanGate 协议

### 3.1 waiting_for_human 触发

当 `run_agent` 返回 `status: "waiting_for_human"` 时，IDE **必须**：
1. 展示 `gate` 字段（含 `gate_id`, `message`, `reasons`, `decision_schema`）
2. 等待用户选 `approve` / `reject`
3. 用同 `thread_id` + `decision` 字段再调一次 `run_agent`（即 resume 模式）

```typescript
type WaitingForHuman = {
  status: "waiting_for_human";
  thread_id: string;
  gate: {
    kind: "human_gate";
    gate_id: string;            // hg_<safe_tid>_<uuid12>
    thread_id: string;
    message: string;            // 默认 "⏸️ 等待人工审批"
    reasons: string[];          // 触发原因（VaR 超阈值等）
    risk_metrics: Record<string, unknown>;
    risk_profile: Record<string, unknown>;
    decision_schema: {
      allowed: ["approve", "reject"];
      default: "reject";        // fail-closed
    };
  };
}
```

代码：`runner/human_gate.py::_gate_payload_for_opencode()` line 58-80 + `format_waiting_for_human()` line 159-188。

### 3.2 approve/reject 决策映射

IDE 端只暴露 `approve` / `reject`（不用 `proceed` / `abort`），Python 侧会做归一化：

| IDE 传 `decision` | Python 内部映射 | 实际行为 |
|---|---|---|
| `"approve"` | `proceed` | 继续执行 |
| `"reject"` | `abort` | 中止 run |
| `"proceed"` | `proceed` | 兼容（不推荐用） |
| `"abort"` | `abort` | 兼容（不推荐用） |
| 其他 / 缺省 | `abort` | fail-closed |

代码：`runner/human_gate.py::normalize_external_decision()` line 34-44。

### 3.3 resume 调用

```typescript
await mcp.callTool("run_agent", {
  thread_id: "<waiting 时返回的 thread_id>",
  decision: "approve",  // 或 "reject"
});
```

返回 `status: "completed" | "rejected" | "error"`。

代码：`runner/agent_mcp_tool.py::_resume_mode()` line 513-575。

---

## 4. checkpoint list / resume 最小接口

### 4.1 当前状态

**Day 5 状态**：checkpoint 持久化（`SqliteSaver`）和 single-thread resume 已可用，但 **`list` 接口没暴露**。

底层已就绪：
- `runner/langgraph_base.py::get_checkpointer(db_path)` — 拿到 SqliteSaver 实例
- 持久化路径：MCP 用 `.quantcode/opencode-checkpoints.db`，CLI 用 `.quantcode/checkpoints.db`
- 单 thread resume：通过 `runner.AgentRunner.resume(thread_id=..., decision=...)`

### 4.2 Day 6 待补：list 接口

**最小实现**（俞高磊你需要的话我可以 Day 6 上午补）：

新加一个 MCP tool `list_threads`：

```typescript
type ListThreadsArgs = {
  group?: string;     // 可选过滤
  limit?: number;     // 默认 20
  status?: "active" | "completed" | "interrupted" | "all";  // 默认 "all"
}

type ThreadSummary = {
  thread_id: string;
  group: string;
  flow_name: string;
  status: "active" | "completed" | "interrupted";
  created_at: string;    // ISO 8601
  updated_at: string;    // ISO 8601
  last_task: string;     // 最近一次 task 文本（截 200 字）
}
```

**实现路径**：直接读 SqliteSaver 背后的 SQLite，查 `checkpoints` 表的 `thread_id` + `checkpoint` JSON 里的 `ts` + `channel_values.messages[0].content`（task 文本）。

**预计工作量**：1-2 小时（含测试）。需要的话告诉我，加 Day 6 第一批。

### 4.3 当前 workaround

Day 5 IDE 可以先用 `run_agent` 的 `thread_id` 字段做"我记得刚才那次 run"—— IDE 自己存最近 N 个 thread_id 即可。不强求 Day 5 就有 list API。

---

## 5. model/risk/factor 三组 Happy Path

### 5.1 测试覆盖证据

`tests/test_six_groups_react_e2e.py` 已经覆盖所有 6 组的 ≥3 步 + artifact（每组 2 测试 = 12 个 invocation）。**model / risk / factor 三组的 PASS 状态**：

```bash
$ pytest tests/test_six_groups_react_e2e.py -v -k "model or risk or factor"
tests/test_six_groups_react_e2e.py::test_group_agent_runs_three_plus_steps_and_produces_artifact[model] PASSED
tests/test_six_groups_react_e2e.py::test_group_agent_does_not_hang_on_simple_task[model] PASSED
tests/test_six_groups_react_e2e.py::test_group_agent_runs_three_plus_steps_and_produces_artifact[risk] PASSED
tests/test_six_groups_react_e2e.py::test_group_agent_does_not_hang_on_simple_task[risk] PASSED
tests/test_six_groups_react_e2e.py::test_group_agent_runs_three_plus_steps_and_produces_artifact[factor] PASSED
tests/test_six_groups_react_e2e.py::test_group_agent_does_not_hang_on_simple_task[factor] PASSED
6 passed
```

### 5.2 ⚠️ Caveat：schema 校验是 keyword 级，非 Pydantic 级

测试用 keyword `model_spec` / `risk_profile` / `factor_report` 搜索 LLM mock 字符串，**不是真 `ModelSpec.model_validate()`**。真 schema 合规由 Lead 维护的 `flows/*.py` 兜底（Day 5 §1.1 spec vs Lead §0 口径差）。

**对 IDE 的影响**：当 LLM 返回 schema-non-compliant artifact 时，IDE 端应自行做 Pydantic 二次校验（用 `tools/schema_utils.py::pydantic_to_json_schema()` 转的 schema）。Python 侧 schema 定义随 group 注册：

```python
# 例子：model group 的真 schema（如果启用了的话）
from quantcode.schemas.v1 import ComposeTaskEvent  # 之类
# IDE 侧：拿到 artifact JSON 后做一次 Pydantic v2 校验
```

**Day 6 计划**：跟 Lead 对齐 `flows/*.py` 的真 schema 注册到 MCP `tools/list` 的输出里（这样 IDE 拉 tool list 时能拿到对应 schema 直接做客户端校验）。

### 5.3 Happy Path 调用样例（factor 组）

```typescript
// 1) 启动
const resp = await mcp.callTool("run_agent", {
  task: "测 PB-ROE 因子",
  group: "factor",
  skill_name: "factor-autoeval",
});

// 2) 流式渲染 execution_trace（如果 MCP 支持 stream；否则一次拿全量再渲染）
// execution_trace: [
//   {type:"agent_start", ...},
//   {type:"skill_loaded", data:{skill_name:"factor-autoeval", ...}},
//   {type:"llm_thought", data:{content:"我来评估..."}},
//   {type:"tool_call", data:{tool:"match_main", args:{...}}},
//   {type:"tool_result", data:{tool:"match_main", result:"..."}},
//   {type:"tool_call", data:{tool:"gen_schema", args:{...}}},
//   {type:"tool_result", data:{tool:"gen_schema", result:"..."}},
//   {type:"tool_call", data:{tool:"autoeval", args:{...}}},
//   {type:"tool_result", data:{tool:"autoeval", result:"..."}},
//   {type:"artifact", data:{path:"artifacts/factor/.../factor_report.json"}},
//   {type:"output_data", data:{output_data:{...}}},
//   {type:"agent_end", data:{status:"completed"}},
// ]

// 3) 最终 output_data 给 factor 的 Schema 卡片组件渲染
const artifact = resp.output_data;  // {factor_id, ic, ir, ...}
```

---

## 附录 A：Dream / Memory 浏览器契约（俞高磊已答复）

**Dream 刷新机制**（Day 5 定）：`trigger_dream()` 跑完后写两条事件到 `.quantcode/dream_events.jsonl`：

```typescript
type DreamEvent = {
  event: "dream_started" | "dream_completed" | "dream_failed";
  timestamp: string;        // ISO 8601
  payload: {
    rlhf_path?: string;     // dream_started
    thread_id?: string;
    hits_count?: number;
    duration_ms?: number;
    error?: string;         // dream_failed
  };
}
```

代码：`dream/trigger.py::_emit_event()` line 32-54 + `trigger_dream()` line 57-132。

**Memory 浏览器**（俞高磊出骨架）：支持 list + detail + 手动刷新即可，**不要求实时 push**。数据源是 `.quantcode/memory.db`（FTS5 SQLite，Day 4 已建）。

## 附录 B：Loop 检测 + RLHF（Day 5 决定）

- **loop_detected**：见 §2.3，Day 6 单独事件。当前通过 `human_gate` event 透传。
- **RLHF 面板**：Day 5 不做，Week 2 备选。数据收集**已在跑**（`.quantcode/rlhf_data.jsonl`），不需要 IDE 加面板。

## 附录 C：环境变量（IDE 启动 MCP 时要确保有）

| 变量名 | 必传 | 说明 |
|---|---|---|
| `QUANTCODE_GROUP` | 是 | 当前活跃组，决定 `tools/list` 过滤 |
| `QUANTCODE_API_KEY` 或 `STEPFUN_PLAN_API_KEY` 或 `ANTHROPIC_API_KEY` | 是 | LLM API key（优先级：QUANTCODE > STEPFUN > ANTHROPIC）|
| `QUANTCODE_MODEL_PROVIDER` | 否 | `stepfun` (默认) / `anthropic` |
| `QUANTCODE_MODEL_NAME` | 否 | 默认 `step-3.7-flash` |
| `QUANTCODE_MODEL_BASE_URL` | 否 | 默认 Stepfun endpoint |

代码：`quantcode/mcp_server.py::_get_model()` line 135-233。

## 附录 D：测试覆盖（IDE 集成测试可借鉴）

| 测试文件 | 覆盖 | 命令 |
|---|---|---|
| `tests/test_six_groups_react_e2e.py` | 6 组 ≥3 步 + artifact | `pytest tests/test_six_groups_react_e2e.py -v` |
| `tests/test_cross_group_stability.py` | 跨组流不挂、不爆 context | `pytest tests/test_cross_group_stability.py -v` |
| `tests/test_demo_scenario_4.py` | loop + dream + rlhf 集成 | `pytest tests/test_demo_scenario_4.py -v` |
| `tests/test_retry.py` | LLM 重试 + RetryStats | `pytest tests/test_retry.py -v` |
| `tests/test_dream_*.py` | Dream 触发/CLI/scheduler | `pytest tests/test_dream_trigger.py tests/test_dream_cli.py tests/test_dream_scheduler.py -v` |
| `tests/test_mcp_server.py` | MCP 协议端到端 | `pytest tests/test_mcp_server.py -v` |

完整回归：`pytest tests/ --tb=line -q`（582 passed / 5 skipped / 0 failed）。

---

**最后更新**：2026-07-10 尹一帆 · PR 见 yifan-day5 分支
**Day 6 承诺项**：§2.3 loop_detected 单独 event + §4.2 list_threads MCP tool（如果你要的话）
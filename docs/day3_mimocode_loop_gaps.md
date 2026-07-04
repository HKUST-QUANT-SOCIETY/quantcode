# Day 3 · 用 LangGraph 改写 MimoCode loop 缺了哪些配套

> Owner: 尹一帆  
> 最后更新: 2026-07-04  
> 配套代码: `runner/agent_engine.py`、`runner/agent_nodes.py`、`tools/registry.py`

## 背景

MimoCode (`MiMo-Code/packages/opencode/src/tool/`) 的 compose loop 是一个 TypeScript 写成的 ReAct
循环（在 `prompt.ts` 的 `runLoop` 里）：while 没拿到 final answer → 调 LLM → 调 tool → 观察 → 继续。

我们 Day 3 决策：**用 LangGraph Python 自己搭 StateGraph**，不直接复用 MimoCode 的 TS loop。
原因（详见计划 §研究点 1）：

1. 架构 §3.1 要求 TaskGate / GoalGate 自定义终止条件，`create_react_agent` 的 state schema
   受限，插不进去。
2. 架构 §3.2 要求循环检测、迭代上限、状态指纹、RLHF 接入点。
3. 自搭 StateGraph 把每个 gate / 检测做成 node，可观测、可单测。

这条路线的代价：**自己实现 MimoCode 内置、但 LangGraph 不直接给的能力**。
本文档列出这些 gap，每项标"Day 3 已做 / Day 4 / 不做"。

---

## 1. 已实现（Day 3 自搭 StateGraph 涵盖）

| 能力 | MimoCode 来源 | LangGraph 怎么做 | 我们的实现 |
|---|---|---|---|
| ReAct 循环 | `prompt.ts::runLoop` while | `add_node` + `add_conditional_edges` | `runner/agent_nodes.py`（5 个节点 + 2 个条件边） |
| Checkpoint | `MimoCode/skill/builtin/.bundle/loop` 增量保存 | `SqliteSaver` + `thread_id` | 复用 `runner.langgraph_base.get_checkpointer` |
| Tool 注册 | `tool/registry.ts` 全局 Map | `ToolRegistry` 单例 + `register_tool` | `tools/registry.py` |
| Tool schema 校验 | Zod `parse()` 抛错 | Pydantic `model_validate()` | `registry.call()` 内置 |
| Tool 错误恢复 | Try/catch 包 execute | `tool_node` 捕获 → ToolMessage 返回 | `tool_node` 内置（错误进 message 让 LLM 决定重试） |
| 系统提示注入 | `prompt.ts` 拼 SKILL.md body | `llm_node` 读 `state["system_prompt"]` | `tools.skills.loader.load_skill()` |
| Tool allowlist | MimoCode 无 group 概念 | 自定义 `load_group_config()` + `get_tools_for_group()` | `.opencode/groups/*/tool_allowlist.yaml` |
| MCP 暴露 tool | MimoCode 自身就是 TUI/CLI | 手写 JSON-RPC stdio server | `quantcode/mcp_server.py` |

---

## 2. MimoCode 有但 Day 3 没做（**需评估**）

### 2.1 同一轮多个 tool_calls 并行执行  `MEDIUM PRIORITY`

- MimoCode 行为：LLM 一次返回多个 tool_calls 时，**并行**调用（用 Promise.all）。
- LangGraph 默认行为：`tool_node` **串行**执行多个 tool_call。
- 影响：速度慢；当 tool 互相独立时浪费 IPC 时间。
- Day 3 现状：**串行**（不做优化）。
- Day 4 评估：用 `asyncio.gather` 把 tool_node 改成 async + 并行，或拆成 N 个 tool_node 实例。

### 2.2 Token 上下文裁剪  `MEDIUM PRIORITY`

- MimoCode 行为：`tool.ts::truncate.output` 在 tool 返回超长时自动截断，省 token。
- LangGraph 默认：不裁剪，messages 列表无限增长。
- 影响：长 task 会爆 context window。
- Day 3 现状：**不裁剪**。SKILL.md 都 < 200 行，加上 3 步工具调用，messages 不会爆。
- Day 4 评估：加一个 `truncate_node` 插在 tool_node 后，对 `messages[i].content > N tokens` 截断。

### 2.3 LLM API 错误重试（rate limit / 401 / timeout）  `LOW PRIORITY`

- MimoCode 行为：内置重试 + 退避。
- LangGraph 默认：`llm_node` 抛异常直接挂掉整个 graph。
- 影响：单次网络抖动就 task 失败。
- Day 3 现状：**让 tool_node 捕获 → ToolMessage 返回错误**，LLM 自己决定重试（迂回方案）。
- Day 4 评估：加 `retry_node` + 指数退避（1s/2s/4s），max 3 次后 END。

### 2.4 Tool 描述自动从 description 生成 few-shot example  `SKIP`

- MimoCode 行为：每个 tool 内置 examples，喂给 LLM。
- 我们：description 已经包含调用时机 + 输入输出 schema，足够 LLM 决策。
- 不做。

### 2.5 Streaming 输出（逐 token）  `LOW PRIORITY`

- MimoCode 行为：TUI 实时显示 token-by-token。
- LangGraph 默认：`app.stream()` 按 node 输出，不按 token。
- 影响：用户体验差，但不影响正确性。
- Day 3 现状：用 `app.stream()` 按 node 输出（每 node 一个 chunk）。
- Day 4 评估：调 LangChain 的 `ChatModel.stream()` 暴露给 MCP server。

### 2.6 HumanGate interrupt（MimoCode 权限系统）  `MEDIUM PRIORITY`

- MimoCode 行为：permission rule `action="ask"` 触发 interrupt，阻塞等用户 approve。
- LangGraph 1.x 支持 `interrupt_before=["gate_node"]`，但 Day 3 没接入。
- 影响：副作用 tool（PR 评论、邮件）能直接跑，没人审。
- Day 3 现状：靠 `@dedupe_within` 防重复，没真审。
- Day 4 评估：在 tool_node 前加 `gate_node`，permission=ask 时 `interrupt_before`。

### 2.7 跨 turn 上下文压缩  `SKIP`

- MimoCode 行为：长对话自动压缩成摘要。
- 我们：单任务 < 10 步，无此需求。

---

## 3. LangGraph 有但 MimoCode 没有（**我们反而占了便宜**）

| 能力 | LangGraph 优势 | MimoCode 对应 |
|---|---|---|
| 真正的 checkpoint + 状态恢复 | SqliteSaver 自动序列化整个 state | 手写 `.mimocode/checkpoint.md` |
| Thread-level 并发隔离 | `configurable.thread_id` 原生支持 | 自实现 session lock |
| 强类型 state schema | TypedDict + operator.add reducer | any-typed Map |
| 内置 LangSmith 可观测 | 开箱即用 | 无 |
| 中间步骤可视化 | `app.stream()` 按 node 流 | 自己打 log |

---

## 4. 总结

**MimoCode compose loop ≈ 200 行 TypeScript，覆盖 1 个 ReAct 循环 + 几个 hook。**

**我们 Day 3 自搭 ≈ 800 行 Python（节点 + 边 + 条件函数 + 测试），覆盖：**

- ReAct 循环 ✓
- 按组过滤 ✓（MimoCode 没有）
- Checkpoint ✓（复用 Day 2）
- 循环/迭代/状态指纹检测 ✓（MimoCode 没有）
- RLHF 接入点 ✓（MimoCode 没有）
- Skill 双源加载（业务 + 元）✓（MimoCode 是单一来源）
- MCP 暴露 ✓（MimoCode 自己就是 CLI）

**Day 4 待补的差距（按优先级）：**

1. **并行 tool call**（速度）
2. **Token 裁剪**（长任务）
3. **LLM 错误重试**（稳定性）
4. **HumanGate interrupt**（权限/合规）

不做的：few-shot 自动生成、streaming token、跨 turn 压缩——当前 scale 用不上。

---

## 5. 验证清单（汇报时引用）

- [x] ≥3 步任务: `test_agent_runs_three_step_task` 通过
- [x] ≥1 skill 能用: `test_agent_uses_skill_markdown_as_system_prompt` + `test_agent_uses_meta_skill_when_no_group` 通过
- [x] checkpoint 恢复: `test_agent_resume_from_checkpoint` 通过
- [x] 多 Agent 并发不冲突: `test_two_concurrent_agents_dont_conflict` 通过
- [x] tool 按组隔离: `test_agent_filters_tools_by_group` 通过
- [x] 循环检测触发: `test_post_tool_check_triggers_loop_on_repeated_call` 通过
- [x] 状态指纹触发: `test_post_tool_check_triggers_state_loop_on_repeated_state` 通过
- [x] 迭代上限触发: `test_agent_stops_on_max_iterations` 通过
- [x] OpenCode MCP 启动: stdio 烟测通过（`python -m quantcode.mcp_server` 能响应 initialize / tools/list / tools/call）

**全量测试：248 个通过、1 个 skipped（任务清单硬性指标 ≥80）**
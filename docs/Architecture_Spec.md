# QuantCode 架构规格说明 v2

> **版本**：v2（三层架构：TS 控制层 + Python/LangGraph 编排层 + Python 执行层）  
> **Owner**：Lead  
> **最后更新**：2026-06-30

---

## 0. 核心决策

**技术选型**：Python/LangGraph 编排层 + TypeScript 控制层（OpenCode fork）+ Python 执行层。三层跑在同一个 MimoCode/OpenCode 运行环境里。

**为什么编排层用 Python/LangGraph（而不是照用 MimoCode 的 TS loop）**：
1. **教学目标**：团队在 LangGraph Python 高级用法（ReAct、checkpoint、自研加固）上沉淀工程能力
2. **算法侧接入**：RLHF 微调、评估、训练数据收集需要 Python 生态
3. **自研加固**：死循环检测、迭代上限、循环检测——MimoCode 有基础版，我们做得更细，作为组员的工程练习

**关于 compose 模式的专项讨论结论**（不改变编排层用 LangGraph 这个总口径，只是明确怎么落地）：
- **compose 的本质是 ReAct 循环**：MimoCode 的 compose（`prompt.ts` 的 `runLoop`）就是 while 循环（推理 → 调 tool → 观察 → 再推理）。LangGraph 的 `create_react_agent` 是同一范式的封装，两者天然兼容。
- **复用 MimoCode 的 15 个 compose skill**：它们是 markdown 文本（brainstorm / plan / execute / tdd / review…），引擎无关，直接喂给我们的 LangGraph Agent 即可复用，不用重写。
- **借鉴 compose 的设计**：skill 加载机制、tool registry、permission 的 ask 人审——这些设计我们参考并在 LangGraph 编排层实现。
- 我们做的是**自己的 LangGraph 编排层，复用 + 借鉴 MimoCode 的好东西**，不是去改 MimoCode 的源码。

**从 OpenCode/MimoCode 调研学到的核心原则**：
- ✅ **ReAct 循环，不预定义 DAG**：Agent 自己推理流程，不是执行预设拓扑
- ✅ **Tool 完全解耦**：统一接口 + registry，tool 间零依赖
- ✅ **compose = 同一循环 + 不同配置**：6 个组共用一个 ReAct loop，只是换 skill(prompt) + tool 白名单
- ✅ **Permission 的 `ask` 就是人审**：不需要复杂状态机，权限规则里 action="ask" 就 interrupt
- ✅ **15 个 skill 是 markdown 文本**：引擎无关，喂给 LangGraph Agent 即可复用
- ✅ **Memory = SQLite FTS5 + markdown**：我们 Day 2 已做，方向正确

---

## 1. 三层架构总览

> 三层跑在同一个 MimoCode/OpenCode 运行环境里。编排平面是我们的 Python/LangGraph 层，复用 MimoCode 的 15 个 skill、借鉴其 compose 设计。

```
┌─────────────────────────────────────────────────────────────┐
│ 控制平面（TypeScript / OpenCode fork，复用+改进）            │
│ - SSH key → 组绑定（长期）                                    │
│ - 任务提交 + SSE 订阅 Agent 状态流                          │
│ - 可视化：Agent 当前在调用什么 tool、在想什么                │
└────────────────┬────────────────────────────────────────────┘
                 │ 触发 compose 流
┌────────────────▼────────────────────────────────────────────┐
│ 编排平面（Python / LangGraph）                               │
│                                                             │
│ ★ 引擎内核：ReAct 循环（create_react_agent）               │
│   while not done:                                           │
│     thought = llm("现在该做什么？", tools, history)          │
│     result = execute_tool(thought.tool_call)                │
│     done = check_gates()  # taskGate / goalGate            │
│     checkpoint()  # LangGraph SqliteSaver                  │
│                                                             │
│ ★ 复用 MimoCode 的 15 个 compose skill（markdown）：       │
│   brainstorm / plan / execute / tdd / review / debug ...   │
│   （引擎无关的工作流知识，作为 prompt/context 喂给 Agent）  │
│                                                             │
│ ★ 自研加固（MimoCode 有基础版，我们做更细）：              │
│   - 死循环检测 / 迭代上限 / 状态指纹循环检测                │
│   - RLHF 接入点（记录 state/action/reward 到训练集）       │
│                                                             │
│ ★ 基础设施（Day 2 已建）：                                  │
│   - Memory FTS5（5-scope 权限）· Blackboard（跨组共享）    │
│   - Permission 规则（allow/deny/ask）· Tool Registry       │
└────────────────┬────────────────────────────────────────────┘
                 │ 调用 tool
┌────────────────▼────────────────────────────────────────────┐
│ 执行平面（Python tools + 外部系统）                          │
│                                                             │
│ ★ 量化 tool：                                               │
│   read_pr / extract_metadata / match_main / gen_schema /   │
│   calc_risk / write_pr_comment / ...                        │
│ ★ 外部系统：AutoEval · SSH · COS · GitHub · RAG · RLHF    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 控制平面职责（TypeScript / OpenCode fork）

控制平面复用 MimoCode/OpenCode 现有能力，改进之处标注 ★。

### 2.1 组绑定（SSH Key 长期绑定）

**流程**：
1. 用户通过 SSH key 登录 OpenCode
2. 系统查 `.opencode/config.yaml` 的 SSH key → 组映射表
3. 加载该组的配置（system prompt、tool 白名单、permission 规则）

**关键**：绑定是长期的，会话内不可变。跨组协作通过 Blackboard PROJECT scope，不改变组身份。

### 2.2 触发 compose 流

**用户操作**：在 OpenCode CLI/UI 输入 compose 命令，如：
```bash
/compose "处理 PR #123 并交给风控"
```

**系统行为**：
1. 识别用户所属组（已绑定的 SSH key → group）
2. 触发该组的 compose Agent（LangGraph 改写的引擎）
3. 实时流式显示 Agent 状态（thought / tool_call / tool_result）

### 2.3 可视化 Agent 状态

**复用 MimoCode/OpenCode 现有能力**：
- session 消息流
- tool 执行日志
- checkpoint 列表

**★ 我们的改进**：
- 显示当前加载的 skill（哪个 SKILL.md）
- 显示 Blackboard 跨组数据流（谁写了什么、谁读了什么）
- 显示 HumanGate 暂停点（VaR 超阈值等待人审）

---

## 3. 编排平面职责（Python / LangGraph）

### 3.1 ReAct Agent 主循环

**核心设计**：不预定义 DAG，Agent 自己推理流程。

**实现**：使用 LangGraph 的 `create_react_agent`

```python
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.sqlite import SqliteSaver

# 定义 Agent
agent = create_react_agent(
    model=llm,                    # ChatAnthropic / ChatOpenAI
    tools=get_tools_for_group(group),  # 该组可用的 tools
    checkpointer=SqliteSaver(".quantcode/checkpoints.db"),
    state_modifier=build_system_prompt(group),  # 该组的 system prompt
)

# 执行（自动 ReAct 循环）
config = {"configurable": {"thread_id": task_id}}
for chunk in agent.stream({"messages": [("user", task)]}, config):
    # 流式输出：thought / tool_call / tool_result / final
    emit_sse(chunk)
```

**ReAct 循环内部**（LangGraph 自动处理）：
1. LLM 推理 → 生成 tool call 或 final answer
2. 工具执行 → LangGraph 自动调用 tool function
3. Checkpoint → 每步自动保存到 SQLite
4. 循环 → 直到 LLM 返回 final answer（不再调 tool）

**终止条件**（我们自研的 gates）：
- **TaskGate**：检查任务列表是否全部完成
- **GoalGate**：用独立模型评估目标是否满足
- **迭代上限**：MAX_ITERATIONS（默认 100）

### 3.2 路由设计（Agent Loop 的真正开关）

**定位**：路由是 ReAct 循环的心脏。`create_react_agent` 内部靠 **conditional edges + 路由函数**决定"每一步之后去哪"——loop 能转起来、能在正确的点分叉/暂停/结束，全靠它。路由函数读当前 state，返回下一个节点名，是 LangGraph 层最核心的自研补充点。

**两个层次的路由（不要混淆）**：

| 层次 | 位置 | 谁决定 | 作用 |
|---|---|---|---|
| **外层路由**（组/流入口） | 控制平面（TS） | SSH key → 组；idea → 模式 | 决定加载哪个 Agent（哪套 prompt+tools） |
| **内层路由**（Loop 开关） | 编排平面（LangGraph） | 路由函数读 state | 决定 Agent 每一步之后去哪个节点 |

外层路由见 §2.1/§2.2（一次性，进入时定）。**本节讲内层路由——它在 loop 里每一步都在运行，是真正的执行开关。**

**内层路由的核心节点**：

```
        ┌──────────────┐
        │ LLM 推理节点  │
        └──────┬───────┘
               │ route_after_llm(state)  ← 路由函数（开关）
      ┌────────┼──────────┬─────────────┐
      ▼        ▼          ▼             ▼
  [调 tool]  [触发人审]  [完成结束]   [错误恢复]
      │        │          │             │
      ▼        ▼          ▼             ▼
   tool节点  interrupt   END         retry节点
      │
      │ route_after_tool(state)  ← 路由函数（开关）
      ▼
  回 LLM 推理节点（继续循环）/ 或 gate 检查
```

**四个关键路由决策点**：

| 路由函数 | 在哪触发 | 读什么 state | 分支去向 |
|---|---|---|---|
| `route_after_llm` | LLM 推理后 | 有无 tool_call / 是否 final | tool节点 / END / 错误恢复 |
| `route_after_tool` | tool 执行后 | tool 结果 / permission 判定 | 回 LLM / interrupt人审 / END |
| `route_gate` | check_gate 后 | taskGate / goalGate 结果 | 继续循环 / END |
| `route_safety` | 每步前置 | 死循环/迭代计数/state指纹 | 正常 / 强制中止 |

#### 路由函数实现示例

**1. route_after_llm（最核心）**

```python
def route_after_llm(state: AgentState) -> Literal["tools", "human_gate", "end", "error"]:
    """LLM 推理后，决定去哪"""
    last_message = state["messages"][-1]
    
    # 检查是否有 tool call
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_call = last_message.tool_calls[0]
        
        # 检查 permission
        permission = check_permission(tool_call.name, tool_call.args, state["group"])
        if permission == "ask":
            return "human_gate"  # 触发 interrupt
        elif permission == "deny":
            return "error"
        else:
            return "tools"  # allow，去执行 tool
    
    # 没有 tool call，检查是否终止
    if is_final_answer(last_message):
        return "end"
    
    # 其他情况：可能是 LLM 输出格式错误
    return "error"
```

**2. route_after_tool（工具执行后）**

```python
def route_after_tool(state: AgentState) -> Literal["continue", "human_gate", "end"]:
    """tool 执行后，决定去哪"""
    last_tool_result = state["messages"][-1]
    
    # 检查 gate（任务完成条件）
    if state.get("task_gate_triggered"):
        return "end"
    if state.get("goal_gate_triggered"):
        return "end"
    
    # 检查是否需要跨组触发（如 trigger_risk_flow）
    if last_tool_result.name == "trigger_risk_flow":
        # 跨组触发后，本组流程结束
        return "end"
    
    # 默认：继续循环，回到 LLM 推理
    return "continue"
```

**3. route_gate（Gate 检查）**

```python
def route_gate(state: AgentState) -> Literal["continue", "end"]:
    """gate 检查后决定循环还是结束"""
    # TaskGate：所有任务是否完成
    if state.get("pending_tasks") and len(state["pending_tasks"]) == 0:
        return "end"
    
    # GoalGate：目标是否满足（独立模型评估）
    if evaluate_goal(state["goal"], state["current_output"]):
        return "end"
    
    # 迭代上限
    if state["step_count"] >= MAX_ITERATIONS:
        return "end"
    
    return "continue"
```

**4. route_safety（死循环 / 安全检查）**

```python
def route_safety(state: AgentState) -> Literal["continue", "abort"]:
    """每步前置安全检查"""
    # 死循环检测（§3.3）
    if detect_loop(state["recent_tool_calls"]):
        return "abort"
    
    # 状态指纹循环（state hash 重复）
    state_fp = compute_state_fingerprint(state)
    if state_fp in state["seen_fingerprints"]:
        return "abort"
    
    return "continue"
```

#### 跨组路由（特殊情况）

model 组 Agent 调 `trigger_risk_flow` → 触发 risk 组处理，这是跨组路由。

**Day 5 定型：采用方式 2（Blackboard 队列标志）**。曾评估过两种方式，最终选队列标志作为落地机制：

```python
# ✅ 已落地（tools/model/trigger_risk_flow.py）：方式 2 — Blackboard 队列标志
def trigger_risk_flow(blackboard_key: str) -> dict:
    """把 pending risk review 写入 PROJECT scope 队列，供 risk 组消费。"""
    # 1. 读取上游 write_blackboard 写的 model spec（shared.model_entries.<key>）
    # 2. 向 PROJECT scope 的 shared.pending_risk_reviews 追加一条 pending review
    #    （GROUP_APPEND 写策略，带 @dedupe_within 600s 去重）
    # 3. 返回 {risk_queue_key, review_id, review}，本组流程即结束
    ...
```

**实际数据链**（已跑通，`tests/test_model_tools.py` + `tests/test_risk_*.py` 覆盖）：

```
model Agent:
  write_blackboard(key="model.pr_123_spec")
    → 落到 PROJECT scope: shared.model_entries.model.pr_123_spec
  trigger_risk_flow(blackboard_key="model.pr_123_spec")
    → 向 PROJECT scope: shared.pending_risk_reviews 追加 {review_id → {status:pending, blackboard_key, ...}}
    → model 组路由返回 end（本组结束）
risk Agent（独立循环，自己的路由）:
  read_blackboard(blackboard_key="model.pr_123_spec")
    → 从 PROJECT scope 读回 model_spec
  calc_risk → generate_risk_profile → check_gate → (超阈值) HumanGate interrupt → write_pr_comment
```

**为什么选方式 2 而非方式 1（直接同步 invoke risk Agent）**：
- 解耦：model 组不持有 risk Agent 的引用，跨组只通过 Blackboard 契约通信（对齐 Pattern 2 Stateful Blackboard）
- 可观测：队列条目在 Blackboard 留痕，前端可可视化"谁写了什么、谁读了什么"
- 幂等：`@dedupe_within` 保证同一 blackboard_key 600s 内不重复触发
- 方式 1（同步直接 invoke）留作 Week 2 的低延迟优化选项，不是当前口径

**关键点**：跨组触发后，model 组的路由返回 `end`（本组流程结束）；risk 组是独立的 Agent 循环，有自己的路由。当前 Day 5 demo 里 risk 组通过 `run_agent(group="risk", skill_name="risk-gate")` 或 `read_blackboard` 消费队列/spec。

#### 路由与 Checkpoint 的配合

路由决策必须写入 state，因为 checkpoint 恢复时需要知道"下一步应该去哪"：

```python
# 路由决策写入 state
state["next_route"] = route_after_llm(state)

# checkpoint 保存（LangGraph 自动）
# 恢复时，从 state["next_route"] 读取，继续走

# 人审场景：
# 1. route 返回 "human_gate" → 触发 interrupt
# 2. checkpoint 保存当前 state（含 next_route="human_gate"）
# 3. 人审 approve 后 → 修改 state["next_route"] = "continue"
# 4. 从 checkpoint 恢复 → 按新路由继续
```

---

**路由设计总结**：路由是 LangGraph 编排层的"神经中枢"，每个路由函数是一个决策开关。我们自研的路由补充（permission 判断、gate 检查、死循环检测、跨组触发）是相对 `create_react_agent` 默认行为的核心扩展点。

### 3.3 自研运行时加固

#### 3.2.1 死循环检测

**问题**：Agent 陷入同一个 tool 反复调用（如无限 read 同一文件）

**实现**：
```python
class LoopDetector:
    def __init__(self, window=10, threshold=5):
        self.recent_calls = deque(maxlen=window)  # 最近 10 次调用
        
    def check(self, tool_name: str, args: dict) -> bool:
        """返回 True 表示检测到循环"""
        call_sig = (tool_name, frozenset(args.items()))
        self.recent_calls.append(call_sig)
        
        # 统计相同调用出现次数
        count = self.recent_calls.count(call_sig)
        if count >= threshold:  # 10 次里出现 5 次
            return True  # 死循环
        return False

# 使用
detector = LoopDetector()
if detector.check(tool_name, args):
    raise LoopDetectedError(f"{tool_name} called {count} times")
```

#### 3.2.2 迭代上限

**实现**：
```python
MAX_ITERATIONS = 100

for i, chunk in enumerate(agent.stream(...)):
    if i >= MAX_ITERATIONS:
        raise MaxIterationsError(f"Exceeded {MAX_ITERATIONS} steps")
    emit_sse(chunk)
```

#### 3.2.3 状态指纹循环检测

**问题**：Agent 绕圈，状态回到之前的样子

**实现**：
```python
def state_fingerprint(state: dict) -> str:
    """计算状态的哈希，忽略 timestamp 等噪音"""
    relevant = {k: v for k, v in state.items() if k not in ["timestamp", "step"]}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()

seen_states = set()
for chunk in agent.stream(...):
    fp = state_fingerprint(chunk["state"])
    if fp in seen_states:
        raise StateLoopError("State repeated")
    seen_states.add(fp)
```

#### 3.2.4 RLHF 接入点

**目标**：记录 (state, action, reward) 三元组，用于后续 RLHF 训练

**实现**：
```python
class RLHFCollector:
    def __init__(self, output_path=".quantcode/rlhf_data.jsonl"):
        self.file = open(output_path, "a")
        
    def record(self, state: dict, action: dict, reward: float):
        """记录一条训练数据"""
        entry = {
            "timestamp": time.time(),
            "state": state,      # Agent 当前状态（messages, blackboard, memory）
            "action": action,    # Tool call（tool_name + args）
            "reward": reward,    # 奖励信号（人工标注 or 自动评估）
        }
        self.file.write(json.dumps(entry) + "\n")
        self.file.flush()

# 在 ReAct 循环中
collector = RLHFCollector()
for chunk in agent.stream(...):
    if chunk["type"] == "tool_result":
        reward = compute_reward(chunk)  # 用户反馈 or 自动评估
        collector.record(state=chunk["state"], action=chunk["action"], reward=reward)
```

### 3.4 Tool Registry（照抄 OpenCode 设计）

**Tool 定义接口**：
```python
from pydantic import BaseModel
from typing import Callable, Any

class ToolDef(BaseModel):
    id: str                      # 唯一标识，如 "read_pr"
    description: str             # LLM 可见的描述
    schema: type[BaseModel]      # Pydantic schema（参数定义）
    execute: Callable[[Any, dict], Any]  # 执行函数

# 示例 Tool
class ReadPRArgs(BaseModel):
    pr_number: int

def read_pr_execute(args: ReadPRArgs, ctx: dict) -> str:
    """读取 PR diff"""
    # 实现逻辑
    return diff_text

read_pr_tool = ToolDef(
    id="read_pr",
    description="Read the diff of a GitHub PR",
    schema=ReadPRArgs,
    execute=read_pr_execute,
)
```

**Tool Registry**：
```python
class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, ToolDef] = {}
        
    def register(self, tool: ToolDef):
        """注册一个 tool"""
        self.tools[tool.id] = tool
        
    def get_tools_for_group(self, group: str) -> list[ToolDef]:
        """根据组过滤 tools"""
        # 加载该组的 tool 白名单
        allowlist = load_group_config(group)["tool_allowlist"]
        return [t for t in self.tools.values() if t.id in allowlist]

# 全局 registry
registry = ToolRegistry()
registry.register(read_pr_tool)
registry.register(extract_metadata_tool)
# ...
```

**Tool 调用**（LangGraph 自动）：
```python
# LangGraph 会自动把 ToolDef 转换成 LangChain Tool
tools = registry.get_tools_for_group("model")
agent = create_react_agent(model=llm, tools=tools, ...)
```

### 3.5 Permission 规则与 HumanGate

**简化设计**：不需要复杂状态机，Permission 的 `ask` 就是 interrupt。

**Permission 规则**：
```python
class PermissionRule(BaseModel):
    tool: str              # 工具名，如 "write_pr_comment"
    pattern: str           # 资源模式，如 "*"
    action: Literal["allow", "deny", "ask"]

# 示例规则
model_group_permissions = [
    PermissionRule(tool="read_pr", pattern="*", action="allow"),
    PermissionRule(tool="write_blackboard", pattern="PROJECT/*", action="allow"),
    PermissionRule(tool="write_pr_comment", pattern="*", action="ask"),  # 需要人审
]
```

**执行时检查**：
```python
def check_permission(tool_name: str, args: dict, rules: list[PermissionRule]) -> str:
    """返回 allow/deny/ask"""
    for rule in rules:
        if rule.tool == tool_name and fnmatch(args.get("pattern", ""), rule.pattern):
            return rule.action
    return "deny"  # 默认拒绝

# 在 tool 执行前
action = check_permission("write_pr_comment", args, model_group_permissions)
if action == "deny":
    raise PermissionDeniedError()
elif action == "ask":
    # 触发 interrupt（LangGraph 机制）
    emit_sse({"event": "interrupt", "reason": "需要人工审批"})
    wait_for_approval()  # 阻塞，等待 /api/task/{id}/approve
```

### 3.6 Memory 与 Blackboard

**Memory**（Day 2 已完成）：
- SQLite FTS5 + BM25 ranking
- 5-scope：global / projects / groups / sessions / tasks
- GROUP scope 隔离：factor 组读不到 model 组的私有 memory

**Blackboard**（Day 3 新增）：
- PROJECT scope：所有组可读，写入记录 `written_by_group`
- 持久化到 `.quantcode/blackboard.db`
- 用于跨组数据传递（如 model → risk）

**API**：
```python
# Memory
memory.search(query="VaR 计算", scope="projects", scope_id=project_id)
memory.write(scope="groups", scope_id="model", key="last_model_pr", value="...")

# Blackboard
blackboard.write(scope="projects", key="model.pr.123", value=model_spec)
blackboard.read(scope="projects", key="model.pr.123")  # risk 组读
```

---

## 4. 执行平面职责（Python tools/）

每个 tool 是独立的 Python 函数，完全解耦。

### 4.1 Tool 列表（按组）

#### model 组 tools
- `read_pr(pr_number)` → PR diff 文本
- `extract_metadata(diff)` → 模型元数据 dict
- `generate_model_spec(metadata)` → ModelSpec（Pydantic）
- `write_blackboard(key, value)` → 写 PROJECT scope
- `trigger_risk_flow(blackboard_key)` → 调用 risk 组 Agent

#### risk 组 tools
- `read_blackboard(key)` → 读 PROJECT scope
- `calc_risk(returns)` → RiskMetrics（早期可用 stub 实现，接口保持稳定）
- `generate_risk_profile(metrics)` → RiskProfile（Pydantic）
- `check_gate(profile)` → bool（VaR 是否超阈值）
- `write_pr_comment(pr_number, comment)` → 写 GitHub PR 评论（带 dedupe）

#### 共享 tools
- `search_memory(query, scope)` → Memory FTS5 搜索
- `read_file(path)` → 读文件
- `write_file(path, content)` → 写文件
- `bash(command)` → 执行 shell 命令

### 4.2 外部系统集成

- `autoeval_client.py`：调用 AutoFactorEvaluation
- `server_ssh.py`：SSH 读不同组服务器
- `cos_client.py`：COS 存储读写
- `rlhf_collector.py`：收集 RLHF 训练数据

### 4.3 PR Multi-Agent Review 平面

PR 代码审查位于业务执行平面之外。它不启动 Quant Code AgentRunner，也不执行 PR 中的 Python 业务代码。

```text
pull_request_target（workflow 来自默认分支）
  → Server B / Quant Physical Gates
      → secret、生产路径、JSON/YAML、shell、可复现性检查
      → 同一 workflow run 的 physical artifact
  → Server B / Quant Multi-Agent Review
      → Contract Boundary
      → Agent Runtime
      → Factor Pipeline
      → Model and Risk
      → Research Workflow
      → CI and Supply Chain
  → arbiter: pass / warn / block
  → 更新同一条 PR 评论
```

信任边界如下：

- PR source 是不可信输入，只用于读取 diff 和静态文件。
- workflow 定义与 reviewer matrix、gate policy、repo profile 都来自 PR 的 base/default branch。PR head 不能在同一次运行中修改自己的审查控制面。
- 中央 review engine 固定到完整 commit SHA。Server B 预先安装对应 wheel 到 `/opt/quant-review-ci/releases/<sha>/venv`，目录由 root 持有，runner 服务用户只有读和执行权限。
- workflow 不安装 Quant Code，也不创建 Quant Code venv。业务依赖测试属于独立测试 CI，不能塞进 reviewer job。
- physical job 不接触 DeepSeek secret。agent job 只消费同一 GitHub run 产生并校验过的 physical artifact。
- `deepseek-review` Environment 只允许 `main` branch 部署；feature branch 中新增的 workflow 不能读取 DeepSeek secret。
- 使用 `pull_request_target` 获取默认分支中的可信 workflow；PR head 只作为静态数据读取，不导入、不测试、不执行。内部 self-hosted runner 仍拒绝 fork PR。

这套 code review 与 Model → Risk Compose → HumanGate 是两个系统。前者判断代码 diff 是否可合并，后者判断模型业务风险是否需要人工批准。

---

## 5. 从 OpenCode 学到的设计原则

### 5.1 解耦（Decoupling）

| 机制 | 实现 |
|---|---|
| **Tool 解耦** | 统一 `ToolDef` 接口，registry 动态注册，tool 间零依赖 |
| **Mode 解耦** | 6 个组共用一个 ReAct loop，只是换 system prompt + tool 白名单 + permission 规则 |
| **Permission 解耦** | 独立的 allow/deny/ask 规则系统，与 tool 逻辑分离 |
| **State 解耦** | Memory/Blackboard 是外部存储，Agent 通过 tool 读写，不在循环内部 |

### 5.2 自主决策（Autonomous Decision-Making）

| 机制 | 实现 |
|---|---|
| **ReAct 循环** | Agent 自己推理"现在该做什么"，不是执行预设 DAG |
| **Tool 选择** | LLM 根据 tool description 自己选，不是 hardcoded dispatch |
| **终止条件** | Agent 自己判断"任务完成了吗"（goalGate / taskGate），不是步数到了就停 |
| **错误恢复** | Agent 看到 tool 报错后，自己决定重试还是换方案 |

### 5.3 范围边界（明确不做 / 分阶段做）

| OpenCode 有 | 我们的取舍 | 原因 |
|---|---|---|
| TypeScript 编排层 | 不做，用 Python | 教学 + 算法接入需要 Python 生态 |
| 15 个内置 compose skill | 不做，只做 6 套业务 Compose 流 | 聚焦量化投研场景 |
| 复杂的 actor spawn 机制 | 后置，先单 Agent 跑通再引入 subagent | 降低首个里程碑复杂度 |
| Dream/Distill 完整实现 | 后置，先原型 | 依赖前置的 trace 与 Memory 积累 |

---

## 6. 系统能力验收（架构级）

架构层面，系统应当具备以下可验证能力（与具体排期、人员无关）：

- **自主推理**：Agent 能基于 system prompt + tool 集，自主推理并完成一个多步任务，无需预定义流程图
- **跨组数据传递**：一个组的 Agent 写入 Blackboard PROJECT scope，另一个组的 Agent 能读到；GROUP scope 私有数据不可跨组读
- **人审断点**：permission 规则为 `ask` 的 tool 触发时，Agent 暂停并等待外部 approve/reject，恢复后继续
- **运行时安全**：死循环检测、迭代上限、状态指纹循环检测任一触发时，Agent 安全中止而非无限消耗
- **副作用幂等**：对外副作用 tool（PR 评论、邮件）在去重窗口内重复触发只生效一次
- **状态可恢复**：Agent 在任意 tool 执行后崩溃，可从 checkpoint 恢复，不重跑已完成步骤
- **算法数据沉淀**：每次 tool call 的 (state, action, reward) 可被记录，供 RLHF / 评估使用
- **PR 审查可信性**：审查配置来自 base SHA，review engine 固定版本，physical artifact 与同一 workflow run 绑定，blocker 能阻止合并

> 具体的迭代排期、任务拆解、人员分工见独立的任务计划文档（如 `docs/DayN_TaskList.md`），不属于本架构规格。

---

**关键 takeaway**：我们不做"预定义工作流引擎"，我们做"能自主推理的 Agent + 一堆独立 tools"。OpenCode 已经证明这条路可行，我们在 Python 侧复刻并加固它。

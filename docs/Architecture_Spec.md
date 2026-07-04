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

## 3. 编排平面职责（LangGraph 改写的 compose 引擎）

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

### 3.2 自研运行时加固

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

### 3.3 Tool Registry（照抄 OpenCode 设计）

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

### 3.4 Permission 规则与 HumanGate

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

### 3.5 Memory 与 Blackboard

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

> 具体的迭代排期、任务拆解、人员分工见独立的任务计划文档（如 `docs/DayN_TaskList.md`），不属于本架构规格。

---

**关键 takeaway**：我们不做"预定义工作流引擎"，我们做"能自主推理的 Agent + 一堆独立 tools"。OpenCode 已经证明这条路可行，我们在 Python 侧复刻并加固它。

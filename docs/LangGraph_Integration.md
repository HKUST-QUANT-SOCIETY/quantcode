# LangGraph 集成文档（Day 2）

> Day 2 决策：用 LangGraph 作为 Compose 流的执行引擎；
> OpenCode 的 SKILL.md 机制、千组千流路由、MimoCode Memory/Dream/Distill 均保持不变。
>
> 本文档面向所有需要新写 / 修改 Compose 流的组员（肖骥超 / 陈镇鸿 / 杨欣琳 / 刘炽 等）。

## 0. 目录

1. 整体架构与边界
2. 环境与依赖
3. 五分钟极速上手
4. 如何定义一条新的 Compose 流
5. State 设计规范
6. Node 函数签名约定
7. Checkpoint 恢复测试方法
8. Memory 集成（StateGraph 节点中读写 Memory）
9. HumanGate（interrupt_before/after）—— Day 2 stub
10. 已知陷阱与 FAQ

---

## 1. 整体架构与边界

```
Skill 作者 ──► pipeline/*.py (Flow 注册)
                    │
                    ▼
        runner/compose_executor.py
        ┌───────────────────────────────────┐
        │ execute_compose_flow(group, …)    │
        │  ├─ 查 FLOW_REGISTRY              │
        │  ├─ 注入 _memory / 钩子           │
        │  ├─ app.invoke(state, thread_id)  │
        │  └─ 返回 {artifacts, output_data} │
        └───────────────────────────────────┘
                    │
                    ▼
        runner/langgraph_base.py
        ┌───────────────────────────────────┐
        │ create_workflow(nodes, edges)     │
        │ get_checkpointer(db_path)         │
        │ make_thread_id(group, flow_name)  │
        │ BaseFlowState (TypedDict)         │
        └───────────────────────────────────┘
                    │
                    ▼
              LangGraph (StateGraph + SqliteSaver)
              ┌────────────────────────────────┐
              │ SqliteSaver @ .quantcode/      │
              │   └─ checkpoints.db (sha256)   │
              └────────────────────────────────┘
```

**我们用 LangGraph 的部分**：

- StateGraph 做线性流水线（替代手写 Orchestrator-Worker）
- SqliteSaver 做 checkpoint（替代手写 checkpoint.md）
- `interrupt_before/after`（Day 2 stub；Day 3 由 HumanGate 接入）

**不用的部分**：

- OpenCode SKILL.md / tool 注册机制
- 千组千流的 SSH key 路由
- MimoCode Memory / Dream / Distill

---

## 2. 环境与依赖

本仓库的 Python 代码 **必须** 在 conda 环境 `hkust-quant` 中运行（Python 3.12）。

```bash
conda activate hkust-quant      # 或：hkust-quant\Scripts\activate (Windows)
pip install -e .[dev]            # 装本仓库声明的依赖
pip install -U langgraph langgraph-checkpoint-sqlite   # 顶层 dep 但同时支持 CI
```

最低版本：

- langgraph >= 1.2
- langgraph-checkpoint-sqlite >= 3.1
- pydantic >= 2.6
- python >= 3.12

---

## 3. 五分钟极速上手

复制粘贴即可（注意 fill in `your_node`）：

```python
from runner.langgraph_base import (
    BaseFlowState,
    create_workflow,
    default_compose_edges,
    get_checkpointer,
    make_thread_id,
)
from runner.compose_executor import register_flow, execute_compose_flow
from langgraph.graph import END


def step1(state: dict) -> dict:
    return {"output_data": {"echoed": state["input_data"]}, "artifacts": ["step1.txt"]}

def step2(state: dict) -> dict:
    return {"output_data": {"final": state["output_data"]["echoed"]}, "artifacts": ["step2.txt"]}


app = create_workflow(
    nodes={"step1": step1, "step2": step2},
    edges=default_compose_edges(["step1", "step2"]),
).compile(checkpointer=get_checkpointer())
register_flow("factor", "demo", app)
result = execute_compose_flow("factor", "demo", {"hi": "world"})
print(result["artifacts"])
```

预期输出：`['step1.txt', 'step2.txt']`。

---

## 4. 如何定义一条新的 Compose 流

### 4.1 三步建流

1. 在 `flows/<group>_<flow>.py`（Day 4 才会正式建 `flows/`；Day 2 可放 `runner/flows_*.py`）写 4 个 node 函数；
2. 把它们配成一张 StateGraph 并 `compile(checkpointer=get_checkpointer())`；
3. 在该文件末尾调用 `register_flow(group, flow_name, app)`。

### 4.2 必须遵守的命名规范

- **group**：小写六组之一（`fundamental`、`factor`、`model`、`risk`、`strategy`、`options`）；register / execute 时自动 lowercase。
- **flow_name**：保留大小写。建议用 `"<group>:<verb>"` 格式与 SKILL.md 对齐，例如 `"factor:autoeval"`、`"model:pr-submit"`。
- **thread_id**：由 `make_thread_id(group, flow_name)` 生成；测试时可显式 `ts=1700000000` 注入。

### 4.3 注册示例（factor:autoeval 模板）

```python
# flows/factor_autoeval.py
from schemas.factor import FactorSpec, FactorReport   # Pydantic schema 已冻结
from runner.langgraph_base import BaseFlowState, create_workflow, default_compose_edges, get_checkpointer
from runner.compose_executor import register_flow


class FactorFlowState(BaseFlowState):
    """factor 流专用 state；在 BaseFlowState 上叠加业务字段。"""
    input_spec: FactorSpec | None       # 由 validate 节点填
    eval_result: dict | None
    report: FactorReport | None


def validate_factor_spec(state):
    spec = FactorSpec(**state["input_data"])        # Pydantic 校验
    return {"input_spec": spec}

def call_autoeval_api(state):
    spec = state["input_spec"]
    # 真实或 mock（Day 2 demo 用 mock；API 推到 Day 3）
    return {"eval_result": _mock_autoeval_result(spec)}

def generate_factor_report(state):
    result = state["eval_result"]
    report = FactorReport(
        factor_name=state["input_spec"].name,
        evaluation_period=state["input_spec"].date_range,
        universe=state["input_spec"].universe,
        ic_metrics=result["ic_metrics"],
        turnover=result["turnover"],
        decay=result["decay"],
        layered_backtest=result["layered_backtest"],
        verdict=result["verdict"],
    )
    path = f"artifacts/factor/{report.factor_name}-report.json"
    return {"report": report, "artifacts": [path]}

def run_acceptance(state):
    r = state["report"]
    assert r.ic_metrics.ic_mean > 0.02, f"IC too low: {r.ic_metrics.ic_mean}"
    assert r.turnover.monthly < 0.3, f"Turnover too high: {r.turnover.monthly}"
    return {}


app = create_workflow(
    nodes={
        "validate": validate_factor_spec,
        "call_autoeval": call_autoeval_api,
        "generate_report": generate_factor_report,
        "acceptance": run_acceptance,
    },
    edges=default_compose_edges([
        "validate", "call_autoeval", "generate_report", "acceptance",
    ]),
).compile(checkpointer=get_checkpointer())

register_flow("factor", "factor:autoeval", app)
```

调用：

```python
from runner.compose_executor import execute_compose_flow
result = execute_compose_flow(
    "factor", "factor:autoeval",
    FactorSpec(name="pb_roe", ...).model_dump(),
)
print(result["artifacts"])  # ['artifacts/factor/pb_roe-report.json']
```

---

## 5. State 设计规范

### 5.1 BaseFlowState 必备字段

```python
class BaseFlowState(TypedDict, total=False):
    group: str                                            # 路由
    flow_name: str                                        # 流名
    thread_id: str                                        # 由 make_thread_id 生成
    input_data: dict[str, Any]                            # 入口 Pydantic dict 化
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]         # 累加写
    errors: Annotated[list[str], operator.add]            # 累加写
    _memory: Any                                          # compose_executor 注入
```

### 5.2 业务流如何扩展

```python
from runner.langgraph_base import BaseFlowState
from schemas.factor import FactorSpec, FactorReport

class FactorFlowState(BaseFlowState, total=False):
    input_spec: FactorSpec | None
    eval_result: dict | None
    report: FactorReport | None
```

### 5.3 累加型字段规范

- `artifacts` / `errors` 必须用 `Annotated[list, operator.add]`。
- node 函数返回 `{"artifacts": ["x.json"]}` 时，LangGraph 自动 append 而不是覆盖。
- 若 node 想要"替换"语义，请用另一个字段（如 `output_data`）。

### 5.4 State 必须可序列化

LangGraph 用 pickle/JSON 把 state 写到 sqlite。如果你在 state 里塞不可序列化对象（如 db 连接、线程锁），checkpoint 会失败——因此：

- **允许**：dict、list、str、int、float、bool、None、Pydantic model（自动序列化）。
- **不允许**：db 连接、threading.Lock、generator、自定义类（除非实现 `__getstate__/__setstate__`）。
- 内部类以 `_` 前缀的字段（如 `_memory`）在 Day 3 会改为不持久化（暂时持久化 OK）。

---

## 6. Node 函数签名约定

```python
def node_fn(state: BaseFlowState) -> dict[str, Any]:
    """签名约定。"""
    ...
    return {"<要 merge 的字段>": <值>}
```

- **入参**：`state`，类型由 BaseFlowState 或业务子类决定；LangGraph 传 dict 进来，Pyright/Pylance 可用 TypedDict 提示。
- **返回值**：dict，被 LangGraph merge 进 state；返回空 dict `{}` 等于"什么都不改"。
- **副作用**：节点可以写文件 / 发 HTTP / 写 Memory，但异常应该抛上来（LangGraph 默认不保存该步 checkpoint）。

### 6.1 Memory 访问（Day 3+）

节点可通过 `state["_memory"]` 拿到 `MemoryService` 实例：

```python
def some_node(state):
    memory = state.get("_memory")
    if memory is None:
        return {}
    # 写
    memory.write(scope="groups", scope_id="factor", type="progress",
                  key="last_run", body="2026-07-02 ...")
    # 读
    rows = memory.search(query="PB-ROE", scope="groups", scope_id="factor")
    ...
    return {"artifacts": [...]}
```

详见第 8 节。

### 6.2 异常处理约定

```python
def node_with_retry(state):
    spec = state["input_spec"]
    try:
        result = call_api(spec)
    except SomeTransientError as exc:
        return {"errors": [f"transient: {exc!r}"]}   # 不抛，让 runner 决定重试
    except (ValueError, KeyError) as exc:
        raise                                  # 业务错误必须抛 — LangGraph 不入 checkpoint
    return {"data": result}
```

---

## 7. Checkpoint 恢复测试方法

### 7.1 Smoke test

最小 smoke test（已内置在 `runner/hello_world_example.py`）：

```bash
python runner/hello_world_example.py
```

期望：

- 第一次 invoke：artifacts 累积为 `['a.txt', 'b.txt']`；
- 第二次同 thread_id：artifacts 累积为 `['a.txt', 'b.txt', 'a.txt', 'b.txt']`（因 reducer 累加）；
- sqlite 中 `SELECT COUNT(*) FROM checkpoints >= 2`。

### 7.2 跨进程恢复

```python
# 进程 A
from runner.compose_executor import execute_compose_flow
result_a = execute_compose_flow("factor", "factor:autoeval", spec.model_dump())
# 拿到 result_a["thread_id"]

# 手动 kill A，再用同 thread_id 在进程 B 启动
result_b = execute_compose_flow(
    "factor", "factor:autoeval",
    spec.model_dump(),
    thread_id=result_a["thread_id"],
)
# LangGraph 会从 checkpoint 恢复 final state；不需要重跑已完成的 node
```

### 7.3 清空 checkpoint（dev only）

```bash
rm .quantcode/checkpoints.db*
# 或
python -c "from runner import langgraph_base; langgraph_base.clear_checkpointer_cache()"
```

---

## 8. Memory 集成

Day 3+ 由 `runner/memory/service.py` 提供 `MemoryService` 类。
`execute_compose_flow` 会自动注入到 `state["_memory"]`（需在调用方传 `inject_memory` 工厂）。

### 8.1 调用方提供 MemoryService

```python
from runner.memory import MemoryService
from runner.compose_executor import execute_compose_flow

memory = MemoryService(db_path=".quantcode/memory.db", root=".quantcode/")
result = execute_compose_flow(
    group="factor",
    flow_name="factor:autoeval",
    input_data=spec.model_dump(),
    inject_memory=lambda _group: memory,
)
```

### 8.2 节点内读写

```python
def some_node(state):
    memory = state["_memory"]
    memory.write(
        scope="groups", scope_id="factor",
        type="progress", key="last_autoeval",
        body=f"ran on {utc_now()}",
    )
    prior = memory.search(query="autoeval", scope="groups", scope_id="factor", limit=5)
    ...
```

### 8.3 GROUP 隔离

`groups` scope 的 memory 强制 requester 必须是同组，否则抛 `PermissionError`。
详见 `docs/LangGraph_Integration.md` 第 10 节以及 `runner/memory/service.py`。

---

## 9. HumanGate（`interrupt_before/after`） —— Day 2 stub

Day 2 仅留 stub：杨欣琳的 `runner/human_gate.py` 计划 Day 3 完成。
调用方可以现在在 register 时挂上 `interrupt_after=["<node>"]`：

```python
from runner.langgraph_base import create_workflow, get_checkpointer
app = create_workflow(
    nodes={"a": a_node, "b": b_node},
    edges=default_compose_edges(["a", "b"]),
).compile(
    checkpointer=get_checkpointer(),
    interrupt_after=["a"],   # HumanGate stub；Day 3 由杨欣琳实装
)
```

Day 3 后，runner 会通过 `runner.human_gate` 模块决定是否真的中断；本字段在 Day 2 是"摆设"。

---

## 10. 已知陷阱与 FAQ

### Q1. `SqliteSaver.from_conn_string` 在 langgraph 1.x 返回 context manager，不是 saver 直接

不能直接 `saver = SqliteSaver.from_conn_string(path)` 然后传给 `compile`。
**正确做法**（已封装在 `runner.langgraph_base.get_checkpointer`）：

```python
conn = sqlite3.connect(path, check_same_thread=False)
saver = SqliteSaver(conn)
saver.setup()
```

或直接用我们的封装：

```python
from runner.langgraph_base import get_checkpointer
saver = get_checkpointer(".quantcode/checkpoints.db")
```

### Q2. `add_edge(START, node)` 必须在 edges 中

不写 START 边，`compile()` 会报 *"Graph must have an entrypoint"*。
最简方案：用 `default_compose_edges(["node1", "node2", ...])`，它会自动加入 `START → node1`。

### Q3. Windows 上 `unlink(checkpoints.db)` 报 PermissionError

sqlite 在 Windows 上即便 close 也会短暂锁住文件数秒。建议：

- CI/单测用 `:memory:` 或 `tmp_path`；
- 真实跑留在 `.quantcode/`，**不要在跑的过程中 unlink**。

### Q4. `TypedDict, total=False` 与 LangGraph 的兼容性

`BaseFlowState` 用 `total=False` 以便业务子类叠加。子类同样声明 `total=False`。
LangGraph 会把缺失字段当作"未设置"，不会主动验证。

### Q5. checkpoint 文件过大

每个 invoke 会写一行到 `checkpoints` 表。Day 4 加 prune（删 30 天前）。
Day 2/3 不做 prune。

### Q6. 怎么 debug 单个 node？

```python
from runner.langgraph_base import create_workflow, get_checkpointer
wf = create_workflow({"node_a": my_node_a}, [(START, "node_a"), ("node_a", END)])
app = wf.compile(checkpointer=get_checkpointer())
result = app.invoke({"input_data": {...}, "group": "factor", "flow_name": "test"},
                    config={"configurable": {"thread_id": "debug-1"}})
print(result)
```

### Q7. 多个 node 共享变量怎么传？

通过 state。例如：

```python
def step1(state):
    return {"_ctx": {"factor_value": 42}}

def step2(state):
    factor = state["_ctx"]["factor_value"]
    ...
```

注意：`_ctx` 不是内置字段，需要在业务子类（`FactorFlowState`）里也声明。

---

## 11. 相关文件索引

| 文件 | 角色 |
|---|---|
| `runner/langgraph_base.py` | 基类、工厂、checkpointer、thread_id |
| `runner/compose_executor.py` | `execute_compose_flow` / FLOW_REGISTRY |
| `runner/hello_world_example.py` | 可独立运行的最小示例 |
| `runner/memory/` | M4+ 的 Memory（Day 2 同步开发中） |
| `schemas/compose_task.py` | GroupName / BlackboardScope 等枚举 |
| `schemas/factor.py` | FactorSpec / FactorReport 等业务 schema |
| `docs/Day2_TaskList.md` §1.1 | 本模块的任务立项 |

---

Owner: 尹一帆（Day 2）

Co-authored-by: Lead（架构决策）

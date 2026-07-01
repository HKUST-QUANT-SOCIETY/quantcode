# Day 2 任务清单

> **日期**：开发第二日（Day 1后一天）
> **总体目标**：跑通第一条完整的 LangGraph Compose 流（factor:autoeval），证明 StateGraph + Checkpoint + Schema 的闭环可行。
> **核心理念**：先把一条流跑通，证明架构正确，再铺开到其他5条流。
> **技术栈决策**：采用 **LangGraph 混合方案** - 用 StateGraph 做 Compose 流编排，保持 OpenCode SKILL.md 机制不变。

---

## 0. Day 2 架构决策说明

### 为什么引入 LangGraph？

Day 1 我们冻结了 Pattern 1+2+5 的架构。Day 2 我们决定用 **LangGraph 作为 Compose 流的执行引擎**，原因：

| 需求 | 手写实现成本 | LangGraph方案 | 优势 |
|---|---|---|---|
| **Pattern 1 (Orchestrator)** | 手写状态机 + 任务调度 | StateGraph | 图结构天然支持 |
| **Pattern 2 (Blackboard) Checkpoint** | 手写checkpoint.md序列化 | SqliteSaver | 自动持久化，可恢复 |
| **Pattern 5 (HumanGate)** | 手写暂停/恢复逻辑 | `interrupt_before/after` | 内置人审断点 |
| **可观测性** | 手写trace日志 | LangSmith集成 | 开箱即用 |

### 混合方案边界

**用 LangGraph 的部分**：
- StateGraph 做 Compose 流的状态机（替代手写）
- SqliteSaver 做 checkpoint（替代手写 checkpoint.md）
- `interrupt_before/after` 做 HumanGate（替代手写人审逻辑）

**不用 LangGraph 的部分**：
- OpenCode 的 SKILL.md 机制保持不变（agent发现和加载skill）
- 千组千流的路由逻辑保持不变（按SSH key识别组身份）
- MimoCode 的 Memory/Dream/Distill 保持不变（已有设计）

**集成点**：
- 每个 SKILL.md 的实现 = LangGraph 的一个 node 函数
- Compose Mode 触发时 = 实例化对应组的 StateGraph
- Runner 调用 = `app.invoke(input, config={"thread_id": ...})`

---

## 1. Day 2 上午：LangGraph 基础设施

**主持**：Lead + 尹一帆

### 全员 standup（15 分钟）

- Day 1 完成情况回顾（8 套 schema 是否全部冻结？）
- Day 2 目标确认：factor:autoeval 跑通
- LangGraph 技术栈快速对齐（5 分钟）

### 1.1 尹一帆 · LangGraph 基础模板（上午 4 小时）

> **新人背景**：尹一帆（HKU MPhil），Agent 系统和多智能体编排专家，Funcent 实习经验（Agent 自动审计闭环、Schema 合约、动态工作流编排）。Day 2 主攻 LangGraph 基础设施。

| 任务 | 说明 | 验收 |
|---|---|---|
| 安装 LangGraph 环境 | `pip install -U langgraph langgraph-checkpoint-sqlite` | 能 `import langgraph` |
| 写 `runner/langgraph_base.py` | StateGraph 基类模板，包含：<br>- `BaseFlowState` (TypedDict)<br>- `create_workflow()` 工厂函数<br>- thread_id 生成规则（`<group>-<flow>-<timestamp>`）<br>- SqliteSaver 封装（`.quantcode/checkpoints.db`） | 能加载一个空的 StateGraph 并执行到 END |
| 写 `runner/compose_executor.py` | Compose Mode 的执行器，包含：<br>- 从 SKILL.md 路径实例化 StateGraph<br>- 注入 GROUP scope 到 state<br>- 处理 interrupt 信号<br>- 返回 artifact 路径 | 能被其他组员调用：`execute_compose_flow(group, flow_name, input_data)` |
| 写 hello-world 示例 | 最简单的 2-node StateGraph（node1 → node2 → END），跑通并验证 checkpoint 可恢复 | `python runner/hello_world_example.py` 能跑通 |
| 写开发文档 | `docs/LangGraph_Integration.md`：<br>- 如何定义一个新的 Compose 流<br>- State 设计规范<br>- Node 函数签名<br>- Checkpoint 恢复测试方法 | 其他组员看完能写自己的 flow |

**关键代码框架**：

```python
# runner/langgraph_base.py

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict, Annotated
import operator

class BaseFlowState(TypedDict):
    """所有 Compose 流的基础 state"""
    group: str  # fundamental / factor / model / risk / strategy / options
    flow_name: str  # 例如 "factor:autoeval"
    input_data: dict  # 输入的 Pydantic schema 序列化
    output_data: dict | None  # 输出的 Pydantic schema 序列化
    artifacts: Annotated[list[str], operator.add]  # 产出的文件路径（累加）
    errors: Annotated[list[str], operator.add]  # 错误信息（累加）

def create_workflow(flow_config: dict) -> StateGraph:
    """
    根据配置创建 StateGraph
    
    flow_config = {
        "nodes": {"validate": validate_fn, "execute": execute_fn},
        "edges": [("validate", "execute"), ("execute", END)]
    }
    """
    workflow = StateGraph(BaseFlowState)
    for name, func in flow_config["nodes"].items():
        workflow.add_node(name, func)
    for source, target in flow_config["edges"]:
        workflow.add_edge(source, target)
    return workflow

def get_checkpointer():
    """返回 SqliteSaver 实例"""
    return SqliteSaver.from_conn_string(".quantcode/checkpoints.db")
```

### 1.2 Lead · Blackboard SQLite 基础（上午 3 小时）

| 任务 | 说明 | 验收 |
|---|---|---|
| 创建 `runner/blackboard.py` | 5 层 scope 的表结构：<br>```sql<br>CREATE TABLE blackboard (<br>  scope TEXT NOT NULL,  -- GLOBAL/PROJECT/GROUP/SESSION/TASK<br>  group_name TEXT,<br>  key TEXT NOT NULL,<br>  value TEXT NOT NULL,<br>  created_at INTEGER,<br>  PRIMARY KEY (scope, group_name, key)<br>);<br>CREATE VIRTUAL TABLE blackboard_fts USING fts5(key, value, content=blackboard);<br>```| 表创建成功 |
| 实现读写接口 | `write(scope, group, key, value)` - 写入<br>`read(scope, group, key)` - 读取 + 权限检查<br>`search(query, group)` - FTS5 全文搜索 | 单元测试通过 |
| 实现 GROUP 隔离规则 | - GROUP scope：只有 owner group 可读写<br>- PROJECT scope：所有组可读，写入需标记 `shared.*` 前缀<br>- SESSION/TASK scope：只有 owner 可读写<br>- GLOBAL scope：所有组可读，只有 Lead 可写 | 测试：factor 组读不到 model 组的 GROUP 数据 |
| 写单元测试 | `tests/test_blackboard.py` - 覆盖所有 scope 的读写和权限 | `pytest tests/test_blackboard.py -v` 全部通过 |

**关键代码框架**：

```python
# runner/blackboard.py

import sqlite3
from enum import StrEnum

class Scope(StrEnum):
    GLOBAL = "GLOBAL"
    PROJECT = "PROJECT"
    GROUP = "GROUP"
    SESSION = "SESSION"
    TASK = "TASK"

class Blackboard:
    def __init__(self, db_path: str = ".quantcode/blackboard.db"):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
    
    def write(self, scope: Scope, group: str, key: str, value: str):
        """写入，自动检查权限"""
        if scope == Scope.PROJECT and not key.startswith("shared."):
            raise PermissionError("PROJECT scope keys must start with 'shared.'")
        # ...
    
    def read(self, scope: Scope, group: str, key: str, requester_group: str) -> str | None:
        """读取，自动检查权限"""
        if scope == Scope.GROUP and group != requester_group:
            raise PermissionError(f"{requester_group} cannot read {group}'s GROUP data")
        # ...
```

### 1.3 肖骥超 · 开始设计 FactorFlowState（上午 1 小时）

| 任务 | 说明 | 验收 |
|---|---|---|
| 定义 `FactorFlowState` | 继承 `BaseFlowState`，添加业务字段：<br>- `input_spec: FactorSpec \| None`<br>- `eval_result: dict \| None`（AutoEval 原始返回）<br>- `report: FactorReport \| None` | 类型定义完成 |
| 草稿 4 个 node 函数签名 | `validate_factor_spec(state) -> dict`<br>`call_autoeval_api(state) -> dict`<br>`generate_factor_report(state) -> dict`<br>`run_acceptance(state) -> dict` | 函数签名完成，实现留到下午 |

### 1.4 其他组员 · 准备工作（上午）

| 组员 | 任务 | 验收 |
|---|---|---|
| 陈镇鸿 | 阅读 LangGraph 文档（https://docs.langchain.com/langgraph/），学习 StateGraph 用法；验证 `@dedupe_within` 在 LangGraph node 中的兼容性 | 能说出 StateGraph 的 3 个核心概念（node/edge/state） |
| 杨欣琳 | 把 Day 1 的 `schemas/human-gate.schema.json` 转为 Pydantic schema；起草 `runner/human_gate.py` 的接口 | `HumanGate` Pydantic 类定义完成 |
| 刘炽 | 优化 Day 1 的 Typst 模板：补充图表、脚注、引用格式 | `typst compile templates/typst/research-report.typ` 产出更完整的 PDF |

---

## 2. Day 2 下午：factor:autoeval 实现

### 2.1 肖骥超 · factor:autoeval 完整实现（下午 4 小时）

> **目标**：把 Day 1 的 `factor:autoeval` SKILL.md 实现为 LangGraph StateGraph

| 任务 | 说明 | 验收 |
|---|---|---|
| 创建 `flows/factor_autoeval.py` | 实现 4 个 node 函数：<br><br>**1. validate_factor_spec**<br>```python<br>def validate_factor_spec(state: FactorFlowState) -> dict:<br>    spec = FactorSpec(**state["input_data"])<br>    # 校验：operators 不重复、date_range 合法<br>    return {"input_spec": spec}<br>```<br><br>**2. call_autoeval_api**<br>```python<br>def call_autoeval_api(state: FactorFlowState) -> dict:<br>    spec = state["input_spec"]<br>    try:<br>        result = autoeval_client.submit(spec)<br>    except Exception:<br>        # 如果 AutoEval 调不通，用 mock<br>        result = _mock_autoeval_result(spec)<br>    return {"eval_result": result}<br>```<br><br>**3. generate_factor_report**<br>```python<br>def generate_factor_report(state: FactorFlowState) -> dict:<br>    eval_result = state["eval_result"]<br>    report = FactorReport(<br>        factor_name=state["input_spec"].name,<br>        ic=eval_result["ic_mean"],<br>        ir=eval_result["ir"],<br>        # ...<br>    )<br>    artifact_path = f"artifacts/factor/{report.factor_name}-report.json"<br>    write_json(artifact_path, report.model_dump())<br>    return {"report": report, "artifacts": [artifact_path]}<br>```<br><br>**4. run_acceptance**<br>```python<br>def run_acceptance(state: FactorFlowState) -> dict:<br>    report = state["report"]<br>    assert report.ic > 0.02, f"IC too low: {report.ic}"<br>    assert report.turnover < 0.3, f"Turnover too high: {report.turnover}"<br>    return {}<br>``` | 4 个函数实现完成 |
| 构建 workflow | ```python<br>from runner.langgraph_base import create_workflow, BaseFlowState<br><br>flow_config = {<br>    "nodes": {<br>        "validate": validate_factor_spec,<br>        "call_autoeval": call_autoeval_api,<br>        "generate_report": generate_factor_report,<br>        "acceptance": run_acceptance,<br>    },<br>    "edges": [<br>        ("validate", "call_autoeval"),<br>        ("call_autoeval", "generate_report"),<br>        ("generate_report", "acceptance"),<br>        ("acceptance", END),<br>    ],<br>}<br><br>factor_autoeval_workflow = create_workflow(flow_config)<br>app = factor_autoeval_workflow.compile(checkpointer=get_checkpointer())<br>``` | workflow 编译成功 |
| 端到端测试 | 用 Day 1 的 `sample_factor.py`（PB-ROE 因子）跑通：<br>```python<br>thread_id = "factor-autoeval-001"<br>result = app.invoke(<br>    {<br>        "group": "factor",<br>        "flow_name": "factor:autoeval",<br>        "input_data": sample_factor_spec.model_dump(),<br>    },<br>    config={"configurable": {"thread_id": thread_id}},<br>)<br>print(result["artifacts"])  # ['artifacts/factor/pb-roe-report.json']<br>``` | `artifacts/factor/pb-roe-report.json` 产出且通过 schema validation |

**mock AutoEval 函数**（如果真实 API 调不通）：

```python
def _mock_autoeval_result(spec: FactorSpec) -> dict:
    """
    Mock AutoEval 返回，用于 Day 2 演示
    """
    return {
        "ic_mean": 0.045,
        "ir": 0.8,
        "turnover": 0.25,
        "decay_half_life": 5.2,
        "layered_backtest": {
            "quintile_1_return": 0.12,
            "quintile_5_return": -0.03,
        },
    }
```

### 2.2 尹一帆 · compose_executor 集成（下午 2 小时）

| 任务 | 说明 | 验收 |
|---|---|---|
| 实现 `execute_compose_flow()` | 供其他组员调用的统一接口：<br>```python<br>from runner.compose_executor import execute_compose_flow<br><br>result = execute_compose_flow(<br>    group="factor",<br>    flow_name="factor:autoeval",<br>    input_data={"name": "pb_roe", ...},<br>)<br># 返回: {"artifacts": [...], "output_data": {...}}<br>``` | 肖骥超能用这个接口跑通 factor:autoeval |
| 集成 Blackboard | 在 StateGraph 的 state 中注入 `blackboard` 实例，每个 node 可以：<br>```python<br>def some_node(state):<br>    blackboard = state["_blackboard"]<br>    blackboard.write(Scope.GROUP, "factor", "last_run", "2026-07-02")<br>``` | 能在 node 中读写 Blackboard |

### 2.3 陈镇鸿 · dedupe 装饰器兼容性测试（下午 2 小时）

| 任务 | 说明 | 验收 |
|---|---|---|
| 在 LangGraph node 中使用 `@dedupe_within` | 验证 Day 1 的 dedupe 装饰器在 StateGraph node 中能正常工作：<br>```python<br>@dedupe_within(seconds=300, key=lambda state: state["input_spec"].name)<br>def call_autoeval_api(state):<br>    # ...<br>``` | 重复调用同一因子，第二次直接返回缓存结果 |
| 验证异常场景 | 如果 node 抛异常，checkpoint 不应保存到该 step | 写单元测试：中断 → 恢复 → 从失败前的 step 重新开始 |

### 2.4 杨欣琳 · HumanGate Pydantic schema（下午 2 小时）

| 任务 | 说明 | 验收 |
|---|---|---|
| 转换 `schemas/human-gate.schema.json` 为 Pydantic | 创建 `schemas/human_gate.py`：<br>```python<br>class HumanGate(BaseModel):<br>    trigger_condition: str  # e.g., "var_99 > 0.05"<br>    notify_channel: str  # e.g., "slack", "email", "log"<br>    timeout_seconds: int = 3600<br>    # ...<br>``` | Pydantic 类通过验证 |
| 实现 `runner/human_gate.py` | ```python<br>def should_interrupt(state: dict, gate_config: HumanGate) -> bool:<br>    """检查是否需要触发 HumanGate"""<br>    # 简单实现：eval trigger_condition<br>    return eval(gate_config.trigger_condition, {"state": state})<br>``` | 能根据 HumanGate 配置决定是否 interrupt |

### 2.5 Lead · 协调 + checkpoint 恢复测试（下午 2 小时）

| 任务 | 说明 | 验收 |
|---|---|---|
| 全局协调 | 解决各 Track 的阻塞点；确保下午 5 点前 factor:autoeval 能跑通 | 无阻塞遗留 |
| 写 checkpoint 恢复测试 | ```python<br># 启动 factor:autoeval<br>app.invoke(..., config={"thread_id": "test-001"})<br><br># 手动 kill 进程（模拟中断）<br><br># 重新启动，从 checkpoint 恢复<br>app.invoke(..., config={"thread_id": "test-001"})<br># 应该从中断点继续，不重新执行已完成的 node<br>``` | checkpoint 恢复成功，日志显示"resumed from node X" |

---

## 3. Day 2 收工前：晚间 standup（30 分钟）

**主持**：Lead

### 议程

1. **factor:autoeval 演示**（10 分钟）：
   - 肖骥超现场跑一遍 factor:autoeval
   - 展示 checkpoint 恢复（中断 → 恢复）
   - 展示 artifact 产出（factor-report.json）

2. **各 Track 进展**（每人 2 分钟）：
   - 完成了什么、遇到了什么问题
   - 明天的优先级

3. **Day 3 任务预览**（5 分钟）：
   - 跨组流程：model:pr-submit → risk-gate
   - HumanGate 触发验证

4. **决策记录**（Lead 当场更新 `docs/QuantCode_Design.md` §11）

### Day 2 整体验收清单

- [ ] factor:autoeval 完整跑通，产出 valid `factor-report.json`
- [ ] checkpoint 机制验证：kill 进程 → resume → 从中断点继续
- [ ] Blackboard GROUP 隔离验证（factor 组读不到 model 组的 GROUP 数据）
- [ ] 第一份 LangGraph trace（本地 log 或 LangSmith）
- [ ] `runner/langgraph_base.py` 和 `runner/compose_executor.py` 完成，其他组员 Day 3 可直接使用
- [ ] `docs/LangGraph_Integration.md` 文档完成

---

## 4. 风险与依赖

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| **LangGraph 学习成本高，上午卡住** | 中 | 高 | 尹一帆上午必须出基础模板，其他人下午才开始写 flow；Lead 提供 1 小时 LangGraph 快速培训 |
| **AutoEval API 调不通** | 高 | 中 | 用 mock 数据，Demo 不影响；真实接入推到 Day 3 |
| **Blackboard SQLite 并发写入冲突** | 低 | 中 | Day 2 只有 1 条流，不会并发；Day 4 再专门测试 |
| **checkpoint 恢复失败（序列化问题）** | 中 | 高 | 尹一帆提前写 hello-world 示例验证；如果失败，简化 state 结构 |

---

## 5. Day 2 不做什么

明确**今天不碰**的事情，避免范围蔓延：

- ❌ 跨组流程（移到 Day 3）
- ❌ 并发测试（移到 Day 4）
- ❌ 前端 Compose 视图（移到 Week 2）
- ❌ LangSmith 集成（可选，有时间再做）
- ❌ Dream / Distill（移到 Day 4）
- ❌ 其他 5 条 Compose 流（Day 3-4 再做）
- ❌ Chroma 向量化（移到 Day 4，今天用不到）

---

## 6. 沟通约定

- **同步**：早 15 分钟 standup + 晚 30 分钟收工 standup
- **异步**：所有问题先发 GitHub Issue 或 PR comment，**不在微信群里讨论代码**
- **阻塞**：超过 2 小时卡住 → 立即在 standup 频道 @Lead
- **代码 review**：所有改动走 PR，至少 1 人 review
- **不直接 push main**：所有改动走 PR

---

## 7. 参考资料

- LangGraph 官方文档：https://docs.langchain.com/langgraph/
- LangGraph GitHub：https://github.com/langchain-ai/langgraph
- Day 0 调研笔记：`docs/langgraph_study_notes.html`（刘炽整理）
- QuantCode 设计文档：`docs/QuantCode_Design.md` §3.2（Pattern 1+2+5）

---

**文档维护**：Day 2 结束后，Lead 把"实际完成"和"延期项"更新到这份文档末尾，作为 Day 3 任务输入。

```
## 8. Day 2 实际完成情况（Day 2 结束时由 Lead 填写）

- 实际完成：
- 延期到 Day 3：
- 新发现的问题：
- 决策记录：
```

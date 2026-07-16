# QuantCode 模块架构文档

> **目的**：完整梳理QuantCode各模块的功能和职责
> **受众**：开发者、代码审查者、新成员onboarding
> **最后更新**：2026-07-15（Lead）

---

## 📚 目录结构

```
quantcode/
├── runner/              # Agent引擎核心
├── tools/               # 6组工具库
├── flows/               # 线性业务流程
├── schemas/             # Pydantic数据模型
├── dream/               # Dream/Distill模块
├── quantcode/           # MCP Server入口
├── tests/               # 测试套件
└── docs/                # 文档
```

---

## 1. Runner模块（Agent引擎核心）

### 📁 `runner/agent_engine.py`
**功能**：AgentRunner主引擎，实现ReAct推理循环

**核心类**：
- `AgentRunner`: Agent执行引擎
  - `run(task, skill_name, thread_id)`: 运行Agent任务
  - `resume(thread_id, decision)`: 恢复暂停的任务
  - 支持checkpoint恢复、HumanGate暂停、死循环检测

**关键特性**：
- 真ReAct循环：LLM自主决策调用工具
- 最大迭代保护：默认10次，防止死循环
- execution_trace回流：10种事件类型供IDE消费
- checkpoint持久化：SQLite存储，支持跨会话恢复

**典型用法**：
```python
from runner.agent_engine import AgentRunner
from runner.llm_provider import create_deepseek_llm

runner = AgentRunner(
    group='factor',
    model=create_deepseek_llm(),
    max_iterations=10,
)

result = runner.run(
    task='生成PB-ROE因子',
    skill_name='factor',
    thread_id='factor-001',
)
```

---

### 📁 `runner/agent_mcp_tool.py`
**功能**：MCP工具入口，暴露`run_agent`给IDE

**核心函数**：
- `run_agent(group, task, skill_name, thread_id, decision)`: 统一入口
  - 两阶段：start（新任务）/ resume（恢复暂停任务）
  - 返回execution_trace供IDE消费

**关键特性**：
- 参数校验：group必须在6组之一
- 状态机：pending_human → approved/rejected
- JSONL流式输出：每个事件一行

**IDE调用示例**：
```typescript
// 启动新任务
const result = await mcp.callTool('run_agent', {
  group: 'factor',
  task: '生成PB-ROE因子',
  skill_name: 'factor',
  thread_id: 'factor-001',
})

// 恢复暂停任务
await mcp.callTool('run_agent', {
  group: 'risk',
  thread_id: 'risk-gate-001',
  decision: 'approve',
})
```

---

### 📁 `runner/llm_provider.py`
**功能**：LLM适配器，封装DeepSeek API

**核心函数**：
- `create_deepseek_llm()`: 创建LLM实例
  - 从`config.json`或环境变量读取配置
  - 返回签名：`(messages, tools) -> AIMessage`

**配置优先级**：
1. 显式参数（api_key/model/base_url）
2. config.json
3. 环境变量（DEEPSEEK_API_KEY）
4. 默认值

**config.json示例**：
```json
{
  "llm": {
    "provider": "deepseek",
    "api_key": "sk-...",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "temperature": 0.0,
    "max_tokens": 4096
  }
}
```

---

### 📁 `runner/routing/router.py`
**功能**：决策路由，判断是否触发HumanGate

**核心函数**：
- `route_next_step(state) -> dict`: 路由决策
  - 检查risk_metrics是否超阈值
  - 返回`requires_human=True`时触发interrupt

**阈值配置**：
- `max_leverage > 3.0`: 高杠杆
- `max_drawdown > 0.2`: 最大回撤超20%
- `var_95 > 0.1`: VaR 95超10%

**典型流程**：
```python
state = {
    'risk_metrics': {'max_leverage': 5.0},
    'risk_profile': {},
}

decision = route_next_step(state)
# {'requires_human': True, 'reason': 'high leverage'}
```

---

### 📁 `runner/acceptance.py`
**功能**：程序化验收，检查artifact是否通过标准

**核心函数**：
- `run_acceptance(artifact_path, criteria) -> AcceptanceResult`
  - 读取artifact（JSON）
  - 检查每个criteria
  - 返回pass/fail + 详细checks

**验收标准示例**：
```python
criteria = {
    'ic_mean': {'min': 0.03, 'max': 1.0},
    'ir': {'min': 0.5},
    'turnover_monthly': {'max': 0.8},
    't_stat': {'min': 2.0},
}
```

---

### 📁 `runner/jerry_demos.py`
**功能**：Day 5 demo场景，供测试和演示

**核心函数**：
- `run_strategy_demo()`: 策略组合demo
- `run_fundamental_demo()`: 基本面分析demo
- `run_options_demo()`: 期权定价demo
- `run_all_demos()`: 运行全部demo

**用途**：
- 单元测试：`tests/test_day5_jerry_demos.py`
- 手动测试：`python -m runner.jerry_demos`
- Investor demo准备

---

## 2. Tools模块（6组工具库）

### 📁 `tools/registry.py`
**功能**：全局工具注册表

**核心类**：
- `ToolDef`: 工具定义（id/description/schema/execute）
- `ToolRegistry`: 单例注册表
  - `register(tool)`: 注册工具
  - `get(tool_id)`: 获取工具
  - `call(tool_id, args_dict, ctx)`: 调用工具
  - `list()`: 列出所有工具ID

**工具生命周期**：
```python
# 1. 定义工具
tool = ToolDef(
    id='my_tool',
    description='做什么',
    schema=MyArgs,
    execute=my_execute_fn,
)

# 2. 注册
register_tool(tool)

# 3. 调用
result = registry.call('my_tool', {'arg': 'value'}, {})
```

---

### 📁 `tools/factor/` — Factor组工具

#### `match_main.py` / `match_main_stub.py`
**功能**：分析因子idea，判断是否兼容主线

**输入**：
- `idea`: 因子想法描述
- `extra_context`: 可选上下文

**输出**：
```json
{
  "compatible": true,
  "suggested_fields": ["pb", "roe"],
  "notes": "LLM分析说明"
}
```

**真实实现**：用LLM推断需要的数据字段
**降级**：API不可用时返回空字段列表

---

#### `gen_schema.py` / `gen_schema_stub.py`
**功能**：根据idea和match结果生成FactorSpec

**输入**：
- `idea`: 因子想法
- `match_result`: match_main的完整输出

**输出**：
```json
{
  "name": "pb_roe_quarterly",
  "formula": "pb * roe",
  "fields": ["pb", "roe"],
  "rebalance": "quarterly",
  "universe": "csi300",
  "date_range": {"start": "2020-01-01", "end": "2023-12-31"}
}
```

**真实实现**：用LLM动态生成完整FactorSpec
**降级**：用规则生成基础spec

---

#### `autoeval.py` / `autoeval_stub.py`
**功能**：提交FactorSpec到AutoEval服务

**输入**：
- `spec`: FactorSpec dict

**输出**：
```json
{
  "ic_mean": 0.045,
  "ic_std": 0.05625,
  "ir": 0.8,
  "t_stat": 2.5,
  "turnover_monthly": 0.25,
  "eval_run_id": "pb_roe_quarterly-eval"
}
```

**真实实现**：HTTP POST到AutoEval API
**降级**：返回mock数据

**环境变量**：
- `AUTOEVAL_API_URL`: API地址
- `AUTOEVAL_API_KEY`: 认证密钥

---

#### `_register.py`
**功能**：注册factor组的3个工具

**环境变量控制**：
- `QUANTCODE_FACTOR_USE_REAL_LLM=1`: 使用真实实现
- 默认：使用stub

```python
import tools.factor._register  # 触发注册
```

---

### 📁 `tools/risk/` — Risk组工具

#### `calc_risk.py`
**功能**：计算风险指标

**输入**：
- `model_spec`: 模型规格
- `backtest_result`: 回测结果（可选）

**输出**：
```json
{
  "max_leverage": 3.5,
  "max_drawdown": 0.15,
  "var_95": 0.08,
  "sharpe": 1.5
}
```

---

#### `check_gate.py`
**功能**：判断是否需要人工审批

**输入**：
- `risk_metrics`: calc_risk的输出

**输出**：
```json
{
  "requires_human": true,
  "reason": "high leverage (5.0 > 3.0)",
  "gate_type": "risk_gate"
}
```

---

#### `write_pr_comment.py`
**功能**：写GitHub PR评论

**输入**：
- `pr_number`: PR编号
- `comment`: 评论内容
- `repo`: 仓库（默认HKUST-QUANT-SOCIETY/quantcode）

**输出**：
```json
{
  "comment_url": "https://github.com/.../issues/29#issuecomment-123",
  "status": "success"
}
```

**环境变量**：`GITHUB_TOKEN`

---

### 📁 `tools/model/` — Model组工具

#### `read_pr.py`
**功能**：读取GitHub PR内容

**输入**：
- `pr_number`: PR编号

**输出**：
```json
{
  "title": "feat: add new model",
  "body": "...",
  "files": [{"filename": "model.py", "patch": "..."}],
  "author": "username"
}
```

---

#### `extract_metadata.py`
**功能**：从PR中提取模型元数据

**输入**：
- `pr_data`: read_pr的输出

**输出**：
```json
{
  "model_name": "momentum_arb",
  "max_leverage": 3.0,
  "instruments": ["futures", "stocks"],
  "strategy_type": "momentum"
}
```

---

#### `trigger_risk_flow.py`
**功能**：触发risk组评估

**输入**：
- `model_spec`: 模型规格

**输出**：
```json
{
  "status": "triggered",
  "risk_thread_id": "risk-gate-001",
  "blackboard_key": "shared.pending_risk_reviews"
}
```

**机制**：写Blackboard队列标志

---

### 📁 `tools/strategy/` — Strategy组工具

#### `select_signals.py`
**功能**：从因子池选择信号

#### `combine_signals.py`
**功能**：组合多个信号

#### `run_strategy_backtest.py`
**功能**：运行策略回测

---

### 📁 `tools/fundamental/` — Fundamental组工具

#### `pit_rag_search.py`
**功能**：Point-in-Time RAG搜索

#### `dcf_valuation.py`
**功能**：DCF估值

---

### 📁 `tools/options/` — Options组工具

#### `build_vol_surface.py`
**功能**：构建波动率曲面

#### `calc_greeks.py`
**功能**：计算期权Greeks

---

## 3. Flows模块（线性业务流程）

### 📁 `flows/factor_autoeval.py`
**功能**：factor:autoeval线性流程（降级路径）

**核心函数**：
- `call_autoeval_api(state)`: 调用AutoEval API
- `build_report(state)`: 构建FactorReport
- `run_acceptance_node(state)`: 程序化验收

**StateGraph节点**：
```
validate_input → call_autoeval_api → build_report → run_acceptance → END
```

**何时使用**：
- Day 4以前：线性flow是主路径
- Day 5以后：AgentRunner是主路径，flow作为降级

---

### 📁 `flows/risk_gate.py`
**功能**：risk:gate线性流程

**节点**：
```
calc_risk → check_gate → [requires_human?]
                          ├─ Yes → human_review → write_comment
                          └─ No → write_comment → END
```

---

## 4. Schemas模块（数据模型）

### 📁 `schemas/factor.py`
**核心模型**：
- `FactorSpec`: 因子规格
- `FactorReport`: 因子评估报告
- `ICMetrics`: IC指标
- `TurnoverMetrics`: 换手率指标
- `FactorVerdict`: pass / fail / marginal

---

### 📁 `schemas/model.py`
**核心模型**：
- `ModelSpec`: 模型规格
- `ModelReport`: 模型评估报告

---

### 📁 `schemas/risk.py`
**核心模型**：
- `RiskMetrics`: 风险指标
- `RiskGateDecision`: 人审决策

---

### 📁 `schemas/strategy.py`
**核心模型**：
- `StrategySpec`: 策略规格
- `StrategyReport`: 策略回测报告

---

### 📁 `schemas/blackboard.py`
**核心模型**：
- `BlackboardEntry`: Blackboard条目
- `BlackboardScope`: session / thread / project

**关键字段**：
- `key`: 命名空间key（如`shared.pending_risk_reviews`）
- `value`: JSON值
- `scope`: 作用域
- `thread_id`: 关联线程

---

## 5. Dream/Distill模块

### 📁 `dream/dream_prototype.py`
**功能**：从RLHF trace提取pattern写入memory

**核心函数**：
- `scan_rlhf_traces()`: 扫描rlhf_data.jsonl
- `extract_patterns(traces)`: LLM提取pattern
- `write_memory(pattern)`: 写入.claude/memory/

**Memory格式**：
```markdown
---
name: factor-quarterly-rebalance-pattern
description: Factor组季度再平衡的标准流程
metadata:
  type: project
---

Factor组在生成季度再平衡因子时，标准流程是...

**Why**: 季度再平衡符合大部分基本面因子的更新频率

**How to apply**: 在gen_schema时默认设置rebalance='quarterly'
```

---

### 📁 `dream/distill_prototype.py`
**功能**：识别重复pattern，候选SKILL.md草案

**核心函数**：
- `find_repetitive_patterns(traces)`: 识别重复工作流
- `generate_skill_draft(pattern)`: 生成SKILL.md草案

**输出**：`.quantcode/distill/skill-drafts/*.md`

---

## 6. QuantCode MCP Server

### 📁 `quantcode/mcp_server.py`
**功能**：MCP Server入口，暴露工具给IDE

**核心函数**：
- `list_tools()`: 列出当前组的工具
- `call_tool(name, arguments)`: 调用工具
- `main()`: stdio模式运行

**环境变量**：
- `QUANTCODE_GROUP`: 当前组（risk/model/factor/strategy/fundamental/options）

**启动方式**：
```bash
QUANTCODE_GROUP=factor python -m quantcode.mcp_server
```

**IDE配置**（opencode.jsonc）：
```json
{
  "mcp": {
    "quantcode-factor": {
      "type": "local",
      "command": ["python", "-m", "quantcode.mcp_server"],
      "environment": {
        "QUANTCODE_GROUP": "factor",
        "PYTHONPATH": "/path/to/QUANTcode"
      }
    }
  }
}
```

---

## 7. Tests模块

### 📁 `tests/test_*_agent_flow.py`
**功能**：端到端Agent测试

**测试内容**：
- Factor组：match_main → gen_schema → autoeval（≥3步ReAct）
- Risk组：calc_risk → check_gate → interrupt暂停 → approve恢复
- Model组：read_pr → extract_metadata → trigger_risk_flow

---

### 📁 `tests/test_*_tools.py`
**功能**：工具注册和基本调用测试

**测试内容**：
- 工具是否注册
- Schema校验
- 基本执行不报错

---

### 📁 `tests/test_routing.py`
**功能**：路由决策测试

**测试内容**：
- 高风险触发HumanGate
- 低风险直接通过
- 边界条件

---

### 📁 `tests/test_agent_engine_basic.py`
**功能**：AgentRunner基础功能测试

**测试内容**：
- ReAct循环正常推理
- HumanGate正确interrupt
- Checkpoint恢复
- 死循环检测

---

## 8. 模块依赖关系

```
┌─────────────────────────────────────────────┐
│           IDE (OpenCode Desktop)            │
│                                             │
│  ┌────────────┐  ┌────────────┐            │
│  │ Chat UI    │  │QuantCode   │            │
│  │            │  │ Side Panel │            │
│  └──────┬─────┘  └──────┬─────┘            │
│         │                │                  │
└─────────┼────────────────┼──────────────────┘
          │ MCP Protocol   │
          ▼                ▼
┌─────────────────────────────────────────────┐
│         quantcode/mcp_server.py             │
│    (根据QUANTCODE_GROUP暴露工具)            │
└─────────────────┬───────────────────────────┘
                  │
          ┌───────┴────────┐
          ▼                ▼
┌──────────────┐   ┌──────────────┐
│ run_agent    │   │ list_tools   │
│ (MCP tool)   │   │ call_tool    │
└──────┬───────┘   └──────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│         runner/agent_engine.py              │
│          (AgentRunner主引擎)                │
│                                             │
│  ┌─────────────────────────────────┐       │
│  │  ReAct Loop:                    │       │
│  │  1. LLM决策                     │       │
│  │  2. 调用tool                    │       │
│  │  3. 观察结果                    │       │
│  │  4. 重复 (最多10次)            │       │
│  └─────────────────────────────────┘       │
└──────┬──────────────────────┬───────────────┘
       │                      │
       │ 调用工具             │ 路由决策
       ▼                      ▼
┌──────────────┐      ┌──────────────┐
│ tools/       │      │ runner/      │
│ registry     │      │ routing/     │
│              │      │ router.py    │
│ ┌──────────┐ │      └──────┬───────┘
│ │ factor/  │ │             │
│ │ risk/    │ │             │ requires_human?
│ │ model/   │ │             ▼
│ │ strategy/│ │      ┌──────────────┐
│ │ fundamen.│ │      │ HumanGate    │
│ │ options/ │ │      │ (interrupt)  │
│ └──────────┘ │      └──────────────┘
└──────┬───────┘
       │ 调用
       ▼
┌──────────────┐
│ schemas/     │
│ (Pydantic)   │
└──────────────┘
```

---

## 9. 关键设计模式

### Pattern 1: Orchestrator-Worker
- **Orchestrator**: AgentRunner（决策者）
- **Worker**: 各组工具（执行者）
- **通信**: ToolDef规范

### Pattern 2: Human-in-the-Loop
- **触发**: routing/router.py判断risk_metrics
- **暂停**: AgentRunner.run() 返回status='interrupted'
- **恢复**: AgentRunner.resume(thread_id, decision)

### Pattern 5: Checkpoint Recovery
- **存储**: SQLite (`.quantcode/checkpoints.db`)
- **时机**: 每次迭代后
- **恢复**: `runner.resume(thread_id)`

---

## 10. 环境变量配置

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `QUANTCODE_GROUP` | 当前组（6选1） | 无（必需） |
| `QUANTCODE_FACTOR_USE_REAL_LLM` | 启用factor真实实现 | 0（stub） |
| `DEEPSEEK_API_KEY` | DeepSeek API密钥 | 从config.json读取 |
| `DEEPSEEK_BASE_URL` | DeepSeek API地址 | https://api.deepseek.com/v1 |
| `DEEPSEEK_MODEL` | 模型名称 | deepseek-chat |
| `AUTOEVAL_API_URL` | AutoEval API地址 | 无（降级到mock） |
| `AUTOEVAL_API_KEY` | AutoEval API密钥 | 无 |
| `GITHUB_TOKEN` | GitHub API token | 无（需要才报错） |

---

## 11. 配置文件

### `config.json` (项目根目录)
```json
{
  "llm": {
    "provider": "deepseek",
    "api_key": "sk-...",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "temperature": 0.0,
    "max_tokens": 4096
  }
}
```

### `opencode.local.jsonc` (OpenCode目录)
```jsonc
{
  "provider": {
    "openai": {
      "apiKey": "sk-...",
      "baseURL": "https://api.deepseek.com"
    }
  },
  "mcp": {
    "quantcode-factor": {
      "type": "local",
      "command": ["python", "-m", "quantcode.mcp_server"],
      "environment": {
        "QUANTCODE_GROUP": "factor",
        "PYTHONPATH": "/Users/.../QUANTcode"
      }
    }
  }
}
```

---

## 12. 常见问题排查

### Q1: "Tool 'xxx' not found"
**原因**: 工具未注册或QUANTCODE_GROUP设置错误
**解决**:
```python
import tools.factor._register  # 确保导入
from tools.registry import get_registry
print(get_registry().list())  # 查看已注册工具
```

### Q2: "Module 'langchain_openai' not found"
**原因**: 依赖未安装
**解决**:
```bash
pip install langchain-openai
```

### Q3: HumanGate不触发
**原因**: risk_metrics未超阈值
**解决**: 检查`runner/routing/router.py`的阈值配置

### Q4: Checkpoint恢复失败
**原因**: `.quantcode/checkpoints.db`损坏
**解决**:
```bash
rm .quantcode/checkpoints.db
# 或修复SQLite
sqlite3 .quantcode/checkpoints.db "PRAGMA integrity_check;"
```

---

## 13. 扩展指南

### 添加新工具
```python
# 1. 定义schema
class MyArgs(BaseModel):
    input: str

# 2. 实现execute
def my_execute(args: MyArgs, ctx: dict) -> dict:
    return {"result": args.input.upper()}

# 3. 创建ToolDef
my_tool = ToolDef(
    id='my_tool',
    description='做什么',
    schema=MyArgs,
    execute=my_execute,
)

# 4. 注册
register_tool(my_tool)
```

### 添加新组
1. 创建`tools/newgroup/`目录
2. 创建`_register.py`注册工具
3. 创建`.opencode/groups/newgroup/skills/newgroup/SKILL.md`
4. 更新`quantcode/mcp_server.py`的GROUP_ALLOWLIST

---

## 14. 性能考虑

- **Checkpoint频率**: 每次迭代后（~0.1s开销）
- **LLM调用延迟**: 2-5秒/次
- **AutoEval超时**: 120秒（评估耗时）
- **ReAct最大迭代**: 10次（防止死循环）

---

## 15. 安全考虑

- **工具权限**: ToolDef不暴露文件系统直接访问
- **API密钥**: 从环境变量读取，不入库
- **Blackboard隔离**: 按thread_id和scope隔离
- **GitHub token**: 需要repo权限（最小化原则）

---

## 附录：术语表

| 术语 | 含义 |
|------|------|
| **ReAct** | Reasoning + Acting，LLM推理+执行循环 |
| **HumanGate** | 人工审批点，高风险暂停 |
| **Checkpoint** | Agent执行状态快照 |
| **Blackboard** | 跨组共享状态存储 |
| **MCP** | Model Context Protocol，IDE与后端通信协议 |
| **ToolDef** | 工具定义规范 |
| **SKILL.md** | 组级提示词，定义Agent行为 |
| **execution_trace** | Agent执行事件流 |
| **thread_id** | Agent会话ID |
| **stub** | 桩代码，返回固定mock数据 |

---

**相关文档**：
- [TEST_GUIDE.md](../TEST_GUIDE.md) - 测试指南
- [TESTING_MANUAL.md](./TESTING_MANUAL.md) - 测试人员手册
- [QuantCode_Design.md](./QuantCode_Design.md) - 架构设计
- [PRD.md](./PRD.md) - 产品需求

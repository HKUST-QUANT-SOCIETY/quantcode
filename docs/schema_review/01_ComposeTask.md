# ComposeTask Schema 评审文档

> **Owner**: 用户（Lead）  
> **模式**: Pattern 1 (Orchestrator-Worker)  
> **评审时长**: 5 分钟  
> **状态**: 待评审

---

## 一句话定义

> **ComposeTask 是所有 skill 之间通信的统一任务信封**，类比 GitHub Issue：有 ID、状态、输入输出、父子关系、审计日志。

---

## 为什么需要它

**问题**：
- 因子组的 `factor:autoeval` 完成后要把结果传给 `factor:merge-main`，两个 skill 之间的**输入输出格式**必须一致
- 前端 Compose 视图要画任务树、任务卡片、状态条，前端只认一种数据结构
- CI / 验收 runner / Memory 查询、日志追踪，全部围绕 `task_id` 拉数据

**解决**：统一任务信封 + 泛型 `ComposeTask[TIn, TOut]`，内容物（FactorSpec / RiskProfile）由业务 schema 定义。

---

## 核心字段

| 字段 | 类型 | 必填 | 用途 |
|---|---|---|---|
| `task_id` | `str` (T1.2.3) | ✅ | 人类可读的层级 ID，**就是树路径**（不另设 tree_path） |
| `internal_id` | `UUID` | ✅ | 稳定引用（重命名后不变） |
| `session_id` | `str` (S[0-9a-f]{16}) | ✅ | 会话隔离 |
| `parent_task_id` | `str \| None` | ❌ | 父任务 ID（root 为 None） |
| `root_task_id` | `str` | ✅ | 树的根（runner 用来 fan checkpoint） |
| `depth` | `int` (0-4) | ✅ | 树深度，root = 0，最大 4 |
| `group` | `GroupName` | ✅ | 6 组之一（fundamental/factor/model/risk/strategy/options） |
| `status` | `TaskStatus` | ✅ | 5 状态：open / in_progress / blocked / done / abandoned |
| `outcome` | `TaskOutcome \| None` | ❌ | terminal-only：success / failure / cancelled / rejected |
| `summary` | `str` | ✅ | 任务一句话描述（≤512 字符） |
| `input` | `TIn` (泛型) | ✅ | 类型化输入（如 FactorSpec） |
| `output` | `TOut \| None` (泛型) | ❌ | 类型化输出（如 FactorReport） |
| `dispatch_count` | `int` (0-100) | ✅ | 分发次数（重试计数） |
| `last_error` | `str \| None` | ❌ | 失败时的错误信息 |
| `created_at` | `datetime` | ✅ | 创建时间（JSON 序列化成 Unix epoch int） |
| `started_at` | `datetime \| None` | ❌ | 开始时间 |
| `finished_at` | `datetime \| None` | ❌ | 结束时间 |

---

## 关键约束（Pydantic 自动校验）

1. **树结构**：
   - root (depth=0) 不能有 parent_task_id
   - root_task_id 必须是 task_id 的前缀（T1.2 的 root 必须是 T1）
   - 最大深度 4（MAX_TREE_DEPTH）

2. **状态机**（5 状态，MimoCode-aligned）：
   ```
   open → in_progress → {blocked, done, abandoned}
   blocked → {in_progress, abandoned}
   ```

3. **Outcome 门控**（terminal-only）：
   - `status=DONE` **强制** `outcome=SUCCESS`
   - `status=ABANDONED` **强制** `outcome ∈ {FAILURE, CANCELLED, REJECTED}`
   - 非 terminal 状态 **禁止** 设 outcome

4. **泛型类型流**：
   - `ComposeTask[FactorSpec, FactorReport]` 在调用点给出完整类型
   - mypy/Pyright 可以端到端检查

---

## 示例：因子评估任务

```python
from schemas import ComposeTask, GroupName, TaskStatus, TaskOutcome

# 业务 payload（Day 1 下午评审）
class FactorSpec(BaseModel):
    name: str
    universe: str = "CSI1000"

class FactorReport(BaseModel):
    ic_mean: float
    ir: float

# 创建任务
task = ComposeTask[FactorSpec, FactorReport](
    task_id="T1.2",
    session_id="S0123456789abcdef",
    parent_task_id="T1",
    root_task_id="T1",
    depth=1,
    group=GroupName.FACTOR,
    summary="Evaluate PB×ROE factor",
    input=FactorSpec(name="pb_roe"),
)

# Runner 填充结果
task.status = TaskStatus.DONE
task.outcome = TaskOutcome.SUCCESS
task.output = FactorReport(ic_mean=0.05, ir=0.7)
```

**JSON 序列化后**（时间戳变 int）：
```json
{
  "task_id": "T1.2",
  "internal_id": "a1b2c3d4-...",
  "session_id": "S0123456789abcdef",
  "parent_task_id": "T1",
  "root_task_id": "T1",
  "depth": 1,
  "group": "factor",
  "status": "done",
  "outcome": "success",
  "summary": "Evaluate PB×ROE factor",
  "input": {"name": "pb_roe", "universe": "CSI1000"},
  "output": {"ic_mean": 0.05, "ir": 0.7},
  "dispatch_count": 1,
  "created_at": 1719734400,
  "started_at": 1719734401,
  "finished_at": 1719734420
}
```

---

## 开放问题（评审会讨论）

### Q1: dispatch_count 上限 100 够不够？

- **背景**：v0 是 10，R2 review 要求提到 100
- **理由**：不同任务类型重试预算不同（研报 5 次、回测 10 次、交易 1 次）
- **建议**：
  - **A**: 保持 100，runner 自己控制重试策略
  - **B**: 改成可配置（每个 skill 自己定上限）
  - **C**: 去掉上限，改成软警告（dispatch_count > 10 时 log warning）

### Q2: session_id 谁分配？

- **背景**：OpenCode fork 的 session 概念是否和我们一致？
- **问题**：用户 SSH 登录后，谁生成 session_id？OpenCode CLI 还是我们的 wrapper？
- **格式**：`S[0-9a-f]{16}` (64-bit)，和 OpenCode 的 session ID 格式兼容吗？

### Q3: task_id 的 "T1.2.3" 格式谁生成？

- **背景**：MimoCode 用 hierarchical string，我们对齐
- **问题**：
  - Orchestrator 生成时，如何保证 T1.2 的下一个子任务是 T1.2.1 而不是 T1.3？
  - 还是用 UUID 生成后再映射到 hierarchical string？
- **建议**：Orchestrator 维护一个 `next_child_index` 计数器

### Q4: 5 状态机足够吗？

- **背景**：MimoCode 5 状态，我们对齐
- **潜在缺失**：
  - 没有 `pending` 状态（任务创建但未分发）？— 用 `open` 代替
  - 没有 `retrying` 状态？— 用 `dispatch_count` + `in_progress` 表达
- **确认**：这两个场景用现有状态覆盖，不加新状态

---

## 依赖关系

**ComposeTask 被以下 schema 依赖**：
- `HumanGate` (杨欣琳) — 引用 `task_id` 触发人审
- `ModelSpec` / `RiskProfile` / `FactorSpec` / `ResearchSpec` (业务 schema) — 作为 `ComposeTask[TIn, TOut]` 的类型参数
- `ComposeTaskEvent` (审计日志) — 记录 task 生命周期

**ComposeTask 依赖**：
- `BlackboardState` (下一个评审项) — task 通过 blackboard 读写状态

---

## 测试覆盖

✅ 29 个测试全过（`tests/test_compose_task.py`）：
- 树结构约束（root 不能有 parent、root_task_id 前缀、深度上限）
- 状态/outcome 门控（DONE→SUCCESS、ABANDONED→{FAILURE,CANCELLED,REJECTED}、非 terminal 禁 outcome）
- 泛型类型流（`ComposeTask[FactorSpec, FactorReport]` 实例化）
- JSON 序列化（datetime → int）

---

## 决策记录（评审会后填写）

| 决策点 | 决策 | 理由 | 反对意见 |
|---|---|---|---|
| Q1: dispatch_count 上限 | ？ | ？ | ？ |
| Q2: session_id 分配方 | ？ | ？ | ？ |
| Q3: task_id 生成策略 | ？ | ？ | ？ |
| Q4: 状态机是否扩展 | ？ | ？ | ？ |

---

**评审通过签字**（全员）：

- [ ] 用户（Lead）
- [ ] 陈镇鸿
- [ ] 杨欣琳
- [ ] 刘炽
- [ ] 肖骥超

# Day 1 Schema 评审会 — PPT 大纲

> **时长**: 90 分钟  
> **前 30 分钟**: 三大契约（ComposeTask + BlackboardState）  
> **后 60 分钟**: 5 套业务 schema

---

## Slide 1: 开场（1 分钟）

**标题**: QuantCode Schema 评审会 — Pattern 1 + 2 契约冻结

**内容**:
- **目标**: 今天冻结 3 套契约 + 5 套业务 schema（v1）
- **流程**: 
  - 0:00-0:30 三大契约（ComposeTask + BlackboardState + HumanGate）
  - 0:30-1:30 业务 schema（ResearchSpec / PITQuery / ModelSpec / RiskProfile / FactorSpec）
- **规则**: 契约不冻结，业务 schema 无法写（依赖关系）

---

## Part 1: ComposeTask（Lead 主讲，10 分钟）

### Slide 2: 为什么需要统一任务信封？

**问题**:
- ❌ 每个 skill 各自定义输入输出 → 前端画不了任务树
- ❌ CI runner 不知道从哪读 task_id → 验收无法追踪
- ❌ skill 之间传递数据格式不统一 → Orchestrator 无法调度

**解决**:
✅ **统一任务信封** = ComposeTask  
✅ 内容物（FactorSpec / RiskProfile）由业务 schema 定义  
✅ 泛型 `ComposeTask[TIn, TOut]` 给出端到端类型流

---

### Slide 3: ComposeTask 核心字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | `str` (T1.2.3) | 人类可读层级 ID |
| `internal_id` | `UUID` | 稳定引用（重命名不变） |
| `group` | `GroupName` | 6 组之一 |
| `status` | `TaskStatus` | 5 状态机 |
| `outcome` | `TaskOutcome \| None` | terminal-only |
| `input` | `TIn` | 泛型输入 |
| `output` | `TOut \| None` | 泛型输出 |

**关键约束**:
- 树深度 ≤ 4（T1.2.3.4.5）
- DONE 强制 outcome=SUCCESS
- ABANDONED 强制 outcome ∈ {FAILURE, CANCELLED, REJECTED}

---

### Slide 4: 示例 — 因子评估任务

```python
task = ComposeTask[FactorSpec, FactorReport](
    task_id="T1.2",
    group=GroupName.FACTOR,
    input=FactorSpec(name="pb_roe"),
)

# Runner 填充
task.status = TaskStatus.DONE
task.outcome = TaskOutcome.SUCCESS
task.output = FactorReport(ic_mean=0.05, ir=0.7)
```

**JSON 序列化**（时间戳 → int）:
```json
{
  "task_id": "T1.2",
  "status": "done",
  "outcome": "success",
  "input": {"name": "pb_roe"},
  "output": {"ic_mean": 0.05, "ir": 0.7},
  "created_at": 1719734400
}
```

---

### Slide 5: 开放问题（讨论 3 分钟）

| 问题 | 选项 |
|---|---|
| **Q1: dispatch_count 上限 100 够不够？** | A. 保持 100<br>B. 可配置<br>C. 去掉上限 |
| **Q2: session_id 谁分配？** | OpenCode CLI vs 我们的 wrapper |
| **Q3: task_id "T1.2.3" 谁生成？** | Orchestrator 维护 `next_child_index` |
| **Q4: 5 状态机足够吗？** | 确认 open/in_progress/blocked/done/abandoned |

---

## Part 2: BlackboardState（Lead 主讲，10 分钟）

### Slide 6: 为什么需要共享状态层？

**问题**:
- ❌ 长任务（10h+）会 compact，LLM 记不住
- ❌ Worker 之间不能直接对话（Pattern 1 禁止）
- ❌ 跨组协作：model 组写 PR 元数据，risk 组读取 → 没有契约

**解决**:
✅ **状态外化到磁盘**（MEMORY.md / checkpoint.md / progress.md）  
✅ **5 层隔离**（GLOBAL / PROJECT / GROUP / SESSION / TASK）  
✅ **WritePolicy 明确权限**（OWNER / APPEND / GROUP_APPEND）

---

### Slide 7: 5 层隔离 — 磁盘映射

| Scope | 磁盘路径 | 谁能读 | 典型用途 |
|---|---|---|---|
| **GLOBAL** | `.quantcode/memory/global/MEMORY.md` | 所有人 | 跨项目用户偏好 |
| **PROJECT** | `./MEMORY.md` | 所有组 | 项目级共享知识 |
| **GROUP** | `.quantcode/memory/groups/<group>/MEMORY.md` | **仅本组** | 组内私有 |
| **SESSION** | `.quantcode/memory/sessions/<sid>/checkpoint.md` | 本会话 | 会话 checkpoint |
| **TASK** | `.quantcode/memory/sessions/<sid>/tasks/<tid>/progress.md` | 本任务 | 任务进度 |

---

### Slide 8: 🔴 关键决策 — GROUP 隔离墙是硬的

**用户核心要求**:
> "跨组读权限应该不能给。只有部分 public 的数据可以读 memory。"

**实现**:
- ❌ factor 组写 `group:factor:ic_registry`，risk 组 `get_entry()` 返回 `None`
- ✅ 显式 PUBLIC 数据写到 `PROJECT` scope，key 前缀 `shared.*`

**代码示例**:
```python
# ❌ 跨组读不到
bb.get_entry(BlackboardScope.GROUP, GroupName.FACTOR, "ic_registry")
# → None（如果当前是 risk 组）

# ✅ 显式 PUBLIC
bb.add_entry(BlackboardEntry(
    scope=BlackboardScope.PROJECT,
    key="shared.factor_registry",  # shared.* = public
    ...
))
# → 所有组都能读到
```

---

### Slide 9: WritePolicy — 3 种权限

| Policy | 谁能写 | 场景 |
|---|---|---|
| **OWNER** | 只有写入的 task | 任务进度 |
| **APPEND** | 任何 task，仅追加 | 全局日志 |
| **GROUP_APPEND** | 同组任何 task，仅追加 | 因子注册表（组内协作） |

**GROUP_APPEND at PROJECT scope**（R2 Q1 澄清）:
- 用 `written_by_group` 追踪
- 场景：factor registry 让 fundamental/factor 两组都能追加

---

### Slide 10: 开放问题（讨论 3 分钟）

| 问题 | 选项 |
|---|---|
| **Q1: SESSION checkpoint 保留多久？** | A. 7 天<br>B. 到项目关闭<br>C. 手动清理 |
| **Q2: TASK progress 谁清理？** | A. task 完成立即删<br>B. 保留到 session 结束<br>C. 归档到 artifacts/ |
| **Q3: GROUP 下要不要细分"子组"（user scope）？** | A. 不做（MVP）<br>B. 加 USER scope<br>C. GROUP 加 owner 字段 |
| **Q4: version 乐观锁语义？** | A. 检查 version 防冲突<br>B. last-writer-wins<br>C. MVP 不做并发写 |

---

## Part 3: 业务 Schema（后 60 分钟）

### Slide 11: 业务 Schema 清单

| Schema | Owner | 用途 | 作为 ComposeTask 类型参数 |
|---|---|---|---|
| **ResearchSpec + PITQuery/PITResult** | 用户（Lead） | 基本面研报 + PIT-RAG | `ComposeTask[ResearchSpec, ResearchResult]`<br>`ComposeTask[PITQuery, PITResult]` |
| **ModelSpec** | 陈镇鸿 | 模型组 PR 元数据 | `ComposeTask[ModelSpec, ModelResult]` |
| **RiskProfile** | 杨欣琳 | 风控画像 | `ComposeTask[RiskRequest, RiskProfile]` |
| **FactorSpec** | 肖骥超 | 因子评估 | `ComposeTask[FactorSpec, FactorReport]` |
| **HumanGate** | 杨欣琳 | Pattern 5 人审 | 引用 `task_id` |

**每个 schema 10 分钟**（5 分钟讲解 + 5 分钟讨论）

---

### Slide 12: ResearchSpec — 研报生成输入

**核心字段**:
- `target_type`: company / industry / macro
- `target_identifier`: ticker（2097.HK）或行业代码
- `as_of_date`: **时点约束**（所有引用 ≤ 此日期）
- `research_questions`: 研究员关心的问题清单
- `sections`: 要生成的章节（中金 6 章节）
- `retrieval_result`: pit-rag 填充的检索结果

**关键约束**:
- `research_questions` ≥ 1 个
- `sections` 默认 5 章节（overview/business/financials/valuation/risks）

---

### Slide 13: PITQuery/PITResult — 时点正确的 RAG

**PITQuery**:
- `query`: 自然语言问题
- `as_of_date`: 检索时点
- `corpus`: 语料范围（研报/公告/电话会/新闻/ALL）
- `top_k`: 召回数量（默认 10）

**PITResult**:
- `documents`: 返回文档列表
- `filtered_count`: 时点过滤掉的文档数

**🔴 关键校验**（Pydantic validator）:
```python
for doc in result.documents:
    assert doc.published_at <= result.as_of_date
```

**如果违反** → `ValidationError: lookahead bias detected`

---

### Slide 14: 蜜雪冰城研报示例

```python
# 1. 用户提交
spec = ResearchSpec(
    target_type=TargetType.COMPANY,
    target_identifier="2097.HK",
    as_of_date=date(2024, 3, 15),
    research_questions=["2023 年收入增长驱动力？", "估值合理性？"],
)

# 2. pit-rag 检索
result = PITResult(
    as_of_date=date(2024, 3, 15),
    documents=[
        PITDocument(published_at=date(2024, 2, 20), ...),  # ✅
        PITDocument(published_at=date(2024, 3, 1), ...),   # ✅
    ],
)

# 3. 生成研报
output = ResearchResult(
    pdf_path="artifacts/research/2097HK-2024-03-15.pdf",
    citations_count=23,
)
```

---

### Slide 15: ResearchSpec 开放问题

| 问题 | 选项 |
|---|---|
| **Q1: SectionType 支持自定义章节？** | A. 不支持（MVP）<br>B. 加 CUSTOM enum<br>C. 改成 list[str] |
| **Q2: PITQuery.corpus 默认值？** | A. [RESEARCH_REPORTS, ANNOUNCEMENTS]<br>B. ALL<br>C. 强制显式指定 |
| **Q3: filtered_count 语义？** | 当前：只统计时点过滤<br>是否改名 `lookahead_filtered_count`？ |
| **Q4: ResearchResult 验收阈值？** | `citations_count >= 10` 按 target_type 分层？ |

---

### Slide 16-19: 其他业务 Schema（陈镇鸿/杨欣琳/肖骥超各讲 10 分钟）

**Slide 16**: ModelSpec（陈镇鸿）
- 模型类型、训练数据范围、超参、依赖算子
- 跨组发起：model → risk

**Slide 17**: RiskProfile（杨欣琳）
- max_drawdown / position_limit / correlation / VaR
- 跨组接收：model → risk

**Slide 18**: FactorSpec（肖骥超）
- 因子函数、universe、date_range、benchmark
- 接 AutoFactorEvaluation 服务

**Slide 19**: HumanGate（杨欣琳）
- Pattern 5 契约
- 引用 task_id，触发人审

---

## Slide 20: 收尾（5 分钟）

### 决策记录

**当场记录到** `docs/schema_review/decision_record.md`:
- 三大契约的 4 个开放问题 × 决策
- 5 套业务 schema 的开放问题 × 决策

### 下一步

- ✅ 三大契约 + 5 套业务 schema 冻结（v1）
- 📋 下午：hello-world plugin 验证 OpenCode 加载
- 📋 下午：陈镇鸿写 `tools/utils/dedupe.py`
- 📋 下午：用户（Lead）+ 刘炽拆中金研报版式

### 签字

全员在评审文档签字确认。

---

**备注**: 每页留 Q&A 时间，控制节奏（30 分钟三大契约 + 60 分钟业务 schema）。

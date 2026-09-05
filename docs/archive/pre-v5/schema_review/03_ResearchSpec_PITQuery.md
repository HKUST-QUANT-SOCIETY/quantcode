# ResearchSpec + PITQuery/PITResult 评审文档

> **Owner**: 用户（Lead）  
> **组**: fundamental  
> **评审时长**: 5 分钟  
> **状态**: 已评审

---

## 一句话定义

> **ResearchSpec 是基本面研报生成任务的输入规格**，**PITQuery/PITResult 是 point-in-time RAG 检索的查询和结果**。两者配合完成"时点正确的研报生成"。

---

## 为什么需要它们

**问题**：

- 基本面研报生成流程（brainstorm → fetch → extract → dcf → draft → render）需要明确输入输出
- 时点正确性是量化研究的生死线：用 2024-03-16 的信息做 2024-03-15 的研报 = lookahead bias
- LLM 生成研报时容易"穿越"，必须用 schema + 验收 assert 强制约束

**解决**：

- `ResearchSpec` 定义"研究什么、什么时点、要哪些章节"
- `PITQuery` 发给 pit-rag skill，`PITResult` 返回时点正确的文档
- `PITResult` 的 Pydantic validator 自动检查 lookahead bias

---

## ResearchSpec 字段

| 字段                 | 类型                | 必填 | 用途                              |
| -------------------- | ------------------- | ---- | --------------------------------- |
| `target_type`        | `TargetType`        | ✅   | company / industry / macro        |
| `target_identifier`  | `str`               | ✅   | ticker（2097.HK）或行业代码或主题 |
| `target_name`        | `str \| None`       | ❌   | 可读名称（如'蜜雪冰城'）          |
| `as_of_date`         | `date`              | ✅   | 研报时点（所有引用数据 ≤ 此日期） |
| `research_questions` | `list[str]`         | ✅   | 研究员关心的问题（≥1 个）         |
| `sections`           | `list[SectionType]` | ❌   | 要生成的章节（默认 5 章节）       |
| `output_format`      | `str`               | ❌   | pdf / markdown / both（默认 pdf） |
| `retrieval_result`   | `PITResult \| None` | ❌   | pit-rag 填充的检索结果            |

### SectionType（中金风格 6 章节）

| Enum 值               | 中文     | 说明               |
| --------------------- | -------- | ------------------ |
| `OVERVIEW`            | 公司概览 | 基本信息、股权结构 |
| `BUSINESS`            | 业务分析 | 商业模式、竞争优势 |
| `FINANCIALS`          | 财务分析 | 三表、关键指标     |
| `VALUATION`           | 估值     | DCF、相对估值      |
| `RISKS`               | 风险提示 | 政策风险、经营风险 |
| `INDUSTRY_COMPARISON` | 行业对比 | 同业对比（可选）   |

---

## PITQuery 字段

| 字段         | 类型               | 必填 | 用途                       |
| ------------ | ------------------ | ---- | -------------------------- |
| `query`      | `str`              | ✅   | 自然语言问题               |
| `as_of_date` | `date`             | ✅   | 检索时点                   |
| `corpus`     | `list[CorpusType]` | ❌   | 语料范围（默认 ALL）       |
| `top_k`      | `int`              | ❌   | 召回数量（默认 10，1-100） |

### CorpusType

| Enum 值            | 说明       |
| ------------------ | ---------- |
| `RESEARCH_REPORTS` | 券商研报   |
| `ANNOUNCEMENTS`    | 公司公告   |
| `EARNINGS_CALLS`   | 业绩电话会 |
| `NEWS`             | 新闻       |
| `ALL`              | 全部       |

---

## PITResult 字段

| 字段                | 类型                | 必填 | 用途                        |
| ------------------- | ------------------- | ---- | --------------------------- |
| `query`             | `str`               | ✅   | 原始查询                    |
| `as_of_date`        | `date`              | ✅   | 检索时点                    |
| `documents`         | `list[PITDocument]` | ✅   | 返回文档（按 score 降序）   |
| `total_candidates`  | `int`               | ✅   | 召回候选总数（过滤前）      |
| `filtered_count`    | `int`               | ✅   | 过滤掉的文档数（lookahead） |
| `retrieval_time_ms` | `int`               | ✅   | 检索耗时（毫秒）            |

### PITDocument（单个文档）

| 字段           | 类型          | 必填 | 用途                 |
| -------------- | ------------- | ---- | -------------------- |
| `id`           | `str`         | ✅   | 文档唯一 ID          |
| `source`       | `str`         | ✅   | 来源（如'中金公司'） |
| `title`        | `str \| None` | ❌   | 文档标题             |
| `published_at` | `date`        | ✅   | **发布日期（关键）** |
| `snippet`      | `str`         | ✅   | 相关片段             |
| `score`        | `float`       | ✅   | 相关性得分（0-1）    |
| `url`          | `str \| None` | ❌   | 原文链接             |

---

## 关键约束：lookahead bias 检测

**Pydantic validator 自动检查**（`PITResult._check_no_lookahead`）：

```python
for doc in result.documents:
    assert doc.published_at <= result.as_of_date
```

**如果违反**：

```python
PITResult(
    query="蜜雪冰城财务",
    as_of_date=date(2024, 3, 15),
    documents=[
        PITDocument(id="ok", published_at=date(2024, 2, 20), ...),
        PITDocument(id="leak", published_at=date(2024, 4, 1), ...),  # ❌ 穿越
    ],
)
# → ValidationError: lookahead bias detected: 1 docs published after 2024-03-15: ['leak']
```

---

## 示例：蜜雪冰城研报生成

### 1. 用户提交 ResearchSpec

```python
from schemas.fundamental import ResearchSpec, TargetType, SectionType
from datetime import date

spec = ResearchSpec(
    target_type=TargetType.COMPANY,
    target_identifier="2097.HK",
    target_name="蜜雪冰城",
    as_of_date=date(2024, 3, 15),
    research_questions=[
        "2023 年收入增长的主要驱动力是什么？",
        "当前估值（30x PE）是否合理？",
        "加盟模式的风险点在哪里？",
    ],
    sections=[
        SectionType.OVERVIEW,
        SectionType.BUSINESS,
        SectionType.FINANCIALS,
        SectionType.VALUATION,
        SectionType.RISKS,
    ],
    output_format="pdf",
)
```

### 2. fundamental:fetch 调用 pit-rag

```python
from schemas.fundamental import PITQuery, CorpusType

query = PITQuery(
    query="蜜雪冰城 2023 年度财务分析 加盟模式 估值",
    as_of_date=spec.as_of_date,
    corpus=[CorpusType.RESEARCH_REPORTS, CorpusType.ANNOUNCEMENTS],
    top_k=20,
)
```

### 3. pit-rag 返回 PITResult

```python
from schemas.fundamental import PITResult, PITDocument

result = PITResult(
    query=query.query,
    as_of_date=query.as_of_date,
    documents=[
        PITDocument(
            id="cicc-2097hk-2024-02-20",
            source="中金公司",
            title="蜜雪冰城：加盟模式驱动快速扩张",
            published_at=date(2024, 2, 20),
            snippet="2023 年收入 189 亿元，同比增长 42%...",
            score=0.89,
            url="https://...",
        ),
        PITDocument(
            id="announcement-2097-2024-03-01",
            source="港交所",
            title="蜜雪冰城 2023 年度业绩公告",
            published_at=date(2024, 3, 1),
            snippet="净利润 26.8 亿元...",
            score=0.85,
        ),
    ],
    total_candidates=150,
    filtered_count=12,  # 12 个文档因 published_at > 2024-03-15 被过滤
    retrieval_time_ms=450,
)

# ✅ 自动校验通过（所有 doc.published_at <= 2024-03-15）
```

### 4. ResearchSpec 更新（fundamental:fetch 填充）

```python
spec.retrieval_result = result
```

### 5. fundamental:draft 生成 ResearchResult

```python
from schemas.fundamental import ResearchResult

output = ResearchResult(
    pdf_path="artifacts/research/2097HK-2024-03-15.pdf",
    sections_generated=[
        SectionType.OVERVIEW,
        SectionType.BUSINESS,
        SectionType.FINANCIALS,
        SectionType.VALUATION,
        SectionType.RISKS,
    ],
    citations_count=23,
    render_time_ms=1840,
    word_count=5200,
)
```

---

## 与 ComposeTask 的集成

```python
from schemas import ComposeTask, GroupName, TaskStatus, TaskOutcome
from schemas.fundamental import ResearchSpec, ResearchResult

# 创建研报生成任务
task = ComposeTask[ResearchSpec, ResearchResult](
    task_id="T3",
    session_id="S0123456789abcdef",
    root_task_id="T3",
    depth=0,
    group=GroupName.FUNDAMENTAL,
    summary="Generate 蜜雪冰城 research report as of 2024-03-15",
    input=spec,
)

# Runner 完成后填充
task.status = TaskStatus.DONE
task.outcome = TaskOutcome.SUCCESS
task.output = output
```

---

## 开放问题（评审会讨论）

### Q1: SectionType 是否要支持自定义章节？

- **背景**：6 个 enum 值是中金标准结构
- **问题**：如果研究员要加"管理层分析"章节怎么办？
- **建议**：
  - **A**: 不支持自定义（MVP 阶段，6 个够用）
  - **B**: 加一个 `CUSTOM` enum 值 + `custom_section_title: str` 字段
  - **C**: `sections` 改成 `list[str]`，放弃 enum 约束

### Q2: PITQuery.corpus 默认值是 ALL 还是 RESEARCH_REPORTS？

- **背景**：`ALL` 召回量大但噪音多，`RESEARCH_REPORTS` 精准但覆盖面窄
- **建议**：
  - **A**: 默认 `[CorpusType.RESEARCH_REPORTS, CorpusType.ANNOUNCEMENTS]`（券商研报 + 公告）
  - **B**: 默认 `ALL`（当前实现）
  - **C**: 不设默认值，强制用户显式指定

### Q3: PITResult.filtered_count 的语义？

- **背景**：`total_candidates` - `len(documents)` ≠ `filtered_count`（因为还有相关性过滤）
- **问题**：`filtered_count` 是"时点过滤掉的"还是"所有被过滤的"？
- **当前实现**：只统计时点过滤（lookahead bias）
- **确认**：这个语义是否清晰？要不要改名 `lookahead_filtered_count`？

### Q4: ResearchResult 的验收标准？

- **背景**：research-pdf skill 的 runner 验收（见 `runner/acceptance.py`）
- **当前标准**：
  ```python
  assert pdf_path exists
  assert sections_generated == spec.sections
  assert citations_count >= 10
  ```
- **问题**：`citations_count >= 10` 是否合理？短研报（如行业快评）可能只有 5 条引用
- **建议**：按 `target_type` 分层阈值（company: 10, industry: 5, macro: 3）

---

## 依赖关系

**ResearchSpec 依赖**：

- `PITResult` — 作为 `retrieval_result` 字段类型
- `ComposeTask[ResearchSpec, ResearchResult]` — 作为泛型参数

**PITQuery/PITResult 依赖**：

- 无（独立 schema）
- 被 `ResearchSpec` 引用

**被依赖**：

- `fundamental:fetch` skill — 消费 `PITQuery`，产出 `PITResult`
- `fundamental:draft` skill — 消费 `ResearchSpec`（含 `retrieval_result`），产出 `ResearchResult`

---

## 测试覆盖（TODO）

需要补充的测试（`tests/test_fundamental.py`）：

- [ ] ResearchSpec 合法实例可序列化
- [ ] PITResult validator 检测 lookahead bias
- [ ] PITResult validator 通过合法输入
- [ ] ResearchResult 路径校验（pdf_path 存在性）
- [ ] 与 ComposeTask 的集成（泛型实例化）

---

## 决策记录（评审会后填写）

| 决策点                      | 决策                                                     | 理由                                                     | 反对意见                               |
| --------------------------- | -------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------- |
| Q1: 自定义章节支持          | MVP 不支持自定义章节                                     | enum 能保证前端、runner、模板的章节集合稳定              | 后续需要"管理层分析"等章节时再加 enum  |
| Q2: PITQuery.corpus 默认值  | 保持 `[CorpusType.ALL]`                                  | 当前实现已覆盖全部语料，具体 skill 可显式传入更窄 corpus | 噪音控制交给 fetch skill 或配置        |
| Q3: filtered_count 语义     | 保持字段名，语义固定为 lookahead 过滤数                  | 避免破坏现有接口，同时在字段说明中明确含义               | 如后续加入多类过滤统计，再新增细分字段 |
| Q4: ResearchResult 验收阈值 | 按 `target_type` 分层：company 10 / industry 5 / macro 3 | 短研报不应被公司深度报告阈值误杀                         | runner thresholds 仍可覆盖默认值       |

---

**评审通过签字**（全员）：

- [ ] 用户（Lead）
- [ ] 陈镇鸿
- [ ] 杨欣琳
- [ ] 刘炽
- [√] 肖骥超

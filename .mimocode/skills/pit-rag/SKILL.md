---
name: pit-rag
description: 量化研究专用 RAG，强制 point-in-time 时点正确，杜绝 lookahead bias
---

# Point-in-Time RAG Skill

## 何时使用

当用户需要在某个历史时点检索研报、公告、纪要或财务数据时调用。

## 关键约束

**所有检索结果必须满足 `published_at <= as_of_date`**。这是量化 RAG 与普通 RAG 的核心差异。

## 输入

- query：自然语言研究问题
- as_of_date：检索的时点（YYYY-MM-DD）
- corpus：可选，限定语料范围（research_reports / announcements / earnings_calls）

## 工作流程

1. 解析 query，提取实体（公司 / 行业 / 主题）
2. 向量检索，召回 top-k 候选
3. **时点过滤**：丢弃所有 `published_at > as_of_date` 的文档
4. 二次重排（rerank）按相关性 + 时间衰减
5. 输出结构化结果

## 输出 schema

见 `schemas/research-spec.schema.json` 的 `retrieval` 字段。

## 验收标准

- 所有返回文档的 `published_at` 严格 <= `as_of_date`
- 召回率 @ 10 >= 0.7（人工标注样本）
- 检索延迟 P95 < 500ms

## 数据依赖

- 向量库：Chroma（本地起步）
- 切片策略：按段落 + 重叠 50 token
- Embedding：bge-large-zh-v1.5 或 OpenAI text-embedding-3

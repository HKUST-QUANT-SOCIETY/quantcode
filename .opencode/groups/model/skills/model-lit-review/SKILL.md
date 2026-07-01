---
name: model-lit-review
description: 文献分享结构化（解决会议纪要散乱问题）
group: model
owner: 陈镇鸿
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
---

# Model Lit Review Skill

## 何时使用

模型组每周文献分享会前，把多篇论文 / 博客的关键信息抽取成结构化笔记，沉淀到组级 MEMORY.md，避免"分享完即丢"。

## 输入

- 论文 PDF / arXiv 链接 / 博客 URL（一份或多份）
- 关心的主题（可选）
- 关联方向（alpha / portfolio / execution / risk / infra，可选）

## 工作流程

1. **抓取正文**：PDF 解析 / 网页抓取
2. **LLM 结构化**：抽取 problem / method / experiment / result / takeaway
3. **生成结构化笔记**：每篇文献输出统一字段，便于之后检索和复用
4. **写入 Group MEMORY**：`.opencode/groups/model/MEMORY.md` 追加新条目
5. **生成分享会用的 markdown 摘要**

## 输出 schema

```yaml
papers:
  - title: ...
    authors: [...]
    published_at: 2026-...
    problem: ...
    method: ...
    experiment: ...
    result: ...
    takeaway: ...
    relevance_to_quant: ...
    possible_model_features: [...]
    implementation_risk: low | medium | high
```

## 验收标准

- 每篇文献至少包含 title / problem / method / takeaway / relevance_to_quant
- markdown 摘要可直接用于周会分享
- 写入 GROUP memory 的内容不包含跨组私密数据；需要共享时另写 PROJECT scope 的 `shared.*` 摘要

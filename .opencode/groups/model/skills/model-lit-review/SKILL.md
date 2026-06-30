---
name: model:lit-review
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

## 工作流程

1. **抓取正文**：PDF 解析 / 网页抓取
2. **LLM 结构化**：抽取 problem / method / experiment / result / takeaway
3. **写入 Group MEMORY**：`.opencode/groups/model/MEMORY.md` 追加新条目
4. **生成分享会用的 markdown 摘要**

## 输出 schema

```yaml
papers:
  - title: ...
    authors: [...]
    published_at: 2026-...
    problem: ...
    method: ...
    takeaway: ...
    relevance_to_quant: ...
```

## 验收标准

- 每篇文献 5 个字段都非空
- 写入 MEMORY.md 后能被后续 `factor:brainstorm` 检索到

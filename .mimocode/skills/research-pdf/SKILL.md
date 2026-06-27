---
name: research-pdf
description: 从结构化输入生成中金/华泰风格的专业 PDF 研报
---

# Research PDF Skill

## 何时使用

当用户提供一份研究规格（公司、时点、关注点）时，自动生成可发布的 PDF 研报。

## 输入

符合 `schemas/research-spec.schema.json` 的研究规格。

## 工作流程

1. 调用 `pit-rag` skill 拉取相关研报、财报、公告
2. 调用 LLM 生成各章节结构化内容（markdown / JSON）：
   - 公司概览
   - 业务分析
   - 财务分析
   - 估值（DCF / 相对估值）
   - 风险提示
3. 填充 `templates/typst/research-report.typ` 模板
4. 调用 `typst compile` 渲染 PDF
5. 产物落地到 `artifacts/research/<company>-<date>.pdf`

## 输出 schema

```json
{
  "pdf_path": "artifacts/research/2097HK-2026-06-27.pdf",
  "sections_generated": ["overview", "business", "financials", "valuation", "risks"],
  "citations_count": 23,
  "render_time_ms": 1840
}
```

## 验收标准

- PDF 渲染成功（exit code 0）
- 所有章节非空
- 至少 10 条引用
- **人工验收（半程序化）**：研究员愿意发出去 = 通过

## 模板

`templates/typst/research-report.typ` 由 T3 owner 维护，需对齐中金研报版式。

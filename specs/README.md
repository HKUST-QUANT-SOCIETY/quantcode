# QuantCode Spec 体系 — 文档地图与规范流程

> v1（2026-09-01）· Owner: Lead · 适用于 QuantCode 后端与 lens UI 全部域 SPEC。

## 1. 文档地图

| 层 | 文件 | 状态 | 职责 |
|---|---|---|---|
| 功能总目录 | [specs/FUNCTIONAL_SPEC.md](FUNCTIONAL_SPEC.md) | 活文档 | 功能唯一事实源：F-XX / P-XX 编号、用户故事、验收口径 |
| 域 SPEC | specs/data/SPEC.md · specs/governance/SPEC.md（扩展中） | draft | 契约先行 + 机器可验证断言（"how"层） |
| 长期路线 | docs/audit/ROADMAP_LONGTERM.md | 活文档 | 四季度里程碑、跨域依赖、协作机制 |
| 历史快照 | docs/PRD.md、docs/QuantCode_Design.md、docs/Architecture_Spec.md、docs/Day1~5_* | **只读冻结** | Day1-5 语境；冲突时以本体系为准 |
| 质量台账 | docs/audit/DEVIATION_REGISTRY.md · ACCEPTANCE_REPORT.md | 活文档 | 偏差修复与验收记录 |

### 文档链路

```
FUNCTIONAL_SPEC (F-XX/P-XX, what & why)
   → 域 SPEC (契约先行 + 机器可验证断言, how)
      → 实现 (代码) + verdict (机器验证结果回填 spec §6)
```

## 2. spec-driven 核心规则（细则见 SPEC_GUIDE.md）

1. **schema 变更必须先改 spec 再改代码**；PR 不附 SPEC diff，reviewer 直接打回。
2. **断言映射测试**：每条断言（编号 `<域>-<序>`，如 D1-A1 / G2-A2）必须能表达为 pytest/playwright；test 文件不存在则标注 `[新增测试]`。
3. **verdict 机器回填**：§6 结果只能来自真实测试运行，禁止人工写"看起来对"。
4. **路径必须真实**：SPEC 引用的每个文件路径真实存在，或显式标 `[新增]`；评审逐条核对。
5. **断言唯一性**：跨 spec 编号唯一；旧断言重排=supersede，在 §0 记录。
6. **契约单源**：schemas/*.py（Pydantic v2）为单一真源，JSON Schema 为生成物，CI 校验一致。
7. **季度红队**：每季度末独立核验"§6 断言仍被测试真实覆盖"（P1-6 遗漏教训的制度化），结论写入 docs/audit/。
8. lens UI 同规则：断言用 playwright 表达，组件真源 = packages/app/src。

## 3. 现有域 SPEC 一览

| SPEC | 覆盖功能 | status | target |
|---|---|---|---|
| specs/data/SPEC.md | P-01 数据接入（qs-cold → FactorPanel/ReturnsDataset） | draft | Q1 D1+D2-dev |
| specs/governance/SPEC.md | F-03 HumanGate 现状锁定 + P-06 evidence chain | draft | Q1 G2-A1 / Q3 G2-B1 |

规划中的域名（随 ROADMAP 推进开新 SPEC）：`engine`（并行/沙箱/流式，P-04）、`portfolio`（P-03）、`research`（A2/A3 实验，P-05）、`product`（U1-U4）。
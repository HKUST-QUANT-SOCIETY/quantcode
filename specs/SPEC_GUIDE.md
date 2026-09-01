# SPEC_GUIDE — QuantCode spec-driven 设计文档规范

> v1（2026-09-01）· Owner: Lead · 适用：QuantCode 后端与 lens UI 全部域 SPEC。

## 1. 文档链路

```
specs/FUNCTIONAL_SPEC.md            specs/<域>/SPEC.md              实现代码 / 测试
F-XX 用户功能 / P-XX 平台功能  →  契约先行 + 机器可验证断言  →  实现  →  verdict 回填 SPEC §6
```

- FUNCTIONAL_SPEC 是唯一入参：只定义"是什么/给谁/验收口径"，不写实现；编号 F-XX / P-XX 跨季不复用。
- 域 SPEC：契约必须先于代码变更落地；断言是测试的规格来源，测试是断言的执行体。
- verdict 回填：pytest/playwright 机器验证结果填入 §6，禁止人工补写。
- 与老文档关系：docs/PRD.md（v2）与 docs/QuantCode_Design.md（v2 对齐）为顶层设计活文档；docs/Day1~5 系列 = **历史快照，只读**；冲突时以 SPEC 为准。
- schema 单一真源：schemas/*.py（Pydantic v2）；JSON Schema 为生成物，CI 校验两者一致。

## 2. SPEC 固定章节（§0–§6，缺章节不得离开 draft）

| 章节 | 内容 | 硬性约束 |
|---|---|---|
| §0 元信息 | status / owner / source 功能编号 / target milestone | status ∈ draft, review, accepted, superseded |
| §1 范围与非目标 | 做什么、明确不做什么 | 非目标须可引用 |
| §2 契约 | 输入/输出 schema，字段级类型+不变量 | 引用 schemas/ 真实路径或标注 `[新增]` |
| §3 数据流 | 工具序列 → Blackboard key → UI 组件 | 箭头文字图；key 遵守黑板命名空间 |
| §4 机器可验证断言 | 编号 A-1..N | 每条可映射 pytest/playwright；禁止含糊措辞 |
| §5 开放问题 | 未定案事项 | 每条有 owner + 决策截止里程碑 |
| §6 verdict 表 | 断言→测试→结果→日期 | 结果 ∈ pass, fail, blocked |

## 3. 全局规则

1. schema 变更必须**先改 spec 再改代码**；PR 未附 SPEC diff 链接，reviewer 打回。
2. 断言编号跨 spec 唯一：`<域>-<序>` 前缀（如 `D1-A1`、`G2-A2`）；重排旧断言 = supersede，须在 §0 记录。
3. 断言措辞只允许可执行谓词（等于/存在/抛出/有序/⊆），禁止"合理地""应当尽量""正确处理"。
4. SPEC 引用的每个文件路径必须真实存在，或显式标注 `[新增]`；评审逐条核对。
5. 每季度末独立红队核验：逐条抽检 §6 断言仍被测试真实覆盖（P1-6 断言—测试漂移教训的制度化），结论写入 docs/audit/。
6. 契约废弃不改旧 SPEC：新开版本并在旧 SPEC §0 标 `superseded_by`。
7. lens UI 同规则：断言用 playwright 表达，组件真源 = packages/app/src。

## 4. 断言与格式约定

- 断言行：`- <ID>: <对象> <可执行谓词>（测试: <path>::<函数>）`。test 文件不存在则标 `[新增测试]`，落地时必须同名落盘。
- verdict 行：`<ID> | tests/<文件>::<函数> | pass,fail,blocked | YYYY-MM-DD`。结果只能来自真实测试运行。
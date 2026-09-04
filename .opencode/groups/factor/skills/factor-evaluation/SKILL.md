---
name: factor-evaluation
description: 调用 canonical QuantEvaluator 并记录契约、来源、版本和 Artifact
group: factor
owner: 肖骥超
pattern: ReAct + component adapter
---

# Factor Evaluation Skill

## 能力选择

```text
已有 FactorPanel / 因子值 → QuantEvaluator
没有因子值              → DataAccess → FactorEngine → QuantEvaluator
需要结构或参数搜索       → FactorOptimizer
需要身份、去重和入库     → FactorAssets
```

Agent 必须先查 Capability Catalog、Group Memory 和数据契约。QuantCode 不计算第二套 IC、IR、换手、分层或标签，也不以 proxy/mock 指标替代 QuantEvaluator。

## 执行

1. 验证 FactorSpec / FactorPanel 契约；
2. 调用 `quant_evaluator`；
3. 检查统一 ComponentCallResult；
4. `SUCCEEDED` 时展示组件返回的 Artifact；
5. `UNAVAILABLE`、`PARTIAL`、`MOCK`、`PROXY` 或 `STAGING` 时原样显示状态，不宣称生产评估成功；
6. 真实共享资产写入仅由 `merge_to_main` 创建 `merge` Gate。

CI 兼容 Flow 为 `flows.factor_evaluation_adapter` / `factor:evaluation`，产品主路径仍是 ReAct。

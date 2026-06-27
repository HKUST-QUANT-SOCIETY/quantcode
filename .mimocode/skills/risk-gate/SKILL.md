---
name: risk-gate
description: 分析 PR 中的策略代码，计算风控画像并输出标准化 JSON，用于 CI 自动门禁
---

# Risk Gate Skill

## 何时使用

当用户提交一个包含策略代码的 PR，或在 CI 中触发 risk-gate workflow 时调用本 skill。

## 输入

- PR diff（来自 GitHub Actions context）
- 策略代码所在路径

## 工作流程

1. **静态分析** 策略代码，识别仓位计算、止损逻辑、杠杆使用
2. **运行回测**（如配置允许），取最近 1 年的样本外数据
3. **计算指标**：
   - max_drawdown
   - position_limit
   - correlation_with_existing
   - capacity_estimate_usd
   - tail_risk_var_99
4. **输出符合 `schemas/risk-profile.schema.json` 的 JSON**
5. **调用 runner 跑预设阈值校验**

## 输出 schema

见 `schemas/risk-profile.schema.json`。

## 验收标准

- JSON 严格通过 schema 校验
- 所有数值字段非空
- runner 返回 `pass` / `fail` 明确结论

## 失败处理

- 回测数据缺失 → 标记 `tail_risk_var_99=null`，runner 自动 fail
- 静态分析无法识别策略类型 → 返回 ask，进入人工 review

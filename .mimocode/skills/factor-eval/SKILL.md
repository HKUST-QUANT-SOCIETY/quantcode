---
name: factor-eval
description: 评估单个因子的有效性，自动计算 IC / IR / 换手 / 衰减并输出标准化报告
---

# Factor Evaluation Skill

## 何时使用

当因子组同学提交一个新因子（Python 函数 + 参数）时，自动完成全套评估并输出 JSON。

## 输入

```python
def factor_func(panel: pd.DataFrame) -> pd.Series:
    """输入 (date, stock) 面板，输出 (date, stock) 因子值"""
    ...
```

加上：
- universe：股票池（默认 CSI 1000）
- date_range：评估区间
- benchmark：基准（默认 HS300）

## 工作流程

1. 拉取 universe 面板数据（OHLCV + 财务）
2. 计算因子值
3. **去极值 + 中性化 + 标准化**
4. 计算指标：
   - IC（Pearson + Spearman），按月聚合
   - IR = IC.mean() / IC.std()
   - 月度换手率
   - 衰减曲线（1, 3, 5, 10, 20 日）
   - 分层回测（十分位）
5. 输出符合 `schemas/factor-report.schema.json` 的 JSON
6. 调用 runner 跑验收阈值

## 验收阈值（默认）

- `abs(IC.mean()) >= 0.03`
- `IR >= 0.5`
- `turnover_monthly <= 0.8`
- `t_stat >= 2.0`

阈值可在 `pipelines/factor_eval/config.yaml` 覆盖。

## 输出

`schemas/factor-report.schema.json`

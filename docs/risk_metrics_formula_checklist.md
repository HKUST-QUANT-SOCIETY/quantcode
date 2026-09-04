# 风控统计指标计算口径清单

Owner: 肖骥超 / T4 为杨欣琳 `risk-ci` 提供统计口径支持

这份文档只定义指标怎么算、输入是什么、输出应该长什么样。它不替代
`risk-ci`，也不直接生成 `risk.json`。变量名保留英文，方便之后写进
schema、runner 和代码。

---

## max_drawdown

`max_drawdown` 表示策略净值从历史最高点下跌到之后最低点的最大跌幅。它衡量的是“最坏的一段连续亏损有多深”。

### 输入

`r_t`：策略按时间排序的收益率序列。

例子：

```text
r_t = [0.10, -0.05, -0.10, 0.08]
```

含义是：

```text
第 1 期收益 +10%
第 2 期收益 -5%
第 3 期收益 -10%
第 4 期收益 +8%
```

### 计算公式

```text
equity_t = cumulative product of (1 + r_t)
running_peak_t = max(equity_0, ..., equity_t)
drawdown_t = equity_t / running_peak_t - 1
max_drawdown = abs(min(drawdown_t))
```

### 手算例子

假设初始净值为 1：

```text
r_t       = [0.10, -0.05, -0.10, 0.08]
equity_t  = [1.10, 1.045, 0.9405, 1.01574]
```

每一期历史最高净值：

```text
running_peak_t = [1.10, 1.10, 1.10, 1.10]
```

每一期回撤：

```text
drawdown_t = [
  1.10 / 1.10 - 1,
  1.045 / 1.10 - 1,
  0.9405 / 1.10 - 1,
  1.01574 / 1.10 - 1
]

drawdown_t = [0.0000, -0.0500, -0.1450, -0.0766]
```

所以：

```text
max_drawdown = abs(min(drawdown_t)) = abs(-0.1450) = 0.1450
```

输出：

```json
{
  "max_drawdown": 0.145
}
```

解释：这个策略在样例区间内最大回撤为 14.5%。

输出范围：

```text
0 <= max_drawdown <= 1
```

---

## tail_risk_var_99

`tail_risk_var_99` 表示 99% VaR。这里建议使用 historical VaR，也就是直接从历史收益率分布里取 1% 分位数。

直观理解：如果 `tail_risk_var_99 = -0.05`，表示按历史分布估计，最差 1% 情况下单期损失大约会超过 5%。

### 输入

`r_t`：策略收益率序列，频率要固定，例如日收益、周收益或月收益。不同频率的 VaR 不能直接比较。

例子：

```text
r_t = [-0.08, -0.05, -0.03, -0.01, 0.00, 0.01, 0.02, 0.04, 0.06, 0.10]
```

### 计算公式

Historical 99% VaR：

```text
tail_risk_var_99 = 1% quantile of r_t
```

### 手算例子

上面的样例只有 10 个点，严格的 1% 分位数需要插值；为了 demo 简单，可以用最差收益近似：

```text
sorted(r_t) = [-0.08, -0.05, -0.03, -0.01, 0.00, 0.01, 0.02, 0.04, 0.06, 0.10]
tail_risk_var_99 ≈ -0.08
```

输出：

```json
{
  "tail_risk_var_99": -0.08
}
```

解释：在这个极小样本里，历史最差单期收益是 -8%，可以作为 99% VaR 的粗略 demo 值。真实使用时应使用更长样本和统一 quantile 方法。

### 符号约定

保留收益率符号：

```text
亏损写成负数，例如 -0.05
盈利写成正数，例如 0.03
```

不要把 VaR 写成正的 0.05，除非整个 `risk-ci` schema 明确采用“损失为正”的约定。当前建议使用收益率符号，因此亏损为负。

Day 1 PRD 阻塞条件：

```text
tail_risk_var_99 must not be null
```

也就是说，`risk-ci` 至少要能给出一个 VaR 数值；如果数据不足，应明确说明 insufficient data，而不是静默返回 null。

---

## expected_shortfall_99

`expected_shortfall_99` 也叫 CVaR。它衡量的是“已经进入最差 1% 情况以后，平均会亏多少”。

VaR 只看分位点，Expected Shortfall 看尾部平均损失，因此通常比 VaR 更能反映极端风险。

### 输入

`r_t`：策略收益率序列。

`VaR_99`：前面算出的 99% VaR。

例子：

```text
r_t = [-0.12, -0.08, -0.05, -0.02, 0.00, 0.01, 0.03, 0.04]
VaR_99 ≈ -0.08
```

### 计算公式

```text
expected_shortfall_99 = mean(r_t | r_t <= VaR_99)
```

### 手算例子

找出所有小于等于 `VaR_99` 的收益：

```text
r_t <= -0.08 的点是 [-0.12, -0.08]
```

取平均：

```text
expected_shortfall_99 = (-0.12 + -0.08) / 2 = -0.10
```

输出：

```json
{
  "expected_shortfall_99": -0.10
}
```

解释：当策略进入最差尾部情形时，平均单期亏损约为 10%。

---

## turnover

`turnover` 表示调仓换手率。它衡量策略每次调仓时组合权重变化有多大，通常用于估计交易成本、容量和策略稳定性。

### 输入

每个资产调仓前后的权重：

```text
weight_before_i
weight_after_i
```

例子：

```text
asset              A     B     C
weight_before   0.50  0.30  0.20
weight_after    0.40  0.40  0.20
```

### 计算公式

单次调仓换手：

```text
turnover_t = sum(abs(weight_after_i - weight_before_i)) / 2
```

月度换手：

```text
monthly_turnover = mean(turnover_t over monthly rebalances)
```

### 手算例子

每只资产权重变化：

```text
A: abs(0.40 - 0.50) = 0.10
B: abs(0.40 - 0.30) = 0.10
C: abs(0.20 - 0.20) = 0.00
```

总变化：

```text
sum(abs(weight_after_i - weight_before_i)) = 0.10 + 0.10 + 0.00 = 0.20
```

除以 2：

```text
turnover_t = 0.20 / 2 = 0.10
```

输出：

```json
{
  "turnover_t": 0.10
}
```

解释：这次调仓的单边换手率是 10%。

如果一个月有 3 次调仓：

```text
turnover_t = [0.10, 0.20, 0.15]
monthly_turnover = (0.10 + 0.20 + 0.15) / 3 = 0.15
```

输出：

```json
{
  "monthly_turnover": 0.15
}
```

Day 1 factor-eval 默认验收阈值：

```text
monthly_turnover <= 0.8
```

---

## correlation_with_existing

`correlation_with_existing` 表示候选策略和已有策略或已有组合收益之间的相关性。

它用于判断新策略是否真的带来增量信息。如果相关性太高，即使单独看收益不错，也可能只是重复已有暴露。

### 输入

按相同日期对齐的两个收益率序列：

```text
candidate_returns
existing_returns
```

例子：

```text
date          t1     t2     t3     t4
candidate   0.01   0.02  -0.01   0.00
existing    0.02   0.01  -0.02   0.01
```

### 计算公式

```text
correlation_with_existing = PearsonCorr(candidate_returns, existing_returns)
```

展开写就是：

```text
correlation = cov(candidate_returns, existing_returns)
              / (std(candidate_returns) * std(existing_returns))
```

### 例子解释

如果计算得到：

```text
correlation_with_existing = 0.75
```

输出：

```json
{
  "correlation_with_existing": 0.75
}
```

解释：候选策略与已有组合高度正相关，可能重复已有策略暴露。

如果计算得到：

```text
correlation_with_existing = 0.20
```

解释：相关性较低，更可能提供增量收益来源。

### 数据要求

只使用两个序列都有值的日期：

```text
aligned_dates = intersection(candidate_dates, existing_dates)
```

如果重叠样本太少，例如少于 30 个观测值，建议不要强行给出相关性结论：

```json
{
  "correlation_with_existing": null,
  "correlation_status": "insufficient_data"
}
```

PRD 默认风控阈值：

```text
abs(correlation_with_existing) <= 0.60
```

---

## worst_1d_return

`worst_1d_return` 表示样本期内最差单日收益。

### 输入

日收益率序列：

```text
r_t = [0.01, -0.03, 0.02, -0.07, 0.00]
```

### 计算公式

```text
worst_1d_return = min(r_t)
```

### 手算例子

```text
min([0.01, -0.03, 0.02, -0.07, 0.00]) = -0.07
```

输出：

```json
{
  "worst_1d_return": -0.07
}
```

解释：样本期内最差一天亏损 7%。

---

## position_limit

`position_limit` 表示组合中单个资产的最大权重。它用于控制单票集中度风险。

### 输入

某一时点的组合权重：

```text
weights = {
  "A": 0.25,
  "B": 0.10,
  "C": 0.05,
  "cash": 0.60
}
```

### 计算公式

如果只看股票资产：

```text
position_limit = max(abs(weight_i)) for tradable assets
```

### 手算例子

忽略 cash 后：

```text
tradable_weights = [0.25, 0.10, 0.05]
position_limit = max(abs(tradable_weights)) = 0.25
```

输出：

```json
{
  "position_limit": 0.25
}
```

解释：最大单票仓位为 25%。

PRD 默认风控阈值：

```text
position_limit <= 0.30
```

---

## 建议给 `risk-ci` 的字段

建议 `risk.json` 至少包含：

```json
{
  "max_drawdown": 0.145,
  "position_limit": 0.25,
  "correlation_with_existing": 0.20,
  "tail_risk_var_99": -0.08,
  "expected_shortfall_99": -0.10,
  "worst_1d_return": -0.07,
  "monthly_turnover": 0.15
}
```

其中 Day 1 PRD 已明确用于阻塞或验收的字段是：

```text
max_drawdown <= 0.20
position_limit <= 0.30
abs(correlation_with_existing) <= 0.60
tail_risk_var_99 is not None
```

`expected_shortfall_99`、`worst_1d_return`、`monthly_turnover` 可以先作为 warning 或补充说明字段，不一定 Day 1 就作为阻塞条件。

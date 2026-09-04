## Summary

提交新的模型因子/策略：`pb_roe_ranker`

该模型为 `boosting` 类型，使用 PB、ROE TTM、市值等特征，对 CSI1000 股票池进行排序建模。模型代码位于：

`tests/fixtures/sample_model/sample_model.py`

## Model Information

- Model name: `pb_roe_ranker`
- Model type: `boosting`
- Owner: `chen-zhenhong`
- Code path: `tests/fixtures/sample_model/sample_model.py`
- Training data range: `2021-01-01` to `2023-12-31`
- As-of date: `2024-03-15`
- Commit SHA: `abcdef1`

## Feature / Operator Dependencies

### Feature dependencies

- `pb`
- `roe_ttm`
- `market_cap`

### Operator dependencies

- `rank`
- `zscore`

## Hyperparameters

- `n_estimators`: `100`
- `learning_rate`: `0.05`
- `max_depth`: `3`

## Risk Metadata

- Universe: `CSI1000`
- Benchmark: `CSI1000`
- Expected holding period: `20` days
- Max position: `5%`
- Uses leverage: `false`
- Notes: Day 1 fixture for model-to-risk handoff; uses mock PB/ROE features.

## ModelSpec

```json
{
  "model_name": "pb_roe_ranker",
  "model_type": "boosting",
  "owner": "chen-zhenhong",
  "code_path": "tests/fixtures/sample_model/sample_model.py",
  "training_data_start": "2021-01-01",
  "training_data_end": "2023-12-31",
  "as_of_date": "2024-03-15",
  "hyperparameters": {
    "n_estimators": 100,
    "learning_rate": 0.05,
    "max_depth": 3
  },
  "feature_dependencies": [
    "pb",
    "roe_ttm",
    "market_cap"
  ],
  "operator_dependencies": [
    "rank",
    "zscore"
  ],
  "risk_metadata": {
    "universe": "CSI1000",
    "benchmark": "CSI1000",
    "expected_holding_period_days": 20,
    "max_position_pct": 0.05,
    "uses_leverage": false,
    "notes": "Day 1 fixture for model-to-risk handoff; uses mock PB/ROE features."
  },
  "commit_sha": "abcdef1"
}
Risk Review Handoff
请风控组基于上述 ModelSpec 执行 risk-ci 检查，重点关注：
- CSI1000 universe / benchmark 是否一致
- 最大单票仓位 5% 是否符合限制
- 持仓周期 20 天对应的换手和容量假设
- 是否存在杠杆使用：当前为 false
- PB / ROE / 市值特征及 rank、zscore 算子是否满足 point-in-time 要求
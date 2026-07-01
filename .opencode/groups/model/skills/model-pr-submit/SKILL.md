---
name: model:pr-submit
description: 模型组提 PR 时自动填风控元数据 + 触发 risk Compose 流
group: model
owner: 陈镇鸿
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 5 (Human-in-the-Loop Gate)
---

# Model PR Submit Skill

## 何时使用

模型组同学完成一个新的 ML 因子 / 策略 / 模型，准备提 PR 时调用本 skill。

## 输入

- 本地模型代码路径（repo-relative）
- 训练数据范围：`training_data_start` / `training_data_end` / `as_of_date`
- 模型类型：`linear` / `tree` / `boosting` / `neural_net` / `ensemble` / `other`
- 超参、特征依赖、算子依赖
- 风控元数据：universe / benchmark / holding period / max position / leverage

## 工作流程

1. **生成 `ModelSpec`**：模型类型、训练数据范围、超参、依赖算子、风控元数据
2. **校验**：用 Pydantic 校验 `ModelSpec`；不通过则报错给用户改
3. **创建 PR**：通过 `github_pr_create`（必须带 `@dedupe_within`）
4. **附 PR 描述**：在 PR body 中写入 fenced JSON block，标题为 `ModelSpec`
5. **触发跨组**：通知 risk Compose 流消费 PR URL + `ModelSpec`
6. **登记到 Blackboard**：GROUP scope 保存私有细节，PROJECT scope 只写 `shared.pending_risk_reviews`

## 输出 schema

`schemas.model.ModelSpec`，同时在 PR 描述里附 JSON 块：

```json
{
  "model_name": "pb_roe_ranker",
  "model_type": "boosting",
  "code_path": "tests/fixtures/sample_model/sample_model.py",
  "training_data_start": "2021-01-01",
  "training_data_end": "2023-12-31",
  "as_of_date": "2024-03-15",
  "hyperparameters": {"n_estimators": 100, "learning_rate": 0.05},
  "feature_dependencies": ["pb", "roe_ttm", "market_cap"],
  "operator_dependencies": ["rank", "zscore"],
  "risk_metadata": {
    "universe": "CSI1000",
    "benchmark": "CSI1000",
    "expected_holding_period_days": 20,
    "max_position_pct": 0.05,
    "uses_leverage": false
  },
  "commit_sha": "abcdef1"
}
```

## 验收标准

- PR 成功创建（GitHub PR URL 返回）
- `ModelSpec` 通过 Pydantic 校验
- 风控组的 risk-gate workflow 被触发（GH Actions run 出现）
- 同一 commit + 同一 PR body 在 5 分钟内不会重复创建 PR / 重复通知

## 副作用 tool 约定

- `github_pr_create` key：`{commit_sha}:{sha256(pr_body)}`
- `cross_team_notify` key：`model:risk:{pr_url}:{commit_sha}`
- dedupe window：300 秒

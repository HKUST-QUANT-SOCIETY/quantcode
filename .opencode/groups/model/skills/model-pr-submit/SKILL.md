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

1. **读取 PR**：调用 `read_pr(pr_number)` 获取 diff
2. **提取元数据**：调用 `extract_metadata(diff)` 获取 ticker / factor 信息
3. **生成 ModelSpec**：调用 `generate_model_spec(metadata)` 生成模型规格
4. **写入 Blackboard**：调用 `write_blackboard(key="model.pr_<pr_number>_spec", value=spec)` 写入 PROJECT scope
5. **触发风控**：调用 `trigger_risk_flow(blackboard_key="model.pr_<pr_number>_spec")` 写 PROJECT scope 的 `shared.pending_risk_reviews`，供 risk 组消费

当前实现不默认双写 GROUP 私有条目；只有后续确有模型组私有状态需要时，才由对应 tool 显式写 GROUP scope。

## 强制规则

- **必须执行全部 5 步**，不得在任意步骤后提前停止
- 即使元数据是 UNKNOWN / unknown_factor 等 mock 值，也必须继续执行后续步骤
- 生成 ModelSpec 后，**必须紧接着**调用 write_blackboard
- **必须紧接着**调用 trigger_risk_flow 完成 handoff
- 不得在生成 ModelSpec 后输出纯文本结束；必须继续调用工具
- 如果某步工具执行失败，重试或报告错误，不得跳过后续步骤
- **完成 checklist**：每步完成后 mentally 标记为已完成，然后立即执行下一步。只有 5 步全部完成时，才能输出纯文本总结。

## 输出 schema

`schemas.model.ModelSpec`，同时写入 Blackboard：

```json
{
  "model_id": "model-bc0e42f8",
  "model_type": "lightgbm",
  "training_window": {"start": "2020-01-01", "end": "2024-12-31"},
  "hyperparameters": {"learning_rate": 0.05, "num_leaves": 31}
}
```

## 验收标准

- [ ] `read_pr` 已调用，PR diff 已获取
- [ ] `extract_metadata` 已调用，元数据已提取
- [ ] `generate_model_spec` 已调用，spec 已生成
- [ ] `write_blackboard` 已调用，spec 已写入 Blackboard
- [ ] `trigger_risk_flow` 已调用，risk 组已收到 handoff
- 以上 5 项必须全部完成，缺一不可
- PROJECT scope 的 `shared.pending_risk_reviews` 出现对应 pending review
- 同一 blackboard_key 在 5 分钟内不会重复触发 risk handoff（`trigger_risk_flow` 带 `@dedupe_within`）

## GitHub token 注入

- `read_pr` 真实 GitHub 路径读取 `GITHUB_TOKEN`，仓库名读取 `repo` 参数或 `GITHUB_REPOSITORY`
- 本地验证示例：`GITHUB_REPOSITORY=HKUST-QUANT-SOCIETY/opencode`
- token 只放环境变量，不写入代码、fixture、Blackboard 或测试输出

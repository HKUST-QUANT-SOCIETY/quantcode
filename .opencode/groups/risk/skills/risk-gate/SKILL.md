---
name: risk-gate
description: 接收模型组 PR，生成 RiskProfile，必要时触发 HumanGate，并向 PR 写入风控评论
group: risk
owner: 杨欣琳
pattern: Pattern 5 (Human-in-the-Loop Gate) + Pattern 1 (Orchestrator-Worker)
---

# Risk Gate Skill

## 何时使用

当模型组提交一个真实 PR，需要风控组判断策略风险是否可接受时调用本 skill。

典型入口：

- GitHub Actions 在 PR 创建或更新时触发
- 模型组通过 `model:pr-submit` handoff 给 risk 组
- 风控组手动指定一个 PR URL 做测试

## 输入

必需输入：

- `pr_url`: 模型组 PR 链接
- `head_sha`: PR 当前 commit SHA，用于去重评论
- `changed_files`: PR 中变更的文件列表
- `model_summary`: 模型或策略的简短说明

可选输入：

- `model_spec`: 模型组提供的结构化元数据
- `risk_thresholds`: 风控阈值配置
- `backtest_result`: 回测结果；Day 1 可用 mock 数据代替

示例输入：

```json
{
  "pr_url": "https://github.com/HKUST-QUANT-SOCIETY/quantcode/pull/123",
  "head_sha": "abc123",
  "changed_files": ["docs/model/sample_model_pr.md"],
  "model_summary": "sample mean-reversion model",
  "risk_thresholds": {
    "max_drawdown": 0.15,
    "position_limit_usage": 0.8,
    "correlation_limit": 0.6,
    "tail_risk_var_99": 0.05
  }
}
```

## 工作流程

1. **拉取 PR 上下文**：`pr_url`、`head_sha`、`changed_files`；解析 PR body 中的 `ModelSpec` JSON block
2. **校验输入**：`ModelSpec` 过 Pydantic；缺字段则在 `analyst_notes` 记录并降级为 `needs_human`
3. **计算风险指标**：调用 `risk_metrics`（Day 3 用 `tests/fixtures/risk_metrics_normal.json` 或 `risk_metrics_breach.json`）
4. **生成 RiskProfile**：填充 `schemas.risk_profile.RiskProfile`
5. **程序化 gate**：`profile.evaluate_verdict(thresholds)` → `pass` / `needs_human` / `rejected`
6. **HumanGate**：`needs_human` 时调用 `request_human_review`，暂停 merge
7. **写 PR 评论**：`github_pr_comment` 附结论 + fenced `RiskProfile` JSON（`@dedupe_within`）
8. **通知 model 组**：PROJECT scope 更新 `shared.risk_verdicts.<strategy_id>`

## 输出 schema

`schemas.risk_profile.RiskProfile` + `RiskGateVerdict`

```json
{
  "strategy_id": "pb_roe_ranker",
  "as_of_date": "2024-03-15",
  "max_drawdown": 0.12,
  "position_limit": 0.45,
  "correlation_with_existing": 0.35,
  "capacity_estimate_usd": 50000000,
  "tail_risk_var_99": 0.03,
  "pr_url": "https://github.com/HKUST-QUANT-SOCIETY/quantcode/pull/123",
  "analyst_notes": null
}
```

## 验收标准

- 正常 fixture → `RiskGateVerdict.PASS`，PR 评论含 `pass`
- 超阈值 fixture → `NEEDS_HUMAN`，HumanGate 触发
- `RiskProfile` 通过 Pydantic 校验
- 同一 `pr_url` + `head_sha` + verdict 在 5 分钟内不重复评论

## 副作用 tool 约定

- `github_pr_comment` key：`{pr_url}:{head_sha}:{verdict}`
- dedupe window：300 秒

## Day3 测试数据

| Fixture | 预期 verdict |
|---------|----------------|
| `tests/fixtures/risk_metrics_normal.json` | `pass` |
| `tests/fixtures/risk_metrics_breach.json` | `needs_human` |
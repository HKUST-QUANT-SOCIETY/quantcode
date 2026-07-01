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
    "max_drawdown": 0.2,
    "position_limit": 0.3,
    "correlation": 0.6,
    "var_95": 0.05
  }
}
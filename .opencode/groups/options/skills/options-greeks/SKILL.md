---
name: options:greeks
description: 基于波动率曲面与持仓合约列表计算组合 Greeks（Δ/Γ/Θ/Vega），输出风险表
group: options
owner: 刘炽
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
---

# Options Greeks Skill

## 何时使用

`options:vol-surface` 完成且 `status=ready_for_greeks` 时调用；或研究员已有曲面 + 持仓列表，仅需刷新 Greeks 时调用。

## 输入

- `options:vol-surface` 输出：`surface_path`, `underlying`, `as_of_date`
- 持仓合约列表（Day 1 可用 mock）：

```json
{
  "positions": [
    {
      "symbol": "510050C2506M02800",
      "call_put": "C",
      "strike": 2.8,
      "expiry": "2026-06-25",
      "quantity": 10,
      "side": "long"
    }
  ]
}
```

- 可选：定价模型（`bs` | `mock`，Day 1 默认 `mock`）

## 工作流程

1. **读取 Blackboard**：`strategy_id`, `surface_path`
2. **加载曲面**：读 `artifacts/options/{strategy_id}/vol_surface.json`
3. **加载持仓**：用户输入或 brainstorm 阶段约定的示例组合
4. **计算 Greeks**：逐合约 Δ、Γ、Θ、Vega；组合加总
5. **落盘**：`artifacts/options/{strategy_id}/greeks_table.csv` + `options-risk.json`
6. **阈值检查**（Day 1 简化）：`|portfolio_delta| > max_abs_delta` 则 `outcome=warn`
7. **登记 Blackboard**：供后续 `options:execute`（Day 2）或人工 review

## 输出 schema（Day 1 stub）

```json
{
  "strategy_id": "OPT-STRAT-2026-001",
  "as_of_date": "2026-06-27",
  "greeks_table_path": "artifacts/options/OPT-STRAT-2026-001/greeks_table.csv",
  "portfolio_greeks": {
    "delta": 0.05,
    "gamma": 0.12,
    "theta": -35.2,
    "vega": 128.4
  },
  "risk_flags": [],
  "status": "done"
}
```

## 验收标准（Day 1）

- `greeks_table.csv` 与 `options-risk.json` 存在
- `portfolio_greeks` 四个字段均为数值
- Compose 任务树中 options 流三步（brainstorm → vol-surface → greeks）均可标为 `done`

## 默认 tool

`greeks_calc`（Day 1 mock）、`read_sample_options`

## 副作用 tool 约定

- 写 `artifacts/`；重复计算同 `strategy_id` + `as_of_date` 应覆盖同路径（幂等）

## 下游

- Day 2：`options:execute`（回测 / 下单占位）
- 跨组：可向 `risk` 组提供 `options-risk.json` 做组合风险门禁（待定）

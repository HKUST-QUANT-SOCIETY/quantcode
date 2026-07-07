---
name: options-greeks
description: 基于持仓计算组合 Greeks，输出 GreeksProfile，可选接回测 stub
group: options
owner: 刘炽
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
tools:
  - calc_greeks
  - run_options_backtest_stub
---

# Options Greeks Skill

## 何时使用

`options-vol-surface` 完成；或已有曲面 + 持仓列表，仅需刷新 Greeks / 回测。

## 输入

- `VolSurfaceResult`（来自上一步，可选）
- `schemas.options.OptionsPosition` 或简化参数：`underlying`, `as_of_date`, `spot_price`, 持仓张数
- 可选：`OptionsStrategySpec` 用于 `run_options_backtest_stub`

## 工作流程

1. **调用 `calc_greeks`**：生成 `GreeksProfile`
2. **阈值检查**：`|portfolio_greeks.delta|` 是否超过 brainstorm 约束
3. **可选回测**：调用 `run_options_backtest_stub` 产出 `OptionsBacktestReport`
4. **落盘**（可选）：`artifacts/options/{strategy_name}/greeks.json`

## 输出 schema

`schemas.options.GreeksProfile`：

```json
{
  "underlying": "GC",
  "as_of_date": "2026-06-27",
  "portfolio_greeks": {
    "delta": 0.52,
    "gamma": 0.03,
    "vega": 14.0,
    "theta": -0.9
  },
  "leg_greeks": [],
  "currency": "USD"
}
```

回测输出：`schemas.options.OptionsBacktestReport`

## 验收标准

- [ ] `GreeksProfile` 四字段均为数值
- [ ] options 流三步（brainstorm → vol-surface → greeks）可在 AgentRunner 中跑通
- [ ] 回测 stub 通过 schema 校验

## Tool 映射

| 旧名称（Day 1） | Day 3 ToolRegistry |
|----------------|-------------------|
| `greeks_calc` | `calc_greeks` |
| （无） | `run_options_backtest_stub` |

## 下游

- 跨组：可向 risk 组提供 Greeks 摘要（待 Blackboard 键名约定）
- Day 4+：真实定价模型替换 stub

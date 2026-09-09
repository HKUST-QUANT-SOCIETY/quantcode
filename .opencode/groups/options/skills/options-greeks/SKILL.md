---
name: options-greeks
description: 核对权威期权组件的持仓 Greeks 与 GreeksProfile 契约
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
3. **可选回测**：调用实际已发布的权威回测组件；只有用户明确要求开发fixture验证、且目录允许时才使用 `run_options_backtest_stub`，结果不能作为生产PnL
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
- [ ] 当前原生任务记录真实组件执行与契约结果；未接通的曲面/Greeks明确报告，不以stub补齐
- [ ] 如果执行了回测，保留真实组件状态；fixture的schema验证只证明样本合同，不证明业务接通

## Tool 映射

| 旧名称（Day 1） | Day 3 ToolRegistry |
|----------------|-------------------|
| `greeks_calc` | `calc_greeks` |
| （无） | `run_options_backtest_stub` |

## 下游

- 跨组：可向 risk 组提供 Greeks 摘要（待 Blackboard 键名约定）
- 权威定价/回测组件未接通时明确返回缺口，不在QuantCode中替换为自造模型

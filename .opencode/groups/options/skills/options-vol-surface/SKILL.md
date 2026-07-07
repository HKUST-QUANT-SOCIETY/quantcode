---
name: options-vol-surface
description: 基于期权样本拟合隐含波动率曲面，输出 VolSurfaceResult
group: options
owner: 刘炽
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
tools:
  - build_vol_surface
---

# Options Vol Surface Skill

## 何时使用

`options-brainstorm` 完成且已有 `OptionsSpec`；或研究员直接提供清洗后的期权链数据。

## 输入

- `schemas.options.OptionsSpec`（或等价字段）
- 样本：`data/sample_options/gc_options_merged_sample.csv`
- 关键列：`underlying`, `expiration`, `strike_price`, `mid_px`, `instrument_class`

## 工作流程

1. **校验 OptionsSpec**（Pydantic）
2. **调用 `build_vol_surface`**：读取 CSV，生成曲面点集
3. **检查数据质量**：`points` 非空；`implied_vol` ∈ [0, 5]
4. **落盘**（可选）：`artifacts/options/{strategy_name}/vol_surface.json`
5. **触发下游**：`calc_greeks` / `options-greeks`

## 输出 schema

`schemas.options.VolSurfaceResult` + `strategy_name`：

```json
{
  "strategy_name": "gc_vol_carry",
  "underlying": "GC",
  "as_of_date": "2026-06-27",
  "forward_price": 3400.0,
  "points": [
    {
      "expiry": "2026-06-25",
      "strike": 3400.0,
      "side": "call",
      "implied_vol": 0.22
    }
  ],
  "interpolation_method": "sample_csv_stub",
  "data_quality": "sample"
}
```

## 验收标准

- [ ] `VolSurfaceResult` 通过 Pydantic 校验
- [ ] `len(points) >= 1`
- [ ] Agent 能自主调用 `build_vol_surface` 并继续 Greeks 步骤

## Tool 映射

| 旧名称（Day 1） | Day 3 ToolRegistry |
|----------------|-------------------|
| `vol_surface` | `build_vol_surface` |
| `read_sample_options` | 由 `build_vol_surface` 内部读 CSV |

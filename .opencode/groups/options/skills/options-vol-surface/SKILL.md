---
name: options:vol-surface
description: 基于期权成交/报价样本拟合隐含波动率曲面，供 Greeks 与组合风险计算使用
group: options
owner: 刘炽
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
---

# Options Vol Surface Skill

## 何时使用

`options:brainstorm` 完成且 `status=ready_for_vol_surface` 时调用；或研究员直接提供清洗后的期权链数据并要求更新曲面时调用。

## 输入

- `options:brainstorm` 输出的 `strategy_id` + `underlyings`
- 期权样本数据：`data/sample_options/`（csv / parquet；Day 1 可用 mock）
- 可选：拟合方法（`svi` | `polynomial` | `mock`）

样本路径（Day 1）：

- `data/sample_options/gc_options_merged_sample.csv`（mock，字段对齐 `DataStructure.md` §6）
- 生产路径：`/srv/quant/shared_data/options/merged/gc_options/{YYYY-MM-DD}.parquet`

关键列（merged gc_options）：

`datetime, file_date, symbol, raw_symbol, instrument_class, underlying, expiration, strike_price, bid_px, ask_px, mid_px, close, volume, fut_symbol`

Day 2 再接入 data review 框架与 IV 列。

## 工作流程

1. **读取 Blackboard** 获取 `strategy_id` 与标的列表
2. **加载样本**：从 `data/sample_options/` 读取；缺失则生成 mock 链（20–50 行）并标注 `data_quality=mock`
3. **数据检验**（Day 1 简化）：价格 > 0、IV ∈ [0, 5]、到期日 ≥ 交易日；失败写入 `last_error`
4. **拟合曲面**：Day 1 默认 `mock`（固定 RMSE=0.01）；Day 2 接 SVI / 多项式
5. **落盘产物**：`artifacts/options/{strategy_id}/vol_surface.json`
6. **更新 Blackboard**：`surface_path`, `fit_rmse`, `as_of_date`
7. **触发下游**：`options:greeks`

## 输出 schema（Day 1 stub）

```json
{
  "strategy_id": "OPT-STRAT-2026-001",
  "underlying": "510050.SH",
  "as_of_date": "2026-06-27",
  "surface_path": "artifacts/options/OPT-STRAT-2026-001/vol_surface.json",
  "fit_method": "mock",
  "fit_rmse": 0.01,
  "data_quality": "sample | mock",
  "status": "ready_for_greeks"
}
```

## 验收标准（Day 1）

- `vol_surface.json` 文件存在（可为 mock 内容）
- 输出 JSON 通过字段完整性检查（`surface_path`, `fit_rmse`, `status`）
- 子任务 `options:greeks` 被创建

## 默认 tool

`vol_surface`（Day 1 mock 实现）、`read_sample_options`

## 副作用 tool 约定

- 写 `artifacts/` 与 Blackboard；同一 `strategy_id` + `as_of_date` 重复拟合应幂等（覆盖同路径）

## 依赖

- 上游：`options:brainstorm`
- 数据：`data/sample_options/`（刘炽 Day 1 任务四；暂无真实数据时用 mock）
- 远期：期权组 data review 框架（`test_fraework.md`）规则接入 Day 2

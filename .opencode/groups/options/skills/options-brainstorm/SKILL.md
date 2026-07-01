---
name: options:brainstorm
description: 与研究员澄清期权策略意图、标的范围与风险约束，产出可执行的策略草案
group: options
owner: 刘炽
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
---

# Options Brainstorm Skill

## 何时使用

期权组同学提出新想法（对冲、波动率交易、价差、备兑等），但策略要素尚未结构化时调用。  
这是 options Compose 流的**第一步**，完成后自动进入 `options:vol-surface`。

## 输入

- 自然语言策略描述（如「50ETF 近月认沽保护，Delta 中性」）
- 可选：标的列表、观点方向、持仓周期、风险偏好
- 可选：`data/sample_options/` 中已有样本的标的范围

> Day 1 无 `OptionsSpec` schema；输入以对话 + JSON 草案为准。Day 2 再对齐 Pydantic 契约。

## 工作流程

1. **澄清策略类型**：方向性 / 波动率 / 套利 / 对冲 / 备兑
2. **锁定标的维度**：underlying、到期月、行权价区间、Call/Put 偏好
3. **确认约束**：最大 Delta/Gamma、保证金上限、是否允许卖期权
4. **检查数据可得性**：`data/sample_options/` 是否有对应标的近期成交/报价（无则标记 `mock_ok`）
5. **写入 Blackboard**：`group=options` scope，供 `options:vol-surface` 读取
6. **触发下游**：创建子任务 `options:vol-surface`

## 输出 schema（Day 1 stub）

```json
{
  "strategy_id": "OPT-STRAT-2026-001",
  "strategy_type": "volatility | directional | hedge | income",
  "underlyings": ["510050.SH"],
  "horizon_days": 30,
  "view": "long_vol | short_vol | neutral",
  "constraints": {
    "max_abs_delta": 0.1,
    "allow_short_options": false
  },
  "data_source": "data/sample_options/",
  "status": "ready_for_vol_surface"
}
```

## 验收标准（Day 1）

- 输出 JSON 可被下游 skill 解析（字段非空：`strategy_type`, `underlyings`, `status`）
- Blackboard 中可查到对应 `strategy_id`
- 子任务 `options:vol-surface` 被 Orchestrator 创建

## 默认 tool

`read_sample_options`（读 `data/sample_options/` 目录清单）

## 副作用 tool 约定

- 本 skill 无副作用写操作；仅读样本数据与写 Blackboard

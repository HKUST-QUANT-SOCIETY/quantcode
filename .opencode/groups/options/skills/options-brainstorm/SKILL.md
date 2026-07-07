---
name: options-brainstorm
description: 与研究员澄清期权策略意图、标的范围与风险约束，产出 OptionsSpec 草案
group: options
owner: 刘炽
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
tools:
  - build_vol_surface
---

# Options Brainstorm Skill

## 何时使用

期权组同学提出新想法（对冲、波动率交易、价差、备兑等），但策略要素尚未结构化时调用。  
完成后进入 `options-vol-surface` 或直接调用 `build_vol_surface`。

## 输入

- 自然语言策略描述（如「GC 近月认沽保护，Delta 中性」）
- 可选：标的、观点方向、持仓周期、风险偏好
- 样本数据：`data/sample_options/gc_options_merged_sample.csv`

## 工作流程

1. **澄清策略类型**：方向性 / 波动率 / 套利 / 对冲 / 备兑
2. **锁定标的维度**：underlying、到期月、行权价区间、Call/Put 偏好
3. **确认约束**：最大 Delta/Gamma、保证金上限、是否允许卖期权
4. **检查数据可得性**：`data/sample_options/` 是否有对应标的
5. **产出 `OptionsSpec` 草案**（Pydantic：`schemas.options.OptionsSpec`）
6. **触发下游**：`build_vol_surface` 或 `options-vol-surface` skill

## 输出 schema

`schemas.options.OptionsSpec`：

```json
{
  "strategy_name": "gc_vol_carry",
  "underlying": "GC",
  "as_of_date": "2026-06-27",
  "data_path": "data/sample_options/gc_options_merged_sample.csv",
  "data_source": "sample_fixture",
  "research_questions": ["曲面是否倒挂？"]
}
```

## 验收标准

- [ ] `OptionsSpec` 通过 Pydantic 校验
- [ ] `underlying` / `as_of_date` / `data_path` 非空
- [ ] 下游能解析并调用 `build_vol_surface`

## AgentRunner 提示

本阶段以对话澄清为主；结构化后由 Agent 调用 `build_vol_surface`，不要跳过 schema 校验。

---
name: strategy-compose
description: 策略组任务：复用信号、组合与回测组件，准备可追溯的研究产物
group: strategy
owner: 刘炽
pattern: Native task orchestration
schema_in: schemas.strategy.StrategySpec
schema_out: schemas.strategy.StrategyReport
---

# 策略组任务

身份由 roster 固定；当前任务统一负责计划、工具调用、子任务和结果。只使用桌面宿主 Provider 的模型配置，子任务继承身份、工作区、方案和预算。

能力目录可能发布 `select_signals`、`combine_signals` 和 `run_strategy_backtest` 等适配器；名称本身不代表已接通。

1. 查询已公布的能力目录与组 Memory，核对 DataAccess、Modeling、Riskfolio-QS、VectorBT-QS 等权威组件的真实状态。
2. 使用 `organization_reuse` 记录覆盖判断，缺口由用户在任务界面决定。需要写入时通过 `organization_solution` 冻结目标、验收和具体文件范围。
3. 按任务需要调用已发布的信号/组合/回测适配器。下列是业务顺序，不是保证可用的工具列表：信号选择 → 组合权重 → 回测 → StrategyReport。
4. 组合优化、成交回放、成本和公司行动口径来自权威组件；QuantCode 不重造这些算法。未接入或 staging 结果保持原状态。
5. 报告检查实际 contract、来源、环境、版本和结果；共享写入仅经精确 merge 审批。预算耗尽停止，不用 HumanGate 扩大预算。

生产部署只通过独立 Admin 管理面和生产服务账号。策略任务可以准备候选 artifact，不能从角色名称或一次普通审批获得生产 shell。

验收以真实 StrategyReport、权威组件证据与原生任务事件为准，不以固定工具调用次数或示例权重判断完成。

---
name: options-compose
description: 期权组任务：策略澄清、权威曲面/Greeks/回测组件与结果契约
group: options
owner: 刘炽
pattern: Native task orchestration
schema_in: schemas.options.OptionsSpec
schema_out: schemas.options.OptionsBacktestReport
---

# 期权组任务

当前 QuantCode 原生任务使用 roster 身份和宿主 Provider；不创建第二套推理循环。原生子任务继承父任务的身份、工作区、预算和方案。

能力目录可能发布 `build_vol_surface`、`calc_greeks` 或 `run_options_backtest_stub` 等适配器；名称本身不代表已接通或可提供生产证据。

1. 查询实际公布的能力目录、组 Memory 和数据契约。通过 `organization_reuse` 提出覆盖判断；缺口由用户在任务界面决定。
2. 加载 `options-brainstorm` 澄清标的、时点、到期、持仓与风险约束，形成 OptionsSpec 草案。缺失关键字段时不猜测。
3. 用 `organization_solution` 记录目标、验收和文件范围；需要方案的写入等待当前版本冻结。
4. 只有相应工具已经发布且组件实际接通，才执行波动率曲面 → Greeks → 回测。业务计算属于权威期权组件，不在 QuantCode 自建第二套实现。
5. 检查 OptionsSpec、VolSurfaceResult、GreeksProfile 和 OptionsBacktestReport 的实际契约、来源、版本、环境及状态。

`data/sample_options/gc_options_merged_sample.csv` 是样本 fixture；旧 `run_options_backtest_stub` 不能提供生产 PnL 证据。没有真实曲面/Greeks 服务时报告缺口，不以 stub 补数继续宣称完成。共享写入需要精确 merge 审批和真实成功回执，组名不授予共享数据库或生产权限。

验收要求：真实输入与时点明确；已调用组件的结果可追溯；未接通能力如实列出；任务事件、用量和取消来自同一原生执行器。

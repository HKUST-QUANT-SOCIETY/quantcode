---
name: factor:autoeval
description: 评估单个因子的有效性，自动计算 IC / IR / 换手 / 衰减并输出标准化报告
group: factor
owner: 肖骥超
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)
---

# Factor AutoEval Skill

## 何时使用

当因子组同学提交一个新因子（Python 函数 + 参数）时，自动完成全套评估并输出 JSON。本 skill 接到 HKUST-QUANT-SOCIETY/auto_factor_evaluation 服务。

## 输入

符合 `FactorSpec` schema（由肖骥超在 Day 1 起草），包含：

```python
def factor_func(panel: pd.DataFrame) -> pd.Series:
    """输入 (date, stock) 面板，输出 (date, stock) 因子值"""
    ...
```

加上：
- universe：股票池（默认 CSI 1000）
- date_range：评估区间
- benchmark：基准（默认 HS300）

## 工作流程

1. 拉取 universe 面板数据（OHLCV + 财务）
2. 计算因子值
3. **去极值 + 中性化 + 标准化**
4. 计算指标：
   - IC（Pearson + Spearman），按月聚合
   - IR = IC.mean() / IC.std()
   - 月度换手率
   - 衰减曲线（1, 3, 5, 10, 20 日）
   - 分层回测（十分位）
5. 输出符合 `schemas/factor-report.schema.json` 的 JSON
6. 调用 runner 跑验收阈值
7. 通过后写入项目级 `MEMORY.md`（Pattern 2 黑板），通知策略组「有新因子可用」

## 验收阈值（默认）

- `abs(IC.mean()) >= 0.03`
- `IR >= 0.5`
- `turnover_monthly <= 0.8`
- `t_stat >= 2.0`

阈值可在 `pipelines/factor_eval/config.yaml` 覆盖。

## 输出

见 `schemas/factor-report.schema.json`。

## Day2 Compose Executor 调用方式

Day 2 起，本 skill 通过统一 Compose executor 触发，不直接在调用方手写
`app.invoke()`。当前需要先注册已编译的 LangGraph app，再调用
`execute_compose_flow()`：

```python
from flows.factor_autoeval import build_workflow
from runner.compose_executor import execute_compose_flow, register_flow

register_flow(
    "factor",
    "factor:autoeval",
    build_workflow(),
    overwrite=True,
)

result = execute_compose_flow(
    group="factor",
    flow_name="factor:autoeval",
    input_data=factor_spec.model_dump(mode="json"),
)
```

返回值约定：

- `result["output_data"]` 是标准 `schemas.factor.FactorReport` dict。
- `result["artifacts"]` 包含生成的 factor report JSON 路径。
- `result["thread_id"]` 是本次 LangGraph checkpoint 线程 id。
- `result["state"]` 保留完整 final state，供 Day2 调试使用。

Day2 当前走 mock AutoEval 路径，用于证明 LangGraph Compose + Schema +
Artifact 闭环。真实 AutoFactorEvaluation 生产链路
`candidate_pool -> Gateway -> Assetization -> Purification -> Evaluation ->
tier2/tier3/tier4` 仍按 Day3 接入。checkpoint resume 目前还不是
`execute_compose_flow()` 的稳定接口，本 skill 不承诺统一 resume API。

## 跨组接口

- 评估通过的因子，向风控组提供统计公式（max_drawdown / VaR 计算口径）

## Day1 T4 Schema Review Alignment

本节由肖骥超补充，用于对齐 `docs/schema_review/01_ComposeTask.md` 和
`docs/schema_review/02_BlackboardState.md`。

- 输入 payload 是 `schemas.factor.FactorSpec`。
- 输出 payload 是 `schemas.factor.FactorReport`。
- 在 Compose 流中，本 skill 应作为 `ComposeTask[FactorSpec, FactorReport]` 执行。
- 若 AutoFactorEvaluation 的真实 HTTP/SDK 接口暂不可用，先使用
  `pipelines/factor_eval/README.md` 中的 mock response 跑通 schema path。
- 对 strategy / risk 的公开共享结果不能写 GROUP scope；应写 PROJECT scope，
  key 使用 `shared.factor_autoeval_results.<factor_name>`。
- 边界：T4 提供 `FactorReport` 和统计口径，不生成 `risk.json`，不替代
  `risk-gate`。

## AutoFactorEvaluation Invocation

根据 `D:\桌面\agent\factor_miner_usage.md`，AutoFactorEvaluation 当前不是
HTTP/SDK 常驻服务，正式入口是仓库根目录的 CLI pipeline：

```bash
python -m pipeline --all
python -m pipeline --gateway-only
python -m pipeline --assetization-only
python -m pipeline --purification-only
python -m pipeline --evaluation-only --ev-workers 4
AFVCONFIG=/path/to/config_dir python -m pipeline --all
```

本 skill 应将 `FactorSpec` 转换为候选因子 manifest，并写入：

```text
candidate_pool/{campaign_id}/{candidate_id}/manifest.json
```

其中 `candidate_id` 建议使用 `FactorSpec.name`。pipeline 完成后，从最终
`afv.json` 的 `Evaluation` 段和 Evaluation artifacts 读取结果，并映射为
`schemas.factor.FactorReport`。Pydantic `FactorReport` 是当前 source of truth；
旧的 `schemas/factor-report.schema.json` 仅作为 legacy JSON Schema artifact。

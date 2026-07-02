# factor_eval / AutoFactorEvaluation handoff

Owner: 肖骥超 / T4 model-factor-eval

AutoFactorEvaluation 的调用方式已由 `D:\桌面\agent\factor_miner_usage.md`
确认：它不是 7x24 常驻 HTTP 服务，也不是当前需要直接调用的 SDK。正式入口是
AutoFactorEvaluation 仓库根目录下的 `pipeline.py`，通过 CLI 单次执行或分阶段执行。

## Invocation

在 AutoFactorEvaluation 仓库根目录运行：

```bash
python -m pipeline --all
```

常用分阶段命令：

```bash
python -m pipeline --gateway-only
python -m pipeline --assetization-only
python -m pipeline --purification-only
python -m pipeline --evaluation-only --ev-workers 4
```

指定配置目录：

```bash
AFVCONFIG=/path/to/config_dir python -m pipeline --all
```

Worker 控制：

```bash
python -m pipeline --all --workers 4
python -m pipeline --all --gw-workers 4 --as-workers 4 --pu-workers 4 --ev-workers 2
```

Evaluation 的 worker 数必须大于 0。长时间无 Evaluation 结果时，可以用
`--ev-no-progress-timeout` 调整超时阈值。

## Input contract

QuantCode 侧用 `schemas.factor.FactorSpec` 表示 factor:autoeval 输入。提交到
AutoFactorEvaluation 时，需要把它转换成候选因子 manifest，并写入：

```text
candidate_pool/{campaign_id}/{candidate_id}/manifest.json
```

其中：

- `candidate_id` 建议使用 `FactorSpec.name`。
- `campaign_id` 使用 `FactorSpec.campaign_id`；为空时由调用方按批次生成。
- `formula` 写入 manifest 的表达式或 callable reference。
- `domain`、`frequency`、`operators`、复杂度信息用于 Gateway 校验。
- campaign 级公共元数据写入 `candidate_pool/{campaign_id}/config.json`。

示例 `FactorSpec`：

```json
{
  "name": "pb_roe_combo",
  "campaign_id": "campaign_2026q2",
  "formula": "tests.fixtures.sample_factor:pb_roe_combo",
  "domain": "equity",
  "frequency": "daily",
  "universe": "CSI1000",
  "operators": ["roe_ttm", "pb", "divide"],
  "estimated_runtime_seconds": 30,
  "date_range": {"start": "2023-01-01", "end": "2025-12-31"},
  "benchmark": "HS300",
  "forward_return_horizon": 5
}
```

## Pipeline stages

```text
candidate_pool
  -> Gateway
  -> Assetization
  -> Purification
  -> Evaluation
  -> tier2 / tier3 / tier4
```

阶段含义：

- Gateway：schema、算子白名单、未来函数、复杂度、去重。
- Assetization：生成 `factor_id` 并计算每日因子值。
- Purification：缺失填补、去极值、可选正交化。
- Evaluation：timeseries、indicator、label、route。

## Output contract

AutoFactorEvaluation 的关键结果来自最终 `afv.json` 的 `Evaluation` 段，以及
Evaluation 工作目录中的指标文件。

核心 `Evaluation` 结构示例：

```json
{
  "Evaluation": {
    "Label": "Evaluated",
    "eval_run_id": "...",
    "route_recommendation": "tier3b_satellite",
    "target_tier": "Tier3B",
    "horizons": [1, 5, 20],
    "key_metrics": {
      "rank_ic_mean": 0.01,
      "rank_ic_ir": 0.5,
      "turnover": 0.6
    },
    "tags": {
      "performance_tags": ["high_turnover"],
      "action_tags": ["needs_smoothing"],
      "semantic_label": "quality"
    },
    "admission_reason": "route_recommendation=tier3b_satellite"
  }
}
```

QuantCode 侧将该结果映射到 `schemas.factor.FactorReport`：

```text
Evaluation.key_metrics.rank_ic_mean -> FactorReport.ic_metrics.ic_mean
Evaluation.key_metrics.rank_ic_ir   -> FactorReport.ic_metrics.ir
Evaluation.key_metrics.turnover     -> FactorReport.turnover.monthly
Evaluation.eval_run_id              -> FactorReport.eval_run_id
Evaluation.route_recommendation     -> FactorReport.route_recommendation
Evaluation.target_tier              -> FactorReport.target_tier
Evaluation.horizons                 -> FactorReport.horizons
Evaluation.tags.*                   -> FactorReport performance/action/semantic fields
Evaluation.admission_reason         -> FactorReport.admission_reason
```

更细结果可从这些文件读取：

```text
indicator_output_h{horizon}/summary_scorecard.json
indicator_output_h{horizon}/metrics_matrix.parquet
indicator_output_h{horizon}/dev4_evaluation_summary.json
indicator_output_h{horizon}/metric_validation_report.json
label/tag_package.json
label/admission_decision.json
label/route_record.json
label/lifecycle_event.json
```

研究侧优先读：

- `summary_scorecard.json`
- `metrics_matrix.parquet`
- `dev4_evaluation_summary.json`
- `metric_validation_report.json`
- `admission_decision.json`
- `route_record.json`

## Acceptance

QuantCode runner 对 `FactorReport` 做本地门禁：

```text
abs(ic_metrics.ic_mean) >= 0.03
ic_metrics.ir >= 0.5
turnover.monthly <= 0.8
ic_metrics.t_stat >= 2.0
```

Public cross-group handoff should write this report to PROJECT-scope blackboard
under `shared.factor_autoeval_results.<factor_name>`.

## Server A smoke result

2026-07-02 已在 Server A `qs-data-ingest-hk-01` 上验证单因子评估入口：

```text
ssh xiaojichao@43.154.17.120
cd /srv/quant/repos/quantsociety_backend
/srv/quant/envs/quantsociety_backend/bin/python -m factor_layer.factor_evaluation.run_from_config --help
```

实际 smoke 使用合成 factor lake、合成 market parquet 和临时 YAML config，写入：

```text
/srv/quant/data/agent/data/tmp/xiaojichao_autoeval_smoke_20260702T005851Z/
```

输出目录：

```text
/srv/quant/data/agent/data/tmp/xiaojichao_autoeval_smoke_20260702T005851Z/evaluations/pb_roe_combo_smoke/day1_t4_smoke_eval
```

已确认生成：

```text
config_snapshot.yaml
daily_ic.parquet
daily_rank_ic.parquet
long_short_returns.parquet
manifest.json
quantile_backtest.parquet
quantile_period_returns.parquet
quantile_summary.parquet
summary.csv
summary.json
```

`summary.json` 核心结果：

```text
factor_id = pb_roe_combo_smoke
run_id = day1_t4_smoke_eval
primary_horizon = 1
horizon 1 rank_ic_mean = 1.0
horizon 1 top_minus_bottom_mean = 0.03
horizon 1 long_short_total_return = 0.19405229652900013
```

## Day 1 status

已确认：

```text
Server A SSH access = ok
factor_artifact_api healthz = ok
single-factor evaluation entrypoint = ok
synthetic run_from_config smoke = ok
QuantCode schema mapping = ok
```

仍未验证：

```text
candidate_pool -> Gateway -> Assetization -> Purification -> Evaluation -> tier2/tier3/tier4
```

原因：Server A 当前可见入口是 `factor_layer.factor_evaluation.run_from_config`；
完整 `candidate_pool` 总编排需要 AutoFactorEvaluation 对应仓库/配置或正式 pipeline
入口。当前 T4 已完成 Server A 单因子评估 smoke、调用方式确认、schema 对齐和结果映射口径。

# FactorSpec / FactorReport Schema 评审文档

> **Owner**: 肖骥超  
> **组**: factor  
> **模式**: Pattern 1 (Orchestrator-Worker) + Pattern 2 (Stateful Blackboard)  
> **状态**: Day 1 已对齐 AutoFactorEvaluation CLI 调用方式

---

## 一句话定义

> **FactorSpec 是 factor:autoeval 的输入契约，FactorReport 是 AutoFactorEvaluation 返回给 QuantCode 的标准化输出契约。**

两者作为 `ComposeTask[FactorSpec, FactorReport]` 的类型参数使用。

---

## FactorSpec 字段

| 字段 | 类型 | 必填 | 用途 |
|---|---|---|---|
| `name` | `str` | 是 | 因子稳定名称，如 `pb_roe_combo` |
| `campaign_id` | `str \| None` | 否 | AutoFactorEvaluation campaign 目录名 |
| `formula` | `str` | 是 | 公式字符串或 Python callable 引用，用于生成 manifest |
| `domain` | `str` | 否 | Gateway 使用的候选因子领域，默认 equity |
| `frequency` | `str` | 否 | Gateway 使用的候选因子频率，默认 daily |
| `universe` | `str` | 否 | 股票池，默认 `CSI1000` |
| `operators` | `list[str]` | 是 | 依赖的数据字段和算子，必须非空且唯一 |
| `estimated_runtime_seconds` | `int` | 是 | 预计 AutoEval 运行时间 |
| `date_range` | `DateRange` | 是 | 评估区间 |
| `benchmark` | `str` | 否 | 基准，默认 `HS300` |
| `forward_return_horizon` | `1/3/5/10/20` | 否 | forward return horizon，默认 5 日 |

---

## FactorReport 字段

| 字段 | 类型 | 必填 | 用途 |
|---|---|---|---|
| `factor_name` | `str` | 是 | 对应因子名 |
| `factor_version` | `str \| None` | 否 | 因子版本 |
| `evaluation_period` | `DateRange` | 是 | 评估区间 |
| `universe` | `str` | 是 | 股票池 |
| `ic_metrics` | `ICMetrics` | 是 | IC mean/std、IR、t-stat、IC method |
| `turnover` | `TurnoverMetrics` | 是 | 月度/年度换手 |
| `decay` | `DecayMetrics` | 否 | 1/3/5/10/20 日 IC decay |
| `layered_backtest` | `LayeredBacktest` | 否 | 分层回测摘要 |
| `verdict` | `pass/fail/marginal` | 是 | runner 结论 |
| `fail_reasons` | `list[str]` | 否 | 失败原因 |
| `eval_run_id` | `str \| None` | 否 | AutoFactorEvaluation Evaluation 段的 run id |
| `route_recommendation` | `str \| None` | 否 | Evaluation 路由建议 |
| `target_tier` | `str \| None` | 否 | 最终目标 tier |
| `horizons` | `list[int]` | 否 | Evaluation horizons |
| `performance_tags` | `list[str]` | 否 | Evaluation performance tags |
| `action_tags` | `list[str]` | 否 | Evaluation action tags |
| `semantic_label` | `str \| None` | 否 | Evaluation semantic label |
| `admission_reason` | `str \| None` | 否 | 入库/路由原因 |

---

## 与 ComposeTask 的集成

```python
from schemas import ComposeTask, FactorReport, FactorSpec, GroupName

task = ComposeTask[FactorSpec, FactorReport](
    task_id="T4",
    session_id="S0123456789abcdef",
    root_task_id="T4",
    group=GroupName.FACTOR,
    summary="Evaluate PB-ROE factor",
    input=FactorSpec(...),
)
```

Runner 或 `factor:autoeval` worker 完成后填充 `task.output = FactorReport(...)`。

---

## Blackboard 共享规则

GROUP scope 仍然硬隔离。需要给 strategy / risk 读取的公开结果必须写入 PROJECT scope，并使用 `shared.*` key：

```text
scope = PROJECT
key = shared.factor_autoeval_results.<factor_name>
written_by_group = factor
```

T4 不直接生成 `risk.json`，只提供 `FactorReport` 和统计口径，供 `risk-gate` 使用。

---

## AutoEval Day 1 调用方式确认

AutoFactorEvaluation 的调用方式已由 `D:\桌面\agent\factor_miner_usage.md` 确认：
它不是 7x24 常驻服务，当前正式入口是 AutoFactorEvaluation 仓库根目录下的
`pipeline.py`。

运行方式：

```bash
python -m pipeline --all
python -m pipeline --gateway-only
python -m pipeline --assetization-only
python -m pipeline --purification-only
python -m pipeline --evaluation-only --ev-workers 4
AFVCONFIG=/path/to/config_dir python -m pipeline --all
```

输入写入：

```text
candidate_pool/{campaign_id}/{candidate_id}/manifest.json
```

其中 `candidate_id` 建议使用 `FactorSpec.name`，`campaign_id` 来自
`FactorSpec.campaign_id` 或由调用方按批次生成。

输出读取：

```text
tier*/.../afv.json 的 Evaluation 段
indicator_output_h{horizon}/summary_scorecard.json
indicator_output_h{horizon}/metrics_matrix.parquet
indicator_output_h{horizon}/dev4_evaluation_summary.json
indicator_output_h{horizon}/metric_validation_report.json
label/admission_decision.json
label/route_record.json
```

当前 formal entry 是本地 batch process，不存在 HTTP job id polling。

## Server A smoke 验证

2026-07-02 已用 `xiaojichao` 登录 Server A，并验证：

```text
host = qs-data-ingest-hk-01
workspace = /srv/quant/data/agent
group = quant-agent
factor_artifact_api healthz = {"ok": true, "service": "factor_artifact_api"}
```

Server A 上可见的评估入口：

```text
/srv/quant/repos/quantsociety_backend/factor_layer/factor_evaluation/run_from_config.py
```

已用公共 venv 跑通合成数据 smoke：

```text
/srv/quant/envs/quantsociety_backend/bin/python
module = factor_layer.factor_evaluation.config_runner.run_from_config
tmp base = /srv/quant/data/agent/data/tmp/xiaojichao_autoeval_smoke_20260702T005851Z
output_dir = .../evaluations/pb_roe_combo_smoke/day1_t4_smoke_eval
result = summary.csv / summary.json / daily_ic.parquet / quantile_backtest.parquet 等产物生成成功
```

该 smoke 验证的是单因子评估 runtime，不等同于完整生产路由链路。
完整 `candidate_pool -> Gateway -> Assetization -> Purification -> Evaluation -> tier`
仍需正式 AutoFactorEvaluation pipeline 入口和配置。

---

## 测试覆盖

`tests/test_factor.py` 覆盖：

- `FactorSpec` 合法实例
- 必填字段和 date range 校验
- `FactorReport` 合法实例
- `ComposeTask[FactorSpec, FactorReport]`
- PROJECT scope + `shared.*` blackboard 共享
- Pydantic JSON Schema 导出
- AutoFactorEvaluation `Evaluation` 段到 `FactorReport` 的字段映射
- Server A 单因子评估 smoke 已跑通

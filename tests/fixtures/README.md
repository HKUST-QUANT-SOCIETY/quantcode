# Day5 Fixtures 终验说明（刘炽）

> 用途：标明各组 demo/fixture 的来源、是否真实抽样、降级项。  
> 对应 `Day5_TaskList.md` §7 验收「fixtures 齐全，降级项标注清楚」。

## 清单

| Fixture | 组 | 来源 | 真实性 | 降级/备注 |
|---------|----|------|--------|-----------|
| `pit_corpus_sample.json` | fundamental | 样例研报摘要（含故意未来文档 `DOC-LEAK-2026`） | 结构真实；正文为脱敏样例 | **种子写入本地 Chroma**；无 chromadb 时直接读 JSON |
| `strategy_backtest_result.json` | strategy | 候选信号样例（对齐 StrategySpec） | 字段真实；权重为演示值 | 真信号应来自 factor/model Blackboard |
| `gc_options_merged_sample.csv` | options | 对齐 `DataStructure.md` 的 GC 期权链样本 | 列真实；行为 mock/抽样 | 生产应换 `/srv/quant/shared_data/options/merged/gc_options/` |
| `factor_backtest_result.json` | factor | AutoEval 形态样例 | schema 对齐 | 真数来自 AutoEval API（肖骥超） |
| `risk_metrics_normal.json` / `breach.json` | risk | 风控双场景 | schema 对齐 | 真数来自 risk tools |
| `sample_model/model_spec.json` | model | ModelSpec 样例 | schema 对齐 | 真数来自 model PR 流 |
| `sample_pr.diff` / `sample_pr_real.diff` | model | PR diff 样例 | 文本样例 | 真 diff 来自 GitHub API |

## PIT 专用

`pit_corpus_sample.json` **必须**保留至少 1 条 `published_at` 晚于常见 `as_of_date` 的文档，用于验收 lookahead 过滤。

## Chroma

- 路径：`.quantcode/chroma_pit/`（gitignore 建议忽略）
- 首次 `pit_rag_search` 会把 fixture 文档 `add` 进 collection `fundamental_pit_corpus`
- 返回字段 `backend`: `chroma` | `fixture_json`

## 更新真实抽样时

1. 向基建/对应组要小样本（见 `docs/jerry_fixture_real_data.html`）
2. 替换上表文件，保持 schema 字段
3. 更新本 README 的「来源」列与日期

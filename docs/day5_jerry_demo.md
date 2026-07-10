# Day 5 Demo 指南 — 刘炽（strategy / fundamental / options）

> 对应 `docs/Day5_TaskList.md` §7 + Demo 场景 3（基本面研报）

## 快速跑通（无需 LLM）

三组完整 tool 链 + schema 校验 + artifact 落盘：

```bash
cd ~/Projects/quantcode-workspace/quantcode

# 全部三组
python3 scripts/demo_jerry_tracks.py --track all

# 单独一组
python3 scripts/demo_jerry_tracks.py --track strategy
python3 scripts/demo_jerry_tracks.py --track fundamental
python3 scripts/demo_jerry_tracks.py --track options

# JSON 输出（供 IDE / 脚本消费）
python3 scripts/demo_jerry_tracks.py --track all --json
```

## 产出 artifact 路径

| Track | Artifact | Schema |
|-------|----------|--------|
| strategy | `artifacts/strategy/multi_signal_csi1000/strategy_report.json` | `StrategyReport` |
| fundamental | `artifacts/research/2097_HK-2025-01-01/fundamental_bundle.json` | `PITResult` + `ResearchResult` |
| options | `artifacts/options/gc_vol_carry/options_risk.json` | `VolSurfaceResult` + `GreeksProfile` + `OptionsBacktestReport` |

## Demo 场景说明

### 场景 A — strategy（组合 PB-ROE + 动量）

1. `select_signals` — 从 fixture 候选信号筛选
2. `combine_signals` — 权重归一化
3. `run_strategy_backtest` — 产出 `StrategyReport`
4. `deploy_strategy` — 根据 verdict 决定是否部署

### 场景 B — fundamental（分析公司 X 估值）

1. `pit_rag_search` — **fixture 语料 + 强制 PIT**（`published_at <= as_of_date`）
2. `extract_financial` — 财务摘要
3. `dcf_valuation` — 每股公允价值
4. `render_report` — markdown + 可选 Typst PDF

**降级说明**：Chroma 向量库 Week 2 接入；当前用 `tests/fixtures/pit_corpus_sample.json`，含一条 `DOC-LEAK-2026` lookahead 文档会被过滤，demo 可现场展示 `filtered_count >= 1`。

### 场景 C — options（GC 期权 Greeks）

1. `build_vol_surface` — **Black-Scholes IV 二分法**（真实化，非 Day1 mock）
2. `calc_greeks` — 读取曲面 artifact，缩放 Greeks
3. `run_options_backtest_stub` — 回测 stub（Week 2 换真实引擎）

产出 `options_risk.json` = 曲面 + Greeks + 回测 bundle。

## OpenCode / IDE 触发（需 LLM）

```bash
python3 -m runner.demo_bridge --group strategy --skill strategy-compose \
  --task "组合 PB-ROE 与动量信号并回测"

python3 -m runner.demo_bridge --group fundamental --skill fundamental-compose \
  --task "分析蜜雪冰城 2097.HK 估值"

python3 -m runner.demo_bridge --group options --skill options-compose \
  --task "为 GC 构建波动率曲面并计算 Greeks"
```

MCP 按组暴露 tool：

```bash
QUANTCODE_GROUP=options python3 -m quantcode.mcp_server
```

## 测试

```bash
python3 -m pytest tests/test_day5_jerry_demos.py tests/test_schema_final_validation.py \
  tests/test_options_tools.py tests/test_strategy_tools.py tests/test_fundamental_tools.py -q
```

## Day 5 验收对照

- [x] strategy/fundamental/options 三组 demo 跑通，artifact 过 schema
- [x] fundamental PIT 时点安全可验（`filtered_count` + 无 `DOC-LEAK-2026`）
- [x] fixtures 齐全（`strategy_backtest_result.json`, `pit_corpus_sample.json`, `gc_options_merged_sample.csv`）
- [x] 降级项明确标注（Chroma / backtest stub / Typst fallback）

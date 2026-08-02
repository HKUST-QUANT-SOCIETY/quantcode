# Day 5 Demo 指南 — 刘炽（strategy / fundamental / options）

> 对应 `docs/Day5_TaskList.md` §7 + Demo 场景 3（基本面研报）

## 验收入口（推荐）

```bash
cd ~/Projects/quantcode-workspace/quantcode
python3 scripts/accept_jerry_day5.py
```

覆盖：fixtures 终验、三组 schema artifact、Chroma PIT、AgentRunner 人审 interrupt/resume、strategy/options 多步 tool 链、**demo 存档 packs**。

## 快速跑通（无需 LLM）

```bash
python3 scripts/demo_jerry_tracks.py --track all
# 默认会写入 archives/<archive_id>/（可用 --no-archive 跳过）

python3 scripts/archive_pack.py --track all
python3 scripts/archive_pack.py --list
```

## Demo 存档（archives/）

`artifacts/` 是临时工作区（gitignore）；汇报/复盘用 **archive pack**：

```
archives/<timestamp>-<group>-.../
  manifest.json
  README.md
  artifacts/     # 本轮产物拷贝
  meta/input.json
  meta/acceptance.json   # accept 脚本打包时有
```

| Track | Artifact | Schema |
|-------|----------|--------|
| strategy | `artifacts/strategy/multi_signal_csi1000/strategy_report.json` | `StrategyReport` |
| fundamental | `artifacts/research/2097_HK-2025-01-01/fundamental_bundle.json` | `PITResult` + `ResearchResult` |
| options | `artifacts/options/gc_vol_carry/options_risk.json` | `VolSurfaceResult` + `GreeksProfile` + `OptionsBacktestReport` |

研报正文：`artifacts/research/2097HK-2025-01-01.md`（必填内容）+ 同名 `.pdf`（本机有 typst 时编译 filled Typst）。

## Demo 场景说明

### 场景 A — strategy

`select_signals` → `combine_signals` → `run_strategy_backtest` → `deploy_strategy` → `StrategyReport`

### 场景 B — fundamental（分析公司 X 估值）

1. `pit_rag_search` — **Chroma PersistentClient**（`.quantcode/chroma_pit`，fixture 种子）；无 chromadb 时降级 `fixture_json`
2. 强制 PIT：`published_at <= as_of_date`（`DOC-LEAK-2026` 计入 `filtered_count`）
3. `extract_financial` → `dcf_valuation` → `render_report`（filled MD/PDF）
4. `request_human_review` — AgentRunner **真 interrupt**，`resume(decision=approve|reject)` 后 `mark_task_done`

### 场景 C — options

`build_vol_surface`（BS IV）→ `calc_greeks` → `run_options_backtest_stub` → OptionsRisk bundle

## 降级标注

见 `tests/fixtures/README.md`。诚实降级项：

| 项 | 现状 |
|----|------|
| Chroma 语料 | 本地 PersistentClient + fixture 种子（非远程生产库） |
| extract/DCF | 简化 stub 财务，非完整卖方模型 |
| options backtest | stub 引擎 |
| strategy 信号 | fixture 候选，非实时 Blackboard |

## OpenCode / IDE（需 LLM）

```bash
python3 -m runner.demo_bridge --group fundamental --skill fundamental-compose \
  --task "分析蜜雪冰城 2097.HK 估值"
```

## 测试

```bash
python3 -m pytest \
  tests/test_day5_jerry_demos.py \
  tests/test_schema_final_validation.py \
  tests/test_fundamental_tools.py \
  tests/test_fundamental_human_gate.py -q
```

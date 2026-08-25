<div align="center">
  
# QuantCode

**Agent-driven quantitative research platform where six specialized teams compose through schema contracts**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-589%20passed-brightgreen.svg)](tests/)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)]()

[Quick Start](#quick-start) • [Architecture](#architecture) • [Six Workflows](#six-workflows) • [Documentation](#documentation) • [Contributing](#contributing)

</div>

---

## What is QuantCode?

QuantCode is an **agent orchestration platform** for quantitative investment research. Six domain teams (Factor, Model, Risk, Fundamental, Strategy, Options) each work through their own ReAct-style agent — no manual handoffs, no Slack threads asking "did you finish the backtest?" The platform enforces **schema contracts** at every boundary: your factor submission must validate against `FactorSpec`, your model PR triggers automatic `RiskProfile` generation, and cross-group state flows through a type-safe Blackboard.

**Core thesis**: Replace "people negotiating over Slack" with "machines validating against schemas." Replace "does this look okay?" with "`assert` pass/fail + deterministic gates."

Built on a fork of [OpenCode](https://github.com/anomalyco/opencode), cherry-picking modules from MimoCode (Memory, Checkpoint, Subagent orchestration), and adding six vertical Compose flows for quant workflows.

---

## News

| Date | Event |
|------|-------|
| 2026-07-16 | 🎯 **Beta Release** — 589/597 tests passing, 6-group E2E demos functional |
| 2026-07-15 | 🔐 Risk Gate E2E: GitHub PR comments with auto-generated `RiskProfile` |
| 2026-07-10 | 🧪 Factor tools migrated from stub → real LLM (DeepSeek) for `gen_schema` + `match_main` |
| 2026-07-09 | 📐 HumanGate deterministic routing engine (Pattern 5: interrupt-resume) |
| 2026-07-05 | 🏗️ AgentRunner ReAct engine + self-built StateGraph (no `create_react_agent`) |

---

## Architecture

### Any domain → typed output

<div align="center">
<img src="docs/images/quantcode_flow.png" width="900" alt="QuantCode flow: 6 groups → AgentRunner → Schema validation → Blackboard → Production" />
</div>

```
User intent → Group-specific AgentRunner → Tool chain → Schema validation → Output artifact
     ↓
  Factor: match_main → gen_schema → autoeval → RiskProfile
  Model: read_pr → extract_metadata → generate_model_spec → (triggers Risk flow)
  Risk: read_blackboard → calc_risk → generate_risk_profile → check_gate → HumanGate
     ↓
  All outputs: JSON artifacts under artifacts/{group}/ + optional PR comments
```

**Three production patterns:**

1. **Pattern 1 (Push)** — Factor group submits FactorSpec → AutoEval returns IC/IR → merges to main if IR > threshold
2. **Pattern 2 (Pull + Human Gate)** — Model group opens PR → Risk agent auto-generates RiskProfile → human approves if max_drawdown > 15%
3. **Pattern 5 (Interrupt-Resume)** — Any tool can `interrupt()` mid-flow for human decision, then `resume(decision=...)` to continue

> **Don't pre-define DAGs. Let agents route.**  
> The platform provides deterministic routing (`route_next_step`) based on state fingerprints, loop detection, and risk thresholds — but the **sequence** of tool calls emerges from LLM reasoning, not hardcoded graphs.

**Key primitives:**

- **AgentRunner** — Self-built StateGraph ReAct engine (not `create_react_agent`). Loads group-specific tools, injects skill markdown as system prompt, routes via `tool_routing_edge` → `route_next_step`.
- **ToolRegistry** — Global singleton. Each group's `_register.py` declares tools at import time. Tests use `importlib.reload()` to re-register after other tests clear the registry.
- **Blackboard** — SQLite-backed shared state with 5-scope isolation (SESSION/THREAD/GROUP/PROJECT/GLOBAL). Model group writes `ModelSpec` to PROJECT scope → Risk group reads it.
- **Memory** — FTS5 full-text search + 5-scope ACL. Factor agent can't read Model group's memory.
- **Schema contracts** — Every artifact validates against Pydantic models in `schemas/`. `FactorSpec`, `RiskProfile`, `StrategyReport`, etc.

---

## Six Workflows

Each group has a vertical Compose flow — from raw idea to production-ready artifact.

### 1. Factor (Owner: 肖骥超)

**Goal**: Automate factor development from idea to AutoEval → main branch merge.

**Tools**: `match_main`, `gen_schema`, `autoeval`

**Flow**:
```python
idea = "高ROE低PB价值因子"
  ↓ match_main (LLM) → finds similar factors in main branch
  ↓ gen_schema (LLM) → generates FactorSpec with formula/fields/rebalance
  ↓ autoeval (API) → submits to AutoEval service, returns IC/IR/turnover
  ↓ Schema validation → artifacts/factor/{name}_eval.json
  ↓ If IR > 1.5 && IC > 0.03 → auto-merge to main
```

**Demo**: `python runner/jerry_demos.py --track factor`

**Status**: ✅ `match_main` + `gen_schema` using real DeepSeek LLM; `autoeval` falls back to mock (real AutoEval service TBD)

---

### 2. Model (Owner: 陈镇鸿)

**Goal**: PR metadata extraction → cross-group handoff to Risk for gate check.

**Tools**: `read_pr`, `extract_metadata`, `generate_model_spec`, `write_blackboard`

**Flow**:
```python
PR #42 opened → read_pr → extract model type/params from diff
  ↓ generate_model_spec → {"model_name": "pb_roe_ranker", "model_type": "ml", ...}
  ↓ write_blackboard(scope=PROJECT) → triggers Risk flow
  ↓ Risk agent reads ModelSpec → calculates risk_metrics → generates RiskProfile
  ↓ check_gate → HumanGate if max_drawdown > 15%
  ↓ write_pr_comment → posts RiskProfile JSON to PR
```

**Cross-group contract**: `ModelSpec` schema (must include `model_name`, `expected_sharpe`, `capacity_estimate`).

---

### 3. Risk (Owner: 杨欣琳)

**Goal**: Automated risk gate for model PRs — generate `RiskProfile`, check thresholds, trigger HumanGate if needed.

**Tools**: `read_blackboard`, `calc_risk`, `generate_risk_profile`, `check_gate`, `write_pr_comment`, `request_human_review`

**Flow**:
```python
ModelSpec in Blackboard → calc_risk → {max_drawdown, tail_risk_var_99, position_limit}
  ↓ generate_risk_profile → enriched RiskProfile with thresholds
  ↓ check_gate → {requires_human: true, reasons: ["max_drawdown", "tail_risk_var_99"]}
  ↓ route_next_step detects risk_profile + threshold breach → HUMAN_GATE
  ↓ _human_gate_node → interrupt() → waits for Command(resume={"decision": "approve"})
  ↓ write_pr_comment → GitHub PR comment with full RiskProfile JSON
```

**HumanGate**: Deterministic routing — if `risk_metrics` exceed thresholds AND `risk_profile` exists, route to `human_gate` node. Agent pauses until user resumes with `approve` or `reject`.

**Demo**: `pytest tests/test_risk_react_ready.py -v`

**Production**: GitHub Actions workflow calls `run_agent(group="risk", task="Run risk gate for PR #{pr_number}")`

---

### 4. Fundamental (Owner: Lead)

**Goal**: Point-in-time safe research report generation (prevent lookahead bias in backtests).

**Tools**: `pit_rag_search`, `extract_financial`, `dcf_valuation`, `render_report`

**PIT safety**: Chroma vector DB with timestamp filter — 2023-01-01 backtest only retrieves docs from ≤ 2022-12-31.

---

### 5. Strategy (Owner: TBD)

**Goal**: Signal combination → backtest → deploy gate.

**Tools**: `select_signals`, `combine_signals`, `run_strategy_backtest`, `deploy_strategy`

**Gate**: `deploy_strategy` always requires HumanGate approval.

---

### 6. Options (Owner: 刘炽)

**Goal**: Volatility surface construction + Greeks calculation for options strategies.

**Tools**: `build_vol_surface`, `calc_greeks`, `run_options_backtest`

**Output**: `artifacts/options/{symbol}_vol_surface.png` + GreeksProfile JSON

---

## Quick Start

### Prerequisites

- Python 3.12+
- Bun (for OpenCode desktop)
- Git

### One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/HKUST-QUANT-SOCIETY/quantcode/main/scripts/setup.sh | bash
```

**Or manual:**

```bash
# 1. Clone repos
git clone https://github.com/HKUST-QUANT-SOCIETY/quantcode.git
git clone https://github.com/HKUST-QUANT-SOCIETY/opencode.git

# 2. Install QuantCode
cd quantcode
pip install -e .

# 3. Configure API keys
cp config.example.json config.json
# Edit config.json: add your DeepSeek API key

# 4. Install OpenCode desktop
cd ../opencode
bun install

# 5. Start desktop
cd ../quantcode
./scripts/start-quantcode.sh
```

### Conversational path

Open QuantCode desktop → select your group → type:

```
我想开发一个基于ROE和PB的价值因子
```

Agent auto-runs: `match_main` → `gen_schema` → `autoeval` → shows you IC/IR results.

### Library path

```python
from tools.registry import registry

# Factor group
result = registry.call("gen_schema", {
    "idea": "momentum factor using 20-day return",
    "match_result": {"main_branch": "momentum", "similar_factors": []}
})
# Returns: {"name": "momentum_20d", "formula": "close/close.shift(20)-1", ...}

# Risk group
risk = registry.call("calc_risk", {
    "model_spec": {"model_name": "test", "expected_sharpe": 1.5},
    "scenario": "high_risk"
})
# Returns: {"max_drawdown": 0.22, "tail_risk_var_99": 0.085, ...}
```

### Run E2E demos

```bash
# All 6 groups
python -m pytest tests/test_day5_jerry_demos.py::test_day5_all_demos -v

# Individual tracks
python runner/jerry_demos.py --track strategy
python runner/jerry_demos.py --track fundamental
python runner/jerry_demos.py --track options
```

---

## Testing

```bash
# Full suite (589 tests)
pytest

# Specific group
pytest tests/test_risk_react_ready.py -v

# With real LLM (requires DEEPSEEK_API_KEY)
QUANTCODE_FACTOR_USE_REAL_LLM=1 pytest tests/test_factor_tools.py -v
```

**Test status**: 589 passed, 8 skipped (as of 2026-07-16). The 8 skipped tests require real LLM API access.

**Coverage**: AgentRunner (ReAct engine), tool registry, Blackboard (5-scope isolation), Memory (FTS5), routing logic (loop detection + risk gates), HumanGate (interrupt-resume), cross-group handoff (Model→Risk).

---

## Documentation

- **[User Manual](docs/USER_MANUAL.md)** — End-to-end guides for all 6 groups
- **[Architecture Spec](docs/Architecture_Spec.md)** — System design, Pattern 1/2/5, state management
- **[Module Architecture](docs/MODULE_ARCHITECTURE.md)** — 15 modules documented (1234 lines)
- **[Testing Guide](TEST_GUIDE.md)** — How to write tests, mock LLMs, fixture patterns (745 lines)
- **[Multi-Agent Review](docs/MULTI_AGENT_REVIEW.md)** — Reviewer matrix, physical gates, fixed Server B runtime, and rollout
- **[PRD](docs/PRD.md)** — Product requirements, acceptance criteria

---

## In Production

**Target deployment**: HKUST QUANT SOCIETY internal platform (12-18 users across 6 groups).

**Current stage**: Beta — full E2E demos functional, 97.6% test pass rate, missing pieces:
- AutoEval service endpoint (factor group blocked on real API)
- Chromadb integration (fundamental group PIT RAG)
- Dream/Distill automation (knowledge extraction from agent traces)

**Production readiness estimate**: 4-6 weeks to GA per [product evaluation](https://github.com/HKUST-QUANT-SOCIETY/quantcode/issues/X).

---

## Roadmap

- [ ] **AutoEval service integration** — Real factor evaluation API (currently mock)
- [ ] **Multi-agent workflows** — Parallel agent orchestration for large-scale tasks
- [ ] **Token budget management** — User-controlled token limits ("+500k" directive)
- [ ] **Distill automation** — Extract reusable patterns from successful agent runs → new tools
- [ ] **Long-context handling** — Custom reducer for 10h+ agent sessions
- [ ] **Monitoring dashboard** — Real-time agent status, token consumption, error rates

---

## Contributing

**Agent-first workflow** (recommended):

Open the QuantCode desktop → type:

```
/implement add a new tool for calculating Fama-French 3-factor exposures
```

The Model agent will:
1. Generate `tools/factor/fama_french.py` with ToolDef
2. Register in `tools/factor/_register.py`
3. Write unit tests in `tests/test_fama_french.py`
4. Run tests and fix until green
5. Create PR with summary

**Manual workflow**:

```bash
# 1. Create feature branch
git checkout -b feat/your-feature

# 2. Make changes
# 3. Add tests (test coverage must not decrease)
pytest tests/test_your_feature.py

# 4. Commit with conventional commits format
git commit -m "feat(factor): add Fama-French 3-factor tool"

# 5. Push and open PR
git push origin feat/your-feature
gh pr create
```

> **IMPORTANT**: Ready internal PRs trigger both the product Risk Gate and repository-wide Multi-Agent Review. The review workflow is loaded from `main`, and its head-bound `Quant Review Gate` status reports failure when either physical or agent review does not complete. On the current GitHub Free/private-repository plan this status is advisory; see [`docs/MULTI_AGENT_REVIEW.md`](docs/MULTI_AGENT_REVIEW.md) before treating it as an enforced merge gate. Risk threshold changes may additionally pause at HumanGate for a human decision.

**Code style**: Black (line length 100), Ruff (target py312), type hints required.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgements

Built by the HKUST QUANT SOCIETY Agent Group (6 people):
- **Lead**: Hendrix Chen (chenyuanheng0127@gmail.com)
- **Factor**: 肖骥超
- **Model**: 陈镇鸿
- **Risk**: 杨欣琳
- **Fundamental**: Lead
- **Options**: 刘炽

**Technology stack**:
- [OpenCode](https://github.com/anomalyco/opencode) — Desktop shell fork
- [LangGraph](https://github.com/langchain-ai/langgraph) — StateGraph orchestration
- [LangChain](https://github.com/langchain-ai/langchain) — Tool abstractions
- [DeepSeek](https://www.deepseek.com/) — LLM for schema generation and matching
- Cherry-picked from [MimoCode](https://github.com/MimoCode/mimocode): Memory, Checkpoint, Subagent modules

---

<div align="center">
  
**[⬆ Back to Top](#quantcode)**

Made with ☕ by the HKUST QUANT SOCIETY Agent Group

</div>

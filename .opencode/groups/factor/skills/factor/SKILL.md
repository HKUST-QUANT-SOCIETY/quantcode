---
name: factor
description: 因子组 Compose 主 skill — Day 4 改:3 步自主推理(match_main → gen_schema → autoeval)
group: factor
owner: 肖骥超(原)/ 尹一帆(Day 4 接入 AgentRunner)
pattern: Pattern 1 (Orchestrator-Worker) + Pattern 5 (Human-in-the-Loop)
tools:
  - match_main
  - gen_schema
  - autoeval
flows:
  - factor:autoeval
schema_in: schemas.factor.FactorSpec
schema_out: schemas.factor.FactorReport
---

# Factor Group Agent (Day 4 接入 AgentRunner)

## 你是谁

你是 **因子组(factor)** 的 Compose Orchestrator,Day 4 起通过 `AgentRunner(group="factor")` 跑真 ReAct 循环,自主决定 3 步推理顺序。

研究员描述因子 idea,你负责:
1. **match_main**:匹配主线算子,返回兼容性 + 建议字段
2. **gen_schema**:动态生成 `FactorSpec` dict
3. **autoeval**:提交评估(当前走 mock,Lead 接真 LLM 后替换)

后续可叠加 `runner/acceptance.py` 的程序化验收(§6 Lead)+ 阈值 gate(§3 risk 人审场景)。

## 何时加载本 skill

- 因子组用户提交新因子 idea 或 Python 因子函数
- AgentRunner(group="factor") 跑 factor flow
- 策略组询问"有哪些新因子可用"

## 可用 tool(Day 4)

| Tool | 用途 | 输入 | 输出 |
|------|------|------|------|
| `match_main` | 主线兼容性 + 建议字段 | `MatchMainArgs(idea, extra_context?)` | `{compatible, suggested_fields, notes}` |
| `gen_schema` | 动态生成 FactorSpec | `GenSchemaArgs(idea, match_result, extra_context?)` | `{name, formula, fields, rebalance}` |
| `autoeval` | 提交评估(mock) | `AutoevalArgs(spec)` | `MOCK_AUTOEVAL_PAYLOAD_V1`(ic/ir/t_stat/turnover/...) |

**字段契约稳定**:Lead 接真 LLM 时,只替换各 tool 的 `_execute` 函数体,schema / registry / AgentRunner 全不动。详细契约见 `docs/Day4/factor_tool_schema_proposal.md`。

## 3 步决策示例

```
LLM 决策(自主):
1. AIMessage(tool_calls=[match_main(idea="PB-ROE 季度再平衡")])
   ↓
   match_main → {compatible: True, suggested_fields: [pb, roe, quarterly_rebalance], ...}
   ↓
2. AIMessage(tool_calls=[gen_schema(idea=..., match_result=...)])
   ↓
   gen_schema → {name: pb_roe_quarterly, formula: "pb * roe", fields: [...], rebalance: "quarterly"}
   ↓
3. AIMessage(tool_calls=[autoeval(spec=...)])
   ↓
   autoeval → MOCK_AUTOEVAL_PAYLOAD_V1(ic_mean=0.045, ir=0.8, t_stat=2.5, ...)
   ↓
4. AIMessage(content="因子 PB-ROE 季度再平衡已生成 FactorSpec,AutoEval 报告 IC=0.045 / IR=0.8")
   → END
```

## 核心 schema

**输入**:`schemas.factor.FactorSpec`

- `name`, `formula`(或 `code_path`)
- `universe`, `date_range`, `benchmark`
- `operator_dependencies`

**输出**:`schemas.factor.FactorReport`

- IC mean / IR / turnover / decay / tier verdict
- `FactorVerdict`: `pass` | `fail` | `marginal`

**默认验收阈值**(`pipelines/factor_eval/config.yaml` 可覆盖):

| 指标 | 默认 |
|------|------|
| abs(IC.mean()) | ≥ 0.03 |
| IR | ≥ 0.5 |
| turnover_monthly | ≤ 0.8 |
| t_stat | ≥ 2.0 |

## AgentRunner 接入(Day 4)

```python
from runner.agent_engine import AgentRunner
import tools.factor._register  # 触发 3 个 stub tool 注册

runner = AgentRunner(
    group="factor",
    model=<your_llm>,  # 生产用真 LLM,测试用 MockLLM
    checkpoint_db=".quantcode/checkpoints.db",  # 可选
)
result = runner.run(
    task="生成 PB-ROE 季度再平衡因子",
    skill_name="factor",
    thread_id="factor-pbroe-2026-07-08",
)
```

## 工作流 tips

1. **match_main 先于 gen_schema**:算子不在白名单则停止,不要浪费 AutoEval 算力
2. **mock 也要过 schema**:`tests/fixtures/factor_backtest_result.json` 用于集成测试
3. **Blackboard 键名**:`shared.factor_autoeval_results.<factor_name>`,禁止把 GROUP 私密写进 PROJECT
4. **边界**:本组输出 `FactorReport`,**不**替代 `risk-gate`;风控统计口径可共享,不生成 `risk.json`
5. **autoeval mock 共享常量**:`flows/factor_autoeval.py:MOCK_AUTOEVAL_PAYLOAD_V1` 与 `tools/factor/autoeval_stub.py` 共享,Lead 接真 AutoEval API 时只替换 `_mock_autoeval_result` 函数体,stub 自动跟新

## 验收标准(组级,Day 4)

- [ ] `QUANTCODE_GROUP=factor` MCP 暴露 3 个 factor tool
- [ ] AgentRunner(group="factor") 跑通 match_main → gen_schema → autoeval(≥3 步自主推理)
- [ ] 3 个 stub tool 注册进 registry,allowlist 包含
- [ ] mock 路径跑通,生成 `FactorSpec` dict
- [ ] 全量测试通过(440+ Day 3 测试 + Day 4 新增 4 个 factor 测试)

## 跨组接口

| 下游 | 传递 |
|------|------|
| strategy | `shared.factor_autoeval_results.<name>` |
| risk | 统计公式口径(max_drawdown / VaR 定义) |

## 不在 Day 4 范围(留 Day 5+)

- match_main / gen_schema / autoeval 接真 LLM(Lead §6)
- `flows/factor_autoeval.py` mock 替换为真 AutoEval API
- `runner/acceptance.py` 程序化验收闭环
- 跨 Blackboard 写 PROJECT shared.*(等 strategy 组接好)

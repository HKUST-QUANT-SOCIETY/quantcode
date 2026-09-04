# QuantCode 测试指南

> **目的**：系统化测试QuantCode的各个层次，确保Day 5 demo可靠性
> **最后更新**：2026-07-15（Lead）

---

## 🎯 测试层次（从底到顶）

### Level 1: 单元测试（597个测试）
测试各模块独立功能，无外部依赖。

```bash
# 运行全部单元测试
python -m pytest -v

# 快速检查（只运行失败的）
python -m pytest --lf

# 查看覆盖率
python -m pytest --cov=runner --cov=tools --cov=flows --cov=schemas --cov-report=html

# 按组测试
python -m pytest tests/test_risk_*.py -v     # Risk组
python -m pytest tests/test_factor_*.py -v   # Factor组
python -m pytest tests/test_model_*.py -v    # Model组
python -m pytest tests/test_strategy_*.py -v # Strategy组
python -m pytest tests/test_fundamental_*.py -v # Fundamental组
python -m pytest tests/test_options_*.py -v  # Options组
```

**验收标准**：全部通过（597/597）

---

### Level 2: 工具集成测试
测试各组工具注册和基本调用。

```bash
# 测试工具注册
python -m pytest tests/test_*_tools.py -v

# 测试MCP暴露
QUANTCODE_GROUP=risk python -c "
from quantcode.mcp_server import list_tools
tools = list_tools()
print(f'Risk组暴露 {len(tools)} 个工具')
assert len(tools) > 0
"

# 测试6组工具
for group in risk model factor strategy fundamental options; do
  echo "Testing $group tools..."
  QUANTCODE_GROUP=$group python -c "from quantcode.mcp_server import list_tools; print(len(list_tools()))"
done
```

**验收标准**：每组至少暴露3个工具

---

### Level 3: Agent引擎测试
测试AgentRunner的ReAct循环。

```bash
# 测试基础ReAct
python -m pytest tests/test_agent_engine_basic.py -v

# 测试HumanGate
python -m pytest tests/test_human_gate.py -v

# 测试routing逻辑
python -m pytest tests/test_routing.py -v

# 测试MCP工具入口
python -m pytest tests/test_agent_mcp_tool.py -v
```

**验收标准**：
- ReAct能自主推理≥3步
- HumanGate正确interrupt/resume
- Routing决策符合预期

---

### Level 4: 端到端流程测试
测试完整的业务流程（真实场景）。

#### 4.1 Factor组E2E

```bash
# 测试factor ReAct readiness
python -m pytest tests/test_factor_agent_flow.py -v

# 手动测试（使用stub）
python -c "
from runner.agent_engine import AgentRunner
from runner.llm_provider import create_deepseek_llm

runner = AgentRunner(
    group='factor',
    model=create_deepseek_llm(),
    max_iterations=10,
)
result = runner.run(
    task='生成PB-ROE季度再平衡因子',
    skill_name='factor',
    thread_id='test-factor-e2e',
)
print('Status:', result.get('status'))
print('Artifacts:', result.get('artifacts'))
"
```

#### 4.2 Risk组E2E

```bash
# 测试risk ReAct + HumanGate
python -m pytest tests/test_risk_react_ready.py -v
python -m pytest tests/test_risk_github_e2e.py -v

# 手动测试人审场景
python -c "
from runner.agent_engine import AgentRunner
from runner.llm_provider import create_deepseek_llm

runner = AgentRunner(group='risk', model=create_deepseek_llm())
result = runner.run(
    task='评估 ModelSpec: max_leverage=5.0',
    skill_name='risk-gate',
    thread_id='test-risk-gate',
)
print('Status:', result.get('status'))
print('HumanGate:', result.get('gate'))
"
```

#### 4.3 Model组E2E

```bash
# 测试model→risk跨组流
python -m pytest tests/test_model_agent_flow.py -v

# 需要GitHub token
export GITHUB_TOKEN="ghp_..."
python -c "
from runner.agent_engine import AgentRunner
from runner.llm_provider import create_deepseek_llm

runner = AgentRunner(group='model', model=create_deepseek_llm())
result = runner.run(
    task='读取PR #29并生成ModelSpec',
    skill_name='model-pr-submit',
    thread_id='test-model-pr',
)
print('ModelSpec:', result.get('output_data'))
"
```

#### 4.4 Strategy/Fundamental/Options组

```bash
# 测试通用AgentRunner路径
python -m pytest tests/test_strategy_agent_flow.py -v
python -m pytest tests/test_fundamental_agent_flow.py -v
python -m pytest tests/test_options_agent_flow.py -v
```

**验收标准**：
- 每组至少一个完整流程通过
- 产出artifact通过schema校验
- HumanGate场景能正确暂停/恢复

---

### Level 5: IDE集成测试
测试OpenCode IDE与Python后端的集成。

#### 5.1 MCP Server启动

```bash
# 启动6个MCP server（各自终端）
QUANTCODE_GROUP=risk python -m quantcode.mcp_server
QUANTCODE_GROUP=model python -m quantcode.mcp_server
QUANTCODE_GROUP=factor python -m quantcode.mcp_server
QUANTCODE_GROUP=strategy python -m quantcode.mcp_server
QUANTCODE_GROUP=fundamental python -m quantcode.mcp_server
QUANTCODE_GROUP=options python -m quantcode.mcp_server
```

#### 5.2 OpenCode IDE启动

```bash
cd ../opencode
git checkout feat/quantcode-day5-ui
bun install
bun dev
```

#### 5.3 IDE功能验收

在浏览器中测试（http://localhost:5173）：

- [ ] `/compose "测试PB-ROE因子"` 能触发factor Agent
- [ ] 主对话区显示流式推理过程
- [ ] 右侧面板显示QuantCode Tab
- [ ] 六面板可见（Compose/任务树/HumanGate/Schema/Memory/Resume）
- [ ] HumanGate场景：高风险暂停 → 面板显示thread_id → approve后恢复
- [ ] 切换组（QUANTCODE_GROUP环境变量）后UI正确更新

---

### Level 6: Demo场景测试
测试investor demo的4个关键场景。

#### 场景1：因子自主推理（factor组）

```bash
/compose "生成PB-ROE季度再平衡因子"
```

**预期**：
1. match_main → compatible=true, suggested_fields=[pb, roe, quarterly_rebalance]
2. gen_schema → FactorSpec生成
3. autoeval → mock结果（IC/IR/turnover指标）
4. 产出FactorReport artifact

#### 场景2：模型风控人审（model→risk跨组）

```bash
/compose "读取PR #29并评估风险"
```

**预期**：
1. model组：read_pr → extract_metadata → generate_model_spec
2. model组：trigger_risk_flow 写Blackboard
3. risk组：自动触发 → calc_risk → 超阈值 → interrupt暂停
4. 人工输入：`approve`
5. risk组：write_pr_comment 真写GitHub评论

#### 场景3：策略组合（strategy组）

```bash
/compose "从因子池选择pb_roe和mom20，组合回测"
```

**预期**：
1. select_signals → 两个因子
2. combine_signals → 权重分配
3. run_strategy_backtest → StrategyReport

#### 场景4：死循环检测

```bash
/compose "重复调用同一个工具10次"
```

**预期**：
- 第5次重复后自动中止
- 返回abort状态
- execution_trace显示loop_detected

---

## 🚨 已知问题清单

根据Day5_Feature_Checklist.md，以下是已知降级项：

1. **factor autoeval**：使用mock返回，真API待接入
2. **fundamental/strategy/options tools**：部分stub
3. **truncate_node**：demo不触发，Week 2补
4. **Distill**：原型级，识别≥1 pattern即达标
5. **Memory浏览器**：前端直接读SQLite，Week 2补MCP只读工具

---

## 📊 测试报告模板

完成测试后，生成报告：

```bash
# 生成测试报告
python -m pytest --html=test_report.html --self-contained-html

# 覆盖率报告
python -m pytest --cov=runner --cov=tools --cov=flows --cov=schemas --cov-report=html

# 手动填写
cat > DEMO_CHECKLIST.md << 'EOF'
# QuantCode Demo验收清单

## Level 1: 单元测试
- [x] 597/597 passed

## Level 2: 工具注册
- [x] 6组工具全部暴露

## Level 3: Agent引擎
- [x] ReAct循环正常
- [x] HumanGate正确interrupt/resume

## Level 4: E2E流程
- [x] Factor组：3步自主推理
- [x] Risk组：人审场景通过
- [x] Model组：跨组流触发成功
- [x] Strategy/Fundamental/Options：通用路径通过

## Level 5: IDE集成
- [ ] /compose命令触发成功
- [ ] QuantCode Tab可见
- [ ] 六面板显示正常
- [ ] HumanGate UI对齐

## Level 6: Demo场景
- [ ] 场景1：因子自主推理
- [ ] 场景2：模型风控人审
- [ ] 场景3：策略组合
- [ ] 场景4：死循环检测

## 已知问题
- factor autoeval使用mock
- 部分工具为stub（已标注）
EOF
```

---

## 🔧 常见问题排查

### 问题1：测试失败 "No module named 'langchain_openai'"

```bash
pip install langchain-openai
```

### 问题2：MCP server启动失败

```bash
# 检查环境变量
echo $QUANTCODE_GROUP

# 检查配置文件
cat config.json
```

### 问题3：HumanGate不触发

```bash
# 检查risk_metrics是否计算
python -m pytest tests/test_routing.py::TestRouteHumanGate -v

# 检查router逻辑
python -c "
from runner.routing.router import route_next_step
state = {'risk_metrics': {'max_leverage': 10.0}, 'risk_profile': {}}
result = route_next_step(state)
print(result)
"
```

### 问题4：跨组流不触发

```bash
# 检查Blackboard写入
python -c "
from tools.blackboard.blackboard_service import get_blackboard_service
service = get_blackboard_service()
# 检查pending_risk_reviews
"
```

---

## 📝 下一步

测试完成后：
1. 填写DEMO_CHECKLIST.md
2. 修复发现的问题
3. 准备录屏demo
4. 更新handoff.md
